-- Owner-run catalog metadata ONLY. No business rows, role passwords, function
-- bodies, connection strings, backup download or restore. Not a migration.
-- If any statement fails, stop; use ROLLBACK, not a retry or a permission change.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '10s';
SET LOCAL lock_timeout = '2s';

SELECT clock_timestamp() AS measured_at,
       current_setting('server_version_num') AS server_version_num,
       current_setting('transaction_read_only') AS transaction_read_only,
       pg_database_size(current_database()) AS current_database_bytes,
       false AS backup_existence_established,
       false AS physical_disk_free_established;

-- Never request privileges or return an incomplete sum as the cluster size.
-- CASE keeps all database-size calls out of the inaccessible/overflow branch.
WITH visibility AS (
  SELECT count(*) AS databases,
         bool_and(has_database_privilege(oid, 'CONNECT') OR
                  pg_has_role('pg_read_all_stats', 'USAGE')) AS all_visible
  FROM pg_database
)
SELECT clock_timestamp() AS measured_at, databases,
       CASE WHEN databases <= 64 AND all_visible THEN 'COMPLETE'
            ELSE 'UNKNOWN_PERMISSION_OR_BOUND' END AS cluster_status,
       CASE WHEN databases <= 64 AND all_visible
            THEN (SELECT sum(pg_database_size(oid)) FROM pg_database)
            ELSE NULL END AS cluster_database_bytes
FROM visibility;

-- Exactly eight named relations: six archived tables plus ledger/daily volume.
-- Missing relations remain explicit rows; no application table is queried.
WITH targets(schema_name, relation_name) AS (VALUES
  ('quant_app', 'mf_nav'), ('quant_app', 'market_quotes'),
  ('quant_app', 'universe_membership'), ('quant_app', 'universe_membership_versions'),
  ('quant_app', 'scanner_observations'), ('equity_research', 'outcomes'),
  ('quant_app', 'evidence_ledger_events'), ('quant_app', 'market_daily_volumes')
)
SELECT t.schema_name, t.relation_name, c.oid IS NOT NULL AS relation_present,
       c.relkind, c.reltuples::bigint AS estimated_rows,
       pg_total_relation_size(c.oid) AS total_bytes,
       pg_relation_size(c.oid) AS heap_bytes,
       pg_indexes_size(c.oid) AS indexes_bytes,
       c.relrowsecurity, c.relforcerowsecurity
FROM targets t LEFT JOIN pg_namespace n ON n.nspname = t.schema_name
LEFT JOIN pg_class c ON c.relnamespace = n.oid AND c.relname = t.relation_name
  AND c.relkind IN ('r', 'p')
ORDER BY t.schema_name, t.relation_name;

-- Actual primary-key column identities; do not assume source SPECS are DDL.
WITH targets(schema_name, relation_name) AS (VALUES
  ('quant_app', 'mf_nav'), ('quant_app', 'market_quotes'),
  ('quant_app', 'universe_membership'), ('quant_app', 'universe_membership_versions'),
  ('quant_app', 'scanner_observations'), ('equity_research', 'outcomes'),
  ('quant_app', 'evidence_ledger_events'), ('quant_app', 'market_daily_volumes')
)
SELECT t.schema_name, t.relation_name,
       array_agg(a.attname ORDER BY k.ord) AS primary_key_columns
FROM targets t LEFT JOIN pg_namespace n ON n.nspname = t.schema_name
LEFT JOIN pg_class c ON c.relnamespace = n.oid AND c.relname = t.relation_name
LEFT JOIN pg_index i ON i.indrelid = c.oid AND i.indisprimary
LEFT JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord)
  ON k.ord <= i.indnkeyatts
LEFT JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.attnum
GROUP BY t.schema_name, t.relation_name ORDER BY t.schema_name, t.relation_name;

-- Extension output max128 records / max128 bytes per version, no silent truncation.
WITH totals AS (
  SELECT count(*) AS entries, bool_and(octet_length(extversion) <= 128) AS versions_bounded
  FROM pg_extension
), listed AS (
  SELECT extname, left(extversion, 128) AS extversion
  FROM pg_extension ORDER BY extname LIMIT 128
)
SELECT entries, entries <= 128 AND coalesce(versions_bounded, true) AS complete,
       CASE WHEN entries <= 128 AND coalesce(versions_bounded, true)
            THEN (SELECT jsonb_agg(listed ORDER BY extname) FROM listed)
            ELSE NULL END AS extensions
FROM totals;
ROLLBACK;
