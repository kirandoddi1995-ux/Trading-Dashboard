-- Owner-run operational metadata only. No source rows, DDL, maintenance or deletes.
BEGIN READ ONLY;
SET LOCAL TIME ZONE 'UTC';
SET LOCAL statement_timeout = '10s';
SET LOCAL lock_timeout = '2s';
SELECT clock_timestamp() AS measured_at_utc,
       pg_database_size(current_database()) AS current_database_bytes,
       (SELECT sum(pg_database_size(datname)) FROM pg_database) AS cluster_bytes;
SELECT source_table, count(*) AS completed_manifests,
       sum(row_count) AS recorded_archived_rows,
       sum(coalesce(deleted_count,0)) AS recorded_deleted_rows,
       min(completed_at) AS first_completion_utc,
       max(completed_at) AS last_completion_utc
FROM quant_app.archive_manifests
WHERE completed_at >= timestamptz '2026-10-11 00:00:00+00'
GROUP BY source_table ORDER BY source_table;
SELECT count(*) AS active_archive_sessions
FROM pg_stat_activity
WHERE application_name='quant-archive' AND pid <> pg_backend_pid();
ROLLBACK;
