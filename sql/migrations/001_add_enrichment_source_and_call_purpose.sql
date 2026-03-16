-- Migration 001: Add enrichment_source to BREAKS and call_purpose to AI_API_CALLS
--
-- Run once against RECON_DB. All statements are idempotent (use ALTER TABLE ... IF NOT EXISTS).
-- After running this migration, dbt models will pick up the new columns automatically.
--
-- Usage:
--   snowsql -a <account> -u <user> -d RECON_DB -f sql/migrations/001_add_enrichment_source_and_call_purpose.sql

USE DATABASE RECON_DB;

-- ── 1. RESULTS.BREAKS: add ENRICHMENT_SOURCE ──────────────────────────────────
-- Values: 'CLAUDE_ENHANCED' (HIGH breaks enriched by Claude)
--         'TEMPLATE_ONLY'   (all other breaks, deterministic templates)
-- Backfill all existing rows to 'TEMPLATE_ONLY' (safe default — pre-migration
-- data was all template-only since Claude was not yet used for this purpose).

ALTER TABLE RESULTS.BREAKS
    ADD COLUMN IF NOT EXISTS ENRICHMENT_SOURCE VARCHAR(32) DEFAULT 'TEMPLATE_ONLY';

UPDATE RESULTS.BREAKS
    SET ENRICHMENT_SOURCE = 'TEMPLATE_ONLY'
    WHERE ENRICHMENT_SOURCE IS NULL;

-- Also add CONFIDENCE and NEEDS_HUMAN_REVIEW if they were not present
-- (populated by break_enricher.py — backfill safe defaults).
ALTER TABLE RESULTS.BREAKS
    ADD COLUMN IF NOT EXISTS CONFIDENCE VARCHAR(16) DEFAULT 'HIGH';

ALTER TABLE RESULTS.BREAKS
    ADD COLUMN IF NOT EXISTS NEEDS_HUMAN_REVIEW BOOLEAN DEFAULT FALSE;

-- ── 2. OBSERVABILITY.AI_API_CALLS: add CALL_PURPOSE ───────────────────────────
-- Values: 'BREAK_ENRICHMENT' (the single targeted Claude call per run)
--         NULL or 'UNKNOWN'  (calls logged before this field was added)

ALTER TABLE OBSERVABILITY.AI_API_CALLS
    ADD COLUMN IF NOT EXISTS CALL_PURPOSE VARCHAR(64);

-- No backfill — historical rows will remain NULL and dbt stg_ai_api_calls
-- coalesces to 'UNKNOWN' so dashboards show the distinction cleanly.

-- ── Verify ────────────────────────────────────────────────────────────────────
SELECT 'BREAKS columns' AS check_target,
       COLUMN_NAME, DATA_TYPE
FROM   INFORMATION_SCHEMA.COLUMNS
WHERE  TABLE_SCHEMA = 'RESULTS'
  AND  TABLE_NAME   = 'BREAKS'
  AND  COLUMN_NAME  IN ('ENRICHMENT_SOURCE', 'CONFIDENCE', 'NEEDS_HUMAN_REVIEW')
ORDER BY COLUMN_NAME;

SELECT 'AI_API_CALLS columns' AS check_target,
       COLUMN_NAME, DATA_TYPE
FROM   INFORMATION_SCHEMA.COLUMNS
WHERE  TABLE_SCHEMA = 'OBSERVABILITY'
  AND  TABLE_NAME   = 'AI_API_CALLS'
  AND  COLUMN_NAME  = 'CALL_PURPOSE';
