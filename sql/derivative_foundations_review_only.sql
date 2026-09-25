-- REVIEW ONLY. Apply manually; never executed by application startup.
-- No existing tables or roles are altered. Provision a password privately for
-- quant_derivative_ingestor after review. Rules must be populated by the owner
-- from reviewed exchange sources, not fabricated from broker expiry markers.
BEGIN;
CREATE SCHEMA IF NOT EXISTS derivatives_reference;
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='quant_derivative_ingestor') THEN
    CREATE ROLE quant_derivative_ingestor LOGIN NOINHERIT NOSUPERUSER NOCREATEDB
      NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 2;
  END IF;
END $$;
CREATE TABLE IF NOT EXISTS derivatives_reference.contract_versions (
  version text PRIMARY KEY CHECK (version ~ '^[a-f0-9]{64}$'),
  payload jsonb NOT NULL, known_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS derivatives_reference.source_snapshots (
  kind text NOT NULL CHECK (kind IN ('MASTER_NSE','MASTER_BSE','NSE_BAN')),
  trading_date date NOT NULL, source_hash text NOT NULL CHECK (source_hash ~ '^[a-f0-9]{64}$'),
  payload jsonb NOT NULL, raw bytea NOT NULL, received_at timestamptz NOT NULL,
  PRIMARY KEY(kind,trading_date,source_hash)
);
CREATE INDEX IF NOT EXISTS derivative_sources_latest ON derivatives_reference.source_snapshots
  (kind,trading_date,received_at DESC);
CREATE TABLE IF NOT EXISTS derivatives_reference.source_health (
  kind text NOT NULL CHECK(kind IN ('MASTER_NSE','MASTER_BSE','NSE_BAN')),
  trading_date date NOT NULL, status text NOT NULL CHECK(status IN ('UNKNOWN','READY')),
  updated_at timestamptz NOT NULL, source_hash text,
  CHECK ((status='READY') = (source_hash IS NOT NULL)),
  FOREIGN KEY(kind,trading_date,source_hash) REFERENCES derivatives_reference.source_snapshots(kind,trading_date,source_hash),
  PRIMARY KEY(kind,trading_date)
);
CREATE TABLE IF NOT EXISTS derivatives_reference.exchange_rules (
  version text PRIMARY KEY CHECK (version ~ '^[a-f0-9]{64}$'),
  instrument_key text NOT NULL, known_at timestamptz NOT NULL, payload jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS derivative_rules_latest ON derivatives_reference.exchange_rules
  (instrument_key,known_at DESC);
CREATE TABLE IF NOT EXISTS derivatives_reference.decision_snapshots (
  snapshot_id text PRIMARY KEY CHECK (snapshot_id ~ '^[a-f0-9]{64}$'),
  contract_version text NOT NULL REFERENCES derivatives_reference.contract_versions(version),
  rule_version text NOT NULL REFERENCES derivatives_reference.exchange_rules(version),
  recorded_at timestamptz NOT NULL, payload jsonb NOT NULL
);
REVOKE ALL ON SCHEMA derivatives_reference FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA derivatives_reference FROM PUBLIC;
GRANT USAGE ON SCHEMA derivatives_reference TO quant_derivative_ingestor, quant_app_runtime;
GRANT SELECT ON ALL TABLES IN SCHEMA derivatives_reference TO quant_app_runtime;
GRANT INSERT ON derivatives_reference.decision_snapshots TO quant_app_runtime;
GRANT SELECT,INSERT ON derivatives_reference.contract_versions,
  derivatives_reference.source_snapshots, derivatives_reference.source_health TO quant_derivative_ingestor;
GRANT UPDATE(status,updated_at,source_hash) ON derivatives_reference.source_health TO quant_derivative_ingestor;
DO $$ DECLARE t text; r text; BEGIN
  FOREACH r IN ARRAY ARRAY['anon','authenticated','equity_research_collector'] LOOP
    IF EXISTS(SELECT FROM pg_roles WHERE rolname=r) THEN
      EXECUTE format('REVOKE ALL ON SCHEMA derivatives_reference FROM %I',r);
      EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA derivatives_reference FROM %I',r);
    END IF;
  END LOOP;
  FOREACH t IN ARRAY ARRAY['contract_versions','source_snapshots','source_health','exchange_rules','decision_snapshots'] LOOP
    EXECUTE format('ALTER TABLE derivatives_reference.%I ENABLE ROW LEVEL SECURITY',t);
    IF NOT EXISTS(SELECT FROM pg_policies WHERE schemaname='derivatives_reference'
                  AND tablename=t AND policyname='runtime_read') THEN
      EXECUTE format('CREATE POLICY runtime_read ON derivatives_reference.%I FOR SELECT TO quant_app_runtime USING(true)',t);
    END IF;
    IF t IN ('contract_versions','source_snapshots','source_health') AND NOT EXISTS(
        SELECT FROM pg_policies WHERE schemaname='derivatives_reference' AND tablename=t AND policyname='ingest_insert') THEN
      EXECUTE format('CREATE POLICY ingest_insert ON derivatives_reference.%I FOR INSERT TO quant_derivative_ingestor WITH CHECK(true)',t);
      EXECUTE format('CREATE POLICY ingest_read ON derivatives_reference.%I FOR SELECT TO quant_derivative_ingestor USING(true)',t);
    END IF;
  END LOOP;
  IF NOT EXISTS(SELECT FROM pg_policies WHERE schemaname='derivatives_reference'
                AND tablename='source_health' AND policyname='ingest_health_update') THEN
    CREATE POLICY ingest_health_update ON derivatives_reference.source_health
      FOR UPDATE TO quant_derivative_ingestor USING(true) WITH CHECK(true);
  END IF;
  IF NOT EXISTS(SELECT FROM pg_policies WHERE schemaname='derivatives_reference'
                AND tablename='decision_snapshots' AND policyname='runtime_insert') THEN
    CREATE POLICY runtime_insert ON derivatives_reference.decision_snapshots
      FOR INSERT TO quant_app_runtime WITH CHECK(true);
  END IF;
END $$;
COMMIT;
-- No retention/delete grants: reviewed archive integration is required before
-- pruning decision lineage. Ingest only the configured small underlying universe.
