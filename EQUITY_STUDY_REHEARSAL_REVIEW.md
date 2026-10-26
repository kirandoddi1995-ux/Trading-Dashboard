# Cash-equity report rehearsal and alert diagnostics — review-only source

Review base:08af92255714e8dfa02c4cc4d1ff49f9d1c7487f, after merged PR59.
No deployment, capture, credentials, schemas, tasks, release holds or orders change.

## Visible change, and its limit

Research→Backtesting adds Equity EOD Development Study — 2022–2024 above the
existing generated NIFTY workbench. Default: REAL STUDY NOT RUN, no replay on boot.
An explicit button generates four artificial three-bar execution examples at
30/60/100bps, showing exit/outcome/net-scenario rows, limitations, JSON download
and deterministic report hash. It uses the existing event_backtest engine unchanged.
All values are generated2022fixtures; no historical prices are loaded/fetched.
No scanner scores are invented or retuned: the fixture has one synthetic entry,
not a live scanner strategy. No real performance, portfolio return, model accuracy,
fill evidence or training/promotion eligibility is claimed. Never treat this
rehearsal as a real development report or accumulation of independent evidence.

Reports are accepted only when exactly equal to the regenerated fixed recipe,
including nested flags, dates and rows. Rehashing invented performance, deleting
rows or replacing false with numeric zero is rejected. This is synthetic-report
validation, not a data-rights or custody proof. Model fitting and real-input
admission remain unconnected. The old workbench remains available and labelled
separately; no existing page/score/risk formula is removed.

## What remains for the real cash-equity study

Permitted private2022–2024data and a frozen cohort; source manifests and quality;
corporate actions/universe/calendar/availability; dated fees and liquidity/fill
limitations; fixed existing rule versus comparable baselines; purged chronological
evaluation, uncertainty and complete trial accounting. Previously used years are
retrospective development, not newly unseen OOS. Historical2025/2026stay sealed.
Minute candles may reduce ambiguity but do not prove order/fill sequences inside
the same minute. Index-only forward capture cannot supply stock-level execution.
ATR/trailing/sizing/regime/news/model variants must be registered and compared
after the baseline, not added silently to make a backtest attractive.

The source is not a licence to download or redistribute data. No model, API key,
private loader, storage retention/deletion or workflow schedule is commissioned.

## Security diagnostic, not dismissal

dependency_alert_review.py reviews an explicitly supplied bounded GitHub REST
alert export offline. Default preview reads nothing; explicit --input absolute
--check reads at most2MiB. It validates required fields and groups advisory,
package, severity and manifest, rejects malformed/duplicate input, and exposes
no raw errors. Completeness attestation is only an owner claim. Empty or
owner-attested input never grants deployment approval. It performs no fetch,
login, dismissal, remediation or settings mutation. Location labels do not
prove a vulnerable dependency is absent from the resolved app environment.
Actual repository alert records were unavailable during implementation; counts
reported by the owner are NOT reconciled by synthetic tests of this tool.

## Tooling and source changes

New matching pandas2.3type stubs are development tools only. App runtime
requirements are unchanged; shared constraints now patch filelock3.32.4→4.2.1
after the expanded tooling audit identified CVE-2026-112940/112913/112907.
pip-audit's CacheControl[filecache] requires filelock>=3.8 with no<4bound; the
fixed package is within declared bounds. The dependency update is not an ignore
or removal from the audit. Existing historical predecessor bytes stay unchanged;
only the constraints successor digest and fixed transition-record hash advance.
That record's original563665abase still identifies its archived original blobs,
not the new package's08af922base. All other eleven test-file successor pins stay.
The actual installed-environment audit also exposed the bundled pip25.2 bootstrap
advisories, not seen in app-only requirements resolution. Both proposed CI
environments explicitly bootstrap pinned pip26.2.2; constraints and the new type
profile bind that version. An additional installed-environment audit keeps this
scope visible rather than excluding the installer. Original environments are
not upgraded in place; only fresh disposable verification environments changed.
The quality workflow adds their exact
tool-profile install in a separate venv, four strict source checks and a separate tool-profile audit;
all existing app audits, strict checks, full tests, release checks and runner
policy remain. No advisory ignore or type-error suppression is added.
The base check environment must not receive the stubs: their presence changes
two old import-typing assumptions and makes existing valid ignores appear unused.
Keep the old19-file checks in the base environment and the four new checks in
the isolated typing environment. Do not edit those old modules to hide this issue.

Existing modifications: app.py adds only the guarded equity panel and explanatory
caption in Backtesting; quality.yml adds the three mandatory steps above.
It also pins installer bootstrap and audits the installed base environment.
constraints.txt patches the audit-cache dependency; the regression-only transition
record/helper bind that approved successor, without changing old uploader gates.
New sources: equity_eod_study_design.py, equity_eod_study.py,
equity_eod_study_ui.py, dependency_alert_review.py; plus tests, strict type config,
tool profile and this review. event_backtest.py, scanner_composite_score,
RiskEngine, positions, capture code and historical upload pin contracts unchanged.

## Acceptance

Builder/independent source checks and native test counts are recorded separately
in the private handoff. Synthetic passing tests establish plumbing/invariants,
not market accuracy or alert exposure. The prior PR59full-suite pass is NOT a
full-suite result for this new source. Exact-base package check, focused tests,
complete source-bound Windows result with skip disposition, whole-profile audits
and exact-final-SHA hosted Quality/Resilience/CodeQL remain separate gates.
Owner alone commits/pushes/merges the reviewed package; no release promotion here.
