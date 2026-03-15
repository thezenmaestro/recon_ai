"""
One-time setup script — creates all OBSERVABILITY tables and views in Snowflake.

Run once:
    python observability/setup.py

Safe to re-run (all statements use IF NOT EXISTS / CREATE OR REPLACE).
"""
from __future__ import annotations

import os
import sys

# Allow running from project root without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv optional — env vars may already be set


def main() -> None:
    from observability.sink import OBSERVABILITY_DDL
    import snowflake.connector

    print("Connecting to Snowflake...")
    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        database=os.environ["SNOWFLAKE_RESULTS_DATABASE"],
        role=os.environ.get("SNOWFLAKE_ROLE", ""),
    )

    print(f"Connected. Creating OBSERVABILITY schema and tables in "
          f"{os.environ['SNOWFLAKE_RESULTS_DATABASE']}...")

    with conn.cursor() as cur:
        for statement in OBSERVABILITY_DDL.strip().split(";"):
            stmt = statement.strip()
            if not stmt or stmt.startswith("--"):
                continue
            print(f"  → {stmt[:70].replace(chr(10), ' ')}...")
            cur.execute(stmt)

    conn.commit()
    conn.close()

    print("\nObservability setup complete.")
    print("Tables created:")
    print("  OBSERVABILITY.AI_API_CALLS")
    print("  OBSERVABILITY.TOOL_CALLS")
    print("  OBSERVABILITY.RUN_EVENTS")
    print("  OBSERVABILITY.USER_ACTIVITY")
    print("\nViews created:")
    print("  OBSERVABILITY.V_DAILY_AI_COST")
    print("  OBSERVABILITY.V_MONTHLY_AI_COST")
    print("  OBSERVABILITY.V_TOOL_PERFORMANCE")
    print("  OBSERVABILITY.V_RUN_HISTORY")
    print("  OBSERVABILITY.V_USER_ACTIVITY")
    print("\nPoint Sigma / Basedash at these views to build your dashboards.")


if __name__ == "__main__":
    main()
