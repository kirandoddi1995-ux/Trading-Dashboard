-- REVIEW ONLY. Apply manually after the two existing Drive archive drafts,
-- before deploying the extended workflow. Deletes no source rows.
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';

-- Fail closed if the original statement-level protection is not present.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger
        WHERE tgrelid='equity_research.outcomes'::regclass
          AND tgname='outcome_append_only' AND tgtype=58 AND tgenabled IN ('O','A')
          AND tgfoid='equity_research.reject_mutation()'::regprocedure) THEN
        RAISE EXCEPTION 'Original outcome append-only trigger is required';
    END IF;
END $$;

-- The original trigger remains attached. Source/observation tables and every
-- UPDATE/TRUNCATE remain blocked, even when attempted by the archive role.
CREATE OR REPLACE FUNCTION equity_research.reject_mutation() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$
BEGIN
    IF TG_TABLE_SCHEMA='equity_research' AND TG_TABLE_NAME='outcomes'
       AND TG_LEVEL='STATEMENT' AND TG_OP='DELETE'
       AND current_user='quant_archive_worker' THEN
        RETURN NULL; -- Row trigger below authorizes each actual deletion.
    END IF;
    RAISE EXCEPTION 'Research evidence is append-only';
END $$;
REVOKE ALL ON FUNCTION equity_research.reject_mutation() FROM PUBLIC;

CREATE OR REPLACE FUNCTION equity_research.guard_outcome_archive_delete() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$
BEGIN
    IF current_user <> 'quant_archive_worker' OR TG_OP <> 'DELETE' THEN
        RAISE EXCEPTION 'Research evidence is append-only';
    END IF;
    -- UTC calendar cutoff matches the maintenance script; caller cannot shorten it.
    IF OLD.recorded_at >= (((statement_timestamp() AT TIME ZONE 'UTC')::date - 14)
                          ::timestamp AT TIME ZONE 'UTC') THEN
        RAISE EXCEPTION 'Research outcome is inside the protected retention window';
    END IF;
    -- Same entity and same tie-breaking order as ResearchRepository.report().
    IF NOT EXISTS (SELECT 1 FROM equity_research.outcomes newer
        WHERE newer.decision_id=OLD.decision_id
          AND (newer.recorded_at,newer.snapshot_id) > (OLD.recorded_at,OLD.snapshot_id)) THEN
        RAISE EXCEPTION 'Latest research outcome must be retained';
    END IF;
    RETURN OLD;
END $$;
REVOKE ALL ON FUNCTION equity_research.guard_outcome_archive_delete() FROM PUBLIC;
DROP TRIGGER IF EXISTS outcome_archive_row_guard ON equity_research.outcomes;
CREATE TRIGGER outcome_archive_row_guard BEFORE DELETE ON equity_research.outcomes
    FOR EACH ROW EXECUTE FUNCTION equity_research.guard_outcome_archive_delete();

GRANT USAGE ON SCHEMA equity_research TO quant_archive_worker;
GRANT SELECT, DELETE ON equity_research.outcomes TO quant_archive_worker;
REVOKE INSERT, UPDATE, TRUNCATE, REFERENCES, TRIGGER ON equity_research.outcomes
    FROM quant_archive_worker;
-- No access to source_decisions/observations; collector/runtime grants unchanged.
ALTER TABLE equity_research.outcomes ENABLE ROW LEVEL SECURITY;
ALTER TABLE equity_research.outcomes FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS archive_outcomes_read ON equity_research.outcomes;
CREATE POLICY archive_outcomes_read ON equity_research.outcomes
    FOR SELECT TO quant_archive_worker USING (true);
DROP POLICY IF EXISTS archive_outcomes_delete ON equity_research.outcomes;
CREATE POLICY archive_outcomes_delete ON equity_research.outcomes
    FOR DELETE TO quant_archive_worker USING (true);
-- No self-referencing DELETE policy (which would recurse through RLS).
-- The mandatory SECURITY INVOKER row trigger performs the eligibility check.

ALTER TABLE quant_app.archive_manifests DROP CONSTRAINT archive_manifests_source_table_check;
ALTER TABLE quant_app.archive_manifests ADD CONSTRAINT archive_manifests_source_table_check
    CHECK (source_table IN ('mf_nav','market_quotes','universe_membership_versions',
                           'scanner_observations','equity_research.outcomes'));
COMMIT;

-- To stop further research deletion without affecting existing archives:
-- REVOKE DELETE ON equity_research.outcomes FROM quant_archive_worker;
-- Keep both triggers, manifests and archived files. Do not re-run the older
-- manifest migrations after this extension; their narrower CHECK would fail.
