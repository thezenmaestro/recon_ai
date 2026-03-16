"""
Snowflake sink — writes all observability events to the OBSERVABILITY schema.

Tables live in RECON_DB.OBSERVABILITY (same results DB, separate schema).
All writes are fire-and-forget with silent failure so the main recon job
is never blocked or crashed by a tracking error.

Schema is also pre-built with Sigma / Basedash-friendly column names and
pre-defined views for common dashboard queries.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

from observability.models import (
    AIAPICallEvent,
    NotificationDeliveryEvent,
    RunEvent,
    ToolCallEvent,
    UserActivityEvent,
)


# =============================================================================
# SNOWFLAKE DDL
# Run once via: python observability/setup.py
# =============================================================================

OBSERVABILITY_DDL = """
-- Run this once. All statements are idempotent.

CREATE SCHEMA IF NOT EXISTS OBSERVABILITY;

-- ── 1. AI API Calls ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS OBSERVABILITY.AI_API_CALLS (
    CALL_ID             VARCHAR(64)     NOT NULL PRIMARY KEY,
    RUN_ID              VARCHAR(64),
    TRADE_DATE          DATE,
    MODEL               VARCHAR(64),
    INPUT_TOKENS        INTEGER,
    OUTPUT_TOKENS       INTEGER,
    THINKING_TOKENS     INTEGER,
    TOTAL_TOKENS        INTEGER,
    COST_USD            NUMBER(12, 6),
    LATENCY_MS          INTEGER,
    STOP_REASON         VARCHAR(32),
    HAD_THINKING        BOOLEAN,
    TOOL_USE_COUNT      INTEGER,
    TRIGGERED_BY        VARCHAR(32),
    CALL_PURPOSE        VARCHAR(64),
    CALLED_AT           TIMESTAMP_NTZ,
    ERROR               TEXT
);

-- ── 2. Tool Calls ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS OBSERVABILITY.TOOL_CALLS (
    TOOL_CALL_ID        VARCHAR(64)     NOT NULL PRIMARY KEY,
    API_CALL_ID         VARCHAR(64),
    RUN_ID              VARCHAR(64),
    TRADE_DATE          DATE,
    TOOL_NAME           VARCHAR(128),
    CALLED_AT           TIMESTAMP_NTZ,
    DURATION_MS         INTEGER,
    STATUS              VARCHAR(16),
    INPUT_SIZE_BYTES    INTEGER,
    OUTPUT_SIZE_BYTES   INTEGER,
    ERROR_MESSAGE       TEXT
);

-- ── 3. Run Events ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS OBSERVABILITY.RUN_EVENTS (
    EVENT_ID                    VARCHAR(64)     NOT NULL PRIMARY KEY,
    RUN_ID                      VARCHAR(64),
    TRADE_DATE                  DATE,
    EVENT_TYPE                  VARCHAR(32),
    TRIGGERED_BY                VARCHAR(32),
    STATUS                      VARCHAR(16),
    TOTAL_TRADES                INTEGER,
    TOTAL_EXECUTIONS            INTEGER,
    MATCHED_COUNT               INTEGER,
    BREAK_COUNT                 INTEGER,
    HIGH_SEVERITY_COUNT         INTEGER,
    TOTAL_NOTIONAL_AT_RISK_USD  NUMBER(20, 4),
    TOTAL_API_CALLS             INTEGER,
    TOTAL_TOKENS_USED           INTEGER,
    TOTAL_COST_USD              NUMBER(12, 6),
    DURATION_SECONDS            NUMBER(10, 2),
    ERROR_MESSAGE               TEXT,
    OCCURRED_AT                 TIMESTAMP_NTZ
);

-- ── 4. Notification Deliveries ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS OBSERVABILITY.NOTIFICATION_DELIVERIES (
    DELIVERY_ID     VARCHAR(64)     NOT NULL PRIMARY KEY,
    RUN_ID          VARCHAR(64),
    TRADE_DATE      DATE,
    CHANNEL_TYPE    VARCHAR(16),
    CHANNEL_NAME    VARCHAR(256),
    BREAK_COUNT     INTEGER,
    STATUS          VARCHAR(16),
    ATTEMPTS        INTEGER,
    ERROR_MESSAGE   TEXT,
    SENT_AT         TIMESTAMP_NTZ
);

-- ── 5. User Activity ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS OBSERVABILITY.USER_ACTIVITY (
    ACTIVITY_ID     VARCHAR(64)     NOT NULL PRIMARY KEY,
    USER_NAME       VARCHAR(256),
    ACTION          VARCHAR(128),
    SOURCE          VARCHAR(32),
    RUN_ID          VARCHAR(64),
    TRADE_DATE      DATE,
    DETAILS         VARIANT,
    IP_ADDRESS      VARCHAR(64),
    OCCURRED_AT     TIMESTAMP_NTZ
);

-- =============================================================================
-- VIEWS — optimised for Sigma / Basedash
-- =============================================================================

-- Daily cost summary
CREATE OR REPLACE VIEW OBSERVABILITY.V_DAILY_AI_COST AS
SELECT
    TRADE_DATE,
    MODEL,
    TRIGGERED_BY,
    COUNT(*)                        AS api_call_count,
    SUM(INPUT_TOKENS)               AS total_input_tokens,
    SUM(OUTPUT_TOKENS)              AS total_output_tokens,
    SUM(THINKING_TOKENS)            AS total_thinking_tokens,
    SUM(TOTAL_TOKENS)               AS total_tokens,
    SUM(COST_USD)                   AS total_cost_usd,
    AVG(LATENCY_MS)                 AS avg_latency_ms,
    MAX(LATENCY_MS)                 AS max_latency_ms,
    SUM(TOOL_USE_COUNT)             AS total_tool_calls,
    COUNT_IF(ERROR IS NOT NULL)     AS error_count
FROM OBSERVABILITY.AI_API_CALLS
GROUP BY 1, 2, 3;

-- Monthly cost rollup
CREATE OR REPLACE VIEW OBSERVABILITY.V_MONTHLY_AI_COST AS
SELECT
    DATE_TRUNC('month', TRADE_DATE) AS month,
    MODEL,
    SUM(total_cost_usd)             AS total_cost_usd,
    SUM(total_tokens)               AS total_tokens,
    SUM(api_call_count)             AS total_api_calls
FROM OBSERVABILITY.V_DAILY_AI_COST
GROUP BY 1, 2;

-- Tool usage frequency + performance
CREATE OR REPLACE VIEW OBSERVABILITY.V_TOOL_PERFORMANCE AS
SELECT
    TOOL_NAME,
    COUNT(*)                            AS total_calls,
    COUNT_IF(STATUS = 'SUCCESS')        AS success_count,
    COUNT_IF(STATUS = 'FAILURE')        AS failure_count,
    ROUND(COUNT_IF(STATUS = 'SUCCESS') * 100.0 / COUNT(*), 2) AS success_rate_pct,
    AVG(DURATION_MS)                    AS avg_duration_ms,
    MAX(DURATION_MS)                    AS max_duration_ms,
    AVG(INPUT_SIZE_BYTES)               AS avg_input_bytes,
    AVG(OUTPUT_SIZE_BYTES)              AS avg_output_bytes,
    MIN(CALLED_AT)                      AS first_seen,
    MAX(CALLED_AT)                      AS last_seen
FROM OBSERVABILITY.TOOL_CALLS
GROUP BY 1;

-- Run history with cost attribution
CREATE OR REPLACE VIEW OBSERVABILITY.V_RUN_HISTORY AS
SELECT
    re.RUN_ID,
    re.TRADE_DATE,
    re.TRIGGERED_BY,
    re.STATUS,
    re.TOTAL_TRADES,
    re.MATCHED_COUNT,
    re.BREAK_COUNT,
    re.HIGH_SEVERITY_COUNT,
    re.TOTAL_NOTIONAL_AT_RISK_USD,
    re.DURATION_SECONDS,
    re.OCCURRED_AT                          AS completed_at,
    ROUND(re.MATCHED_COUNT * 100.0 / NULLIF(re.TOTAL_TRADES, 0), 2) AS match_rate_pct,
    cost.total_cost_usd                     AS ai_cost_usd,
    cost.total_tokens                       AS tokens_used,
    cost.api_call_count
FROM OBSERVABILITY.RUN_EVENTS re
LEFT JOIN (
    SELECT
        RUN_ID,
        SUM(COST_USD)       AS total_cost_usd,
        SUM(TOTAL_TOKENS)   AS total_tokens,
        COUNT(*)            AS api_call_count
    FROM OBSERVABILITY.AI_API_CALLS
    GROUP BY RUN_ID
) cost ON re.RUN_ID = cost.RUN_ID
WHERE re.EVENT_TYPE = 'COMPLETED';

-- Notification delivery success/failure rates by channel
CREATE OR REPLACE VIEW OBSERVABILITY.V_NOTIFICATION_DELIVERIES AS
SELECT
    TRADE_DATE,
    CHANNEL_TYPE,
    CHANNEL_NAME,
    COUNT(*)                                AS total_dispatches,
    COUNT_IF(STATUS = 'SUCCESS')            AS success_count,
    COUNT_IF(STATUS = 'FAILURE')            AS failure_count,
    COUNT_IF(STATUS = 'SKIPPED')            AS skipped_count,
    ROUND(COUNT_IF(STATUS = 'SUCCESS') * 100.0 / NULLIF(COUNT(*), 0), 2) AS success_rate_pct,
    SUM(BREAK_COUNT)                        AS total_breaks_delivered,
    AVG(ATTEMPTS)                           AS avg_attempts
FROM OBSERVABILITY.NOTIFICATION_DELIVERIES
GROUP BY 1, 2, 3;

-- User activity log (human-readable)
CREATE OR REPLACE VIEW OBSERVABILITY.V_USER_ACTIVITY AS
SELECT
    ACTIVITY_ID,
    USER_NAME,
    ACTION,
    SOURCE,
    RUN_ID,
    TRADE_DATE,
    DETAILS,
    OCCURRED_AT
FROM OBSERVABILITY.USER_ACTIVITY
ORDER BY OCCURRED_AT DESC;
"""


# =============================================================================
# SINK CLASS
# =============================================================================

class ObservabilitySink:
    """
    Writes observability events to Snowflake OBSERVABILITY schema.
    All public methods are fire-and-forget — exceptions are caught and logged
    so the main recon job is never interrupted by tracking failures.
    """

    def __init__(self) -> None:
        self._conn = None

    def _get_conn(self):
        """Lazy connection — only connects when first write is needed."""
        if self._conn is None or self._conn.is_closed():
            import snowflake.connector
            self._conn = snowflake.connector.connect(
                account=os.environ["SNOWFLAKE_ACCOUNT"],
                user=os.environ["SNOWFLAKE_USER"],
                password=os.environ["SNOWFLAKE_PASSWORD"],
                warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
                database=os.environ["SNOWFLAKE_RESULTS_DATABASE"],
                schema="OBSERVABILITY",
                role=os.environ.get("SNOWFLAKE_ROLE", ""),
            )
        return self._conn

    def _insert(self, table: str, data: dict) -> None:
        """Insert a single row. Silently fails on error."""
        try:
            df = pd.DataFrame([data])
            df.columns = [c.upper() for c in df.columns]
            from snowflake.connector.pandas_tools import write_pandas
            write_pandas(
                conn=self._get_conn(),
                df=df,
                table_name=table,
                schema="OBSERVABILITY",
                database=os.environ["SNOWFLAKE_RESULTS_DATABASE"],
                auto_create_table=False,
                overwrite=False,
            )
        except Exception as e:
            # Never crash the main job over an observability write
            logger.warning("Observability write to %s failed: %s", table, e)

    # ── Public write methods ─────────────────────────────────────────────────

    def log_api_call(self, event: AIAPICallEvent) -> None:
        data = event.model_dump()
        data["called_at"] = data["called_at"].isoformat()
        self._insert("AI_API_CALLS", data)

    def log_tool_call(self, event: ToolCallEvent) -> None:
        data = event.model_dump()
        data["called_at"] = data["called_at"].isoformat()
        self._insert("TOOL_CALLS", data)

    def log_run_event(self, event: RunEvent) -> None:
        data = event.model_dump()
        data["occurred_at"] = data["occurred_at"].isoformat()
        self._insert("RUN_EVENTS", data)

    def log_notification(self, event: NotificationDeliveryEvent) -> None:
        data = event.model_dump()
        data["sent_at"] = data["sent_at"].isoformat()
        self._insert("NOTIFICATION_DELIVERIES", data)

    def log_user_activity(self, event: UserActivityEvent) -> None:
        data = event.model_dump()
        data["occurred_at"] = data["occurred_at"].isoformat()
        # Rename 'user' → 'user_name' to avoid SQL reserved word
        data["user_name"] = data.pop("user", "system")
        # Serialise details dict to JSON string for VARIANT column
        if isinstance(data.get("details"), dict):
            data["details"] = json.dumps(data["details"])
        self._insert("USER_ACTIVITY", data)

    def close(self) -> None:
        if self._conn and not self._conn.is_closed():
            self._conn.close()


# Module-level singleton — shared across the process
_sink: ObservabilitySink | None = None

def get_sink() -> ObservabilitySink:
    global _sink
    if _sink is None:
        _sink = ObservabilitySink()
    return _sink
