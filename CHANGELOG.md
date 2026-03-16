# Changelog

> Auto-generated — last 10 commits on branch `main`. Updated: 2026-03-16 20:07 UTC

---

### `b4cb02f` — docs(changelog): consolidate to single CHANGELOG.md, load at agent session start

| Field  | Value |
|--------|-------|
| Date   | 2026-03-16 |
| Author | thezenmaestro |
| Commit | `b4cb02f630416379404035a214f341e0d6236d13` |

- Merge docs/CHANGELOG.md (narrative Fixes 1-10) into root CHANGELOG.md
  below a <!-- HISTORICAL --> marker — one source of truth
- update_changelog.sh preserves the historical section on every regeneration;
  only the "Recent Commits" header is rewritten
- CLAUDE.md: add session-start instruction to read CHANGELOG.md so the agent
  is always current on recent changes without user re-explanation
- README.md: update docs table to point to root CHANGELOG.md
- docs/CHANGELOG.md: deleted (content now in root CHANGELOG.md)
Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

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

