# recon_ai — dbt Semantic Layer

This dbt project models all reconciliation and observability data into a
clean semantic layer for dashboards (Sigma, Basedash, Tableau, etc.) and
AI-assisted analysis.

---

## Quick Start

```bash
# Install dbt-snowflake
pip install dbt-snowflake

# Install dbt packages (dbt_utils)
cd dbt/
dbt deps

# Verify connection (uses env vars from .env)
dbt debug

# Run all models
dbt run

# Run tests
dbt test

# Generate and serve docs
dbt docs generate && dbt docs serve
```

---

## Environment Variables

This project reads Snowflake credentials from env vars (same as the recon pipeline):

```
SNOWFLAKE_ACCOUNT
SNOWFLAKE_USER
SNOWFLAKE_PASSWORD
SNOWFLAKE_WAREHOUSE
SNOWFLAKE_RESULTS_DATABASE   (default: RECON_DB)
SNOWFLAKE_ROLE               (default: SYSADMIN)
```

Copy `profiles.yml` to `~/.dbt/profiles.yml` or set `DBT_PROFILES_DIR=./dbt`.

---

## Project Structure

```
dbt/
├── dbt_project.yml          ← Project config, materializations
├── profiles.yml             ← Snowflake connection (copy to ~/.dbt/)
├── packages.yml             ← dbt_utils dependency
└── models/
    ├── staging/             ← 1:1 with raw tables; clean + rename + cast
    │   ├── _staging.yml     ← Source definitions + staging model docs
    │   ├── stg_recon_runs.sql
    │   ├── stg_breaks.sql
    │   ├── stg_matched_trades.sql
    │   ├── stg_position_impact.sql
    │   ├── stg_ai_api_calls.sql
    │   ├── stg_tool_calls.sql
    │   ├── stg_run_events.sql
    │   └── stg_user_activity.sql
    └── marts/               ← Business-level joins; materialised as tables
        ├── _marts.yml       ← Mart model docs + column tests
        ├── fct_recon_runs.sql        ← Primary run health dashboard table
        ├── fct_breaks.sql            ← Ops investigation + break analysis
        ├── fct_matched_trades.sql    ← Settlement confirmation tracking
        ├── fct_ai_usage.sql          ← AI cost monitoring + ROI metrics
        └── fct_break_trends.sql      ← Historical pattern detection (90-day)
```

---

## Data Sources

| Source | Snowflake location | Written by |
|---|---|---|
| `recon_runs` | `RECON_DB.RESULTS.RECON_RUNS` | `reporter.py` |
| `breaks` | `RECON_DB.RESULTS.BREAKS` | `reporter.py` |
| `matched_trades` | `RECON_DB.RESULTS.MATCHED_TRADES` | `reporter.py` |
| `position_impact` | `RECON_DB.RESULTS.POSITION_IMPACT` | `reporter.py` |
| `ai_api_calls` | `RECON_DB.OBSERVABILITY.AI_API_CALLS` | `tracker.py` |
| `tool_calls` | `RECON_DB.OBSERVABILITY.TOOL_CALLS` | `tracker.py` |
| `run_events` | `RECON_DB.OBSERVABILITY.RUN_EVENTS` | `reconciliation_agent.py` |
| `user_activity` | `RECON_DB.OBSERVABILITY.USER_ACTIVITY` | `tracker.py` |

---

## Mart Models

### `fct_recon_runs`
Primary dashboard table. One row per completed run with:
- Match rate, SLA outcome (completed before 08:00 ET?)
- Break counts by severity
- AI cost attribution per run
- `run_outcome`: `CLEAN` | `BREAKS_FOUND` | `CRITICAL` | `FAILED`

### `fct_breaks`
Full break detail joined with position impact. One row per break:
- All break fields + AI explanation + recommended action
- `enrichment_source`: `CLAUDE_ENHANCED` (HIGH breaks) or `TEMPLATE_ONLY`
- P&L impact, settlement cash impact, DV01 from position_impact.py

### `fct_matched_trades`
Matched trade pairs with run context. Used for settlement confirmation rates.

### `fct_ai_usage`
AI cost monitoring per run:
- Cost per break, cost per HIGH break, cost per $1M notional
- Token breakdown (input / output / thinking)
- Latency stats
- `call_purpose` breakdown (BREAK_ENRICHMENT vs others)

### `fct_break_trends`
Historical pattern analysis (90-day window):
- Rolling 7/30/90-day break counts per (counterparty, instrument, break_type)
- `recurrence_label`: `ISOLATED` | `OCCASIONAL` | `RECURRING` | `CHRONIC`
- Days since last occurrence, pattern lifespan

---

## Key Derived Fields

| Field | Location | Description |
|---|---|---|
| `sla_met` | `fct_recon_runs` | Run completed before 08:00 ET |
| `match_rate_pct` | `fct_recon_runs` | matched / total_trades × 100 |
| `run_outcome` | `fct_recon_runs` | CLEAN / BREAKS_FOUND / CRITICAL / FAILED |
| `enrichment_source` | `fct_breaks` | CLAUDE_ENHANCED or TEMPLATE_ONLY |
| `is_claude_enhanced` | `fct_breaks` | Boolean: HIGH break enriched by Claude |
| `total_financial_exposure_usd` | `fct_breaks` | P&L + settlement cash impact |
| `cost_per_break_usd` | `fct_ai_usage` | AI spend per break found |
| `cost_per_high_break_usd` | `fct_ai_usage` | AI spend per HIGH-severity break |
| `recurrence_label` | `fct_break_trends` | Break pattern recurrence category |

---

## Running After Each Recon

The pipeline writes to raw tables immediately after each run. Run dbt to refresh
marts (typically < 60 seconds):

```bash
dbt run --select marts
```

Or schedule in Airflow as a downstream task of `trade_reconciliation_nightly`.

---

## Database Migration

Before first use, run the migration to add new columns to existing tables:

```bash
snowsql -a $SNOWFLAKE_ACCOUNT -u $SNOWFLAKE_USER \
  -d RECON_DB \
  -f sql/migrations/001_add_enrichment_source_and_call_purpose.sql
```

See [sql/migrations/001_add_enrichment_source_and_call_purpose.sql](../sql/migrations/001_add_enrichment_source_and_call_purpose.sql).
