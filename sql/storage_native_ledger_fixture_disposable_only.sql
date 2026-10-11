-- DISPOSABLE ONLY: psql entry point; NEVER run on Supabase.
-- Load after storage_native_fixture_disposable_only.sql in the ephemeral service.
\set ON_ERROR_STOP on
DO $$ BEGIN
  IF current_database() <> 'storage_conformance_sandbox' OR current_user <> 'postgres'
     OR shobj_description((SELECT oid FROM pg_database WHERE datname=current_database()),
                          'pg_database') IS DISTINCT FROM 'disposable-storage-guard-v1' THEN
    RAISE EXCEPTION 'DISPOSABLE_DATABASE_REQUIRED';
  END IF;
END $$;
CREATE ROLE quant_app_runtime LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS
  NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD 'public-disposable-fixture-only';
CREATE SCHEMA quant_app;
CREATE TABLE quant_app.evidence_ledger_events (
  event_id uuid PRIMARY KEY, aggregate_id text NOT NULL, sequence_no bigint NOT NULL,
  event_type text NOT NULL, recorded_at timestamptz NOT NULL, effective_at timestamptz NOT NULL,
  source text NOT NULL, actor_id text NOT NULL, idempotency_key text NOT NULL UNIQUE,
  payload jsonb NOT NULL, previous_hash text NOT NULL, event_hash text NOT NULL,
  hash_algorithm text NOT NULL, schema_version integer NOT NULL, key_id text,
  UNIQUE(aggregate_id,sequence_no));
CREATE FUNCTION quant_app.fixture_immutable() RETURNS trigger LANGUAGE plpgsql
  AS $$ BEGIN RAISE EXCEPTION 'IMMUTABLE'; END; $$;
CREATE TRIGGER evidence_ledger_no_update BEFORE UPDATE ON quant_app.evidence_ledger_events
  FOR EACH ROW EXECUTE FUNCTION quant_app.fixture_immutable();
CREATE TRIGGER evidence_ledger_no_delete BEFORE DELETE ON quant_app.evidence_ledger_events
  FOR EACH ROW EXECUTE FUNCTION quant_app.fixture_immutable();
ALTER TABLE quant_app.evidence_ledger_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE quant_app.evidence_ledger_events FORCE ROW LEVEL SECURITY;
CREATE POLICY fixture_read ON quant_app.evidence_ledger_events FOR SELECT
  TO quant_app_runtime USING(true);
CREATE POLICY fixture_append ON quant_app.evidence_ledger_events FOR INSERT
  TO quant_app_runtime WITH CHECK(true);
GRANT USAGE ON SCHEMA quant_app TO quant_app_runtime;
GRANT SELECT,INSERT ON quant_app.evidence_ledger_events TO quant_app_runtime;

-- Execute the reviewed migrations themselves, not copies of their functions.
\ir ../supabase/migrations/20261005194922_permanent_storage_control_review_only.sql
\ir ../supabase/migrations/20261005200414_permanent_storage_ledger_review_only.sql
\ir ../supabase/migrations/20261005210149_permanent_storage_heads_review_only.sql

-- Public synthetic credentials/commission ONLY inside this fresh fixture.
ALTER ROLE quant_storage_archiver PASSWORD 'public-disposable-fixture-only';
INSERT INTO quant_storage.catalog_roots(scope,generation,root,receipt_sha256,published_at)
  SELECT scope,0,'4cd567969cd41b76f83b2f8af04dee90007074a5016a06f28ed1821bcbe00698',repeat('0',64),
    '2026-10-11T00:00:00Z'::timestamptz
  FROM (VALUES('ledger'),('relations')) AS scopes(scope);
UPDATE quant_storage.ledger_control SET heads_enabled=true,pruning_enabled=true,
  head_audit_sha256=repeat('e',64),reader_fingerprint=repeat('f',64),
  commissioned_at='2026-10-11T00:00:00Z';
