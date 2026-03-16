# Changelog

> Auto-generated — last 10 commits on branch `main`.
> Updated: 2026-03-16 19:55 UTC

---

## `20fe85a` — feat(changelog): add auto-updating CHANGELOG.md with post-commit hook

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

## `f17762b` — test(position_impact): add 42 unit tests for calculate_position_impact

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

## `da5fa0a` — docs(CLAUDE.md): replace resolved reporter.py TODO with SFTP-not-implemented gap

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

## `d0a44c7` — config_validator: detect unreplaced ← REPLACE placeholders in alert_routing.yaml

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

## `676bb67` — Fix .env.example: add LOG_LEVEL, annotate SFTP as not-yet-implemented

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

## `0f060d9` — Document pendulum dependency alongside commented Airflow block in requirements.txt

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

## `195352e` — Document all 9 reliability fixes across CHANGELOG, ARCHITECTURE, DATA_DICTIONARY, RUNBOOK, README, CLAUDE.md

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

## `988ff77` — Fix 9: Add unit tests for matcher, classifier, enricher, alert router

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

## `63bf1e0` — Fix 8: Add data quality metrics logging to OBSERVABILITY schema

| Field  | Value |
|--------|-------|
| Date   | 2026-03-15 |
| Author | thezenmaestro |
| Commit | `63bf1e0229a1c3cc117f848f419c05857ec0d754` |

data_loader.py now measures Snowflake query latency and null counts
for key columns (trade_id/execution_id, ISIN, quantity, price) after
each load, then writes a row to DATA_QUALITY_METRICS. Status is
SUCCESS, EMPTY, or FAILURE. Includes DDL for the new table and
V_DATA_QUALITY_TRENDS view showing null rates and latency over time.
Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

