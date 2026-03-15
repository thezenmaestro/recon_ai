"""
CLI entry point — run reconciliation locally for testing or manual reruns.

Usage:
    python main.py --date 2024-01-15
    python main.py --date 2024-01-15 --run-id RECON-MANUAL-001
    python main.py --setup-tables       # Create result tables in Snowflake (first-time setup)
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta


def main() -> None:
    parser = argparse.ArgumentParser(description="Trade Reconciliation CLI")
    parser.add_argument(
        "--date",
        type=str,
        default=str(date.today() - timedelta(days=1)),
        help="Trade date to reconcile (YYYY-MM-DD). Defaults to yesterday.",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Optional run ID. Auto-generated if not provided.",
    )
    parser.add_argument(
        "--setup-tables",
        action="store_true",
        help="Create result tables in Snowflake (run once during setup).",
    )
    args = parser.parse_args()

    # ── One-time setup ────────────────────────────────────────────────────────
    if args.setup_tables:
        from src.data.snowflake_connector import create_result_tables
        create_result_tables()
        print("Setup complete.")
        sys.exit(0)

    # ── Run reconciliation ────────────────────────────────────────────────────
    from src.agents.reconciliation_agent import run_reconciliation

    print(f"Starting reconciliation for trade date: {args.date}")
    summary = run_reconciliation(
        trade_date=args.date,
        run_id=args.run_id,
        triggered_by="manual",
    )

    print("\n" + "=" * 60)
    print(f"RECONCILIATION COMPLETE")
    print("=" * 60)
    print(f"Status          : {summary.overall_status}")
    print(f"Total Breaks    : {summary.total_breaks}")
    print(f"High Severity   : {summary.high_severity_count}")
    print(f"Notional at Risk: ${summary.total_notional_at_risk_usd:,.0f}")
    print(f"\nNarrative:\n{summary.narrative}")

    if summary.immediate_actions:
        print("\nImmediate Actions Required:")
        for i, action in enumerate(summary.immediate_actions, 1):
            print(f"  {i}. {action}")

    sys.exit(0 if summary.overall_status != "CRITICAL" else 1)


if __name__ == "__main__":
    main()
