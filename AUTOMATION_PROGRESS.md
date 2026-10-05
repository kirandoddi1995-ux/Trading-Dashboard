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

## Authorized continuation — private development export / forward producer

Owner evidence clears the earlier local-work boundary: all twenty-two files are
uploaded to main 2866faf with green CI; manual Offline research and application
self-check #1 passed in 4m22. AUTOMATED_SELF_CHECK_ENABLED remains absent. The
owner verified report SHA 57e429252a3510d8eb7e8b95f4e184dfca9b331ef35fc9fcf8bc7ad11333500a,
registered spec 1aaddcb4f3fa79c46834a49ff9de039eb5fe96b07914eaab8a09ce3405e95a79,
and twice obtained result 7895d7ac87ddd3d82c84509323a90f66892287fc5d294327ba4684f0e1e36bfc.
These are owner-reported observations; no hosted query/dispatch was performed.
New explicit authority: build local development export and forward producer.
Existing local-only rules, sealed historical partitions and no-retuning apply.

Decisions:
- Private Drive for immutable verified input/journal backups, durable local disk
  for the running producer. No Supabase, public artifacts or repository datasets.
- Offline development export first; prospective supervised capture second; durable
  host and independent missed-run alert commissioning remain owner steps.
- Fixed current-day NIFTY five-minute REST GET avoids a second websocket connection.
  Actual first receipt and computation are recorded, never backdated. Only newest
  completed bar emits; earlier downloaded bars are context, not past decisions.
- Producer uses explicit conservative daily reset/60-bar warmup. This is a distinct
  diagnostic policy, not an unnoticed replacement for frozen multi-session replay.
- Current official Upstox docs distinguish no-static-IP market/history access from
  static-IP account/portfolio access. One-year Analytics Token endpoint capability
  still needs owner supervised verification. No automatic auth refresh assumed.
- Reuse drive.file OAuth transport/folder; owner must verify privacy and app-specific
  folder visibility. Single immutable context/journal JSON-gzip logical backup,
  capped 2 MiB packed / 8 MiB expanded. No remote deletion or retention changes.

Implementation:
export_development_inputs.py streams only development numeric rows, preserves
special/incomplete sessions, verifies original frozen hashes/coverage and rehashes
sources before publishing a completion manifest. Mixed source bytes are hashed
without scoring later prices; no actual private dataset was opened by the agent.
forward_nifty_producer.py freezes code/calendar/previous-close identity, commits
first-seen input locally before decisions, rejects revisions/overlap, and retains
missing evidence. Stale crash locks require owner confirmation before clearing.
forward_nifty_job.py offers offline prepare/preview, explicit supervised one-poll
capture, clock/auth/licence gates and backup-only retry with sanitized failure
receipts. No timer or automatic collection is enabled.
forward_nifty_archive.py verifies exact downloaded data/manifest, reproduces actual
recorded prefixes and restores logical input/journal state to a new private folder.
Missing decisions are not reconstructed or counted as completed observations.

Current upload batch (all paths relative to C:\Users\banga\Desktop\kiran_share_market):
Root: export_development_inputs.py; forward_nifty_producer.py;
forward_nifty_archive.py; forward_nifty_job.py; mypy-automation.ini;
FORWARD_DATA_RUNBOOK.md; AUTOMATED_RESEARCH_RUNBOOK.md;
AUTOMATION_FOUNDATION_ACCEPTANCE.md; AUTOMATION_PROGRESS.md.
Tests: tests/test_export_development_inputs.py; tests/test_forward_nifty_producer.py;
tests/test_research_automation.py.
Workflow: .github/workflows/quality.yml.
Thirteen files, no requirements changes, no live app/imported production source changes.
No upload or hosted action performed. Keep tests under tests/, not repository root.

Verification in progress: first full suite 1,485 passed / 4 skipped / 2 subtests;
subsequent focused slice 58 passed including denied-I/O import. Self-review then
added malformed-expiry AUTH_REQUIRED handling and retry/size/computation tests;
final full rerun pending. Strict mypy twelve sources and full lint passed before
those last changes; must rerun. Initial targeted run's default pytest temporary
cleanup hit a pre-existing Windows ACL error; dedicated unique --basetemp avoids
that without changing any old directory permissions or deleting prior test state.

Next: final lint/types/full offline suite and app boot; verify unchanged equity
fingerprint; record results and hand off. No real validation/holdout read, token
read, real producer run, Drive upload, database change or schedule enablement.
Owner steps after review/CI: private offline development export, freeze/review
recipe, verify licence/token/folder/clock, supervised capture and backup restore
drill. Persistent hosting/auth/independent alerts remain uncommissioned. Programme
is partial; do not mark goal complete or claim genuine forward capture verified.

### Final verification / review boundary

Final frozen-source full suite: 1,490 passed, 4 unchanged skips, 2 subtests passed
in 190.47 seconds, including SQL PGlite safety tests, app import and external-I/O-
denied imports of all twelve foundation modules. +57 passing tests over the prior
1,433 handoff; no removed tests. Full root/tests pyflakes and strict mypy across
twelve source modules passed. pip check passed. Equity fingerprint verified
unchanged: 2893995505709b1b6a6bfcea342a2edb3770319c695297234747cf1b6801c7b9.
No Streamlit secret/fingerprint update is required for this thirteen-file batch.

Final main-agent self-review covered source/data boundaries, timestamp causality,
restart/idempotency, missing versus unavailable decisions, prefix reconstruction
after late backfill, exclusive writer ownership, restore completion markers,
credential sanitization, transport bounds, CI/type wiring and commissioning docs.
Fixed datetime/context-manager shadowing, current calendar selection, source-change
during export detection, original-prefix filtering after late context arrival,
malformed expiry reporting and backup-only authentication independence. No known
outstanding defect identified in this scoped slice; this is not a claim that
synthetic tests verify live Upstox behaviour, provenance, licence or economic edge.

Local implementation ready for owner review/upload as one thirteen-file group.
Next progress requires owner private export and supervised API/Drive/clock checks,
then an explicitly chosen persistent host and independently tested missed-run
alerting. Do not dispatch, provision, enable timers, read private sealed datasets
or copy credentials on a later automatic continuation. No further local changes
are needed merely because the owner commissioning evidence is unchanged.

## Authorized automatic previous-close / Windows scheduling continuation

Owner reports DEVELOPMENT_EXPORTED: 55,596 rows / 737 accepted sessions, development
bars SHA prefix d20a4782...840a and sessions 02ae9448...688b, bounded 2022–2024.
Reviewed/registered PARKED_DEVELOPMENT_REPLAY spec 916d1850...49f5 produced identical
result ebd4c52c531d06d870bd307fe205e9ac6cedbef217348c7f8bb504c5e75f9ee8 twice.
Original and automated trade lists matched exactly; accepted/excluded 737/6,
out-of-session bars 84. This is owner-provided evidence, not agent access to private
datasets. No 2025/2026 historical file has been opened or new rule tuned here.

New local authority: implement automatic official previous close and owner-installed
awake-PC scheduling, supervised first. No actual tasks, credentials, hosted settings
or capture runs may be installed/changed/dispatched by the agent.

Decisions/implementation:
- nifty_previous_close.py: bounded exact-date NSE Daily Snapshot CSV GET with verified
  HTTPS/no redirects/fallback. Calendar skips closed dates but includes genuine
  prior special sessions. Exact unique NIFTY 50 price-index row, positive Decimal,
  original bytes/hash/source URL/observed retrieval; publication time remains unknown.
- forward_nifty_producer.py: additive v2 provenance validation with embedded source
  bytes so existing Drive bundles preserve it. v1 manual compatibility remains.
  Scheduler-only v2 must have same-IST-target-day pre-open source retrieval. Config
  source/environment freeze unchanged in principle; old captures need original code.
- forward_windows_credentials.py: lazy ctypes Windows Credential Manager generic
  credentials, current user, no plaintext secret files or command-line values.
  Fixed five names, bounded blobs, hidden TTY prompts and sanitized failures.
- forward_nifty_schedule.py: default offline preview; explicit source licence guard,
  real clock check, pre-open freeze, bounded five-minute polls and read-only coverage
  audit. Environment restored after vault-backed capture. Only owner generates or
  registers disabled task plans; no activation. Local receipts are not an off-PC
  watchdog. Unknown years/special targets/missing data remain non-actionable.
- scripts/install_forward_tasks.ps1: owner-only two-phase plan/verify/register,
  no replacement of existing tasks, normal interactive account, least privilege.
  09:00 prepare, 09:20:30–15:30:30 five-minute polls (75), 15:40 audit. IgnoreNew,
  no catch-up/wake/elevation/password. Registration leaves all three disabled.

Current fourteen-file upload group, relative to C:\Users\banga\Desktop\kiran_share_market:
Root: nifty_previous_close.py; forward_windows_credentials.py;
forward_nifty_schedule.py; forward_nifty_producer.py; mypy-automation.ini;
FORWARD_DATA_RUNBOOK.md; AUTOMATION_FOUNDATION_ACCEPTANCE.md; AUTOMATION_PROGRESS.md.
Tests: tests/test_nifty_previous_close.py; tests/test_forward_windows_credentials.py;
tests/test_forward_nifty_schedule.py; tests/test_research_automation.py.
Scripts: scripts/install_forward_tasks.ps1.
Workflow: .github/workflows/quality.yml.
No new dependencies, SQL migration, Supabase storage or equity fingerprint update.

Verification in progress: first focused pass 100 passed (includes old producer and
denied-I/O import); first full pass 1,545 passed / 4 unchanged skips / 2 subtests.
Self-review strengthened current-day provenance/licence gating and local audit
session/acknowledgment checks. Final frozen-source full suite pending. Strict mypy
15 source modules, root/tests pyflakes, pip check and PowerShell parser passed.
Live equity SHA remains 2893995505709b1b6a6bfcea342a2edb3770319c695297234747cf1b6801c7b9.

Important live gap: official NSE public catalogue lists the Daily Snapshot, but an
agent read-only probe of a pre-study 2021 archive URL timed out. No price data was
retrieved. Exact endpoint/schema availability on the owner's PC is UNVERIFIED.
Do not claim network commissioning or evade access controls. Owner must review the
first retained real source and resulting config before any task is enabled.

Next: finish full final suite/self-review, record result and hand off. Owner actions
are in FORWARD_DATA_RUNBOOK.md: review/upload/CI, private hidden-prompt vault setup,
generate/review/register disabled tasks, supervised pre-open preparation/first polls,
then deliberate recurring activation only after backup/replay drill. PC must remain
awake/signed in. Off-PC missed-run alerts remain separate and uncommissioned.
Overall programme stays partial. Do not run scheduled work merely on a heartbeat
until owner supplies new authorization/commissioning evidence.

### Final Windows-adapter verification and handoff

Final frozen-source offline suite: 1,547 passed, 4 unchanged skips, 2 subtests passed
in 226.77 seconds. +57 passing tests over the prior 1,490 baseline; no tests removed.
SQL PGlite safety, app import and fifteen-module external-I/O-denied import passed.
All root/test Python lint and strict mypy across fifteen source modules passed;
pip check and native PowerShell script parsing passed. Equity fingerprint remains
2893995505709b1b6a6bfcea342a2edb3770319c695297234747cf1b6801c7b9.

Main-agent final self-review covered code/module boundaries, strict dated source
identity, Decimal adapter precision, current-IST-date pre-open retrieval, source
licence checks, holiday/special/calendar limits, same-user credential scope and
secret-output masking, native-buffer lifecycle, environment restoration, poll
off-by-one/lateness bounds, serial overlap, disabled/least-privilege installation,
absence of catch-up, current-day audit identity and full remote acknowledgment.
Fixed generic OAuth error normalization, current-day provenance constraints,
source licence gating and audit shape/session checks. No known outstanding defect
identified within the tested local slice. Native task registration, real vault
access and official endpoint/schema availability still require supervised owner
verification; offline tests do not establish them.

Fourteen-file group is ready for review/upload. No agent-installed task, actual
credential-store access, real capture, dataset deletion, database/hosted change or
GitHub write. Owner commissioning instructions and stop/disable steps are in
FORWARD_DATA_RUNBOOK.md. No further local changes are required merely because
these owner-controlled operational prerequisites remain unchanged.

### 2026-10-05 owner commissioning failures: narrow repair

Owner initially observed three XML encoding registration failures followed by an incorrect
success message. The initial attempt created no real tasks. Owner also verified credential inputs and
vault roundtrip via private file after hidden long-JSON paste failed. Those results
do not justify relaxing any capture/auth/scheduling limits.

Local repair: installer calls an import-safe PowerShell helper which preserves
the verified UTF-8 plan files, removes the byte-encoding declaration only from
the Unicode COM input, explicitly stops cmdlet errors, and checks registered
Disabled state before claiming success. All plans are checked before the first
registration; partial installations are never enabled, overwritten or deleted.
Credential setup now supports --drive-oauth-file outside the repo, bounded UTF-8/
BOM input, JSON validation/compaction in memory, four remaining hidden prompts,
and full vault readback before success. Preview stays offline; token.json and the
real vault were not read or changed by the agent. Existing owner-verified vault
needs no repeat setup. Existing XML plans need no regeneration; registration retry
must use the same original PrivateRoot/StartDate.

Option pilot diagnosis: publish/verification precedes exit status. CAPTURED plus
DELAYED at 89.95 seconds intentionally exits 1, retaining the verified sample but
setting same_time_comparison_eligible false (60-second same-slot tolerance versus
600-second maximum capture window). Audit/resume also reject it as an on-time slot.
No option code/policy changed; manual early-start wait remains bounded to 600 seconds.

Changed upload group (seven files):
- forward_windows_credentials.py
- scripts/install_forward_tasks.ps1
- scripts/forward_task_registration.ps1 (new)
- tests/test_forward_windows_credentials.py
- tests/test_forward_task_registration.py (new)
- FORWARD_DATA_RUNBOOK.md
- AUTOMATION_PROGRESS.md

Repair validation completed: full offline suite with SQL harness, 1,563 passed /
4 skipped / 2 subtests; final targeted 29 tests passed (including three failure
cases added after that full run). Python lint, strict mypy (15 modules), and both
PowerShell parsers passed. Mocked PowerShell cmdlets
exercise real helper encoding, partial errors, missing/readied tasks and all-three
Disabled verification without touching Task Scheduler. Initial oversized pytest
parameter IDs caused temporary-path setup errors; short explicit IDs fix the test
fixture names. Equity fingerprint unchanged:
2893995505709b1b6a6bfcea342a2edb3770319c695297234747cf1b6801c7b9.
Owner reports all three upload commits green on main, successful real registration
of all three tasks as Disabled, then deliberate enabling of prepare/poll/audit
together. 6 Oct is the first automatic day; its 15:40 audit remains pending.
Option retry #20: CAPTURED, 47 rows, ON_TIME, 10.02-second delay, exit 0, token
days remaining 236. This verifies one hosted capture/archive/timing path, not
future punctuality, provider Greek conventions or unattended forward-day coverage.
Overall foundation remains partial; no inference of complete commissioning.

### Checked dashboard deployment foundation (local implementation)

Owner-authorized scope: separate release branch controlled by exact-SHA quality,
resilience and CodeQL results, actual offline AppTest boot, automatic promotion,
explicit paused rollback, owner-only hosted cutover instructions. Research/default
branch remains main. Existing model authorization/promotion/rollback untouched.

Decision: GitHub metadata (including latest reruns and CodeQL app identity) is the
authority, not success of whichever old event woke the job. Read-only planning
precedes the sole contents-write job; it revalidates before an atomic ref update,
requires a checked controller, uses no managed deployment secrets and executes no
candidate application code. Serial publisher concurrency; no cancellation mid-write.
Publisher uses a dedicated dashboard-release environment; owner must restrict
its deployment branches to main/release before authorizing automation. No required
reviewer is imposed for routine automatic promotion and no secrets enter it.
Historical fingerprint manifest parsed as data; hash is reported for the owner.
Streamlit's independently configured expected hash remains mandatory. A new hash
can temporarily block approvals until owner updates Secrets; no self-expectation
or automatic weakening was introduced. Actual hosted health is still owner-verified.

AppTest covers real OIDC sign-in UI and full Settings boot, copied dependency closure
plus policy/fingerprint sources, clean temporary state, synthetic configuration and
external-I/O denial. It does not validate live identity/broker/database services or
all authenticated pages. Special Matplotlib font initialization stays outside the
subprocess-denial window, with network denied throughout. Production code unchanged.

Eight-file upload group:
- dashboard_release.py (new, repository root)
- .github/workflows/dashboard-release.yml (new)
- .github/workflows/quality.yml
- mypy-automation.ini
- tests/test_dashboard_release.py (new)
- tests/test_streamlit_boot.py (new)
- DASHBOARD_RELEASE_RUNBOOK.md (new, repository root)
- AUTOMATION_PROGRESS.md

Final frozen-source validation: 1,601 passed, 4 unchanged skips, 2 subtests passed
in 225.48 seconds. Targeted release/real boot checks: 34 passed. All root/test Python
lint, strict mypy (16 modules), pip check and final workflow YAML/permission/branch
restrictions passed. Actual app boot and SQL safety tests are included in the full
suite. The new local-app finder prevents imports from escaping to the source tree;
the original extracted ZIP gate remains intact. Equity fingerprint unchanged:
2893995505709b1b6a6bfcea342a2edb3770319c695297234747cf1b6801c7b9.

Final self-review checked trigger/ref/origin restrictions, privilege split, no
credential inheritance or output, exact head/attempt identity, pagination, CodeQL
origin/missingness, boolean-vs-string confirmation, stale/ref/rerun races, controller
checks, fast-forward-only promotion, ancestor/tag-only rollback, historical manifest
reading without executing candidate code, external expectation preservation, real
boot paths and source isolation. Fixed test-copy resource coverage and import
isolation; clarified server environment restrictions, static run-variable snapshots,
queued publisher draining, historical advisory checks and lack of a hosted drain
handshake. A separate non-basetemp diagnostic hit the pre-existing pytest-current
Windows ACL cleanup issue; final runs use unique temporary roots, without changing
permissions or deleting old test data. No remaining defect identified in the tested
implementation. Hosted GitHub metadata identity/permissions, CodeQL categories,
environment settings, Streamlit webhook behavior/OIDC and runtime health remain
owner commissioning checks; local mocks are not claimed to establish them.

Next owner steps:
review/upload final group, green exact commit, read-only release preview, authorize
publisher, establish release branch, private secrets/settings backup, drain local
delivery, quiet-window delete/redeploy to release, verify OIDC/runtime and record
known-good SHA. Runbook explains timings, latest-head race boundary, branch rules,
fingerprint ordering, asynchronous restart and schema-compatible rollback.
No real ref update, task/vault operation, GitHub/settings write, cloud deployment,
database interaction, data/history deletion or 2025/2026 research examination.
Waiting on owner review/upload and release-branch commissioning. No additional
changes are needed merely on a heartbeat while those prerequisites are unchanged.
