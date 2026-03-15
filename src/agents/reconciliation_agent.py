"""
Reconciliation Agent — the AI orchestration layer.
Uses Claude Opus 4.6 with tool use to run the full reconciliation pipeline.

This is the ONLY file that imports anthropic.
All business logic lives in src/tools/ and is called via @beta_tool.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, date

import anthropic
from anthropic import beta_tool

from src.agents.prompts import build_task_prompt, load_system_prompt
from src.schemas.recon_output import ReconSummary
from src.tools.break_classifier import classify_breaks
from src.tools.data_loader import load_booked_trades, load_executed_transactions
from src.tools.matcher import match_transactions
from src.tools.position_impact import calculate_position_impact
from src.tools.reporter import (
    finalise_recon_run,
    write_breaks,
    write_matched_trades,
    write_position_impacts,
    write_recon_run,
)
from src.notifications.alert_router import route_alerts


# =============================================================================
# TOOL DEFINITIONS — wrap each tool function with @beta_tool
# These are the ONLY functions Claude can call. Keep them thin wrappers.
# =============================================================================

@beta_tool
def tool_load_booked_trades(trade_date: str) -> str:
    """Load all booked trades from the OMS Snowflake database for a given trade date.

    Args:
        trade_date: Trade date in YYYY-MM-DD format.
    """
    return load_booked_trades(trade_date)


@beta_tool
def tool_load_executed_transactions(trade_date: str) -> str:
    """Load all execution confirms from the broker Snowflake database for a given trade date.

    Args:
        trade_date: Trade date in YYYY-MM-DD format.
    """
    return load_executed_transactions(trade_date)


@beta_tool
def tool_match_transactions(trades_json: str, executions_json: str) -> str:
    """Match booked trades against execution confirms using rule-based key hierarchy.
    Returns matched pairs and unmatched records.

    Args:
        trades_json: JSON output from tool_load_booked_trades.
        executions_json: JSON output from tool_load_executed_transactions.
    """
    return match_transactions(trades_json, executions_json)


@beta_tool
def tool_classify_breaks(match_results_json: str) -> str:
    """Classify unmatched records into typed breaks with severity scores.

    Args:
        match_results_json: JSON output from tool_match_transactions.
    """
    return classify_breaks(match_results_json)


@beta_tool
def tool_calculate_position_impact(breaks_json: str, trade_date: str) -> str:
    """Calculate open position impact, P&L exposure, and settlement/funding risk for each break.

    Args:
        breaks_json: JSON output from tool_classify_breaks (with ai_explanation populated).
        trade_date: Trade date in YYYY-MM-DD format for price/rate lookups.
    """
    return calculate_position_impact(breaks_json, trade_date)


@beta_tool
def tool_write_matched_trades(matched_json: str, run_id: str) -> str:
    """Persist matched trade pairs to the RECON_DB.RESULTS.MATCHED_TRADES Snowflake table.

    Args:
        matched_json: JSON string containing the 'matched' array from tool_match_transactions.
        run_id: The reconciliation run ID.
    """
    return write_matched_trades(matched_json, run_id)


@beta_tool
def tool_write_breaks(breaks_json: str) -> str:
    """Persist break records (including AI explanations) to RECON_DB.RESULTS.BREAKS.

    Args:
        breaks_json: JSON output from tool_classify_breaks after adding ai_explanation
                     and recommended_action to each break record.
    """
    return write_breaks(breaks_json)


@beta_tool
def tool_write_position_impacts(impacts_json: str) -> str:
    """Persist position/valuation impacts to RECON_DB.RESULTS.POSITION_IMPACT.

    Args:
        impacts_json: JSON output from tool_calculate_position_impact.
    """
    return write_position_impacts(impacts_json)


@beta_tool
def tool_route_alerts(breaks_json: str, run_id: str, trade_date: str) -> str:
    """Route break alerts to Slack, Email, and Teams based on severity and asset class.

    Args:
        breaks_json: JSON output from tool_classify_breaks with AI explanations populated.
        run_id: The reconciliation run ID.
        trade_date: Trade date in YYYY-MM-DD format.
    """
    return route_alerts(breaks_json, run_id, trade_date)


# =============================================================================
# AGENT RUNNER
# =============================================================================

ALL_TOOLS = [
    tool_load_booked_trades,
    tool_load_executed_transactions,
    tool_match_transactions,
    tool_classify_breaks,
    tool_calculate_position_impact,
    tool_write_matched_trades,
    tool_write_breaks,
    tool_write_position_impacts,
    tool_route_alerts,
]


def run_reconciliation(
    trade_date: str,
    run_id: str | None = None,
    triggered_by: str = "airflow",
) -> ReconSummary:
    """
    Run the full nightly trade reconciliation for a given trade date.

    Args:
        trade_date: Date to reconcile in YYYY-MM-DD format.
        run_id: Optional run ID (auto-generated if not provided).
        triggered_by: Who/what triggered this run — 'airflow', 'manual', 'event'.

    Returns:
        ReconSummary — structured summary of the reconciliation run.
    """
    if run_id is None:
        run_id = f"RECON-{trade_date}-{uuid.uuid4().hex[:8].upper()}"

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    # ── Register this run in Snowflake ───────────────────────────────────────
    write_recon_run({
        "run_id": run_id,
        "trade_date": trade_date,
        "run_timestamp": datetime.utcnow().isoformat(),
        "triggered_by": triggered_by,
        "status": "RUNNING",
    })

    print(f"[{run_id}] Starting reconciliation for trade date {trade_date}...")

    try:
        # ── Run the agentic loop ─────────────────────────────────────────────
        runner = client.beta.messages.tool_runner(
            model="claude-opus-4-6",
            max_tokens=8192,
            thinking={"type": "adaptive"},     # Let Claude reason through complex breaks
            system=load_system_prompt(),
            tools=ALL_TOOLS,
            messages=[{
                "role": "user",
                "content": build_task_prompt(trade_date, run_id),
            }],
        )

        final_message = None
        for message in runner:
            # Stream progress to logs
            for block in message.content:
                if hasattr(block, "type") and block.type == "text":
                    print(f"[Claude] {block.text[:200]}...")
            final_message = message

        # ── Parse structured summary from Claude's final response ────────────
        summary = _extract_summary(final_message, run_id, trade_date)

        # ── Mark run complete ────────────────────────────────────────────────
        finalise_recon_run(run_id, "COMPLETED")
        print(f"[{run_id}] Reconciliation complete. Status: {summary.overall_status}")
        return summary

    except Exception as e:
        error_msg = str(e)
        print(f"[{run_id}] Reconciliation FAILED: {error_msg}")
        finalise_recon_run(run_id, "FAILED", error_message=error_msg)
        raise


# =============================================================================
# SUMMARY EXTRACTOR
# =============================================================================

def _extract_summary(final_message, run_id: str, trade_date: str) -> ReconSummary:
    """
    Extract the ReconSummary from Claude's final message.
    Claude is instructed to return a JSON-serialisable summary — we parse it here.
    Falls back to a minimal summary if parsing fails.
    """
    if final_message is None:
        return _minimal_summary(run_id, trade_date, "Agent produced no final message.")

    for block in final_message.content:
        if hasattr(block, "type") and block.type == "text":
            text = block.text
            # Try to extract JSON from Claude's response
            try:
                # Claude may wrap the JSON in markdown code fences
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0].strip()
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0].strip()

                data = json.loads(text)
                return ReconSummary(**data)
            except Exception:
                # Return Claude's text as a narrative if JSON parsing fails
                return ReconSummary(
                    run_id=run_id,
                    trade_date=trade_date,
                    overall_status="BREAKS_FOUND",
                    total_breaks=0,
                    high_severity_count=0,
                    total_notional_at_risk_usd=0.0,
                    narrative=text[:1000],
                    key_themes=[],
                    immediate_actions=[],
                    break_explanations=[],
                )

    return _minimal_summary(run_id, trade_date, "No text block in final message.")


def _minimal_summary(run_id: str, trade_date: str, note: str) -> ReconSummary:
    return ReconSummary(
        run_id=run_id,
        trade_date=trade_date,
        overall_status="UNKNOWN",
        total_breaks=0,
        high_severity_count=0,
        total_notional_at_risk_usd=0.0,
        narrative=note,
        key_themes=[],
        immediate_actions=["Review agent logs for errors."],
        break_explanations=[],
    )
