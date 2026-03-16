# Changelog

> Auto-generated recent commits — branch `main`. Updated: 2026-03-16 20:05 UTC
> Full narrative history below the divider.

---

## Recent Commits (last 10)

### `4bf95cd` — chore(changelog): sync CHANGELOG.md after post-commit hook regeneration

| Field  | Value |
|--------|-------|
| Date   | 2026-03-16 |
| Author | thezenmaestro |
| Commit | `4bf95cd878249ccd6d0d44ce0c0a91b9d3b1fb7d` |

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### `20fe85a` — feat(changelog): add auto-updating CHANGELOG.md with post-commit hook

| Field  | Value |
|--------|-------|
| Date   | 2026-03-16 |
| Author | thezenmaestro |
| Commit | `20fe85a2fbc1afad7b711114f22dd0460ad5bc93` |

- scripts/update_changelog.sh regenerates CHANGELOG.md with the last 10
  commits (hash, date, author, subject, full body) after every commit
- .git/hooks/post-commit calls the script automatically on each commit
- CHANGELOG.md seeded with current last 10 commits
Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### `f17762b` — test(position_impact): add 42 unit tests for calculate_position_impact

| Field  | Value |
|--------|-------|
| Date   | 2026-03-16 |
| Author | thezenmaestro |
| Commit | `f17762b6a54eee723629cf96fbb8b6c2388fcb73` |

Covers BUY/SELL cash & securities direction, P&L with mocked last price,
DV01 estimation for BOND/DERIVATIVE, delta for EQUITY/DERIVATIVE,
portfolio summary aggregation, empty break list, and unknown instrument
type. All tests run without Snowflake connections or a Claude API key.
Total unit tests: 126 across 5 modules (was 84 across 4).
Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### `da5fa0a` — docs(CLAUDE.md): replace resolved reporter.py TODO with SFTP-not-implemented gap

| Field  | Value |
|--------|-------|
| Date   | 2026-03-16 |
| Author | thezenmaestro |
| Commit | `da5fa0a3903c9e2aaa62493672e11757f84a7e2d` |

The reporter.py parameterized UPDATE was fixed in commit ded257b.
Replace it with the actual open gap: SFTP source mode is declared in
field_mappings.yaml but data_loader.py has no SFTP code path — only
Snowflake source is implemented.
Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### `d0a44c7` — config_validator: detect unreplaced ← REPLACE placeholders in alert_routing.yaml

| Field  | Value |
|--------|-------|
| Date   | 2026-03-16 |
| Author | thezenmaestro |
| Commit | `d0a44c7fe7da4bc6bfe30fcf140b5e69feacbcbf` |

Previously _check_alert_routing() only verified that 'routing_matrix' and
'channels' keys existed — it passed even when all channel values still held
template placeholders. The pipeline would then reach alert dispatch at runtime
and fail silently (SKIPPED or FAILURE rows in NOTIFICATION_DELIVERIES) with no
clear error at startup.
Now reads the raw file text and reports every line that still contains the
'← REPLACE' marker, matching the same pre-flight defence already applied to
field_mappings.yaml via the REPLACE check in _check_field_mappings().
Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### `676bb67` — Fix .env.example: add LOG_LEVEL, annotate SFTP as not-yet-implemented

| Field  | Value |
|--------|-------|
| Date   | 2026-03-16 |
| Author | thezenmaestro |
| Commit | `676bb67ff2a654e7816830608a03023d457d4b9f` |

- Add LOG_LEVEL=INFO (used in main.py:28 via os.environ.get but was missing
  from the template — defaults to INFO but should be explicit for operators)
- Add prominent NOT YET IMPLEMENTED comments to both SFTP blocks:
  field_mappings.yaml supports source=sftp but data_loader.py only implements
  the Snowflake path; without this note operators would configure SFTP vars
  and wonder why they have no effect
Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### `0f060d9` — Document pendulum dependency alongside commented Airflow block in requirements.txt

| Field  | Value |
|--------|-------|
| Date   | 2026-03-16 |
| Author | thezenmaestro |
| Commit | `0f060d9cc241438d55b7e36ddeabc7e420919a05` |

pendulum is imported in airflow/dags/recon_dag.py for timezone-aware scheduling.
It ships bundled with Airflow on the worker so no separate install is needed,
but keeping it commented next to the Airflow block makes the dependency explicit
for anyone running the DAG outside a standard Airflow environment.
Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### `195352e` — Document all 9 reliability fixes across CHANGELOG, ARCHITECTURE, DATA_DICTIONARY, RUNBOOK, README, CLAUDE.md

| Field  | Value |
|--------|-------|
| Date   | 2026-03-16 |
| Author | thezenmaestro |
| Commit | `195352e7d5133cdf388627a9377a62cc6c77bc01` |

- docs/CHANGELOG.md (new): per-fix entries for all 9 commits — problem statement,
  what changed, files modified, verification steps; plus cross-cutting UTF-8 fix
- docs/DATA_DICTIONARY.md: add DATA_QUALITY_METRICS and NOTIFICATION_DELIVERIES
  table definitions with key queries; add V_DATA_QUALITY_TRENDS and
  V_NOTIFICATION_DELIVERIES view descriptions; add 2 new dashboard pages
- docs/ARCHITECTURE.md: update Snowflake block (6 OBSERVABILITY tables, 7 views);
  add typed exception hierarchy table; add notification retry behaviour section;
  update failure modes table (config validation, FX stub, retry exhaustion)
- docs/RUNBOOK.md: add alert delivery failure scenario with SQL; add data quality
  warning scenario; add 3 new monitoring queries (deliveries, data quality)
- README.md: add V_DATA_QUALITY_TRENDS and V_NOTIFICATION_DELIVERIES to views
  table; add Testing section (84 tests, 4 modules, how to run); add CHANGELOG.md
  to documentation table
- CLAUDE.md: add src/exceptions.py, src/config_validator.py, src/notifications/retry.py,
  pytest.ini, tests/conftest.py, and all 4 test files to directory structure;
  update Snowflake schema map (2 new tables, 2 new views); mark SQL bug TODO as fixed;
  update architecture rule 5 (log WARNING, not print)
Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### `988ff77` — Fix 9: Add unit tests for matcher, classifier, enricher, alert router

| Field  | Value |
|--------|-------|
| Date   | 2026-03-16 |
| Author | thezenmaestro |
| Commit | `988ff77927ca5fee730d1c1c2a88c265d0e851cb` |

84 tests across 4 test modules, all passing:
  - test_matcher: tolerance helpers, pass-1/pass-2 matching, composite
    key normalisation, empty dataset handling
  - test_break_classifier: severity thresholds, UNEXECUTED always HIGH,
    orphan executions, summary counts and notional totals
  - test_break_enricher: all 7 break types, None/zero edge cases,
    enrich_breaks_locally field additions
  - test_alert_router: dispatch per channel type, SKIPPED/FAILURE
    outcomes, _record_delivery fire-and-forget safety
Also fixes UTF-8 encoding on all open() calls for YAML config files
(was failing on Windows with default cp1252 codec due to ← characters
in alert_routing.yaml placeholder values).
Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---


<!-- HISTORICAL -->

---

## Historical Fixes (Fixes 1–10)

# Changelog — recon_ai Reliability Improvements

Nine targeted fixes committed to the `main` branch. Each fix was committed
independently for clean rollback isolation.

---

## Fix 1 — SQL Parameterisation Bug in `finalise_recon_run`

**Commit:** `ded257b`
**Problem:** `finalise_recon_run()` in `reporter.py` used `execute_ddl` (which
sends raw SQL strings) to run an UPDATE statement. Parameters were string-
formatted directly into the SQL rather than bound via Snowflake's parameterised
query interface. This is both a SQL-injection risk and the root cause of
intermittent `ProgrammingError` failures when run IDs contained special
characters.

**What changed:**
- `src/tools/reporter.py` — changed the UPDATE call to use `execute_query` with
  positional parameters `(status, completed_at, run_id)` instead of f-string
  interpolation.
- `src/data/snowflake_connector.py` — ensured `execute_query` (as opposed to
  `execute_ddl`) is the correct helper for DML with bind variables.

**Files modified:** `src/tools/reporter.py`, `src/data/snowflake_connector.py`

**Verification:**
```bash
# Run a reconciliation and confirm RECON_RUNS.STATUS is updated correctly
python main.py --date YYYY-MM-DD
# Then check:
# SELECT STATUS, COMPLETED_AT FROM RECON_DB.RESULTS.RECON_RUNS
# WHERE RUN_ID = '...'
```

---

## Fix 2 — Replace `print()` with Structured Python Logging

**Commit:** `b0275d3`
**Problem:** The pipeline used bare `print()` calls throughout. These are
invisible to Airflow's log capture, cannot be filtered by severity, and produce
no timestamps. Ops teams had no way to grep for warnings without drowning in
informational output.

**What changed:**
- `src/agents/reconciliation_agent.py` — replaced all `print()` calls with
  `logger.info()` / `logger.warning()` / `logger.error()`. Logger is
  `logging.getLogger("src.agents.reconciliation_agent")`.
- `src/notifications/slack_notifier.py` — added `logger` and replaced prints.
- `src/notifications/email_notifier.py` — added `logger` and replaced prints.
- `src/notifications/teams_notifier.py` — added `logger` and replaced prints.
- `observability/sink.py` — added `logger` for sink write failures.
- `main.py` — added `logging.basicConfig(level=INFO, format=...)` for CLI runs.

**Log format:**
```
2024-01-15 06:12:34,512 INFO  src.agents.reconciliation_agent — [RECON-2024-01-15-A1B2] Starting reconciliation
2024-01-15 06:12:40,101 WARNING src.notifications.slack_notifier — Slack post failed (attempt 1/3): Connection timeout
```

**Files modified:** `main.py`, `src/agents/reconciliation_agent.py`,
`src/notifications/slack_notifier.py`, `src/notifications/email_notifier.py`,
`src/notifications/teams_notifier.py`, `observability/sink.py`

---

## Fix 3 — Config Validation on Startup

**Commit:** `fd7f9a3`
**Problem:** Missing or misnamed Snowflake credentials, invalid YAML syntax in
config files, and missing required config sections caused the pipeline to fail
mid-run — after Airflow had already spent minutes loading data. The error
messages were cryptic (`KeyError: 'channels'`).

**What changed:**
- `src/config_validator.py` (new file, 224 lines) — validates at startup:
  - All required environment variables are set and non-empty
  - `config/business_rules.yaml` parses without error and contains all required
    top-level keys (`matching`, `breaks`, `position`, `cli`)
  - `config/field_mappings.yaml` parses and has `trades`, `executions`, and
    `fx_rates` sections
  - `config/alert_routing.yaml` parses and has `channels` and `routing_matrix`
  - Reports ALL validation failures at once (not just the first one), so ops
    can fix everything in a single pass
- `main.py` — calls `validate_config()` before any Snowflake connections are
  opened; exits with code 2 (CONFIG_ERROR) on failure.

**Files modified:** `src/config_validator.py` (new), `main.py`

**Verification:**
```bash
# With a missing env var
unset ANTHROPIC_API_KEY
python main.py --date 2024-01-15
# Should exit immediately with:
# CONFIG ERROR: Missing required environment variables: ANTHROPIC_API_KEY
```

---

## Fix 4 — Typed Exception Hierarchy

**Commit:** `6f6cca4`
**Problem:** All pipeline errors surfaced as generic `Exception`. Callers
could not distinguish between transient Snowflake timeouts (safe to retry),
data quality failures (not safe to retry — re-run after fixing the data), and
Claude API auth errors (not safe to retry — requires operator intervention).
Airflow's retry policy had no way to be selective.

**What changed:**
- `src/exceptions.py` (new file) — defines:
  - `ReconBaseError` — base class for all pipeline exceptions
  - `DataLoadError(ReconBaseError)` — raised when a Snowflake query fails; safe to retry
  - `DataQualityError(ReconBaseError)` — raised when required columns are missing
    or null counts exceed thresholds; NOT safe to retry without data fix
  - `MatchingError(ReconBaseError)` — raised on unexpected matcher failure
  - `ClassificationError(ReconBaseError)` — raised by break classifier
  - `EnrichmentError(ReconBaseError)` — raised when Claude API call fails
  - `ReportingError(ReconBaseError)` — raised on Snowflake write failure
  - `AlertingError(ReconBaseError)` — raised by notification dispatch
  - `ConfigValidationError(ReconBaseError)` — raised by config validator
- `src/agents/reconciliation_agent.py` — catches typed exceptions, logs
  context-appropriate messages, writes typed error codes to RECON_RUNS.
- `src/tools/data_loader.py` — raises `DataLoadError` on connection failure
  and `DataQualityError` on missing columns.
- `src/tools/reporter.py` — raises `ReportingError` on write failure.

**Files modified:** `src/exceptions.py` (new), `src/agents/reconciliation_agent.py`,
`src/tools/data_loader.py`, `src/tools/reporter.py`

---

## Fix 5 — Explicit Warnings for Price and FX Stub Placeholders

**Commit:** `cce415c`
**Problem:** `position_impact.py` contains two known TODO stubs:
`_get_fx_rate()` returns a flat 1.0 fallback and `_get_last_price()` returns
`None`. Both silently produce incorrect P&L and notional figures without any
indication to operators. Dashboards showed `$0.00` P&L impact with no
explanation.

**What changed:**
- `src/tools/position_impact.py` — `_get_fx_rate()` now logs a `WARNING`
  every time it falls back to the placeholder rate:
  ```
  WARNING position_impact — FX rate lookup not implemented — using fallback rate
  1.0000 for EUR→USD. Notional figures may be incorrect for non-USD positions.
  ```
- `_get_last_price()` logs a `WARNING` every time it returns `None`:
  ```
  WARNING position_impact — _get_last_price is not implemented — pnl_impact
  will be $0.00 for isin=GB00B24CGK77 instrument_type=BOND.
  ```

These warnings appear in Airflow logs and can be alerted on. They are also
visible when running `python main.py --date ...` locally.

**Files modified:** `src/tools/position_impact.py`

**Note:** These warnings will disappear once the Snowflake market data lookups
are implemented (see CLAUDE.md known TODOs).

---

## Fix 6 — Exponential Backoff Retry for Notification Channels

**Commit:** `567a0b8`
**Problem:** Transient network failures and webhook throttling caused alert
delivery to fail silently on the first attempt. Slack returns HTTP 429 (rate
limit) during high-load periods. SMTP connections are frequently dropped by
corporate firewalls after inactivity. A single failed attempt meant ops never
received the alert.

**What changed:**
- `src/notifications/retry.py` (new file):
  - `TransientError(Exception)` — signal class; callers raise this to indicate
    the failure is retryable.
  - `retry_with_backoff(fn, *, attempts=3, base_delay=1.0, max_delay=30.0, jitter=0.5, label="operation")`
    — retries `fn()` up to `attempts` times. On each retry, waits
    `min(base_delay × 2^attempt + random(0, jitter), max_delay)` seconds.
    Non-`TransientError` exceptions are re-raised immediately (no retry).
    Uses `logger.warning` between attempts.
- `src/notifications/slack_notifier.py` — inner `_post()` raises
  `TransientError` on `ConnectionError`, `requests.Timeout`, and HTTP
  429 / 5xx responses. Calls `retry_with_backoff(_post, attempts=3)`.
- `src/notifications/teams_notifier.py` — same retry pattern as Slack.
- `src/notifications/email_notifier.py` — `SMTPServerDisconnected` and
  `SMTPConnectError` → `TransientError`. Other `SMTPException` (auth, bad
  recipient) re-raise immediately. `base_delay=2.0` for SMTP.

**Retry schedule (default):**
| Attempt | Wait before retry |
|---|---|
| 1 → 2 | 1–1.5 s |
| 2 → 3 | 2–2.5 s |
| 3+ | gives up, logs ERROR |

**Files modified:** `src/notifications/retry.py` (new),
`src/notifications/slack_notifier.py`, `src/notifications/teams_notifier.py`,
`src/notifications/email_notifier.py`

---

## Fix 7 — Notification Delivery Outcomes Written to OBSERVABILITY

**Commit:** `b7b7dc9`
**Problem:** There was no way to know whether alerts had actually been delivered.
A failed Slack post or a misconfigured email group was invisible unless ops
manually checked Airflow logs. Dashboard users had no delivery success rate
metric.

**What changed:**
- `observability/models.py` — added `NotificationDeliveryEvent(BaseModel)`:
  `delivery_id`, `run_id`, `trade_date`, `channel_type`, `channel_name`,
  `break_count`, `status` (`SUCCESS` / `FAILURE` / `SKIPPED`), `attempts`,
  `error_message`, `sent_at`.
- `observability/sink.py` — added `NOTIFICATION_DELIVERIES` DDL (6th
  Snowflake table), `V_NOTIFICATION_DELIVERIES` view, and
  `log_notification(event)` write method.
- `src/notifications/alert_router.py`:
  - `_dispatch()` now returns `(status: str, error_message: str | None)`.
  - Added `_record_delivery()` — fire-and-forget helper that creates a
    `NotificationDeliveryEvent` and calls `get_sink().log_notification()`.
    Wrapped entirely in `try/except` so it never blocks or crashes the
    alert pipeline. Logs a `WARNING` on failure.
  - `route_alerts()` calls `_record_delivery()` after each dispatch.
  - `_dispatch()` now correctly returns `SKIPPED` when an email recipient group
    or Teams alias is not present in `alert_routing.yaml`, rather than
    silently doing nothing.

**New Snowflake table:** `RECON_DB.OBSERVABILITY.NOTIFICATION_DELIVERIES`
**New Snowflake view:** `RECON_DB.OBSERVABILITY.V_NOTIFICATION_DELIVERIES`

See [DATA_DICTIONARY.md](DATA_DICTIONARY.md) for full column reference.

**Files modified:** `observability/models.py`, `observability/sink.py`,
`src/notifications/alert_router.py`

---

## Fix 8 — Data Quality Metrics Written to OBSERVABILITY

**Commit:** `63bf1e0`
**Problem:** There was no structured record of data load health. Silent `EMPTY`
loads (Snowflake returned zero rows for a trade date) and high null-column
counts were invisible. Without historical data, it was impossible to detect
recurring data feed problems from specific brokers.

**What changed:**
- `observability/models.py` — added `DataQualityMetricEvent(BaseModel)`:
  `metric_id`, `run_id`, `trade_date`, `dataset` (`trades` or `executions`),
  `record_count`, `null_trade_id`, `null_isin`, `null_quantity`, `null_price`,
  `query_latency_ms`, `status` (`SUCCESS` / `EMPTY` / `FAILURE`),
  `error_message`, `measured_at`.
- `observability/sink.py` — added `DATA_QUALITY_METRICS` DDL (5th Snowflake
  table), `V_DATA_QUALITY_TRENDS` view, and `log_data_quality(event)` write
  method.
- `src/tools/data_loader.py`:
  - Added `time.monotonic()` timing around each Snowflake query to measure
    `query_latency_ms`.
  - Added null-count computation after successful loads (`null_trade_id`,
    `null_isin`, `null_quantity`, `null_price`).
  - Added `_emit_data_quality()` fire-and-forget helper at the bottom of the
    file — same pattern as `_record_delivery()`: lazy imports, `try/except`,
    `logger.warning` on failure.
  - `load_booked_trades()` and `load_executed_transactions()` both emit on
    `SUCCESS`, `EMPTY`, and `FAILURE` outcomes.

**New Snowflake table:** `RECON_DB.OBSERVABILITY.DATA_QUALITY_METRICS`
**New Snowflake view:** `RECON_DB.OBSERVABILITY.V_DATA_QUALITY_TRENDS`

See [DATA_DICTIONARY.md](DATA_DICTIONARY.md) for full column reference.

**Files modified:** `observability/models.py`, `observability/sink.py`,
`src/tools/data_loader.py`

---

## Fix 9 — Unit Test Suite

**Commit:** `988ff77`
**Problem:** There were no automated tests. Regressions in the matching engine,
break classifier, enricher, and alert router could only be caught manually.
The absence of tests also meant CI had nothing to run, and contributors had no
safety net.

**What changed:**
- `pytest.ini` (new) — test discovery config: `testpaths = tests`,
  `python_files = test_*.py`, `addopts = -v --tb=short`.
- `tests/conftest.py` (new) — adds the repo root to `sys.path` so all
  `src.*` and `observability.*` imports resolve in the test environment.
- `tests/unit/test_matcher.py` (new, 20 tests):
  - `TestWithinPriceTolerance` — exact match, within/outside tolerance, zero-
    price edge cases (both zero passes, non-zero vs zero fails).
  - `TestWithinQtyTolerance` — exact match, large gap fails.
  - `TestWithinDateTolerance` — same date, 30-day gap always fails.
  - `TestMatchTransactions` — empty inputs, perfect Pass-1 match (`EXACT`),
    unmatched trade, unmatched execution, Pass-2 composite match (`COMPOSITE`),
    price mismatch fallthrough, 3 simultaneous matches, counterparty case-
    insensitive normalisation, output structure keys.
- `tests/unit/test_break_classifier.py` (new, 17 tests):
  - `TestClassifySeverity` — UNEXECUTED always HIGH, zero/high notional, all
    break types produce valid severity strings.
  - `TestClassifyBreaksUnmatchedTrades` — empty input, single break creates
    correct record with expected field values, all break_ids unique.
  - `TestClassifyBreaksOrphanExecutions` — orphan type, count, mixed inputs.
  - `TestClassifyBreaksSummary` — structure, severity counts, notional sum.
- `tests/unit/test_break_enricher.py` (new, 35 tests):
  - `TestExplain` — all 7 break types return strings; content checks for
    trade_id, counterparty, dates, prices, fill percentages; None/zero edge
    cases.
  - `TestRecommend` — all 7 break types, remaining qty in partial, unknown type
    fallback.
  - `TestEnrichBreaksLocally` — all 4 fields populated, `needs_human_review`
    True/False logic, preserves existing dict keys, all break types enriched.
- `tests/unit/test_alert_router.py` (new, 12 tests):
  - `TestRouteAlerts` — empty breaks returns dispatched=0, valid JSON, multiple
    breaks.
  - `TestDispatch` — Slack SUCCESS calls `send_slack` with correct args, Teams
    SKIPPED on missing alias, email SKIPPED on missing group, Slack FAILURE
    returns `"FAILURE"` and error string, email FAILURE when recipients patched.
  - `TestRecordDelivery` — does not raise on observability failure, logs a
    WARNING (not an exception) when `get_sink()` errors.

**Total: 84 unit tests. Runtime: ~0.8 s.**

**Files added:** `pytest.ini`, `tests/conftest.py`,
`tests/unit/test_matcher.py`, `tests/unit/test_break_classifier.py`,
`tests/unit/test_break_enricher.py`, `tests/unit/test_alert_router.py`

---

## Fix 10 — Unit Tests for `position_impact.py`

**Problem:** `calculate_position_impact()` had no test coverage despite containing
the core BUY/SELL cash direction logic, DV01 estimation, delta computation, and
portfolio aggregation — all of which are pure Python and fully testable without
Snowflake or a Claude API key.

**What changed:**
- `tests/unit/test_position_impact.py` (new, 42 tests):
  - `TestGetFxRate` — same-currency short-circuit returns 1.0 (case-insensitive),
    different-currency falls back to `fx_rate_fallback = 1.0` from
    `business_rules.yaml`, logs WARNING with currency pair in message.
  - `TestBuyDirection` — cash impact positive (liquidity retained), securities
    impact negative (not received), `net_position_direction = "LONG"`, numeric
    values equal to notional and qty_gap respectively.
  - `TestSellDirection` — cash impact negative (revenue not received), securities
    positive (not delivered), `net_position_direction = "SHORT"`.
  - `TestPnlImpact` — P&L is $0 when `_get_last_price` returns None (the current
    stub behaviour); correct `(price_move × qty × direction_sign)` formula when
    mocked last price is provided; `last_known_price` and `price_source` captured
    in output.
  - `TestDv01Metrics` — BOND and DERIVATIVE get DV01 (`$1/bps/$1M` per config),
    EQUITY and FX do not; DV01 scales linearly with notional; `risk_metric_notes`
    present for bond.
  - `TestDeltaMetrics` — EQUITY and DERIVATIVE get `delta_impact = qty_gap`, BOND
    and FX do not.
  - `TestPortfolioSummary` — empty list produces zero summary; break count matches
    input length; cash and securities impacts sum correctly across multiple breaks;
    opposing BUY/SELL cash impacts net to zero.
  - `TestOutputStructure` — all 17 required output keys present; `impact_id` is
    unique (UUID) per break; `break_id`, `as_of_date`, `net_position_change`
    preserved exactly from input; round-trips to valid JSON.
  - `TestUnknownInstrumentType` — produces no risk metrics but still computes cash
    and securities impacts.

**Total after this fix: 126 unit tests. Runtime: ~0.9 s.**

**Files added:** `tests/unit/test_position_impact.py`

**To run:**
```bash
pytest tests/unit/
```

---

## Cross-Cutting Fix — UTF-8 Encoding on Windows

Discovered during Fix 9 test execution. `config/alert_routing.yaml` contains
`←` characters (UTF-8 code point U+2190). Python's default file encoding on
Windows is `cp1252`, which cannot decode byte `0x90` in the UTF-8 sequence
`\xe2\x86\x90`, causing `UnicodeDecodeError` at import time.

**Files updated** (all `open(...yaml...)` calls):
`src/notifications/alert_router.py`, `src/notifications/email_notifier.py`,
`src/notifications/slack_notifier.py`, `src/notifications/teams_notifier.py`,
`src/tools/break_classifier.py`, `src/tools/data_loader.py`,
`src/tools/matcher.py`, `src/tools/position_impact.py`,
`src/config_validator.py`

All open calls now use `encoding="utf-8"` explicitly. This is a no-op on Linux
/ macOS where UTF-8 is the default but is required for Windows compatibility.
