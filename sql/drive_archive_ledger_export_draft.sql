-- REVIEW ONLY: owner runs once in the Supabase SQL editor (ROLLING_WINDOW_2026-11-07.md).
-- Gives the archive role READ access to the evidence ledger so it can be exported to Drive.
-- Nothing is deleted or changed in the ledger; the archive job refuses to delete ledger rows,
-- and this script fails unless the ledger's no-delete/no-update triggers are in place and the
-- archive role holds no write privilege on it. Transactional and rerunnable.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

DO $$ BEGIN
    IF (SELECT count(*) FROM pg_trigger
        WHERE tgrelid='quant_app.evidence_ledger_events'::regclass AND NOT tgisinternal
          AND tgenabled IN ('O','A')
          AND tgname IN ('evidence_ledger_no_delete','evidence_ledger_no_update')) <> 2 THEN
        RAISE EXCEPTION 'Ledger append-only triggers required before export access';
    END IF;
    -- With row-level security on and no policy, the archive role would silently see no rows.
    IF (SELECT relrowsecurity FROM pg_class WHERE oid='quant_app.evidence_ledger_events'::regclass) THEN
        RAISE EXCEPTION 'Ledger row-level security is on: review a read policy first';
    END IF;
END $$;

-- The catalog accepts ledger batches (same list as the storage-relief draft, plus the ledger).
ALTER TABLE quant_app.archive_manifests DROP CONSTRAINT archive_manifests_source_table_check;
ALTER TABLE quant_app.archive_manifests ADD CONSTRAINT archive_manifests_source_table_check
    CHECK(source_table IN ('mf_nav','market_quotes','universe_membership_versions',
                          'scanner_observations','equity_research.outcomes','universe_membership',
                          'evidence_ledger_events'));

GRANT SELECT ON quant_app.evidence_ledger_events TO quant_archive_worker;

DO $$ BEGIN
    IF has_table_privilege('quant_archive_worker','quant_app.evidence_ledger_events',
                           'DELETE,INSERT,UPDATE,TRUNCATE,TRIGGER') THEN
        RAISE EXCEPTION 'Archive role must never write the ledger';
    END IF;
END $$;
COMMIT;
