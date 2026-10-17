# Preserved outcome review and frozen-cohort handoff

## Decision and evidence boundary

Owner reports PR42 merged green as `0ffcb53f1b00f9db266b432d7194d8fc59c8ccf1`.
The first execution returned `SYNTHETIC_COMPLETION_NOT_PROVEN`, enable attempted,
Disabled verified, no visible popup. This attempt is consumed. Do not rerun the
bridge/controller, generate a replacement ID, ACK an unseen notification, delete
markers, or change the preserved task/action/recipe. A historical date does not
become a new admission date. Monday's manual capture is independent of this work.

Source-verified: the controller rejects when the worker-claim marker was not seen
OR the last sampled result was not 2. The elapsed 3–4 minutes is consistent with
its 150-second observation budget plus native calls; it does not identify cause.
The worker writes `attempt.json` only after its recipe/date/hash/controller checks.
Both a caught worker failure and its intended synthetic outcome exit 2. Therefore
neither exit 2 nor an absent popup identifies launch, Python, permissions or recipe
as the cause. The scheduled process's environment has not been measured.

## One additive upload, no commissioning

Exact base: `0ffcb53f1b00f9db266b432d7194d8fc59c8ccf1`. Nine added destinations,
zero modified existing files. Each source below is relative to
`C:\Users\banga\Desktop\kiran_share_market`; destination is the identical relative
path in the clean upload clone. No staged substitutes and no force-add CSVs.

1. `preserved_drill_outcome.ps1`
2. `tests/test_preserved_drill_outcome.py`
3. `research_frozen_cohort.py`
4. `tests/test_research_frozen_cohort.py`
5. `FROZEN_COHORT_FOUNDATION_2026-10-17.md`
6. `OUTCOME_AND_COHORT_HANDOFF_2026-10-17.md`
7. `outcome_cohort_upload_check.py`
8. `tests/test_outcome_cohort_upload_check.py`
9. `OUTCOME_COHORT_UPLOAD_2026-10-17.json`

The JSON manifest pins LF-normalised bytes and unchanged prerequisite bytes.
Its own hash is null to avoid circular self-hashing; index/worktree equality is
checked. A hash binds reviewed bytes, not custody or execution truth. If main
moves, stop and reconcile the new base; do not loosen pins or edit the base.

### Owner upload blocks (normal PowerShell, one at a time)

Use the established clean-clone routine, at the exact base above, on a new branch.
From that clone, copy/stage ONLY these nine destinations:

```powershell
$ErrorActionPreference='Stop'
$reviewPython='C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
$packageSource='C:\Users\banga\Desktop\kiran_share_market'
$expectedBase='0ffcb53f1b00f9db266b432d7194d8fc59c8ccf1'
$head=& git rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $head -cne $expectedBase) {throw 'EXACT_BASE_REQUIRED'}
$dirty=@(& git status --porcelain)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -ne 0) {throw 'CLEAN_CLONE_REQUIRED'}
$paths=@('preserved_drill_outcome.ps1','tests/test_preserved_drill_outcome.py',
 'research_frozen_cohort.py','tests/test_research_frozen_cohort.py',
 'FROZEN_COHORT_FOUNDATION_2026-10-17.md','OUTCOME_AND_COHORT_HANDOFF_2026-10-17.md',
 'outcome_cohort_upload_check.py','tests/test_outcome_cohort_upload_check.py',
 'OUTCOME_COHORT_UPLOAD_2026-10-17.json')
foreach ($path in $paths) {Copy-Item -LiteralPath (Join-Path $packageSource $path) -Destination (Join-Path $PWD $path) -ErrorAction Stop}
& git add -- $paths
if ($LASTEXITCODE -ne 0) {throw 'STAGE_FAILED'}
& $reviewPython -B outcome_cohort_upload_check.py --base $expectedBase
if ($LASTEXITCODE -ne 0) {throw 'PACKAGE_CHECK_BLOCKED'}
```

Require `OUTCOME_COHORT_PACKAGE_VERIFIED_REQUIRES_TESTS_AND_EXACT_COMMIT_CI`, failures `[]`.

```powershell
$ErrorActionPreference='Stop'
& $reviewPython -B -m pytest -q -p no:cacheprovider tests/test_preserved_drill_outcome.py tests/test_research_frozen_cohort.py tests/test_outcome_cohort_upload_check.py tests/test_research_dataset_boundary.py tests/test_quote_faithful_futures_replay.py tests/test_research_session_inference.py tests/test_archive_commissioning_hold.py
if ($LASTEXITCODE -ne 0) {throw 'FOCUSED_TESTS_FAILED'}
& $reviewPython -B -m pyflakes outcome_cohort_upload_check.py research_frozen_cohort.py tests/test_preserved_drill_outcome.py tests/test_research_frozen_cohort.py tests/test_outcome_cohort_upload_check.py
if ($LASTEXITCODE -ne 0) {throw 'LINT_FAILED'}
$typeCache=Join-Path $env:TEMP ('cohort-mypy-'+[guid]::NewGuid().ToString('N'))
& $reviewPython -B -m mypy --strict --follow-imports=silent --cache-dir $typeCache research_frozen_cohort.py outcome_cohort_upload_check.py
if ($LASTEXITCODE -ne 0) {throw 'TYPES_FAILED'}
& git diff --cached --check
if ($LASTEXITCODE -ne 0) {throw 'DIFF_CHECK_FAILED'}
```

Before committing require repo-local identity presence, without printing values:

```powershell
$ErrorActionPreference='Stop'
$identityName=& git config user.name
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($identityName)) {throw 'OWNER_SET_REPO_LOCAL_NAME_FIRST'}
$identityMail=& git config user.email
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($identityMail)) {throw 'OWNER_SET_REPO_LOCAL_EMAIL_FIRST'}
```

Use one commit with message `Add preserved outcome review and frozen cohort accounting`.
PR description, one plain line: `Add read-only preserved drill outcome diagnostics and inactive complete-cohort research accounting.`
No attribution/trailers. Require full hosted CI green on the exact final PR SHA;
owner alone merges. Builder offline tests do not substitute for that gate.

## Read-only owner outcome check, AFTER merge

In a fresh clean checkout of the merged version, normal non-admin PowerShell:

```powershell
$ErrorActionPreference='Stop'
& .\preserved_drill_outcome.ps1
if ($LASTEXITCODE -ne 0) {throw 'PREVIEW_BLOCKED'}
```

Require PREVIEW, all counters zero. Then a separate block:

```powershell
$ErrorActionPreference='Stop'
& .\preserved_drill_outcome.ps1 -ConfirmReadOnly
if ($LASTEXITCODE -ne 0) {throw 'READ_ONLY_OUTCOME_BLOCKED_PRESERVE_OUTPUT'}
```

Share only the JSON. This queries exactly the fixed dummy task definition and
its task-info once each, plus metadata of six fixed isolated files and at most
16 report-directory entries. It reads no JSON contents, credentials or capture
state, runs no worker, and changes no task or file. It rejects links, directories
in place of marker files and files over 1 MiB. It is not an adversarial concurrent
filesystem sandbox; the multi-query snapshot is explicitly non-atomic.

Absent `attempt.json` means the claim marker was not found at the reviewed root,
NOT that Python never ran. Present files may be malformed/unsigned; names and
sizes are not a semantic route proof. A launch marker does not prove popup
delivery. No result authorises retry, replacement, ACK or cleanup. If the task is
not Disabled, stop and report the JSON; this helper intentionally cannot disable it.
Query failure is NOT `NOT_FOUND` and is never presented as successful absence.

After these facts, the next drill design must persist classified worker-stage
receipts before validation, distinguish intentional exit 2 from caught failure,
and bind native start/completion to that exact receipt. Build an inactive future
capsule with independent fault tests; do not retrofit this preserved attempt.
No future drill is authorised by this document. A synthetic success would still
not prove real production blocked-poll delivery or independent delivery.

## Archive and capacity: next owner evidence, independent of this upload

Owner-reported: DELETE=false; ARCHIVE=true; release=false; no active archive runs.
PR42 source holds scheduled archive runs without database/Drive I/O. Green may
mean HELD; earlier green runs are not evidence of zero deletions or restore.

Run the ALREADY-MERGED `sql/archive_hold_reconciliation_read_only.sql` once in the
Supabase SQL editor, unchanged. It uses BEGIN READ ONLY, bounded timeouts and
ROLLBACK, returns operational metadata only. Share measurement time, current DB
bytes, cluster bytes, per-table manifest/deleted totals and active archive count;
no secrets or market rows. A permission/query failure means not established,
not zero. Counts are recorded manifest sums, not unique archived rows or custody.
Keep DELETE=false and do not run exports/deletion/compaction/research extension.
Inspect archive run logs for hold status separately; do not rerun failed/old jobs.

The 345,549,971-byte current-database reading cannot establish cluster headroom,
growth or a cause for the apparent reduction. Supabase documents the cluster sum
separately from WAL/system disk and applies the free database-size limit at 500 MB.
No fresh capacity claim or retention admission is made here.

Next commissioning order: private key note → harmless encrypted-disk rehearsal →
owner Drive storage/retention facts → consistent-cut export → independently verified
custody of that exact generation → matching full restore → guarded writer/cold-reader
factory acceptance → source retention and capacity proof. Existing holds stay in
force; no deletion is unlocked by successful tests or environment booleans.

## Open-item decisions, no dropped work

- **Monday 19 Oct:** unchanged proven manual Prepare→Start, genuine 16 Oct close.
  This package is not a dependency. No manual+guided route on the same date.
  Owner calendar says 20 closed, 21 regular; this package does not change calendars.
- **Alert delivery:** unknown production route; consumed synthetic attempt reviewed
  read-only first. Do not try to manufacture proof by breaking capture.
- **Local PostgreSQL:** non-loopback listeners deserve a dependency/exposure review.
  They do not prove public reachability. Prefer an on-demand, loopback-only disposable
  test service over a permanently running development server, but make no service,
  firewall or permission changes until the exact dependency review and owner step.
  This package uses no PostgreSQL connection, including port 5433.
- **Time service/root dispersion:** attribution remains unknown; preserve clock
  gates, no clock self-heal or threshold relaxation from this result.
- **14 Oct saved audit:** report not found does not establish observations absent.
  Do not regenerate or rewrite historical evidence to make a report appear.
- **Legacy audit exit 2/shared-root writes:** still unresolved; inspect only under a
  separate reviewed bounded historical procedure, never run the legacy writer.
- **Guided/daily SID binding:** still needs canonical-identity integration and a new
  separate-date supervised rehearsal. Historical pin 0b0aad4 remains uncommissioned.
- **OPTION_CAPTURE_ENABLED:** undefined stays off. Skipped runs are not failures or
  data. Do not extend frozen EQUITY_RESEARCH_SESSIONS_JSON beyond 1 Oct automatically.
- **Friday 75/75/0:** retained as an unsigned owner-reported saved-report claim, not
  authenticated custody, cohort eligibility or training admission.
- **ML/backtesting:** mandatory delivery; the new full-cohort adapter advances the
  denominator/withholding boundary only. Real fitting, licensed labels, strategy
  performance claims, application promotion and live decisions remain gated.

## Technology radar and next leverage

Adopt existing stdlib Python, native read-only Scheduler interfaces, PS5.1/PS7
portability tests and the existing offline Linux container. Adapt complete-cohort
accounting instead of discarding failed trials. No new package, plugin, account,
agent runtime, hosted resource or cost is introduced. Broad desktop automation
and process-wide logging are rejected here: they add authority and potential
secret output without establishing this worker's lost result.

Next highest leverage: immutable, classified stage receipts written before risky
worker checks, correlated with native completion. This prevents another opaque
exit-2 investigation; it is not permission to rerun the present attempt.

Primary references reviewed:
- https://learn.microsoft.com/windows/win32/taskschd/task-scheduler-error-and-success-constants
- https://learn.microsoft.com/en-us/troubleshoot/windows-server/system-management-components/troubleshoot-scheduled-tasks-not-running
- https://supabase.com/docs/guides/platform/database-size
- https://supabase.com/changelog (markdown index unavailable through the reader;
  HTML fallback inspected; no SDK, schema or hosted changes in this package)

## Builder verification and limits

Combined seven-file focused suite: Windows Python 3.13.9, **264 passed, 0 skipped**;
Linux Python 3.13.9 in the network-disabled public-source container, **242 passed,
22 skipped**. The 22 skips are Windows PowerShell executable cases; PS7 cases ran
on Linux. These exercise Scheduler doubles, not real native tasks. New diagnostic
alone: Windows45; Linux23/22skip. New cohort48 on both. Pyflakes clean for five
package Python files; strict mypy passes two modules on both platforms.

Independent checker reviewed the diagnostic, handoff/checker contract and cohort.
Two cohort defects (evaluation-cutoff leakage and nonfinite-input resource bypass)
were reproduced, fixed and independently rechecked with regressions. No unresolved
source blocker found in this package's declared scope. Existing project-wide full
suite, actual-base Git/index package check, final-SHA hosted CI, native owner outcome,
custody, restore, production delivery and real model performance are NOT verified
by this builder run. The owner must run the exact-base staged check and hosted CI.
