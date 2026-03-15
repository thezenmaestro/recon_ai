"""
Data Loader Tool — reads trades and executions from Snowflake.
Called by the reconciliation agent via @beta_tool.
No AI logic here — pure data access.
"""
from __future__ import annotations

import json
import os
from datetime import date
from typing import Any

import pandas as pd
import yaml

from src.data.snowflake_connector import executions_conn, query_to_df, trades_conn

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

    with trades_conn() as conn:
        df = query_to_df(conn, sql, params=(trade_date,))

    if df.empty:
        return json.dumps({"trades": [], "count": 0, "trade_date": trade_date})

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

    with executions_conn() as conn:
        df = query_to_df(conn, sql, params=(trade_date,))

    if df.empty:
        return json.dumps({"executions": [], "count": 0, "trade_date": trade_date})

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
