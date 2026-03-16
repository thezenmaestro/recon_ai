# Architecture — recon_ai

## System Overview

**Trigger:** Airflow DAG `trade_reconciliation_nightly` (daily 06:00 ET) or `python main.py --date`

**Pipeline** — hard-coded Python in `reconciliation_agent.py` (Claude is NOT the orchestrator):
1. `load_booked_trades()` / `load_executed_transactions()` — `data_loader.py`
2. `match_transactions()` — `matcher.py` (exact key → composite key)
3. `classify_breaks()` + `enrich_breaks_locally()` — `break_classifier.py` (Python templates, all breaks)
4. `_enrich_with_claude()` — **one** Claude Opus 4.6 API call (HIGH breaks only; skipped if none)
5. `calculate_position_impact()` — `position_impact.py`
6. `write_*()` — `reporter.py` → Snowflake RECON_DB.RESULTS.*
7. `route_alerts()` — `alert_router.py` → Slack / Email / Teams

**Observability** (`observability/` — fully independent of `src/`):
- `TrackedAnthropic` wrapper captures tokens, cost, latency, tool calls, run events
- `data_loader` and `alert_router` emit data quality and delivery records directly
- All writes fire-and-forget (try/except → WARNING); never crashes the main job

**Snowflake layout:**
- `TRADES_DB.OMS.BOOKED_TRADES` / `EXECUTIONS_DB.CONFIRMS.EXECUTED_TRANSACTIONS` — read only
- `RECON_DB.RESULTS.*` — pipeline outputs (4 tables)
- `RECON_DB.OBSERVABILITY.*` — tracking (6 tables, 7 views)
- `RECON_DB.dbt_marts.*` — 5 dashboard-ready fact tables built by dbt

**Notifications** (tiered by severity × asset class):
- LOW ($0–10K) → ops only · MEDIUM ($10–100K) → ops + desk head · HIGH ($100K+) → + risk (+ mgmt for bonds)

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

All `ObservabilitySink` write methods catch exceptions silently and log a `WARNING`.
The main recon job is never blocked or crashed by a tracking failure.

Two additional observability streams are written by pipeline components directly
(not via `TrackedAnthropic`):

| Stream | Written by | When |
|---|---|---|
| `DATA_QUALITY_METRICS` | `data_loader._emit_data_quality()` | After every `load_booked_trades()` and `load_executed_transactions()` call — records row count, null rates, query latency, and outcome |
| `NOTIFICATION_DELIVERIES` | `alert_router._record_delivery()` | After every `_dispatch()` call — records channel type, name, break count, status (`SUCCESS` / `FAILURE` / `SKIPPED`), and retry count |

Both helpers use the same fire-and-forget pattern: lazy imports inside `try/except`,
`logger.warning` on failure, never raises.

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

## Typed Exception Hierarchy

All pipeline exceptions extend `ReconBaseError` from `src/exceptions.py`.
Callers can catch the specific subclass to distinguish retry-safe vs non-retry
failures:

| Exception | Raised by | Safe to retry? |
|---|---|---|
| `DataLoadError` | `data_loader.py` | Yes — transient Snowflake connection issue |
| `DataQualityError` | `data_loader.py` | No — fix source data first |
| `MatchingError` | `matcher.py` | Investigate — unexpected input shape |
| `ClassificationError` | `break_classifier.py` | Investigate |
| `EnrichmentError` | `reconciliation_agent.py` | Yes if API timeout; No if auth |
| `ReportingError` | `reporter.py` | Yes — transient Snowflake write failure |
| `AlertingError` | `alert_router.py` | Yes (retry built into notifiers) |
| `ConfigValidationError` | `config_validator.py` | No — fix config first |

---

## Notification Retry Behaviour

All three notification channels (Slack, email, Teams) retry on transient
failures using exponential backoff with jitter:

```
src/notifications/retry.py

retry_with_backoff(fn, attempts=3, base_delay=1.0, max_delay=30.0, jitter=0.5)
  Attempt 1 → fails → wait 1.0–1.5 s
  Attempt 2 → fails → wait 2.0–2.5 s
  Attempt 3 → fails → log ERROR, re-raise
```

Callers raise `TransientError` for retryable failures (network, HTTP 429/5xx,
SMTP connection drop). Non-transient failures (auth errors, bad recipients)
propagate immediately without retrying.

---

## Failure Modes and Recovery

| Failure | Impact | Recovery |
|---|---|---|
| Snowflake connection lost mid-run | Run marked FAILED in RECON_RUNS | Re-trigger for same date: `python main.py --date YYYY-MM-DD` |
| Claude API error | Run marked FAILED | Check ANTHROPIC_API_KEY; re-trigger |
| Partial tool failure | Claude logs error, continues where possible | Check Airflow logs; review RECON_RUNS.ERROR_MESSAGE |
| Observability write fails | WARNING logged, no impact on recon | Check SNOWFLAKE_RESULTS_DATABASE access |
| Alert delivery fails after retries | WARNING logged, FAILURE row in NOTIFICATION_DELIVERIES | Query `V_NOTIFICATION_DELIVERIES`; manually notify if needed |
| Duplicate run for same date | Second run writes additional rows | Filter by max(RUN_TIMESTAMP) per TRADE_DATE in queries |
| Config invalid at startup | Process exits with code 2 before any Snowflake connections | Fix reported config errors; re-trigger |
| FX / price stubs in use | WARNING logged; P&L and notional may be inaccurate | Implement `_get_fx_rate()` and `_get_last_price()` in `position_impact.py` |

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
