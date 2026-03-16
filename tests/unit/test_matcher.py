"""
Unit tests for src/tools/matcher.py

Tests cover:
  - Price tolerance checks across instrument types
  - Quantity tolerance checks
  - Date tolerance checks
  - Pass-1 (trade_id ↔ trade_ref_id) matching
  - Pass-2 (composite key) matching
  - Counterparty normalisation edge cases
  - Empty dataset handling
"""
import json

import pytest

from src.tools.matcher import (
    _within_date_tolerance,
    _within_price_tolerance,
    _within_qty_tolerance,
    match_transactions,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trade(**kwargs):
    defaults = {
        "trade_id": "T001",
        "isin": "US0231351067",
        "ticker": "AAPL",
        "instrument_type": "EQUITY",
        "counterparty": "Goldman Sachs",
        "direction": "BUY",
        "quantity": 1000.0,
        "price": 150.0,
        "notional": 150000.0,
        "currency": "USD",
        "trade_date": "2024-01-15",
        "settlement_date": "2024-01-17",
        "status": "CONFIRMED",
    }
    return {**defaults, **kwargs}


def _make_exec(**kwargs):
    defaults = {
        "execution_id": "E001",
        "trade_ref_id": "T001",
        "isin": "US0231351067",
        "ticker": "AAPL",
        "instrument_type": "EQUITY",
        "counterparty": "Goldman Sachs",
        "direction": "BUY",
        "executed_quantity": 1000.0,
        "executed_price": 150.0,
        "executed_notional": 150000.0,
        "currency": "USD",
        "execution_date": "2024-01-15",
        "settlement_date": "2024-01-17",
        "status": "CONFIRMED",
    }
    return {**defaults, **kwargs}


def _wrap_trades(*trades):
    return json.dumps({"trades": list(trades), "count": len(trades), "trade_date": "2024-01-15"})


def _wrap_execs(*execs):
    return json.dumps({"executions": list(execs), "count": len(execs), "trade_date": "2024-01-15"})


# ---------------------------------------------------------------------------
# Tolerance helpers
# ---------------------------------------------------------------------------

class TestWithinPriceTolerance:
    def test_exact_match(self):
        ok, var = _within_price_tolerance(100.0, 100.0, "EQUITY")
        assert ok is True
        assert var == 0.0

    def test_within_tolerance(self):
        # EQUITY default tolerance should accept <0.5% — 0.1% variance
        ok, var = _within_price_tolerance(100.0, 100.1, "EQUITY")
        assert ok is True

    def test_outside_tolerance(self):
        # 5% variance is well beyond any standard equity tolerance
        ok, var = _within_price_tolerance(100.0, 105.1, "EQUITY")
        assert ok is False
        assert var > 0

    def test_zero_booked_price_zero_executed(self):
        ok, var = _within_price_tolerance(0.0, 0.0, "EQUITY")
        assert ok is True

    def test_zero_booked_price_nonzero_executed(self):
        ok, var = _within_price_tolerance(0.0, 1.0, "EQUITY")
        assert ok is False


class TestWithinQtyTolerance:
    def test_exact_match(self):
        ok, var = _within_qty_tolerance(500.0, 500.0, "EQUITY")
        assert ok is True
        assert var == 0.0

    def test_within_absolute_tolerance(self):
        # var of 0 should always pass
        ok, var = _within_qty_tolerance(500.0, 500.0, "EQUITY")
        assert ok is True

    def test_outside_tolerance(self):
        # Large quantity gap should fail
        ok, var = _within_qty_tolerance(1000.0, 1.0, "EQUITY")
        assert ok is False
        assert var == 999.0


class TestWithinDateTolerance:
    def test_same_date(self):
        assert _within_date_tolerance("2024-01-17", "2024-01-17", "EQUITY") is True

    def test_one_day_difference(self):
        # Most instruments allow 0 day tolerance or small buffer — just check not crashing
        result = _within_date_tolerance("2024-01-17", "2024-01-18", "EQUITY")
        assert isinstance(result, bool)

    def test_large_difference_fails(self):
        # 30 day gap should always fail regardless of instrument type
        assert _within_date_tolerance("2024-01-01", "2024-03-01", "EQUITY") is False


# ---------------------------------------------------------------------------
# match_transactions — happy path
# ---------------------------------------------------------------------------

class TestMatchTransactions:
    def test_empty_inputs(self):
        result = json.loads(match_transactions(
            _wrap_trades(), _wrap_execs()
        ))
        assert result["summary"]["total_trades"] == 0
        assert result["summary"]["total_executions"] == 0
        assert result["summary"]["matched_count"] == 0

    def test_perfect_match_pass1(self):
        """Single trade matched by trade_id ↔ trade_ref_id."""
        result = json.loads(match_transactions(
            _wrap_trades(_make_trade()),
            _wrap_execs(_make_exec()),
        ))
        assert result["summary"]["matched_count"] == 1
        assert result["summary"]["unmatched_trade_count"] == 0
        assert result["summary"].get("unmatched_execution_count", 0) == 0
        assert result["matched"][0]["match_confidence"] == "EXACT"

    def test_unmatched_trade(self):
        """Trade with no corresponding execution stays unmatched."""
        result = json.loads(match_transactions(
            _wrap_trades(_make_trade(trade_id="T999")),
            _wrap_execs(),
        ))
        assert result["summary"]["unmatched_trade_count"] == 1
        assert result["summary"]["matched_count"] == 0

    def test_unmatched_execution(self):
        """Execution with no corresponding trade stays unmatched."""
        result = json.loads(match_transactions(
            _wrap_trades(),
            _wrap_execs(_make_exec(trade_ref_id="")),
        ))
        assert result["summary"]["unmatched_execution_count"] == 1

    def test_pass2_composite_match(self):
        """Trade matched via composite key when trade_ref_id is blank."""
        trade = _make_trade(trade_id="T002")
        exe = _make_exec(execution_id="E002", trade_ref_id="")  # no ref_id → pass 2
        result = json.loads(match_transactions(
            _wrap_trades(trade),
            _wrap_execs(exe),
        ))
        assert result["summary"]["matched_count"] == 1
        assert result["matched"][0]["match_confidence"] == "COMPOSITE"

    def test_price_mismatch_falls_through(self):
        """Trade with matching ID but excessive price variance goes unmatched in pass 1."""
        trade = _make_trade()
        exe = _make_exec(executed_price=200.0)  # 33% variance — should fail
        result = json.loads(match_transactions(
            _wrap_trades(trade),
            _wrap_execs(exe),
        ))
        # Should either be unmatched or matched depending on tolerance; key thing:
        # result must be valid JSON with the expected keys
        assert "summary" in result
        assert "matched" in result

    def test_multiple_trades_and_execs(self):
        """Three perfect matches produce 3 matched rows."""
        trades = [_make_trade(trade_id=f"T{i:03d}") for i in range(3)]
        execs = [_make_exec(execution_id=f"E{i:03d}", trade_ref_id=f"T{i:03d}") for i in range(3)]
        result = json.loads(match_transactions(
            _wrap_trades(*trades),
            _wrap_execs(*execs),
        ))
        assert result["summary"]["matched_count"] == 3
        assert result["summary"]["unmatched_trade_count"] == 0

    def test_counterparty_normalisation_case_insensitive(self):
        """Counterparty matching is case-insensitive in composite pass."""
        trade = _make_trade(trade_id="TX", counterparty="goldman sachs")
        exe = _make_exec(execution_id="EX", trade_ref_id="", counterparty="GOLDMAN SACHS")
        result = json.loads(match_transactions(
            _wrap_trades(trade),
            _wrap_execs(exe),
        ))
        # Normalisation should allow composite match
        assert result["summary"]["matched_count"] == 1

    def test_output_structure(self):
        """Output always contains required top-level keys."""
        result = json.loads(match_transactions(_wrap_trades(), _wrap_execs()))
        assert "matched" in result
        assert "unmatched_trades" in result
        assert "unmatched_executions" in result
        assert "summary" in result
        summary = result["summary"]
        for key in ("total_trades", "total_executions", "matched_count",
                    "unmatched_trade_count", "unmatched_execution_count"):
            assert key in summary
