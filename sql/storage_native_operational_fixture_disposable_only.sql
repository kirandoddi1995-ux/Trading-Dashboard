-- DISPOSABLE ONLY; NEVER run this entry point on Supabase.
\set ON_ERROR_STOP on
DO $$ BEGIN
  IF current_database()<>'storage_conformance_sandbox' OR current_user<>'postgres'
    OR shobj_description((SELECT oid FROM pg_database WHERE datname=current_database()),
       'pg_database') IS DISTINCT FROM 'disposable-storage-guard-v1' THEN
    RAISE EXCEPTION 'DISPOSABLE_DATABASE_REQUIRED';
  END IF;
END $$;
\ir operational_receipts_review_only.sql
-- Enable only the new synthetic namespace, never live operations.
UPDATE quant_operational_receipts.control SET enabled=true;
INSERT INTO quant_operational_receipts.leases VALUES
 ('expired-serial','old',1,'2000-01-01T00:00:00Z'),
 ('expired-cas','old',1,'2000-01-01T00:00:00Z'),
 ('expired-old-writer','old',1,'2000-01-01T00:00:00Z');
