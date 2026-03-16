"""
Local break enricher — generates factual explanations and recommended actions
from templates using only the break's own data fields.

No AI API calls. Covers all break types deterministically.
LOW and MEDIUM severity breaks are fully handled here.
HIGH severity breaks get template explanations as a baseline; Claude then
enhances them (and only them) in a single API call per run.
"""
from __future__ import annotations


# =============================================================================
# EXPLANATION TEMPLATES
# =============================================================================

def _explain(brk: dict) -> str:
    t = brk["break_type"]
    cp = brk.get("counterparty") or "counterparty"
    tid = brk.get("trade_id") or "—"
    eid = brk.get("execution_id") or "—"
    isin = brk.get("isin") or "unknown instrument"
    direction = (brk.get("direction") or "").upper()
    b_qty = float(brk.get("booked_quantity") or 0)
    e_qty = float(brk.get("executed_quantity") or 0)
    gap = abs(float(brk.get("quantity_gap") or (b_qty - e_qty)))
    b_price = float(brk.get("booked_price") or 0)
    e_price = float(brk.get("executed_price") or 0)
    variance_pct = float(brk.get("price_variance_pct") or (
        abs(b_price - e_price) / b_price * 100 if b_price else 0
    ))
    notional = float(brk.get("notional_at_risk_usd") or 0)
    b_settle = brk.get("booked_settlement_date") or "unknown"
    e_settle = brk.get("executed_settlement_date") or "unknown"

    if t == "UNEXECUTED":
        return (
            f"No execution confirm received from {cp} for trade {tid} "
            f"({direction} {b_qty:,.0f} {isin} @ {b_price:,.4f}). "
            f"Settlement expected {b_settle}. Full notional at risk: ${notional:,.0f}."
        )

    if t == "PARTIAL_EXECUTION":
        filled_pct = (e_qty / b_qty * 100) if b_qty else 0
        remaining = b_qty - e_qty
        return (
            f"Partial fill on trade {tid} with {cp}: "
            f"{e_qty:,.0f} of {b_qty:,.0f} units executed ({filled_pct:.0f}% filled). "
            f"Remaining {remaining:,.0f} units unexecuted. "
            f"Notional gap: ${notional:,.0f}."
        )

    if t == "QTY_MISMATCH":
        return (
            f"Quantity mismatch on trade {tid} with {cp}: "
            f"booked {b_qty:,.0f} vs executed {e_qty:,.0f} units "
            f"(gap of {gap:,.0f}). Notional at risk: ${notional:,.0f}."
        )

    if t == "PRICE_MISMATCH":
        return (
            f"Price mismatch on trade {tid} with {cp}: "
            f"booked {b_price:,.4f} vs executed {e_price:,.4f} "
            f"({variance_pct:.3f}% variance). Notional at risk: ${notional:,.0f}."
        )

    if t == "SETTLEMENT_DATE_MISMATCH":
        return (
            f"Settlement date mismatch on trade {tid} with {cp}: "
            f"booked {b_settle} vs confirmed {e_settle}. "
            f"Notional at risk: ${notional:,.0f}."
        )

    if t == "ORPHAN_EXECUTION":
        return (
            f"Execution {eid} received from {cp} for {isin} "
            f"({direction} {e_qty:,.0f} @ {e_price:,.4f}) "
            f"has no corresponding booked trade. "
            f"Notional: ${notional:,.0f}."
        )

    # NEEDS_REVIEW
    return (
        f"Break on trade {tid} ({isin}) with {cp} could not be definitively "
        f"classified by the rule engine. Flagged for manual review. "
        f"Notional: ${notional:,.0f}."
    )


def _recommend(brk: dict) -> str:
    t = brk["break_type"]
    cp = brk.get("counterparty") or "counterparty"
    tid = brk.get("trade_id") or "—"
    eid = brk.get("execution_id") or "—"
    b_qty = float(brk.get("booked_quantity") or 0)
    e_qty = float(brk.get("executed_quantity") or 0)
    remaining = b_qty - e_qty

    actions = {
        "UNEXECUTED": (
            f"Contact {cp} confirms desk immediately to chase execution confirm "
            f"for trade {tid}."
        ),
        "PARTIAL_EXECUTION": (
            f"Contact {cp} for fill status on remaining {remaining:,.0f} units "
            f"for trade {tid}. Check for pending order amendments."
        ),
        "QTY_MISMATCH": (
            f"Obtain official fill report from {cp} and reconcile quantity "
            f"for trade {tid} against OMS booking."
        ),
        "PRICE_MISMATCH": (
            f"Obtain official execution report from {cp} and compare to OMS "
            f"booking for trade {tid}. Escalate to trader if variance is material."
        ),
        "SETTLEMENT_DATE_MISMATCH": (
            f"Confirm correct settlement date with {cp} and amend OMS or "
            f"execution confirm accordingly."
        ),
        "ORPHAN_EXECUTION": (
            f"Investigate whether execution {eid} from {cp} corresponds to an "
            f"unbooked or cancelled trade. Escalate to trader."
        ),
        "NEEDS_REVIEW": (
            f"Review break on trade {tid} manually and determine break type "
            f"before market open."
        ),
    }
    return actions.get(t, f"Review break on trade {tid} and take appropriate action.")


# =============================================================================
# PUBLIC API
# =============================================================================

def enrich_breaks_locally(breaks_data: dict) -> dict:
    """
    Apply template-based explanations and recommended actions to all breaks.

    Returns the same structure with ai_explanation and recommended_action
    populated for every break. These are used as-is for LOW and MEDIUM severity.
    HIGH severity breaks will be further enhanced by a single Claude API call.
    """
    for brk in breaks_data.get("breaks", []):
        brk["ai_explanation"] = _explain(brk)
        brk["recommended_action"] = _recommend(brk)
        brk["confidence"] = "HIGH"          # Template outputs are deterministic
        brk["needs_human_review"] = (brk.get("break_type") == "NEEDS_REVIEW")
        brk["enrichment_source"] = "TEMPLATE_ONLY"

    return breaks_data
