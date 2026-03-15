"""
Break Classifier — determines break type and severity for each unmatched record.
Called by the reconciliation agent after matching.
No AI here — pure rule evaluation. Claude then adds narrative explanations.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import date

import yaml

_RULES_PATH = os.path.join(os.path.dirname(__file__), "../../config/business_rules.yaml")
with open(_RULES_PATH) as f:
    RULES = yaml.safe_load(f)


# =============================================================================
# SEVERITY CLASSIFICATION
# =============================================================================

def _classify_severity(notional_usd: float, break_type: str) -> str:
    """
    Classify severity based on notional (USD) and break type.
    UNEXECUTED trades are always HIGH regardless of amount.
    """
    thresholds = RULES["breaks"]["severity_thresholds"]

    if break_type == "UNEXECUTED":
        return "HIGH"

    if notional_usd < thresholds["LOW"]["max_notional"]:
        return "LOW"
    elif notional_usd < thresholds["MEDIUM"]["max_notional"]:
        return "MEDIUM"
    else:
        return "HIGH"


# =============================================================================
# BREAK TYPE DETECTION
# =============================================================================

def _detect_break_type(trade: dict, execution: dict | None) -> str:
    """Given a trade and its (possibly None) execution, determine the break type."""
    if execution is None:
        return "UNEXECUTED"

    # Check quantity gap
    qty_gap = abs(trade["quantity"] - execution["executed_quantity"])
    if qty_gap > 0:
        exec_qty = execution["executed_quantity"]
        if exec_qty > 0 and exec_qty < trade["quantity"]:
            return "PARTIAL_EXECUTION"
        return "QTY_MISMATCH"

    # Check price
    from src.tools.matcher import _within_price_tolerance
    price_ok, _ = _within_price_tolerance(
        trade["price"], execution["executed_price"], trade["instrument_type"]
    )
    if not price_ok:
        return "PRICE_MISMATCH"

    # Check settlement date
    if trade.get("settlement_date") and execution.get("settlement_date"):
        if trade["settlement_date"] != execution["settlement_date"]:
            return "SETTLEMENT_DATE_MISMATCH"

    return "NEEDS_REVIEW"


# =============================================================================
# MAIN CLASSIFIER
# =============================================================================

def classify_breaks(match_results_json: str) -> str:
    """
    Classify all unmatched trades and produce structured BreakRecord payloads.
    Also flags unmatched executions (orphan confirms — executed but no booked trade).

    Args:
        match_results_json: JSON output from match_transactions()

    Returns:
        JSON string with 'breaks' list and 'summary'.
    """
    data = json.loads(match_results_json)
    unmatched_trades = data.get("unmatched_trades", [])
    unmatched_executions = data.get("unmatched_executions", [])
    run_id = data.get("run_id", str(uuid.uuid4()))

    breaks = []

    # ── Breaks from unmatched booked trades ──────────────────────────────────
    for trade in unmatched_trades:
        break_type = "UNEXECUTED"
        notional = float(trade.get("notional", 0))
        severity = _classify_severity(notional, break_type)

        breaks.append({
            "break_id": str(uuid.uuid4()),
            "run_id": run_id,
            "trade_id": trade["trade_id"],
            "execution_id": None,
            "instrument_type": trade.get("instrument_type", "UNKNOWN"),
            "counterparty": trade.get("counterparty", ""),
            "isin": trade.get("isin"),
            "direction": trade.get("direction", ""),
            "break_type": break_type,
            "severity": severity,
            "booked_quantity": float(trade.get("quantity", 0)),
            "executed_quantity": 0.0,
            "quantity_gap": float(trade.get("quantity", 0)),
            "booked_price": float(trade.get("price", 0)),
            "executed_price": None,
            "price_variance_pct": None,
            "notional_at_risk_usd": notional,
            "booked_settlement_date": trade.get("settlement_date"),
            "executed_settlement_date": None,
            # ai_explanation and recommended_action filled by Claude
        })

    # ── Orphan executions (executed but no matching booked trade) ────────────
    # These are flagged separately — could indicate rogue trades or data issues
    orphan_breaks = []
    for ex in unmatched_executions:
        notional = float(ex.get("executed_notional", 0))
        severity = _classify_severity(notional, "UNEXECUTED")
        orphan_breaks.append({
            "break_id": str(uuid.uuid4()),
            "run_id": run_id,
            "trade_id": None,
            "execution_id": ex["execution_id"],
            "instrument_type": ex.get("instrument_type", "UNKNOWN"),
            "counterparty": ex.get("counterparty", ""),
            "isin": ex.get("isin"),
            "direction": ex.get("direction", ""),
            "break_type": "ORPHAN_EXECUTION",   # Executed but no booked trade
            "severity": severity,
            "booked_quantity": 0.0,
            "executed_quantity": float(ex.get("executed_quantity", 0)),
            "quantity_gap": float(ex.get("executed_quantity", 0)),
            "booked_price": 0.0,
            "executed_price": float(ex.get("executed_price", 0)),
            "price_variance_pct": None,
            "notional_at_risk_usd": notional,
            "booked_settlement_date": None,
            "executed_settlement_date": ex.get("settlement_date"),
        })

    all_breaks = breaks + orphan_breaks

    # Summary by severity
    by_severity = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for b in all_breaks:
        by_severity[b["severity"]] = by_severity.get(b["severity"], 0) + 1

    total_notional = sum(b["notional_at_risk_usd"] for b in all_breaks)

    return json.dumps({
        "breaks": all_breaks,
        "orphan_execution_count": len(orphan_breaks),
        "summary": {
            "total_breaks": len(all_breaks),
            "by_severity": by_severity,
            "total_notional_at_risk_usd": round(total_notional, 2),
        },
    })
