# Architecture — recon_ai

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        AIRFLOW / CLI TRIGGER                        │
│              trade_reconciliation_nightly (daily 06:00 ET)          │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    reconciliation_agent.py                          │
│                                                                     │
│   Hard-coded Python pipeline (steps 1–7 run in fixed order).       │
│   Claude is NOT the orchestrator — Python calls each step directly. │
│                                                                     │
│   1. load_booked_trades()          → Python (data_loader.py)        │
│   2. load_executed_transactions()  → Python (data_loader.py)        │
│   3. match_transactions()          → Python (matcher.py)            │
│   4. classify_breaks()             → Python (break_classifier.py)   │
│      enrich_breaks_locally()       → Python templates (all breaks)  │
│      _enrich_with_claude()         → Claude Opus 4.6 ← ONE API CALL│
│                                      (HIGH breaks only, skipped if  │
│                                       no HIGH breaks exist)          │
│   5. calculate_position_impact()   → Python (position_impact.py)    │
│   6. write_matched_trades() / ...  → Python (reporter.py)           │
│   7. route_alerts()                → Python (alert_router.py)        │
└──────────────┬──────────────────────────────────────┬─────────────┘
               │                                      │
               ▼                                      ▼
┌──────────────────────────┐           ┌──────────────────────────────┐
│   src/tools/ (Python)    │           │   observability/ (independent)│
│                          │           │                              │
│  data_loader.py          │           │  TrackedAnthropic wrapper    │
│  matcher.py              │           │  captures on every API call: │
│  break_classifier.py     │           │  • tokens / cost / latency  │
│  position_impact.py      │           │  • tool names + duration    │
│  reporter.py             │           │  • run lifecycle events     │
│                          │           │  • user activity            │
│  No AI imports.          │           │                              │
│  Fully unit-testable.    │           │  Writes to OBSERVABILITY     │
└──────────┬───────────────┘           │  schema. Silent on failure.  │
           │                           └──────────────────────────────┘
           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          SNOWFLAKE                                  │
│                                                                     │
│  TRADES_DB.OMS.BOOKED_TRADES          (read only — Source A)       │
│  EXECUTIONS_DB.CONFIRMS.EXECUTED_TRANSACTIONS (read only — B)      │
│                                                                     │
│  RECON_DB.RESULTS.RECON_RUNS          (run metadata)               │
│  RECON_DB.RESULTS.MATCHED_TRADES      (confirmed matches)          │
│  RECON_DB.RESULTS.BREAKS              (breaks + AI explanations)   │
│  RECON_DB.RESULTS.POSITION_IMPACT     (P&L, cash, risk)            │
│                                                                     │
│  RECON_DB.OBSERVABILITY.AI_API_CALLS  (Claude usage per call)      │
│  RECON_DB.OBSERVABILITY.TOOL_CALLS    (tool invocations)           │
│  RECON_DB.OBSERVABILITY.RUN_EVENTS    (lifecycle events)           │
│  RECON_DB.OBSERVABILITY.USER_ACTIVITY (audit trail)                │
│  RECON_DB.OBSERVABILITY.V_*           (5 raw SQL views)            │
└──────────────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────┐
│              dbt SEMANTIC LAYER  (dbt run --select marts)           │
│              Airflow downstream task, runs after pipeline           │
│                                                                     │
│  RECON_DB.dbt_staging.*  — 8 views, 1:1 with raw tables            │
│    stg_recon_runs        stg_breaks          stg_matched_trades     │
│    stg_position_impact   stg_ai_api_calls    stg_tool_calls         │
│    stg_run_events        stg_user_activity                          │
│                                                                     │
│  RECON_DB.dbt_marts.*   — 5 Snowflake tables, dashboard-ready      │
│    fct_recon_runs   → run health, SLA, match rate, AI cost/run     │
│    fct_breaks       → ops investigation + position impact joined    │
│    fct_matched_trades → settlement confirmation tracking            │
│    fct_ai_usage     → cost per break / HIGH break / $1M notional   │
│    fct_break_trends → 90-day rolling counterparty/instrument ptrns │
└─────────────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   NOTIFICATIONS (parallel)                          │
│                                                                     │
│   Slack webhook → #recon-ops / #recon-{asset} / #recon-risk        │
│   SMTP email    → ops team / desk heads / risk / management        │
│   Teams webhook → ops / risk / management channels                 │
│                                                                     │
│   Routing: tiered by break severity × instrument type              │
│   LOW  ($0–10K)  → ops only                                        │
│   MED  ($10–100K)→ ops + desk head                                 │
│   HIGH ($100K+)  → ops + desk head + risk + (management for bonds) │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Matching Algorithm

The matcher makes **two passes** before declaring an unmatched break:

```
Pass 1 — Primary Key Match
  trade_id (OMS) ↔ trade_ref_id (broker confirm)
  │
  ├── Found → check price tolerance + qty tolerance + date tolerance
  │     ├── All within tolerance → MATCHED (EXACT)
  │     └── Outside tolerance   → not matched, try Pass 2
  │
  └── Not found → try Pass 2

Pass 2 — Composite Key Match
  (isin, normalised_counterparty, direction, settlement_date)
  │
  ├── Found → check price + qty tolerances
  │     ├── Within tolerance → MATCHED (COMPOSITE)
  │     └── Outside tolerance → UNMATCHED → break
  │
  └── Not found → UNMATCHED → break (type: UNEXECUTED)

Unmatched executions (orphan confirms — no corresponding booked trade)
are also flagged as breaks with type: ORPHAN_EXECUTION
```

Tolerances are looked up from `config/business_rules.yaml` per instrument type.
The `DEFAULT` block is used as fallback for unrecognised instrument types.

---

## AI Role — What Claude Does vs What Code Does

This is intentional and important. Claude is only used where human judgment adds value.

| Task | Done by | Why |
|---|---|---|
| Load data from SFTP / Snowflake | Python (`data_loader.py`) | Deterministic, testable |
| Rule-based matching | Python (`matcher.py`) | Fast, auditable, no hallucination risk |
| Break type classification | Python (`break_classifier.py`) | Rules-based, consistent |
| Severity scoring | Python (threshold lookup) | Must be consistent and auditable |
| **Template explanations (ALL breaks)** | **Python (`break_enricher.py`)** | Factual, deterministic, no API cost |
| **Pattern detection across breaks** | **Python (`break_enricher.py`)** | Counter-based, no API cost |
| **Enhance HIGH break explanations** | **Claude (single call)** | Risk nuance and judgment on material breaks |
| **Executive narrative + action list** | **Claude (same single call)** | Natural language for senior management |
| Write results to Snowflake | Python (`reporter.py`) | Deterministic, testable |
| Route alerts | Python (`alert_router.py`) | Rules-based |

**API call frequency:**
- Clean days (0 breaks): **0 Claude API calls**
- Breaks but no HIGH severity: **0 Claude API calls** (templates sufficient)
- Any HIGH severity break: **1 Claude API call** (HIGH breaks + narrative)

Claude uses **adaptive thinking** (`thinking: {type: "adaptive"}`) on that single call.

---

## Config-Driven Design

All parameters that a non-engineer might need to change live in YAML, not Python:

```
config/business_rules.yaml   → tolerances, severity thresholds
config/field_mappings.yaml   → Snowflake column names
config/alert_routing.yaml    → channel routing rules
config/system_prompt.md      → domain knowledge fed to Claude
```

**Consequence:** adding a new instrument type or adjusting a tolerance requires
only a YAML edit and no code deployment.

---

## Observability Independence Contract

The `observability/` module is designed to be completely decoupled:

```
observability/ imports:  anthropic, snowflake-connector, pydantic, pandas
                         (no imports from src/)

src/ imports from observability/:  only reconciliation_agent.py
                                   imports TrackedAnthropic and RunEvent/get_sink

If observability/ is deleted:  change 3 lines in reconciliation_agent.py
                                to restore plain anthropic.Anthropic() client
                                — everything else continues to work
```

All `ObservabilitySink` write methods catch exceptions silently and print a warning.
The main recon job is never blocked or crashed by a tracking failure.

---

## dbt Semantic Layer

The `dbt/` project transforms raw Snowflake tables into a clean semantic layer
that powers dashboards and AI analysis. It is completely independent of the
Python pipeline — it reads from the same raw tables the pipeline writes to.

```
dbt/
├── dbt_project.yml          ← Project config, materializations
├── profiles.yml             ← Snowflake connection (uses same env vars as pipeline)
├── packages.yml             ← dbt_utils
└── models/
    ├── staging/             ← Views: 1:1 with raw tables, clean + cast
    │   ├── stg_recon_runs.sql      → adds sla_met, match_rate_pct
    │   ├── stg_breaks.sql          → adds is_claude_enhanced, safe coalesces
    │   ├── stg_matched_trades.sql  → adds is_exact_match
    │   ├── stg_position_impact.sql → adds total_financial_exposure_usd
    │   ├── stg_ai_api_calls.sql    → adds call_succeeded, cost_per_1k_tokens
    │   ├── stg_tool_calls.sql      → adds call_succeeded
    │   ├── stg_run_events.sql      → adds duration_minutes
    │   └── stg_user_activity.sql   → adds occurred_date
    └── marts/               ← Tables: business joins, materialised in Snowflake
        ├── fct_recon_runs.sql      ← PRIMARY: run health, SLA, cost, outcomes
        ├── fct_breaks.sql          ← PRIMARY: ops investigation + position impact
        ├── fct_matched_trades.sql  ← settlement confirmation tracking
        ├── fct_ai_usage.sql        ← AI cost attribution + ROI metrics
        └── fct_break_trends.sql    ← 90-day rolling pattern detection
```

**Key derived fields added by dbt (not in raw tables):**

| Field | Model | How derived |
|---|---|---|
| `sla_met` | `fct_recon_runs` | `completed_at` converted to ET, hour < 08:00 |
| `run_outcome` | `fct_recon_runs` | `CLEAN / BREAKS_FOUND / CRITICAL / FAILED` |
| `match_rate_pct` | `fct_recon_runs` | `matched / nullif(total_trades, 0) × 100` |
| `ai_cost_usd` | `fct_recon_runs` | Sum of `AI_API_CALLS.cost_usd` per run |
| `cost_per_break_usd` | `fct_ai_usage` | Total cost / breaks found |
| `cost_per_high_break_usd` | `fct_ai_usage` | Total cost / HIGH breaks |
| `is_claude_enhanced` | `fct_breaks` | `enrichment_source = 'CLAUDE_ENHANCED'` |
| `total_financial_exposure_usd` | `fct_breaks` | P&L + settlement cash impact |
| `recurrence_label` | `fct_break_trends` | `ISOLATED / OCCASIONAL / RECURRING / CHRONIC` |
| `break_count_30d` | `fct_break_trends` | 30-day rolling window per counterparty/instrument/type |

**Running dbt:**
```bash
cd dbt && dbt run          # refresh all models
dbt run --select marts     # refresh marts only (< 60 seconds)
dbt test                   # run schema + not_null + unique tests
```

Before first use, run the migration to add new columns to existing Snowflake tables:
```bash
snowsql -d RECON_DB -f sql/migrations/001_add_enrichment_source_and_call_purpose.sql
```

---

## Data Flow — Detailed

```
1. LOAD (data_loader.py)
   Snowflake SQL → DataFrame → JSON string (trades_json, executions_json)
   All dates as YYYY-MM-DD strings. All numerics as float.

2. MATCH (matcher.py)
   Accepts: trades_json, executions_json
   Returns: { matched: [...], unmatched_trades: [...], unmatched_executions: [...] }
   Matched: { match_id, trade_id, execution_id, match_confidence, variances }

3. CLASSIFY (break_classifier.py)
   Accepts: match output JSON
   Returns: { breaks: [...], summary: { by_severity, total_notional } }
   Each break: all fields of BreakRecord EXCEPT ai_explanation, recommended_action

4. ENRICH (break_enricher.py → Claude)
   4a. enrich_breaks_locally(): deterministic templates for ALL breaks
       Sets enrichment_source='TEMPLATE_ONLY' on every break
   4b. _enrich_with_claude(): single API call (call_purpose='BREAK_ENRICHMENT')
       HIGH breaks only — sets enrichment_source='CLAUDE_ENHANCED' on response
       Claude adds narrative, key themes, and immediate actions

5. POSITION IMPACT (position_impact.py)
   Accepts: enriched breaks_json, trade_date
   Returns: { position_impacts: [...], portfolio_summary: {...} }
   Two TODO stubs: FX rate lookup + last-known price lookup

6. WRITE (reporter.py)
   Parallel inserts via write_pandas:
     MATCHED_TRADES, BREAKS (with AI text), POSITION_IMPACT, RECON_RUNS

7. ALERT (alert_router.py)
   Reads routing matrix from alert_routing.yaml
   Digest mode: groups all breaks into one message per channel
   Sends to all applicable Slack channels, email groups, Teams webhooks
```

---

## Failure Modes and Recovery

| Failure | Impact | Recovery |
|---|---|---|
| Snowflake connection lost mid-run | Run marked FAILED in RECON_RUNS | Re-trigger for same date: `python main.py --date YYYY-MM-DD` |
| Claude API error | Run marked FAILED | Check ANTHROPIC_API_KEY; re-trigger |
| Partial tool failure | Claude logs error, continues where possible | Check Airflow logs; review RECON_RUNS.ERROR_MESSAGE |
| Observability write fails | Warning printed, no impact on recon | Check SNOWFLAKE_RESULTS_DATABASE access |
| Alert delivery fails | Warning printed, results still in Snowflake | Manually query RECON_DB.RESULTS.BREAKS |
| Duplicate run for same date | Second run writes additional rows | Filter by max(RUN_TIMESTAMP) per TRADE_DATE in queries |

---

## Performance Characteristics

| Step | Typical duration (10K–500K records) |
|---|---|
| Load trades + executions | 10–60 seconds |
| Matching | 5–30 seconds (in-memory pandas) |
| Break classification | < 5 seconds |
| Claude enrichment | 30–120 seconds (depends on break count) |
| Position impact | 10–30 seconds |
| Snowflake writes | 5–20 seconds per table |
| Alert dispatch | 5–15 seconds |
| **Total** | **~2–5 minutes for typical runs** |

Airflow task timeout is set to 2 hours. Adjust in `airflow/dags/recon_dag.py`
`execution_timeout=timedelta(hours=2)` if volumes grow significantly.
