"""
Airflow DAG — Nightly Trade Reconciliation
Runs every weekday night after market close.

Schedule: Mon–Fri at 20:00 UTC (adjust to your market close + buffer)
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.dates import days_ago


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

    # Ensure recon_ai is on the path — adjust if your Airflow setup differs
    sys.path.insert(0, os.environ.get("RECON_AI_PATH", "/opt/airflow/recon_ai"))

    from src.agents.reconciliation_agent import run_reconciliation

    # Use the logical execution date as the trade date
    execution_date = context["logical_date"]
    trade_date = execution_date.strftime("%Y-%m-%d")

    # Skip weekends (Airflow can also handle this via schedule, but double-check)
    if execution_date.weekday() >= 5:   # 5=Sat, 6=Sun
        print(f"Skipping weekend date: {trade_date}")
        return {"skipped": True, "trade_date": trade_date}

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
    description="Nightly AI-powered trade reconciliation (booked vs executed)",
    default_args=default_args,
    schedule_interval="0 20 * * 1-5",   # Mon–Fri at 20:00 UTC
    start_date=days_ago(1),
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
