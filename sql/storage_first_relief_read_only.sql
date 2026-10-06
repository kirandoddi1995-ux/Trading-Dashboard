-- Run each block separately; no writes or payload/credential output.
-- Connector owner/BYPASSRLS is not a restricted read-only login.
BEGIN READ ONLY;
SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT clock_timestamp() AS observed_at,pg_database_size(current_database()) AS current_database_bytes,
       (SELECT sum(pg_database_size(datname)) FROM pg_database) AS cluster_bytes,
       pg_total_relation_size('quant_app.mf_nav') AS nav_allocated_bytes;
ROLLBACK;

-- Agent's overnight/new-session metadata check, no business payloads.
BEGIN READ ONLY;
SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT date_trunc('hour',recorded_at) AS hour_utc,count(*) AS events,
       sum(pg_column_size(payload)) AS stored_payload_bytes
FROM quant_app.evidence_ledger_events
WHERE recorded_at>=TIMESTAMPTZ '2026-10-05 18:05:00+00'
GROUP BY 1 ORDER BY 1;
ROLLBACK;

BEGIN READ ONLY;
SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT t.tgname,t.tgenabled,p.proname,pg_get_functiondef(p.oid) AS guard_definition
FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid
WHERE t.tgrelid='quant_app.mf_nav'::regclass AND NOT t.tgisinternal;
ROLLBACK;

BEGIN READ ONLY;
SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT schemaname,relname,pg_total_relation_size(relid) AS total_bytes,
       n_live_tup,n_dead_tup,n_tup_ins,n_tup_upd,n_tup_del,last_autovacuum
FROM pg_stat_user_tables
WHERE schemaname IN ('quant_app','equity_operations','equity_research')
ORDER BY pg_total_relation_size(relid) DESC LIMIT 15;
ROLLBACK;

-- Latest-value fingerprint: preserve before/after every deletion run.
BEGIN READ ONLY;
SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
WITH latest AS (
 SELECT DISTINCT ON(scheme_code) scheme_code,nav_date,to_jsonb(s)::text AS original
 FROM quant_app.mf_nav s ORDER BY scheme_code,nav_date DESC
)
SELECT count(*) AS latest_schemes,md5(string_agg(original,E'\n' ORDER BY scheme_code)) AS latest_fingerprint
FROM latest;
ROLLBACK;

-- Agent follow-up interval:09:01:53IST size unchanged; zero new ledger rows.
BEGIN READ ONLY;
SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT count(*) AS events,coalesce(sum(pg_column_size(payload)),0) AS stored_payload_bytes
FROM quant_app.evidence_ledger_events
WHERE recorded_at>=TIMESTAMPTZ '2026-10-06 03:21:16.394344+00';
ROLLBACK;

-- Explicit one-time date, not a proposed automatic retention change.
BEGIN READ ONLY;
SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT count(*) AS eligible_rows,coalesce(sum(pg_column_size(s)),0) AS eligible_row_bytes
FROM quant_app.mf_nav s WHERE nav_date<DATE '2026-10-04'
AND EXISTS(SELECT 1 FROM quant_app.mf_nav newer
 WHERE newer.scheme_code=s.scheme_code AND newer.nav_date>s.nav_date);
ROLLBACK;
