-- DISPOSABLE ONLY: load after shared native fixtures, never hosted/production.
\set ON_ERROR_STOP on
BEGIN;
DO $$ BEGIN
 IF current_database()<>'storage_conformance_sandbox' OR current_user<>'postgres'
 OR shobj_description((SELECT oid FROM pg_database WHERE datname=current_database()),
 'pg_database') IS DISTINCT FROM 'disposable-storage-guard-v1'
 THEN RAISE EXCEPTION 'DISPOSABLE_DATABASE_REQUIRED'; END IF;
END $$;
CREATE TABLE public.overnight_storage_fixture(marker text PRIMARY KEY);
INSERT INTO public.overnight_storage_fixture VALUES ('staged-three-methods-v1');
CREATE TABLE quant_app.collection_runs(
 run_id uuid PRIMARY KEY, mode text, scheduled_for timestamptz,
 started_at timestamptz, status text, provider text, metadata jsonb);
CREATE SCHEMA equity_operations;
CREATE TABLE equity_operations.scan_runs(
 run_id text PRIMARY KEY, owner_id text, signature text, scan_mode text,
 horizon_sessions integer, status text, fencing_token bigint, started_at timestamptz,
 heartbeat_at timestamptz, metadata jsonb);
CREATE TABLE equity_operations.scan_candidates(
 run_id text REFERENCES equity_operations.scan_runs, instrument text, item jsonb,
 status text, attempt_no integer, updated_at timestamptz, checkpoint_fencing_token bigint,
 PRIMARY KEY(run_id,instrument));
CREATE SCHEMA derivatives_reference;
CREATE TABLE derivatives_reference.source_health(
 kind text, trading_date date, status text, updated_at timestamptz, source_hash text,
 PRIMARY KEY(kind,trading_date));
DO $$ DECLARE relation text; BEGIN
 FOREACH relation IN ARRAY ARRAY['quant_app.collection_runs','equity_operations.scan_runs',
 'equity_operations.scan_candidates','derivatives_reference.source_health'] LOOP
 EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY',relation);
 EXECUTE format('ALTER TABLE %s FORCE ROW LEVEL SECURITY',relation);
 EXECUTE format('CREATE POLICY overnight_storage_fixture_rows ON %s TO storage_conformance_writer USING(true) WITH CHECK(true)',relation);
 EXECUTE format('GRANT SELECT,INSERT,UPDATE ON %s TO storage_conformance_writer',relation);
 END LOOP;
END $$;
GRANT USAGE ON SCHEMA quant_app,equity_operations,derivatives_reference TO storage_conformance_writer;
GRANT SELECT ON public.overnight_storage_fixture TO storage_conformance_writer;
COMMIT;
