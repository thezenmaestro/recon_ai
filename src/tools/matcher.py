"""
Matching Engine — deterministic rule-based matching.
No AI here. Claude calls this as a tool and interprets the results.

Matching strategy (in order):
  1. Exact trade_id / trade_ref_id match
  2. Composite key match: isin + counterparty + direction + settlement_date
  3. Remaining unmatched records flagged as breaks
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import pandas as pd
import yaml

# Load business rules once
_RULES_PATH = os.path.join(os.path.dirname(__file__), "../../config/business_rules.yaml")
with open(_RULES_PATH) as f:
    RULES = yaml.safe_load(f)


# =============================================================================
# TOLERANCE CHECKER
# =============================================================================

def _get_tolerance(instrument_type: str) -> dict:
    tolerances = RULES["matching"]["tolerances"]
    return tolerances.get(instrument_type.upper(), tolerances["DEFAULT"])


def _within_price_tolerance(booked: float, executed: float, instrument_type: str) -> tuple[bool, float]:
    """Returns (is_within_tolerance, pct_variance)."""
    if booked == 0:
        return executed == 0, 0.0
    pct_var = abs(booked - executed) / abs(booked)
    tol = _get_tolerance(instrument_type)
    return pct_var <= tol["price_pct"], round(pct_var, 8)


def _within_qty_tolerance(booked: float, executed: float, instrument_type: str) -> tuple[bool, float]:
    """Returns (is_within_tolerance, absolute_variance)."""
    abs_var = abs(booked - executed)
    tol = _get_tolerance(instrument_type)
    return abs_var <= tol["qty_abs"], abs_var


def _within_date_tolerance(booked_date: str, executed_date: str, instrument_type: str) -> bool:
    from datetime import date as dt
    d1 = dt.fromisoformat(booked_date)
    d2 = dt.fromisoformat(executed_date)
    tol = _get_tolerance(instrument_type)
    return abs((d1 - d2).days) <= tol["date_days"]


# =============================================================================
# MAIN MATCHER
# =============================================================================

def match_transactions(trades_json: str, executions_json: str) -> str:
    """
    Match booked trades against execution confirms using the key hierarchy
    defined in business_rules.yaml.

    Args:
        trades_json: JSON string from load_booked_trades()
        executions_json: JSON string from load_executed_transactions()

    Returns:
        JSON string with keys: matched, unmatched_trades, unmatched_executions, summary
    """
    trades_data = json.loads(trades_json)
    exec_data = json.loads(executions_json)

    trades = trades_data.get("trades", [])
    executions = exec_data.get("executions", [])

    matched = []
    unmatched_trades = []
    unmatched_executions = list(executions)   # Start with all; remove as matched

    matched_exec_ids = set()

    # ── Pass 1: Primary key match (trade_id ↔ trade_ref_id) ─────────────────
    exec_by_ref = {}
    for ex in executions:
        ref = (ex.get("trade_ref_id") or "").strip()
        if ref:
            exec_by_ref.setdefault(ref, []).append(ex)

    remaining_trades = []
    for trade in trades:
        tid = trade["trade_id"].strip()
        candidates = exec_by_ref.get(tid, [])

        if candidates:
            # Take first unmatched candidate; flag extras as partial if qty differs
            best = candidates[0]
            price_ok, price_var = _within_price_tolerance(
                trade["price"], best["executed_price"], trade["instrument_type"]
            )
            qty_ok, qty_var = _within_qty_tolerance(
                trade["quantity"], best["executed_quantity"], trade["instrument_type"]
            )
            date_ok = _within_date_tolerance(
                trade["settlement_date"], best["settlement_date"], trade["instrument_type"]
            )

            if price_ok and qty_ok and date_ok:
                matched.append({
                    "match_id": str(uuid.uuid4()),
                    "trade_id": trade["trade_id"],
                    "execution_id": best["execution_id"],
                    "instrument_type": trade["instrument_type"],
                    "notional_usd": trade["notional"],
                    "qty_variance": float(qty_var),
                    "price_variance_pct": float(price_var),
                    "match_confidence": "EXACT",
                })
                matched_exec_ids.add(best["execution_id"])
            else:
                # Key matched but attributes differ → still a break
                remaining_trades.append(trade)
        else:
            remaining_trades.append(trade)

    unmatched_executions = [e for e in executions if e["execution_id"] not in matched_exec_ids]

    # ── Pass 2: Composite key match ──────────────────────────────────────────
    # Key: (isin, counterparty_normalised, direction, settlement_date)
    def _normalise_counterparty(name: str) -> str:
        return name.strip().upper().replace("  ", " ")

    exec_by_composite = {}
    for ex in unmatched_executions:
        key = (
            (ex.get("isin") or "").upper(),
            _normalise_counterparty(ex.get("counterparty", "")),
            ex.get("direction", "").upper(),
            ex.get("settlement_date", ""),
        )
        exec_by_composite.setdefault(key, []).append(ex)

    still_unmatched_trades = []
    for trade in remaining_trades:
        key = (
            (trade.get("isin") or "").upper(),
            _normalise_counterparty(trade.get("counterparty", "")),
            trade.get("direction", "").upper(),
            trade.get("settlement_date", ""),
        )
        candidates = exec_by_composite.get(key, [])

        if candidates:
            best = candidates[0]
            price_ok, price_var = _within_price_tolerance(
                trade["price"], best["executed_price"], trade["instrument_type"]
            )
            qty_ok, qty_var = _within_qty_tolerance(
                trade["quantity"], best["executed_quantity"], trade["instrument_type"]
            )

            matched.append({
                "match_id": str(uuid.uuid4()),
                "trade_id": trade["trade_id"],
                "execution_id": best["execution_id"],
                "instrument_type": trade["instrument_type"],
                "notional_usd": trade["notional"],
                "qty_variance": float(qty_var),
                "price_variance_pct": float(price_var),
                "match_confidence": "COMPOSITE",
            })
            matched_exec_ids.add(best["execution_id"])
            exec_by_composite[key].remove(best)
        else:
            still_unmatched_trades.append(trade)

    final_unmatched_executions = [e for e in unmatched_executions if e["execution_id"] not in matched_exec_ids]

    return json.dumps({
        "matched": matched,
        "unmatched_trades": still_unmatched_trades,
        "unmatched_executions": final_unmatched_executions,
        "summary": {
            "total_trades": len(trades),
            "total_executions": len(executions),
            "matched_count": len(matched),
            "unmatched_trade_count": len(still_unmatched_trades),
            "unmatched_execution_count": len(final_unmatched_executions),
        },
    })
