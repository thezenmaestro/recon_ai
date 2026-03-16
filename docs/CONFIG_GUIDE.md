# Configuration Guide — recon_ai

All business logic, routing rules, field mappings, and notification settings
live in four YAML/Markdown files in `config/`. **No Python changes are needed
for the tasks described in this guide.**

---

## Which file controls what?

| I want to change…                              | Edit this file                        |
|------------------------------------------------|---------------------------------------|
| Matching tolerances (price, qty, date)         | `business_rules.yaml` → `matching.tolerances` |
| How counterparty names are normalised          | `business_rules.yaml` → `matching.counterparty_normalization` |
| What counts as a break and its severity        | `business_rules.yaml` → `breaks` |
| Risk metrics per asset class (DV01, delta)     | `business_rules.yaml` → `position` |
| CLI exit codes for monitoring/Airflow alerts   | `business_rules.yaml` → `cli.exit_codes` |
| Snowflake table and column names               | `field_mappings.yaml` |
| Which trades/executions are in scope           | `field_mappings.yaml` → `filters.active_statuses` |
| FX rate data source                            | `field_mappings.yaml` → `fx_rates` |
| Slack channel IDs                              | `alert_routing.yaml` → `channels.slack` |
| Email recipients per desk/team                 | `alert_routing.yaml` → `channels.email` |
| Teams webhook URLs                             | `alert_routing.yaml` → `channels.teams` |
| Who gets notified for each break type          | `alert_routing.yaml` → `routing_matrix` |
| Bot names, colours, email footer               | `alert_routing.yaml` → `notification_formatting` |
| Counterparty aliases Claude understands        | `config/system_prompt.md` |
| Known data quirks for Claude to reason about   | `config/system_prompt.md` |
| Market calendar and end-of-day cutoff          | `config/system_prompt.md` |

---

## `config/business_rules.yaml`

The primary file for all reconciliation logic. Every tolerance, threshold, and
calculation constant is here.

### `matching.tolerances`

Controls when a matched pair is accepted vs flagged as a break. One block per
instrument type. The `DEFAULT` block is used when an instrument type isn't
explicitly listed.

```yaml
matching:
  tolerances:
    EQUITY:
      price_pct: 0.001      # Max % difference: booked price vs executed price
                            # 0.001 = 0.1%, e.g. $100.00 ±$0.10
      qty_abs: 0            # Max absolute quantity difference (0 = must be exact)
      notional_pct: 0.002   # Max % difference on total notional (qty × price)
      date_days: 0          # Max settlement date difference in calendar days
```

**Field reference:**

| Field | Type | Meaning |
|---|---|---|
| `price_pct` | decimal | `abs(booked - executed) / booked ≤ price_pct` |
| `qty_abs` | number | `abs(booked_qty - executed_qty) ≤ qty_abs` |
| `notional_pct` | decimal | Notional-level tolerance; rarely the binding constraint |
| `date_days` | integer | `abs(booked_date - executed_date).days ≤ date_days` |

**To add a new instrument type** (e.g. CDS):

```yaml
matching:
  tolerances:
    CDS:
      price_pct: 0.001
      qty_abs: 0
      notional_pct: 0.002
      date_days: 1
```

Then add `CDS` to `InstrumentType` in `src/data/models.py` and to
`position.compute_risk_metrics` below. No other code changes needed.

---

### `matching.counterparty_normalization`

Controls how counterparty names are cleaned before composite-key matching.
This absorbs common naming differences between your OMS and broker confirms
(e.g. "GOLDMAN SACHS LLC" vs "Goldman Sachs").

```yaml
matching:
  counterparty_normalization:
    case: upper               # upper | lower | preserve
    strip_whitespace: true    # Remove leading/trailing spaces
    collapse_spaces: true     # "Goldman  Sachs" → "Goldman Sachs"
    strip_suffixes:           # Legal suffixes removed before matching
      - "LLC"
      - "INC"
      - "PLC"
      - "LTD"
      - "LIMITED"
      - "CORP"
      - "CORPORATION"
```

**Common changes:**

- Add broker-specific suffixes your firm uses (e.g. "AG", "SA", "NV", "GmbH")
- If your OMS uses mixed case and your broker uses ALL CAPS, set `case: upper`
- For aliases that can't be resolved by suffix stripping alone (e.g. "GS" vs
  "Goldman Sachs International"), add them to `config/system_prompt.md` →
  Counterparty Aliases instead — Claude handles those at enrichment time

---

### `breaks.types`

Defines the break types the system can produce. Two modes:

- `auto_severity: HIGH` — always assigned this severity regardless of notional
- `severity_by_notional: true` — severity calculated from the thresholds below

```yaml
breaks:
  types:
    UNEXECUTED:
      description: "Trade booked in OMS with no matching execution confirm"
      auto_severity: HIGH     # Always HIGH — trade may not have happened at all

    SETTLEMENT_DATE_MISMATCH:
      description: "Confirmed settlement date differs from booked"
      auto_severity: MEDIUM   # Funding risk, but not a trade failure

    QTY_MISMATCH:
      description: "Executed quantity differs from booked quantity"
      severity_by_notional: true   # LOW / MEDIUM / HIGH by notional thresholds below
```

---

### `breaks.severity_thresholds`

Applies to break types with `severity_by_notional: true`.
Notional is always the USD-equivalent value of the gap (not the full trade).

```yaml
breaks:
  severity_thresholds:
    LOW:
      max_notional: 10000        # < $10,000  → ops team only
    MEDIUM:
      min_notional: 10000
      max_notional: 100000       # $10K–$100K → ops + desk head
    HIGH:
      min_notional: 100000       # > $100,000 → ops + desk head + risk
```

**Example: tighten to escalate anything over $50K:**

```yaml
    MEDIUM:
      min_notional: 10000
      max_notional: 50000
    HIGH:
      min_notional: 50000
```

---

### `position`

Controls how position and valuation impact is calculated for each break.

```yaml
position:
  group_by: [isin, counterparty, settlement_date]  # Aggregation keys
  mtm_fallback: last_known_price                   # Price source when live unavailable
  fx_rate_fallback: 1.0                            # Rate used when FX lookup fails
                                                   # 1.0 = treat all breaks as USD

  dv01_config:                                     # Simplified DV01 for bonds/derivatives
    basis_points_per_million: 1.0                  # $1 per bp per $1M notional
    equivalent_duration_years: 10                  # Assumed duration (flat-rate simplification)
    estimation_note: "DV01 is estimated..."        # Text stored in RISK_METRIC_NOTES column

  compute_risk_metrics:                            # Which metrics to compute per asset class
    EQUITY: [delta, notional_usd]
    FX: [notional_usd, base_currency_exposure]
    BOND: [notional_usd, dv01]
    DERIVATIVE: [delta, notional_usd, dv01]
```

**`fx_rate_fallback`** — Set to `1.0` (USD pass-through) until `MARKET_DATA_DB`
is live. Once the FX rate Snowflake lookup is implemented, this value only
applies when the lookup returns no result.

**`dv01_config`** — This is a simplified estimate. Replace with a proper
duration-adjusted model once you have live market data. Until then, tune
`basis_points_per_million` to match your risk desk's convention.

**To add risk metrics for a new instrument type:**

```yaml
  compute_risk_metrics:
    CDS: [notional_usd, dv01]   # add this line
```

---

### `cli.exit_codes`

Maps reconciliation run status to the process exit code returned by `main.py`.
Used by Airflow, monitoring scripts, and CI pipelines to detect failures.

```yaml
cli:
  exit_codes:
    ALL_MATCHED: 0      # Clean run — no breaks
    BREAKS_FOUND: 0     # Breaks found but pipeline succeeded — alerts sent
    CRITICAL: 1         # Fatal error (Snowflake down, Claude API failure, etc.)
```

`BREAKS_FOUND` is intentionally `0` — breaks are business-as-usual and are
handled via alerts, not pipeline failures. Set to `1` only if your Airflow
monitoring should treat any break as a pipeline failure.

---

## `config/field_mappings.yaml`

Maps the internal field names the pipeline uses to your actual Snowflake
database, schema, table, and column names. **Edit this before the first run.**

### Source tables

```yaml
trades:
  snowflake:
    database: TRADES_DB           # ← Your actual DB name
    schema: OMS                   # ← Your actual schema
    table: BOOKED_TRADES          # ← Your actual table name

  columns:
    trade_id: TRADE_ID            # Left side: internal name (don't change)
    isin: ISIN                    # Right side: your actual column name (change this)
    ticker: TICKER
    instrument_type: INSTRUMENT_TYPE   # Must contain EQUITY|FX|BOND|DERIVATIVE
    counterparty: COUNTERPARTY
    direction: DIRECTION               # Must contain BUY or SELL
    quantity: QUANTITY
    price: PRICE
    notional: NOTIONAL
    currency: CURRENCY                 # ISO 4217 (USD, GBP, EUR, …)
    trade_date: TRADE_DATE
    settlement_date: SETTLEMENT_DATE
    status: STATUS

  filters:
    active_statuses: ["BOOKED", "AMENDED"]   # Only these statuses are loaded
```

The `executions` block follows the same pattern for your broker confirms table.
The internal names on the left are used throughout the pipeline — only change
the right-hand values.

**Common issue:** If match count is unexpectedly zero, check that:
1. `status` column values match `filters.active_statuses` exactly (case-sensitive)
2. `trade_date` / `execution_date` columns contain dates in the queried date range
3. `trade_ref_id` in executions is populated — if all NULL, Pass 1 matching will
   find nothing and only composite-key matching will run

### Results database

```yaml
results:
  snowflake:
    database: RECON_DB
    schema: RESULTS

  tables:
    recon_runs: RECON_RUNS
    matched_trades: MATCHED_TRADES
    breaks: BREAKS
    position_impact: POSITION_IMPACT
    audit_log: RECON_AUDIT_LOG
```

These tables are created by `python main.py --setup-tables`. If you rename
them here, re-run setup to create them with the new names.

### FX rates

```yaml
fx_rates:
  use_snowflake_table: true         # true = use your Snowflake table
                                    # false = skip lookup (all notional treated as USD)
  snowflake:
    database: MARKET_DATA_DB        # ← Replace with your market data DB
    schema: RATES
    table: FX_RATES_EOD
    date_column: RATE_DATE          # Column containing the rate date
    from_currency_column: FROM_CCY  # Column containing source currency (e.g. GBP)
    to_currency_column: TO_CCY      # Column containing target currency (e.g. USD)
    rate_column: MID_RATE           # Column containing the mid rate
  base_currency: USD                # Target currency for all notional calculations
```

Until `MARKET_DATA_DB` is available, set `use_snowflake_table: false` and
set `position.fx_rate_fallback: 1.0` in `business_rules.yaml`. When the table
is ready, set `use_snowflake_table: true`, fill in the column names, and
uncomment the Snowflake block in `src/tools/position_impact.py`.

---

## `config/alert_routing.yaml`

Controls who gets notified, via which channel, under which conditions — and
how those notifications look.

### `channels`

Defines the available destinations. Routing rules reference these by alias
(e.g. `ops_general`, `bonds_desk`), not by raw URL.

```yaml
channels:
  slack:
    channels:
      ops_general: "#recon-ops"       # ← Replace with your channel name
      equities_desk: "#recon-equities"
      bonds_desk: "#recon-bonds"
      risk_management: "#recon-risk"
      management: "#recon-management"

  email:
    from_address: "recon-system@yourfirm.com"   # ← Replace
    recipients:
      ops_team:
        - "ops-team@yourfirm.com"               # ← Replace; can be a list
      bonds_desk_head:
        - "bonds-head@yourfirm.com"

  teams:
    webhooks:
      ops_channel: "https://yourfirm.webhook.office.com/..."    # ← Replace
      risk_channel: "https://yourfirm.webhook.office.com/..."
```

**To add a new Slack channel:**

```yaml
channels:
  slack:
    channels:
      credit_desk: "#recon-credit"   # add this alias
```

Then reference `credit_desk` in the `routing_matrix`.

---

### `routing_matrix`

Defines who gets which alert for each combination of asset class and severity.
References channel aliases defined above.

```yaml
routing_matrix:
  BOND:
    LOW:
      slack: [ops_general]
      email: [ops_team]
      teams: [ops_channel]

    MEDIUM:
      slack: [ops_general, bonds_desk]
      email: [ops_team, bonds_desk_head]
      teams: [ops_channel]

    HIGH:
      slack: [ops_general, bonds_desk, risk_management, management]
      email: [ops_team, bonds_desk_head, risk_management, senior_management]
      teams: [ops_channel, risk_channel, management_channel]
```

**To restrict HIGH bond alerts to ops + risk only (remove management):**

```yaml
    HIGH:
      slack: [ops_general, bonds_desk, risk_management]
      email: [ops_team, bonds_desk_head, risk_management]
      teams: [ops_channel, risk_channel]
```

The `DEFAULT` block at the bottom catches any instrument type not listed.
If you add a new instrument type, add a matching block here — or the
DEFAULT rules will apply.

---

### `alert_settings`

```yaml
alert_settings:
  include_ai_explanation: true    # Include Claude's plain-English break explanation
  include_position_impact: true   # Include P&L/cash/risk numbers
  max_breaks_in_summary: 10       # Max breaks shown in a single Slack/Teams message
  digest_mode: true               # true  = one message per run (all breaks grouped)
                                  # false = one message per break
```

`digest_mode: false` is noisy for runs with many breaks. Keep it `true` unless
you have fewer than 5 breaks per night on average.

---

### `notification_formatting`

Controls the visual style of alerts. Change these to match your firm's branding
without touching any Python files.

```yaml
notification_formatting:
  slack:
    bot_name: "Recon Bot"         # Name shown in Slack messages
    icon_emoji: ":bar_chart:"     # Emoji icon shown next to the bot name

  email:
    header_color: "#c0392b"       # Hex colour of the email header banner
    footer_text: "This is an automated message from the Trade Reconciliation System."

  teams:
    theme_color: "C0392B"         # Hex colour without # for Teams card header
    card_title: "**Trade Reconciliation Alert**"
    card_subtitle: "Automated nightly run"
```

---

## `config/system_prompt.md`

This file is Claude's domain knowledge — it shapes how Claude explains breaks,
interprets ambiguous data, and makes recommendations. Unlike the YAML files,
this is free-form text. **Fill it in thoroughly — it directly affects the
quality of Claude's break explanations.**

### Counterparty Aliases

Add aliases so Claude doesn't treat "GS" and "Goldman Sachs International" as
different counterparties in its narrative:

```markdown
### Counterparty Aliases

counterparty_aliases:
  - canonical: "Goldman Sachs International"
    aliases: ["GSI", "GS International", "Goldman Sachs Intl", "GS"]

  - canonical: "JP Morgan Securities"
    aliases: ["JPMS", "JPMorgan", "J.P. Morgan Securities", "JPM"]

  - canonical: "Barclays Capital"
    aliases: ["Barclays", "BARC", "BarCap"]
```

These are guidance for Claude's reasoning — not machine-parsed. The
`counterparty_normalization` config in `business_rules.yaml` handles the
automated normalisation before matching. Aliases here help Claude produce
accurate narrative text ("this is the same counterparty as…").

### Known Data Quality Issues

Document anything Claude needs to know to reason correctly:

```markdown
### Known Data Quality Issues

- Broker X sends execution confirms up to 2 hours after market close.
  If a trade shows as UNEXECUTED but the confirm window hasn't closed,
  flag as NEEDS_REVIEW rather than a definitive break.

- OMS sometimes duplicates trades when an amendment is processed.
  Deduplicate on trade_id + latest version before matching.

- FX notional from Broker Y comes in base currency; our OMS stores
  USD equivalent. Convert before comparing prices.

- Our prime broker echoes trade IDs with a "PB-" prefix.
  Strip it before comparing against OMS trade IDs.
```

### Business Calendar

```markdown
### Business Calendar

- Holidays: Follow London Stock Exchange calendar.
- End-of-day cutoff: 18:00 London time.
- Trades booked after cutoff belong to the NEXT business day.
- FX spot settlement: T+2. Same-day (TOD) trades settle T+0.
- Bond settlement: T+2 for gilts; T+1 for US Treasuries.
```

---

## Common tasks

### I need to tighten the price tolerance for FX

```yaml
# config/business_rules.yaml
matching:
  tolerances:
    FX:
      price_pct: 0.00005   # Changed from 0.0001 to 0.005% (2 pip level)
```

### I need to add a new Slack channel for a credit desk

1. Add the channel alias to `channels.slack.channels`:
   ```yaml
   credit_desk: "#recon-credit"
   ```

2. Add a routing rule for the new desk:
   ```yaml
   routing_matrix:
     CREDIT:
       LOW:
         slack: [ops_general]
         email: [ops_team]
         teams: [ops_channel]
       HIGH:
         slack: [ops_general, credit_desk, risk_management]
         email: [ops_team, credit_desk_head, risk_management]
         teams: [ops_channel, risk_channel]
   ```

3. Add `credit_desk_head` to `channels.email.recipients`.

4. Add `CREDIT` to `InstrumentType` in `src/data/models.py` and to
   `position.compute_risk_metrics` in `business_rules.yaml`.

### I want HIGH breaks to also page a third-party on-call service

Add a `webhook` entry in `channels` pointing to your alerting provider's
inbound webhook, then add it to the `routing_matrix` HIGH entries as needed.
The `alert_router.py` already dispatches to Teams-style webhooks; for other
formats you would need a new notifier in `src/notifications/`.

### I want all UNEXECUTED breaks to also email senior management

In `alert_routing.yaml`, the `routing_matrix` routes by severity. Since
`UNEXECUTED` is always `HIGH` (via `auto_severity` in `business_rules.yaml`),
add `senior_management` to the HIGH email list for each asset class where
unexecuted breaks are possible.

### I want to change the Slack bot name and colour scheme

```yaml
# config/alert_routing.yaml
notification_formatting:
  slack:
    bot_name: "ReconAI"
    icon_emoji: ":rotating_light:"
  email:
    header_color: "#1a3a5c"
  teams:
    theme_color: "1A3A5C"
```

No code changes. Takes effect on the next run.

### I want to enable FX rate lookups from Snowflake

1. Fill in the Snowflake coordinates in `field_mappings.yaml → fx_rates`.
2. Set `use_snowflake_table: true`.
3. In `src/tools/position_impact.py`, uncomment the block inside
   `_get_fx_rate()` marked "Snowflake FX lookup".
4. Optionally update `position.fx_rate_fallback` in `business_rules.yaml`
   to a sensible default for lookup failures (e.g. `1.0` keeps USD assumption).

---

## Validation checklist before first run

- [ ] `field_mappings.yaml` — no `← REPLACE` markers remain
- [ ] `alert_routing.yaml` — no `← REPLACE` markers remain; all webhook URLs are real
- [ ] `config/system_prompt.md` — counterparty aliases and data quirks filled in
- [ ] `.env` file exists with all required environment variables (see [CLAUDE.md](../CLAUDE.md))
- [ ] `python main.py --setup-tables` has been run
- [ ] `python observability/setup.py` has been run
- [ ] Test run: `python main.py --date <yesterday>` completes without CRITICAL status
