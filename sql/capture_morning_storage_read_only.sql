-- SELECT-only diagnostic blocks. Run separately. Never returns business payloads.
-- Connector currently uses owner/BYPASSRLS: the transaction is read-only, not the login.
-- Maintenance blocker check: no query texts, usernames or connection details returned.
BEGIN READ ONLY;
SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT (SELECT count(*) FROM pg_stat_activity WHERE pid<>pg_backend_pid()
        AND xact_start<now()-interval '5 minutes') AS transactions_older_than_5min,
       (SELECT count(*) FROM pg_replication_slots
        WHERE xmin IS NOT NULL OR catalog_xmin IS NOT NULL) AS slots_retaining_snapshots,
       (SELECT count(*) FROM pg_prepared_xacts) AS prepared_transactions,
       (SELECT count(*) FROM pg_stat_progress_vacuum) AS vacuums_running;
ROLLBACK;

BEGIN READ ONLY;
SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT now() AS measured_at, pg_database_size(current_database()) AS current_database_bytes,
       (SELECT sum(pg_database_size(oid)) FROM pg_database) AS cluster_bytes;
ROLLBACK;

BEGIN READ ONLY;
SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT schemaname,relname,n_live_tup,n_dead_tup,last_autovacuum,last_vacuum,
       pg_total_relation_size(relid) AS allocated_bytes
FROM pg_stat_user_tables
WHERE (schemaname,relname) IN (('equity_research','outcomes'),('quant_app','mf_nav'),
                             ('quant_app','evidence_ledger_events'));
ROLLBACK;

BEGIN READ ONLY;
SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT n.nspname AS parent_schema,c.relname AS parent_table,
       pg_relation_size(c.oid) AS heap_bytes,pg_indexes_size(c.oid) AS parent_index_bytes,
       pg_total_relation_size(c.reltoastrelid) AS toast_total_bytes,
       t.n_live_tup AS toast_live_chunks,t.n_dead_tup AS toast_dead_chunks,
       t.last_autovacuum AS toast_last_autovacuum,t.last_vacuum AS toast_last_vacuum,
       c.reloptions AS parent_settings,tc.reloptions AS toast_settings
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
JOIN pg_class tc ON tc.oid=c.reltoastrelid
LEFT JOIN pg_stat_all_tables t ON t.relid=tc.oid
WHERE n.nspname='equity_research' AND c.relname='outcomes';
ROLLBACK;

-- Save two timestamped results to attribute future allocation/counter deltas.
-- Counters are cumulative since stats_reset, not today's write counts.
BEGIN READ ONLY;
SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT schemaname,relname,pg_total_relation_size(relid) AS allocated_bytes,
       n_tup_ins,n_tup_upd,n_tup_del,stats_reset
FROM pg_stat_user_tables CROSS JOIN
     (SELECT stats_reset FROM pg_stat_database WHERE datname=current_database()) d
WHERE schemaname IN ('quant_app','equity_operations','equity_research')
ORDER BY pg_total_relation_size(relid) DESC LIMIT 15;
ROLLBACK;
