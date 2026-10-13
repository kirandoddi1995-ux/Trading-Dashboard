# Inactive version-aware research engineering — 2026-10-13

## Scope and exact new files

Local source only. No credentials, installed capture, real research datasets,
sealed historical data, hosted activation, model promotion or broker orders were
accessed. Existing code and requirements are unchanged. No package/release manifest
is commissioned here; consolidation and the reviewed upload checker are listed
in OVERNIGHT_UPLOAD_ORDER_2026-10-13.md.

The engineering stream created these 17 files; the final upload group adds its
fixed checker and JSON manifest (19 files total):

- `overnight_research_dataset.py`
- `overnight_research_execution.py`
- `overnight_research_ml.py`
- `overnight_research_evidence.py`
- `overnight_research_runner.py`
- `overnight_research_trials.py`
- `overnight_research_paper.py`
- `tests/test_overnight_research_dataset.py`
- `tests/test_overnight_research_execution.py`
- `tests/test_overnight_research_ml.py`
- `tests/test_overnight_research_evidence.py`
- `tests/test_overnight_research_runner.py`
- `tests/test_overnight_research_trials.py`
- `tests/test_overnight_research_paper.py`
- `requirements-overnight-research.txt`
- `.github/workflows/overnight-research-offline.yml`
- `OVERNIGHT_RESEARCH_2026-10-13.md`

## Executable foundation

The runner executes verified bundle projection, logical dataset manifest creation,
quote/cost scenarios, grouped chronological purging, train-only standardization and
deterministic ridge fitting, trial recording and paper evidence gating. Its CLI
accepts only synthetic self-check or installed-environment verification commands.
The self-check uses generated 2022 candles and arbitrary synthetic regression test
targets. Those targets are neither market returns nor executable profit labels.
The returned scenario is insufficient without quotes/contracts/cost inputs, and
the paper gate stays blocked. There is no data-path argument or dataset discovery.

Capture versions are explicit actual identifiers such as `nifty-forward-v1`,
bound to exact recipe and producer source hashes. Programme item letters I–M are
not capture versions. Default `DEVELOPMENT_ONLY` accepts 2022–24 observations.
Explicit `PROSPECTIVE_VERSIONED` accepts only the supported versioned capture
envelope with sessions on/after 2026-10-13 and full existing recipe/source replay.
2025 and earlier 2026 historical inputs stay sealed. Metadata registration,
listing and policy-review timestamps have separate aware-time checks. Structural
replay does not authenticate provider receipts or grant source admission.

Rows preserve missing/blocked/warmup states and actual computation availability.
Later revisions cannot rewrite earlier projected observations. No missing poll is
invented and no outcome claim creates a usable label. The dataset manifest is a
logical in-memory manifest, not a package manifest. Optional Arrow exports are
in-memory Parquet bytes with an explicit schema, UTC timestamp and bound manifest
metadata. Missing backend or mismatched manifest fails closed without installing.

Execution requires an explicit derivative contract, expiry, tick and lot inputs,
listed/known timestamps, reviewed deadline, whole-lot quantity, positive aligned
bid/ask quotes, causal exchange/receipt times and sufficient visible side depth.
Pricing uses ask on buys and bid on sells with declared adverse tick stress.
Fees delegate to `intraday_fo_costs.round_trip` using supplied dated exact-decimal
policies. No real rates are invented. Unknown opportunities stay in the denominator
and never become losses. Queue priority, actual fills, partial fills, intrabar
stops, short options, exercise, funding and multi-order futures remain unsupported.

ML folds keep variants sharing a decision in the same group, reject duplicate
identity and purge overlapping closed feature/label intervals and unavailable
training labels. No future train rows are used; the pre-test gap is explicit.
A post-test embargo is vacuous for this strictly prior-only walk-forward design;
this code does not implement CPCV. Ridge uses a positive frozen alpha, a train-only
standardizer and deterministic stdlib linear algebra. Evaluation includes zero,
train-mean, seeded chance and simple first-feature sign baselines. Synthetic
metrics exercise machinery only and are not reported as trading performance.

The explicit session_groups mode, propagated through runner and fitter, groups
all observations by their actual IST session date. Its minimum/test group counts
then count sessions, not five-minute decisions. Whole train sessions are purged
when any member overlaps a test information interval. A one-day fixture retains
an INSUFFICIENT_DATA trial rather than fitting under this mode. The default
decision-group mode remains only the synthetic plumbing demonstration; a future
real-data admission adapter must bind a preregistered session split/adequacy policy
before allowing economic evaluation. Neither mode creates authentic outcomes.

The private future-owner SQLite trial ledger is append-only and hash chained.
STARTED records precede execution; completed, failed and insufficient attempts
remain distinct. Restart exposes unfinished attempts without rerunning or
inventing completion. Missing/corrupt ledgers are not repaired automatically.
Private-path ownership, backups and independent custody are still needed; a hash
chain in an owner-controlled database is not an external attestation service.

Forward paper diagnostics bind a pre-emitted intent and frozen protocol to later
observable contract quotes. Missing outcomes stay missing. They do not produce
TARGET/STOP labels, fill evidence or permission to paper trade. Evidence reports
must bind dataset/model identities, declared use rights, preregistered adequacy,
PIT/contract/cost audits, all trials and a paper stop/logging protocol. Even complete
caller reports are pending independent review rather than self-commissioning.

## Verification

The main project isolated environment matches the pinned profile: Python 3.13.9,
NumPy 2.4.6, pandas 2.3.3, Arrow 24.0.0, pytest 9.1.1, mypy 2.4.0, pyflakes 3.2.0
and tzdata 2026.3. The environment check returned PINNED_ENVIRONMENT_VERIFIED,
with no installation or download. This supersedes the earlier parallel agent's
different environment. Real Parquet round-trip checks run on these pinned versions.
Final combined checks and counts are recorded in OVERNIGHT_PROGRAMME_2026-10-13.md.

The inactive workflow uses a standard GitHub-hosted public-repository runner,
not a self-hosted machine. It runs only generated synthetic fixtures, without
credentials, private data or uploaded artifacts. Schedule execution requires
an explicit variable; absent/false means skipped. Manual execution requires
RUN_SYNTHETIC_ONLY. Do not enable it during upload. Public standard runner usage
is free under [GitHub's runner policy](https://docs.github.com/en/actions/reference/runners/github-hosted-runners);
private-repository or billing changes require a fresh review. A public-repository
self-hosted runner is avoided because of [GitHub's security guidance](https://docs.github.com/en/actions/reference/security/secure-use).
The workflow preserves the repository-wide Python 3.13 selector. Local verification
used 3.13.9; CI may resolve a newer 3.13 patch. Its environment receipt checks the
3.13 minor and exact package versions, not an exact Python patch. Reproducible
research manifests must retain the actual patch version used for each future run.

## Remaining engineering and real external prerequisites

Completed source remains inactive. Independent source/licensing admission and a
verified label adapter are not implemented by this foundation: the main agent
owns that boundary. Real-data fitting therefore returns an explicit pending
admission status rather than converting a caller boolean into training evidence.
The future admission adapter must verify bytes/custody, actual receipt clocks,
permitted ML/speculative use, contract/quote/depth evidence, calendar and dated
tariff references, and preregistered adequate out-of-sample sessions. A few days
of forward observations are not demonstrated adequate data.

No real contract master, broker margin reference, funded risk plan or executable
return series is present. No realistic full execution engine or profitability
claim follows from the scenario functions. The workflow is source only, defaults
off, and has not been published, enabled or run on hosted resources. A real private
dataset scheduler requires a separately reviewed owner host and licence boundary.

PBO/DSR, statistical significance and strategy selection across a real trial
population have not been calculated. They require real independently admitted
returns, sample assumptions and the full tried-strategy population. The registry
preserves attempts needed for that later analysis; it does not certify significance.

## Primary research URLs and design consequences

- [Apache Parquet metadata](https://parquet.apache.org/docs/file-format/metadata/)
  and [Arrow Parquet documentation](https://arrow.apache.org/docs/python/parquet.html):
  explicit schema/metadata and actual byte round-trip verification.
- [Feast point-in-time joins](https://docs.feast.dev/getting-started/concepts/point-in-time-joins):
  event-time selection alone can admit late corrections; constrain creation/receipt
  availability as well. This code uses actual received prefixes and computation time.
- [scikit-learn TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html):
  ordered evaluation and gaps; a row-count gap alone does not solve variable label
  horizon leakage. The custom folds purge actual closed information intervals.
- [Hudson & Thames mlfinlab cross-validation implementation](https://random-docs.readthedocs.io/en/latest/implementations/cross_validation.html):
  primary implementation documentation of purging/embargo based on López de Prado,
  *Advances in Financial Machine Learning*, Chapters 7 and 12. It is an implementation
  reference, not presented as an original journal paper.
- [Bailey et al., The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf):
  multiple strategy trials and selection affect apparent performance; preserve
  failed/unresolved attempts rather than keeping only the selected winner.
- [Bailey and López de Prado, The Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf):
  selection and non-normal returns affect Sharpe significance; a synthetic fit does
  not support a Sharpe or DSR claim.
- [Dwork et al., Generalization in Adaptive Data Analysis and Holdout Reuse](https://arxiv.org/abs/1506.02629):
  adaptive reuse of evaluation data changes generalization guarantees; freeze
  recipe/parameters before observations and retain every trial.
- [QuantConnect future fill model](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/trade-fills/supported-models/future-model):
  side-specific quotes, slippage and stale/order-time guards inform conservative
  quote scenarios. A quoted price is not a real fill.
- [NSE contract specifications](https://www.nseindia.com/static/products-services/equity-derivatives-contract-specifications)
  and [NSE contract information](https://www.nseindia.com/static/products-services/equity-derivatives-contract-information):
  expiry/lot/tick must come from dated instrument-specific references and the daily
  contract master, not a fixed current 75/65 or weekday assumption. No master was downloaded.
- [Current statutory STT Section 98](https://www.incometaxindia.gov.in/w/section-98-55):
  the current table lists futures sale STT of 0.05% and option sale STT of 0.15%.
  Current values are not automatically back-applied to old scenarios. The enacted
  section is preferred to a Finance Bill proposal; other fees still need dated proofs.
- [NSE disclaimer](https://www.nseindia.com/static/nse-disclaimer): free research-oriented
  access excludes commercial/speculative/investigative purposes, has an aggregate
  2GB threshold and institution/access conditions. A free download is not approval
  for speculative ML use.
- [NSE Data Sharing & Usage Policy](https://www.nseindia.com/static/market-data/nse-data-policy):
  intended use and end-user restrictions belong in relevant agreements; redistribution
  is not permitted except as agreed. Main agent owns the source report/ingest admission.
