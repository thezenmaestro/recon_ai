"""
Unit tests for src/tools/position_impact.py

Tests cover:
  - _get_fx_rate: same-currency short-circuit, fallback warning
  - calculate_position_impact: BUY vs SELL cash/securities direction
  - calculate_position_impact: P&L when last price is available vs not
  - calculate_position_impact: DV01 for BOND and DERIVATIVE instruments
  - calculate_position_impact: delta for EQUITY and DERIVATIVE
  - calculate_position_impact: portfolio summary aggregation across multiple breaks
  - calculate_position_impact: empty break list
  - calculate_position_impact: UNKNOWN/unsupported instrument type (no risk metrics)
  - calculate_position_impact: net_position_direction BUY→LONG, SELL→SHORT
  - calculate_position_impact: FX rate applied to notional
  - calculate_position_impact: impact_id and required output keys present
"""
from __future__ import annotations

import json

import pytest

from src.tools.position_impact import _get_fx_rate, calculate_position_impact


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_break(**kwargs) -> dict:
    """Minimal break dict matching what break_classifier produces."""
    defaults = {
        "break_id": "b001",
        "run_id": "run-test",
        "trade_id": "T001",
        "execution_id": None,
        "instrument_type": "EQUITY",
        "counterparty": "Goldman Sachs",
        "isin": "US1234567890",
        "direction": "BUY",
        "currency": "USD",
        "quantity_gap": 1000.0,
        "booked_price": 150.0,
        "notional_at_risk_usd": 150_000.0,
    }
    return {**defaults, **kwargs}


def _calc(breaks: list[dict], trade_date: str = "2024-01-15") -> dict:
    """Run calculate_position_impact and return the parsed result dict."""
    payload = json.dumps({"breaks": breaks})
    return json.loads(calculate_position_impact(payload, trade_date))


# ---------------------------------------------------------------------------
# _get_fx_rate — unit tests (no Snowflake, no mocking needed)
# ---------------------------------------------------------------------------

class TestGetFxRate:
    def test_same_currency_returns_one(self):
        assert _get_fx_rate("USD", "USD") == 1.0

    def test_same_currency_case_insensitive(self):
        assert _get_fx_rate("usd", "USD") == 1.0
        assert _get_fx_rate("GBP", "gbp") == 1.0

    def test_different_currency_returns_fallback(self):
        # With use_snowflake_table=false (default in template), falls back to
        # business_rules.yaml → position.fx_rate_fallback = 1.0
        rate = _get_fx_rate("GBP", "USD")
        assert isinstance(rate, float)
        assert rate == 1.0  # matches fx_rate_fallback in business_rules.yaml

    def test_different_currency_logs_warning(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="src.tools.position_impact"):
            _get_fx_rate("EUR", "USD", trade_date="2024-01-15")
        assert "FX rate lookup not implemented" in caplog.text
        assert "EUR" in caplog.text


# ---------------------------------------------------------------------------
# calculate_position_impact — BUY direction
# ---------------------------------------------------------------------------

class TestBuyDirection:
    def test_buy_cash_impact_is_positive(self):
        result = _calc([_make_break(direction="BUY", notional_at_risk_usd=100_000)])
        impact = result["position_impacts"][0]
        # BUY break → cash NOT sent → positive liquidity effect
        assert impact["settlement_cash_impact_usd"] > 0

    def test_buy_securities_impact_is_negative(self):
        result = _calc([_make_break(direction="BUY", quantity_gap=500)])
        impact = result["position_impacts"][0]
        # BUY break → securities NOT received → negative
        assert impact["securities_delivery_impact"] < 0

    def test_buy_net_position_direction_is_long(self):
        result = _calc([_make_break(direction="BUY")])
        assert result["position_impacts"][0]["net_position_direction"] == "LONG"

    def test_buy_cash_equals_notional_usd(self):
        result = _calc([_make_break(direction="BUY", notional_at_risk_usd=75_000.0)])
        impact = result["position_impacts"][0]
        # FX rate = 1.0 (same currency), so cash impact == notional_at_risk
        assert impact["settlement_cash_impact_usd"] == pytest.approx(75_000.0)

    def test_buy_securities_equals_negative_qty_gap(self):
        result = _calc([_make_break(direction="BUY", quantity_gap=300.0)])
        impact = result["position_impacts"][0]
        assert impact["securities_delivery_impact"] == pytest.approx(-300.0)


# ---------------------------------------------------------------------------
# calculate_position_impact — SELL direction
# ---------------------------------------------------------------------------

class TestSellDirection:
    def test_sell_cash_impact_is_negative(self):
        result = _calc([_make_break(direction="SELL", notional_at_risk_usd=100_000)])
        impact = result["position_impacts"][0]
        # SELL break → cash NOT received → negative
        assert impact["settlement_cash_impact_usd"] < 0

    def test_sell_securities_impact_is_positive(self):
        result = _calc([_make_break(direction="SELL", quantity_gap=500)])
        impact = result["position_impacts"][0]
        # SELL break → securities NOT delivered → positive
        assert impact["securities_delivery_impact"] > 0

    def test_sell_net_position_direction_is_short(self):
        result = _calc([_make_break(direction="SELL")])
        assert result["position_impacts"][0]["net_position_direction"] == "SHORT"

    def test_sell_cash_equals_negative_notional_usd(self):
        result = _calc([_make_break(direction="SELL", notional_at_risk_usd=50_000.0)])
        impact = result["position_impacts"][0]
        assert impact["settlement_cash_impact_usd"] == pytest.approx(-50_000.0)


# ---------------------------------------------------------------------------
# P&L impact
# ---------------------------------------------------------------------------

class TestPnlImpact:
    def test_pnl_zero_when_no_last_price(self):
        # _get_last_price returns None → pnl_impact must be 0
        result = _calc([_make_break()])
        assert result["position_impacts"][0]["pnl_impact_usd"] == 0.0

    def test_price_source_not_available_when_stub(self):
        result = _calc([_make_break()])
        assert result["position_impacts"][0]["price_source"] == "NOT_AVAILABLE"

    def test_pnl_calculated_when_last_price_provided(self, mocker):
        # Mock _get_last_price to return a price higher than booked price
        mocker.patch(
            "src.tools.position_impact._get_last_price",
            return_value=(160.0, "MOCK"),
        )
        # BUY, qty_gap=1000, booked_price=150, last=160 → gain of $10 × 1000 = $10,000
        result = _calc([_make_break(direction="BUY", quantity_gap=1000.0, booked_price=150.0)])
        pnl = result["position_impacts"][0]["pnl_impact_usd"]
        assert pnl == pytest.approx(10_000.0)

    def test_pnl_negative_for_buy_when_price_falls(self, mocker):
        mocker.patch(
            "src.tools.position_impact._get_last_price",
            return_value=(140.0, "MOCK"),
        )
        # BUY break, price dropped → missed loss = (140-150) × 1000 = -10,000
        result = _calc([_make_break(direction="BUY", quantity_gap=1000.0, booked_price=150.0)])
        pnl = result["position_impacts"][0]["pnl_impact_usd"]
        assert pnl == pytest.approx(-10_000.0)

    def test_pnl_inverted_for_sell(self, mocker):
        mocker.patch(
            "src.tools.position_impact._get_last_price",
            return_value=(160.0, "MOCK"),
        )
        # SELL break, price went up → would have received more cash: penalty = -10K
        result = _calc([_make_break(direction="SELL", quantity_gap=1000.0, booked_price=150.0)])
        pnl = result["position_impacts"][0]["pnl_impact_usd"]
        assert pnl == pytest.approx(-10_000.0)

    def test_last_known_price_captured_in_output(self, mocker):
        mocker.patch(
            "src.tools.position_impact._get_last_price",
            return_value=(175.5, "MOCK_SOURCE"),
        )
        result = _calc([_make_break()])
        impact = result["position_impacts"][0]
        assert impact["last_known_price"] == pytest.approx(175.5)
        assert impact["price_source"] == "MOCK_SOURCE"


# ---------------------------------------------------------------------------
# Risk metrics — DV01 (BOND / DERIVATIVE)
# ---------------------------------------------------------------------------

class TestDv01Metrics:
    def test_bond_has_dv01(self):
        result = _calc([_make_break(instrument_type="BOND", notional_at_risk_usd=1_000_000.0)])
        impact = result["position_impacts"][0]
        assert impact["dv01_impact_usd"] is not None
        # $1M notional × 1.0 bps_per_million = $1.00 DV01
        assert impact["dv01_impact_usd"] == pytest.approx(1.0)

    def test_derivative_has_dv01(self):
        result = _calc([_make_break(instrument_type="DERIVATIVE", notional_at_risk_usd=2_000_000.0)])
        impact = result["position_impacts"][0]
        assert impact["dv01_impact_usd"] == pytest.approx(2.0)

    def test_equity_has_no_dv01(self):
        result = _calc([_make_break(instrument_type="EQUITY")])
        assert result["position_impacts"][0]["dv01_impact_usd"] is None

    def test_fx_has_no_dv01(self):
        result = _calc([_make_break(instrument_type="FX")])
        assert result["position_impacts"][0]["dv01_impact_usd"] is None

    def test_dv01_scales_with_notional(self):
        result = _calc([_make_break(instrument_type="BOND", notional_at_risk_usd=5_000_000.0)])
        assert result["position_impacts"][0]["dv01_impact_usd"] == pytest.approx(5.0)

    def test_dv01_risk_notes_present_for_bond(self):
        result = _calc([_make_break(instrument_type="BOND", notional_at_risk_usd=1_000_000.0)])
        notes = result["position_impacts"][0]["risk_metric_notes"]
        assert notes is not None
        assert "DV01" in notes


# ---------------------------------------------------------------------------
# Risk metrics — delta (EQUITY / DERIVATIVE)
# ---------------------------------------------------------------------------

class TestDeltaMetrics:
    def test_equity_has_delta(self):
        result = _calc([_make_break(instrument_type="EQUITY", quantity_gap=250.0)])
        assert result["position_impacts"][0]["delta_impact"] == pytest.approx(250.0)

    def test_derivative_has_delta(self):
        result = _calc([_make_break(instrument_type="DERIVATIVE", quantity_gap=100.0)])
        assert result["position_impacts"][0]["delta_impact"] == pytest.approx(100.0)

    def test_bond_has_no_delta(self):
        result = _calc([_make_break(instrument_type="BOND")])
        assert result["position_impacts"][0]["delta_impact"] is None

    def test_fx_has_no_delta(self):
        result = _calc([_make_break(instrument_type="FX")])
        assert result["position_impacts"][0]["delta_impact"] is None


# ---------------------------------------------------------------------------
# Portfolio summary aggregation
# ---------------------------------------------------------------------------

class TestPortfolioSummary:
    def test_empty_breaks_returns_zero_portfolio(self):
        result = _calc([])
        summary = result["portfolio_summary"]
        assert summary["total_pnl_impact_usd"] == 0.0
        assert summary["total_cash_impact_usd"] == 0.0
        assert summary["total_securities_impact"] == 0.0
        assert summary["break_count_with_impact"] == 0

    def test_break_count_matches_input(self):
        breaks = [_make_break(break_id=f"b{i:03d}") for i in range(5)]
        result = _calc(breaks)
        assert result["portfolio_summary"]["break_count_with_impact"] == 5

    def test_cash_impact_sums_across_breaks(self):
        # Two BUY breaks: $100K + $50K = $150K total
        breaks = [
            _make_break(break_id="b001", direction="BUY", notional_at_risk_usd=100_000.0),
            _make_break(break_id="b002", direction="BUY", notional_at_risk_usd=50_000.0),
        ]
        result = _calc(breaks)
        assert result["portfolio_summary"]["total_cash_impact_usd"] == pytest.approx(150_000.0)

    def test_buy_and_sell_cash_impact_nets(self):
        # BUY $100K + SELL $100K → net $0
        breaks = [
            _make_break(break_id="b001", direction="BUY", notional_at_risk_usd=100_000.0),
            _make_break(break_id="b002", direction="SELL", notional_at_risk_usd=100_000.0),
        ]
        result = _calc(breaks)
        assert result["portfolio_summary"]["total_cash_impact_usd"] == pytest.approx(0.0)

    def test_securities_impact_sums_across_breaks(self):
        breaks = [
            _make_break(break_id="b001", direction="BUY", quantity_gap=200.0),
            _make_break(break_id="b002", direction="BUY", quantity_gap=300.0),
        ]
        result = _calc(breaks)
        # Both BUY → -200 + -300 = -500
        assert result["portfolio_summary"]["total_securities_impact"] == pytest.approx(-500.0)


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------

class TestOutputStructure:
    REQUIRED_IMPACT_KEYS = {
        "impact_id", "run_id", "break_id", "isin", "instrument_type",
        "counterparty", "net_position_change", "net_position_direction",
        "pnl_impact_usd", "settlement_cash_impact_usd",
        "securities_delivery_impact", "delta_impact", "dv01_impact_usd",
        "risk_metric_notes", "as_of_date", "last_known_price", "price_source",
    }

    def test_all_required_keys_present(self):
        result = _calc([_make_break()])
        impact = result["position_impacts"][0]
        assert self.REQUIRED_IMPACT_KEYS.issubset(set(impact.keys()))

    def test_impact_id_is_unique_across_breaks(self):
        breaks = [_make_break(break_id=f"b{i:03d}") for i in range(3)]
        result = _calc(breaks)
        ids = [imp["impact_id"] for imp in result["position_impacts"]]
        assert len(set(ids)) == 3

    def test_break_id_preserved_in_output(self):
        result = _calc([_make_break(break_id="MYBREAK")])
        assert result["position_impacts"][0]["break_id"] == "MYBREAK"

    def test_as_of_date_matches_input(self):
        result = _calc([_make_break()], trade_date="2024-06-30")
        assert result["position_impacts"][0]["as_of_date"] == "2024-06-30"

    def test_result_is_valid_json_string(self):
        payload = json.dumps({"breaks": [_make_break()]})
        raw = calculate_position_impact(payload, "2024-01-15")
        parsed = json.loads(raw)
        assert "position_impacts" in parsed
        assert "portfolio_summary" in parsed

    def test_net_position_change_equals_qty_gap(self):
        result = _calc([_make_break(quantity_gap=750.0)])
        assert result["position_impacts"][0]["net_position_change"] == pytest.approx(750.0)


# ---------------------------------------------------------------------------
# Unknown / unsupported instrument type
# ---------------------------------------------------------------------------

class TestUnknownInstrumentType:
    def test_unknown_type_produces_no_risk_metrics(self):
        result = _calc([_make_break(instrument_type="UNKNOWN")])
        impact = result["position_impacts"][0]
        assert impact["delta_impact"] is None
        assert impact["dv01_impact_usd"] is None

    def test_unknown_type_still_computes_cash_impact(self):
        result = _calc([_make_break(instrument_type="UNKNOWN", direction="BUY", notional_at_risk_usd=20_000.0)])
        assert result["position_impacts"][0]["settlement_cash_impact_usd"] == pytest.approx(20_000.0)
