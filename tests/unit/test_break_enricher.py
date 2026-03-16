"""
Unit tests for src/tools/break_enricher.py

Tests cover:
  - _explain() template output for every break type
  - _recommend() action text for every break type
  - enrich_breaks_locally() field additions and mutations
  - Edge cases: missing/None fields, zero values
"""
import pytest

from src.tools.break_enricher import _explain, _recommend, enrich_breaks_locally


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_break(**kwargs):
    defaults = {
        "break_id": "b001",
        "run_id": "run-test",
        "trade_id": "T001",
        "execution_id": "E001",
        "instrument_type": "EQUITY",
        "counterparty": "Goldman Sachs",
        "isin": "US1234567890",
        "direction": "BUY",
        "break_type": "UNEXECUTED",
        "severity": "HIGH",
        "booked_quantity": 1000.0,
        "executed_quantity": 0.0,
        "quantity_gap": 1000.0,
        "booked_price": 150.0,
        "executed_price": None,
        "price_variance_pct": None,
        "notional_at_risk_usd": 150_000.0,
        "booked_settlement_date": "2024-01-17",
        "executed_settlement_date": None,
    }
    return {**defaults, **kwargs}


ALL_BREAK_TYPES = [
    "UNEXECUTED",
    "PARTIAL_EXECUTION",
    "QTY_MISMATCH",
    "PRICE_MISMATCH",
    "SETTLEMENT_DATE_MISMATCH",
    "ORPHAN_EXECUTION",
    "NEEDS_REVIEW",
]


# ---------------------------------------------------------------------------
# _explain
# ---------------------------------------------------------------------------

class TestExplain:
    @pytest.mark.parametrize("break_type", ALL_BREAK_TYPES)
    def test_explain_returns_string(self, break_type):
        brk = _make_break(break_type=break_type)
        result = _explain(brk)
        assert isinstance(result, str)
        assert len(result) > 10

    def test_unexecuted_mentions_trade_id(self):
        brk = _make_break(break_type="UNEXECUTED", trade_id="T999")
        assert "T999" in _explain(brk)

    def test_unexecuted_mentions_counterparty(self):
        brk = _make_break(break_type="UNEXECUTED", counterparty="Barclays")
        assert "Barclays" in _explain(brk)

    def test_partial_execution_shows_fill_pct(self):
        brk = _make_break(
            break_type="PARTIAL_EXECUTION",
            booked_quantity=1000.0,
            executed_quantity=500.0,
        )
        result = _explain(brk)
        # Should mention 50% filled
        assert "50%" in result

    def test_qty_mismatch_shows_gap(self):
        brk = _make_break(
            break_type="QTY_MISMATCH",
            booked_quantity=1000.0,
            executed_quantity=900.0,
            quantity_gap=100.0,
        )
        assert "100" in _explain(brk)

    def test_price_mismatch_shows_prices(self):
        brk = _make_break(
            break_type="PRICE_MISMATCH",
            booked_price=100.0,
            executed_price=105.0,
        )
        result = _explain(brk)
        assert "100" in result
        assert "105" in result

    def test_settlement_date_mismatch_shows_dates(self):
        brk = _make_break(
            break_type="SETTLEMENT_DATE_MISMATCH",
            booked_settlement_date="2024-01-17",
            executed_settlement_date="2024-01-18",
        )
        result = _explain(brk)
        assert "2024-01-17" in result
        assert "2024-01-18" in result

    def test_orphan_execution_mentions_execution_id(self):
        brk = _make_break(break_type="ORPHAN_EXECUTION", execution_id="ORPHAN-99")
        assert "ORPHAN-99" in _explain(brk)

    def test_none_fields_do_not_raise(self):
        """Missing optional fields should not raise — use safe defaults."""
        brk = _make_break(
            break_type="UNEXECUTED",
            trade_id=None,
            counterparty=None,
            isin=None,
        )
        result = _explain(brk)
        assert isinstance(result, str)

    def test_zero_notional(self):
        brk = _make_break(break_type="UNEXECUTED", notional_at_risk_usd=0.0)
        result = _explain(brk)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _recommend
# ---------------------------------------------------------------------------

class TestRecommend:
    @pytest.mark.parametrize("break_type", ALL_BREAK_TYPES)
    def test_recommend_returns_string(self, break_type):
        brk = _make_break(break_type=break_type)
        result = _recommend(brk)
        assert isinstance(result, str)
        assert len(result) > 10

    def test_unexecuted_action_mentions_counterparty(self):
        brk = _make_break(break_type="UNEXECUTED", counterparty="Citi")
        assert "Citi" in _recommend(brk)

    def test_partial_execution_mentions_remaining(self):
        brk = _make_break(
            break_type="PARTIAL_EXECUTION",
            booked_quantity=1000.0,
            executed_quantity=400.0,
        )
        result = _recommend(brk)
        assert "600" in result  # remaining = 600

    def test_unknown_break_type_returns_fallback(self):
        brk = _make_break(break_type="FUTURE_UNKNOWN_TYPE")
        result = _recommend(brk)
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# enrich_breaks_locally
# ---------------------------------------------------------------------------

class TestEnrichBreaksLocally:
    def test_empty_breaks(self):
        data = {"breaks": []}
        result = enrich_breaks_locally(data)
        assert result["breaks"] == []

    def test_adds_ai_explanation(self):
        data = {"breaks": [_make_break()]}
        result = enrich_breaks_locally(data)
        assert "ai_explanation" in result["breaks"][0]
        assert isinstance(result["breaks"][0]["ai_explanation"], str)

    def test_adds_recommended_action(self):
        data = {"breaks": [_make_break()]}
        result = enrich_breaks_locally(data)
        assert "recommended_action" in result["breaks"][0]
        assert isinstance(result["breaks"][0]["recommended_action"], str)

    def test_adds_confidence(self):
        data = {"breaks": [_make_break()]}
        result = enrich_breaks_locally(data)
        assert result["breaks"][0]["confidence"] == "HIGH"

    def test_adds_enrichment_source(self):
        data = {"breaks": [_make_break()]}
        result = enrich_breaks_locally(data)
        assert result["breaks"][0]["enrichment_source"] == "TEMPLATE_ONLY"

    def test_needs_human_review_set_for_needs_review_type(self):
        data = {"breaks": [_make_break(break_type="NEEDS_REVIEW")]}
        result = enrich_breaks_locally(data)
        assert result["breaks"][0]["needs_human_review"] is True

    def test_needs_human_review_false_for_other_types(self):
        for break_type in ("UNEXECUTED", "PRICE_MISMATCH", "QTY_MISMATCH"):
            data = {"breaks": [_make_break(break_type=break_type)]}
            result = enrich_breaks_locally(data)
            assert result["breaks"][0]["needs_human_review"] is False

    def test_returns_same_structure(self):
        """enrich_breaks_locally should return the input dict (mutated in place)."""
        data = {"breaks": [_make_break()], "summary": {"total": 1}}
        result = enrich_breaks_locally(data)
        assert result is data
        assert "summary" in result

    def test_all_breaks_enriched(self):
        breaks = [_make_break(break_type=bt, trade_id=f"T{i}")
                  for i, bt in enumerate(ALL_BREAK_TYPES)]
        result = enrich_breaks_locally({"breaks": breaks})
        for brk in result["breaks"]:
            assert brk.get("ai_explanation")
            assert brk.get("recommended_action")
