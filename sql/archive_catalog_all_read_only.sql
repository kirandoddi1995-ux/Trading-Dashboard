-- Owner-run operational metadata ONLY. Save the single JSON cell privately.
-- All dates, all six sources, including export-only and unfinished receipts.
-- No market rows, maintenance, credentials, extension, or permission changes.
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL TIME ZONE 'UTC';
SET LOCAL statement_timeout = '10s';
SET LOCAL lock_timeout = '2s';
WITH receipts AS MATERIALIZED (
    SELECT batch_id, source_table, row_count, file_sha256, drive_file_id,
           drive_manifest_id, deleted_count, verified_at, completed_at,
           row_number() OVER (ORDER BY batch_id) AS ordinal,
           (octet_length(COALESCE(batch_id, '')) <= 64
            AND octet_length(COALESCE(source_table, '')) <= 128
            AND octet_length(COALESCE(file_sha256, '')) <= 64
            AND octet_length(COALESCE(drive_file_id, '')) <= 200
            AND octet_length(COALESCE(drive_manifest_id, '')) <= 200) AS fields_bounded
    FROM quant_app.archive_manifests
), payload AS (
    SELECT count(*) AS total_count, COALESCE(bool_and(fields_bounded), true) AS fields_bounded,
           CASE WHEN count(*) <= 4096 THEN COALESCE(jsonb_agg(jsonb_build_object(
               'batch_id', batch_id, 'source_table', source_table, 'row_count', row_count,
               'file_sha256', file_sha256, 'drive_file_id', drive_file_id,
               'drive_manifest_id', drive_manifest_id, 'deleted_count', deleted_count,
               'verified_at', to_char(verified_at, 'YYYY-MM-DD"T"HH24:MI:SS.US"+00:00"'),
               'completed_at', to_char(completed_at, 'YYYY-MM-DD"T"HH24:MI:SS.US"+00:00"')
           ) ORDER BY batch_id) FILTER (WHERE ordinal <= 4096 AND fields_bounded), '[]'::jsonb)
           ELSE '[]'::jsonb END AS records
    FROM receipts
)
SELECT jsonb_build_object(
    'format', 'archive-all-catalog-v1',
    'status', CASE WHEN fields_bounded AND total_count <= 4096 AND octet_length(records::text) <= 4194304
                   THEN 'COMPLETE_METADATA_EXPORT' ELSE 'BOUND_EXCEEDED_REVIEW_REQUIRED' END,
    'measured_at', to_char(clock_timestamp(), 'YYYY-MM-DD"T"HH24:MI:SS.US"+00:00"'),
    'total_count', total_count,
    'truncated', (NOT fields_bounded OR total_count > 4096 OR octet_length(records::text) > 4194304),
    'records', CASE WHEN fields_bounded AND total_count <= 4096 AND octet_length(records::text) <= 4194304
                    THEN records ELSE '[]'::jsonb END
) AS private_archive_all_catalog
FROM payload;
ROLLBACK;
