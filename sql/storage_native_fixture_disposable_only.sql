-- DISPOSABLE SERVICE ONLY. Never run this against Supabase/project storage.
-- Run with psql -X -v ON_ERROR_STOP=1; database must already have this exact name.
DO $$ BEGIN
  IF current_database() <> 'storage_conformance_sandbox' THEN
    RAISE EXCEPTION 'DISPOSABLE_DATABASE_REQUIRED';
  END IF;
END $$;
CREATE ROLE storage_conformance_writer LOGIN NOSUPERUSER NOBYPASSRLS
    NOCREATEDB NOCREATEROLE NOREPLICATION
    PASSWORD 'public-disposable-fixture-only';
COMMENT ON DATABASE storage_conformance_sandbox IS 'disposable-storage-guard-v1';
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE TABLE public.guard_probe(id integer PRIMARY KEY);
ALTER TABLE public.guard_probe ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.guard_probe FORCE ROW LEVEL SECURITY;
CREATE POLICY fixture_rows ON public.guard_probe TO storage_conformance_writer
    USING(true) WITH CHECK(true);
GRANT CONNECT ON DATABASE storage_conformance_sandbox TO storage_conformance_writer;
GRANT USAGE ON SCHEMA public TO storage_conformance_writer;
GRANT SELECT,INSERT ON public.guard_probe TO storage_conformance_writer;
