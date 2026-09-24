-- REVIEW DRAFT: execute manually in Supabase before deploying the Python files.
-- No migration of legacy SQLite positions: missing trade details stay missing.
BEGIN;
CREATE TABLE equity_operations.positions (
    position_id uuid PRIMARY KEY,
    owner_id text NOT NULL CHECK (owner_id ~ '^[0-9a-f]{64}$'),
    ticker text NOT NULL CHECK (ticker ~ '^[A-Z0-9&.\-]{1,32}$'),
    sector text NOT NULL CHECK (length(sector) BETWEEN 1 AND 100),
    entry_price numeric(18,4) NOT NULL CHECK (entry_price > 0 AND entry_price < 100000000000000),
    stop_price numeric(18,4) NOT NULL CHECK (stop_price > 0 AND stop_price < entry_price),
    target_price numeric(18,4) NOT NULL CHECK (target_price > entry_price AND target_price < 100000000000000),
    quantity integer NOT NULL CHECK (quantity > 0),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    closed_at timestamptz,
    exit_price numeric(18,4) CHECK (exit_price > 0 AND exit_price < 100000000000000),
    CHECK (closed_at IS NULL OR closed_at >= recorded_at),
    CHECK (closed_at IS NOT NULL OR exit_price IS NULL)
);
-- Also supports the small open-positions read. No payload or historical price index.
CREATE UNIQUE INDEX positions_one_open_ticker
    ON equity_operations.positions(owner_id,ticker) WHERE closed_at IS NULL;
ALTER TABLE equity_operations.positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE equity_operations.positions FORCE ROW LEVEL SECURITY;
REVOKE ALL ON equity_operations.positions FROM PUBLIC,anon,authenticated,service_role,equity_research_collector,quant_app_runtime;
GRANT SELECT,INSERT ON equity_operations.positions TO quant_app_runtime;
GRANT UPDATE (closed_at,exit_price) ON equity_operations.positions TO quant_app_runtime;
CREATE POLICY positions_owner_read ON equity_operations.positions FOR SELECT TO quant_app_runtime
    USING (owner_id = current_setting('app.position_owner',true));
CREATE POLICY positions_owner_insert ON equity_operations.positions FOR INSERT TO quant_app_runtime
    WITH CHECK (owner_id = current_setting('app.position_owner',true) AND closed_at IS NULL AND exit_price IS NULL);
CREATE POLICY positions_owner_close ON equity_operations.positions FOR UPDATE TO quant_app_runtime
    USING (owner_id = current_setting('app.position_owner',true) AND closed_at IS NULL)
    WITH CHECK (owner_id = current_setting('app.position_owner',true) AND closed_at IS NOT NULL);
COMMIT;
-- No DELETE/TRUNCATE grants, no production evidence writes, no research-role access.
-- Run once. Re-running intentionally fails rather than accepting a different schema.
