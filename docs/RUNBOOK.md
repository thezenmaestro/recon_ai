# Runbook — Trade Reconciliation Operations

This document is for the **operations team**. It covers how to respond to alerts,
investigate breaks, re-run reconciliation, and escalate incidents.

---

## Daily Routine

| Time | Action |
|---|---|
| 20:00 UTC | Airflow DAG triggers automatically |
| 20:05–20:10 UTC | Snowflake connections validated, data loaded |
| 20:10–20:15 UTC | Matching and break classification complete |
| 20:15–20:25 UTC | Claude enriches breaks, writes results, sends alerts |
| By 07:00 London | All HIGH severity breaks must be actioned |

---

## Understanding Alerts

Alerts arrive via Slack, email, and Teams. Every alert includes:

```
RECON ALERT — Trade Date: 2024-01-15
Run ID: RECON-2024-01-15-A1B2C3D4

Total Breaks: 5 | High Severity: 2 | Total Notional at Risk: $4,820,000
---
1. [HIGH] UNEXECUTED | Trade: TR-2024-001 | BOND | Goldman Sachs | $3,200,000
   AI: Trade TR-2024-001 (10Y Gilt, £2.5M notional) was booked at 09:42 but no
       execution confirm received from Goldman Sachs by end of day.
   Action: Contact Goldman Sachs confirms desk (gsi-confirms@gs.com) and request
           status. If unresolved by 07:00, escalate to desk head.
```

**Severity definitions:**

| Severity | Notional | Always HIGH regardless of amount |
|---|---|---|
| LOW | < $10,000 | — |
| MEDIUM | $10,000 – $100,000 | — |
| HIGH | > $100,000 | UNEXECUTED trades (any amount) |

---

## Break Types — What Each Means

### UNEXECUTED
Trade exists in OMS but no execution confirm received from broker.
- **Risk:** Trade may not have been executed. Position is wrong. Settlement will fail.
- **Action:** Contact broker confirms desk immediately. Obtain verbal confirmation or cancellation.

### QTY_MISMATCH
Execution confirm received but quantity differs from booked quantity beyond tolerance.
- **Risk:** Partial position. Settlement mismatch.
- **Action:** Request amended confirm from broker or amend OMS booking.

### PRICE_MISMATCH
Execution price deviates beyond tolerance from booked price.
- **Risk:** P&L impact. Cost basis error.
- **Action:** Obtain detailed execution report from broker. If price is correct, amend OMS booking.

### SETTLEMENT_DATE_MISMATCH
Confirm shows a different settlement date than booked.
- **Risk:** Funding/delivery mismatch. Potential fails.
- **Action:** Align with broker on correct settlement date. Notify settlements team.

### PARTIAL_EXECUTION
Trade partially filled — some quantity executed, remainder outstanding.
- **Risk:** Open order risk. Position gap.
- **Action:** Confirm whether remainder is pending or cancelled. Update OMS accordingly.

### ORPHAN_EXECUTION
Execution confirm received with no corresponding booked trade.
- **Risk:** Rogue trade or data entry error.
- **Action:** Investigate with front office. Either book the missing trade or instruct broker to cancel confirm.

---

## Investigating a Break

### Step 1 — Query the break details

```sql
SELECT
    BREAK_ID, TRADE_ID, EXECUTION_ID,
    INSTRUMENT_TYPE, COUNTERPARTY, ISIN,
    BREAK_TYPE, SEVERITY,
    BOOKED_QUANTITY, EXECUTED_QUANTITY, QUANTITY_GAP,
    BOOKED_PRICE, EXECUTED_PRICE, PRICE_VARIANCE_PCT,
    NOTIONAL_AT_RISK_USD,
    BOOKED_SETTLEMENT_DATE, EXECUTED_SETTLEMENT_DATE,
    AI_EXPLANATION,
    RECOMMENDED_ACTION
FROM RECON_DB.RESULTS.BREAKS
WHERE TRADE_DATE = '2024-01-15'   -- replace with your date
  AND SEVERITY = 'HIGH'
ORDER BY NOTIONAL_AT_RISK_USD DESC;
```

### Step 2 — Check position impact

```sql
SELECT
    pi.ISIN, pi.INSTRUMENT_TYPE, pi.COUNTERPARTY,
    pi.NET_POSITION_CHANGE, pi.NET_POSITION_DIRECTION,
    pi.PNL_IMPACT_USD,
    pi.SETTLEMENT_CASH_IMPACT_USD,
    pi.DV01_IMPACT_USD,
    b.AI_EXPLANATION
FROM RECON_DB.RESULTS.POSITION_IMPACT pi
JOIN RECON_DB.RESULTS.BREAKS b ON pi.BREAK_ID = b.BREAK_ID
WHERE pi.AS_OF_DATE = '2024-01-15'
ORDER BY ABS(pi.PNL_IMPACT_USD) DESC;
```

### Step 3 — Check the raw source data

```sql
-- Check the booked trade
SELECT * FROM TRADES_DB.OMS.BOOKED_TRADES WHERE TRADE_ID = 'TR-2024-001';

-- Check for any execution confirms for this ISIN
SELECT * FROM EXECUTIONS_DB.CONFIRMS.EXECUTED_TRANSACTIONS
WHERE ISIN = 'GB00B24CGK77'
  AND EXECUTION_DATE = '2024-01-15';
```

---

## Re-Running Reconciliation

If data was updated (e.g. a late confirm arrived), re-run for the same date:

```bash
# On the server / local machine
python main.py --date 2024-01-15
```

Or trigger the Airflow DAG manually:

```bash
airflow dags trigger trade_reconciliation_nightly \
  --conf '{"trade_date": "2024-01-15"}'
```

**Note:** Re-running inserts new rows with a new RUN_ID. To see only the latest run:

```sql
SELECT * FROM RECON_DB.RESULTS.BREAKS
WHERE TRADE_DATE = '2024-01-15'
  AND RUN_ID = (
    SELECT RUN_ID FROM RECON_DB.RESULTS.RECON_RUNS
    WHERE TRADE_DATE = '2024-01-15'
      AND STATUS = 'COMPLETED'
    ORDER BY RUN_TIMESTAMP DESC
    LIMIT 1
  );
```

---

## Escalation Matrix

| Break | Amount | Escalate to | Timeline |
|---|---|---|---|
| Any HIGH break | Any | Desk head + ops | Before 07:00 London |
| UNEXECUTED BOND or DERIVATIVE | Any | Desk head + risk | Immediately on alert |
| Any break | > $1M | Risk management | Before 07:00 London |
| Any break | > $10M | Risk + COO | Immediately |
| Orphan execution | > $100K | Compliance + risk | Same day |

---

## Common Scenarios

### "Airflow DAG failed — no results in Snowflake"

1. Check Airflow logs: `airflow tasks logs trade_reconciliation_nightly run_reconciliation <run_id>`
2. Look for the error in `RECON_DB.RESULTS.RECON_RUNS`:
   ```sql
   SELECT RUN_ID, STATUS, ERROR_MESSAGE, RUN_TIMESTAMP
   FROM RECON_DB.RESULTS.RECON_RUNS
   ORDER BY RUN_TIMESTAMP DESC LIMIT 5;
   ```
3. Common causes:
   - Snowflake warehouse suspended → resume warehouse and retry
   - ANTHROPIC_API_KEY expired → rotate key and update Airflow connection
   - Source table schema changed → update `config/field_mappings.yaml`

### "Alerts sent but no breaks visible in Snowflake"

- Check `RECON_DB.RESULTS.RECON_RUNS` for the run ID referenced in the alert
- If run STATUS = FAILED, the alert may have been sent before the write failed
- Re-run for the same date to regenerate clean results

### "Too many false positives — breaks that aren't real"

1. Review `config/business_rules.yaml` tolerances — they may be too tight
2. Check `config/system_prompt.md` counterparty aliases — missing aliases cause false COMPOSITE match failures
3. Check `config/field_mappings.yaml` — wrong column mappings can cause systematic mismatches

### "Break count is zero but I know there are breaks"

1. Check filter in `config/field_mappings.yaml`:
   ```yaml
   trades:
     filters:
       active_statuses: ["BOOKED", "AMENDED"]   # is the trade status in this list?
   ```
2. Verify the trade and execution dates align — the loader queries by `trade_date` / `execution_date`
3. Check the matching keys — if `trade_ref_id` in executions is null for all records, Pass 1 won't match anything

---

## Monitoring Queries

### Today's run summary

```sql
SELECT
    RUN_ID, TRADE_DATE, STATUS,
    TOTAL_TRADES, MATCHED_COUNT,
    BREAK_COUNT, HIGH_SEVERITY_COUNT,
    TOTAL_NOTIONAL_AT_RISK_USD,
    DURATION_SECONDS,
    RUN_TIMESTAMP
FROM RECON_DB.RESULTS.RECON_RUNS
WHERE TRADE_DATE = CURRENT_DATE - 1
ORDER BY RUN_TIMESTAMP DESC
LIMIT 1;
```

### Week's break trend

```sql
SELECT
    TRADE_DATE,
    COUNT(*) AS break_count,
    COUNT_IF(SEVERITY = 'HIGH') AS high_breaks,
    SUM(NOTIONAL_AT_RISK_USD) AS total_notional
FROM RECON_DB.RESULTS.BREAKS
WHERE TRADE_DATE >= CURRENT_DATE - 7
GROUP BY 1
ORDER BY 1 DESC;
```

### AI cost this month

```sql
SELECT * FROM RECON_DB.OBSERVABILITY.V_MONTHLY_AI_COST
WHERE MONTH = DATE_TRUNC('month', CURRENT_DATE);
```
