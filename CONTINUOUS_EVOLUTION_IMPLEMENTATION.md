# Quant Continuous Evolution — Production Contract

This release joins point-in-time evidence, production models, calibration,
uncertainty, execution realism, portfolio risk and operational safety into one
fail-closed recommendation contract. It does not claim that market prediction
can be guaranteed. The public label remains **99% not established** until the
independent evidence gate proves otherwise.

## One decision path

Every candidate must follow this exact path:

1. Validate source, availability and effective timestamps through the PIT firewall.
2. Route the approved market regime and load only signed ACTIVE/CHAMPION/PRODUCTION models.
3. Require an interpretable logistic or GAM baseline. Boosted models may join the
   constrained ensemble; deep temporal/order-book, options-surface and order-flow
   specialists remain SHADOW until independently promoted.
4. Validate the ensemble-linked calibration package from nested chronological
   development folds and an untouched holdout.
5. Validate reliability bins, finite Brier/log-loss/ECE metrics, validity dates,
   PSI, calibration decay and the chronological conformal interval.
6. Price target, stop, time-exit, partial-fill/non-fill, costs and adverse selection.
7. Require complete portfolio histories, stress scenarios, Expected Shortfall,
   marginal-risk, concentration and Greek limits before applying fractional Kelly.
8. Map every failure to the shared safety-state machine and append the compact,
   hashed decision bundle to the durable evidence ledger.

No downstream component may replace a failed or missing upstream result with a
zero, default probability, current timestamp or optimistic fill assumption.

## Configuration and enforcement

The approved thresholds live in `resilience_policy.json`; its SHA-256 sidecar is
verified at startup and in CI. Runtime build and policy hashes are compared on
every decision. A policy edit therefore requires review, a regenerated sidecar,
the full test suite, the credential-free game day and a signed deployment.

- `NORMAL`: every mandatory control passes; entries, exits and audit writes work.
- `DEGRADED`: non-trading telemetry is incomplete, but no mandatory decision
  evidence is missing. New trades are permitted only where the decision gate passes.
- `NO_TRADE`: stale/PIT-invalid data, model disagreement, invalid calibration,
  wide conformal uncertainty, non-positive executable EV, absent histories,
  stress breach or kill-switch condition. Exits and audit reads remain enabled.
- `READ_ONLY`: ledger/outbox durability, execution-state integrity, retention or
  recovery controls fail. New writes and entries stop; exits and audit reads remain.
- `EMERGENCY_STOP`: policy/runtime signature or ledger signature is invalid, or a
  secret value is exposed. Recovery requires authorization and clean hysteresis windows.

## Monitoring hooks

Each decision emits one correlation ID across `quant_control`, `safety_state` and
`predictive_claim` events. The immutable decision event records only statuses,
lineage hashes, model version, policy state and decision hash—never raw secrets.

Alert on any of the following:

- PIT coverage below 90%, future timestamps, stale features or schema mismatch.
- Model probability range above 0.15, missing baseline, regime mismatch, unsigned
  artifact, or a SHADOW specialist attempting to affect production.
- Calibration age above 30 days, ECE above 0.08, Brier deterioration above 0.05,
  log loss above 0.69, weak reliability-bin support or conformal coverage below 88%.
- Fill-model OOS samples below 500, fill ECE above 0.08, stale partial fills,
  negative fill-adjusted EV or execution slippage above policy.
- Missing aligned portfolio histories, Expected Shortfall/stress/MRC/concentration
  breach, outbox backlog, ledger verification failure or runtime-policy mismatch.

## Acceptance gates

CI blocks release unless all unit/adversarial tests, dependency preflight, package
audit, resilience game day, canary and package manifest verification pass. Model
promotion additionally requires signed artifacts, PIT verification, untouched
holdout, full executable costs, rollback availability and independent approval.

The 99% label is permitted only with all of these facts in immutable evidence:

- at least 1,000 matured actionable observations;
- candidate coverage of at least 5%;
- a 95% Wilson lower confidence bound of at least 0.99;
- at least 100 observations in each of at least three major regimes;
- untouched chronological holdout and verified PIT lineage;
- executable prices, full costs and a verified ledger.

Anything less must render **99% not established**. Test counts, rule scores,
historical win rates and calibration confidence are never substituted for that claim.

## Model-development adapters

Training jobs may use logistic/GAM baselines, monotonic or constrained boosted
trees, and deep temporal/order-book specialists, but must export the same evidence
contract: artifact hash/signature, feature-schema hash, training/calibration/holdout
windows, regime, deployment mode, OOS predictions, costs and rollback ID. This lets
new research evolve without bypassing the production control plane.

Deep and specialist models must first run in SHADOW, then PAPER and CANARY. Only an
independently attested promotion changes them to ACTIVE/CHAMPION/PRODUCTION. Their
weights must be non-negative, reviewed, and no single model may exceed 80% when an
ensemble has multiple members.

## Research-only option-surface features

The feature registry now defines unusual option volume/OI activity, near-money and
far-OTM put/call OI skew, IV term-structure steepness and IV skew steepness. These
features are deliberately disconnected from recommendation scoring, governance
gates, allocation and the scheduled live collector.

- Unusual activity is a contract-level median/MAD robust z-score over at least 20
  prior, PIT-valid observations from the same intraday capture context. A flat or
  incomplete baseline returns `UNAVAILABLE`; no fixed activity threshold is used.
- OI skew uses independently reported call and put open interest in absolute-delta
  buckets. Missing OI, zero-sided buckets, invalid IV rows or future availability
  timestamps return `UNAVAILABLE` or are rejected.
- IV term structure uses validated ATM executable-mid model IV across at least two
  expiries and is withheld when calendar total variance fails. IV skew uses the
  nearest-expiry validated OTM put/call wings and requires strike coverage on both
  sides of spot.
- Every publishable value goes through the existing versioned feature registry,
  quality monitor and prospective feature-observation store. Until a separately
  reviewed prospective option-surface archive accumulates real history, the
  unusual-activity feature correctly remains unavailable.

These fields are evidence for future chronological research only. They cannot
unlock trading, alter Kelly sizing or support a predictive-accuracy claim.
