-- READ ONLY. Run each numbered block separately; save results before/after cleanup,
-- after VACUUM, and after the next collection cycle. No credentials or query text output.

-- 1. Allocation. Bytes avoid MB/MiB ambiguity; compare dashboard database usage too.
SELECT clock_timestamp() AS measured_at,
       pg_database_size(current_database()) AS current_database_bytes,
       (SELECT sum(pg_database_size(datname)) FROM pg_database) AS cluster_database_bytes;
SELECT c.oid::regclass::text AS relation,pg_total_relation_size(c.oid) AS total_bytes,
       pg_relation_size(c.oid) AS heap_bytes,pg_indexes_size(c.oid) AS index_bytes,
       CASE WHEN c.reltoastrelid<>0 THEN pg_total_relation_size(c.reltoastrelid) ELSE 0 END AS toast_bytes
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname IN ('quant_app','equity_research','equity_operations') AND c.relkind='r'
ORDER BY total_bytes DESC;

-- 2. Parent AND TOAST vacuum statistics/overrides. Dead counts are estimates.
WITH parents AS (
 SELECT c.oid,c.reltoastrelid FROM pg_class c
 WHERE c.oid IN ('equity_research.outcomes'::regclass,'quant_app.universe_membership'::regclass)
), targets AS (
 SELECT oid,'parent' AS kind FROM parents UNION ALL
 SELECT reltoastrelid,'TOAST' FROM parents WHERE reltoastrelid<>0
)
SELECT c.oid::regclass::text AS relation,t.kind,c.reltuples,c.reloptions,
       s.n_live_tup,s.n_dead_tup,s.last_vacuum,s.last_autovacuum,
       s.vacuum_count,s.autovacuum_count,pg_total_relation_size(c.oid) AS allocated_bytes
FROM targets t JOIN pg_class c ON c.oid=t.oid
LEFT JOIN pg_stat_all_tables s ON s.relid=c.oid;
SELECT name,setting,unit FROM pg_settings
WHERE name IN ('autovacuum','autovacuum_vacuum_threshold','autovacuum_vacuum_scale_factor',
              'autovacuum_vacuum_insert_threshold','autovacuum_vacuum_insert_scale_factor',
              'autovacuum_naptime','autovacuum_max_workers');

-- 3. Possible cleanup blockers. Do not terminate sessions automatically.
SELECT pid,usename,state,clock_timestamp()-xact_start AS transaction_age,
       backend_xmin,age(backend_xmin) AS xmin_age,wait_event_type,wait_event
FROM pg_stat_activity WHERE pid<>pg_backend_pid()
AND (xact_start<clock_timestamp()-interval '5 minutes' OR backend_xmin IS NOT NULL)
ORDER BY xact_start NULLS LAST;
SELECT slot_name,slot_type,active,xmin,catalog_xmin FROM pg_replication_slots;
SELECT gid,prepared,owner,database FROM pg_prepared_xacts;
SELECT pid,relid::regclass::text AS relation,phase,heap_blks_total,heap_blks_scanned
FROM pg_stat_progress_vacuum;

-- 4. Proposed outcome cutoff / retained-latest protection. Valid before migration.
SELECT ((clock_timestamp() AT TIME ZONE 'UTC')::date-7) AS cutoff_date,
 count(*) AS eligible_rows,coalesce(sum(pg_column_size(s.payload)),0) AS live_payload_bytes
FROM equity_research.outcomes s
WHERE s.recorded_at < (((statement_timestamp() AT TIME ZONE 'UTC')::date-7)::timestamp AT TIME ZONE 'UTC')
AND EXISTS (SELECT 1 FROM equity_research.outcomes newer WHERE newer.decision_id=s.decision_id
 AND (newer.recorded_at,newer.snapshot_id)>(s.recorded_at,s.snapshot_id));
-- Actual horizon controls, not a predicted expiry based on elapsed weekdays.
WITH latest AS (
 SELECT DISTINCT ON(decision_id) decision_id,payload FROM equity_research.outcomes
 ORDER BY decision_id,recorded_at DESC,snapshot_id DESC
)
SELECT payload->>'horizon_close' AS horizon_close,
       payload->>'requested_data_through' AS requested_data_through,
       payload->>'horizon_complete' AS horizon_complete,count(*) AS subjects
FROM latest GROUP BY 1,2,3 ORDER BY 1,2;

-- 5. Canonical eligibility: preserve headers, current date, complete fallback,
-- recently recaptured dates, and every surviving scanner reference.
SELECT s.snapshot_date,count(*) AS eligible_rows,
       sum(pg_column_size(s)) AS live_row_bytes
FROM quant_app.universe_membership s
WHERE s.snapshot_date < (statement_timestamp() AT TIME ZONE 'UTC')::date-14
AND s.observed_at < (((statement_timestamp() AT TIME ZONE 'UTC')::date-14)::timestamp AT TIME ZONE 'UTC')
AND EXISTS (SELECT 1 FROM quant_app.universe_snapshots h WHERE h.snapshot_date=s.snapshot_date
 AND h.observed_at < (((statement_timestamp() AT TIME ZONE 'UTC')::date-14)::timestamp AT TIME ZONE 'UTC'))
AND s.snapshot_date < (SELECT max(snapshot_date) FROM quant_app.universe_snapshots)
AND s.snapshot_date < (SELECT max(snapshot_date) FROM quant_app.universe_snapshots WHERE is_complete)
AND NOT EXISTS (SELECT 1 FROM quant_app.scanner_observations o WHERE o.universe_snapshot_date=s.snapshot_date)
GROUP BY s.snapshot_date ORDER BY s.snapshot_date;
SELECT max(snapshot_date) AS reader_date,
       max(snapshot_date) FILTER(WHERE is_complete) AS latest_complete_date
FROM quant_app.universe_snapshots;
SELECT source_table,count(*) AS batches,sum(row_count) AS exported_rows,
       sum(coalesce(deleted_count,0)) AS deleted_rows,max(completed_at) AS latest_completion
FROM quant_app.archive_manifests GROUP BY source_table ORDER BY source_table;

-- 6. Before/after invariants. Save these results and compare after deletion.
SELECT count(DISTINCT decision_id) AS retained_subjects FROM equity_research.outcomes;
SELECT decision_id,snapshot_id,recorded_at FROM (
 SELECT DISTINCT ON(decision_id) decision_id,snapshot_id,recorded_at
 FROM equity_research.outcomes ORDER BY decision_id,recorded_at DESC,snapshot_id DESC
) latest ORDER BY decision_id;
SELECT h.snapshot_date,h.is_complete,count(u.instrument_key) AS retained_members
FROM quant_app.universe_snapshots h LEFT JOIN quant_app.universe_membership u USING(snapshot_date)
WHERE h.snapshot_date IN ((SELECT max(snapshot_date) FROM quant_app.universe_snapshots),
 (SELECT max(snapshot_date) FROM quant_app.universe_snapshots WHERE is_complete))
GROUP BY h.snapshot_date,h.is_complete ORDER BY h.snapshot_date;

-- 7. Run AFTER migration only. Expect both outcome guards and canonical guard enabled.
SELECT tgrelid::regclass::text AS relation,tgname,tgenabled FROM pg_trigger
WHERE NOT tgisinternal AND tgrelid IN ('equity_research.outcomes'::regclass,
                                     'quant_app.universe_membership'::regclass);
SELECT has_table_privilege('quant_archive_worker','quant_app.universe_membership','SELECT') AS archive_read,
 has_table_privilege('quant_archive_worker','quant_app.universe_membership','DELETE') AS archive_delete,
 has_table_privilege('quant_archive_worker','quant_app.universe_membership','INSERT,UPDATE,TRUNCATE') AS forbidden_writes,
 has_table_privilege('equity_research_collector','quant_app.universe_membership','SELECT,INSERT,UPDATE,DELETE') AS research_access;
