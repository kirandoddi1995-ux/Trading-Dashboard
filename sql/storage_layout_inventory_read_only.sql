-- Owner SELECT-only inventory. Run each block separately. No payload/credentials.
-- No migration/extension/maintenance/deletion authority. Dashboard disk is separate.
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT clock_timestamp() AS measured_at,
       (SELECT sum(pg_database_size(oid)) FROM pg_database) AS cluster_bytes,
       500000000-(SELECT sum(pg_database_size(oid)) FROM pg_database) AS nominal_headroom,
       476000000-(SELECT sum(pg_database_size(oid)) FROM pg_database) AS transition_allowance;
ROLLBACK;

BEGIN READ ONLY;
SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
SELECT n.nspname,c.relname,c.relkind,c.relpersistence,c.relrowsecurity,c.relforcerowsecurity,
       pg_total_relation_size(c.oid) AS allocated_bytes,
       pg_relation_size(c.oid) AS heap_bytes,pg_indexes_size(c.oid) AS index_bytes,
       CASE WHEN c.reltoastrelid=0 THEN 0 ELSE pg_total_relation_size(c.reltoastrelid) END AS toast_bytes,
       s.n_live_tup,s.n_dead_tup,
       pg_get_partkeydef(c.oid) AS existing_partition_key
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
LEFT JOIN pg_stat_user_tables s ON s.relid=c.oid
WHERE n.nspname IN ('quant_app','equity_research','equity_operations')
  AND c.relkind IN ('r','p')
ORDER BY allocated_bytes DESC;
ROLLBACK;

BEGIN READ ONLY;
SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
-- Global unique/PK/FK constraints must survive any new partition routing.
SELECT n.nspname,c.relname,k.conname,k.contype,k.convalidated,
       pg_get_constraintdef(k.oid) AS definition,
       CASE WHEN k.confrelid=0 THEN NULL ELSE k.confrelid::regclass::text END AS referenced_table
FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname IN ('quant_app','equity_research','equity_operations')
  AND k.contype IN ('p','u','f','c')
ORDER BY n.nspname,c.relname,k.conname;
ROLLBACK;

BEGIN READ ONLY;
SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
-- Inbound dependencies include schemas outside this application's inventory.
SELECT k.conrelid::regclass::text AS dependent_table,k.confrelid::regclass::text AS source_table,
       k.conname,pg_get_constraintdef(k.oid) AS definition
FROM pg_constraint k
WHERE k.contype='f' AND k.confrelid IN (
    SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname IN ('quant_app','equity_research','equity_operations'))
ORDER BY source_table,dependent_table,k.conname;
ROLLBACK;
