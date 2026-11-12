-- READ-ONLY report: forward outcome labels of the scheduled Stage-2 shadow passes
-- (equity_stage2_maturation.py; switch SCHEDULED_STAGE2_MATURATION). Changes nothing.
--
-- Decisions: shadow passes at least 22 days old (IST date, as maturation) whose 15-session horizon has
-- completed: 15 sessions of the shadow scan after the decision day (it runs every NSE session; a missed
-- scan only delays eligibility, it never brings it forward), or any pass of that day is already labelled
-- (maturation counts sessions on NIFTY's own bars, so a label settles the day for every pass of it, and
-- coverage is never judged on the labelled passes alone). A stock that passed in both scans of one day counts
-- once: its earliest scan that day, chosen BEFORE looking at labels, so both policies are scored on
-- the same decisions. Policies: incumbent-levels-v1 (the recorded stop/target) and atr15-stop-v1
-- (stop at entry - 1.5 ATR). Label version net-excess-execution-v2.minute-aligned-v1 only.
-- sample 'all'    = every eligible decision; stats over those labelled under that policy.
-- sample 'paired' = only decisions labelled under BOTH policies (the like-for-like comparison).
-- Rows per sample and policy, per recorded action (Buy/Watch), and per action and score band.
-- labelled < eligible means evidence was incomplete or ambiguous (retried until 60 days old).
-- Returns are after the decision's estimated round-trip costs, in %.
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
labelled_days AS MATERIALIZED (   -- a label proves NIFTY completed the horizon for that whole day
    SELECT DISTINCT o.as_of_date
    FROM quant_app.scanner_observations o
    JOIN quant_app.prediction_targets t ON t.observation_id = o.observation_id AND t.horizon_sessions = 15
    JOIN policies p ON t.target_version = 'stage2-shadow:net-excess-execution-v2.minute-aligned-v1:' || p.policy
    WHERE o.strategy_version = 'equity-stage2-scheduled-shadow-v1'
),
decisions AS (
    SELECT f.* FROM first_scans f
    WHERE (SELECT count(*) FROM scan_sessions s WHERE s.as_of_date > f.as_of_date) >= 15
       OR f.as_of_date IN (SELECT as_of_date FROM labelled_days)
),
actions AS (
    -- LEFT JOIN: a decision whose ledger entry is missing still counts as eligible (action 'unknown').
    SELECT d.observation_id, d.as_of_date,
           c.value->'inputs_used'->>'signal_action' AS action,
           CASE WHEN d.score >= 70 THEN '70+' WHEN d.score >= 60 THEN '60-70'
                WHEN d.score >= 50 THEN '50-60' WHEN d.score IS NOT NULL THEN '<50' ELSE 'unknown' END AS band
    FROM decisions d
    LEFT JOIN quant_app.evidence_ledger_events e
      ON e.aggregate_id = 'scan:' || (d.feature_json->>'scan_run_id')
     AND e.event_type = 'DECISION_BATCH_EVALUATED'
    LEFT JOIN LATERAL (
        SELECT x.value FROM jsonb_array_elements(e.payload->'candidates') x
        WHERE x.value->>'decision_id' = d.observation_id LIMIT 1
    ) c ON true
),
grid AS (
    SELECT a.*, p.policy, t.outcome, t.net_return, t.excess_return
    FROM actions a
    CROSS JOIN policies p
    LEFT JOIN quant_app.prediction_targets t
      ON t.observation_id = a.observation_id
     AND t.horizon_sessions = 15
     AND t.target_version = 'stage2-shadow:net-excess-execution-v2.minute-aligned-v1:' || p.policy
),
paired AS (
    SELECT observation_id FROM grid GROUP BY observation_id HAVING count(outcome) = 2
),
scoped AS (
    SELECT 'all' AS sample, g.* FROM grid g
    UNION ALL
    SELECT 'paired' AS sample, g.* FROM grid g JOIN paired USING (observation_id)
)
SELECT sample, policy,
       CASE WHEN GROUPING(action) = 1 THEN 'ALL' ELSE coalesce(action, 'unknown') END AS action,
       CASE WHEN GROUPING(band) = 1 THEN 'ALL' ELSE band END AS score_band,
       count(*) AS eligible,
       count(outcome) AS labelled,
       count(*) FILTER (WHERE outcome = 'target') AS target_hits,
       count(*) FILTER (WHERE outcome = 'stop') AS stop_hits,
       count(*) FILTER (WHERE outcome = 'horizon') AS time_exits,
       round(100 * avg(net_return)::numeric, 2) AS avg_net_pct,
       round(100 * (percentile_cont(0.5) WITHIN GROUP (ORDER BY net_return))::numeric, 2) AS median_net_pct,
       round(100 * avg(excess_return)::numeric, 2) AS avg_excess_vs_nifty_pct,
       round(100 * avg((net_return > 0)::int)::numeric, 1) AS positive_pct,
       min(as_of_date) AS first_decision, max(as_of_date) AS last_decision
FROM scoped
GROUP BY GROUPING SETS ((sample, policy), (sample, policy, action), (sample, policy, action, band))
ORDER BY sample, policy, GROUPING(action) DESC, action, GROUPING(band) DESC, band;
