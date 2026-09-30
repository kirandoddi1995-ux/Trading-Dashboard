-- REVIEW ONLY. Run manually AFTER derivative_foundations_review_only.sql.
-- No existing data/columns changed. Adds monitor SELECT policies to the two
-- existing reference tables below. No startup migration or research grants.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
DO $$ BEGIN
 IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='quant_app_runtime')
    OR to_regclass('derivatives_reference.contract_versions') IS NULL
    OR to_regclass('derivatives_reference.exchange_rules') IS NULL
    OR to_regclass('derivatives_reference.source_snapshots') IS NULL
    OR to_regclass('derivatives_reference.source_health') IS NULL
    OR to_regclass('derivatives_reference.decision_snapshots') IS NULL THEN
  RAISE EXCEPTION 'Derivative foundations prerequisite missing. Stop; review/apply foundations before monitoring.';
 END IF;
 IF EXISTS (SELECT FROM pg_roles WHERE rolname IN
     ('quant_app_runtime','quant_derivative_monitor','quant_derivative_watchdog')
     AND (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication)) THEN
  RAISE EXCEPTION 'Unsafe existing monitor/application role attributes. Stop for role review; no role was changed.';
 END IF;
END $$;
CREATE SCHEMA IF NOT EXISTS derivatives_monitor;
DO $$ BEGIN
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='quant_derivative_monitor') THEN
  CREATE ROLE quant_derivative_monitor LOGIN NOINHERIT NOSUPERUSER NOCREATEDB
    NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 3;
 END IF;
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='quant_derivative_watchdog') THEN
  CREATE ROLE quant_derivative_watchdog LOGIN NOINHERIT NOSUPERUSER NOCREATEDB
    NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 2;
 END IF;
END $$;
CREATE TABLE IF NOT EXISTS derivatives_monitor.records (
 version text PRIMARY KEY CHECK(version ~ '^[a-f0-9]{64}$'),
 kind text NOT NULL CHECK(kind IN ('BROKER_POLICY','ADJUSTMENT_REVIEW','CONTRACT_ADJUSTMENT',
    'PRICING_EVENT','FINAL_PRICE','RECONCILIATION')),
 instrument_key text NOT NULL, known_at timestamptz NOT NULL, payload jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS derivative_record_lookup ON derivatives_monitor.records
 (kind,instrument_key,known_at DESC,version);
CREATE TABLE IF NOT EXISTS derivatives_monitor.state (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 account_key text NOT NULL CHECK(account_key ~ '^[a-f0-9]{64}$'),
 status text NOT NULL CHECK(status IN ('POLLING','READY','AUTH_REQUIRED','DATA_UNAVAILABLE','ATTENTION')),
 checked_at timestamptz NOT NULL, valid_until timestamptz NOT NULL,
 unresolved_critical boolean NOT NULL
);
CREATE TABLE IF NOT EXISTS derivatives_monitor.positions (
 position_key text PRIMARY KEY CHECK(position_key ~ '^[a-f0-9]{64}$'),
 account_key text NOT NULL, instrument_key text NOT NULL, product text NOT NULL,
 payload jsonb NOT NULL, updated_at timestamptz NOT NULL,
 UNIQUE(account_key,instrument_key,product)
);
CREATE TABLE IF NOT EXISTS derivatives_monitor.alerts (
 alert_id text PRIMARY KEY CHECK(alert_id ~ '^[a-f0-9]{64}$'),
 code text NOT NULL, active boolean NOT NULL DEFAULT true,
 first_seen timestamptz NOT NULL, last_seen timestamptz NOT NULL,
 acknowledged_at timestamptz,
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
 next_attempt timestamptz NOT NULL, delivered_at timestamptz,
 lease_token uuid, lease_until timestamptz,
 last_error text CHECK(last_error IS NULL OR last_error='EMAIL_DELIVERY_FAILED')
);
CREATE INDEX IF NOT EXISTS derivative_alert_due ON derivatives_monitor.alerts(next_attempt)
 WHERE active;
REVOKE ALL ON SCHEMA derivatives_monitor FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA derivatives_monitor FROM PUBLIC;
GRANT USAGE ON SCHEMA derivatives_monitor TO quant_app_runtime,quant_derivative_monitor;
GRANT USAGE ON SCHEMA derivatives_monitor TO quant_derivative_watchdog;
GRANT SELECT ON derivatives_monitor.state TO quant_derivative_watchdog;
GRANT SELECT ON derivatives_monitor.records,derivatives_monitor.state,
 derivatives_monitor.positions,derivatives_monitor.alerts TO quant_app_runtime,quant_derivative_monitor;
GRANT UPDATE(acknowledged_at) ON derivatives_monitor.alerts TO quant_app_runtime;
GRANT INSERT,UPDATE ON derivatives_monitor.state,derivatives_monitor.positions,derivatives_monitor.alerts
 TO quant_derivative_monitor;
GRANT USAGE ON SCHEMA derivatives_reference TO quant_derivative_monitor;
GRANT SELECT ON derivatives_reference.contract_versions,derivatives_reference.exchange_rules
 TO quant_derivative_monitor;
DO $$ DECLARE t text; r text; BEGIN
 FOREACH t IN ARRAY ARRAY['contract_versions','exchange_rules'] LOOP
  IF NOT EXISTS(SELECT FROM pg_policies WHERE schemaname='derivatives_reference' AND tablename=t AND policyname='monitor_read') THEN
   EXECUTE format('CREATE POLICY monitor_read ON derivatives_reference.%I FOR SELECT TO quant_derivative_monitor USING(true)',t);
  END IF;
 END LOOP;
 FOREACH t IN ARRAY ARRAY['records','state','positions','alerts'] LOOP
  EXECUTE format('ALTER TABLE derivatives_monitor.%I ENABLE ROW LEVEL SECURITY',t);
  IF NOT EXISTS(SELECT FROM pg_policies WHERE schemaname='derivatives_monitor' AND tablename=t AND policyname='operational_read') THEN
   EXECUTE format('CREATE POLICY operational_read ON derivatives_monitor.%I FOR SELECT TO quant_app_runtime,quant_derivative_monitor USING(true)',t);
  END IF;
  IF t <> 'records' AND NOT EXISTS(SELECT FROM pg_policies WHERE schemaname='derivatives_monitor' AND tablename=t AND policyname='monitor_write') THEN
   EXECUTE format('CREATE POLICY monitor_write ON derivatives_monitor.%I FOR ALL TO quant_derivative_monitor USING(true) WITH CHECK(true)',t);
  END IF;
 END LOOP;
 IF NOT EXISTS(SELECT FROM pg_policies WHERE schemaname='derivatives_monitor' AND tablename='alerts' AND policyname='runtime_ack') THEN
  CREATE POLICY runtime_ack ON derivatives_monitor.alerts FOR UPDATE TO quant_app_runtime USING(true) WITH CHECK(true);
 END IF;
 IF NOT EXISTS(SELECT FROM pg_policies WHERE schemaname='derivatives_monitor' AND tablename='state' AND policyname='watchdog_read') THEN
  CREATE POLICY watchdog_read ON derivatives_monitor.state FOR SELECT TO quant_derivative_watchdog USING(true);
 END IF;
 FOREACH r IN ARRAY ARRAY['anon','authenticated','equity_research_collector','quant_derivative_ingestor'] LOOP
  IF EXISTS(SELECT FROM pg_roles WHERE rolname=r) THEN
   EXECUTE format('REVOKE ALL ON SCHEMA derivatives_monitor FROM %I',r);
   EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA derivatives_monitor FROM %I',r);
  END IF;
 END LOOP;
END $$;
COMMIT;
-- Only the owner provisions immutable reviewed records (including imported broker
-- reconciliation evidence). Runtime, monitor and research roles cannot manufacture them.
-- No DELETE grants. Current state/positions/alerts are bounded upserts, not tick history.
