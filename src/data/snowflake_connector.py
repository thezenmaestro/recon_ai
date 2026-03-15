"""
Snowflake connection management.
Handles two separate databases: TRADES_DB and EXECUTIONS_DB.
Results are written to RECON_DB.

All credentials come from environment variables (see .env.example).
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Generator, Optional

import pandas as pd
import snowflake.connector
from snowflake.connector import DictCursor
from snowflake.connector.connection import SnowflakeConnection


# =============================================================================
# CONNECTION FACTORY
# =============================================================================

def _get_base_params() -> dict[str, str]:
    """Build base Snowflake connection params from environment variables."""
    return {
        "account":   os.environ["SNOWFLAKE_ACCOUNT"],      # e.g. xy12345.us-east-1
        "user":      os.environ["SNOWFLAKE_USER"],
        "password":  os.environ["SNOWFLAKE_PASSWORD"],
        "warehouse": os.environ["SNOWFLAKE_WAREHOUSE"],    # e.g. RECON_WH
        "role":      os.environ.get("SNOWFLAKE_ROLE", ""),
    }


@contextmanager
def trades_conn() -> Generator[SnowflakeConnection, None, None]:
    """Context manager: connection to the Trades (OMS) database."""
    params = _get_base_params()
    params["database"] = os.environ["SNOWFLAKE_TRADES_DATABASE"]
    conn = snowflake.connector.connect(**params)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def executions_conn() -> Generator[SnowflakeConnection, None, None]:
    """Context manager: connection to the Executions (Broker Confirms) database."""
    params = _get_base_params()
    params["database"] = os.environ["SNOWFLAKE_EXECUTIONS_DATABASE"]
    conn = snowflake.connector.connect(**params)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def results_conn() -> Generator[SnowflakeConnection, None, None]:
    """Context manager: connection to the Reconciliation Results database."""
    params = _get_base_params()
    params["database"] = os.environ["SNOWFLAKE_RESULTS_DATABASE"]
    conn = snowflake.connector.connect(**params)
    try:
        yield conn
    finally:
        conn.close()


# =============================================================================
# QUERY HELPERS
# =============================================================================

def query_to_df(conn: SnowflakeConnection, sql: str, params: Optional[tuple] = None) -> pd.DataFrame:
    """Execute a SELECT query and return results as a DataFrame."""
    with conn.cursor(DictCursor) as cur:
        cur.execute(sql, params or ())
        rows = cur.fetchall()
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def execute_ddl(conn: SnowflakeConnection, sql: str) -> None:
    """Execute a non-SELECT statement (INSERT, MERGE, CREATE, etc.)."""
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def bulk_insert(
    conn: SnowflakeConnection,
    table: str,
    df: pd.DataFrame,
    schema: str,
    database: str,
) -> int:
    """
    Insert a DataFrame into a Snowflake table using write_pandas.
    Returns the number of rows written.
    """
    from snowflake.connector.pandas_tools import write_pandas

    success, _, nrows, _ = write_pandas(
        conn=conn,
        df=df,
        table_name=table.upper(),
        schema=schema.upper(),
        database=database.upper(),
        auto_create_table=False,    # Tables must be pre-created (see DDL below)
        overwrite=False,
    )
    if not success:
        raise RuntimeError(f"bulk_insert failed for {database}.{schema}.{table}")
    return nrows


# =============================================================================
# DDL — CREATE RESULT TABLES (run once during setup)
# =============================================================================
# Execute create_result_tables() once to set up your RECON_DB schema.
# Idempotent: uses CREATE TABLE IF NOT EXISTS.

RESULT_TABLE_DDL = """
-- Run this once in your RECON_DB / RESULTS schema

CREATE TABLE IF NOT EXISTS RECON_RUNS (
    RUN_ID              VARCHAR(64)     NOT NULL PRIMARY KEY,
    TRADE_DATE          DATE            NOT NULL,
    RUN_TIMESTAMP       TIMESTAMP_NTZ   NOT NULL,
    TRIGGERED_BY        VARCHAR(32),
    TOTAL_TRADES        INTEGER,
    TOTAL_EXECUTIONS    INTEGER,
    MATCHED_COUNT       INTEGER,
    BREAK_COUNT         INTEGER,
    NEEDS_REVIEW_COUNT  INTEGER,
    TOTAL_MATCHED_NOTIONAL_USD  NUMBER(20,4),
    TOTAL_BREAK_NOTIONAL_USD    NUMBER(20,4),
    STATUS              VARCHAR(16),
    ERROR_MESSAGE       TEXT,
    COMPLETED_AT        TIMESTAMP_NTZ
);

CREATE TABLE IF NOT EXISTS MATCHED_TRADES (
    MATCH_ID            VARCHAR(64)     NOT NULL PRIMARY KEY,
    RUN_ID              VARCHAR(64)     NOT NULL,
    TRADE_ID            VARCHAR(128),
    EXECUTION_ID        VARCHAR(128),
    INSTRUMENT_TYPE     VARCHAR(32),
    NOTIONAL_USD        NUMBER(20,4),
    QTY_VARIANCE        NUMBER(20,6),
    PRICE_VARIANCE_PCT  NUMBER(10,6),
    MATCH_CONFIDENCE    VARCHAR(16),
    MATCHED_AT          TIMESTAMP_NTZ
);

CREATE TABLE IF NOT EXISTS BREAKS (
    BREAK_ID                VARCHAR(64)     NOT NULL PRIMARY KEY,
    RUN_ID                  VARCHAR(64)     NOT NULL,
    TRADE_ID                VARCHAR(128),
    EXECUTION_ID            VARCHAR(128),
    INSTRUMENT_TYPE         VARCHAR(32),
    COUNTERPARTY            VARCHAR(256),
    ISIN                    VARCHAR(12),
    DIRECTION               VARCHAR(4),
    BREAK_TYPE              VARCHAR(32),
    SEVERITY                VARCHAR(8),
    BOOKED_QUANTITY         NUMBER(20,6),
    EXECUTED_QUANTITY       NUMBER(20,6),
    QUANTITY_GAP            NUMBER(20,6),
    BOOKED_PRICE            NUMBER(20,8),
    EXECUTED_PRICE          NUMBER(20,8),
    PRICE_VARIANCE_PCT      NUMBER(10,6),
    NOTIONAL_AT_RISK_USD    NUMBER(20,4),
    BOOKED_SETTLEMENT_DATE  DATE,
    EXECUTED_SETTLEMENT_DATE DATE,
    AI_EXPLANATION          TEXT,
    RECOMMENDED_ACTION      TEXT,
    CREATED_AT              TIMESTAMP_NTZ
);

CREATE TABLE IF NOT EXISTS POSITION_IMPACT (
    IMPACT_ID                   VARCHAR(64)     NOT NULL PRIMARY KEY,
    RUN_ID                      VARCHAR(64)     NOT NULL,
    BREAK_ID                    VARCHAR(64),
    ISIN                        VARCHAR(12),
    INSTRUMENT_TYPE             VARCHAR(32),
    COUNTERPARTY                VARCHAR(256),
    NET_POSITION_CHANGE         NUMBER(20,6),
    NET_POSITION_DIRECTION      VARCHAR(8),
    PNL_IMPACT_USD              NUMBER(20,4),
    SETTLEMENT_CASH_IMPACT_USD  NUMBER(20,4),
    SECURITIES_DELIVERY_IMPACT  NUMBER(20,6),
    DELTA_IMPACT                NUMBER(20,8),
    DV01_IMPACT_USD             NUMBER(20,4),
    RISK_METRIC_NOTES           TEXT,
    AS_OF_DATE                  DATE,
    LAST_KNOWN_PRICE            NUMBER(20,8),
    PRICE_SOURCE                VARCHAR(64)
);
"""


def create_result_tables() -> None:
    """Run once during setup to create result tables in RECON_DB."""
    with results_conn() as conn:
        schema = os.environ.get("SNOWFLAKE_RESULTS_SCHEMA", "RESULTS")
        with conn.cursor() as cur:
            cur.execute(f"USE SCHEMA {schema}")
            for statement in RESULT_TABLE_DDL.strip().split(";"):
                stmt = statement.strip()
                if stmt:
                    cur.execute(stmt)
        conn.commit()
    print("Result tables created successfully.")


if __name__ == "__main__":
    create_result_tables()
