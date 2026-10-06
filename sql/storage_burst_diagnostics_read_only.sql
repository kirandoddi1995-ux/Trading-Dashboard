-- Each block separately. Owner connector/BYPASSRLS, not restricted read-only login.
-- No market prices, credentials, query texts or frozen-period results returned.
BEGIN READ ONLY;
SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT now() AS observed_at,pg_database_size(current_database()) AS database_bytes,
       (SELECT sum(pg_database_size(oid)) FROM pg_database) AS cluster_bytes;
ROLLBACK;

BEGIN READ ONLY;
SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT c.relname,pg_relation_size(c.oid) AS heap_bytes,pg_indexes_size(c.oid) AS indexes_bytes,
       CASE WHEN c.reltoastrelid=0 THEN 0 ELSE pg_total_relation_size(c.reltoastrelid) END AS toast_bytes,
       s.n_live_tup,s.n_dead_tup,s.n_tup_ins,s.n_tup_upd,s.last_autovacuum
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
JOIN pg_stat_user_tables s ON s.relid=c.oid
WHERE n.nspname='quant_app' AND c.relname IN ('evidence_ledger_events','market_daily_volumes');
ROLLBACK;

BEGIN READ ONLY;
SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT recorded_at,event_type,pg_column_size(payload) AS payload_stored_bytes,
       octet_length(payload::text) AS payload_json_bytes
FROM quant_app.evidence_ledger_events
WHERE recorded_at>=TIMESTAMPTZ '2026-10-06 03:50:00+00'
ORDER BY recorded_at DESC LIMIT 5;
ROLLBACK;

BEGIN READ ONLY;
SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT tgname,pg_get_functiondef(tgfoid) AS trigger_definition FROM pg_trigger
WHERE tgrelid='quant_app.market_quotes'::regclass AND NOT tgisinternal
AND pg_get_functiondef(tgfoid) LIKE '%market_daily_volumes%';
ROLLBACK;

BEGIN READ ONLY;
SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT count(*) AS daily_rows,
       md5(string_agg(to_jsonb(d)::text,E'\n' ORDER BY instrument_key,trade_date)) AS maxima_fingerprint
FROM quant_app.market_daily_volumes d;
ROLLBACK;

BEGIN READ ONLY;
SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT (SELECT count(*) FROM pg_stat_activity WHERE pid<>pg_backend_pid()
        AND xact_start<now()-interval '5 minutes') AS transactions_older_than_5min,
       (SELECT count(*) FROM pg_replication_slots
        WHERE xmin IS NOT NULL OR catalog_xmin IS NOT NULL) AS slots_retaining_snapshots,
       (SELECT count(*) FROM pg_prepared_xacts) AS prepared_transactions,
       (SELECT count(*) FROM pg_stat_progress_vacuum) AS vacuums_running;
ROLLBACK;
