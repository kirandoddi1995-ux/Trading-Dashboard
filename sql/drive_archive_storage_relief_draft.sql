-- REVIEW ONLY: owner runs manually after all three existing Drive archive drafts.
-- No source rows are deleted; no automatic startup execution. Transactional/rerunnable.
-- Do not reapply older drafts afterwards: they restore narrower manifest policies.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';

DO $$ BEGIN
    IF (SELECT count(*) FROM pg_trigger WHERE tgrelid='equity_research.outcomes'::regclass
        AND tgenabled IN ('O','A') AND NOT tgisinternal AND
        ((tgname='outcome_append_only' AND tgtype=58
          AND tgfoid='equity_research.reject_mutation()'::regprocedure)
         OR (tgname='outcome_archive_row_guard' AND tgtype=11
          AND tgfoid='equity_research.guard_outcome_archive_delete()'::regprocedure))) <> 2 THEN
        RAISE EXCEPTION 'Existing research archive protections required';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE contype='f'
        AND confrelid='quant_app.universe_membership'::regclass) THEN
        RAISE EXCEPTION 'Unexpected canonical membership FK dependency: review before migration';
    END IF;
END $$;

-- Keep the per-row protection cheap; repeated absent-date probes must not scan
-- the whole scanner table. Small single-column btree, not a wide covering index.
-- Normal (not concurrent) build inside this transaction: bounded lock timeout,
-- owner runs during the morning maintenance window, not while scans are writing.
CREATE INDEX IF NOT EXISTS scanner_universe_snapshot_date_idx
    ON quant_app.scanner_observations(universe_snapshot_date);
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_index i JOIN pg_class idx ON idx.oid=i.indexrelid
        JOIN pg_am am ON am.oid=idx.relam
        JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=i.indkey[0]
        WHERE i.indexrelid='quant_app.scanner_universe_snapshot_date_idx'::regclass
          AND i.indrelid='quant_app.scanner_observations'::regclass
          AND i.indisvalid AND i.indisready AND i.indnkeyatts=1
          AND i.indpred IS NULL AND i.indexprs IS NULL AND am.amname='btree'
          AND a.attname='universe_snapshot_date') THEN
        RAISE EXCEPTION 'Scanner dependency index invalid or has unexpected definition';
    END IF;
    -- Do not silently hide data from an unreviewed reader when enabling RLS.
    -- Superuser/BYPASSRLS roles remain unaffected. Other effective table/column
    -- readers must be explicitly reviewed, including inherited/PUBLIC grants.
    IF EXISTS (SELECT 1 FROM pg_class c CROSS JOIN pg_roles r
        WHERE c.oid IN ('quant_app.universe_membership'::regclass,
                        'quant_app.universe_snapshots'::regclass)
          AND NOT c.relrowsecurity AND NOT r.rolsuper AND NOT r.rolbypassrls
          -- Predefined pg_read_all_data is a NOLOGIN capability, not a reader
          -- session. Any real role inheriting it is still checked below.
          AND r.rolname !~ '^pg_'
          AND r.rolname NOT IN ('quant_app_runtime','quant_archive_worker')
          AND has_schema_privilege(r.oid,c.relnamespace,'USAGE')
          AND has_any_column_privilege(r.oid,c.oid,'SELECT')) THEN
        RAISE EXCEPTION 'Unreviewed canonical reader role: inspect grants before enabling RLS';
    END IF;
END $$;

-- Only this table changes from 14 to 7 UTC calendar days. Latest always survives.
CREATE OR REPLACE FUNCTION equity_research.guard_outcome_archive_delete() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$
BEGIN
    IF current_user <> 'quant_archive_worker' OR TG_OP <> 'DELETE' THEN
        RAISE EXCEPTION 'Research evidence is append-only';
    END IF;
    IF OLD.recorded_at >= (((statement_timestamp() AT TIME ZONE 'UTC')::date - 7)
                           ::timestamp AT TIME ZONE 'UTC') THEN
        RAISE EXCEPTION 'Research outcome is inside the protected retention window';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM equity_research.outcomes newer
        WHERE newer.decision_id=OLD.decision_id
        AND (newer.recorded_at,newer.snapshot_id) > (OLD.recorded_at,OLD.snapshot_id)) THEN
        RAISE EXCEPTION 'Latest research outcome must be retained';
    END IF;
    RETURN OLD;
END $$;
REVOKE ALL ON FUNCTION equity_research.guard_outcome_archive_delete() FROM PUBLIC;

ALTER TABLE quant_app.archive_manifests DROP CONSTRAINT archive_manifests_source_table_check;
ALTER TABLE quant_app.archive_manifests ADD CONSTRAINT archive_manifests_source_table_check
    CHECK(source_table IN ('mf_nav','market_quotes','universe_membership_versions',
                          'scanner_observations','equity_research.outcomes','universe_membership'));

GRANT SELECT,DELETE ON quant_app.universe_membership TO quant_archive_worker;
REVOKE INSERT,UPDATE,TRUNCATE,REFERENCES,TRIGGER ON quant_app.universe_membership FROM quant_archive_worker;
GRANT SELECT(snapshot_date,observed_at,is_complete) ON quant_app.universe_snapshots TO quant_archive_worker;
-- Headers stay online: no DELETE or table-wide SELECT grant for them.
DO $$ DECLARE t text; BEGIN
    FOREACH t IN ARRAY ARRAY['universe_membership','universe_snapshots'] LOOP
        IF NOT (SELECT relrowsecurity FROM pg_class WHERE oid=format('quant_app.%I',t)::regclass) THEN
            EXECUTE format('CREATE POLICY archive_preserve_runtime ON quant_app.%I '
                'TO quant_app_runtime USING(true) WITH CHECK(true)',t);
            EXECUTE format('ALTER TABLE quant_app.%I ENABLE ROW LEVEL SECURITY',t);
        END IF;
    END LOOP;
END $$;
DROP POLICY IF EXISTS archive_canonical_read ON quant_app.universe_membership;
CREATE POLICY archive_canonical_read ON quant_app.universe_membership
    FOR SELECT TO quant_archive_worker USING(true);
DROP POLICY IF EXISTS archive_canonical_delete ON quant_app.universe_membership;
CREATE POLICY archive_canonical_delete ON quant_app.universe_membership
    FOR DELETE TO quant_archive_worker USING(true);
DROP POLICY IF EXISTS archive_canonical_header_read ON quant_app.universe_snapshots;
CREATE POLICY archive_canonical_header_read ON quant_app.universe_snapshots
    FOR SELECT TO quant_archive_worker USING(true);

-- Narrow definer helper: ONLY fixed-table locks, no data reads/writes, no arguments.
-- Avoid granting archive worker UPDATE/ownership on headers merely to acquire locks.
-- Archive code calls this after Drive verification, in the DELETE transaction.
CREATE OR REPLACE FUNCTION quant_app.lock_canonical_archive_dependencies() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
    LOCK TABLE quant_app.universe_snapshots, quant_app.universe_membership,
               quant_app.scanner_observations IN SHARE ROW EXCLUSIVE MODE;
END $$;
REVOKE ALL ON FUNCTION quant_app.lock_canonical_archive_dependencies() FROM PUBLIC,
    quant_app_runtime,equity_research_collector,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION quant_app.lock_canonical_archive_dependencies() TO quant_archive_worker;

CREATE OR REPLACE FUNCTION quant_app.guard_canonical_archive_delete() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$
DECLARE cutoff date := (statement_timestamp() AT TIME ZONE 'UTC')::date - 14;
BEGIN
    -- Preserve existing runtime same-day replacement, not a new runtime privilege.
    IF current_user <> 'quant_archive_worker' THEN RETURN OLD; END IF;
    PERFORM quant_app.lock_canonical_archive_dependencies();
    IF NOT (OLD.snapshot_date < cutoff
        AND OLD.observed_at < (cutoff::timestamp AT TIME ZONE 'UTC')
        AND EXISTS (SELECT 1 FROM quant_app.universe_snapshots h
            WHERE h.snapshot_date=OLD.snapshot_date
              AND h.observed_at < (cutoff::timestamp AT TIME ZONE 'UTC'))
        AND OLD.snapshot_date < (SELECT max(snapshot_date) FROM quant_app.universe_snapshots)
        AND OLD.snapshot_date < (SELECT max(snapshot_date) FROM quant_app.universe_snapshots WHERE is_complete)
        AND NOT EXISTS (SELECT 1 FROM quant_app.scanner_observations o
            WHERE o.universe_snapshot_date=OLD.snapshot_date)) IS TRUE THEN
        RAISE EXCEPTION 'Canonical snapshot is protected by age or reader dependencies';
    END IF;
    RETURN OLD;
END $$;
REVOKE ALL ON FUNCTION quant_app.guard_canonical_archive_delete() FROM PUBLIC;
DROP TRIGGER IF EXISTS canonical_archive_row_guard ON quant_app.universe_membership;
CREATE TRIGGER canonical_archive_row_guard BEFORE DELETE ON quant_app.universe_membership
    FOR EACH ROW EXECUTE FUNCTION quant_app.guard_canonical_archive_delete();
COMMIT;

-- Stop deletion: set GitHub ARCHIVE_DELETE_ENABLED=false (collectors unaffected).
-- Optional owner containment: REVOKE DELETE ON quant_app.universe_membership FROM quant_archive_worker;
-- Do not drop manifests/headers or triggers. Rollback cannot restore deleted data:
-- restore verified Parquet rows first if needed. Reverting the outcome policy to
-- 14 days requires a reviewed function replacement, not rerunning old migrations.
