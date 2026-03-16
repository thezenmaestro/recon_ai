"""
Reconciliation Agent — pipeline orchestration and targeted AI enrichment.

The pipeline runs as hard-coded Python steps (no AI involved in orchestration).
Claude is called ONCE per run, only when HIGH severity breaks exist, to:
  - Enhance break explanations beyond what templates provide
  - Identify cross-break patterns
  - Write an executive narrative

On a clean day (zero breaks) no API call is made at all.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from observability.tracker import TrackedAnthropic
from observability.models import RunEvent
from observability.sink import get_sink

from src.agents.prompts import build_enrichment_prompt, load_system_prompt
from src.schemas.recon_output import (
    BreakExplanation,
    ClaudeEnrichmentResponse,
    ReconSummary,
)
from src.tools.break_classifier import classify_breaks
from src.tools.break_enricher import enrich_breaks_locally
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


# JSON schema for the single Claude call — used with output_config for guaranteed
# valid structure. Avoids the brittle string-splitting previously used in _extract_summary.
_ENRICHMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "break_explanations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "break_id":          {"type": "string"},
                    "ai_explanation":    {"type": "string"},
                    "recommended_action":{"type": "string"},
                    "confidence":        {"type": "string"},
                    "needs_human_review":{"type": "boolean"},
                },
                "required": ["break_id", "ai_explanation", "recommended_action",
                             "confidence", "needs_human_review"],
                "additionalProperties": False,
            },
        },
        "narrative":         {"type": "string"},
        "key_themes":        {"type": "array", "items": {"type": "string"}},
        "immediate_actions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["break_explanations", "narrative", "key_themes", "immediate_actions"],
    "additionalProperties": False,
}


# =============================================================================
# PIPELINE
# =============================================================================

def run_reconciliation(
    trade_date: str,
    run_id: str | None = None,
    triggered_by: str = "airflow",
) -> ReconSummary:
    """
    Run the full trade reconciliation for a given trade date.

    Steps 1–7 execute as direct Python function calls (no AI orchestration).
    A single Claude call is made at step 4 only when HIGH severity breaks exist.

    Args:
        trade_date: Date to reconcile in YYYY-MM-DD format.
        run_id: Optional run ID (auto-generated if not provided).
        triggered_by: 'airflow', 'manual', or 'event'.

    Returns:
        ReconSummary — structured summary of the reconciliation run.
    """
    if run_id is None:
        run_id = f"RECON-{trade_date}-{uuid.uuid4().hex[:8].upper()}"

    client = TrackedAnthropic(
        run_id=run_id,
        trade_date=trade_date,
        triggered_by=triggered_by,
    )

    write_recon_run({
        "run_id": run_id,
        "trade_date": trade_date,
        "run_timestamp": datetime.utcnow().isoformat(),
        "triggered_by": triggered_by,
        "status": "RUNNING",
    })

    print(f"[{run_id}] Starting reconciliation for {trade_date}...")

    sink = get_sink()
    run_start = datetime.utcnow()

    sink.log_run_event(RunEvent(
        run_id=run_id,
        trade_date=trade_date,
        event_type="STARTED",
        triggered_by=triggered_by,
        status="RUNNING",
        occurred_at=run_start,
    ))

    try:
        # ── Step 1: Load data ─────────────────────────────────────────────────
        print(f"[{run_id}] Loading trades and executions...")
        trades_json = load_booked_trades(trade_date)
        executions_json = load_executed_transactions(trade_date)

        trades_count = len(json.loads(trades_json).get("trades", []))
        exec_count = len(json.loads(executions_json).get("executions", []))
        print(f"[{run_id}] Loaded {trades_count:,} trades, {exec_count:,} executions.")

        # ── Step 2: Match ─────────────────────────────────────────────────────
        print(f"[{run_id}] Matching...")
        match_json = match_transactions(trades_json, executions_json)
        match_data = json.loads(match_json)
        matched_count = len(match_data.get("matched", []))
        unmatched_count = len(match_data.get("unmatched_trades", []))
        print(f"[{run_id}] {matched_count:,} matched, {unmatched_count:,} unmatched.")

        # ── Step 3: Classify breaks ───────────────────────────────────────────
        print(f"[{run_id}] Classifying breaks...")
        breaks_json = classify_breaks(match_json)
        breaks_data = json.loads(breaks_json)
        all_breaks = breaks_data.get("breaks", [])
        brk_summary = breaks_data.get("summary", {})
        total_breaks = brk_summary.get("total_breaks", 0)
        by_severity = brk_summary.get("by_severity", {})
        print(f"[{run_id}] {total_breaks} breaks — "
              f"HIGH: {by_severity.get('HIGH', 0)}, "
              f"MEDIUM: {by_severity.get('MEDIUM', 0)}, "
              f"LOW: {by_severity.get('LOW', 0)}")

        # ── Step 4: Enrich breaks ─────────────────────────────────────────────
        # 4a. Template enrichment — all breaks, no API call
        breaks_data = enrich_breaks_locally(breaks_data)
        all_breaks = breaks_data["breaks"]

        # 4b. Claude enrichment — HIGH breaks only, single API call
        high_breaks = [b for b in all_breaks if b.get("severity") == "HIGH"]
        match_stats = {
            "matched_count": matched_count,
            "by_severity": by_severity,
        }
        claude_response = _enrich_with_claude(
            client, high_breaks, all_breaks, match_stats, trade_date, run_id
        )

        # Merge Claude's enhanced explanations back into the full breaks list
        if claude_response:
            enhanced = {e["break_id"]: e for e in claude_response.get("break_explanations", [])}
            for brk in all_breaks:
                if brk["break_id"] in enhanced:
                    upd = enhanced[brk["break_id"]]
                    brk["ai_explanation"] = upd["ai_explanation"]
                    brk["recommended_action"] = upd["recommended_action"]
                    brk["confidence"] = upd["confidence"]
                    brk["needs_human_review"] = upd["needs_human_review"]

        breaks_data["breaks"] = all_breaks
        enriched_breaks_json = json.dumps(breaks_data)

        # ── Step 5: Position impact ───────────────────────────────────────────
        print(f"[{run_id}] Calculating position impact...")
        impacts_json = calculate_position_impact(enriched_breaks_json, trade_date)

        # ── Step 6: Write results ─────────────────────────────────────────────
        print(f"[{run_id}] Writing results to Snowflake...")
        write_matched_trades(match_json, run_id)
        write_breaks(enriched_breaks_json)
        write_position_impacts(impacts_json)

        # ── Step 7: Route alerts ──────────────────────────────────────────────
        print(f"[{run_id}] Routing alerts...")
        route_alerts(enriched_breaks_json, run_id, trade_date)

        # ── Build summary ─────────────────────────────────────────────────────
        summary = _build_summary(
            run_id=run_id,
            trade_date=trade_date,
            all_breaks=all_breaks,
            brk_summary=brk_summary,
            claude_response=claude_response,
        )

        duration = (datetime.utcnow() - run_start).total_seconds()
        finalise_recon_run(run_id, "COMPLETED")

        sink.log_run_event(RunEvent(
            run_id=run_id,
            trade_date=trade_date,
            event_type="COMPLETED",
            triggered_by=triggered_by,
            status="COMPLETED",
            break_count=summary.total_breaks,
            high_severity_count=summary.high_severity_count,
            total_notional_at_risk_usd=summary.total_notional_at_risk_usd,
            duration_seconds=round(duration, 2),
        ))

        print(f"[{run_id}] Done. Status: {summary.overall_status}")
        return summary

    except Exception as e:
        error_msg = str(e)
        duration = (datetime.utcnow() - run_start).total_seconds()
        print(f"[{run_id}] FAILED: {error_msg}")
        finalise_recon_run(run_id, "FAILED", error_message=error_msg)
        sink.log_run_event(RunEvent(
            run_id=run_id,
            trade_date=trade_date,
            event_type="FAILED",
            triggered_by=triggered_by,
            status="FAILED",
            error_message=error_msg,
            duration_seconds=round(duration, 2),
        ))
        raise


# =============================================================================
# CLAUDE ENRICHMENT — single call, HIGH breaks only
# =============================================================================

def _enrich_with_claude(
    client,
    high_breaks: list,
    all_breaks: list,
    match_stats: dict,
    trade_date: str,
    run_id: str,
) -> dict | None:
    """
    Make a single Claude API call to enhance HIGH severity break explanations
    and produce the cross-break narrative. Returns None on clean runs.
    """
    if not high_breaks:
        print(f"[{run_id}] No HIGH severity breaks — skipping Claude API call.")
        return None

    print(f"[{run_id}] Calling Claude to enhance {len(high_breaks)} HIGH break(s)...")

    prompt = build_enrichment_prompt(high_breaks, all_breaks, match_stats, trade_date)

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=load_system_prompt(),
        messages=[{"role": "user", "content": prompt}],
        output_config={
            "format": {
                "type": "json_schema",
                "schema": _ENRICHMENT_SCHEMA,
            }
        },
    )

    for block in response.content:
        if getattr(block, "type", None) == "text":
            try:
                return json.loads(block.text)
            except json.JSONDecodeError:
                print(f"[{run_id}] Warning: Claude enrichment response was not valid JSON. "
                      "Using template explanations for all HIGH breaks.")
                return None

    return None


# =============================================================================
# SUMMARY BUILDER
# =============================================================================

def _build_summary(
    run_id: str,
    trade_date: str,
    all_breaks: list,
    brk_summary: dict,
    claude_response: dict | None,
) -> ReconSummary:
    """Build the final ReconSummary from pipeline outputs."""
    total_breaks = brk_summary.get("total_breaks", 0)
    by_severity = brk_summary.get("by_severity", {})
    high_count = by_severity.get("HIGH", 0)
    total_notional = brk_summary.get("total_notional_at_risk_usd", 0.0)

    if total_breaks == 0:
        overall_status = "CLEAN"
    elif high_count > 0:
        overall_status = "CRITICAL"
    else:
        overall_status = "BREAKS_FOUND"

    # Narrative — from Claude if available, otherwise generated locally
    if claude_response:
        narrative = claude_response.get("narrative", "")
        key_themes = claude_response.get("key_themes", [])
        immediate_actions = claude_response.get("immediate_actions", [])
        break_explanations = [
            BreakExplanation(**e)
            for e in claude_response.get("break_explanations", [])
        ]
    else:
        narrative = _local_narrative(trade_date, total_breaks, high_count, total_notional)
        key_themes = _local_themes(all_breaks)
        immediate_actions = _local_actions(all_breaks)
        break_explanations = []

    return ReconSummary(
        run_id=run_id,
        trade_date=trade_date,
        overall_status=overall_status,
        total_breaks=total_breaks,
        high_severity_count=high_count,
        total_notional_at_risk_usd=total_notional,
        narrative=narrative,
        key_themes=key_themes,
        immediate_actions=immediate_actions,
        break_explanations=break_explanations,
    )


def _local_narrative(trade_date: str, total: int, high: int, notional: float) -> str:
    if total == 0:
        return f"All trades for {trade_date} matched cleanly. No breaks identified."
    med_low = total - high
    parts = []
    if high:
        parts.append(f"{high} HIGH severity break{'s' if high > 1 else ''} require immediate action")
    if med_low:
        parts.append(f"{med_low} lower-severity break{'s' if med_low > 1 else ''} flagged for review")
    return (
        f"{total} break{'s' if total > 1 else ''} identified for {trade_date}: "
        f"{' and '.join(parts)}. Total notional at risk: ${notional:,.0f}."
    )


def _local_themes(breaks: list) -> list[str]:
    """Identify simple patterns locally without AI."""
    themes = []
    from collections import Counter

    cp_counts = Counter(b.get("counterparty") for b in breaks if b.get("counterparty"))
    for cp, count in cp_counts.items():
        if count >= 2:
            themes.append(f"{count} breaks with {cp}")

    type_counts = Counter(b.get("break_type") for b in breaks)
    for bt, count in type_counts.most_common(3):
        if count >= 2:
            themes.append(f"{count} {bt} breaks")

    inst_counts = Counter(b.get("instrument_type") for b in breaks if b.get("instrument_type"))
    for inst, count in inst_counts.items():
        if count >= 3:
            themes.append(f"{count} breaks in {inst}")

    return themes or ["No recurring patterns identified"]


def _local_actions(breaks: list) -> list[str]:
    """Generate prioritised action list from break data without AI."""
    actions = []
    high_breaks = [b for b in breaks if b.get("severity") == "HIGH"]
    for b in high_breaks:
        action = b.get("recommended_action", "")
        if action and action not in actions:
            actions.append(action)
    return actions or ["Review all breaks before market open."]
