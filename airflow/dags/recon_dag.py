"""
Airflow DAG — Daily Trade Reconciliation (Canada / Eastern Time)
Runs every morning at 06:00 ET (America/Toronto), handles DST automatically.
Skips Canadian federal and Ontario provincial holidays.

Reports are published by 08:00 ET.
"""
from __future__ import annotations

import os
from datetime import timedelta

import pendulum

from airflow import DAG
from airflow.operators.python import PythonOperator


# =============================================================================
# DAG DEFAULT ARGS
# =============================================================================

default_args = {
    "owner": os.environ.get("AIRFLOW_DAG_OWNER", "recon-team"),
    "depends_on_past": False,
    "email": [os.environ.get("AIRFLOW_FAILURE_EMAIL", "ops-team@yourfirm.com")],
    "email_on_failure": True,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


# =============================================================================
# TASK FUNCTIONS
# =============================================================================

def run_recon(**context) -> dict:
    """
    Main reconciliation task.
    Imports are local so Airflow workers don't load heavy deps at parse time.
    """
    import sys
    import os
    import holidays

    # Ensure recon_ai is on the path — adjust if your Airflow setup differs
    sys.path.insert(0, os.environ.get("RECON_AI_PATH", "/opt/airflow/recon_ai"))

    from src.agents.reconciliation_agent import run_reconciliation

    # Use the logical execution date as the trade date (already in ET via DAG timezone)
    execution_date = context["logical_date"]
    trade_date = execution_date.strftime("%Y-%m-%d")
    trade_date_obj = execution_date.date()

    # Skip Canadian federal + Ontario provincial holidays
    ca_holidays = holidays.Canada(prov="ON")
    if trade_date_obj in ca_holidays:
        holiday_name = ca_holidays.get(trade_date_obj)
        print(f"Skipping Canadian holiday: {holiday_name} ({trade_date})")
        return {"skipped": True, "trade_date": trade_date, "reason": holiday_name}

    summary = run_reconciliation(
        trade_date=trade_date,
        triggered_by="airflow",
    )

    # Push summary to XCom for downstream tasks / monitoring
    context["ti"].xcom_push(key="recon_summary", value={
        "run_id": summary.run_id,
        "trade_date": summary.trade_date,
        "overall_status": summary.overall_status,
        "total_breaks": summary.total_breaks,
        "high_severity_count": summary.high_severity_count,
        "total_notional_at_risk_usd": summary.total_notional_at_risk_usd,
    })

    # Fail the DAG task if there are critical breaks — so PagerDuty/email fires
    if summary.overall_status == "CRITICAL":
        raise RuntimeError(
            f"CRITICAL reconciliation breaks detected for {trade_date}. "
            f"High severity breaks: {summary.high_severity_count}. "
            f"Notional at risk: ${summary.total_notional_at_risk_usd:,.0f}"
        )

    return {"status": summary.overall_status, "trade_date": trade_date}


def validate_snowflake_connections(**context) -> None:
    """Pre-flight check: verify Snowflake connections before running recon."""
    import sys, os
    sys.path.insert(0, os.environ.get("RECON_AI_PATH", "/opt/airflow/recon_ai"))

    from src.data.snowflake_connector import trades_conn, executions_conn, results_conn

    for name, conn_fn in [
        ("TRADES_DB", trades_conn),
        ("EXECUTIONS_DB", executions_conn),
        ("RECON_DB", results_conn),
    ]:
        with conn_fn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT CURRENT_VERSION()")
                version = cur.fetchone()[0]
        print(f"[{name}] Connected. Snowflake version: {version}")


# =============================================================================
# DAG DEFINITION
# =============================================================================

with DAG(
    dag_id="trade_reconciliation_nightly",
    description="Daily AI-powered trade reconciliation — 06:00 ET, reports by 08:00 ET. Skips Canadian holidays.",
    default_args=default_args,
    schedule_interval="0 6 * * *",       # 06:00 ET daily (DST handled by timezone below)
    start_date=pendulum.datetime(2024, 1, 1, tz="America/Toronto"),
    catchup=False,
    max_active_runs=1,                   # Never run two recon jobs simultaneously
    tags=["reconciliation", "trade-ops", "ai"],
) as dag:

    t_validate = PythonOperator(
        task_id="validate_snowflake_connections",
        python_callable=validate_snowflake_connections,
        doc_md="Verify all three Snowflake databases are reachable before starting.",
    )

    t_reconcile = PythonOperator(
        task_id="run_reconciliation",
        python_callable=run_recon,
        doc_md="Run the full AI-powered reconciliation pipeline for today's trade date.",
        execution_timeout=timedelta(hours=2),  # Hard limit — adjust for your volume
    )

    t_validate >> t_reconcile
