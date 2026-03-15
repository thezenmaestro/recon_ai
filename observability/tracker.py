"""
TrackedAnthropic — a drop-in replacement for anthropic.Anthropic().

Intercepts every API call, measures latency, captures token usage,
estimates cost, and logs tool call events — all transparently.

Usage (the ONLY change needed in reconciliation_agent.py):

    # Before:
    client = anthropic.Anthropic()

    # After:
    from observability.tracker import TrackedAnthropic
    client = TrackedAnthropic(run_id=run_id, trade_date=trade_date, triggered_by=triggered_by)

The rest of the code — tool_runner, message creation, streaming — is unchanged.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Iterator

import anthropic

from observability.models import AIAPICallEvent, ToolCallEvent, UserActivityEvent, estimate_cost
from observability.sink import get_sink


class _TrackedBetaMessages:
    """Mirrors client.beta.messages with tracking injected."""

    def __init__(self, beta_messages, tracker: "TrackedAnthropic") -> None:
        self._beta_messages = beta_messages
        self._tracker = tracker

    def tool_runner(self, **kwargs) -> "_TrackedToolRunner":
        """Wrap the beta tool runner to intercept per-iteration API calls."""
        return _TrackedToolRunner(
            self._beta_messages.tool_runner(**kwargs),
            tracker=self._tracker,
        )

    def create(self, **kwargs) -> Any:
        """Wrap a direct beta.messages.create() call."""
        return self._tracker._tracked_create(
            lambda: self._beta_messages.create(**kwargs), **kwargs
        )

    def __getattr__(self, name: str) -> Any:
        # Pass through anything else (e.g. files, batches)
        return getattr(self._beta_messages, name)


class _TrackedToolRunner:
    """
    Wraps the anthropic beta tool_runner iterator.
    Each yielded BetaMessage corresponds to one agentic iteration (one API call).
    We capture the usage block from each message as it's yielded.
    """

    def __init__(self, runner, tracker: "TrackedAnthropic") -> None:
        self._runner = runner
        self._tracker = tracker
        self._iteration = 0

    def __iter__(self) -> Iterator[Any]:
        for message in self._runner:
            self._iteration += 1
            self._tracker._capture_message(message, iteration=self._iteration)
            yield message

    # Pass through any attributes the tool runner exposes (e.g. final_message)
    def __getattr__(self, name: str) -> Any:
        return getattr(self._runner, name)


class TrackedAnthropic:
    """
    Drop-in replacement for anthropic.Anthropic().
    Wraps the underlying client and logs all API activity to Snowflake.

    Args:
        run_id:       Current reconciliation run ID (for cross-referencing)
        trade_date:   Trade date string YYYY-MM-DD
        triggered_by: 'airflow' | 'manual' | 'event'
    """

    def __init__(
        self,
        run_id: str | None = None,
        trade_date: str | None = None,
        triggered_by: str = "airflow",
    ) -> None:
        self._client = anthropic.Anthropic()
        self._run_id = run_id
        self._trade_date = trade_date
        self._triggered_by = triggered_by
        self._sink = get_sink()

        # Expose beta.messages as a tracked wrapper
        self.beta = _TrackedBeta(self._client.beta, tracker=self)

        # Also expose messages for direct non-beta calls
        self.messages = _TrackedMessages(self._client.messages, tracker=self)

        # Log that a session started
        self._log_user_activity("SESSION_START")

    # ── Internal capture helpers ─────────────────────────────────────────────

    def _capture_message(
        self,
        message: Any,
        iteration: int = 1,
        latency_ms: int = 0,
    ) -> None:
        """Extract usage from a BetaMessage and write to Snowflake."""
        try:
            usage = getattr(message, "usage", None)
            if usage is None:
                return

            input_tokens    = getattr(usage, "input_tokens", 0) or 0
            output_tokens   = getattr(usage, "output_tokens", 0) or 0
            # Thinking tokens may be nested under cache or extended usage fields
            thinking_tokens = (
                getattr(usage, "thinking_tokens", 0)
                or getattr(usage, "cache_read_input_tokens", 0)
                or 0
            )
            model = getattr(message, "model", "claude-opus-4-6")
            stop_reason = getattr(message, "stop_reason", None)

            # Count tool_use blocks in this message
            tool_use_count = sum(
                1 for b in (getattr(message, "content", []) or [])
                if getattr(b, "type", "") == "tool_use"
            )

            had_thinking = any(
                getattr(b, "type", "") == "thinking"
                for b in (getattr(message, "content", []) or [])
            )

            cost = estimate_cost(model, input_tokens, output_tokens)

            event = AIAPICallEvent(
                run_id=self._run_id,
                trade_date=self._trade_date,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                thinking_tokens=thinking_tokens,
                total_tokens=input_tokens + output_tokens + thinking_tokens,
                cost_usd=cost,
                latency_ms=latency_ms,
                stop_reason=str(stop_reason) if stop_reason else None,
                had_thinking=had_thinking,
                tool_use_count=tool_use_count,
                triggered_by=self._triggered_by,
            )
            self._sink.log_api_call(event)

            # Log each tool_use block as a separate ToolCallEvent
            for block in (getattr(message, "content", []) or []):
                if getattr(block, "type", "") == "tool_use":
                    tool_event = ToolCallEvent(
                        api_call_id=event.call_id,
                        run_id=self._run_id,
                        trade_date=self._trade_date,
                        tool_name=getattr(block, "name", "unknown"),
                        status="SUCCESS",
                        input_size_bytes=len(str(getattr(block, "input", ""))) ,
                    )
                    self._sink.log_tool_call(tool_event)

        except Exception as e:
            print(f"[Observability] WARNING: failed to capture message usage: {e}")

    def _tracked_create(self, fn, **kwargs) -> Any:
        """Time a create() call and capture usage from the response."""
        start = time.perf_counter()
        error_msg = None
        response = None
        try:
            response = fn()
            return response
        except Exception as e:
            error_msg = str(e)
            raise
        finally:
            latency_ms = int((time.perf_counter() - start) * 1000)
            if response is not None:
                self._capture_message(response, latency_ms=latency_ms)
            elif error_msg:
                event = AIAPICallEvent(
                    run_id=self._run_id,
                    trade_date=self._trade_date,
                    model=kwargs.get("model", "claude-opus-4-6"),
                    latency_ms=latency_ms,
                    triggered_by=self._triggered_by,
                    error=error_msg,
                )
                self._sink.log_api_call(event)

    def _log_user_activity(self, action: str, details: dict | None = None) -> None:
        import os
        event = UserActivityEvent(
            user=os.environ.get("RECON_USER", "system"),
            action=action,
            source=self._triggered_by,
            run_id=self._run_id,
            trade_date=self._trade_date,
            details=str(details) if details else None,
        )
        self._sink.log_user_activity(event)

    # ── Pass-through for anything not explicitly wrapped ─────────────────────
    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


class _TrackedBeta:
    """Mirrors client.beta with messages wrapped."""
    def __init__(self, beta, tracker: TrackedAnthropic) -> None:
        self._beta = beta
        self.messages = _TrackedBetaMessages(beta.messages, tracker=tracker)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._beta, name)


class _TrackedMessages:
    """Mirrors client.messages with tracking injected."""
    def __init__(self, messages, tracker: TrackedAnthropic) -> None:
        self._messages = messages
        self._tracker = tracker

    def create(self, **kwargs) -> Any:
        return self._tracker._tracked_create(
            lambda: self._messages.create(**kwargs), **kwargs
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._messages, name)
