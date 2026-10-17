# Priority: archive deletion hold, preserved first execution, paper replay

## Do first: owner settings, independent of this PR

Owner reports PR41 merged green9be13929644dab3a091210df13743ddfbb38db32.
No hosted setting or task was changed by this build. The owner observed
ARCHIVE_ENABLED=true and ARCHIVE_DELETE_ENABLED=true. Current released workflow
selects delete nightly; the old flag is NOT proof of custody/restore commissioning.

1. On repository Settings -> Secrets and variables -> Actions -> Variables, set
   ONLY ARCHIVE_DELETE_ENABLED to the literal false. No secret read, ACL, role,
   release setting or other variable change. Verify its displayed value.
2. Inspect the exact Verified Drive archive workflow for queued/in-progress runs.
   If active, record run number/SHA and cancel that run once to prevent further
   batches. Cancellation is NOT rollback proof; preserve logs and do not retry.
   A flag change does not change an already-running process's environment.
3. After no archive run is active, owner may run
   sql/archive_hold_reconciliation_read_only.sql in the SQL editor as one read-only
   transaction. Share aggregate counts/bytes/timestamps only, no URLs/keys/rows.
   It reads operational manifest metadata, not prices or held-out observations.
   Query failure does not prove zero deletions. Its counters are not authenticated
   restore/custody evidence and repeated archives are not necessarily unique rows.

No mutation is commissioned by those diagnostic queries. No VACUUM/rewrite, source
deletion, privilege change or model/data collection is requested.

## What this reviewed package changes

All three archive deletion entry points now deny: CLI, run_batch and repository
acknowledge. A true deletion flag cannot override
AUTHENTICATED_CUSTODY_AND_RESTORE_NOT_COMMISSIONED. CLI with flag off retains
DELETION_NOT_ENABLED. Denial precedes DB construction/select, credentials, upload
or transaction/manifest writes. No CUSTODY_VERIFIED=true or other boolean unlocks
it. Future deletion needs reviewed generation-bound custody/restore implementation,
not a new flag. This is archive-API enforcement, not a restriction on privileged
SQL users or every unrelated SQL deletion path.

Nightly workflow becomes an explicit ARCHIVE_SCHEDULE_HELD_NO_IO job with no
checkout, dependencies, secrets, DB/Drive connection or deletion. Its green exit
means HELD, not archived or storage healthy. Manual choices are preview/export
only; export still uploads objects and writes DB manifests, so it is NOT read-only
or newly commissioned. No manual export is requested now. Existing workflow is
not newly enabled; its scheduled behaviour is made non-destructive on merge.
The dashboard release hold remains false and capture is untouched.

Historical row/restore/dependency algorithms remain covered in disposable tests.
Three legacy test modules explicitly monkeypatch only the new denial function
within synthetic fixtures. New test_archive_commissioning_hold.py does NOT patch
it and proves denial at every entry point, regardless of environment flags.
Those algorithm tests do not establish production deletion admission.

## Preserved drill: distinct first worker execution, not Setup retry

Owner's fresh read-only audit reports source/task/recipe/Disabled true and same
IST day17Oct, no execution witnesses. The new preserved_drill_first_run.ps1 is
a separate reviewed owner-confirmed first-execution bridge for EXACT ID
389daf12415a482eb0231443ddfd8697. It never repeats Setup, changes a task action,
registers/deletes a task, changes a date, resets a marker or authorises a new ID.

Default preview is inert. Confirmed invocation requires normal window, explicit
Python3.13.9, owner idle attestation, clean reviewed tools checkout, three fixed
helper-source pins and a repeated full read-only audit. It requires literal
same-day/binding/Disabled success; the hard date is17Oct2026 IST. It writes a NEW
exclusive recovery-admission.json, retaining the original recipe. The record binds
the private action/interpreter/directory, recipe LF hash, reviewed source set and
owner consent; it is NOT a signed authentication record or whole-tree hash.

Only then does the pinned Run helper recheck recipe/date/source/task binding,
exclusively claim controller-attempt and enable/start the exact dummy once.
Fresh bridge date checks run after audit, around admission and immediately before
Enable/Start after binding queries. The worker retains its own fresh date guard.
This is not an atomic midnight guarantee; time can change between operations.
Any existing admission/attempt/witness/ACK, uncertain write, unknown Start or
cleanup outcome consumes/stops the route. No continuation, reset or same attempt
retry. Best-effort Disable is not a verified Disabled result. Cleanup may disable
the exact dummy after expiry; it may never start it then.

Use this only AFTER exact-final-SHA CI green and owner merge, only if still17Oct
IST with generous time to observe the result and no capture running. Do not rush
a merge or invocation to beat midnight. If later: NO_GO, preserve the old attempt;
a separately reviewed future dated commissioning is needed. Monday needs none of
this bridge. Production failed-poll delivery remains unproven after synthetic ACK.

Fresh normal PowerShell in the new clean tools checkout; one block at a time:

```powershell
$ErrorActionPreference='Stop'
$reviewPython='C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
$ownerShell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
& $ownerShell -NoProfile -File (Join-Path $PWD.ProviderPath 'preserved_drill_first_run.ps1')
if ($LASTEXITCODE -ne 0) {throw 'STOP_FIRST_EXECUTION_PREVIEW'}
```

Require PREVIEW, all counters zero. Then, only under the same-day conditions:

```powershell
$ErrorActionPreference='Stop'
$oldDrillTools=Read-Host 'Exact original PR39 tools checkout used for the failed Setup'
& $ownerShell -NoProfile -File (Join-Path $PWD.ProviderPath 'preserved_drill_first_run.ps1') -OldToolsRoot $oldDrillTools -Python $reviewPython -ConfirmNoCaptureRunning -ConfirmFirstExecution
if ($LASTEXITCODE -ne 0) {throw 'STOP_PRESERVE_FIRST_EXECUTION_OUTCOME_NO_RETRY'}
```

Expected ISOLATED_FAILURE_ROUTE_RECORDED_AWAITING_OWNER_ACK, scheduler_result2,
launch_acknowledged/task_disabled_owner_witness true. Task result2 is intentional
for this synthetic worker, not success of a production poll. Read the actual
visible message: existing caption NIFTY capture alert, body synthetic <code>
clock review required. If not personally seen, do NOT acknowledge. If blocked,
share JSON and stop; no Inspect or retry is requested until review.

Only after that expected result and actually seeing the matching popup:

```powershell
$ErrorActionPreference='Stop'
$seenCode=Read-Host 'Eight-letter code personally seen in the synthetic popup'
& $reviewPython -I -B (Join-Path $oldDrillTools 'isolated_alert_drill.py') --drill-id 389daf12415a482eb0231443ddfd8697 --mode acknowledge --confirm-drill-only --confirm-notification-seen --seen-code $seenCode
if ($LASTEXITCODE -ne 0) {throw 'STOP_PRESERVE_ACK_OUTCOME_NO_RETRY'}
```

This separate ACK may occur later than17Oct because inspection is historical;
it remains the owner's truthful attestation, not independent delivery proof.
Keep the dummy Disabled and all records. Never upload isolated records or private
paths. No cleanup/deletion is authorised.

## Repository variables and current measurements

- OPTION_CAPTURE_ENABLED absent: keep absent/off. Licence ACK=true and expiry
  metadata alone do not commission scheduled capture. Before any future enable:
  review actual licence/source rights, dated references/contract/calendar, correct
  token identity/expiry, Drive quota/retention and supervised receipt/audit. No
  missing option slots are caught up. The observed2027-05-30 variable is configured
  expiry metadata, not provider-verified token validity; do not replace it with the
  older generic Analytics-token August statement without identifying the token.
- PROSPECTIVE_DATA_LICENSE_ACK=true/EQUITY_RESEARCH_ENABLED=true are existing
  owner observations, not independent licence proof. EQUITY_RESEARCH_SESSIONS_JSON
  ends1Oct/reviewed10Sep: preserve its frozen cohort; do not silently append dates
  or retune it. Read-only logs/run-SHA/cohort review next, no variable extension.
- ARCHIVE_ENABLED stays as observed; ARCHIVE_DELETE_ENABLED must remain false.
  DASHBOARD_RELEASE_ENABLED=false unchanged. No new model/backend/research
  workflow or capture recurrence is enabled by this PR.
-345,549,971bytes at13:04UTC17Oct is CURRENT DATABASE only. It is lower than the
  older figure but neither the decrease's cause nor cluster headroom is established.
  Do not subtract it from500MB to claim actual runway. The SQL diagnostic supplies
  current/cluster separately. Supabase documents cluster-summed database size and
  the free500MB threshold separately from WAL/system disk usage.
- Small/new Drive manifest/Parquet files prove neither complete source coverage,
  account free quota, retention guarantees, independent custody nor matching
  restore. Owner Storage screenshot and private key-note/disk rehearsal remain.

## Mandatory research delivery and remaining open items

New quote_faithful_futures_replay.py supplies bounded typed two-leg PAPER
accounting with chronological availability/version selection, bid/ask, explicit
latency/depth/staleness, tick/lot/expiry checks and dated decimal costs. Read
FUTURES_REPLAY_FOUNDATION_2026-10-17.md. It is not a live execution simulator,
licensed backtest or a link to the application. Unsupported exits commit NO paper
legs, not a magically closed real entry. All withheld/rejected planned trials
must remain in denominators: never aggregate success-only pairs as performance.
Next: complete frozen-cohort dataset->replay adapter, then split/calibration/
holdout evaluation linked to full trial accounting. ML/backtesting remain required
in parallel with custody; real training, labels, claims and promotion stay gated.

Priority owner/build chain after the archive hold: same-day optional dummy drill
only if safely ready -> key-note/disk/Drive prerequisites and exact-cut source
publication -> authenticated independent custody and six-table/full-image restore
-> writer/cold-reader wiring -> lossless dedup/retention -> steady-state capacity
and independent alert delivery. No deletion before commissioned proofs.

14Oct report not found is NOT no observations. A compatible original-capsule
journal audit remains separate read-only work. Friday75/75/0 stays an unsigned
owner-reported saved-report claim. Legacy exit2/shared-root writes and Time12:48/
root-dispersion causes remain unresolved; syncing Information events and START
triggers do not establish the stop's cause. No service/clock/ACL repair.

Local PG17 Running/Auto/non-loopback remains an exposure/dependency review, not
proof of external reachability or disuse. Keep service/firewall settings unchanged
until a separately approved owner change. Guided wrapper remains pinned0b0aad4,
uncommissioned; exported-account/planned-SID compatibility still separate. Never
use guided and manual for one session. Monday19Oct keeps the proven manual route,
genuine16Octclose;20Oct closed;21Oct regular/19Octclose. Setup19/21 already exists,
do not repeat it. No package here is a Monday dependency.

Technology radar: adopt existing typed stdlib/Decimal, immutable hashes and fake-
native Windows/Linux failure injection. No plugin/account/key/dependency install.
Consider Arrow/DuckDB only for later bounded Parquet analytics; reject a broad
terminal plugin or an env boolean as custody/approval authority. Builder and
independent reviewer are separate; runtime agents only monitor/report.

Official references reviewed17Oct: https://supabase.com/docs/guides/platform/database-size
and https://supabase.com/docs/guides/platform/backups . Changelog markdown fetch
unsupported; HTML fallback checked. No schema/SDK change or hosted query ran here.

## Builder verification, not commissioning

Final focused five-file selection below: Windows181passed/0skipped; network-
disabled Linux163passed/18skipped. Linux18 skips are WindowsPowerShell cases
exercised on Windows; PowerShell7 fake-native cases run on both. Additional exact
public/staged SQL algorithm selection:36passed on EACH platform with in-memory
PGlite, scoped test-only denial replacement and synthetic rows. These are NOT
native Postgres race/locking acceptance or commissioned deletion/custody proofs.
Strict mypy2 new modules and pyflakes10 Python files pass on both platforms.
Independent source/method/binding/checker review found no remaining blocker.
No real task, identity, private state, credential, source data or hosted service
was accessed by builder tests. Only inert native-script previews execute directly;
all confirmed task/service calls are fake. No system setting was changed.

Full repository suite, actual-base staged checker, exact-final-SHA hosted CI,
native first execution/notification delivery, owner flag changes and the new
hosted read-only diagnostic remain unverified owner steps. Real current database
numbers and full audit results above are owner reports, not builder observations.
The optional bridge has no late-date fallback even if uploads take longer.

## One reviewed upload,16 destination paths (5M/11A)

Exact base9be13929644dab3a091210df13743ddfbb38db32; stop if main moved. Source root
C:\Users\banga\Desktop\kiran_share_market; destination root the owner's fresh clean
upload clone. SAME suffix unless explicitly mapped below:

```text
M archive_maintenance.py -> archive_maintenance.py
M .github/workflows/drive-archive.yml -> .github/workflows/drive-archive.yml
M tests/test_drive_archive.py -> tests/test_drive_archive.py
M staged_archive_hold/test_archive_maintenance_sql.py.reviewed -> tests/test_archive_maintenance_sql.py
M tests/test_archive_storage_relief.py -> tests/test_archive_storage_relief.py
A tests/test_archive_commissioning_hold.py -> tests/test_archive_commissioning_hold.py
A quote_faithful_futures_replay.py -> quote_faithful_futures_replay.py
A tests/test_quote_faithful_futures_replay.py -> tests/test_quote_faithful_futures_replay.py
A FUTURES_REPLAY_FOUNDATION_2026-10-17.md -> FUTURES_REPLAY_FOUNDATION_2026-10-17.md
A preserved_drill_first_run.ps1 -> preserved_drill_first_run.ps1
A tests/test_preserved_drill_first_run.py -> tests/test_preserved_drill_first_run.py
A sql/archive_hold_reconciliation_read_only.sql -> sql/archive_hold_reconciliation_read_only.sql
A COMMISSIONING_NEXT_2026-10-17.md -> COMMISSIONING_NEXT_2026-10-17.md
A commissioning_next_upload_check.py -> commissioning_next_upload_check.py
A tests/test_commissioning_next_upload_check.py -> tests/test_commissioning_next_upload_check.py
A COMMISSIONING_NEXT_UPLOAD_2026-10-17.json -> COMMISSIONING_NEXT_UPLOAD_2026-10-17.json
```

SPECIAL MAPPING: do NOT copy the root tests/test_archive_maintenance_sql.py: it
contains an unrelated local-only harness draft. The .reviewed staging file is
exact public-base bytes plus only the scoped test fixture; no old pin was loosened.
Do not upload staged_archive_hold or a .reviewed destination. Clean-clone copy:

```powershell
$ErrorActionPreference='Stop'
Copy-Item -LiteralPath 'C:\Users\banga\Desktop\kiran_share_market\staged_archive_hold\test_archive_maintenance_sql.py.reviewed' -Destination '.\tests\test_archive_maintenance_sql.py'
```

After all16 destinations copied/staged, normal PowerShell one block at a time:

```powershell
$ErrorActionPreference='Stop'
$reviewPython='C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
& $reviewPython -I -B -c "import sys; assert sys.version_info[:3] == (3,13,9)"
if ($LASTEXITCODE -ne 0) {throw 'PINNED_PYTHON_REQUIRED'}
& $reviewPython -B commissioning_next_upload_check.py --base 9be13929644dab3a091210df13743ddfbb38db32
if ($LASTEXITCODE -ne 0) {throw 'STOP_COMMISSIONING_PACKAGE'}
```

Require COMMISSIONING_PACKAGE_VERIFIED_REQUIRES_TESTS_AND_EXACT_COMMIT_CI,failures[].
Checker requires5 M/11 A, all payloads/index/worktree, old-base hashes for5Ms,
12 unchanged prerequisites, no extras, regular stage-zero files, exact clean
base HEAD. It is precommit only, not a checker for the later committed SHA.

```powershell
$ErrorActionPreference='Stop'
$scratch=Join-Path $env:TEMP ('commission-next-'+[guid]::NewGuid().ToString('N'))
& $reviewPython -B -m pytest -q tests/test_archive_commissioning_hold.py tests/test_drive_archive.py tests/test_quote_faithful_futures_replay.py tests/test_preserved_drill_first_run.py tests/test_commissioning_next_upload_check.py --basetemp=$scratch -p no:cacheprovider -r s
if ($LASTEXITCODE -ne 0) {throw 'STOP_COMMISSIONING_TESTS'}
```

```powershell
$ErrorActionPreference='Stop'
& $reviewPython -B -m pyflakes archive_maintenance.py tests/test_drive_archive.py tests/test_archive_maintenance_sql.py tests/test_archive_storage_relief.py tests/test_archive_commissioning_hold.py quote_faithful_futures_replay.py tests/test_quote_faithful_futures_replay.py tests/test_preserved_drill_first_run.py commissioning_next_upload_check.py tests/test_commissioning_next_upload_check.py
if ($LASTEXITCODE -ne 0) {throw 'STOP_COMMISSIONING_LINT'}
$cache=Join-Path $env:TEMP ('mypy-commission-'+[guid]::NewGuid().ToString('N'))
& $reviewPython -B -m mypy --strict --cache-dir=$cache quote_faithful_futures_replay.py commissioning_next_upload_check.py
if ($LASTEXITCODE -ne 0) {throw 'STOP_COMMISSIONING_TYPES'}
```

Strict typing scope is2 new Python modules, not the legacy untyped archive module.
Check repo-local identity presence privately; if absent set only this clone to
the owner's chosen identity, never print values. Require git diff --cached --check.
Suggested commit: Hold archive deletion and add reviewed paper replay.
One-line PR description: Block uncommissioned archive deletion and add gated first
drill execution with paper futures replay. No attribution/trailers. Exact-final-SHA
hosted CI green, owner-only merge, then fresh clean tools checkout. No bridge Run
before merge, no late-date fallback, no new ID or capture modification.
