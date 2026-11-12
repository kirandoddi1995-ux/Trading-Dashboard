-- REVIEW ONLY. Run manually as database owner (Supabase SQL editor). Rerunnable.
-- No credentials are embedded. No rows are read, changed or deleted.
--
-- Per-decision dispositions of the scheduled Stage-2 shadow maturation
-- (equity_stage2_maturation.py, save_dispositions). One row per shadow pass and label
-- version: what the last maturation attempt concluded for that decision (labelled, or the
-- reason it was not: corporate_action, basis_mismatch, window_problem, no_fill, ...), every
-- conclusion it has had (`reasons`, first-seen order), how many runs attempted it, when first
-- and last. The run summary only counts reasons; this keeps WHICH decision had WHICH reason,
-- so held, failed and expired passes can be listed (sql/stage2_shadow_dispositions_report.sql)
-- and the share of passes ever rejected by a check counted, also when a retry labelled them.
--
-- Until this file is run, every maturation run that attempts a decision reports PARTIAL
-- with DispositionWriteFailed (labels are still stored): run it before or with the merge.
--
-- Rules this table must keep (checked by tests/test_equity_stage2_maturation.py):
-- * The foreign key is ON DELETE RESTRICT, declared explicitly. The nightly archive refuses
--   to run (SCANNER_ARCHIVE_RESTRICT_FK_REQUIRED) when any foreign key on
--   scanner_observations has another delete action, and the default (NO ACTION) is
--   another action. Rows only reference Stage-2 passes, which the archive never deletes.
-- * The runtime role gets SELECT, INSERT, UPDATE (the upsert; the schema's default
--   privileges give it the same), never DELETE; RLS is on with a runtime policy created
--   first, so the runtime is never locked out (sql/runtime_rls_policies.sql pattern).
-- * No other role gets anything: the archive check (ARCHIVE_ROLE_TOO_BROAD) and the research
--   repository's permission check fail when their roles hold privileges on quant_app tables
--   they do not list, so the file revokes from them as the other quant_app files do.
-- * Run it outside the 10:07 and 14:37 IST scans (e.g. in the evening): the foreign key takes
--   a short lock on scanner_observations (lock_timeout 10 s; rerun if it times out).
-- * Size: one row per Stage-2 shadow pass (about 45 a trading day, ~350 B each with the
--   primary-key index, up to ~1 KB with three messages: ~4 MB a year); updated in place on each
--   retry. Budget 4 MB in storage_policy.BUDGETS; rows older than 60 days are final.
--
-- After running, run sql/check_rls_policy_gaps.sql (expect no row for this table).

BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '60s';

CREATE TABLE IF NOT EXISTS quant_app.stage2_shadow_dispositions (
    observation_id text NOT NULL
        REFERENCES quant_app.scanner_observations(observation_id) ON DELETE RESTRICT,
    label_version text NOT NULL,
    disposition text NOT NULL,
    reasons text[] NOT NULL DEFAULT '{}'::text[],
    detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    attempts integer NOT NULL DEFAULT 1 CHECK (attempts > 0),
    first_at timestamptz NOT NULL DEFAULT now(),
    last_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (observation_id, label_version)
);

-- Everything is taken back first (a grant added by hand, DELETE for the runtime included), from
-- each role that exists here (the house pattern, sql/drive_archive_draft.sql), then granted again.
REVOKE ALL ON quant_app.stage2_shadow_dispositions FROM PUBLIC;
DO $$ DECLARE r TEXT; BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated', 'service_role', 'equity_research_collector',
                             'quant_archive_worker', 'quant_app_runtime'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON quant_app.stage2_shadow_dispositions FROM %I', r);
        END IF;
    END LOOP;
END $$;
GRANT SELECT, INSERT, UPDATE ON quant_app.stage2_shadow_dispositions TO quant_app_runtime;

DROP POLICY IF EXISTS runtime_dispositions ON quant_app.stage2_shadow_dispositions;
CREATE POLICY runtime_dispositions ON quant_app.stage2_shadow_dispositions
    TO quant_app_runtime USING (true) WITH CHECK (true);

ALTER TABLE quant_app.stage2_shadow_dispositions ENABLE ROW LEVEL SECURITY;

COMMIT;
