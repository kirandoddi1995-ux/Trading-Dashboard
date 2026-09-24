-- REVIEW / MANUAL EXECUTION ONLY. Requires sql/drive_archive_draft.sql first.
-- No source data deleted. Apply before uploading the new maintenance code.
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';

ALTER TABLE quant_app.archive_manifests
    DROP CONSTRAINT IF EXISTS archive_manifests_source_table_check;
ALTER TABLE quant_app.archive_manifests ADD CONSTRAINT archive_manifests_source_table_check
    CHECK (source_table IN ('mf_nav','market_quotes',
                           'universe_membership_versions','scanner_observations'));

-- Replace the existing CASCADE: a concurrent target insert must block deletion,
-- never allow deleting its training label as a side effect of maintenance.
ALTER TABLE quant_app.prediction_targets
    DROP CONSTRAINT IF EXISTS prediction_targets_observation_id_fkey;
ALTER TABLE quant_app.prediction_targets ADD CONSTRAINT prediction_targets_observation_id_fkey
    FOREIGN KEY (observation_id) REFERENCES quant_app.scanner_observations(observation_id)
    ON DELETE RESTRICT;

GRANT SELECT, DELETE ON quant_app.universe_membership_versions,
    quant_app.scanner_observations TO quant_archive_worker;
-- Dependency lookups only; deliberately not table-wide SELECT privileges.
GRANT SELECT (observation_id) ON quant_app.prediction_targets TO quant_archive_worker;
GRANT SELECT (snapshot_id,snapshot_date,observed_at,is_complete)
    ON quant_app.universe_snapshot_versions TO quant_archive_worker;

-- Preserve pre-existing runtime behavior when enabling RLS for the first time.
-- Do NOT widen any already-enabled RLS policy. Existing table grants still limit
-- operations; this adds no runtime table privileges.
DO $$ DECLARE table_name text; BEGIN
    FOREACH table_name IN ARRAY ARRAY['universe_membership_versions','scanner_observations',
                                     'prediction_targets','universe_snapshot_versions'] LOOP
        IF NOT (SELECT relrowsecurity FROM pg_class
                WHERE oid=format('quant_app.%I',table_name)::regclass) THEN
            EXECUTE format('CREATE POLICY archive_preserve_runtime ON quant_app.%I '
                'TO quant_app_runtime USING (true) WITH CHECK (true)',table_name);
            EXECUTE format('ALTER TABLE quant_app.%I ENABLE ROW LEVEL SECURITY',table_name);
        END IF;
    END LOOP;
END $$;

DROP POLICY IF EXISTS archive_membership_read ON quant_app.universe_membership_versions;
CREATE POLICY archive_membership_read ON quant_app.universe_membership_versions
    FOR SELECT TO quant_archive_worker USING (true);
DROP POLICY IF EXISTS archive_membership_delete ON quant_app.universe_membership_versions;
CREATE POLICY archive_membership_delete ON quant_app.universe_membership_versions
    FOR DELETE TO quant_archive_worker USING (true);
DROP POLICY IF EXISTS archive_scanner_read ON quant_app.scanner_observations;
CREATE POLICY archive_scanner_read ON quant_app.scanner_observations
    FOR SELECT TO quant_archive_worker USING (true);
DROP POLICY IF EXISTS archive_scanner_delete ON quant_app.scanner_observations;
CREATE POLICY archive_scanner_delete ON quant_app.scanner_observations
    FOR DELETE TO quant_archive_worker USING (stage2_pass IS FALSE AND NOT EXISTS (
        SELECT 1 FROM quant_app.prediction_targets t
        WHERE t.observation_id=scanner_observations.observation_id));
DROP POLICY IF EXISTS archive_target_dependency_read ON quant_app.prediction_targets;
CREATE POLICY archive_target_dependency_read ON quant_app.prediction_targets
    FOR SELECT TO quant_archive_worker USING (true);
DROP POLICY IF EXISTS archive_snapshot_dependency_read ON quant_app.universe_snapshot_versions;
CREATE POLICY archive_snapshot_dependency_read ON quant_app.universe_snapshot_versions
    FOR SELECT TO quant_archive_worker USING (true);

-- Existing PK indexes support target and snapshot lookups. Avoid another large
-- index on the 78 MB membership table; batches remain bounded and time-limited.
COMMIT;

-- Rollback: disable ARCHIVE_ENABLED first. Do not restore ON DELETE CASCADE.
-- Revoke the four grants above and drop archive_* policies introduced here if
-- reverting code. Retain manifests/Drive files; restore verified rows before any
-- future reader that needs archived membership history. No automatic rollback.
