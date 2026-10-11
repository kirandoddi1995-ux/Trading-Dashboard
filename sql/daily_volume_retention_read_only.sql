-- Owner preview only; not an archive/delete candidate authorisation.
-- Retains exactly the current reader's 20 most recent NON-NULL captured dates
-- before the IST date. Current/future and NULL rows stay protected in this preview.
-- Unknown dependencies, cold-reader/custody and licence gates remain UNVERIFIED.
-- No prices, instrument IDs, credentials or frozen research results are returned.
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s';
-- BEGIN_VOLUME_INVENTORY
WITH parameters AS (
    SELECT (transaction_timestamp() AT TIME ZONE 'Asia/Kolkata')::date AS as_of_date
), ranked AS (
    SELECT d.instrument_key,d.trade_date,
           row_number() OVER (PARTITION BY d.instrument_key ORDER BY d.trade_date DESC) AS rn,
           pg_column_size(d) AS estimated_row_bytes
    FROM quant_app.market_daily_volumes d,parameters p
    WHERE d.trade_date<p.as_of_date AND d.max_captured_volume IS NOT NULL
), inventory AS (
    SELECT count(*) FILTER (WHERE rn<=20) AS lookback_rows,
           count(*) FILTER (WHERE rn>20) AS older_rows,
           coalesce(sum(estimated_row_bytes) FILTER (WHERE rn>20),0) AS older_row_bytes_estimate
    FROM ranked
), short_histories AS (
    SELECT count(*) AS instruments_below_20_captured_dates FROM (
        SELECT instrument_key FROM ranked GROUP BY instrument_key HAVING count(*)<20
    ) available
)
SELECT (SELECT as_of_date FROM parameters) AS as_of_date,
       (SELECT count(*) FROM quant_app.market_daily_volumes) AS total_rows,
       i.lookback_rows,i.older_rows,i.older_row_bytes_estimate,
       s.instruments_below_20_captured_dates,
       false AS dependency_checks_complete,false AS archive_reader_commissioned,
       false AS deletion_authorised
FROM inventory i CROSS JOIN short_histories s;
-- END_VOLUME_INVENTORY
ROLLBACK;
