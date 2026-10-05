# Automation foundation — continuity record

## Mission and non-negotiable rules

Build automated backtesting/self-checking for a Streamlit NSE intraday NIFTY
futures/options decision-support app. Never place orders or invent evidence.
Missing evidence blocks; safety gates are not loosened. Local project is source
of truth. No hosted changes, GitHub writes, dispatches, data/history deletion,
credential output or copies of Documents/TradingResearch in the repository.
2025 validation and 2026 holdout remain unexamined. Automation never retunes.

Quality: focused typed/docstringed modules; deterministic offline failure-path
tests; full suite count cannot drop; clean lint and new-code type checks;
app/import check; final adversarial self-review and fix before reporting.
Update this file after each completed step and before stopping.

## Baseline / known constraints

- Owner reports main matches local, green CI; baseline 1,281 passed / 4 skipped.
- Equity fingerprint 2893995505709b1b6a6bfcea342a2edb3770319c695297234747cf1b6801c7b9.
- Supabase approximately 479/500 MB: this implementation makes ZERO DB writes.
- Upstox Plus, older futures depth, unattended token refresh unverified.
- Two directional rules parked; no new candidate selected or validated.
- Existing fees, futures probe and roll tools are research-only; complete dated
  costs/lot terms/deadlines are NOT commissioned.

## Reference review and independent decisions (completed)

Read all 255 lines of Automated backtesting and self checks.md. It is research
input, not authority to change hosted resources or loosen gates. Reuse existing
directional/cost diagnostics and extracted-release import verification.
Do not introduce a new engine/dependency framework, auto-unsealing, fixed-time
square-off, candle option fills, arbitrary promotion thresholds or database
storage. Do not use a report's theoretical statistical cutoffs as gate defaults.

Chosen first slice:
1. Typed development manifest/spec validation, append-only local registry/trial
   ledger and reproducible runner, with 2025/2026 unavailable by design.
2. Synthetic golden/invariant tests and credential-free import/type CI checks.
3. Owner runbook for consistent upload, release branch and external monitors.
Stop at this boundary: live forward integration/hosted commissioning need owner
decisions and actual market/cost evidence; do not enable them automatically.
The next purely local engine-wrapper step is still possible without owner
credentials; stopping this checkpoint does not mean the overall goal is done.

## Checkpoint 1 (completed)

First offline slice implemented: exact report/source/runtime fingerprints,
explicit registration, append-only serialized local attempts, sealed-period
checks, atomic non-overwriting result publication, deterministic repeated-result
checks, and CI import/type checks. No live application source changed.

Checkpoint verification COMPLETE:
- Full suite: 1,319 passed, 4 skipped, 2 subtests passed in 144.41 seconds.
  Baseline increased by 38; no tests removed or additional skips introduced.
- Focused synthetic suite: 38 passed.
- Full root/tests pyflakes: clean. Strict mypy: both new modules clean.
- pip check: no broken requirements. App import: APP_IMPORT_OK (bare-mode
  Streamlit warnings expected; not an authenticated UI test).
- environment_preflight --strict: pass.
- production_readiness --repository-only --strict: pass, not hosted readiness.
- deployment_canary: pass, including existing ZIP integrity.
- Recomputed equity hash unchanged:
  2893995505709b1b6a6bfcea342a2edb3770319c695297234747cf1b6801c7b9.
- Final main-agent review read all changed files. Fixed Windows rooted-path
  handling, atomic output publication, registration/terminal identity checks,
  and moved result-conflict enforcement inside the serialized ledger transaction.
  No outstanding defect identified in this bounded slice; not a guarantee of
  defect-free code or validation of the entire trading system.
- Synthetic fixtures only; no real replay or sealed data opened. No hosted
  actions, network data acquisition, credentials or production gates changed.

That checkpoint was ready for review/upload; its next engine-wrapper step is now
implemented in checkpoint 2 below. The overall programme remains partial.

## Checkpoint 2 (completed and verified)

Actual causal replay now runs through the shared recorded-trial lifecycle. Its
recipe freezes separate development-only bar/calendar hashes and the transitive
local import closure (reusing release dependency discovery). No strategy controls,
unseal flags, data acquisition, broker fills or genuine derivatives P&L added.
The first runner also now fingerprints its transitive implementation imports.
Old registered specs block on source drift; preserve them and register a separately
reviewed new version rather than overwriting history.

Focused checks: 68 tests passed (38 original foundation plus 30 new engine/workflow
tests). Includes a hand-derived reversal list, a reviewed full five-session
indicator-to-trade golden, full-session prefix invariance, missing/delayed bars,
explicit special/closed sessions, IST boundaries, forming bars, invalid OHLC,
sealed dates, contradictory eligibility and denied external I/O imports.
Final full suite: 1,354 passed, 4 skipped, 2 subtests passed in 146.89 seconds.
No tests removed and no additional skips; total +73 passing tests versus mission
baseline (includes the newly discovered workflow file in runtime-pin tests).
Strict mypy clean on three new modules; full root/tests pyflakes clean; pip check
clean. Independent app-import smoke: passed. External-I/O-denied imports include
all three new modules and passed in the full suite. Environment preflight,
repository-only readiness and deployment canary passed. Equity fingerprint
recomputed unchanged: 2893995505709b1b6a6bfcea342a2edb3770319c695297234747cf1b6801c7b9.

Final main-agent review inspected changed modules/tests/workflows/docs. Caught and
fixed sanitized CSV-parser failure handling and the existing runtime-pin test's
assumption that every workflow declares its own runner. Runtime checks now follow
reviewed local reusable calls (not exempt them), rejecting missing/cyclic/remote
targets. No outstanding defect identified in this slice; no whole-system or
live-broker correctness guarantee is claimed. No real/private replay files opened.

Opt-in research-self-check workflow calls the full existing quality gate rather
than maintaining a second test list. It passes no secrets, only contents:read,
bounded timeout and no overlapping scheduled/manual self-checks. Schedule remains
disabled unless OWNER sets AUTOMATED_SELF_CHECK_ENABLED=true. No hosted action
was made. GitHub workflow-call/secrets/concurrency syntax checked against official
documentation; local tests cover the configuration contract, not a hosted run.

## Changed files (one consistent upload; relative to project root)

- research_integrity.py — new typed manifest loader and local trial ledger.
- automated_development_checks.py — new frozen parked-report diagnostic runner.
- automated_directional_replay.py — frozen causal engine recipe/runner.
- research_replay_comparison.py — private research observations and exact replay
  comparison contract; no production capture hook.
- automation_health.py — explicit commissioning/heartbeat/release/clock contract;
  no network polling/notifications or automatic remediation.
- tests/test_research_automation.py — synthetic integrity/golden/failure tests.
- tests/test_automated_directional_replay.py — full-engine golden/causal checks.
- tests/test_research_replay_comparison.py — synthetic persistence/comparison checks.
- tests/test_automation_health.py — synthetic health-policy/completion checks.
- tests/test_workflow_runtimes.py — verifies runtime pins through local reusable
  workflow calls; rejects cycles, missing/unsafe or unreviewed remote targets.
- requirements-automation.txt — CI/local tooling only; not live dependencies.
- mypy-automation.ini — strict type check configuration for new modules.
- .github/workflows/quality.yml — adds tooling, type and offline import checks.
- .github/workflows/research-self-check.yml — opt-in reusable offline quality job.
- AUTOMATED_RESEARCH_RUNBOOK.md — owner commands and commissioning boundaries.
- AUTOMATION_PROGRESS.md — this continuity record.
- AUTOMATION_FOUNDATION_ACCEPTANCE.md — requirement evidence and uncommissioned
  boundaries; not a whole-system validity claim.

## Checkpoint 3 (completed and verified)

Forward contract now stores explicit research-only records with strict completed-
bar/aware timestamp identity and transactional idempotency/conflict handling.
Full expected-session comparison separates missing observations/replay, input or
basis differences, delayed availability and decision differences. Capture lag is
reported; no unvalidated delay tolerance or approval power added. Producer/input
archive is NOT wired; checksums alone cannot reconstruct data for replay.

Pure health contract distinguishes missing policy, expectation/observation,
not commissioned, awaiting deadline, missed completion and actual matching-run
completion. Explicit required lane scope prevents a selected healthy subset from
claiming whole-policy success. Self-review caught/fixed completion-before-deadline
semantics and expected-run receipt identity. No real reads or notifications.
Verification: 46 new tests passed; focused new/first-foundation selection 84 passed.
Final full suite: 1,400 passed, 4 skipped, 2 subtests passed in 145.45 seconds.
No removed tests or new skips. Strict mypy clean on five new modules; full
root/tests pyflakes clean; pip check clean; app-import smoke passed. Five-module
external-I/O-denied import check passed within the full suite. Environment
preflight, repository-only readiness and deployment canary passed.
Equity hash remains 2893995505709b1b6a6bfcea342a2edb3770319c695297234747cf1b6801c7b9.

Final main-agent review read changed code/tests/docs. Fixed receipt identity and
deadline semantics, explicit missing-lane scope, sanitized timestamp validation,
private-journal path guard, explicit stored research classification, and separate
available/unavailable match counts. No outstanding defect identified in this
bounded slice; no live correctness or whole-system validity guarantee.
No real datasets opened, no hosted operations, no app/production gate changes.

## Remaining after this slice

This is NOT the entire automated backtesting programme. Frozen report diagnostics
and underlying-bar execution/goldens now exist.
The timestamped observation/replay checker and health contracts are now built,
but NOT live wired. Next: actual supervised producer/input retention and independent
receipt/alert host commissioning. Do not wire production logging or network alerts without
the appropriate owner review. Keep both rules parked; do not invent/search rules.
Then commission actual dated futures costs/lot terms and expired-contract data
with owner evidence. Executable option replay needs recorded bid/ask evidence.
Live forward comparison, authenticated UI smoke testing, release-branch hosting,
external heartbeat/alerts and unattended auth require separate owner setup.
Do not introduce automatic promotion or unseal 2025/2026. See the runbook.
That next local step is now completed in checkpoint 4: recoverable private input
storage and replay-reference generation, deliberately NOT replay→observation
conversion. Do not treat these APIs as actual forward collection.

## Safe continuation

Read this record, acceptance inventory and runbook first; inspect the twenty-two-file manifest below end-to-end.
Do not mistake SUCCEEDED diagnostic computation for result-file publication or
tradable evidence. Source/runtime drift requires a separately reviewed spec.
Use a new pytest --basetemp directory and -p no:cacheprovider on Windows.
Set EQUITY_TEST_PGLITE_MODULE to the local SQL harness module for full coverage.

Full verification command used (from project root):
```powershell
$env:EQUITY_TEST_PGLITE_MODULE = Join-Path (Get-Location) 'tests/sql-harness/node_modules/@electric-sql/pglite'
$automationTestTemp = Join-Path $env:TEMP ('automation-full-' + [guid]::NewGuid().ToString('N'))
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp $automationTestTemp
```

Owner next steps: review/upload the twenty-two files together, wait for CI, optionally
prepare/review/register the existing private development report and compare two
diagnostic result hashes using AUTOMATED_RESEARCH_RUNBOOK.md. No Streamlit secret
update or database migration is needed. Do not upload private specs/results/ledger,
test temp data or tooling caches. No unattended research job has been enabled;
the new opt-in workflow requires the separate owner switch and contains no
private-data/network-market run. No actual real-data engine replay was executed.

## Checkpoint 4 — recoverable inputs and honest replay origin

Implemented bounded compressed content-addressed private inputs, exact-byte
deduplication, archive-only recovery and verified report/reference reproduction.
Shared the existing CSV/calendar decoder rather than duplicating logic; added
strict boolean warmup-reset validation. Underlying strategy math unchanged.
Comparison identity excludes full future dataset hashes while trial identity
still binds complete files. Prefix references include consumed history, previous
close, session rules and availability basis. Actual historical receipt time is
never invented. ReplayReference needs actual computation time when converted;
REPLAY rows cannot enter the OBSERVED journal or its side of a comparison.
CLI prepare/review/register/run/restore uses private paths, sanitized failures,
no overwrites, and explicit registration. No market network, DB, hosted writes,
real data access, automatic tuning or production safety changes.

Focused new archive/adapter tests: 24 passed. Strict mypy: seven modules clean.
Full suite: 1,424 passed, 4 unchanged skips, 2 subtests passed in 179.20 seconds.
Passing count +143 versus mission baseline; no removed tests or added skips.
Full root/tests pyflakes clean, seven-module strict mypy clean, pip check clean.
App-import smoke passed separately (1 passed) and in full suite; external-I/O-
denied seven-module import passed in full suite. Environment preflight, repository-
only readiness and deployment canary passed; these are NOT hosted commissioning.
Recomputed equity fingerprint unchanged:
2893995505709b1b6a6bfcea342a2edb3770319c695297234747cf1b6801c7b9.

Self-review addressed malformed recovery inventories, exact input lengths,
warmup boolean coercion and origin confusion. Archive recovery requires the
matching source/dependencies; a hash cannot restore implementation dependencies.
Main-agent final review covered changed code, tests, workflow/config and docs.
No outstanding defect identified in this bounded slice; this is not a guarantee
of defect-free software or live strategy validity. All tests used synthetic data.
Forward collection, actual point-in-time retention, live comparison, remote
completion/notification and authenticated UI drills remain uncommissioned.
This is a sensible local foundation boundary, not a completed live programme.

### Complete consistent upload manifest — twenty-two files

All paths relative to C:\Users\banga\Desktop\kiran_share_market:

Root Python:
- research_integrity.py
- automated_development_checks.py
- automated_directional_replay.py
- research_replay_comparison.py
- automation_health.py
- research_input_archive.py
- archived_directional_replay.py
- research_replay_check.py

Tests:
- tests/test_research_automation.py
- tests/test_automated_directional_replay.py
- tests/test_research_replay_comparison.py
- tests/test_automation_health.py
- tests/test_archived_directional_replay.py
- tests/test_research_replay_check.py
- tests/test_workflow_runtimes.py

Configuration/workflows:
- requirements-automation.txt
- mypy-automation.ini
- .github/workflows/quality.yml
- .github/workflows/research-self-check.yml

Documentation:
- AUTOMATED_RESEARCH_RUNBOOK.md
- AUTOMATION_FOUNDATION_ACCEPTANCE.md
- AUTOMATION_PROGRESS.md

Next: owner review/upload and optional explicit private development verification.
Do not commission a producer without deciding actual input provenance/persistence;
do not install live app hooks or remote alert delivery silently. Existing parked
rules remain parked. No Streamlit secret update is needed if fingerprint stays
unchanged. No database migration is included or required.

## Checkpoint 5 — integrated offline archive/replay self-check

Completion audit found a safe local integration gap between recovery and comparison;
implemented research_replay_check.py rather than requiring ad-hoc owner glue.
It reconstructs verified development archives and compares every accepted regular
session, preserving exclusions and full 75-decision denominators. Missing journals
are not created and cannot pass. Journal reads use SQLite mode=ro; existing empty
or invalid files are not initialized/repaired. Even full matches carry
live_capture_verified=false, approval_authority=false and fill_evidence=false.
CLI exit 0 for complete comparisons, 1 for missing/different evidence, 2 for blocked
integrity/read/publication. No output overwrite or automatic actions.

Focused integrated/journal tests first passed 34; final integration-only selection
passed 9 after adding explicit successful CLI exit coverage. Final full suite:
1,433 passed, 4 unchanged skips, 2 subtests passed in 173.13 seconds. Passing count
is +152 versus mission baseline; no removed tests or additional skips.
Full root/tests lint clean; eight-module strict mypy clean; pip check clean.
Separate app-import and eight-module external-I/O-denied import: 2 passed.
Environment preflight, repository-only readiness and deployment canary passed.
Equity fingerprint still 2893995505709b1b6a6bfcea342a2edb3770319c695297234747cf1b6801c7b9.
No real dataset, hosted resource, secret, schedule or live app change.
Self-review fixed journal initialization during checks; tests verify unchanged
file bytes and denied writes. Producer provenance and hosting remain uncommissioned.
Final main-agent self-review read integration code/tests, read-only journal path,
CI/type wiring and owner docs. No outstanding defect identified in this slice;
synthetic checks do not establish live correctness or economic edge.

Handoff boundary: twenty-two-file local foundation ready for owner review/upload.
The overall goal stays partial: true forward capture, dated cost/broker evidence,
OIDC UI verification and independent hosted completion/alerts remain unproved.
Do not claim these are running or broaden authority to commission them silently.
Next step requires owner review of producer provenance and persistent hosting,
or a separately authorized commissioning target. Preserve all sealed data and gates.

## Owner-boundary audit — first blocked observation

Re-read the current checkpoint 5 implementation and acceptance record after the
verified handoff. Previous turn was progress: integration, read-only protection,
tests and final verification changed authoritative state. No process is awaiting
polling. The local foundation is ready; broader live completion remains unproved.

The next required evidence cannot be produced by another synthetic test: owner
review/upload and hosted CI, genuine capture/input provenance, chosen persistent
host and privately configured authentication/notification destination. Current
authority prohibits hosted writes/dispatches and examining real 2025/2026 data.
Do not fabricate receipts, relabel replay as observations or mark the overall goal
complete. First consecutive owner-boundary observation; goal remains active.

Recommended next owner step: review/upload the complete twenty-two-file manifest
and report CI results. Then explicitly authorize a supervised forward-producer
commissioning scope with a chosen persistent private storage location/host; keep
historical validation/holdout sealed and do not send credentials through chat.
No application change or repeat of the full suite was warranted by this audit.

### Second consecutive owner-boundary observation

Previous turn was no progress toward live commissioning, not a verified wait:
it documented the boundary without implementing or verifying a new capability.
Revalidated the current opt-in workflow and commissioning runbook. They still
contain no market/DB secrets or live capture/alert wiring. No new owner evidence,
authorization or hosted completion receipt has arrived. The same owner-controlled
commissioning condition remains; no safe local check can manufacture that evidence.
Goal remains active pending the three-turn blocked audit threshold. No code,
settings, data or gate changes; latest verified test results remain unchanged.

### Third consecutive owner-boundary observation — goal blocked

Previous turn again made no commissioning progress and was not a verified wait.
Current files confirm the same gap: real capture provenance, persistent hosting,
privately configured auth/alert accounts and hosted verification are absent or
unverified. No owner authorization/evidence arrived. Existing local APIs and
synthetic results cannot prove these operational requirements. Further commissioning
would exceed the explicit local-only boundary; do not fabricate it or loosen gates.
The three-turn blocked threshold is met; mark the goal blocked, not complete.
No new application changes, data access or test rerun in this boundary audit.
Resume after owner review/upload/CI evidence and an explicitly authorized next
commissioning scope. Full twenty-two-file manifest, runbook and latest verification
(1,433 passed, 4 skipped, 2 subtests passed) remain the handoff source of truth.
