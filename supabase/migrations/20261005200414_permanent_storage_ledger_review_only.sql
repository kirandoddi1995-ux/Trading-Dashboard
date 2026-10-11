-- REVIEW ONLY: unfinished storage group. No hosted execution authorized.
-- Requires the preceding permanent_storage_control_review_only migration.
-- Source pruning remains DISABLED until owner commissions ALL cold readers.
BEGIN;
SET LOCAL lock_timeout='2s';
SET LOCAL statement_timeout='30s';
SELECT pg_advisory_xact_lock(hashtext('quant-storage-schema-v1'));
DO $preflight$
BEGIN
  IF to_regclass('quant_storage.catalog_roots') IS NULL
     OR to_regclass('quant_app.evidence_ledger_events') IS NULL THEN
    RAISE EXCEPTION 'STORAGE_LEDGER_SCHEMA_MISSING';
  END IF;
  IF obj_description('quant_storage.catalog_roots'::regclass,'pg_class')
       IS DISTINCT FROM 'permanent-storage-control-v1'
     OR to_regprocedure('pg_catalog.sha256(bytea)') IS NULL THEN
    RAISE EXCEPTION 'STORAGE_LEDGER_SCHEMA_UNSUPPORTED';
  END IF;
  IF (SELECT array_agg(attname::text ORDER BY attname)
      FROM pg_attribute WHERE attrelid='quant_app.evidence_ledger_events'::regclass
        AND attnum>0 AND NOT attisdropped) IS DISTINCT FROM
    ARRAY['actor_id','aggregate_id','effective_at','event_hash','event_id','event_type',
          'hash_algorithm','idempotency_key','key_id','payload','previous_hash',
          'recorded_at','schema_version','sequence_no','source']::text[] THEN
    RAISE EXCEPTION 'STORAGE_LEDGER_SHAPE_UNEXPECTED';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname='quant_storage'
             AND nspowner<>current_user::regrole)
     OR EXISTS (SELECT 1 FROM pg_roles WHERE rolname='quant_storage_archiver'
                 AND (NOT rolcanlogin OR rolinherit OR rolsuper OR rolbypassrls
                      OR rolcreatedb OR rolcreaterole OR rolreplication))
     OR EXISTS (SELECT 1 FROM pg_auth_members
                 WHERE member='quant_storage_archiver'::regrole
                    OR roleid='quant_storage_archiver'::regrole) THEN
    RAISE EXCEPTION 'STORAGE_LEDGER_ROLE_OR_OWNER_UNSAFE';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_class
             WHERE oid=to_regclass('quant_storage.ledger_control')
               AND (relowner<>current_user::regrole
                    OR obj_description(oid,'pg_class')
                       IS DISTINCT FROM 'permanent-storage-ledger-control-v1')) THEN
    RAISE EXCEPTION 'STORAGE_LEDGER_CONTROL_VERSION_UNEXPECTED';
  END IF;
END;
$preflight$;

CREATE TABLE IF NOT EXISTS quant_storage.ledger_control (
  singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
  pruning_enabled boolean NOT NULL DEFAULT false,
  heads_enabled boolean NOT NULL DEFAULT false,
  head_audit_sha256 text CHECK(head_audit_sha256 ~ '^[0-9a-f]{64}$'),
  reader_fingerprint text CHECK(reader_fingerprint ~ '^[0-9a-f]{64}$'),
  commissioned_at timestamptz,
  CHECK(NOT heads_enabled OR head_audit_sha256 IS NOT NULL),
  CHECK(NOT pruning_enabled OR (heads_enabled AND reader_fingerprint IS NOT NULL
                               AND commissioned_at IS NOT NULL))
);
COMMENT ON TABLE quant_storage.ledger_control IS 'permanent-storage-ledger-control-v1';
DO $shape$
BEGIN
  IF (SELECT array_agg(attname::text ORDER BY attname)
      FROM pg_attribute WHERE attrelid='quant_storage.ledger_control'::regclass
        AND attnum>0 AND NOT attisdropped) IS DISTINCT FROM
    ARRAY['commissioned_at','head_audit_sha256','heads_enabled','pruning_enabled',
          'reader_fingerprint','singleton']::text[]
     OR EXISTS (SELECT 1 FROM pg_policy
                 WHERE polrelid='quant_storage.ledger_control'::regclass
                   AND polname<>'storage_ledger_control_reader') THEN
    RAISE EXCEPTION 'STORAGE_LEDGER_CONTROL_SHAPE_UNEXPECTED';
  END IF;
END;
$shape$;
INSERT INTO quant_storage.ledger_control(singleton) VALUES(true) ON CONFLICT DO NOTHING;
ALTER TABLE quant_storage.ledger_control ENABLE ROW LEVEL SECURITY;
ALTER TABLE quant_storage.ledger_control FORCE ROW LEVEL SECURITY;
REVOKE ALL ON quant_storage.ledger_control FROM PUBLIC,quant_app_runtime,quant_storage_archiver;
DO $revoke$
DECLARE role_name text;
BEGIN
  FOREACH role_name IN ARRAY ARRAY['anon','authenticated','service_role',
                                  'quant_archive_worker','equity_research_collector'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
      EXECUTE format('REVOKE ALL ON quant_storage.ledger_control FROM %I',role_name);
    END IF;
  END LOOP;
END;
$revoke$;
GRANT SELECT ON quant_storage.ledger_control TO quant_app_runtime,quant_storage_archiver;
DROP POLICY IF EXISTS storage_ledger_control_reader ON quant_storage.ledger_control;
CREATE POLICY storage_ledger_control_reader ON quant_storage.ledger_control
  FOR SELECT TO quant_app_runtime,quant_storage_archiver USING(true);

CREATE OR REPLACE FUNCTION quant_storage.require_ledger_stage()
RETURNS void LANGUAGE plpgsql SECURITY INVOKER
SET search_path=pg_catalog,quant_storage AS $stage$
DECLARE approved text; staged text; declared_count bigint;
BEGIN
  IF current_user<>'quant_storage_archiver' THEN
    RAISE EXCEPTION 'STORAGE_LEDGER_ARCHIVER_REQUIRED';
  END IF;
  SELECT reader_fingerprint INTO approved FROM quant_storage.ledger_control
    WHERE singleton AND pruning_enabled AND heads_enabled;
  IF approved IS NULL THEN
    RAISE EXCEPTION 'STORAGE_COLD_READERS_NOT_COMMISSIONED';
  END IF;
  IF current_setting('TimeZone')<>'UTC'
     OR to_regclass('pg_temp.quant_storage_ledger_stage') IS NULL
     OR to_regclass('pg_temp.quant_storage_ledger_rows') IS NULL THEN
    RAISE EXCEPTION 'STORAGE_LEDGER_STAGE_MISSING';
  END IF;
  IF (SELECT count(*) FROM pg_temp.quant_storage_ledger_stage)<>1 THEN
    RAISE EXCEPTION 'STORAGE_LEDGER_STAGE_INVALID';
  END IF;
  SELECT reader_fingerprint,source_count INTO staged,declared_count
    FROM pg_temp.quant_storage_ledger_stage;
  IF staged IS DISTINCT FROM approved OR declared_count IS NULL
     OR declared_count NOT BETWEEN 1 AND 900
     OR (SELECT count(*) FROM pg_temp.quant_storage_ledger_rows)<>declared_count
     OR (SELECT count(DISTINCT aggregate_id) FROM pg_temp.quant_storage_ledger_rows)>32 THEN
    RAISE EXCEPTION 'STORAGE_LEDGER_STAGE_INVALID';
  END IF;
END;
$stage$;

CREATE OR REPLACE FUNCTION quant_storage.guard_ledger_delete()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER
SET search_path=pg_catalog,quant_storage AS $delete$
DECLARE allowed boolean;
BEGIN
  -- Statement guard checks commissioning and bounded staging once per batch.
  IF TG_LEVEL='STATEMENT' THEN
    PERFORM quant_storage.require_ledger_stage();
    RETURN NULL;
  END IF;
  IF current_user<>'quant_storage_archiver' THEN
    RAISE EXCEPTION 'STORAGE_LEDGER_ARCHIVER_REQUIRED';
  END IF;
  SELECT true INTO allowed FROM pg_temp.quant_storage_ledger_rows p
    WHERE p.event_id=OLD.event_id AND p.event_hash=OLD.event_hash
      AND p.aggregate_id=OLD.aggregate_id AND p.sequence_no=OLD.sequence_no
      AND p.source_sha256=encode(sha256(convert_to(to_jsonb(OLD)::text,'UTF8')),'hex');
  IF allowed IS DISTINCT FROM true THEN
    RAISE EXCEPTION 'STORAGE_LEDGER_ROW_NOT_VERIFIED';
  END IF;
  RETURN OLD;
END;
$delete$;

CREATE OR REPLACE FUNCTION quant_storage.guard_ledger_root()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER
SET search_path=pg_catalog,quant_storage AS $root$
DECLARE valid boolean;
BEGIN
  IF NEW.scope<>'ledger' THEN RETURN NEW; END IF;
  PERFORM quant_storage.require_ledger_stage();
  SELECT true INTO valid FROM pg_temp.quant_storage_ledger_stage s
    WHERE s.previous_generation=OLD.generation AND s.previous_root=OLD.root
      AND s.previous_receipt=OLD.receipt_sha256
      AND s.next_generation=NEW.generation AND s.next_root=NEW.root
      AND s.next_receipt=NEW.receipt_sha256 AND s.segment=NEW.segment;
  IF valid IS DISTINCT FROM true THEN
    RAISE EXCEPTION 'STORAGE_LEDGER_ROOT_STAGE_MISMATCH';
  END IF;
  RETURN NEW;
END;
$root$;

CREATE OR REPLACE FUNCTION quant_storage.check_ledger_archive_commit()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER
SET search_path=pg_catalog,quant_storage AS $commit$
DECLARE advanced boolean;
BEGIN
  IF TG_TABLE_SCHEMA='quant_storage' THEN
    IF NEW.scope<>'ledger' THEN RETURN NULL; END IF;
  END IF;
  SELECT true INTO advanced FROM quant_storage.catalog_roots r
    JOIN pg_temp.quant_storage_ledger_stage s
      ON r.scope='ledger' AND r.generation=s.next_generation AND r.root=s.next_root
       AND r.receipt_sha256=s.next_receipt AND r.segment=s.segment;
  IF advanced IS DISTINCT FROM true THEN
    RAISE EXCEPTION 'STORAGE_LEDGER_ROOT_NOT_ADVANCED';
  END IF;
  -- One root-trigger check verifies the entire deletion set, not an O(n^2)
  -- full-ledger scan for every deleted event. Source-row checks stay indexed.
  IF TG_TABLE_SCHEMA='quant_storage' AND EXISTS (
    SELECT 1 FROM quant_app.evidence_ledger_events e
      JOIN pg_temp.quant_storage_ledger_rows p ON e.event_id=p.event_id) THEN
    RAISE EXCEPTION 'STORAGE_LEDGER_BATCH_NOT_DELETED';
  END IF;
  RETURN NULL;
END;
$commit$;

REVOKE ALL ON FUNCTION quant_storage.require_ledger_stage(),
  quant_storage.guard_ledger_delete(),quant_storage.guard_ledger_root(),
  quant_storage.check_ledger_archive_commit() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION quant_storage.require_ledger_stage(),
  quant_storage.guard_ledger_delete(),quant_storage.guard_ledger_root(),
  quant_storage.check_ledger_archive_commit() TO quant_storage_archiver;

DROP TRIGGER IF EXISTS storage_ledger_delete_statement ON quant_app.evidence_ledger_events;
CREATE TRIGGER storage_ledger_delete_statement BEFORE DELETE ON quant_app.evidence_ledger_events
  FOR EACH STATEMENT EXECUTE FUNCTION quant_storage.guard_ledger_delete();
-- Keep the UPDATE immutability trigger. Only the DELETE trigger gains a narrowly
-- gated verified-archive path, initially disabled by ledger_control above.
DROP TRIGGER IF EXISTS evidence_ledger_no_delete ON quant_app.evidence_ledger_events;
CREATE TRIGGER evidence_ledger_no_delete BEFORE DELETE ON quant_app.evidence_ledger_events
  FOR EACH ROW EXECUTE FUNCTION quant_storage.guard_ledger_delete();
DROP TRIGGER IF EXISTS storage_ledger_delete_commit ON quant_app.evidence_ledger_events;
CREATE CONSTRAINT TRIGGER storage_ledger_delete_commit
  AFTER DELETE ON quant_app.evidence_ledger_events DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION quant_storage.check_ledger_archive_commit();
DROP TRIGGER IF EXISTS storage_ledger_root_stage ON quant_storage.catalog_roots;
CREATE TRIGGER storage_ledger_root_stage BEFORE UPDATE ON quant_storage.catalog_roots
  FOR EACH ROW EXECUTE FUNCTION quant_storage.guard_ledger_root();
DROP TRIGGER IF EXISTS storage_ledger_root_commit ON quant_storage.catalog_roots;
CREATE CONSTRAINT TRIGGER storage_ledger_root_commit
  AFTER UPDATE ON quant_storage.catalog_roots DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION quant_storage.check_ledger_archive_commit();

GRANT USAGE ON SCHEMA quant_app TO quant_storage_archiver;
REVOKE ALL ON quant_app.evidence_ledger_events FROM quant_storage_archiver;
GRANT SELECT,DELETE ON quant_app.evidence_ledger_events TO quant_storage_archiver;
DROP POLICY IF EXISTS storage_archiver_ledger_read ON quant_app.evidence_ledger_events;
CREATE POLICY storage_archiver_ledger_read ON quant_app.evidence_ledger_events
  FOR SELECT TO quant_storage_archiver USING(true);
DROP POLICY IF EXISTS storage_archiver_ledger_delete ON quant_app.evidence_ledger_events;
CREATE POLICY storage_archiver_ledger_delete ON quant_app.evidence_ledger_events
  FOR DELETE TO quant_storage_archiver USING(true);
-- Preserve source RLS flags/other reader policies; this is not a blanket RLS rollout.
COMMIT;
