"""
Reporter — writes all reconciliation results back to Snowflake RECON_DB.
Also writes the ReconRun summary record.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime

import pandas as pd

from src.data.snowflake_connector import bulk_insert, execute_ddl, results_conn


def _get_schema() -> str:
    return os.environ.get("SNOWFLAKE_RESULTS_SCHEMA", "RESULTS")


def _get_database() -> str:
    return os.environ["SNOWFLAKE_RESULTS_DATABASE"]


# =============================================================================
# WRITE HELPERS
# =============================================================================

def write_recon_run(run_record: dict) -> str:
    """
    Insert or update the RECON_RUNS record.

    Args:
        run_record: Dict matching ReconRun model fields.

    Returns:
        Confirmation JSON string.
    """
    df = pd.DataFrame([run_record])
    df.columns = [c.upper() for c in df.columns]

    with results_conn() as conn:
        n = bulk_insert(conn, "RECON_RUNS", df, _get_schema(), _get_database())

    return json.dumps({"written": n, "table": "RECON_RUNS", "run_id": run_record.get("run_id")})


def write_matched_trades(matched_json: str, run_id: str) -> str:
    """
    Write matched trade pairs to MATCHED_TRADES.

    Args:
        matched_json: JSON output from match_transactions() → 'matched' key
        run_id: Current reconciliation run ID
    """
    data = json.loads(matched_json)
    matched = data.get("matched", [])

    if not matched:
        return json.dumps({"written": 0, "table": "MATCHED_TRADES"})

    df = pd.DataFrame(matched)
    df["RUN_ID"] = run_id
    df.columns = [c.upper() for c in df.columns]

    with results_conn() as conn:
        n = bulk_insert(conn, "MATCHED_TRADES", df, _get_schema(), _get_database())

    return json.dumps({"written": n, "table": "MATCHED_TRADES", "run_id": run_id})


def write_breaks(breaks_json: str) -> str:
    """
    Write break records (with AI explanations) to BREAKS table.

    Args:
        breaks_json: JSON output from classify_breaks() after Claude
                     has added ai_explanation and recommended_action fields.
    """
    data = json.loads(breaks_json)
    breaks = data.get("breaks", [])

    if not breaks:
        return json.dumps({"written": 0, "table": "BREAKS"})

    df = pd.DataFrame(breaks)
    df.columns = [c.upper() for c in df.columns]

    # Ensure timestamp column
    if "CREATED_AT" not in df.columns:
        df["CREATED_AT"] = datetime.utcnow()

    with results_conn() as conn:
        n = bulk_insert(conn, "BREAKS", df, _get_schema(), _get_database())

    return json.dumps({"written": n, "table": "BREAKS"})


def write_position_impacts(impacts_json: str) -> str:
    """
    Write position/valuation impacts to POSITION_IMPACT table.

    Args:
        impacts_json: JSON output from calculate_position_impact()
    """
    data = json.loads(impacts_json)
    impacts = data.get("position_impacts", [])

    if not impacts:
        return json.dumps({"written": 0, "table": "POSITION_IMPACT"})

    df = pd.DataFrame(impacts)
    df.columns = [c.upper() for c in df.columns]

    with results_conn() as conn:
        n = bulk_insert(conn, "POSITION_IMPACT", df, _get_schema(), _get_database())

    return json.dumps({"written": n, "table": "POSITION_IMPACT"})


def finalise_recon_run(run_id: str, status: str, error_message: str | None = None) -> str:
    """
    Update the RECON_RUNS record with final status and completion timestamp.
    """
    schema = _get_schema()
    database = _get_database()

    sql = f"""
        UPDATE {database}.{schema}.RECON_RUNS
        SET STATUS = %s,
            COMPLETED_AT = %s,
            ERROR_MESSAGE = %s
        WHERE RUN_ID = %s
    """
    with results_conn() as conn:
        execute_ddl(conn, sql)   # execute_ddl handles commit

    return json.dumps({"run_id": run_id, "status": status, "updated": True})
