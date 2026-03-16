# recon_ai — AI-Powered Trade Reconciliation

Nightly reconciliation pipeline that matches booked trades against broker execution confirms,
classifies breaks, assesses position and P&L impact, and routes tiered alerts — orchestrated
by Claude Opus 4.6.

---

## What It Does

```
OMS (Booked Trades)          Broker Confirms (Executions)
        │                              │
        └──────────┬───────────────────┘
                   ▼
          Rule-based Matcher
          (exact key → composite key)
                   │
        ┌──────────┴──────────┐
        │                     │
    Matched              Unmatched (Breaks)
        │                     │
        │              Claude Opus 4.6
        │              ├── Classifies break type
        │              ├── Explains in plain English
        │              ├── Calculates position/P&L impact
        │              └── Recommends action
        │                     │
        └──────────┬───────────┘
                   ▼
            Snowflake (RECON_DB)
                   │
        ┌──────────┼──────────┐
        │          │          │
      Slack     Email      Teams
```

---

## Project Structure

```
recon_ai/
├── config/           ← domain knowledge (rules, mappings, alerts)
├── src/              ← reconciliation pipeline
│   ├── agents/       ← Claude AI orchestration
│   ├── tools/        ← pure Python business logic
│   ├── data/         ← Snowflake connectors and data models
│   └── notifications/← Slack, email, Teams
├── observability/    ← AI usage and run tracking (independent)
├── airflow/          ← Airflow DAG
├── docs/             ← detailed documentation
└── tests/            ← unit and integration tests
```

Full architecture detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

## Prerequisites

- Python 3.11+
- Access to three Snowflake databases (trades, executions, results)
- Anthropic API key
- Apache Airflow 2.8+ (for scheduled runs)

---

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/thezenmaestro/recon_ai.git
cd recon_ai
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — fill in all Snowflake credentials, API keys, and webhook URLs
```

### 3. Fill in your domain knowledge

Edit these four files before running anything:

| File | What to fill in | Full reference |
|---|---|---|
| [config/field_mappings.yaml](config/field_mappings.yaml) | Snowflake DB / schema / table / column names | [CONFIG_GUIDE.md → field_mappings](docs/CONFIG_GUIDE.md#configfield_mappingsyaml) |
| [config/business_rules.yaml](config/business_rules.yaml) | Tolerances, severity thresholds, risk metrics | [CONFIG_GUIDE.md → business_rules](docs/CONFIG_GUIDE.md#configbusiness_rulesyaml) |
| [config/alert_routing.yaml](config/alert_routing.yaml) | Slack channels, email addresses, Teams webhooks, bot formatting | [CONFIG_GUIDE.md → alert_routing](docs/CONFIG_GUIDE.md#configalert_routingyaml) |
| [config/system_prompt.md](config/system_prompt.md) | Counterparty aliases, data quirks, market calendar | [CONFIG_GUIDE.md → system_prompt](docs/CONFIG_GUIDE.md#configsystem_promptmd) |

See [docs/CONFIG_GUIDE.md](docs/CONFIG_GUIDE.md) for field-by-field explanations,
common tasks, and a pre-flight checklist.

### 4. Create Snowflake result tables

```bash
# Creates RECON_DB.RESULTS tables
python main.py --setup-tables

# Creates RECON_DB.OBSERVABILITY tables and views (for dashboards)
python observability/setup.py
```

---

## Running

### Manual / local

```bash
python main.py --date 2024-01-15
```

```
Starting reconciliation for trade date: 2024-01-15
[RECON-2024-01-15-A1B2C3D4] Starting...
[Claude] Loading 1,247 trades and 1,239 executions...
[Claude] Matched 1,231 pairs. 16 breaks identified...
...
============================================================
RECONCILIATION COMPLETE
Status          : BREAKS_FOUND
Total Breaks    : 16
High Severity   : 3
Notional at Risk: $4,820,000

Narrative:
16 breaks identified for 2024-01-15. 3 HIGH severity breaks in
BOND and DERIVATIVE instruments require immediate attention before
London open. Primary issue: 2 unexecuted bond trades with Goldman
Sachs (notional $3.2M) and 1 FX partial fill with Citi ($850K gap).

Immediate Actions Required:
  1. Contact Goldman Sachs confirms desk re: trades TR-2024-001 and TR-2024-002
  2. Obtain partial fill breakdown from Citi for trade TR-2024-089
  3. Escalate $3.2M bond exposure to risk desk before 07:00 London
```

### Airflow (scheduled)

The DAG `trade_reconciliation_nightly` runs automatically every day at 06:00 ET (America/Toronto, DST-aware), ensuring reports are ready by 08:00 ET. Canadian federal and Ontario provincial holidays are skipped automatically.

```bash
# On the Airflow server — copy project and set env
export RECON_AI_PATH=/opt/airflow/recon_ai
airflow dags trigger trade_reconciliation_nightly --conf '{"trade_date": "2024-01-15"}'
```

---

## Configuration Reference

All business logic lives in `config/` — no Python changes needed for routine
adjustments. See **[docs/CONFIG_GUIDE.md](docs/CONFIG_GUIDE.md)** for the
complete field-by-field reference. Quick summary below.

### `config/business_rules.yaml` — Tolerances and thresholds

| Section | Controls |
|---|---|
| `matching.tolerances` | Per-asset-class price/qty/date tolerance for matching |
| `matching.counterparty_normalization` | Case, whitespace, legal suffix stripping |
| `breaks.types` | Break type definitions and auto-severity overrides |
| `breaks.severity_thresholds` | USD notional bands for LOW / MEDIUM / HIGH |
| `position.dv01_config` | DV01 estimation constants for bonds and derivatives |
| `position.fx_rate_fallback` | Rate used when FX lookup is unavailable |
| `position.compute_risk_metrics` | Which risk metrics to compute per asset class |
| `cli.exit_codes` | Process exit codes by run status (for Airflow/monitoring) |

### `config/field_mappings.yaml` — Snowflake coordinates

Maps internal field names to your actual Snowflake databases, schemas, tables,
and columns. Also configures the FX rate source table.

**Every `← REPLACE` comment marks a value you must change before the first run.**

### `config/alert_routing.yaml` — Notification routing

| Section | Controls |
|---|---|
| `channels.slack` | Channel aliases → Slack channel names |
| `channels.email` | Recipient group aliases → email address lists |
| `channels.teams` | Channel aliases → Teams webhook URLs |
| `routing_matrix` | Who gets notified for each severity × asset class combination |
| `alert_settings` | Digest mode, max breaks shown, AI explanation toggle |
| `notification_formatting` | Bot name, emoji, email colour, Teams card style |

### `config/system_prompt.md` — Claude's domain knowledge

Free-form text read directly into Claude's system prompt. Fill in:
- Counterparty aliases (e.g. "GS" = "Goldman Sachs International")
- Known data quirks per broker or system
- Market calendar and end-of-day cutoff time

---

## Observability (AI Usage Tracking)

All Claude API usage, tool calls, and run events are captured automatically in
`RECON_DB.OBSERVABILITY`. Connect Sigma or Basedash to these pre-built views:

| View | Shows |
|---|---|
| `V_DAILY_AI_COST` | Daily token usage and cost by model |
| `V_MONTHLY_AI_COST` | Monthly cost rollup |
| `V_TOOL_PERFORMANCE` | Which tools Claude calls most, success rate, latency |
| `V_RUN_HISTORY` | Every run with match rate, break counts, AI cost |
| `V_USER_ACTIVITY` | Full audit trail of who triggered what |

See [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) for full table and field reference.

---

## Adding New Instrument Types

1. Add a tolerance block in `config/business_rules.yaml`:
   ```yaml
   matching:
     tolerances:
       CDS:
         price_pct: 0.001
         qty_abs: 0
         date_days: 1
   ```
2. Add to `InstrumentType` enum in `src/data/models.py`
3. Add risk metrics config in `config/business_rules.yaml` under `position.compute_risk_metrics`

No other code changes needed.

---

## Documentation

| Document | Audience | Contents |
|---|---|---|
| [CLAUDE.md](CLAUDE.md) | AI (auto-loaded) | Full project context for AI sessions |
| [README.md](README.md) | All | Setup, usage, configuration reference |
| [docs/CONFIG_GUIDE.md](docs/CONFIG_GUIDE.md) | Ops / Analysts | All config fields explained with examples and common tasks |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Engineers | System design, data flow, design decisions |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Operations | How to handle alerts, breaks, and incidents |
| [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) | Analysts / Engineers | All Snowflake tables, views, and fields |

---

## Contributing

1. Branch from `main`: `git checkout -b feat/your-feature`
2. Make changes — see [CLAUDE.md](CLAUDE.md) for architecture rules
3. Run tests: `pytest tests/unit/`
4. Open a PR against `main`

Never commit `.env` or any file containing credentials.
