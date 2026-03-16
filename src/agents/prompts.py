"""
Prompt management — loads system prompt from config and builds task prompts.
All AI-facing text lives here, not scattered across tool files.
"""
from __future__ import annotations

import os
from pathlib import Path


_CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


def load_system_prompt() -> str:
    """Load the domain-knowledge system prompt from config/system_prompt.md."""
    path = _CONFIG_DIR / "system_prompt.md"
    return path.read_text(encoding="utf-8")


def build_task_prompt(trade_date: str, run_id: str) -> str:
    """
    Build the user-turn task prompt for a reconciliation run.
    Claude uses this as its initial instruction.
    """
    return f"""
Run a full trade reconciliation for trade date: {trade_date}
Reconciliation Run ID: {run_id}

Execute the following steps IN ORDER using the tools available to you:

1. LOAD DATA
   - Call load_booked_trades("{trade_date}") to get all OMS trades.
   - Call load_executed_transactions("{trade_date}") to get all broker confirms.
   - Report the counts: how many trades, how many executions.

2. MATCH
   - Call match_transactions(trades_json, executions_json) with the results from step 1.
   - Report: how many matched, how many unmatched trades, how many orphan executions.

3. CLASSIFY BREAKS
   - Call classify_breaks(match_results_json) with the match output.
   - Review every break. For each break, add:
       * ai_explanation: a clear, specific explanation of what went wrong
         (include trade ID, counterparty, amounts, and why you believe it's a break)
       * recommended_action: the single most important next step for the ops team

4. CALCULATE POSITION IMPACT
   - Call calculate_position_impact(breaks_json, "{trade_date}") with the classified breaks.
   - Summarise the total P&L impact, cash funding impact, and securities delivery exposure.

5. WRITE RESULTS
   - Call write_matched_trades(matched_json, "{run_id}") to persist matches.
   - Call write_breaks(breaks_json_with_explanations) to persist breaks.
   - Call write_position_impacts(impacts_json) to persist position impacts.

6. SEND ALERTS
   - Call route_alerts(breaks_json, "{run_id}", "{trade_date}") to dispatch notifications.

7. PRODUCE FINAL SUMMARY
   - Return a structured ReconSummary with:
     * overall_status: CLEAN (0 breaks), BREAKS_FOUND (breaks but none HIGH), or CRITICAL (any HIGH break)
     * narrative: 2–3 sentence plain English summary for senior management
     * key_themes: list of recurring patterns you observed
     * immediate_actions: ordered list of things ops must do before market open

IMPORTANT:
- Do not skip steps.
- If any tool returns an error, log it and continue to the next step where possible.
- Be specific in explanations — use actual trade IDs, amounts, and counterparty names.
- Flag anything uncertain as NEEDS_REVIEW rather than guessing.
"""


def build_enrichment_prompt(high_breaks: list, all_breaks: list, match_stats: dict, trade_date: str) -> str:
    """
    Focused prompt for the single Claude API call per run.

    The pipeline has already:
    - Loaded, matched, and classified all breaks
    - Applied template explanations to every break

    Claude's job here is narrowly scoped:
    1. Enhance explanations for HIGH severity breaks (templates are the baseline)
    2. Identify cross-break patterns across ALL breaks
    3. Write a 2-3 sentence executive narrative
    4. Produce an ordered list of immediate actions

    LOW and MEDIUM breaks are NOT sent to Claude — their template explanations
    are sufficient and they do not require AI enrichment.
    """
    import json

    high_breaks_json = json.dumps(high_breaks, indent=2, default=str)
    all_break_types = [b.get("break_type") for b in all_breaks]
    all_counterparties = [b.get("counterparty") for b in all_breaks if b.get("counterparty")]
    total_notional = sum(b.get("notional_at_risk_usd", 0) for b in all_breaks)
    by_severity = match_stats.get("by_severity", {})

    return f"""Trade date: {trade_date}

RECONCILIATION RESULTS — SUMMARY
  Matched:       {match_stats.get("matched_count", 0):,} pairs
  Total breaks:  {len(all_breaks)} ({by_severity.get("HIGH", 0)} HIGH / {by_severity.get("MEDIUM", 0)} MEDIUM / {by_severity.get("LOW", 0)} LOW)
  Total notional at risk: ${total_notional:,.0f}
  Break types seen: {", ".join(sorted(set(all_break_types)))}
  Counterparties involved: {", ".join(sorted(set(all_counterparties)))}

HIGH SEVERITY BREAKS (requiring your analysis):
{high_breaks_json}

YOUR TASKS:
1. For each HIGH severity break above, enhance the ai_explanation with any additional
   context, risk implications, or nuance beyond the template. Be specific — use the
   actual trade IDs, amounts, and counterparty names already present.

2. Identify patterns across ALL {len(all_breaks)} breaks (not just HIGH) — e.g. same
   counterparty appearing multiple times, same break type clustering, instrument-level
   concentration.

3. Write a 2-3 sentence narrative suitable for senior management. Lead with the most
   critical issue.

4. List immediate actions ops must complete before market open, ordered by urgency.

Return your response as JSON matching the schema exactly. Every HIGH break in the list
above must have a corresponding entry in break_explanations.
"""


def build_break_explanation_prompt(breaks_json: str) -> str:
    """
    Prompt used when Claude is asked to enrich breaks with explanations only
    (e.g. for a re-explanation run without re-running the full pipeline).
    """
    return f"""
The following breaks have been identified by the automated reconciliation engine.
For each break, provide:
  1. A clear, specific ai_explanation (1–2 sentences, mention trade ID and amounts)
  2. A recommended_action for the operations team

Breaks:
{breaks_json}

Return your response as a JSON array of objects with fields:
  break_id, ai_explanation, recommended_action, confidence, needs_human_review
"""
