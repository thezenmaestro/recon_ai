"""
Data Loader Tool — reads trades and executions from Snowflake.
Called by the reconciliation agent via @beta_tool.
No AI logic here — pure data access.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import date
from typing import Any

import pandas as pd
import yaml

from src.data.snowflake_connector import executions_conn, query_to_df, trades_conn
from src.exceptions import DataLoadError, DataQualityError

logger = logging.getLogger(__name__)

# Load field mappings once at import time
_MAPPINGS_PATH = os.path.join(os.path.dirname(__file__), "../../config/field_mappings.yaml")
with open(_MAPPINGS_PATH) as f:
    MAPPINGS = yaml.safe_load(f)


# =============================================================================
# TRADES LOADER
# =============================================================================

def load_booked_trades(trade_date: str) -> str:
    """
    Load booked trades from the OMS Snowflake database for a given trade date.

    Args:
        trade_date: Trade date in YYYY-MM-DD format.

    Returns:
        JSON string of trade records. Each record maps to BookedTrade fields.
    """
    cfg = MAPPINGS["trades"]
    cols = cfg["columns"]
    sf = cfg["snowflake"]
    statuses = cfg["filters"]["active_statuses"]
    status_list = ", ".join(f"'{s}'" for s in statuses)

    sql = f"""
        SELECT
            {cols['trade_id']}          AS trade_id,
            {cols['isin']}              AS isin,
            {cols['ticker']}            AS ticker,
            {cols['instrument_type']}   AS instrument_type,
            {cols['counterparty']}      AS counterparty,
            {cols['direction']}         AS direction,
            {cols['quantity']}          AS quantity,
            {cols['price']}             AS price,
            {cols['notional']}          AS notional,
            {cols['currency']}          AS currency,
            {cols['trade_date']}        AS trade_date,
            {cols['settlement_date']}   AS settlement_date,
            {cols['status']}            AS status
        FROM {sf['schema']}.{sf['table']}
        WHERE {cols['trade_date']} = %s
          AND {cols['status']} IN ({status_list})
    """

    t0 = time.monotonic()
    try:
        with trades_conn() as conn:
            df = query_to_df(conn, sql, params=(trade_date,))
    except Exception as exc:
        _emit_data_quality("trades", trade_date, 0, {}, int((time.monotonic() - t0) * 1000),
                           "FAILURE", str(exc))
        raise DataLoadError(f"Failed to load booked trades for {trade_date}") from exc
    latency_ms = int((time.monotonic() - t0) * 1000)

    if df.empty:
        logger.warning("No booked trades found for %s — returning empty dataset", trade_date)
        _emit_data_quality("trades", trade_date, 0, {}, latency_ms, "EMPTY")
        return json.dumps({"trades": [], "count": 0, "trade_date": trade_date})

    # Validate required columns are present
    required = {"trade_id", "isin", "quantity", "price", "settlement_date"}
    missing = required - set(df.columns)
    if missing:
        raise DataQualityError(
            f"Booked trades query for {trade_date} missing required columns: {missing}"
        )

    null_counts = {
        "null_trade_id": int(df["trade_id"].isna().sum()),
        "null_isin":     int(df["isin"].isna().sum()),
        "null_quantity": int(df["quantity"].isna().sum()),
        "null_price":    int(df["price"].isna().sum()),
    }
    _emit_data_quality("trades", trade_date, len(df), null_counts, latency_ms, "SUCCESS")

    # Normalise date columns to string for JSON serialisation
    for col in ["trade_date", "settlement_date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col]).dt.strftime("%Y-%m-%d")

    # Normalise numeric columns
    for col in ["quantity", "price", "notional"]:
        if col in df.columns:
            df[col] = df[col].astype(float)

    return json.dumps({
        "trades": df.to_dict(orient="records"),
        "count": len(df),
        "trade_date": trade_date,
    })


# =============================================================================
# EXECUTIONS LOADER
# =============================================================================

def load_executed_transactions(trade_date: str) -> str:
    """
    Load execution confirms from the broker Snowflake database for a given trade date.

    Args:
        trade_date: Trade date in YYYY-MM-DD format (matches on execution_date).

    Returns:
        JSON string of execution records. Each record maps to ExecutedTransaction fields.
    """
    cfg = MAPPINGS["executions"]
    cols = cfg["columns"]
    sf = cfg["snowflake"]
    statuses = cfg["filters"]["active_statuses"]
    status_list = ", ".join(f"'{s}'" for s in statuses)

    sql = f"""
        SELECT
            {cols['execution_id']}          AS execution_id,
            {cols['trade_ref_id']}          AS trade_ref_id,
            {cols['isin']}                  AS isin,
            {cols['ticker']}                AS ticker,
            {cols['instrument_type']}       AS instrument_type,
            {cols['counterparty']}          AS counterparty,
            {cols['direction']}             AS direction,
            {cols['executed_quantity']}     AS executed_quantity,
            {cols['executed_price']}        AS executed_price,
            {cols['executed_notional']}     AS executed_notional,
            {cols['currency']}              AS currency,
            {cols['execution_date']}        AS execution_date,
            {cols['settlement_date']}       AS settlement_date,
            {cols['status']}                AS status
        FROM {sf['schema']}.{sf['table']}
        WHERE {cols['execution_date']} = %s
          AND {cols['status']} IN ({status_list})
    """

    t0 = time.monotonic()
    try:
        with executions_conn() as conn:
            df = query_to_df(conn, sql, params=(trade_date,))
    except Exception as exc:
        _emit_data_quality("executions", trade_date, 0, {}, int((time.monotonic() - t0) * 1000),
                           "FAILURE", str(exc))
        raise DataLoadError(f"Failed to load executed transactions for {trade_date}") from exc
    latency_ms = int((time.monotonic() - t0) * 1000)

    if df.empty:
        logger.warning("No executed transactions found for %s — returning empty dataset", trade_date)
        _emit_data_quality("executions", trade_date, 0, {}, latency_ms, "EMPTY")
        return json.dumps({"executions": [], "count": 0, "trade_date": trade_date})

    # Validate required columns are present
    required = {"execution_id", "executed_quantity", "executed_price", "settlement_date"}
    missing = required - set(df.columns)
    if missing:
        raise DataQualityError(
            f"Executed transactions query for {trade_date} missing required columns: {missing}"
        )

    null_counts = {
        "null_trade_id": int(df["execution_id"].isna().sum()),
        "null_isin":     int(df["isin"].isna().sum()),
        "null_quantity": int(df["executed_quantity"].isna().sum()),
        "null_price":    int(df["executed_price"].isna().sum()),
    }
    _emit_data_quality("executions", trade_date, len(df), null_counts, latency_ms, "SUCCESS")

    for col in ["execution_date", "settlement_date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col]).dt.strftime("%Y-%m-%d")

    for col in ["executed_quantity", "executed_price", "executed_notional"]:
        if col in df.columns:
            df[col] = df[col].astype(float)

    return json.dumps({
        "executions": df.to_dict(orient="records"),
        "count": len(df),
        "trade_date": trade_date,
    })


# =============================================================================
# OBSERVABILITY HELPER
# =============================================================================

def _emit_data_quality(
    dataset: str,
    trade_date: str,
    record_count: int,
    null_counts: dict,
    query_latency_ms: int,
    status: str,
    error_message: str | None = None,
) -> None:
    """Fire-and-forget write to OBSERVABILITY.DATA_QUALITY_METRICS."""
    try:
        from observability.models import DataQualityMetricEvent
        from observability.sink import get_sink
        event = DataQualityMetricEvent(
            trade_date=trade_date,
            dataset=dataset,
            record_count=record_count,
            null_trade_id=null_counts.get("null_trade_id", 0),
            null_isin=null_counts.get("null_isin", 0),
            null_quantity=null_counts.get("null_quantity", 0),
            null_price=null_counts.get("null_price", 0),
            query_latency_ms=query_latency_ms,
            status=status,
            error_message=error_message,
        )
        get_sink().log_data_quality(event)
    except Exception as exc:
        logger.warning("Failed to write data quality metrics to OBSERVABILITY: %s", exc)
