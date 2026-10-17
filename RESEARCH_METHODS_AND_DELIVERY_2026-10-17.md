# Required ML and backtesting: methods, stages and honest reliance

This is a delivery contract, not a promise of positive returns. No real training,
market-data read, sealed-period examination, model download, broker request or
backend activation occurred. Synthetic loss scores used by tests are declared
arithmetic fixtures, not fabricated market sessions, prices, labels or P&L.

## What can be built now

Build the full research path while evidence accumulates. Rights/custody/labels
block real admission, not typed interfaces, algorithms, failure injection, report
replay or application integration. Research capability and production promotion
are separate. No count, signature, role or licence gate is lowered to show a result.
The following stages are ordered deliverables; after a stage passes engineering
acceptance the next is built without waiting for real-data thresholds.

1. **Session-level inference and complete trial accounting (built here).**
   `research_session_inference.infer` accepts a declared family and already
   computed paired session-mean losses, not price paths or data files. All planned
   trials must be present/completed on identical ordered dates. Otherwise it
   returns INSUFFICIENT_EVIDENCE with no p-values. All failed/unrun trials remain
   in the family; no quiet denominator shrinkage or post-hoc winner selection.
   Nonfinite/bool/negative losses, duplicate/out-of-order dates, inconsistent rows,
   undeclared trials and bound violations reject. It never fits, trades, registers
   a model, admits a study or chooses a winner.

   Equal weight goes to sessions, not correlated five-minute rows. Fixed groups
   of five ordered sessions receive shared random signs across all family members;
   a partial final block retains its actual session weight.999 seeded draws use
   `(1+exceedances)/(999+1)` and complete-family Holm-adjusted p-values. The declared
   minimum120 dates is a fixed engineering floor, not a proof of statistical power.
   Bounds:16 trials,2000 sessions/trial, loss magnitude at most1e12. Method, plan
   and supplied-input hashes bind the output. The plan is NOT an authenticated
   preregistration: a full study also needs objective/units, benchmark, data/version,
   cost, label, split, trial-log and code hashes retained before evaluation.

   Crucially: block-sign symmetry and approximate independence between blocks are
   assumptions NOT established by this function. Five sessions is not a universal
   autocorrelation cure. Bad raw tests are not repaired by Holm. Outputs remain
   METHOD_OUTPUT_UNADMITTED, assumptions_verified=false, training_eligible=false,
   approval_authority=false, promotable=false even for tiny p-values. No Sharpe,
   derivative P&L or trading edge is inferred. This is a shared evaluation component,
   not yet wired into the app, registry or scheduled runner.

2. **Admitted dataset and label adapter (next implementation).**
   Keep raw originals/actual receipts, event time, receive time, feature availability,
   revision ID and source/recipe hashes distinct. Select only versions available
   at the decision boundary. Freeze feature dependencies, including lag windows;
   purge their full spans, not just the nominal bar. Fit imputers/scalers only on
   train prefixes; no label-derived filtering, future universe, revised final bars
   or global normalization. Missing bars/quotes/labels stay missing, with reasons.

   An outcome label is append-only after its horizon is observable; retain label
   interval, actual availability, instrument, cost/execution policy and source
   references. Price-direction labels are reference labels, not fills or executable
   derivative returns. Owner-supplied data is not automatically licensed/admitted.
   The adapter must fail closed for insufficient quotes, unmatured outcomes,
   ambiguous paths, unavailable contracts, mismatched hashes and sealed partitions.
   No unseal flag or discovery of2025/2026 historical datasets. Prospective versioned
   captures after the existing admission start remain a distinct stream.

   Acceptance: synthetic causal prefix/revision/duplicate/gap/horizon tests,
   immutable relabel rejection, cross-file manifest mismatch, year-boundary guards,
   and exact schema/hash report replay on Windows/Linux. Then owner-authorized
   one-dataset admission review—not automatic fitting.

3. **NIFTY futures event replay and cost commissioning (required).**
   Start with one instrument/horizon and one pre-registered question, not an options
   strategy search. Use actual effective-dated contract/lot/tick/expiry/calendar,
   roll rules known at the time, bid/ask/depth and receive/decision latency. Buying
   pays ask and selling receives bid with separately declared adverse stress;
   insufficient depth or stale/crossed quotes are rejected, not optimistic fills.
   Five-minute OHLC cannot resolve whether both stop and target were touched first;
   report unresolved unless a pre-registered defensible path observation resolves it.
   Execution scenarios are counterfactual paper models, never evidence of real fills.

   Commission brokerage, STT, exchange, IPFT, SEBI, buy-side stamp and GST with
   retained source bytes/hash, publication/effective dates, reviewer/time and tax
   bases/rounding. Existing `fo_cost_commissioning` records remain UNREVIEWED until
   that evidence exists. Current fees must not be applied to2022–24. Unknown costs
   make net P&L unavailable; margin is collateral, not a maximum-loss estimate.
   Contract rollover must not turn a back-adjusted continuous price into a tradable
   fill. Keep index09:15–15:30 reference and segment/date-specific F&O close separate;
   this programme changes neither capture window nor live inputs.

   Acceptance: independent hand-calculated decimal fixtures, lot/expiry/calendar
   boundary tests, adverse spread/latency/depth, unknown cost/ambiguous bar failures,
   funding/margin/risk constraints and exact deterministic report replay. Only then
   a licensed development-only replay with an explicitly limited claim scope.

4. **Nested ML/calibration and untouched holdout adapter (required).**
   Reuse existing numpy/scikit-learn logistic, GAM and constrained boosted candidate
   implementations after auditing their actual PIT/contract compatibility. Retain
   frozen simple rules, no-skill/base-rate predictions and no-trade benchmarks.
   Fit parameters only under an owner-frozen recipe inside chronological outer
   training prefixes; use a separate calibration
   prefix with both outcome classes. Calibration never sees validation/holdout labels.
   Automation never changes rules, horizons, features, thresholds or the study
   recipe. Any candidate/hyperparameter family must be explicitly frozen and
   logged before evaluation; no autonomous optimizer or drift-triggered retuning.
   Purge overlapping feature/label intervals and embargo explicitly; grouping by
   whole date prevents same-session train/test leakage. Regime labels must themselves
   be causal; no future-defined volatility regimes.

   Use proper losses (Brier/log loss), reliability diagrams and uncertainty;
   accuracy alone and naive independent-bar standard errors are insufficient.
   Scikit-learn calibration defaults are not automatically purged time-series CV.
   Inspect class weights versus calibration prior; do not relabel balanced scores
   as calibrated deployment probabilities. Deep networks, RL and automatic feature
   searches are deferred until a justified sample and all-trial budget exist—not
   used to compensate for a few clean days. Missing features are not invented.

   Keep all existing readiness minima:1000 matured eligible observations,100 per
   class,120 dates,500 nested OOF,500 untouched holdout over20 dates, plus every
   quality/cost/quote/ledger/regime/calibration condition. These are lower bounds,
   not a guarantee they are jointly feasible at exactly1000 rows or120 days. The
   equity15-session target does not transfer unchanged to intraday NIFTY derivatives.
   Per-asset/horizon contracts and reviewers must approve a derivative-specific
   pipeline without silently weakening the existing equity contract.

   Acceptance: full-data refit leakage traps, train-only scalers, calibration-split
   labels hidden until evaluation, adversarial overlapping horizons, insufficient
   class/days, future revisions, baseline underperformance, all-trial reporting and
   fresh replay validation. A VALIDATED research result remains promotable:false.

5. **Frozen paper/forward comparison and monitoring (required).**
   Register signals as-of time before outcomes, track exclusions/missingness and
   decision coverage, and mature labels without retro-replay. Compare prospective
   paper assumptions with received executable quotes and explicitly unavailable
   actual-fill evidence. Separate data/source revision drift, feature drift,
   probability/calibration drift and economic performance; delayed labels prevent
   instant performance monitoring. Alarms report/abstain; automation never retunes.
   Research thresholds and monitor false-alarm budgets are preregistered, not picked
   after a drawdown. Require independent session-level evidence and real reconciliation
   before any trust;75 observations on one day are not75 independent trading days.

6. **Registry, automation and application completion (required).**
   Reproducible dataset/code/cost/contract/model/report hashes and an append-only
   complete trial ledger precede durable registry wiring. Keep candidate, champion,
   rollback, signature/key provenance, approvals, admission reasons and lineage.
   Local SQLite can be a development backend, not an ephemeral runner's durable
   production endpoint. Managed signing/two independent approvers stay mandatory;
   a local key or an AI vote is not a substitute. Read-only pages show real versus
   synthetic versus insufficient separately; no empty page displays invented zeros.

   Scheduled jobs stay inactive until approved; capture resources take precedence.
   Bound runtime/CPU/disk/memory and stop without partial promotion. Reports record
   every trial including negative/error/unrun entries; a growing hidden search log
   invalidates selection claims. Promotion and live training need explicit human
   commissioning, not a green offline suite.

## Shortest credible real-evidence path and owner dependencies

Obtain explicit permitted-use terms covering collection, retention/backup,
derived labels, personal prospective paper speculation/research, ML and any data
submission to an LLM. Broker access and owning a CSV do not establish those rights.
NSE's no-cost research provisions exclude commercial/speculative/investigative
purposes in the published disclaimer; do not assume this project's eventual use
qualifies. Ask the provider for the intended-use answer, privately retain it and
the reviewed admission record. No legal clearance is asserted here.

First authenticated one-session NIFTY history check remains NOT VERIFIED. After
rights and zero-cost entitlement confirmation, use one approved2022–24 development
date through the existing bounded history tool; retain original receipt/hash and
metadata, then reconcile timestamps, duplicate/gap counts and75 expected index bars
against the dated contract. No bulk run, paid expired-contract upgrade or2025/2026
historical query. History obtained today proves final-history contents, not past
decision availability. Candle-only history cannot supply absent derivative quotes.

The old bulk CLI default extended into2026. This package removes implicit start/end
and rejects sealed-year check/range requests before credentials, network or cached
prices; it also rejects a sealed-year session-check receipt before opening that
receipt's cached candles. No unseal switch is added. Pure parsing/acquisition
library APIs are unchanged; they are NOT a separate admission path for arbitrary
callers. Future sealed evaluation needs its own frozen-study review, not this
development downloader. Explicit daily pre2022 warmup, if legitimately permitted,
remains context and must not enter the scored development/ML cohort.

Prospective licensed futures quotes/contract records are the preferable next data
addition if permitted and storage/custody admit it. Existing index capture stays
unchanged. Option surface replay waits on licensed strike/expiry quote histories;
Greek/pricing diagnostics are not fills. Free bhavcopies are EOD reference/settlement
checks, not intraday order books. Existing failed development benchmarks stay failed;
freeze a new question, hypotheses, rules and hashes before any sealed evaluation.

LLM: retain deterministic Evidence Assistant first, with exact cited records,
read-only scope and no invented numbers. No remote free-tier upload of private or
licensed records without explicit rights/consent. Hardware is uninspected, so no
local model is selected/downloaded. A local backend later needs model licence,
CPU/RAM/resource rehearsal and adversarial faithfulness tests; it never calculates
or approves a trading decision. Model licensing is separate from data licensing.

## Study record: primary sources and decisions

Researched17Oct2026; no source page is being treated as an empirical trading edge.

- [Cawley and Talbot2010](https://jmlr.org/papers/v11/cawley10a.html): model-selection
  variance can overfit evaluation. Adopt nested chronological evaluation and all-trial
  reporting; reject reporting only the best synthetic fit.
- [Holm1979, original paper](https://www.ime.usp.br/~abe/lista/pdf4R8xPVzCnX.pdf):
  adopt complete-family monotone step-down p-value correction. It needs valid raw
  tests; it does not repair missing trials or invalid dependence assumptions.
- [Phipson and Smyth2010](https://pubmed.ncbi.nlm.nih.gov/21044043/):
  use the plus-one Monte Carlo convention rather than report a sampled zero p-value.
- [Bailey et al., backtest overfitting](https://sdm.lbl.gov/oapapers/ssrn-id2507040-bailey.pdf):
  retain selection-bias and overfitting audits. PBO/deflated-Sharpe diagnostics
  supplement a frozen study, not substitute for executable labels or real holdout.
- [Guo et al.2017](https://proceedings.mlr.press/v70/guo17a.html) and
  [scikit-learn calibration](https://scikit-learn.org/stable/modules/calibration.html):
  measure probability reliability and fit calibration independently. Do not infer
  neural networks are appropriate for this tiny, correlated dataset or transfer a
  calibration result from nonfinancial benchmarks as market evidence.
- [NSE policy](https://www.nseindia.com/static/market-data/nse-data-policy),
  [disclaimer](https://www.nseindia.com/static/nse-disclaimer),
  [research access](https://www.nseindia.com/static/research/research-initiatives):
  free availability is not general speculative-use or redistribution permission.
- [Upstox historyV3](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/)
  and [expired instruments](https://upstox.com/developer/api-documentation/expired-instruments/):
  investigate endpoint/entitlement separately from rights. No endpoint was called.
  [Official expired-API announcement](https://upstox.com/developer/api-documentation/announcements/expired-instruments-api/)
  identifies Plus access; no upgrade or zero-cost assumption is authorized here.
- [NSE STT circular](https://nsearchives.nseindia.com/content/circulars/FATAX73524.pdf):
  tariff effective dates matter; it is not a complete commissionable cost ledger.
  Source byte retention/hash and independent component review remain pending.

These engineering deliverables do not require extra paid tools. Existing sklearn,
numpy, stdlib and optional already-reviewed Arrow/Parquet support are adequate for
the first honest pipeline. New dependencies/models/agents must solve a demonstrated
problem, not make an evidence-insufficient dashboard appear advanced.
