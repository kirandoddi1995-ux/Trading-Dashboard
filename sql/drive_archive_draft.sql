-- REVIEW ONLY. Run manually as database owner BEFORE deploying the new reader.
-- No source rows are deleted by this migration. No credentials are embedded.
-- Rerunnable; backfill preserves existing compact maxima after raw archival.
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='quant_archive_worker') THEN
        CREATE ROLE quant_archive_worker LOGIN NOINHERIT NOSUPERUSER NOCREATEDB
            NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 2;
    END IF;
END $$;
-- Set this role's password privately, separately. Never use the postgres URL in CI.
GRANT CONNECT, TEMPORARY ON DATABASE postgres TO quant_archive_worker;
GRANT USAGE ON SCHEMA quant_app TO quant_archive_worker;

CREATE TABLE IF NOT EXISTS quant_app.market_daily_volumes (
    instrument_key TEXT NOT NULL,
    trade_date DATE NOT NULL,
    max_captured_volume NUMERIC NOT NULL,
    PRIMARY KEY (instrument_key, trade_date)
);
COMMENT ON TABLE quant_app.market_daily_volumes IS
    'Maximum observed cumulative volume, NOT guaranteed exchange-final volume. Preserve beyond 30 days.';
CREATE TABLE IF NOT EXISTS quant_app.archive_manifests (
    batch_id TEXT PRIMARY KEY CHECK (batch_id ~ '^[a-f0-9]{64}$'),
    source_table TEXT NOT NULL CHECK (source_table IN ('mf_nav','market_quotes')),
    row_count INTEGER NOT NULL CHECK (row_count > 0),
    file_sha256 TEXT NOT NULL CHECK (file_sha256 ~ '^[a-f0-9]{64}$'),
    drive_file_id TEXT NOT NULL,
    drive_manifest_id TEXT NOT NULL,
    verified_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    completed_at TIMESTAMPTZ,
    deleted_count INTEGER CHECK (deleted_count >= 0 AND deleted_count <= row_count)
);

REVOKE ALL ON quant_app.market_daily_volumes, quant_app.archive_manifests FROM PUBLIC;
DO $$ DECLARE r TEXT; BEGIN
    FOREACH r IN ARRAY ARRAY['anon','authenticated','service_role','equity_research_collector'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=r) THEN
            EXECUTE format('REVOKE ALL ON quant_app.market_daily_volumes, quant_app.archive_manifests FROM %I',r);
        END IF;
    END LOOP;
END $$;
ALTER TABLE quant_app.market_daily_volumes ENABLE ROW LEVEL SECURITY;
ALTER TABLE quant_app.archive_manifests ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE ON quant_app.market_daily_volumes TO quant_app_runtime;
GRANT SELECT ON quant_app.market_daily_volumes TO quant_archive_worker;
GRANT SELECT, INSERT, UPDATE ON quant_app.archive_manifests TO quant_archive_worker;
DROP POLICY IF EXISTS daily_volume_runtime ON quant_app.market_daily_volumes;
CREATE POLICY daily_volume_runtime ON quant_app.market_daily_volumes TO quant_app_runtime
    USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS daily_volume_archive_read ON quant_app.market_daily_volumes;
CREATE POLICY daily_volume_archive_read ON quant_app.market_daily_volumes FOR SELECT
    TO quant_archive_worker USING (true);
DROP POLICY IF EXISTS archive_manifest_worker ON quant_app.archive_manifests;
CREATE POLICY archive_manifest_worker ON quant_app.archive_manifests TO quant_archive_worker
    USING (true) WITH CHECK (true);

-- Explicit two-table scope. No grants on ledger, scanner, universe, research,
-- positions, execution records, or model tables.
GRANT SELECT, DELETE ON quant_app.mf_nav, quant_app.market_quotes TO quant_archive_worker;
DROP POLICY IF EXISTS archive_nav_select ON quant_app.mf_nav;
CREATE POLICY archive_nav_select ON quant_app.mf_nav FOR SELECT TO quant_archive_worker USING (true);
DROP POLICY IF EXISTS archive_nav_delete ON quant_app.mf_nav;
CREATE POLICY archive_nav_delete ON quant_app.mf_nav FOR DELETE TO quant_archive_worker USING (true);
DROP POLICY IF EXISTS archive_quote_select ON quant_app.market_quotes;
CREATE POLICY archive_quote_select ON quant_app.market_quotes FOR SELECT TO quant_archive_worker USING (true);
DROP POLICY IF EXISTS archive_quote_delete ON quant_app.market_quotes;
CREATE POLICY archive_quote_delete ON quant_app.market_quotes FOR DELETE TO quant_archive_worker USING (true);

-- No SECURITY DEFINER: the inserting runtime must have the explicit grants above.
-- Serialize writers while installing trigger and backfilling, so no observation
-- can land in the gap between the initial aggregate and trigger installation.
LOCK TABLE quant_app.market_quotes IN SHARE ROW EXCLUSIVE MODE;
CREATE OR REPLACE FUNCTION quant_app.capture_daily_volume()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER
SET search_path = pg_catalog, quant_app AS $$
BEGIN
    IF NEW.volume IS NOT NULL THEN
        INSERT INTO quant_app.market_daily_volumes(instrument_key,trade_date,max_captured_volume)
        VALUES (NEW.instrument_key,NEW.trade_date,NEW.volume)
        ON CONFLICT (instrument_key,trade_date) DO UPDATE
        SET max_captured_volume=GREATEST(quant_app.market_daily_volumes.max_captured_volume,
                                        EXCLUDED.max_captured_volume);
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION quant_app.capture_daily_volume() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION quant_app.capture_daily_volume() TO quant_app_runtime;
DROP TRIGGER IF EXISTS quote_daily_volume_insert ON quant_app.market_quotes;
CREATE TRIGGER quote_daily_volume_insert AFTER INSERT ON quant_app.market_quotes
    FOR EACH ROW EXECUTE FUNCTION quant_app.capture_daily_volume();

INSERT INTO quant_app.market_daily_volumes(instrument_key,trade_date,max_captured_volume)
SELECT instrument_key,trade_date,MAX(volume) FROM quant_app.market_quotes
WHERE volume IS NOT NULL GROUP BY instrument_key,trade_date
ON CONFLICT (instrument_key,trade_date) DO UPDATE
SET max_captured_volume=GREATEST(quant_app.market_daily_volumes.max_captured_volume,
                                EXCLUDED.max_captured_volume);
COMMIT;

-- Rollback is NOT automatic: disable maintenance and restore the previous
-- Python reader first. Once raw rows have been archived/deleted, restore them
-- from VERIFIED archives before returning to a raw-only reader. Do not drop
-- the daily table or manifests as a shortcut; they are then required history.
