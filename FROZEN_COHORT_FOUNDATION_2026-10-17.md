# Frozen-cohort replay/evaluation adapter

`research_frozen_cohort.py` composes the pure APIs in `research_dataset_boundary`,
`quote_faithful_futures_replay` and `research_session_inference`. These are its
only project dependencies; all four use standard-library computation. No file,
data, network, task, model-fitting, activation or historical-unseal adapter exists.

Scope is deliberately modest: one frozen directional prediction and one matured
reference decision per trial/session, plus one candidate PAPER round-trip preflight.
Squared reference-direction error is the predeclared loss; it is NOT profit,
economic performance, executable PnL or the training pipeline's target-before-stop
label. The baseline is a supplied frozen direction, not a separately replayed
baseline portfolio. No bars, successful trades or paper profits are pooled into
performance. All sessions receive equal weight in the existing inference method.

Before outcomes, preserve `plan_sha256(plan)`. The plan declares ordered unique
trials/strategy hashes, common ordered session dates, source/study/baseline hashes,
partition and provenance. Its frozen time must precede the first session day.
Evaluation requires that exact pin. The trial × session Cartesian scope cannot
be reduced by omitting outcomes: every missing slot is emitted as NOT_REPORTED.
Duplicate or outside-family submissions are rejected, never silently discarded.

Each RUN cell supplies raw typed dataset evidence and replay inputs, not a claimed
successful child report. The adapter calls both real pure validators. Forecast,
study/source/provenance, prefix, session, direction, horizon and metadata timing
bindings are checked. Forecast, frozen paper decision and dataset decision use
the same cutoff; a forecast cannot claim a prefix received only afterward.
Preserve `decision_sha256(evidence)` at forecast time;
this envelope excludes future labels/quotes but binds the input prefix and
predeclared exit/cost/contract assumptions. Future quote/label outcomes are bound
separately by canonical input and child-manifest digests. None of these hashes
authenticate a timestamp, implemented strategy, licence, complete prefix or data.

Replay receives only quotes available at or before the supplied `evaluated_at`.
Future quote prices, depth and revisions are not consumed as current outcomes;
exit evidence still in the future retains NO_FILLS and blocks family inference.
The full supplied batch remains input-hash-bound, while replay's child digest
binds only the as-of-visible stream. The cutoff is a caller claim, not a live clock.

All declared trials, including UNRUN, FAILED, REJECTED, missing, dataset-withheld
and NO_FILLS, remain visible. A failed member is never assigned zero loss, a
fabricated fill or a substitute price. Inference requires every cell of every
trial to be complete and at least the existing 120 distinct sessions. Otherwise
no loss means, raw/adjusted p-values, ranking or successful-subset performance are
reported. Successful cells retain status and provenance hashes only. Conflicting
reference datasets or baseline directions for a common session reject the
conflicting complete cells; there is no trial-specific reference cherry-picking.

Complete families use the existing fixed five-session block sign flips, 999 draws,
seed 1729 and full-family Holm adjustment. Every trial's result remains present;
there is no best-trial selection. Symmetry/approximate block independence and
sample adequacy are not verified. A low p-value is not an admission or trading edge.

Limits: 16 trials, 2,000 session dates, 4,096 total trial/session slots; per cell
128 source versions, 256 quotes and 64 declared input events; 65,536 total source/
quote records, 16 MiB canonical supplied input and 8 MiB result manifest. Scalar
strings are bounded to 128 characters. Malformed nonfinite cells are retained as
REJECTED with explicitly absent input digests, never falsely hash-bound. Other
global ambiguity/resource violations raise fixed ValueError codes. Frozen result
objects and immutable canonical manifest bytes bind the full retained status grid,
child digests and inference. No data is stored by this module.
Every scalar is validated even after a nonfinite float is found. For byte-budget
accounting only, nonfinite floats receive explicit strict-JSON invalid-float tags;
the entire tagged cell counts toward the aggregate input-byte bound, but receives
no content digest. Those accounting tags are not accepted evidence or hashed
surrogates for invalid input.

Inputs remain SYNTHETIC or CALLER_UNAUTHENTICATED. Existing development/prospective
partition restrictions apply through the boundary; a caller cannot claim REAL.
All training, promotion, approval, authenticated-admission and selection flags
remain false even for complete statistically low-p families. PAPER pair preflight
is not real after-entry recovery. This adapter is neither a complete engine nor
licensed-real-data integration. Tests generate only 2022 toy reference/quote data.

## Remaining engine/model requirements (not implemented or commissioned)

- Authenticated licence, provenance, preregistration custody, complete PIT source
  prefix and actual strategy-code/forecast verification; hashes alone prove none.
- Multi-decision session aggregation, portfolio/contract-roll handling, partial
  fills, queue/impact realism and stateful after-entry failure/liquidation handling.
  The current candidate-only atomic pair is not an economic baseline comparison.
- Reviewed economic objectives/labels, costs and execution evidence; reference
  direction error must not be relabelled as executable PnL or model-training labels.
- Leakage-controlled model fitting/calibration, chronological whole-session
  evaluation, independent-session adequacy and explicit multiplicity/holdout policy.
  This adapter computes neither features nor models, and unlocks no sealed data.
- Separately reviewed real-data adapters, independent custody/restore and native
  operational acceptance before any integration. No acceptance is implied here.

These are separate prerequisites, not instructions or permission to activate them.
