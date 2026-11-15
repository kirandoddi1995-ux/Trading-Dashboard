-- Stage-2 shadow re-score report (read-only). Zero-Buys study, 15 Nov 2026
-- (claude/status_2026-11-15_zero_buys_root_cause.md).
--
-- Question: which level policy, reward:risk scale and score threshold would have produced Buys,
-- and how did those Buys turn out? Nothing here changes the live rule (equity_action in
-- app_runtime.py); it recomputes the action per shadow pass under variants.
--
-- Per pass (Stage-2 shadow pass with its ledger candidate, as the maturation reads it):
--   levels  incumbent-levels-v1 = recorded stop/target; atr15-stop-v1 = stop entry - 1.5 ATR, target
--           from equity_stage2_maturation.levels_for_stop (2.1 ATR when a resistance at or above
--           entry + 2.25 ATR exists, else entry + 2 (1 + horizon/70) ATR).
--   net R:R (target - entry - cost) / (entry - stop + cost), cost = entry x round-trip bps
--           (trade_contracts.calculate_trade_math); Stage-2 needs >= 1.30.
--   score'  recorded score - 0.15 x recorded risk_reward component + 0.15 x scale(net R:R, 1, H)
--           (weights: prediction_validation.scanner_composite_score), H = 4 (live), 3 or 2.
--   action  Buy when net R:R >= 1.30, stop <= 20% below entry, target - entry <= ATR x
--           max(4, 2 sqrt(horizon)), and score' >= T (70 live, 65, 60); else Watch.
-- One pass per stock per day: the day's first scan, as the outcomes report counts it.
-- Self-check: incumbent-levels-v1 / H 4 / T 70 must equal recorded_buys (the recorded signal_action,
-- before the governance gate). net R:R is rounded to 2 dp as calculate_trade_math does.
-- unscorable = passes missing score, risk_reward or ATR: no action is recomputed for them, and they
-- are in no other action or outcome column. Passes
-- with no ledger candidate are left out (the outcomes report keeps them as 'unknown').
-- Outcomes: labels of that policy (net-excess-app-contract-v1). full_* = full-window labels only
-- (label_end_date >= decision day + 21): early labels are stop/target exits only, so their average
-- alone is biased; use the outcomes report for cohort-complete comparisons.
WITH first_scans AS (
    SELECT DISTINCT ON (o.instrument_key, o.as_of_date) o.*
    FROM quant_app.scanner_observations o
    WHERE o.strategy_version = 'equity-stage2-scheduled-shadow-v1' AND o.stage2_pass
    ORDER BY o.instrument_key, o.as_of_date, o.observed_at, o.observation_id
),
passes AS MATERIALIZED (
    SELECT o.observation_id, o.as_of_date, o.entry::numeric AS entry, o.stop::numeric AS stop,
           o.target::numeric AS target, (c.value->'inputs_used'->>'score')::numeric AS score,
           (c.value->'inputs_used'->'features'->'components'->>'risk_reward')::numeric AS rr_component,
           (c.value->'inputs_used'->'equity_capture'->'inputs'->>'atr_val')::numeric AS atr,
           (c.value->'inputs_used'->'equity_capture'->'inputs'->'levels'->>'resistance20')::numeric AS r20,
           (c.value->'inputs_used'->'equity_capture'->'inputs'->'levels'->>'resistance60')::numeric AS r60,
           coalesce((c.value->'inputs_used'->'features'->>'horizon_days')::numeric, 15) AS horizon,
           coalesce((c.value->'costs'->>'round_trip_bps')::numeric, 0) AS cost_bps,
           c.value->'inputs_used'->>'signal_action' AS recorded_action
    FROM first_scans o
    JOIN quant_app.evidence_ledger_events e
      ON e.aggregate_id = 'scan:' || (o.feature_json->>'scan_run_id')
     AND e.event_type = 'DECISION_BATCH_EVALUATED'
    CROSS JOIN LATERAL jsonb_array_elements(e.payload->'candidates') c
    WHERE c.value->>'decision_id' = o.observation_id
      AND o.entry IS NOT NULL AND o.stop IS NOT NULL AND o.target IS NOT NULL
),
levels AS (
    SELECT p.*, 'incumbent-levels-v1' AS policy, p.stop AS s, p.target AS t FROM passes p
    UNION ALL
    SELECT p.*, 'atr15-stop-v1', round(p.entry - 1.5 * p.atr, 2),
           round(CASE WHEN EXISTS (SELECT 1 FROM (VALUES (p.r20), (p.r60)) r(v)
                             WHERE r.v > p.entry * 1.005 AND r.v >= p.entry + 2.25 * p.atr)
                THEN least((SELECT min(r.v) FROM (VALUES (p.r20), (p.r60)) r(v)
                            WHERE r.v > p.entry * 1.005 AND r.v >= p.entry + 2.25 * p.atr),
                           p.entry + greatest(2.1 * p.atr, 0.85 * 2.0 * (1 + p.horizon / 70.0) * p.atr))
                ELSE p.entry + greatest(2.1 * p.atr, 2.0 * (1 + p.horizon / 70.0) * p.atr) END, 2)
    FROM passes p WHERE p.atr > 0 AND p.entry - 1.5 * p.atr > 0
),
rated AS (
    SELECT l.*, round((l.t - l.entry - l.entry * l.cost_bps / 10000)
                      / (l.entry - l.s + l.entry * l.cost_bps / 10000), 2) AS net_rr,
           (l.entry - l.s) / l.entry <= 0.20
             AND l.t - l.entry <= l.atr * greatest(4, 2 * sqrt(greatest(l.horizon, 1))) AS fits_gate
    FROM levels l WHERE l.s > 0 AND l.s < l.entry AND l.entry < l.t
),
variants AS (
    SELECT r.*, h.scale_high, th.threshold,
           r.score - 0.15 * r.rr_component
             + 0.15 * least(100, greatest(0, (r.net_rr - 1.0) / (h.scale_high - 1.0) * 100)) AS rescored
    FROM rated r
    CROSS JOIN (VALUES (4.0), (3.0), (2.0)) h(scale_high)
    CROSS JOIN (VALUES (70), (65), (60)) th(threshold)
),
acted AS (
    SELECT v.*, CASE WHEN v.score IS NULL OR v.rr_component IS NULL OR v.atr IS NULL THEN NULL
                     ELSE v.net_rr >= 1.30 AND v.fits_gate AND v.rescored >= v.threshold END AS buy,
           t.net_return, t.excess_return, t.positive_excess,
           t.label_end_date >= v.as_of_date + 21 AS full_window
    FROM variants v
    LEFT JOIN quant_app.prediction_targets t
      ON t.observation_id = v.observation_id AND t.horizon_sessions = 15
     AND t.target_version = 'stage2-shadow:net-excess-app-contract-v1:' || v.policy
)
SELECT policy, scale_high, threshold,
       count(*) AS passes,
       count(*) FILTER (WHERE recorded_action = 'Buy') AS recorded_buys,
       count(*) FILTER (WHERE buy) AS buys,
       count(*) FILTER (WHERE NOT fits_gate AND buy IS NOT NULL) AS wide,
       count(*) FILTER (WHERE fits_gate AND net_rr >= 1.30 AND NOT buy) AS score_watch,
       count(*) FILTER (WHERE buy AND net_return IS NOT NULL) AS buys_labelled,
       round(avg(excess_return) FILTER (WHERE buy)::numeric, 4) AS buy_avg_excess,
       round(avg(positive_excess::int) FILTER (WHERE buy)::numeric, 3) AS buy_win_rate,
       count(*) FILTER (WHERE buy AND full_window) AS buys_full_window,
       round(avg(excess_return) FILTER (WHERE buy AND full_window)::numeric, 4) AS full_buy_avg_excess,
       round(avg(excess_return) FILTER (WHERE NOT buy)::numeric, 4) AS watch_avg_excess,
       count(*) FILTER (WHERE buy IS NULL) AS unscorable
FROM acted
GROUP BY policy, scale_high, threshold
ORDER BY policy DESC, scale_high DESC, threshold DESC;
