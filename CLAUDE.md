# CLAUDE.md — AI Context for recon_ai

This file is automatically loaded by Claude Code at the start of every session.
It gives the AI complete project context so work can resume immediately without re-explanation.

> **Session start:** Read [CHANGELOG.md](CHANGELOG.md) before doing any work.
> It contains the last 10 commits (auto-updated after every commit) and the full
> narrative history of all reliability fixes. This keeps you current on recent changes
> without needing to ask the user.

---

## What This Project Does

AI-powered nightly trade reconciliation pipeline (OMS vs broker confirms → break classification → Claude enrichment → Snowflake → tiered alerts). See [README.md](README.md) for full overview and setup.

---

## Directory Structure and Component Roles

```
recon_ai/
│
├── CLAUDE.md                      ← YOU ARE HERE — AI context file
├── README.md                      ← Human onboarding
│
├── config/                        ← ALL DOMAIN KNOWLEDGE LIVES HERE
│   │                              Full reference: docs/CONFIG_GUIDE.md
│   ├── business_rules.yaml        # matching.tolerances (per asset class)
│   │                              # matching.counterparty_normalization (case, suffixes)
│   │                              # breaks.types + breaks.severity_thresholds
│   │                              # position.dv01_config, fx_rate_fallback
│   │                              # cli.exit_codes (Airflow/monitoring integration)
│   ├── field_mappings.yaml        # Snowflake DB/schema/table/column names
│   │                              # fx_rates → points to FX rate source table
│   │                              # EDIT THIS FIRST when source tables change
│   ├── alert_routing.yaml         # channels (Slack/email/Teams aliases + URLs)
│   │                              # routing_matrix (severity × asset class → who gets what)
│   │                              # alert_settings (digest mode, AI explanation toggle)
│   │                              # notification_formatting (bot name, colours, footer)
│   └── system_prompt.md           # Free-form domain knowledge fed to Claude
│                                  # ADD: counterparty aliases, data quirks, calendar
│
├── src/                           ← MAIN RECON PIPELINE — independent of observability
│   ├── agents/
│   │   ├── reconciliation_agent.py  # ENTRY POINT — Claude orchestration
│   │   │                            # Imports TrackedAnthropic (not plain Anthropic)
│   │   │                            # Logs STARTED/COMPLETED/FAILED run events
│   │   └── prompts.py               # All prompt text — edit wording here, not in agent
│   │
│   ├── tools/                     # Pure Python business logic — NO AI imports
│   │   ├── data_loader.py           # Reads TRADES_DB + EXECUTIONS_DB via SQL
│   │   ├── matcher.py               # Rule-based matching engine (2 passes)
│   │   ├── break_classifier.py      # Classifies break type + severity
│   │   ├── position_impact.py       # P&L, cash, risk metrics — has 2 TODOs (see below)
│   │   └── reporter.py              # Writes to RECON_DB result tables
│   │
│   ├── data/
│   │   ├── models.py                # All Pydantic models: BookedTrade, BreakRecord, etc.
│   │   └── snowflake_connector.py   # 3 connection context managers + DDL for result tables
│   │
│   ├── exceptions.py                # Typed exception hierarchy — DataLoadError,
│   │                                # DataQualityError, EnrichmentError, etc.
│   │                                # All extend ReconBaseError
│   ├── config_validator.py          # Validates env vars + YAML config on startup
│   │                                # Called from main.py before any connections open
│   │                                # Exits with code 2 on failure, reports ALL issues at once
│   │
│   ├── notifications/
│   │   ├── retry.py                 # retry_with_backoff() + TransientError
│   │   │                            # Used by all three notifiers for network/webhook retries
│   │   ├── slack_notifier.py        # SLACK_WEBHOOK_URL env var; retries on 429/5xx
│   │   ├── email_notifier.py        # SMTP_HOST/USER/PASSWORD env vars; retries on SMTP drops
│   │   ├── teams_notifier.py        # Teams webhook URLs from alert_routing.yaml; retries
│   │   └── alert_router.py          # Reads routing matrix, dispatches to all 3 channels
│   │                                # _record_delivery() writes to OBSERVABILITY (fire-and-forget)
│   │
│   └── schemas/
│       └── recon_output.py          # Pydantic schema for Claude's final ReconSummary
│
├── observability/                 ← INDEPENDENT DATA CAPTURE LAYER
│   ├── models.py                    # AIAPICallEvent, ToolCallEvent, RunEvent, UserActivityEvent
│   │                                # DataQualityMetricEvent, NotificationDeliveryEvent
│   ├── tracker.py                   # TrackedAnthropic — drop-in for anthropic.Anthropic()
│   ├── sink.py                      # Snowflake writes to OBSERVABILITY schema + DDL + views
│   │                                # 6 tables, 7 views
│   └── setup.py                     # Run once: creates tables and views
│
├── airflow/
│   └── dags/recon_dag.py            # DAG: validate_snowflake_connections → run_reconciliation
│
├── tests/
│   ├── conftest.py                  # sys.path setup for test imports
│   ├── unit/                        # 126 tests — no Snowflake, no AI key required
│   │   ├── test_matcher.py          # 20 tests: tolerances, pass-1, pass-2, composite key
│   │   ├── test_break_classifier.py # 17 tests: severity, orphan, summary structure
│   │   ├── test_break_enricher.py   # 35 tests: all 7 break types, explain/recommend
│   │   ├── test_alert_router.py     # 12 tests: dispatch, SKIPPED, FAILURE, observability safety
│   │   └── test_position_impact.py  # 42 tests: BUY/SELL direction, P&L, DV01, delta, portfolio
│   └── integration/                 # Full pipeline tests
│
├── pytest.ini                       # Test discovery config (testpaths = tests)
├── main.py                          # CLI: python main.py --date YYYY-MM-DD
└── .env.example                     # Template — copy to .env, never commit .env
```

---

## Architecture Rules — Do Not Violate

1. **`src/tools/` has zero AI imports** — all business logic is pure Python, unit-testable without mocking Claude
2. **`observability/` has zero imports from `src/`** — it is fully independent
3. **`src/` imports from `observability/` in exactly ONE place** — `reconciliation_agent.py` line: `client = TrackedAnthropic(...)`
4. **Config files are the single source of truth** — never hardcode table names, tolerances, or channel IDs in Python
5. **Observability never crashes the main job** — all sink writes are wrapped in try/except and log WARNING (never raises)
6. **Pipeline is hard-coded Python** — `reconciliation_agent.py` calls `src/tools/` functions directly in fixed order; Claude is NOT the orchestrator

---

## Known TODOs (incomplete placeholders)

| File | Line area | What to implement |
|---|---|---|
| [src/tools/position_impact.py](src/tools/position_impact.py) | `_get_fx_rate()` | Real Snowflake FX rate lookup — config is wired in `field_mappings.yaml → fx_rates`, uncomment the SQL block once MARKET_DATA_DB is live |
| [src/tools/position_impact.py](src/tools/position_impact.py) | `_get_last_price()` | Last known price lookup from Snowflake market data |
| `src/tools/data_loader.py` | `load_booked_trades()` / `load_executed_transactions()` | SFTP source mode (`source: sftp` in field_mappings.yaml) is configured but not implemented — only Snowflake path works |
| [config/system_prompt.md](config/system_prompt.md) | Counterparty Aliases section | Fill in real counterparty alias mappings |
| [config/system_prompt.md](config/system_prompt.md) | Known Data Quality Issues | Fill in broker-specific data quirks |
| [config/field_mappings.yaml](config/field_mappings.yaml) | All `← REPLACE` lines | Real Snowflake DB/schema/table/column names |
| [config/alert_routing.yaml](config/alert_routing.yaml) | All `← REPLACE` lines | Real Slack channels, email addresses, Teams webhooks |

---

## Environment Variables Required

```bash
ANTHROPIC_API_KEY              # Claude API key
SNOWFLAKE_ACCOUNT              # e.g. xy12345.us-east-1
SNOWFLAKE_USER
SNOWFLAKE_PASSWORD
SNOWFLAKE_WAREHOUSE            # e.g. RECON_WH
SNOWFLAKE_ROLE                 # optional
SNOWFLAKE_TRADES_DATABASE      # Source A: OMS trades
SNOWFLAKE_EXECUTIONS_DATABASE  # Source B: Broker confirms
SNOWFLAKE_RESULTS_DATABASE     # Output + observability
SNOWFLAKE_RESULTS_SCHEMA       # default: RESULTS
SLACK_WEBHOOK_URL
SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD / EMAIL_FROM
RECON_AI_PATH                  # Airflow worker: absolute path to this project
AIRFLOW_DAG_OWNER              # Airflow: team name shown as DAG owner (default: recon-team)
AIRFLOW_FAILURE_EMAIL          # Airflow: email notified on DAG task failure
RECON_USER                     # optional: username for user activity logging (manual runs)
```

---

## Snowflake Schema Map

See [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) for full table and field reference.

---

## How to Extend This Project

**Add a new instrument type:**
1. Add tolerance block to `config/business_rules.yaml` under `matching.tolerances`
2. Add risk metrics to `position.compute_risk_metrics`
3. Add alert routing to `config/alert_routing.yaml` under `routing_matrix`
4. Add to `InstrumentType` enum in `src/data/models.py`
5. No other code changes needed

**Add a new break type:**
1. Add to `BreakType` enum in `src/data/models.py`
2. Add detection logic in `src/tools/break_classifier.py`
3. Add severity rule in `config/business_rules.yaml`

**Add a new notification channel:**
1. Create `src/notifications/new_channel_notifier.py`
2. Add channel config to `config/alert_routing.yaml`
3. Wire into `src/notifications/alert_router.py`

**Add a new pipeline step:**
1. Implement function in `src/tools/`
2. Call it directly in `run_reconciliation()` in `src/agents/reconciliation_agent.py` at the appropriate step
3. If it produces break context Claude should know about, pass it into `build_enrichment_prompt()` in `src/agents/prompts.py`

**Add a new observability event:**
1. Add model to `observability/models.py`
2. Add table DDL to `OBSERVABILITY_DDL` in `observability/sink.py`
3. Add write method to `ObservabilitySink`
4. Run `python observability/setup.py` to create the table

---

## Git / Branching Convention

- `main` — production-ready code, always deployable
- Feature branches: `feat/description` (e.g. `feat/add-cds-instrument-type`)
- Fix branches: `fix/description`
- Never commit `.env` — credentials stay local only
- Commit messages follow: `<type>: <short description>` with Co-Authored-By Claude tag
