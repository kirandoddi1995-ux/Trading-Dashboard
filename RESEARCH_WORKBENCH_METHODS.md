# Research workbench backend contract

This backend provides generated regression validation and a generated quote/cost
arithmetic rehearsal. It does **not** provide an admitted derivative backtest.
No real 2025/2026 data, credentials, source accounts, network requests, private
files, training activation, orders, or schedules are used. Integration into main's
UI, staged source closure and package manifests remains main's responsibility.

## UI API

```python
from research_workbench import catalog, run_generated, validate_report, compare_reports
state = catalog()                              # static; no fitting or source reads
report = run_generated("backtesting")         # ONLY inside explicit page button
models = run_generated("ml_models")           # same fixed experiment, different view
automation = run_generated("automation_reports")
checked = validate_report(report)              # Mapping or JSON bytes; defensive copy
comparison = compare_reports(report, report)   # descriptive only; no edge assertion
```

`frozen_baseline` is also supported. Every study uses the same generator and
model rather than retuning by view. `run_generated(study, now=None)` accepts an
aware datetime for clock tests; production UI must omit `now`. This local clock
injection is not an authorization boundary. `WorkbenchSpec` and
`run_synthetic(spec, now=...)` support bounded offline experiments; no real-input
argument exists. `guard_compute` rejects invalid bounds before reading source or
fitting, and rejects every day from 09:15:00 through 15:40:59 IST inclusive. The
every-day gate is conservative, not an exchange holiday calendar. Invalid input,
engine failures and blocked work raise `ResearchError`; UI must display a blocked
or failed state and must not manufacture a successful report.

`inspect_report` returns a validated defensive copy. `report_json` exports
canonical ASCII JSON bytes. All public report returns are typed `dict[str, Json]`.
`real_training_admission()` always returns `REAL_TRAINING_BLOCKED` and
`INSUFFICIENT_REAL_DATA`, including explicit independent-custody, licensing,
point-in-time, execution and study-review blockers. Caller flags cannot admit data.

## Envelope and evidence use

The v1 envelope contains `schema`, `status=SYNTHETIC_PLUMBING_ONLY`,
`synthetic=true`, `training_eligible=false`, `approval_authority=false`, `payload`
and `report_sha256`. Payload contains:

| Field | Meaning |
| --- | --- |
| `spec`, `assumptions` | Frozen study, grouping, purge/gap conventions, artificial label units and absent real costs |
| `identities` | Canonical spec/input/model hashes; hashes of explicit sibling code files and their aggregate |
| `validation` | Actual synthetic ridge/zero/mean/chance/rule losses, per-fold train/test/purged IDs, scaler, coefficients and predictions |
| `model_registry` | One in-memory synthetic model spec/trial; deployment disabled; importance `NOT_ESTABLISHED` with null values |
| `drift` | Fixed-bin descriptive Jensen–Shannon divergence; no alarm threshold or retraining authority |
| `generated_execution` | Explicit generated contract, bid/ask/depth/tariff inputs and the existing engine's decimal scenario result |
| `backtest` | Real results unavailable: null returns, Sharpe and net P&L, no fill evidence |
| `readiness` | Null real-session/label counts and missing instrument/cost/fill/liquidity/margin/license/PIT evidence matrix |
| `automation_report` | Manual generated run checks; no schedules, activation or deployment |
| `admission` | Real training blocked independently of synthetic fit success |

Generated quote scenario gross/net amounts are arithmetic on declared artificial
prices and tariff rates, **not fabricated historical P&L or an actual derivative
backtest**. The fictional source URLs and reference hashes are fixture labels,
not official records, licensing evidence or attestations. Risk evidence remains
missing. Backtesting UI must keep this section separate from regression losses
and real backtest results. Never relabel regression predictions as profits.

An evidence assistant may use `validate_report` output and cite paths such as
`payload.validation.metrics.ridge.mae`, but must preserve synthetic scope, units,
nulls and non-authority flags. No model API or retrieval is invoked here. Validation
proves internal coherence of this bounded fixture, not truth or source provenance.
SHA-256 is an identity/checksum, not a signature; anyone can recompute a checksum.

Import rejects oversized bytes (128 KiB), duplicate JSON keys, unknown/missing
nested fields, nonfinite/excessive numbers, booleans in numeric fields, excessive
depth/nodes/arrays/strings, modified authorities and unsupported claims. It verifies
fixture and model identities, exact causal folds, train-only scaler/intercept,
ridge normal equations, every prediction and baseline, derived losses, drift and
execution arithmetic. It does not refit a model, load data or read current source
files. Historical code identities are retained, not replaced with current hashes.

Comparison requires identical input identity, code identity and assumptions.
Changed seeds, periods, grouping/gap conventions or code make a comparison
incompatible and yield no deltas. Model alpha may differ for descriptive model
comparison on otherwise identical inputs. Compatible reports yield B-minus-A
loss differences only. There is no winner, p-value, confidence claim, Sharpe,
multiple-testing correction claim or statistical edge; `edge_status` always
remains `NOT_ESTABLISHED`.

## Methods and rationale

The actual public main checkout inspected was
`C:/Users/banga/AppData/Local/Temp/overnight-main-da4a9be`. Existing
`overnight_research_ml.chronological_folds` and `walk_forward_ridge` are reused
without changing their implementation. Defaults generate 12 daily 2022 sessions,
one row per session, two bounded causal features, one ridge alpha and eight
walk-forward tests. Limits are 6–24 sessions, seed 0–65535, alpha .01–100,
3 through sessions-minus-2 minimum training sessions and 0–86400 seconds gap.
The three-session lower bound leaves at least two training rows after the
previous-session lag dependency is purged; it is not a model retuning choice.
These are workload bounds, not adequacy thresholds for real research.

Signal and previous generated signal are features; a separate artificial label
becomes available after the decision and label end.
Each lagged row declares its feature history from the previous session's decision;
the first row uses a constant zero lag and a five-minute feature history. The
test row's previous-session dependency intersects that session's label interval,
so each fold purges the immediately preceding session (the default first fold
trains on three sessions and purges one).
All learned centering/scaling,
coefficients, means and baseline magnitudes use only training rows. The model is
registered before observations. Closed feature/label interval intersection,
labels unavailable at fit time and the pre-test time gap purge entire groups.
Whole IST sessions remain intact. Training is expanding and strictly past-only:
post-test embargo is vacuous because no future training rows exist. This is **not
CPCV**, random K-fold or a new implementation of embargo.

This choice follows the leakage concerns and purging/embargo distinctions in
Marcos López de Prado, *Advances in Financial Machine Learning*, Wiley (2018),
Chapters 7 and 12 ([publisher record](https://uat.store.wiley.com/en-us/advances-in-financial-machine-learning-p-9781119482109),
[Chapter 7](https://www.oreilly.com/library/view/advances-in-financial/9781119482086/c07.xhtml)).
Removing overlap is only one safeguard; it does not establish independence,
feature authenticity, label executability or profitable performance.

Bailey, Borwein, López de Prado and Zhu, *The Probability of Backtest Overfitting*
([author paper](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)) motivates
keeping model searches and comparative claims explicit. This workbench freezes
one small fit and records its baselines; its one-trial registry is in-memory, not
a complete durable ledger of the user's historical attempts. Repeated synthetic
fits cannot justify model selection or significance. No PBO or deflated-Sharpe
estimate is calculated on this fixture.

Hamilton, *Macroeconomic Regimes and Regime Shifts* (2016)
([NBER primary paper](https://www.nber.org/papers/w21863)) motivates treating
distribution change as a diagnostic with uncertain regime interpretation. Drift
here reuses `research_lab_statistics.histogram_drift`: three fixed signal bins
below -1/3, between the boundaries inclusive, and above 1/3; last-fold training
rows are the reference and its one test row is the current window. That tiny
current window is deliberately not an adequate drift alarm or regime estimator.
No bins, cutoff or parameters are selected using test labels. Coefficients appear
in fitted records, but correlated features and synthetic labels do not establish
causal or independently validated feature importance.

Frazzini, Israel and Moskowitz, *Trading Costs of Asset Pricing Anomalies*
([authors' working paper](https://pages.stern.nyu.edu/~afrazzin/pdf/Trading%20Cost%20of%20Asset%20Pricing%20Anomalies%20-%20Frazzini%2C%20Israel%20and%20Moskowitz.pdf))
supports distinguishing a price/cost calculation from executable profitability.
The rehearsal reuses `overnight_research_execution.round_trip_scenario` and
`intraday_fo_costs` for bid/ask, declared adverse ticks and exact decimal charge
arithmetic. Generated rates are explicitly artificial, not historical or current
NSE/broker tariffs. No real fee, liquidity or margin claim follows.

## Unsupported production mechanics and verification

Real market/ML use rights are unverified. Live F&O brokerage, contract/expiry/lot
changes, real depth, queue priority, partial fills, intrabar stops, expiry exercise,
rolls, short options, multi-order futures, exchange calendars and dated margin/
stress references are not commissioned by this chunk. Existing quote scenario
limitations still apply. No source rights or real-data custody are inferred from
public code availability. A successful generated test is not complete production
integration or permission to influence decisions.

Only the three owned files are authored. The source identity allowlist includes
this module, overnight dataset/ML/runner/execution/evidence/trials modules,
research lab statistics and intraday F&O costs. Each must be packaged alongside
the UI; tests perform no network, installs, hosted writes or real-data reads.

Verification commands (use an existing environment, no installs):

```text
python -m pytest -q -p no:cacheprovider tests/test_research_workbench.py
python -m mypy --strict --follow-imports=silent research_workbench.py tests/test_research_workbench.py
python -m mypy --strict --follow-imports=skip research_workbench.py
```

Silent import following preserves dependency types while restricting diagnostics
to the two new files; the existing research backend is not retuned or rewritten.
Tests cover generated fitting, deterministic reports, typed schema validation,
semantic and resealed tampering, inspection without fitting, market timing,
work limits, source-read boundaries, train-only causality and incompatible inputs.
