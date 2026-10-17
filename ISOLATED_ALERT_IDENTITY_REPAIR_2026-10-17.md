# Isolated identity repair: reconcile, do not retry

Owner-reported PR39 merged green as d2da7bb90f092dc53be9e5b5bf5875799108d123.
Native Setup stopped on current_user during DISABLED_DRILL_REGISTRATION. No Run
was reported. Builder did not inspect native tasks, isolated state or credentials.

## Meaning and boundaries

The old check compared Task.Principal.UserId text to WindowsIdentity.User.Value
and WindowsIdentity.Name. Registration requested the SID but Scheduler can return
an account name. Different strings may identify the same SID. This is a likely
representation defect, NOT proof that this task belongs to the current account.
The repair resolves both identities through Windows SecurityIdentifier/NTAccount
and requires exact SID equality. Empty, unresolved or different identities fail
closed, with only SID_EQUAL, SID_MISMATCH or UNRESOLVED printed. No username,
SID, email, task command, exception text or XML is printed. NOT_CHECKED identifies
a failure before the identity check. Microsoft documents account translation:
https://learn.microsoft.com/en-us/dotnet/api/system.security.principal.ntaccount.translate
Name resolution may consult Windows directory services; no strictly local-only
or hard elapsed-time bound is claimed. The scope is a bounded set of task/file
metadata queries, not a network timeout guarantee.

Setup creates recipe.json before registering the Disabled task, then checks its
binding, then checks Disabled state. Thus state and task may already exist; the
reported task_disabled_verified=false means NOT PROVED, not necessarily enabled.
The source never reached Enable or worker Run in this Setup branch. Unknown
external changes are not excluded. Do not infer absence from a query failure.

This failed SETUP attempt is consumed/preserved. It is not a capture slot and
does not consume a worker execution, but this is NOT authorisation to execute it.
The current helper does not reconstruct a lost registration-acceptance receipt.
No automatic adoption, migration, overwrite, deletion, reset or new-ID retry is
provided. After reconciliation, a separate reviewed recovery decision must bind
the exact disabled task, action, tools checkout and existing recipe before any
single Run can be authorised. Changed checkout paths must not be silently adopted.
If any execution/ACK witness exists, or the task is not Disabled, stop for review.

## Owner read-only steps after reviewed merge

Use a new clean checkout of the final reviewed green merge, not the old drill's
checkout. Do not replace that old checkout or any state. Normal non-Administrator
PowerShell, one block at a time. No Python invocation is needed for these reads.

```powershell
$ErrorActionPreference='Stop'
& .\isolated_alert_reconcile.ps1 -DrillId 389daf12415a482eb0231443ddfd8697
if ($LASTEXITCODE -ne 0) {throw 'STOP_READ_ONLY_PREVIEW'}
```

Require PREVIEW and zero counters. Then:

```powershell
$ErrorActionPreference='Stop'
& .\isolated_alert_reconcile.ps1 -DrillId 389daf12415a482eb0231443ddfd8697 -ConfirmReadOnly
if ($LASTEXITCODE -ne 0) {throw 'STOP_PRESERVE_READ_ONLY_FAILURE'}
```

Share only its JSON. It queries only the exact synthetic task and five fixed
isolated-file presence flags, never file contents or other tasks. It rejects
linked state ancestors/files. Task query failure is NOT_FOUND neither assumed nor
claimed: it returns READ_ONLY_QUERY_OR_IDENTITY_NOT_ESTABLISHED. Its read-only
result is not full task binding/recipe acceptance. raw_identity_equal=false with
current_user_sid_equal=true would confirm the old representation mismatch.

## Guided wrapper and open items

Guided delegates Setup/Start to the daily coordinator. That coordinator compares
exported UserId against the SID in planned XML, rather than this drill's raw
SID-or-name list. Representation differences can also cause a safe rejection
there, but Monday's dated tasks were already owner-verified. No production
binding change is included; keep Monday's proven manual route and separate guided
commissioning. Do not infer this synthetic repair fixes or breaks capture.

Production failure-alert delivery remains unproven; this blocks only drill
acceptance. Saved Friday75/75 report remains owner-reported, unsigned. Historical
14Oct audit, legacy exit2/shared-root writes, Time stop/root dispersion and option
workflow skips remain unresolved. Independent custody/restore, fresh DB/Drive
capacity and storage commissioning remain pending. Local PG service unchanged;
no service, ACL, marker, clock, capture or hosted changes are authorised. ML and
backtesting engineering remain required in parallel, with real training/LLM and
performance claims gated by licences, labels, study freeze and paper evidence.

Technology radar: reuse native .NET SID translation and deterministic comparison;
no plugin, admin elevation, new account or paid service. Do not use short-name
matching or accept any resolvable account. Highest leverage: bounded reconciliation
then an authenticated one-attempt acceptance record, not repeated Setup attempts.

## Upload: one group, exact base

Base d2da7bb90f092dc53be9e5b5bf5875799108d123; stop if main changed. Same source
root and identical destination suffixes in the clean upload clone:

```text
M isolated_alert_task_drill.ps1 -> isolated_alert_task_drill.ps1
M tests/test_isolated_alert_drill.py -> tests/test_isolated_alert_drill.py
M ISOLATED_ALERT_DRILL_RUNBOOK_2026-10-17.md -> ISOLATED_ALERT_DRILL_RUNBOOK_2026-10-17.md
M PROGRAMME_NEXT_UPLOAD_2026-10-17.json -> PROGRAMME_NEXT_UPLOAD_2026-10-17.json
A isolated_alert_reconcile.ps1 -> isolated_alert_reconcile.ps1
A tests/test_isolated_alert_identity.py -> tests/test_isolated_alert_identity.py
A isolated_identity_upload_check.py -> isolated_identity_upload_check.py
A tests/test_isolated_identity_upload_check.py -> tests/test_isolated_identity_upload_check.py
A ISOLATED_ALERT_IDENTITY_REPAIR_2026-10-17.md -> ISOLATED_ALERT_IDENTITY_REPAIR_2026-10-17.md
A ISOLATED_IDENTITY_UPLOAD_2026-10-17.json -> ISOLATED_IDENTITY_UPLOAD_2026-10-17.json
```

The prior manifest is refreshed only for the three intentionally changed payloads
so its existing integrity regression stays valid; old prerequisite/base pins stay
intact. It remains a historical precommit package, not the new upload checker.
Stage exactly these10 paths. Explicit reviewed venv Python3.13.9, never bare py.

```powershell
$ErrorActionPreference='Stop'
$reviewPython='C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
& $reviewPython -B isolated_identity_upload_check.py --base d2da7bb90f092dc53be9e5b5bf5875799108d123
if ($LASTEXITCODE -ne 0) {throw 'STOP_IDENTITY_PACKAGE'}
```

```powershell
$ErrorActionPreference='Stop'
$scratch=Join-Path $env:TEMP ('identity-tests-'+[guid]::NewGuid().ToString('N'))
& $reviewPython -B -m pytest -q tests/test_isolated_alert_identity.py tests/test_isolated_alert_drill.py tests/test_isolated_identity_upload_check.py tests/test_programme_next_upload_check.py --basetemp=$scratch -p no:cacheprovider -r s
if ($LASTEXITCODE -ne 0) {throw 'STOP_IDENTITY_TESTS'}
```

Check repo-local identity presence privately, git diff --cached --check, then one
commit/PR; no attribution/trailers. Suggested commit: Fix isolated drill identity
binding and add read-only reconciliation. One-line PR description: Resolve exact
SID identity and preserve blocked isolated drill attempts for read-only review.
Require exact-final-SHA hosted CI green; owner alone merges. No activation on merge.

Offline lint/type block, separately before commit:

```powershell
$ErrorActionPreference='Stop'
& $reviewPython -B -m pyflakes isolated_identity_upload_check.py tests/test_isolated_identity_upload_check.py tests/test_isolated_alert_identity.py tests/test_isolated_alert_drill.py
if ($LASTEXITCODE -ne 0) {throw 'STOP_IDENTITY_LINT'}
$cache=Join-Path $env:TEMP ('mypy-identity-'+[guid]::NewGuid().ToString('N'))
& $reviewPython -B -m mypy --strict --cache-dir=$cache isolated_identity_upload_check.py
if ($LASTEXITCODE -ne 0) {throw 'STOP_IDENTITY_TYPES'}
```

## Builder verification, not native acceptance

Final focused four-file selection: Windows74passed/1skipped; Linux58passed/
17skipped. Windows symlink-privilege skip is covered on Linux; Linux skips17
WindowsPowerShell-only cases covered on Windows. PowerShell7 synthetic identity
and reconciliation cases run on both. Linux lacks Windows SID APIs and must
report UNRESOLVED rather than manufacture equality. Query/denied/link failures
are executable mocks; no real task/state/identity was queried by these tests.
Strict mypy1 new checker and pyflakes4 Python files pass both platforms.
Independent review found no remaining blocking source/package issue.
Full repository suite, real-base staged acceptance, exact-final-SHA hosted CI,
native reconciliation and real notification delivery remain owner acceptance.
The builder's working folder did not support the scoped git diff check; the
owner clean-clone git diff --cached --check remains required, not claimed passed.
