BEGIN READ ONLY; SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s'; SELECT jsonb_build_object('checked_at',now(),'cluster_bytes',(SELECT sum(pg_database_size(datname)) FROM pg_database),'tables',(SELECT jsonb_agg(x) FROM(SELECT n.nspname||'.'||c.relname AS name,pg_total_relation_size(c.oid) AS allocated_bytes,c.reltuples::bigint AS estimated_rows FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN('r','p') AND n.nspname IN('quant_app','equity_research','equity_operations','derivatives_reference','derivatives_monitor') ORDER BY 1)x),'ledger_formats',(SELECT jsonb_agg(x) FROM(SELECT schema_version,hash_algorithm,count(*) AS rows FROM quant_app.evidence_ledger_events GROUP BY 1,2)x)); ROLLBACK;

-- Separate key-presence check: no key IDs, keys or payloads returned.
BEGIN READ ONLY; SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT schema_version,key_id IS NULL AS key_id_missing,count(*) AS events
FROM quant_app.evidence_ledger_events GROUP BY 1,2 ORDER BY 1,2;
ROLLBACK;

-- Rechecked 2026-10-05 21:37:01.610116 UTC, postgres owner/BYPASSRLS connector.
-- cluster493984565/current478710931 unchanged over this interval; NOT steady state.
BEGIN READ ONLY; SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT now() AS checked_at,current_user AS connector_role,
       (SELECT sum(pg_database_size(datname)) FROM pg_database) AS cluster_bytes,
       pg_database_size(current_database()) AS current_database_bytes;
ROLLBACK;

-- Rechecked 2026-10-05 20:54:22.070763 UTC; postgres connector (owner/BYPASSRLS).
-- cluster493984565/current478710931: unchanged, not steady-state proof.
BEGIN READ ONLY; SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT now() AS checked_at,current_user AS connector_role,
       (SELECT sum(pg_database_size(datname)) FROM pg_database) AS cluster_bytes,
       pg_database_size(current_database()) AS current_database_bytes;
ROLLBACK;

-- Metadata only, checked during milestone6; no aggregate IDs or payloads returned.
-- 9782 events / 4913 aggregates; longest feature-quality chain2474.
BEGIN READ ONLY; SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT split_part(aggregate_id,':',1) AS aggregate_namespace,count(*) AS events,
       count(DISTINCT aggregate_id) AS aggregates,max(sequence_no) AS longest_sequence
FROM quant_app.evidence_ledger_events GROUP BY 1 ORDER BY 1;
ROLLBACK;

-- Rechecked 2026-10-05 20:20:10.59088 UTC through postgres connector.
-- Returned cluster493984565/current478710931, unchanged from19:40 UTC.
-- READ ONLY does not turn this owner/BYPASSRLS login into a restricted login.
BEGIN READ ONLY; SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT now() AS checked_at,current_user AS connector_role,
       (SELECT sum(pg_database_size(datname)) FROM pg_database) AS cluster_bytes,
       pg_database_size(current_database()) AS current_database_bytes;
ROLLBACK;

-- Rechecked 2026-10-05 19:40:04 UTC. Sizes only; no business payloads.
BEGIN READ ONLY; SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT now() AS checked_at,current_user AS connector_role,
       (SELECT sum(pg_database_size(datname)) FROM pg_database) AS cluster_bytes,
       pg_database_size(current_database()) AS current_database_bytes;
ROLLBACK;

-- Rechecked 2026-10-05 19:41:18 UTC. Statistics are estimates/cumulative counters,
-- NOT precise live row counts, today's growth, or proof of removable bloat.
BEGIN READ ONLY; SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT now() AS checked_at,n.nspname||'.'||c.relname AS relation,
       pg_total_relation_size(c.oid) AS total_bytes,
       pg_relation_size(c.oid) AS heap_bytes,pg_indexes_size(c.oid) AS index_bytes,
       CASE WHEN c.reltoastrelid=0 THEN 0
            ELSE pg_total_relation_size(c.reltoastrelid) END AS toast_bytes,
       s.n_live_tup,s.n_dead_tup,s.n_tup_ins,s.n_tup_upd,s.n_tup_del,
       s.last_autovacuum,s.last_vacuum,
       (SELECT stats_reset FROM pg_stat_database WHERE datname=current_database())
           AS database_stats_reset
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
LEFT JOIN pg_stat_user_tables s ON s.relid=c.oid
WHERE c.relkind='r' AND n.nspname IN('quant_app','equity_research','equity_operations')
ORDER BY pg_total_relation_size(c.oid) DESC LIMIT 10;
ROLLBACK;
