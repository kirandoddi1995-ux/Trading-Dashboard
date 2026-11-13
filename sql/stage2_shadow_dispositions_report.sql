-- READ-ONLY report: why each scheduled Stage-2 shadow pass was or was not labelled
-- (equity_stage2_maturation.py, table quant_app.stage2_shadow_dispositions from
-- sql/stage2_shadow_dispositions.sql). Changes nothing.
--
-- Every Stage-2 shadow pass old enough to be selected (22 days, with entry, stop and target, as
-- the maturation's pending query) is counted, with or without a disposition row. One row per
-- disposition and state. The disposition is the last attempt's conclusion, except that a pass
-- with both shadow labels stored always counts as labelled (its last disposition write may have
-- been lost: the labels are the record), and a pass with no row is `no_record` (not attempted
-- yet: sessions still to complete or a full run; or its first write was lost). States:
--   final    = labelled under both policies;
--   excluded = its stock has an archived Bonus / Split / Rights Issue ex-dated after the decision
--              day and on or before today: the maturation's pending query leaves it out (as long as
--              that archived action stands);
--   expired  = not labelled under both policies and older than 60 days (IST date): no more retries;
--   retrying = otherwise: maturation tries it again on a later run.
-- decisions = shadow passes; attempts = runs that tried them; earlier_reasons = other conclusions
-- these passes had on earlier attempts (e.g. a touch-check rejection before a label), with counts;
-- examples = up to 20 passes, newest first: symbol, decision day, attempts, first message.
-- Label version net-excess-app-contract-v1 only.
WITH latest AS MATERIALIZED (
    SELECT o.observation_id, coalesce(d.reasons, '{}'::text[]) AS reasons,
           coalesce(d.attempts, 0) AS attempts, d.last_at,
           o.trading_symbol, o.as_of_date,
           d.detail->'messages'->>0 AS message,
           (SELECT count(DISTINCT t.target_version) FROM quant_app.prediction_targets t
            WHERE t.observation_id = o.observation_id
              AND t.target_version IN ('stage2-shadow:net-excess-app-contract-v1:incumbent-levels-v1',
                                       'stage2-shadow:net-excess-app-contract-v1:atr15-stop-v1')) = 2
               AS labelled,
           coalesce(d.disposition, 'no_record') AS last_disposition, o.instrument_key
    FROM quant_app.scanner_observations o
    LEFT JOIN quant_app.stage2_shadow_dispositions d
           ON d.observation_id = o.observation_id AND d.label_version = 'net-excess-app-contract-v1'
    WHERE o.strategy_version = 'equity-stage2-scheduled-shadow-v1' AND o.stage2_pass
      AND o.entry IS NOT NULL AND o.stop IS NOT NULL AND o.target IS NOT NULL
      AND o.as_of_date <= (now() AT TIME ZONE 'Asia/Kolkata')::date - 22
),
passes AS MATERIALIZED (
    SELECT l.*,
           CASE WHEN l.labelled THEN 'labelled' ELSE l.last_disposition END AS disposition,
           CASE WHEN l.labelled THEN 'final'
                WHEN EXISTS (SELECT 1 FROM quant_app.corporate_actions c
                             WHERE c.isin = split_part(l.instrument_key, '|', 2)
                               AND lower(trim(c.action_type)) IN ('bonus', 'split', 'rights issue')
                               AND c.ex_date > l.as_of_date
                               AND c.ex_date <= (now() AT TIME ZONE 'Asia/Kolkata')::date) THEN 'excluded'
                WHEN l.as_of_date < (now() AT TIME ZONE 'Asia/Kolkata')::date - 60 THEN 'expired'
                ELSE 'retrying' END AS state
    FROM latest l
),
groups AS (
    SELECT disposition, state, count(*) AS decisions, sum(attempts) AS attempts,
           min(as_of_date) AS first_decision_day, max(as_of_date) AS last_decision_day,
           max(last_at) AS last_attempt_at,
           (array_agg(trading_symbol || ' ' || as_of_date || ' x' || attempts
                      || coalesce(' - ' || message, '')
                      ORDER BY as_of_date DESC, trading_symbol))[1:20] AS examples
    FROM passes
    GROUP BY disposition, state
)
SELECT g.disposition, g.state, g.decisions, g.attempts, g.first_decision_day, g.last_decision_day,
       g.last_attempt_at,
       (SELECT string_agg(r.reason || ':' || r.n, ', ' ORDER BY r.n DESC, r.reason)
        FROM (SELECT u.reason, count(*) AS n
              FROM passes p CROSS JOIN LATERAL unnest(p.reasons) AS u(reason)
              WHERE p.disposition = g.disposition AND p.state = g.state AND u.reason <> g.disposition
              GROUP BY u.reason) r) AS earlier_reasons,
       g.examples
FROM groups g
ORDER BY (g.disposition = 'labelled') DESC, g.decisions DESC, g.disposition, g.state;
