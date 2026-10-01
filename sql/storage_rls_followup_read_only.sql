-- OWNER-RUN DIAGNOSTICS ONLY. Run one numbered block at a time.
-- No DELETE, VACUUM, DDL, credentials, raw payloads, account IDs or Drive IDs.
-- Estimated live/dead tuples are NOT an exact bloat measurement.

-- CHECK 1: allocated heap/TOAST/index space and vacuum activity.
SELECT n.nspname||'.'||c.relname AS relation,
 pg_relation_size(c.oid) AS main_heap_bytes,
 pg_table_size(c.oid) AS table_including_toast_bytes,
 pg_indexes_size(c.oid) AS main_indexes_bytes,
 pg_total_relation_size(c.oid) AS total_bytes,
 CASE WHEN c.reltoastrelid<>0 THEN pg_total_relation_size(c.reltoastrelid) ELSE 0 END AS toast_total_bytes,
 s.n_live_tup AS estimated_live_rows,s.n_dead_tup AS estimated_dead_rows,
 s.last_autovacuum,s.last_vacuum,s.last_analyze,s.last_autoanalyze,
 c.relrowsecurity AS rls_enabled,c.relforcerowsecurity AS rls_forced
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
LEFT JOIN pg_stat_all_tables s ON s.relid=c.oid
WHERE n.nspname IN ('quant_app','equity_operations','equity_research') AND c.relkind='r'
ORDER BY total_bytes DESC;

-- CHECK 2: effective existing-table access (including inherited/PUBLIC grants).
-- RLS policies are returned separately below; an ACL alone does not mean rows are visible.
SELECT r.rolname,n.nspname||'.'||c.relname AS relation,
 has_schema_privilege(r.oid,n.oid,'USAGE') AS schema_usage,
 ARRAY(SELECT p FROM unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) p
       WHERE has_table_privilege(r.oid,c.oid,p)) AS table_rights,
 ARRAY(SELECT a.attname||':'||p FROM pg_attribute a CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE']) p
       WHERE a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
         AND has_column_privilege(r.oid,c.oid,a.attnum,p)
         AND NOT has_table_privilege(r.oid,c.oid,p)) AS column_only_rights
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace CROSS JOIN pg_roles r
WHERE n.nspname IN ('quant_app','equity_operations','equity_research') AND c.relkind='r'
 AND r.rolname IN ('quant_app_runtime','equity_research_collector','quant_archive_worker','anon','authenticated','service_role')
ORDER BY relation,r.rolname;

-- CHECK 3: actual policies, even where currently DISABLED.
SELECT schemaname,tablename,policyname,roles,cmd,permissive,qual,with_check
FROM pg_policies WHERE schemaname IN ('quant_app','equity_operations','equity_research')
ORDER BY schemaname,tablename,policyname;

-- CHECK 4: your application's migration ledger, not the Supabase CLI ledger.
SELECT version,applied_at FROM quant_app.schema_migrations ORDER BY version;

-- CHECK 5: completed archive deletions versus verified exports.
-- These are recorded batch totals, NOT independently reverified Drive contents.
SELECT source_table,count(*) AS batches,sum(row_count) AS recorded_export_rows,
 sum(COALESCE(deleted_count,0)) AS recorded_deleted_rows,
 count(*) FILTER(WHERE completed_at IS NULL) AS export_only_or_uncompleted_batches,
 max(verified_at) AS latest_verified_at,max(completed_at) AS latest_completed_at
FROM quant_app.archive_manifests GROUP BY source_table ORDER BY source_table;

-- CHECK 6: live outcomes count and the exact current 14-day superseded predicate.
-- Cutoff uses UTC date, matching archive_maintenance.py. Does not authorize deletion.
WITH cutoff AS (SELECT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date-14)::timestamp AT TIME ZONE 'UTC' AS t)
SELECT count(*) AS live_rows,count(DISTINCT decision_id) AS subjects,
 min(recorded_at) AS oldest_at,max(recorded_at) AS newest_at,
 count(*) FILTER(WHERE recorded_at<cutoff.t AND EXISTS(
   SELECT 1 FROM equity_research.outcomes newer WHERE newer.decision_id=s.decision_id
     AND (newer.recorded_at,newer.snapshot_id)>(s.recorded_at,s.snapshot_id))) AS eligible_superseded_rows
FROM equity_research.outcomes s CROSS JOIN cutoff;

-- CHECK 7: bounded diagnostic sample, latest 100 outcomes, NOT population estimate.
-- Stored payload bytes and serialized JSON bytes differ; neither equals full table allocation.
SELECT count(*) AS sampled_rows,avg(pg_column_size(payload)) AS mean_stored_payload_bytes,
 avg(octet_length(payload::text)) AS mean_json_text_bytes,
 max(octet_length(payload::text)) AS max_json_text_bytes
FROM (SELECT payload FROM equity_research.outcomes ORDER BY recorded_at DESC,snapshot_id DESC LIMIT 100) s;

-- CHECK 8: canonical universe history; newest canonical date must be preserved.
-- Older rows are review candidates only, NOT approved archive/delete targets.
SELECT snapshot_date,count(*) AS rows,
 snapshot_date=(SELECT max(snapshot_date) FROM quant_app.universe_snapshots) AS current_reader_date
FROM quant_app.universe_membership GROUP BY snapshot_date ORDER BY snapshot_date DESC;
