-- READ ONLY. Run checks separately. Save CHECK 1 now and at the same point in
-- the collection/archive cycle tomorrow and the following day; no history table is created.

-- CHECK 1: allocated growth, not gross ingestion. One JSON cell avoids the 100-row display cap.
SELECT jsonb_build_object('measured_at',clock_timestamp(),
 'database_bytes',pg_database_size(current_database()),
 'nominal_headroom_to_500_decimal_MB',500000000-pg_database_size(current_database()),
 'tables',(SELECT jsonb_agg(jsonb_build_object('table',n.nspname||'.'||c.relname,
      'bytes',pg_total_relation_size(c.oid)) ORDER BY n.nspname,c.relname)
   FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE c.relkind='r' AND n.nspname IN ('quant_app','equity_research','equity_operations'))
) AS growth_baseline;

-- CHECK 2: detect repeated canonical content; equal row counts alone prove nothing.
-- MD5 here is a diagnostic comparison, NOT an archival integrity/authorization hash.
-- Exclude snapshot/observation time, keep actual instrument fields and raw contents.
WITH daily AS (
 SELECT snapshot_date,count(*) AS rows,
  md5(string_agg(md5((to_jsonb(u)-'snapshot_date'-'observed_at')::text),' '
      ORDER BY instrument_key)) AS diagnostic_content_hash
 FROM quant_app.universe_membership u GROUP BY snapshot_date
), compared AS (
 SELECT *,lag(snapshot_date) OVER(ORDER BY snapshot_date) AS previous_date,
   lag(diagnostic_content_hash) OVER(ORDER BY snapshot_date) AS previous_hash FROM daily
)
SELECT snapshot_date,rows,previous_date,
 extract(isodow FROM snapshot_date) IN (6,7) AS calendar_weekend,
 diagnostic_content_hash=previous_hash AS same_content_as_previous,
 snapshot_date=(SELECT max(snapshot_date) FROM quant_app.universe_snapshots) AS current_reader_date
FROM compared ORDER BY snapshot_date DESC;

-- CHECK 3: retained outcome cohorts; sizes describe live stored payloads, not reclaimable allocation.
-- horizon_complete alone does NOT mean missing bars have been corrected.
SELECT (recorded_at AT TIME ZONE 'UTC')::date AS recorded_day_utc,count(*) AS rows,
 sum(pg_column_size(payload)) AS stored_payload_bytes,
 count(*) FILTER(WHERE payload->>'horizon_complete'='true') AS horizon_complete_rows,
 count(*) FILTER(WHERE payload->>'coverage_complete'='false') AS incomplete_coverage_rows
FROM equity_research.outcomes GROUP BY 1 ORDER BY 1 DESC;
