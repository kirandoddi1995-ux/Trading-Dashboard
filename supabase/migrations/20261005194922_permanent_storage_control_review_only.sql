-- REVIEW ONLY. Part of an UNFINISHED storage group: DO NOT apply independently.
-- Generated using pinned Supabase CLI migration new; no hosted execution.
-- This installs bounded root metadata only. It grants NO ledger DELETE and
-- bootstraps NO root. Readers/transport/archive proof still need integration.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';
-- Serialize against legacy ProductionRepository schema setup before any DDL.
SELECT pg_advisory_xact_lock(hashtext('quant-storage-schema-v1'));

DO $check$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='quant_app_runtime') THEN
    RAISE EXCEPTION 'STORAGE_RUNTIME_ROLE_MISSING';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname='quant_storage'
             AND nspowner <> current_user::regrole) THEN
    RAISE EXCEPTION 'STORAGE_SCHEMA_OWNER_UNEXPECTED';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
             WHERE n.nspname='quant_storage' AND c.relname='catalog_roots'
               AND (c.relowner<>current_user::regrole
                    OR obj_description(c.oid,'pg_class')
                       IS DISTINCT FROM 'permanent-storage-control-v1')) THEN
    RAISE EXCEPTION 'STORAGE_CONTROL_VERSION_UNEXPECTED';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='quant_storage_archiver') THEN
    CREATE ROLE quant_storage_archiver LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS
      NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='quant_storage_archiver'
             AND (NOT rolcanlogin OR rolinherit OR rolsuper OR rolbypassrls
                  OR rolcreatedb OR rolcreaterole OR rolreplication))
     OR EXISTS (SELECT 1 FROM pg_auth_members
                WHERE member=(SELECT oid FROM pg_roles WHERE rolname='quant_storage_archiver')
                   OR roleid=(SELECT oid FROM pg_roles WHERE rolname='quant_storage_archiver'))
     OR pg_has_role('quant_app_runtime','quant_storage_archiver','MEMBER') THEN
    RAISE EXCEPTION 'STORAGE_ARCHIVER_ROLE_UNSAFE';
  END IF;
END;
$check$;

CREATE SCHEMA IF NOT EXISTS quant_storage;
REVOKE ALL ON SCHEMA quant_storage FROM PUBLIC;
GRANT USAGE ON SCHEMA quant_storage TO quant_app_runtime,quant_storage_archiver;

CREATE TABLE IF NOT EXISTS quant_storage.catalog_roots (
  scope text PRIMARY KEY CHECK(scope IN ('ledger','relations')),
  generation bigint NOT NULL CHECK(generation>=0),
  root text NOT NULL CHECK(root ~ '^[0-9a-f]{64}$'),
  receipt_sha256 text NOT NULL CHECK(receipt_sha256 ~ '^[0-9a-f]{64}$'),
  previous_root text CHECK(previous_root ~ '^[0-9a-f]{64}$'),
  previous_receipt text CHECK(previous_receipt ~ '^[0-9a-f]{64}$'),
  segment text CHECK(segment ~ '^[0-9a-f]{64}$'),
  key_id text CHECK(key_id ~ '^[A-Za-z0-9_.:-]{1,128}$'),
  published_at timestamptz NOT NULL,
  CONSTRAINT storage_root_shape CHECK (
    (generation=0
      AND root='4cd567969cd41b76f83b2f8af04dee90007074a5016a06f28ed1821bcbe00698'
      AND receipt_sha256=repeat('0',64)
      AND previous_root IS NULL AND previous_receipt IS NULL
      AND segment IS NULL AND key_id IS NULL)
    OR (generation>0 AND receipt_sha256<>repeat('0',64)
      AND previous_root IS NOT NULL AND previous_receipt IS NOT NULL
      AND segment IS NOT NULL AND key_id IS NOT NULL))
);
COMMENT ON TABLE quant_storage.catalog_roots IS 'permanent-storage-control-v1';
DO $shape$
BEGIN
  IF (SELECT array_agg(attname::text ORDER BY attname)
      FROM pg_attribute WHERE attrelid='quant_storage.catalog_roots'::regclass
        AND attnum>0 AND NOT attisdropped) IS DISTINCT FROM
      ARRAY['generation','key_id','previous_receipt','previous_root','published_at',
            'receipt_sha256','root','scope','segment']::text[]
     OR EXISTS (SELECT 1 FROM pg_policy
                 WHERE polrelid='quant_storage.catalog_roots'::regclass
                   AND polname NOT IN ('storage_root_reader','storage_root_advance')) THEN
    RAISE EXCEPTION 'STORAGE_CONTROL_SHAPE_UNEXPECTED';
  END IF;
END;
$shape$;

-- No DELETE policy/grant for any non-owner role. An old signed receipt is not
-- permission to rewind an anchor. Row locking/CAS is required by the repository.
CREATE OR REPLACE FUNCTION quant_storage.guard_catalog_root()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER
SET search_path=pg_catalog,quant_storage AS $guard$
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'STORAGE_ROOT_DELETE_FORBIDDEN';
  ELSIF TG_OP='INSERT' THEN
    IF NEW.generation<>0 THEN
      RAISE EXCEPTION 'STORAGE_ROOT_BOOTSTRAP_INVALID';
    END IF;
  ELSIF NEW.scope<>OLD.scope OR OLD.generation=9223372036854775807
        OR NEW.generation<>OLD.generation+1
        OR NEW.previous_root<>OLD.root
        OR NEW.previous_receipt<>OLD.receipt_sha256
        OR NEW.receipt_sha256=OLD.receipt_sha256
        OR NEW.root=OLD.root THEN
    RAISE EXCEPTION 'STORAGE_ROOT_PREDECESSOR_MISMATCH';
  END IF;
  RETURN NEW;
END;
$guard$;
REVOKE ALL ON FUNCTION quant_storage.guard_catalog_root() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION quant_storage.guard_catalog_root() TO quant_storage_archiver;
DROP TRIGGER IF EXISTS storage_root_monotonic ON quant_storage.catalog_roots;
CREATE TRIGGER storage_root_monotonic BEFORE INSERT OR UPDATE OR DELETE
  ON quant_storage.catalog_roots FOR EACH ROW
  EXECUTE FUNCTION quant_storage.guard_catalog_root();

ALTER TABLE quant_storage.catalog_roots ENABLE ROW LEVEL SECURITY;
ALTER TABLE quant_storage.catalog_roots FORCE ROW LEVEL SECURITY;
REVOKE ALL ON quant_storage.catalog_roots FROM PUBLIC,quant_app_runtime,quant_storage_archiver;
-- Remove global default-privilege leftovers on this new control relation.
DO $revoke$
DECLARE role_name text;
BEGIN
  FOREACH role_name IN ARRAY ARRAY['anon','authenticated','service_role',
                                  'quant_archive_worker','equity_research_collector'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
      EXECUTE format('REVOKE ALL ON quant_storage.catalog_roots FROM %I',role_name);
    END IF;
  END LOOP;
END;
$revoke$;
GRANT SELECT ON quant_storage.catalog_roots TO quant_app_runtime,quant_storage_archiver;
GRANT UPDATE ON quant_storage.catalog_roots TO quant_storage_archiver;
DROP POLICY IF EXISTS storage_root_reader ON quant_storage.catalog_roots;
CREATE POLICY storage_root_reader ON quant_storage.catalog_roots
  FOR SELECT TO quant_app_runtime,quant_storage_archiver USING(true);
DROP POLICY IF EXISTS storage_root_advance ON quant_storage.catalog_roots;
CREATE POLICY storage_root_advance ON quant_storage.catalog_roots
  FOR UPDATE TO quant_storage_archiver USING(true) WITH CHECK(true);
-- Explicit owner bootstrap is a later reviewed step after object/root verification.
-- Password setup is owner-only, never part of this SQL or workflow output.
COMMIT;
