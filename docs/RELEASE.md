# Release Guide — recon_ai

This document covers how to deploy the recon_ai pipeline and dbt semantic layer
from development to production. It applies to both the Python reconciliation
pipeline and the dbt models.

---

## Environment Overview

The project has two environments. Each writes to a separate set of schemas in
Snowflake so development work never touches production data.

| | Dev | Prod |
|---|---|---|
| Pipeline source data | `RECON_DB.RESULTS.*`, `RECON_DB.OBSERVABILITY.*` (shared read-only) | Same |
| Pipeline output | Same Snowflake databases — results are isolated by run metadata | Same |
| dbt staging schema | `RECON_DB.dbt_dev_dbt_staging` | `RECON_DB.dbt_prod_dbt_staging` |
| dbt mart schema | `RECON_DB.dbt_dev_dbt_marts` | `RECON_DB.dbt_prod_dbt_marts` |
| dbt target | `dev` (default in `profiles.yml`) | `prod` (Airflow sets `--target prod`) |
| Airflow DAG | Not scheduled — manual trigger only | Scheduled: 06:00 ET daily |
| Threads | 4 | 8 |
| Snowflake query tag | `recon_ai_dbt_dev` | `recon_ai_dbt_prod` |

The `profiles.yml` target is the single switch that controls which environment
dbt writes to. The Python pipeline uses the same Snowflake credentials in both
environments — environment isolation for the pipeline is achieved by using
separate Airflow connections and `.env` files.

---

## First-Time Setup (any environment)

Run these once when setting up a fresh environment. They are idempotent — safe
to re-run.

### 1. Python pipeline tables

```bash
# Creates RECON_DB.RESULTS tables (RECON_RUNS, BREAKS, MATCHED_TRADES, POSITION_IMPACT)
python main.py --setup-tables

# Creates RECON_DB.OBSERVABILITY tables and raw SQL views
python observability/setup.py
```

### 2. Database migration — add new columns

Run before the first dbt run. This adds columns that the dbt models depend on
but that were not present in the original schema:

```bash
snowsql -a $SNOWFLAKE_ACCOUNT -u $SNOWFLAKE_USER \
  -d RECON_DB \
  -f sql/migrations/001_add_enrichment_source_and_call_purpose.sql
```

What this migration does:
- Adds `ENRICHMENT_SOURCE VARCHAR(32)` to `RESULTS.BREAKS` (backfills existing rows to `'TEMPLATE_ONLY'`)
- Adds `CONFIDENCE VARCHAR(16)` to `RESULTS.BREAKS`
- Adds `NEEDS_HUMAN_REVIEW BOOLEAN` to `RESULTS.BREAKS`
- Adds `CALL_PURPOSE VARCHAR(64)` to `OBSERVABILITY.AI_API_CALLS`

All statements use `ADD COLUMN IF NOT EXISTS` — safe to re-run.

### 3. dbt dependencies

```bash
cd dbt
pip install dbt-snowflake    # if not already installed
dbt deps                     # installs dbt_utils
```

### 4. Set the profiles directory

dbt looks for `profiles.yml` in `~/.dbt/` by default. Point it at the project's
`dbt/` folder instead:

```bash
# Linux / macOS
export DBT_PROFILES_DIR=/path/to/recon_ai/dbt

# Windows PowerShell
$env:DBT_PROFILES_DIR = "C:\path\to\recon_ai\dbt"

# Or pass it inline per command
dbt run --profiles-dir ./dbt
```

---

## Dev Workflow

### Step 1 — Verify the connection

```bash
cd dbt
dbt debug --target dev
```

Confirms credentials, warehouse access, and that the database exists. Fix any
failures here before running models.

### Step 2 — Build all models in dev

```bash
dbt run --target dev
```

Creates `RECON_DB.dbt_dev_dbt_staging.*` (views) and
`RECON_DB.dbt_dev_dbt_marts.*` (tables). Production schemas are not touched.

### Step 3 — Run all tests

```bash
dbt test --target dev
```

Tests declared in `_staging.yml` and `_marts.yml`:
- `not_null` and `unique` on all primary keys
- `accepted_values` on `status`, `severity`, `break_type`, `enrichment_source`, `event_type`

All tests must pass before promoting to production.

### Step 4 — Spot-check the mart tables

Connect to Snowflake and verify the data looks correct:

```sql
-- One row per completed run, run_outcome correctly classified
SELECT run_outcome, COUNT(*) AS run_count
FROM RECON_DB.dbt_dev_dbt_marts.fct_recon_runs
GROUP BY 1;

-- HIGH breaks should be CLAUDE_ENHANCED, others TEMPLATE_ONLY
SELECT enrichment_source, severity, COUNT(*) AS break_count
FROM RECON_DB.dbt_dev_dbt_marts.fct_breaks
GROUP BY 1, 2
ORDER BY 2, 1;

-- AI cost should only attribute to BREAK_ENRICHMENT calls
SELECT call_purpose, SUM(total_cost_usd) AS cost
FROM RECON_DB.dbt_dev_dbt_marts.fct_ai_usage
GROUP BY 1;

-- Recurrence labels should spread across the four categories
SELECT recurrence_label, COUNT(*) AS pattern_count
FROM RECON_DB.dbt_dev_dbt_marts.fct_break_trends
GROUP BY 1;
```

### Faster iteration — rebuild a single model

```bash
# Rebuild one mart model only
dbt run --target dev --select fct_breaks

# Rebuild one model and everything downstream of it
dbt run --target dev --select fct_recon_runs+

# Rebuild marts only (staging views are cheap so rarely need rebuilding)
dbt run --target dev --select marts
```

---

## Pre-Production Checklist

Go through this before every production release.

**Database migration**
- [ ] `sql/migrations/001_add_enrichment_source_and_call_purpose.sql` has been run against `RECON_DB` in production

**dbt**
- [ ] `dbt debug --target prod` succeeds
- [ ] `dbt run --target dev` completes without errors
- [ ] `dbt test --target dev` passes all tests
- [ ] Mart spot-checks pass (see Step 4 above)
- [ ] No model writes to `dbt_prod_*` schemas during dev testing (verify via Snowflake query history or `query_tag = 'recon_ai_dbt_dev'`)

**Python pipeline**
- [ ] `python main.py --setup-tables` has been run (new environments only)
- [ ] `python observability/setup.py` has been run (new environments only)
- [ ] All `← REPLACE` markers resolved in `config/field_mappings.yaml`
- [ ] `config/business_rules.yaml` tolerances reviewed for the target environment
- [ ] `config/alert_routing.yaml` points to production Slack channels, email groups, and Teams webhooks
- [ ] `.env` contains production credentials — `ANTHROPIC_API_KEY`, `SNOWFLAKE_*`, webhook URLs

**Airflow**
- [ ] Airflow connections `snowflake_recon` and `anthropic_api` updated with production credentials
- [ ] DAG `trade_reconciliation_nightly` is unpaused
- [ ] `dbt_refresh_marts` task is present downstream of the pipeline task
- [ ] A manual trigger for today's date runs successfully end to end

---

## Promoting to Production

Once all checklist items are green:

```bash
cd dbt

# 1. Full build in prod
dbt run --target prod

# 2. Run all tests against prod data
dbt test --target prod
```

This writes to `RECON_DB.dbt_prod_dbt_staging.*` and
`RECON_DB.dbt_prod_dbt_marts.*`. Point dashboards at the `dbt_prod_dbt_marts`
schema.

For ongoing releases (model logic changes only), running marts is sufficient:

```bash
dbt run --target prod --select marts
dbt test --target prod --select marts
```

---

## Airflow Integration (Production Scheduling)

The dbt mart refresh runs as a downstream task of `trade_reconciliation_nightly`
every day after the pipeline completes.

Add the following task to `airflow/dags/recon_dag.py`:

```python
from airflow.operators.bash import BashOperator

dbt_refresh = BashOperator(
    task_id="dbt_refresh_marts",
    bash_command=(
        "cd {{ var('recon_ai_path') }}/dbt && "
        "DBT_PROFILES_DIR=. "
        "dbt run --target prod --select marts && "
        "dbt test --target prod --select marts"
    ),
    env={
        "SNOWFLAKE_ACCOUNT":          "{{ var('snowflake_account') }}",
        "SNOWFLAKE_USER":             "{{ var('snowflake_user') }}",
        "SNOWFLAKE_PASSWORD":         "{{ var('snowflake_password') }}",
        "SNOWFLAKE_WAREHOUSE":        "{{ var('snowflake_warehouse') }}",
        "SNOWFLAKE_RESULTS_DATABASE": "RECON_DB",
        "SNOWFLAKE_ROLE":             "SYSADMIN",
    },
    execution_timeout=timedelta(minutes=15),
    dag=dag,
)

# Chain: pipeline must complete before dbt refreshes
reconciliation_task >> dbt_refresh
```

Airflow variables (`var(...)`) keep credentials out of the DAG file. Set them
in the Airflow UI under **Admin → Variables**.

Expected daily sequence:

```
06:00 ET  trade_reconciliation_nightly starts
06:15 ET  Pipeline writes results to RECON_DB.RESULTS and RECON_DB.OBSERVABILITY
06:15 ET  dbt_refresh_marts starts (triggered by pipeline task success)
06:17 ET  dbt run --select marts completes (~2 minutes)
06:17 ET  dbt test --select marts completes (~30 seconds)
06:18 ET  Dashboard data is current for this trade date
```

---

## Environment Variable Reference

Both the Python pipeline and dbt read the same set of environment variables.
In development, set these in `.env` (copy from `.env.example`). In production,
set them as Airflow Variables or in your secrets manager.

| Variable | Required | Description |
|---|---|---|
| `SNOWFLAKE_ACCOUNT` | Yes | Snowflake account identifier (e.g. `xy12345.us-east-1`) |
| `SNOWFLAKE_USER` | Yes | Snowflake user |
| `SNOWFLAKE_PASSWORD` | Yes | Snowflake password |
| `SNOWFLAKE_WAREHOUSE` | Yes | Compute warehouse (e.g. `RECON_WH`) |
| `SNOWFLAKE_RESULTS_DATABASE` | No | Database for results (default: `RECON_DB`) |
| `SNOWFLAKE_ROLE` | No | Snowflake role (default: `SYSADMIN`) |
| `ANTHROPIC_API_KEY` | Yes | Claude API key — rotate every 90 days |

Never commit `.env` to git. It is listed in `.gitignore`.

---

## Isolating Source Data for a True Dev Sandbox

By default both environments read from the same `RECON_DB.RESULTS` and
`RECON_DB.OBSERVABILITY` tables — only the dbt output schemas differ. This is
fine for most work. If you need to test against a separate copy of source data
(e.g. synthetic or masked data), override the source vars at runtime:

```bash
dbt run --target dev \
  --vars '{"results_database": "RECON_DB_DEV", "results_schema": "RESULTS_SAMPLE", "observability_database": "RECON_DB_DEV", "observability_schema": "OBSERVABILITY_SAMPLE"}'
```

The vars `results_database`, `results_schema`, `observability_database`, and
`observability_schema` are declared in `dbt/dbt_project.yml` and referenced in
`dbt/models/staging/_staging.yml`. The default values point at the shared
production source tables.

---

## Rollback

### Rolling back a dbt release

dbt does not have built-in rollback. The practical approach:

1. Re-run the previous version of the models from the prior git commit:

   ```bash
   git checkout <previous-commit-sha> -- dbt/models/
   dbt run --target prod --select marts
   ```

2. Once stable, re-apply the intended changes or revert the git commit fully:

   ```bash
   git revert <bad-commit-sha>
   git push origin main
   dbt run --target prod --select marts
   ```

Staging models are views — they update immediately on `dbt run` with no data
migration needed. Mart models are tables — a re-run replaces them in full.

### Rolling back a Python pipeline release

The pipeline writes new rows on every run — it does not overwrite. To suppress
a bad run from dashboards, filter by the latest run ID per trade date:

```sql
-- Identify runs to suppress
SELECT RUN_ID, RUN_TIMESTAMP, STATUS
FROM RECON_DB.RESULTS.RECON_RUNS
WHERE TRADE_DATE = '2024-01-15'
ORDER BY RUN_TIMESTAMP DESC;

-- Dashboards should always use this pattern to get only the latest run
SELECT * FROM RECON_DB.dbt_prod_dbt_marts.fct_recon_runs
WHERE trade_date = '2024-01-15'
  AND run_timestamp = (
    SELECT MAX(run_timestamp)
    FROM RECON_DB.dbt_prod_dbt_marts.fct_recon_runs
    WHERE trade_date = '2024-01-15'
  );
```

If rows must be physically removed, the operations team should contact the data
engineering lead — deletes against `RECON_DB.RESULTS` require approval.

---

## dbt Commands Quick Reference

```bash
# Verify connection
dbt debug --target dev

# Install packages (run once after clone or after packages.yml changes)
dbt deps

# Full build
dbt run --target dev
dbt run --target prod

# Marts only (routine production refresh)
dbt run --target prod --select marts

# Single model
dbt run --target dev --select fct_breaks

# Model + all downstream dependents
dbt run --target dev --select fct_recon_runs+

# Run all tests
dbt test --target dev
dbt test --target prod

# Run tests for one model
dbt test --target dev --select fct_breaks

# Browse model lineage (opens browser at localhost:8080)
dbt docs generate && dbt docs serve

# Clean compiled files
dbt clean
```
