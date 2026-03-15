"""
Position & Valuation Impact Calculator.
For each break, calculates open position impact, P&L exposure,
settlement/funding risk, and risk metrics (delta, DV01).
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

_MAPPINGS_PATH = os.path.join(os.path.dirname(__file__), "../../config/field_mappings.yaml")
with open(_MAPPINGS_PATH) as f:
    MAPPINGS = yaml.safe_load(f)


# =============================================================================
# FX RATE LOOKUP
# =============================================================================

def _get_fx_rate(from_currency: str, to_currency: str = "USD", trade_date: str | None = None) -> float:
    """
    Look up an FX rate to convert notional to the base currency (default USD).
    Config source: field_mappings.yaml → fx_rates
    Fallback rate:  business_rules.yaml → position.fx_rate_fallback

    TODO: Uncomment the Snowflake block below once MARKET_DATA_DB is available.
    """
    fallback = float(RULES["position"].get("fx_rate_fallback", 1.0))

    if from_currency.upper() == to_currency.upper():
        return 1.0

    fx_cfg = MAPPINGS.get("fx_rates", {})

    if fx_cfg.get("use_snowflake_table", False):
        # ── Snowflake FX lookup (uncomment when MARKET_DATA_DB is live) ─────
        # db    = fx_cfg["snowflake"]["database"]
        # schema = fx_cfg["snowflake"]["schema"]
        # table  = fx_cfg["snowflake"]["table"]
        # date_col   = fx_cfg["snowflake"]["date_column"]
        # from_col   = fx_cfg["snowflake"]["from_currency_column"]
        # to_col     = fx_cfg["snowflake"]["to_currency_column"]
        # rate_col   = fx_cfg["snowflake"]["rate_column"]
        # rate_date  = trade_date or str(date.today())
        #
        # sql = (
        #     f"SELECT {rate_col} FROM {db}.{schema}.{table} "
        #     f"WHERE {from_col} = %s AND {to_col} = %s AND {date_col} = %s"
        # )
        # try:
        #     from src.data.snowflake_connector import query_to_df, results_conn
        #     with results_conn() as conn:
        #         df = query_to_df(conn, sql, (from_currency.upper(), to_currency.upper(), rate_date))
        #     if not df.empty:
        #         return float(df.iloc[0, 0])
        # except Exception as exc:
        #     print(f"[FX] Snowflake lookup failed ({from_currency}→{to_currency}): {exc}")
        pass  # Remove when implementing the block above

    return fallback


def _get_last_price(isin: str, instrument_type: str) -> tuple[float | None, str]:
    """
    Get the last known market price for an instrument.
    Returns (price, source_description).

    TODO: Implement using your market data source in Snowflake.
    """
    # Placeholder — replace with actual lookup
    return None, "NOT_AVAILABLE"


# =============================================================================
# IMPACT CALCULATOR
# =============================================================================

def calculate_position_impact(breaks_json: str, trade_date: str) -> str:
    """
    For each break, calculate forward position and valuation impact.

    Args:
        breaks_json: JSON output from classify_breaks()
        trade_date: Trade date in YYYY-MM-DD (used for price/rate lookups)

    Returns:
        JSON string with 'position_impacts' list and 'portfolio_summary'
    """
    data = json.loads(breaks_json)
    breaks = data.get("breaks", [])

    impacts = []
    portfolio_pnl = 0.0
    portfolio_cash = 0.0
    portfolio_securities = 0.0

    risk_metrics_config = RULES["position"]["compute_risk_metrics"]

    for brk in breaks:
        instrument_type = brk.get("instrument_type", "UNKNOWN")
        isin = brk.get("isin")
        currency = brk.get("currency") or MAPPINGS.get("fx_rates", {}).get("base_currency", "USD")
        direction = brk.get("direction", "BUY")

        qty_gap = float(brk.get("quantity_gap", 0))
        booked_price = float(brk.get("booked_price", 0))
        notional_at_risk = float(brk.get("notional_at_risk_usd", 0))

        # FX conversion
        fx_rate = _get_fx_rate(currency, trade_date=trade_date)
        notional_usd = notional_at_risk * fx_rate

        # Position direction (gap represents exposure we DON'T have)
        net_direction = "LONG" if direction == "BUY" else "SHORT"

        # P&L impact: mark unexecuted notional at last known price
        last_price, price_source = _get_last_price(isin or "", instrument_type)
        pnl_impact = 0.0
        if last_price and booked_price:
            price_move = last_price - booked_price
            # If BUY didn't execute: missed gain if price went up
            pnl_impact = price_move * qty_gap * fx_rate * (1 if direction == "BUY" else -1)

        # Settlement / funding impact
        # BUY break → cash we don't need to pay (positive), securities we won't receive
        # SELL break → securities we don't need to deliver, cash we won't receive
        if direction == "BUY":
            cash_impact = notional_usd         # Cash NOT sent → positive liquidity
            securities_impact = -qty_gap        # Securities NOT received
        else:
            cash_impact = -notional_usd         # Cash NOT received → negative
            securities_impact = qty_gap         # Securities NOT delivered

        # Risk metrics
        delta_impact = None
        dv01_impact = None
        risk_notes = None

        required_metrics = risk_metrics_config.get(instrument_type, [])
        if "dv01" in required_metrics:
            dv01_cfg = RULES["position"].get("dv01_config", {})
            bps_per_million = float(dv01_cfg.get("basis_points_per_million", 1.0))
            dv01_impact = (notional_usd / 1_000_000) * bps_per_million
            risk_notes = dv01_cfg.get("estimation_note", "DV01 is estimated.")

        if "delta" in required_metrics:
            delta_impact = qty_gap   # For linear instruments, delta = qty

        portfolio_pnl += pnl_impact
        portfolio_cash += cash_impact
        portfolio_securities += securities_impact

        impacts.append({
            "impact_id": str(uuid.uuid4()),
            "run_id": brk.get("run_id"),
            "break_id": brk.get("break_id"),
            "isin": isin,
            "instrument_type": instrument_type,
            "counterparty": brk.get("counterparty", ""),
            "net_position_change": float(qty_gap),
            "net_position_direction": net_direction,
            "pnl_impact_usd": round(pnl_impact, 4),
            "settlement_cash_impact_usd": round(cash_impact, 4),
            "securities_delivery_impact": round(securities_impact, 6),
            "delta_impact": round(delta_impact, 4) if delta_impact is not None else None,
            "dv01_impact_usd": round(dv01_impact, 4) if dv01_impact is not None else None,
            "risk_metric_notes": risk_notes,
            "as_of_date": trade_date,
            "last_known_price": float(last_price) if last_price else None,
            "price_source": price_source,
        })

    return json.dumps({
        "position_impacts": impacts,
        "portfolio_summary": {
            "total_pnl_impact_usd": round(portfolio_pnl, 4),
            "total_cash_impact_usd": round(portfolio_cash, 4),
            "total_securities_impact": round(portfolio_securities, 6),
            "break_count_with_impact": len(impacts),
        },
    })
