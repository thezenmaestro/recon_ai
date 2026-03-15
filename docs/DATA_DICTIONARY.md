# Data Dictionary — recon_ai

All Snowflake tables, views, and fields. Use this as the reference when
building Sigma / Basedash dashboards or writing ad-hoc queries.

---

## Database Map

| Database | Schema | Purpose |
|---|---|---|
| `TRADES_DB` | `OMS` | Source A — booked trades (read only) |
| `EXECUTIONS_DB` | `CONFIRMS` | Source B — broker execution confirms (read only) |
| `RECON_DB` | `RESULTS` | Reconciliation output tables |
| `RECON_DB` | `OBSERVABILITY` | AI usage, tool calls, run history, audit trail |

---

## Source Tables (Read Only)

### TRADES_DB.OMS.BOOKED_TRADES

| Column (internal name) | Actual column | Type | Description |
|---|---|---|---|
| `trade_id` | configured in field_mappings.yaml | VARCHAR | Unique OMS trade identifier |
| `isin` | configured | VARCHAR(12) | Security ISIN |
| `ticker` | configured | VARCHAR | Bloomberg/Reuters ticker |
| `instrument_type` | configured | VARCHAR | EQUITY, FX, BOND, DERIVATIVE |
| `counterparty` | configured | VARCHAR | Counterparty legal entity name |
| `direction` | configured | VARCHAR | BUY or SELL |
| `quantity` | configured | NUMBER | Number of units / face value |
| `price` | configured | NUMBER | Booked price per unit (clean price for bonds) |
| `notional` | configured | NUMBER | quantity × price |
| `currency` | configured | VARCHAR(3) | ISO 4217 currency code |
| `trade_date` | configured | DATE | Date trade was entered in OMS |
| `settlement_date` | configured | DATE | Expected settlement date |
| `status` | configured | VARCHAR | BOOKED, AMENDED (filter in field_mappings.yaml) |

> Actual column names are defined in `config/field_mappings.yaml → trades.columns`

### EXECUTIONS_DB.CONFIRMS.EXECUTED_TRANSACTIONS

| Column (internal name) | Actual column | Type | Description |
|---|---|---|---|
| `execution_id` | configured | VARCHAR | Broker's unique execution reference |
| `trade_ref_id` | configured | VARCHAR | OMS trade ID echoed back (may be NULL) |
| `isin` | configured | VARCHAR(12) | Security ISIN |
| `counterparty` | configured | VARCHAR | Counterparty name |
| `direction` | configured | VARCHAR | BUY or SELL |
| `executed_quantity` | configured | NUMBER | Actual filled quantity |
| `executed_price` | configured | NUMBER | Actual fill price |
| `executed_notional` | configured | NUMBER | executed_quantity × executed_price |
| `currency` | configured | VARCHAR(3) | ISO 4217 currency code |
| `execution_date` | configured | DATE | Date execution was confirmed |
| `settlement_date` | configured | DATE | Confirmed settlement date |
| `status` | configured | VARCHAR | FILLED, PARTIAL (filter in field_mappings.yaml) |

---

## Result Tables (Written by Pipeline)

### RECON_DB.RESULTS.RECON_RUNS

One row per reconciliation run. The authoritative record of every run.

| Column | Type | Description |
|---|---|---|
| `RUN_ID` | VARCHAR(64) PK | Unique run identifier. Format: `RECON-YYYY-MM-DD-XXXXXXXX` |
| `TRADE_DATE` | DATE | Trade date being reconciled |
| `RUN_TIMESTAMP` | TIMESTAMP_NTZ | When the run started (UTC) |
| `TRIGGERED_BY` | VARCHAR(32) | `airflow`, `manual`, or `event` |
| `TOTAL_TRADES` | INTEGER | Count of booked trades loaded |
| `TOTAL_EXECUTIONS` | INTEGER | Count of execution confirms loaded |
| `MATCHED_COUNT` | INTEGER | Number of successfully matched pairs |
| `BREAK_COUNT` | INTEGER | Number of breaks found |
| `NEEDS_REVIEW_COUNT` | INTEGER | Breaks flagged as uncertain by Claude |
| `TOTAL_MATCHED_NOTIONAL_USD` | NUMBER(20,4) | USD notional of matched trades |
| `TOTAL_BREAK_NOTIONAL_USD` | NUMBER(20,4) | USD notional at risk from breaks |
| `STATUS` | VARCHAR(16) | `RUNNING`, `COMPLETED`, `FAILED` |
| `ERROR_MESSAGE` | TEXT | Populated on FAILED runs |
| `COMPLETED_AT` | TIMESTAMP_NTZ | When the run finished (UTC) |

**Key query:** Latest successful run per date
```sql
SELECT * FROM RECON_DB.RESULTS.RECON_RUNS
WHERE TRADE_DATE = '2024-01-15' AND STATUS = 'COMPLETED'
ORDER BY RUN_TIMESTAMP DESC LIMIT 1;
```

---

### RECON_DB.RESULTS.MATCHED_TRADES

One row per successfully matched trade↔execution pair.

| Column | Type | Description |
|---|---|---|
| `MATCH_ID` | VARCHAR(64) PK | Unique match identifier |
| `RUN_ID` | VARCHAR(64) | FK → RECON_RUNS |
| `TRADE_ID` | VARCHAR(128) | OMS trade ID |
| `EXECUTION_ID` | VARCHAR(128) | Broker execution ID |
| `INSTRUMENT_TYPE` | VARCHAR(32) | EQUITY, FX, BOND, DERIVATIVE |
| `NOTIONAL_USD` | NUMBER(20,4) | Trade notional in USD equivalent |
| `QTY_VARIANCE` | NUMBER(20,6) | Absolute quantity difference (0 = exact) |
| `PRICE_VARIANCE_PCT` | NUMBER(10,6) | % price difference (0 = exact) |
| `MATCH_CONFIDENCE` | VARCHAR(16) | `EXACT` (key match) or `COMPOSITE` (attribute match) |
| `MATCHED_AT` | TIMESTAMP_NTZ | When the match was recorded |

---

### RECON_DB.RESULTS.BREAKS

One row per break. The primary table for ops investigation and dashboard metrics.

| Column | Type | Description |
|---|---|---|
| `BREAK_ID` | VARCHAR(64) PK | Unique break identifier |
| `RUN_ID` | VARCHAR(64) | FK → RECON_RUNS |
| `TRADE_ID` | VARCHAR(128) | OMS trade ID (NULL for ORPHAN_EXECUTION breaks) |
| `EXECUTION_ID` | VARCHAR(128) | Broker execution ID (NULL for UNEXECUTED breaks) |
| `INSTRUMENT_TYPE` | VARCHAR(32) | EQUITY, FX, BOND, DERIVATIVE |
| `COUNTERPARTY` | VARCHAR(256) | Counterparty entity name |
| `ISIN` | VARCHAR(12) | Security ISIN |
| `DIRECTION` | VARCHAR(4) | BUY or SELL |
| `BREAK_TYPE` | VARCHAR(32) | See break type definitions below |
| `SEVERITY` | VARCHAR(8) | `LOW`, `MEDIUM`, `HIGH` |
| `BOOKED_QUANTITY` | NUMBER(20,6) | Quantity in OMS |
| `EXECUTED_QUANTITY` | NUMBER(20,6) | Quantity confirmed by broker (0 if UNEXECUTED) |
| `QUANTITY_GAP` | NUMBER(20,6) | `BOOKED_QUANTITY - EXECUTED_QUANTITY` |
| `BOOKED_PRICE` | NUMBER(20,8) | Price in OMS |
| `EXECUTED_PRICE` | NUMBER(20,8) | Price from broker confirm (NULL if UNEXECUTED) |
| `PRICE_VARIANCE_PCT` | NUMBER(10,6) | % difference between booked and executed price |
| `NOTIONAL_AT_RISK_USD` | NUMBER(20,4) | USD value of the break (gap × price × FX rate) |
| `BOOKED_SETTLEMENT_DATE` | DATE | Settlement date in OMS |
| `EXECUTED_SETTLEMENT_DATE` | DATE | Settlement date from broker (NULL if UNEXECUTED) |
| `AI_EXPLANATION` | TEXT | Claude's plain English explanation of the break |
| `RECOMMENDED_ACTION` | TEXT | Claude's recommended next step for the ops team |
| `CREATED_AT` | TIMESTAMP_NTZ | When the break record was written |

**Break type values:**

| BREAK_TYPE | Meaning |
|---|---|
| `UNEXECUTED` | Trade in OMS, no matching execution confirm |
| `QTY_MISMATCH` | Confirmed quantity differs from booked quantity |
| `PRICE_MISMATCH` | Confirmed price outside tolerance |
| `SETTLEMENT_DATE_MISMATCH` | Confirmed settlement date differs from booked |
| `PARTIAL_EXECUTION` | Some quantity executed, gap remains |
| `ORPHAN_EXECUTION` | Execution confirm with no corresponding booked trade |
| `NEEDS_REVIEW` | Claude flagged as uncertain — requires manual review |

---

### RECON_DB.RESULTS.POSITION_IMPACT

One row per break, showing forward impact on positions and valuations.

| Column | Type | Description |
|---|---|---|
| `IMPACT_ID` | VARCHAR(64) PK | Unique impact record ID |
| `RUN_ID` | VARCHAR(64) | FK → RECON_RUNS |
| `BREAK_ID` | VARCHAR(64) | FK → BREAKS |
| `ISIN` | VARCHAR(12) | Security ISIN |
| `INSTRUMENT_TYPE` | VARCHAR(32) | Instrument type |
| `COUNTERPARTY` | VARCHAR(256) | Counterparty |
| `NET_POSITION_CHANGE` | NUMBER(20,6) | Units impact on net position |
| `NET_POSITION_DIRECTION` | VARCHAR(8) | `LONG`, `SHORT`, `FLAT` |
| `PNL_IMPACT_USD` | NUMBER(20,4) | Mark-to-market P&L impact (last known price vs booked price × gap qty) |
| `SETTLEMENT_CASH_IMPACT_USD` | NUMBER(20,4) | Cash funding impact (positive = cash freed, negative = cash needed) |
| `SECURITIES_DELIVERY_IMPACT` | NUMBER(20,6) | Units to deliver/receive at settlement |
| `DELTA_IMPACT` | NUMBER(20,8) | Delta exposure impact (equities and derivatives) |
| `DV01_IMPACT_USD` | NUMBER(20,4) | DV01 impact in USD (bonds and derivatives only — estimated) |
| `RISK_METRIC_NOTES` | TEXT | Caveats on risk calculations (e.g. "DV01 is estimated") |
| `AS_OF_DATE` | DATE | Valuation date |
| `LAST_KNOWN_PRICE` | NUMBER(20,8) | Price used for mark-to-market (NULL until FX/price TODOs are implemented) |
| `PRICE_SOURCE` | VARCHAR(64) | Source of last_known_price (`NOT_AVAILABLE` until implemented) |

---

## Observability Tables

### RECON_DB.OBSERVABILITY.AI_API_CALLS

One row per Claude API call. The primary table for cost monitoring.

| Column | Type | Description |
|---|---|---|
| `CALL_ID` | VARCHAR(64) PK | Unique call identifier |
| `RUN_ID` | VARCHAR(64) | Reconciliation run ID |
| `TRADE_DATE` | DATE | Trade date of the run |
| `MODEL` | VARCHAR(64) | Model used (e.g. `claude-opus-4-6`) |
| `INPUT_TOKENS` | INTEGER | Tokens in the prompt |
| `OUTPUT_TOKENS` | INTEGER | Tokens in the response |
| `THINKING_TOKENS` | INTEGER | Tokens used in adaptive thinking |
| `TOTAL_TOKENS` | INTEGER | Sum of all token types |
| `COST_USD` | NUMBER(12,6) | Estimated USD cost for this call |
| `LATENCY_MS` | INTEGER | Wall-clock milliseconds for the API call |
| `STOP_REASON` | VARCHAR(32) | `end_turn`, `tool_use`, `max_tokens` |
| `HAD_THINKING` | BOOLEAN | Whether Claude used extended thinking |
| `TOOL_USE_COUNT` | INTEGER | Number of tool_use blocks in the response |
| `TRIGGERED_BY` | VARCHAR(32) | `airflow`, `manual`, `event` |
| `CALLED_AT` | TIMESTAMP_NTZ | When the API call was made |
| `ERROR` | TEXT | Error message if the call failed |

### RECON_DB.OBSERVABILITY.TOOL_CALLS

One row per tool invocation. Used for tool performance monitoring.

| Column | Type | Description |
|---|---|---|
| `TOOL_CALL_ID` | VARCHAR(64) PK | Unique tool call ID |
| `API_CALL_ID` | VARCHAR(64) | FK → AI_API_CALLS |
| `RUN_ID` | VARCHAR(64) | Reconciliation run ID |
| `TRADE_DATE` | DATE | Trade date |
| `TOOL_NAME` | VARCHAR(128) | Tool function name (e.g. `tool_load_booked_trades`) |
| `CALLED_AT` | TIMESTAMP_NTZ | When the tool was invoked |
| `DURATION_MS` | INTEGER | How long the tool took to execute |
| `STATUS` | VARCHAR(16) | `SUCCESS` or `FAILURE` |
| `INPUT_SIZE_BYTES` | INTEGER | Size of the input JSON passed to the tool |
| `OUTPUT_SIZE_BYTES` | INTEGER | Size of the output JSON returned by the tool |
| `ERROR_MESSAGE` | TEXT | Error detail if STATUS = FAILURE |

### RECON_DB.OBSERVABILITY.RUN_EVENTS

Run lifecycle events — STARTED, COMPLETED, FAILED.

| Column | Type | Description |
|---|---|---|
| `EVENT_ID` | VARCHAR(64) PK | Unique event ID |
| `RUN_ID` | VARCHAR(64) | Reconciliation run ID |
| `TRADE_DATE` | DATE | Trade date |
| `EVENT_TYPE` | VARCHAR(32) | `STARTED`, `COMPLETED`, `FAILED` |
| `TRIGGERED_BY` | VARCHAR(32) | `airflow`, `manual`, `event` |
| `STATUS` | VARCHAR(16) | Run status at time of event |
| `TOTAL_TRADES` | INTEGER | Populated on COMPLETED |
| `MATCHED_COUNT` | INTEGER | Populated on COMPLETED |
| `BREAK_COUNT` | INTEGER | Populated on COMPLETED |
| `HIGH_SEVERITY_COUNT` | INTEGER | Populated on COMPLETED |
| `TOTAL_NOTIONAL_AT_RISK_USD` | NUMBER(20,4) | Populated on COMPLETED |
| `TOTAL_API_CALLS` | INTEGER | Number of Claude API calls in this run |
| `TOTAL_TOKENS_USED` | INTEGER | Total tokens consumed |
| `TOTAL_COST_USD` | NUMBER(12,6) | Total AI cost for the run |
| `DURATION_SECONDS` | NUMBER(10,2) | Total run duration |
| `ERROR_MESSAGE` | TEXT | Populated on FAILED |
| `OCCURRED_AT` | TIMESTAMP_NTZ | When this event occurred |

### RECON_DB.OBSERVABILITY.USER_ACTIVITY

Full audit trail of all user-initiated actions.

| Column | Type | Description |
|---|---|---|
| `ACTIVITY_ID` | VARCHAR(64) PK | Unique activity ID |
| `USER_NAME` | VARCHAR(256) | Username or `system` / `airflow` |
| `ACTION` | VARCHAR(128) | `SESSION_START`, `RUN_RECON`, `MANUAL_RERUN`, etc. |
| `SOURCE` | VARCHAR(32) | `airflow`, `manual`, `cli`, `api` |
| `RUN_ID` | VARCHAR(64) | Associated run ID (if applicable) |
| `TRADE_DATE` | DATE | Trade date (if applicable) |
| `DETAILS` | VARIANT | JSON blob with additional context |
| `IP_ADDRESS` | VARCHAR(64) | Client IP (if available) |
| `OCCURRED_AT` | TIMESTAMP_NTZ | When the action occurred |

---

## Pre-Built Views (Sigma / Basedash Ready)

### V_DAILY_AI_COST
Daily cost aggregation by model and trigger source. Use for cost trend dashboards.

**Key columns:** `TRADE_DATE`, `MODEL`, `TRIGGERED_BY`, `api_call_count`, `total_tokens`, `total_cost_usd`, `avg_latency_ms`, `error_count`

### V_MONTHLY_AI_COST
Monthly rollup. Use for budget tracking and invoicing review.

**Key columns:** `month`, `MODEL`, `total_cost_usd`, `total_tokens`, `total_api_calls`

### V_TOOL_PERFORMANCE
Tool usage statistics. Use to identify slow or failing tools.

**Key columns:** `TOOL_NAME`, `total_calls`, `success_rate_pct`, `avg_duration_ms`, `max_duration_ms`

### V_RUN_HISTORY
Full run history with match rate and cost. Primary view for operations dashboard.

**Key columns:** `RUN_ID`, `TRADE_DATE`, `STATUS`, `match_rate_pct`, `BREAK_COUNT`, `HIGH_SEVERITY_COUNT`, `TOTAL_NOTIONAL_AT_RISK_USD`, `ai_cost_usd`, `DURATION_SECONDS`

### V_USER_ACTIVITY
Human-readable audit trail ordered by most recent.

**Key columns:** `USER_NAME`, `ACTION`, `SOURCE`, `RUN_ID`, `TRADE_DATE`, `OCCURRED_AT`

---

## Suggested Sigma / Basedash Dashboard Pages

| Page | Primary Table/View | Key Metrics |
|---|---|---|
| **Daily Summary** | `V_RUN_HISTORY` | Match rate %, break count, notional at risk, run status |
| **Break Explorer** | `RESULTS.BREAKS` | Break list filterable by date/severity/type/counterparty |
| **Position Impact** | `RESULTS.POSITION_IMPACT` | P&L at risk, cash impact, DV01 by instrument |
| **AI Cost Monitor** | `V_DAILY_AI_COST` + `V_MONTHLY_AI_COST` | Daily/monthly spend, tokens, latency |
| **Tool Performance** | `V_TOOL_PERFORMANCE` | Success rate, avg latency per tool |
| **Audit Trail** | `V_USER_ACTIVITY` | Who did what, when |
| **Break Trends** | `RESULTS.BREAKS` aggregated | Break rate over time by asset class |
