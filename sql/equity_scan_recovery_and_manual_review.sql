-- REVIEW DRAFT ONLY. Do not execute until separately approved.
-- Operational equity recovery/review data is isolated from equity_research.
BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (
      SELECT 1 FROM pg_roles WHERE rolname='quant_app_runtime'
        AND NOT rolsuper AND NOT rolbypassrls AND NOT rolcreaterole
        AND NOT rolcreatedb AND NOT rolreplication) THEN
    RAISE EXCEPTION 'Restricted quant_app_runtime role is required';
  END IF;
  IF NOT EXISTS (
      SELECT 1 FROM pg_roles WHERE rolname='equity_research_collector'
        AND NOT rolsuper AND NOT rolbypassrls AND NOT rolcreaterole
        AND NOT rolcreatedb AND NOT rolreplication) THEN
    RAISE EXCEPTION 'Restricted equity_research_collector role is required';
  END IF;
  IF EXISTS (
      SELECT 1 FROM pg_auth_members m
      JOIN pg_roles role_granted ON role_granted.oid=m.roleid
      JOIN pg_roles member_role ON member_role.oid=m.member
      WHERE member_role.rolname='equity_research_collector'
        AND role_granted.rolname='quant_app_runtime') THEN
    RAISE EXCEPTION 'Research collector must not inherit runtime privileges';
  END IF;
END $$;

CREATE SCHEMA equity_operations;
REVOKE ALL ON SCHEMA equity_operations FROM PUBLIC;
REVOKE ALL ON SCHEMA equity_operations FROM anon, authenticated, service_role,
  equity_research_collector;
GRANT USAGE ON SCHEMA equity_operations TO quant_app_runtime;

ALTER DEFAULT PRIVILEGES IN SCHEMA equity_operations REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA equity_operations REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA equity_operations REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

CREATE TABLE equity_operations.scan_runs (
    run_id text PRIMARY KEY,
    owner_id text NOT NULL,
    signature text NOT NULL,
    scan_mode text NOT NULL,
    horizon_sessions integer NOT NULL CHECK (horizon_sessions > 0),
    status text NOT NULL CHECK (status IN
      ('RUNNING','RECOVERING','INTERRUPTED','CANCELLED','COMPLETE')),
    fencing_token bigint NOT NULL CHECK (fencing_token > 0),
    started_at timestamptz NOT NULL,
    heartbeat_at timestamptz NOT NULL,
    finished_at timestamptz,
    error_kind text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK (jsonb_typeof(metadata)='object')
);
CREATE INDEX equity_scan_recoverable_idx
  ON equity_operations.scan_runs(owner_id,signature,started_at DESC)
  WHERE status IN ('RUNNING','RECOVERING','INTERRUPTED','CANCELLED');

CREATE TABLE equity_operations.scan_candidates (
    run_id text NOT NULL REFERENCES equity_operations.scan_runs(run_id),
    instrument text NOT NULL,
    item jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('PENDING','RUNNING','COMPLETE')),
    attempt_no integer NOT NULL DEFAULT 0 CHECK (attempt_no >= 0),
    result jsonb,
    rejection jsonb,
    quote_observed_at timestamptz,
    governance_decision_at timestamptz,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (run_id,instrument),
    CHECK (NOT (result IS NOT NULL AND rejection IS NOT NULL)),
    CHECK (status <> 'COMPLETE' OR result IS NOT NULL OR rejection IS NOT NULL)
);
CREATE INDEX equity_scan_unfinished_idx
  ON equity_operations.scan_candidates(run_id,instrument)
  WHERE status <> 'COMPLETE';

CREATE TABLE equity_operations.manual_quote_reviews (
    review_id uuid PRIMARY KEY,
    decision_id text NOT NULL,
    decision_digest text NOT NULL CHECK (length(decision_digest)=64),
    scan_run_id text,
    instrument text NOT NULL,
    reviewer text NOT NULL,
    attested_at timestamptz NOT NULL,
    secondary_platform text NOT NULL,
    secondary_price numeric NOT NULL CHECK (secondary_price > 0),
    source_quote_observed_at timestamptz,
    primary_price numeric NOT NULL CHECK (primary_price > 0),
    difference_bps numeric NOT NULL CHECK (difference_bps >= 0),
    status text NOT NULL CHECK (status IN ('CONFIRMED','MISMATCH')),
    payload jsonb NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (jsonb_typeof(payload)='object'),
    CHECK ((payload->>'purpose'='LIVE_EQUITY_MANUAL_QUOTE_CHECK') IS TRUE),
    CHECK ((payload->>'decision_id'=decision_id) IS TRUE),
    CHECK ((payload->>'decision_digest'=decision_digest) IS TRUE),
    CHECK ((payload->>'instrument'=instrument) IS TRUE),
    CHECK ((payload->>'status'=status) IS TRUE),
    CHECK ((payload->'system_allow_trade'='true'::jsonb) IS TRUE)
);
CREATE INDEX equity_manual_review_decision_idx
  ON equity_operations.manual_quote_reviews(decision_id,attested_at DESC);

REVOKE ALL ON ALL TABLES IN SCHEMA equity_operations FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA equity_operations
  FROM anon, authenticated, service_role, equity_research_collector;
GRANT SELECT, INSERT, UPDATE ON equity_operations.scan_runs,
  equity_operations.scan_candidates TO quant_app_runtime;
GRANT SELECT, INSERT ON equity_operations.manual_quote_reviews TO quant_app_runtime;

ALTER TABLE equity_operations.scan_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE equity_operations.scan_runs FORCE ROW LEVEL SECURITY;
ALTER TABLE equity_operations.scan_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE equity_operations.scan_candidates FORCE ROW LEVEL SECURITY;
ALTER TABLE equity_operations.manual_quote_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE equity_operations.manual_quote_reviews FORCE ROW LEVEL SECURITY;

CREATE POLICY runtime_scan_runs_read ON equity_operations.scan_runs
  FOR SELECT TO quant_app_runtime USING (true);
CREATE POLICY runtime_scan_runs_insert ON equity_operations.scan_runs
  FOR INSERT TO quant_app_runtime WITH CHECK (true);
CREATE POLICY runtime_scan_runs_update ON equity_operations.scan_runs
  FOR UPDATE TO quant_app_runtime USING (true) WITH CHECK (true);
CREATE POLICY runtime_scan_candidates_read ON equity_operations.scan_candidates
  FOR SELECT TO quant_app_runtime USING (true);
CREATE POLICY runtime_scan_candidates_insert ON equity_operations.scan_candidates
  FOR INSERT TO quant_app_runtime WITH CHECK (true);
CREATE POLICY runtime_scan_candidates_update ON equity_operations.scan_candidates
  FOR UPDATE TO quant_app_runtime USING (true) WITH CHECK (true);
CREATE POLICY runtime_manual_reviews_read ON equity_operations.manual_quote_reviews
  FOR SELECT TO quant_app_runtime USING (true);
CREATE POLICY runtime_manual_reviews_insert ON equity_operations.manual_quote_reviews
  FOR INSERT TO quant_app_runtime WITH CHECK (
    (payload->>'purpose'='LIVE_EQUITY_MANUAL_QUOTE_CHECK') IS TRUE
    AND (payload->'system_allow_trade'='true'::jsonb) IS TRUE
  );

-- Explicitly prove the research role received no operational access.
DO $$
BEGIN
  IF has_schema_privilege('equity_research_collector','equity_operations','USAGE')
     OR has_table_privilege('equity_research_collector',
                            'equity_operations.scan_runs','SELECT')
     OR has_table_privilege('equity_research_collector',
                            'equity_operations.scan_candidates','SELECT')
     OR has_table_privilege('equity_research_collector',
                            'equity_operations.manual_quote_reviews','SELECT') THEN
    RAISE EXCEPTION 'Research collector unexpectedly has operational access';
  END IF;
END $$;

COMMIT;
