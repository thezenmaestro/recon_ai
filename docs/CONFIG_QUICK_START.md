# Config Quick Start — recon_ai

Common config tasks and the pre-flight checklist. For field-by-field reference see [CONFIG_GUIDE.md](CONFIG_GUIDE.md).

---

## Common tasks

### Tighten the price tolerance for FX

```yaml
# config/business_rules.yaml
matching:
  tolerances:
    FX:
      price_pct: 0.00005   # 0.005% (2 pip level)
```

### Add a new Slack channel for a new desk (e.g. credit)

1. Add the channel alias to `channels.slack.channels` in `alert_routing.yaml`:
   ```yaml
   credit_desk: "#recon-credit"
   ```
2. Add a routing rule under `routing_matrix`:
   ```yaml
   CREDIT:
     MEDIUM:
       slack: [ops_general, credit_desk]
       email: [ops_team, credit_desk_head]
       teams: [ops_channel]
     HIGH:
       slack: [ops_general, credit_desk, risk_management]
       email: [ops_team, credit_desk_head, risk_management]
       teams: [ops_channel, risk_channel]
   ```
   LOW entries inherit from `routing_defaults` automatically.
3. Add `credit_desk_head` to `channels.email.recipients`.
4. Add `CREDIT` to `InstrumentType` in `src/data/models.py` and to `position.compute_risk_metrics` in `business_rules.yaml`.

### Page a third-party on-call service for HIGH breaks

Add a `webhook` entry in `channels` pointing to your alerting provider's inbound webhook, then add it to the `routing_matrix` HIGH entries. `alert_router.py` dispatches to Teams-style webhooks; for other formats add a new notifier in `src/notifications/`.

### Email senior management on all UNEXECUTED breaks

Since `UNEXECUTED` is always `HIGH` (via `auto_severity` in `business_rules.yaml`), add `senior_management` to the HIGH email list for each relevant asset class in `routing_matrix`.

### Change the Slack bot name and colour scheme

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

### Switch between SFTP and Snowflake as the data source

```yaml
# config/field_mappings.yaml
trades:
  source: snowflake   # or: sftp
executions:
  source: snowflake   # or: sftp
```

For `snowflake`: fill in `trades.snowflake.database/schema/table` and set `SNOWFLAKE_*` env vars.
For `sftp`: fill in `trades.sftp.remote_dir`, `filename_pattern`, `format`, and set `SFTP_TRADES_*` env vars. No code changes needed.

### Enable FX rate lookups from Snowflake

1. Fill in the Snowflake coordinates in `field_mappings.yaml → fx_rates`.
2. Set `use_snowflake_table: true`.
3. In `src/tools/position_impact.py`, implement `_get_fx_rate()` (see TODO comment).
4. Optionally update `position.fx_rate_fallback` in `business_rules.yaml` as a fallback for lookup failures.

---

## Validation checklist before first run

**Data source setup:**
- [ ] `field_mappings.yaml` — `trades.source` and `executions.source` set to `sftp` or `snowflake`
- [ ] `field_mappings.yaml` — SFTP `remote_dir`, `filename_pattern`, `format`, and `delimiter` filled in for each `sftp` source
- [ ] `field_mappings.yaml` — Snowflake DB/schema/table names filled in for each `snowflake` source
- [ ] `field_mappings.yaml` — no `← REPLACE` markers remain
- [ ] `.env` — SFTP credentials set (`SFTP_TRADES_*` and/or `SFTP_CONFIRMS_*`) for each SFTP source

**Notifications:**
- [ ] `alert_routing.yaml` — no `← REPLACE` markers remain; all webhook URLs are real

**Claude domain knowledge:**
- [ ] `config/system_prompt.md` — counterparty aliases and data quirks filled in

**Infrastructure:**
- [ ] `.env` file exists with all required environment variables (see [CLAUDE.md](../CLAUDE.md))
- [ ] `python main.py --setup-tables` has been run
- [ ] `python observability/setup.py` has been run

**Smoke test:**
- [ ] Test run: `python main.py --date <yesterday>` completes without CRITICAL status
