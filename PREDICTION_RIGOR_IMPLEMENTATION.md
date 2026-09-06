# Prediction Rigor Implementation Contract

This release adds causal replay, volatility clustering, nightly probability
validation, a complete decision/outcome record, and constrained stacking. It
does not claim predictive correctness until prospective, matured evidence passes
the existing promotion gates. Missing evidence remains `INSUFFICIENT_EVIDENCE`
and cannot unlock live trading.

## Canonical Kelly sizing

For a trade risking `L` to gain `G`, the decimal payoff ratio is `b = G / L`.
For calibrated win probability `p` and `q = 1 - p`, the full Kelly fraction is:

`f* = (b*p - q)/b = p - q/b = (p*G - q*L)/G`.

The rejected expression `p/L - q/G = (p*G - q*L)/(L*G)` contains an extra
division by `L`, so it is not the standard dimensionless bankroll fraction.
All production consumers call `quant_foundation.fractional_kelly_weight`.
An architecture test rejects another Kelly-named function or inline Kelly
arithmetic outside that canonical module.

## Probability acceptance

The old absolute holdout rule `log loss <= 0.69` has been removed. A candidate
must now meet all existing Brier, calibration and chronology controls and also:

- improve holdout log loss by at least 1% relative to a constant base-rate model;
- use a base rate estimated from the development window, never the holdout;
- have a positive lower bound from a one-sided 95% paired moving-block bootstrap
  of per-observation log-loss improvement.

This blocks a near-coin-flip model whose tiny apparent advantage is sampling
noise. The paired block bootstrap preserves short-range temporal dependence
better than an independent-observation bootstrap.

## Event-driven backtest

`event_backtest.py` replays immutable, timezone-aware OHLC events. Signals see
only completed history, orders fill no earlier than the next event, bracket
levels use the actual fill, costs are charged, and every signal/order/fill/exit
is retained. When a stop and target both touch inside one OHLC bar, the engine
uses a conservative stop-first rule. This is an auditable bar-event simulator,
not an exchange queue or market-impact simulator.

## Volatility clustering

`volatility_models.py` fits a Student-t GARCH(1,1) by constrained maximum
likelihood and validates stationarity plus standardized-residual diagnostics.
There is no constant or heuristic fallback. Invalid or insufficient evidence
returns `UNAVAILABLE`/`ABSTAIN`. The forecast is shadow risk evidence and is not
eligible to influence production scores without prospective validation and
promotion.

## Nightly probability models and stacking

The weekday post-close readiness workflow re-checks immutable matured evidence.
When sufficient, `model_training_pipeline.py` performs chronological folds,
separate calibration, and an untouched holdout. Logistic, GAM and monotonic
boosted probabilities are combined by a non-negative, sum-to-one log-loss
stacker, then calibrated. The output remains non-promotable until signed artifact
creation, durable registration and protected human approval complete.

## Complete track record

`track_record.py` and the Evidence Readiness UI retain every supplied Buy, Watch
and No Trade decision, including losses, invalid matured outcomes and pending
outcomes. Counts and denominators are explicit. Overlapping decision returns are
not misrepresented as a portfolio equity curve. Broker fill-quality statistics
remain unavailable until real order and fill events are durably linked.

## Monitoring and fail-closed behavior

Monitor event chronology violations, rejected/cancelled orders, GARCH fit and
diagnostic status, Brier/ECE/log-loss skill, bootstrap lower bounds, stack
weights, losses, pending-outcome age and ledger integrity. Any missing required
evidence keeps the affected model or trading path unavailable. The public claim
continues to be **99% not established** until independently demonstrated by the
existing prospective evidence contract.
