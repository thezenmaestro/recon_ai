"""
Unit tests for src/tools/break_classifier.py

Tests cover:
  - _classify_severity: notional thresholds, UNEXECUTED always HIGH
  - classify_breaks: unmatched trades → UNEXECUTED breaks
  - classify_breaks: orphan executions → ORPHAN_EXECUTION breaks
  - Output structure and summary counts
  - Edge cases: zero notional, missing fields
"""
import json

import pytest

from src.tools.break_classifier import _classify_severity, classify_breaks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_match_result(unmatched_trades=None, unmatched_executions=None, run_id="run-test"):
    return json.dumps({
        "matched": [],
        "unmatched_trades": unmatched_trades or [],
        "unmatched_executions": unmatched_executions or [],
        "run_id": run_id,
        "summary": {},
    })


def _make_trade(**kwargs):
    defaults = {
        "trade_id": "T001",
        "isin": "US1234567890",
        "instrument_type": "EQUITY",
        "counterparty": "Goldman Sachs",
        "direction": "BUY",
        "quantity": 1000.0,
        "price": 100.0,
        "notional": 100000.0,
        "currency": "USD",
        "trade_date": "2024-01-15",
        "settlement_date": "2024-01-17",
        "status": "CONFIRMED",
    }
    return {**defaults, **kwargs}


def _make_orphan_exec(**kwargs):
    defaults = {
        "execution_id": "E001",
        "trade_ref_id": "",
        "isin": "US1234567890",
        "instrument_type": "EQUITY",
        "counterparty": "Morgan Stanley",
        "direction": "SELL",
        "executed_quantity": 500.0,
        "executed_price": 95.0,
        "executed_notional": 47500.0,
        "currency": "USD",
        "execution_date": "2024-01-15",
        "settlement_date": "2024-01-17",
        "status": "CONFIRMED",
    }
    return {**defaults, **kwargs}


# ---------------------------------------------------------------------------
# _classify_severity
# ---------------------------------------------------------------------------

class TestClassifySeverity:
    def test_unexecuted_always_high(self):
        # Regardless of notional, UNEXECUTED is always HIGH
        assert _classify_severity(0.0, "UNEXECUTED") == "HIGH"
        assert _classify_severity(1.0, "UNEXECUTED") == "HIGH"
        assert _classify_severity(1_000_000.0, "UNEXECUTED") == "HIGH"

    def test_zero_notional_is_low(self):
        assert _classify_severity(0.0, "QTY_MISMATCH") == "LOW"

    def test_low_notional(self):
        result = _classify_severity(100.0, "PRICE_MISMATCH")
        assert result in ("LOW", "MEDIUM", "HIGH")

    def test_high_notional(self):
        # 10M USD should be HIGH for any non-UNEXECUTED break
        result = _classify_severity(10_000_000.0, "PRICE_MISMATCH")
        assert result == "HIGH"

    def test_returns_valid_severity(self):
        for break_type in ("QTY_MISMATCH", "PRICE_MISMATCH", "SETTLEMENT_DATE_MISMATCH",
                           "PARTIAL_EXECUTION", "ORPHAN_EXECUTION", "NEEDS_REVIEW"):
            result = _classify_severity(50_000.0, break_type)
            assert result in ("LOW", "MEDIUM", "HIGH"), f"Unexpected severity: {result}"


# ---------------------------------------------------------------------------
# classify_breaks — unmatched trades
# ---------------------------------------------------------------------------

class TestClassifyBreaksUnmatchedTrades:
    def test_empty_input(self):
        result = json.loads(classify_breaks(_make_match_result()))
        assert result["breaks"] == []
        assert result["summary"]["total_breaks"] == 0

    def test_single_unmatched_trade_creates_break(self):
        result = json.loads(classify_breaks(
            _make_match_result(unmatched_trades=[_make_trade()])
        ))
        assert len(result["breaks"]) == 1
        brk = result["breaks"][0]
        assert brk["break_type"] == "UNEXECUTED"
        assert brk["severity"] == "HIGH"
        assert brk["trade_id"] == "T001"
        assert brk["execution_id"] is None

    def test_break_has_required_fields(self):
        result = json.loads(classify_breaks(
            _make_match_result(unmatched_trades=[_make_trade()])
        ))
        brk = result["breaks"][0]
        required = {
            "break_id", "run_id", "trade_id", "execution_id",
            "instrument_type", "counterparty", "isin", "direction",
            "break_type", "severity", "booked_quantity", "executed_quantity",
            "quantity_gap", "booked_price", "notional_at_risk_usd",
        }
        for field in required:
            assert field in brk, f"Missing required field: {field}"

    def test_break_id_is_unique(self):
        trades = [_make_trade(trade_id=f"T{i:03d}") for i in range(5)]
        result = json.loads(classify_breaks(
            _make_match_result(unmatched_trades=trades)
        ))
        ids = [b["break_id"] for b in result["breaks"]]
        assert len(ids) == len(set(ids)), "break_ids should be unique"

    def test_notional_at_risk_set_from_trade(self):
        trade = _make_trade(notional=250_000.0)
        result = json.loads(classify_breaks(
            _make_match_result(unmatched_trades=[trade])
        ))
        assert result["breaks"][0]["notional_at_risk_usd"] == 250_000.0

    def test_quantity_gap_equals_booked_quantity(self):
        trade = _make_trade(quantity=750.0)
        result = json.loads(classify_breaks(
            _make_match_result(unmatched_trades=[trade])
        ))
        brk = result["breaks"][0]
        assert brk["quantity_gap"] == 750.0
        assert brk["executed_quantity"] == 0.0


# ---------------------------------------------------------------------------
# classify_breaks — orphan executions
# ---------------------------------------------------------------------------

class TestClassifyBreaksOrphanExecutions:
    def test_orphan_execution_creates_break(self):
        result = json.loads(classify_breaks(
            _make_match_result(unmatched_executions=[_make_orphan_exec()])
        ))
        assert len(result["breaks"]) == 1
        brk = result["breaks"][0]
        assert brk["break_type"] == "ORPHAN_EXECUTION"
        assert brk["trade_id"] is None
        assert brk["execution_id"] == "E001"

    def test_orphan_count_in_output(self):
        execs = [_make_orphan_exec(execution_id=f"E{i:03d}") for i in range(3)]
        result = json.loads(classify_breaks(
            _make_match_result(unmatched_executions=execs)
        ))
        assert result["orphan_execution_count"] == 3

    def test_mix_of_unmatched_and_orphans(self):
        result = json.loads(classify_breaks(
            _make_match_result(
                unmatched_trades=[_make_trade()],
                unmatched_executions=[_make_orphan_exec()],
            )
        ))
        assert result["summary"]["total_breaks"] == 2
        types = {b["break_type"] for b in result["breaks"]}
        assert types == {"UNEXECUTED", "ORPHAN_EXECUTION"}


# ---------------------------------------------------------------------------
# classify_breaks — summary
# ---------------------------------------------------------------------------

class TestClassifyBreaksSummary:
    def test_summary_structure(self):
        result = json.loads(classify_breaks(_make_match_result()))
        summary = result["summary"]
        assert "total_breaks" in summary
        assert "by_severity" in summary
        assert "total_notional_at_risk_usd" in summary

    def test_severity_counts_in_summary(self):
        # Three HIGH (UNEXECUTED) trades
        trades = [_make_trade(trade_id=f"T{i}", notional=500_000.0) for i in range(3)]
        result = json.loads(classify_breaks(
            _make_match_result(unmatched_trades=trades)
        ))
        assert result["summary"]["by_severity"]["HIGH"] == 3

    def test_total_notional_sums_correctly(self):
        trades = [_make_trade(trade_id=f"T{i}", notional=100_000.0) for i in range(4)]
        result = json.loads(classify_breaks(
            _make_match_result(unmatched_trades=trades)
        ))
        assert result["summary"]["total_notional_at_risk_usd"] == 400_000.0
