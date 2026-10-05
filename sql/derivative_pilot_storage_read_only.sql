-- Owner SQL editor: read-only before installation, after each draft, and after pilot.
-- These are decimal bytes. The Dashboard quota usage must also be reviewed.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '10s';
SET LOCAL lock_timeout = '2s';
SELECT now() AS checked_at,
       (SELECT sum(pg_database_size(datname))::bigint FROM pg_database) AS cluster_bytes,
       pg_database_size(current_database()) AS current_database_bytes,
       500000000 - (SELECT sum(pg_database_size(datname))::bigint FROM pg_database) AS nominal_headroom_bytes,
       COALESCE((SELECT sum(pg_total_relation_size(c.oid))::bigint
         FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
         WHERE n.nspname IN ('derivatives_reference','derivatives_monitor')
         AND c.relkind IN ('r','m')),0) AS derivative_allocated_bytes;
SELECT n.nspname AS schema_name,c.relname AS table_name,
       pg_total_relation_size(c.oid) AS allocated_bytes,c.reltuples AS estimated_rows,
       c.relrowsecurity AS rls_enabled
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname IN ('derivatives_reference','derivatives_monitor') AND c.relkind='r'
ORDER BY n.nspname,c.relname;
ROLLBACK;
