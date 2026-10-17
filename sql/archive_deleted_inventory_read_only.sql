-- Owner-run operational receipt export ONLY; save the JSON privately.
-- No market rows, DDL, maintenance, deletion, restore, or Drive access.
-- One final result set avoids the SQL editor's last-result-only presentation.
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL TIME ZONE 'UTC';
SET LOCAL statement_timeout = '10s';
SET LOCAL lock_timeout = '2s';
WITH bounds AS (
    SELECT timestamptz '2026-10-11 00:00:00+00' AS window_start,
           timestamptz '2026-10-17 18:25:14+00' AS window_end
), affected AS MATERIALIZED (
    SELECT m.batch_id, m.source_table, m.row_count, m.file_sha256,
           m.drive_file_id, m.drive_manifest_id, m.deleted_count, m.completed_at
    FROM quant_app.archive_manifests m CROSS JOIN bounds b
    WHERE m.completed_at >= b.window_start AND m.completed_at <= b.window_end
      AND m.deleted_count > 0
)
SELECT jsonb_build_object(
    'format', 'archive-recovery-inventory-v1',
    'window_start', to_char(b.window_start, 'YYYY-MM-DD"T"HH24:MI:SS.US"+00:00"'),
    'window_end', to_char(b.window_end, 'YYYY-MM-DD"T"HH24:MI:SS.US"+00:00"'),
    'measured_at', to_char(clock_timestamp(), 'YYYY-MM-DD"T"HH24:MI:SS.US"+00:00"'),
    'batches', COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
            'batch_id', a.batch_id, 'source_table', a.source_table,
            'row_count', a.row_count, 'file_sha256', a.file_sha256,
            'drive_file_id', a.drive_file_id, 'drive_manifest_id', a.drive_manifest_id,
            'deleted_count', a.deleted_count,
            'completed_at', to_char(a.completed_at, 'YYYY-MM-DD"T"HH24:MI:SS.US"+00:00"')
        ) ORDER BY a.batch_id) FROM affected a
    ), '[]'::jsonb)
) AS private_recovery_inventory
FROM bounds b;
ROLLBACK;
