-- REVIEW ONLY. Run manually as database owner (Supabase SQL editor). Rerunnable.
-- No credentials are embedded. No rows are read, changed or deleted.
--
-- Runtime-role RLS policies for the quant_app tables the collector/app write.
--
-- WHY (9 Nov 2026): RLS was enabled on quant_app.market_quotes and quant_app.mf_nav
-- to clear Supabase security-advisor findings. Their only policies came from
-- sql/drive_archive_draft.sql and were scoped to quant_archive_worker, so every
-- quant_app_runtime INSERT failed with
--   "new row violates row-level security policy for table market_quotes"
-- (scheduled evidence collector runs #203/#204). The runtime-side policy had only
-- ever existed in a test fixture, never in a migration.
--
-- These policies do NOT widen privilege: the runtime is still bounded by its table
-- GRANTs (SELECT, INSERT, UPDATE; no DELETE). Same shape as daily_volume_runtime.
-- Policies are created before RLS is (re)enabled, in one transaction, so there is
-- no window where the runtime is locked out.
--
-- After ANY RLS or grant change, run sql/check_rls_policy_gaps.sql.

BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '60s';

DROP POLICY IF EXISTS runtime_quotes ON quant_app.market_quotes;
CREATE POLICY runtime_quotes ON quant_app.market_quotes
    TO quant_app_runtime USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS runtime_nav ON quant_app.mf_nav;
CREATE POLICY runtime_nav ON quant_app.mf_nav
    TO quant_app_runtime USING (true) WITH CHECK (true);

ALTER TABLE quant_app.market_quotes ENABLE ROW LEVEL SECURITY;
ALTER TABLE quant_app.mf_nav ENABLE ROW LEVEL SECURITY;

COMMIT;
