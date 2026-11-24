-- READ-ONLY rows for PREREG3 (claude/PREREG_2026-11-24_live_pipeline_forward.md, v1.2): one row per first-scan
-- pass of the scheduled Stage-2 shadow at least 22 days old, for stage2_forward_test.py. Changes nothing.
--
-- The CTEs up to `decisions` are copied byte for byte from sql/stage2_shadow_outcomes_report.sql (a test
-- keeps them identical), so both read the same population: the earliest scan of each stock-day,
-- eligible once its 15-session horizon has completed. `eligible` = in that report's decisions; the tool
-- uses eligible rows only, and holds a look while an earlier first-scan day is not eligible yet (a later
-- day can become eligible first, through a full-window label).
-- incumbent_excess / atr15_excess: the label's excess over NIFTY after the decision's own costs
-- (fraction; NULL = no label). settled: the row can no longer change: both policies' labels are stored
-- (labels are append-only and maturation stops retrying), or the decision is older than maturation's
-- 60-day retry window. traded_value: entry x the Stage-1 20-day average volume (NULL when either is
-- missing). queried_at: when this query ran (IST), the report's provenance. total_rows: the row count, so a
-- cut-off export (a tool's output limit) is refused instead of read.
WITH policies(policy) AS (
    VALUES ('incumbent-levels-v1'), ('atr15-stop-v1')
),
scan_sessions AS MATERIALIZED (   -- once (one row per session), not once per decision
    SELECT DISTINCT o.as_of_date
    FROM quant_app.scanner_observations o
    WHERE o.strategy_version = 'equity-stage2-scheduled-shadow-v1'
      AND o.as_of_date < (now() AT TIME ZONE 'Asia/Kolkata')::date
),
first_scans AS (
    SELECT DISTINCT ON (o.instrument_key, o.as_of_date)
           o.observation_id, o.instrument_key, o.as_of_date, o.score, o.feature_json
    FROM quant_app.scanner_observations o
    WHERE o.strategy_version = 'equity-stage2-scheduled-shadow-v1' AND o.stage2_pass
      AND o.as_of_date <= (now() AT TIME ZONE 'Asia/Kolkata')::date - 22
    ORDER BY o.instrument_key, o.as_of_date, o.observed_at, o.observation_id
),
labelled_days AS MATERIALIZED (   -- a full-window label proves NIFTY completed the horizon for that day
    SELECT DISTINCT o.as_of_date
    FROM quant_app.scanner_observations o
    JOIN quant_app.prediction_targets t ON t.observation_id = o.observation_id AND t.horizon_sessions = 15
     AND t.label_end_date >= o.as_of_date + 21
    JOIN policies p ON t.target_version = 'stage2-shadow:net-excess-app-contract-v2:' || p.policy
    WHERE o.strategy_version = 'equity-stage2-scheduled-shadow-v1'
),
complete_days AS MATERIALIZED (   -- every decision of the day labelled under both policies: nothing left out
    SELECT f.as_of_date
    FROM first_scans f
    GROUP BY f.as_of_date
    HAVING bool_and((SELECT count(DISTINCT t.target_version) FROM quant_app.prediction_targets t
                     JOIN policies p ON t.target_version = 'stage2-shadow:net-excess-app-contract-v2:' || p.policy
                     WHERE t.observation_id = f.observation_id AND t.horizon_sessions = 15) = 2)
),
decisions AS (
    SELECT f.* FROM first_scans f
    WHERE (SELECT count(*) FROM scan_sessions s WHERE s.as_of_date > f.as_of_date) >= 15
       OR f.as_of_date IN (SELECT as_of_date FROM labelled_days)
       OR f.as_of_date IN (SELECT as_of_date FROM complete_days)
),
per_decision AS (
    SELECT f.observation_id::text AS observation_id,
           f.as_of_date::text AS day,
           (f.observation_id IN (SELECT observation_id FROM decisions)) AS eligible,
           to_char(o.observed_at AT TIME ZONE 'Asia/Kolkata', 'HH24:MI') AS scan_time,
           f.score::float8 AS score,
           c.value->'inputs_used'->>'signal_action' AS action,
           ti.outcome AS incumbent_outcome,
           ti.excess_return::float8 AS incumbent_excess,
           ta.excess_return::float8 AS atr15_excess,
           ds.disposition AS disposition,
           ((ti.observation_id IS NOT NULL AND ta.observation_id IS NOT NULL)
            OR f.as_of_date < (now() AT TIME ZONE 'Asia/Kolkata')::date - 60) AS settled,
           (c.value->'inputs_used'->>'entry')::float8
             * (s1.value->'inputs_used'->>'average_volume_20d')::float8 AS traded_value,
           to_char(now() AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM-DD"T"HH24:MI:SS') AS queried_at,
           count(*) OVER () AS total_rows
    FROM first_scans f
    JOIN quant_app.scanner_observations o ON o.observation_id = f.observation_id
    LEFT JOIN LATERAL (   -- one candidate even if a batch event were stored twice
        SELECT x.value
        FROM quant_app.evidence_ledger_events e, jsonb_array_elements(e.payload->'candidates') x
        WHERE e.aggregate_id = 'scan:' || (f.feature_json->>'scan_run_id')
          AND e.event_type = 'DECISION_BATCH_EVALUATED'
          AND x.value->>'decision_id' = f.observation_id
        ORDER BY e.sequence_no
        LIMIT 1
    ) c ON true
    LEFT JOIN LATERAL (
        SELECT x.value
        FROM quant_app.evidence_ledger_events e1, jsonb_array_elements(e1.payload->'candidates') x
        WHERE e1.aggregate_id = c.value->'inputs_used'->>'stage1_decision_scan'
          AND e1.event_type = 'DECISION_BATCH_EVALUATED'
          AND x.value->>'instrument_key' = f.instrument_key
        ORDER BY e1.sequence_no
        LIMIT 1
    ) s1 ON true
    LEFT JOIN quant_app.prediction_targets ti
      ON ti.observation_id = f.observation_id AND ti.horizon_sessions = 15
     AND ti.target_version = 'stage2-shadow:net-excess-app-contract-v2:incumbent-levels-v1'
    LEFT JOIN quant_app.prediction_targets ta
      ON ta.observation_id = f.observation_id AND ta.horizon_sessions = 15
     AND ta.target_version = 'stage2-shadow:net-excess-app-contract-v2:atr15-stop-v1'
    LEFT JOIN quant_app.stage2_shadow_dispositions ds
      ON ds.observation_id = f.observation_id AND ds.label_version = 'net-excess-app-contract-v2'
)
SELECT * FROM per_decision ORDER BY day, observation_id;
