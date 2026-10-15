# Nine-file task-binding recovery — one reviewed PR, no task deletion

Exact green base: 4764146106f6e80f0613b564d5bf27e84dee4ff5 (PR35 merged).
If main changes, STOP for reviewed reconciliation. Do not modify this base or
old manifest pins to get a pass. Historical33/seven-file packages remain records;
do not upload them again. This is three modified files and six additions.

## What the observations establish

OWNER-REPORTED: CheckSetup passed; Setup blocked at DISABLED_TASK_SETUP with
TASK_BINDING_FIELD_MISSING_OR_DUPLICATE. Read-only task export inspection found
the dated poll Disabled, audit absent, no duplicate required leaves. RunLevel,
triggerEnabled, StartWhenAvailable, WakeToRun and repetitionStop were omitted.
Native principal RunLevel is ENUM/LIMITED, task_enabledfalse. Nothing was changed.

SOURCE-VERIFIED: RunLevel is the first omitted field checked by the old validator.
The failure occurred in disabled-task readback, after capsule/environment/calendar
acceptance. Registration may already have happened. rollbackNOT_REQUIRED proves
only that this controller did not attempt polling enablement, NOT zero writes.
Setup cannot reach the Start-marker write; existing private markers were not
inventoried and must not be reset. native_exit_code0 is not task acceptance.
Task origin/creation time and every actual binding value remain unverified until
the new full read-only CheckTasks. Shape counts are not binding acceptance.

## Permanent contract, not XML editing

The coordinator compares EFFECTIVE task bindings while preserving the exact plan.
Planned fields must remain explicit and unique. Exported fields use only declared
Task Scheduler defaults; missing batteries/time-limit resolve to unsafe defaults
and therefore fail the reviewed planned-value comparison. Required actions,
identities, dates and duration remain strict. Duplicate ancestors/leaves fail.
Audit must be one-shot: unexpected repetition fails. No schedule/window/rule,
producer1251530731cce5b75fad8601567b9320d07b710d, source/policy/clock pin changes.

RunLevel is NOT inferred from the XSD. Positive typed native-principal readback
must establish Limited(enum0/typed integer0 or exact native stringLimited);
Highest, unknown, missing, false-as-boolean, string0 and wrong numeric enums fail.
An omitted exported RunLevel can then compare as LeastPrivilege. The planned
RunLevel must still be explicit. No task is rewritten to manufacture matching XML.

Missing/duplicate-field diagnostics identify role/field/source/count/reason without
values. Value mismatches report field/source/reason; generic query/state rejections
may have no field record and retain a fixed public code/stage. Registration
attempts and positively verified disabled roles are separate. Stage names separate
registration from readback. Known pre-Start failures say markerNOT_REACHED without
claiming a private-state inventory. Native errors never print raw text.

CheckTasks uses the unchanged Setup date gate and exact capsule/owner prerequisites.
It verifies EXISTING tasks disabled, reports absent roles, then exits BEFORE task
registration, notification, marker or capture. It is not Setup acceptance or GO.
Setup reuses a verified existing task; it never overwrites it. Query errors cannot
be treated as absence. Only absent tasks may be registered, explicitly disabled.
No automatic deletion, ACL repair, clock repair, retry, catch-up or enabling.

## Exact source -> destination list

```text
C:/Users/banga/Desktop/kiran_share_market/forward_daily_owner.ps1 -> forward_daily_owner.ps1
C:/Users/banga/Desktop/kiran_share_market/tests/test_forward_daily_owner.py -> tests/test_forward_daily_owner.py
C:/Users/banga/Desktop/kiran_share_market/FRIDAY_CAPTURE_2026-10-16.md -> FRIDAY_CAPTURE_2026-10-16.md
C:/Users/banga/Desktop/kiran_share_market/forward_task_binding_diagnostic.ps1 -> forward_task_binding_diagnostic.ps1
C:/Users/banga/Desktop/kiran_share_market/tests/test_forward_task_binding_diagnostic.py -> tests/test_forward_task_binding_diagnostic.py
C:/Users/banga/Desktop/kiran_share_market/task_binding_repair_upload_check.py -> task_binding_repair_upload_check.py
C:/Users/banga/Desktop/kiran_share_market/tests/test_task_binding_repair_upload_check.py -> tests/test_task_binding_repair_upload_check.py
C:/Users/banga/Desktop/kiran_share_market/TASK_BINDING_REPAIR_UPLOAD_2026-10-16.md -> TASK_BINDING_REPAIR_UPLOAD_2026-10-16.md
C:/Users/banga/Desktop/kiran_share_market/TASK_BINDING_REPAIR_UPLOAD_2026-10-16.json -> TASK_BINDING_REPAIR_UPLOAD_2026-10-16.json
```

No other files: no installed capsule, state, credentials, caches, local handoff,
AUTOMATION_PROGRESS.md, reviewed_stage tooling or historical manifests/checkers.
The added diagnostic stays outside clean tools during ad hoc owner use; do not
copy it into an older clean checkout and make that checkout dirty.

## Owner upload — one block at a time

1. NEW clean public clone, core.autocrlf=false, HEAD exactly4764146 above, clean
   status. Create the usual review branch. Copy/stage exactly the nine files.
   `$testPython` is the existing reviewed3.13.9 test interpreter; no installation.
2. New exact package checker (not the previous seven-file checker):

```powershell
$bindingBase = (git rev-parse HEAD).Trim()
& $testPython -B task_binding_repair_upload_check.py --base $bindingBase
if ($LASTEXITCODE -ne 0) { throw 'STOP: exact task-binding package failed' }
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw 'STOP: staged whitespace failed' }
```

3. Focused regression, fresh temp root (do not repair ACLs on old pytest roots):

```powershell
$bindingTemp = Join-Path $env:LOCALAPPDATA ('Temp\binding-focus-' + [guid]::NewGuid().ToString('N'))
& $testPython -B -m pytest -q -rs -p no:cacheprovider --basetemp $bindingTemp tests/test_forward_daily_owner.py tests/test_forward_task_binding_diagnostic.py tests/test_task_binding_repair_upload_check.py tests/test_forward_ops_plan.py tests/test_forward_daily_contract.py
if ($LASTEXITCODE -ne 0) { throw 'STOP: focused regression failed' }
```

Unavailable runtimes are explicit skips, NOT passes. PS7 is not required to use
the reviewed PS5.1 owner route. The changed tests use real generator output and
synthetic task commands/typed enums; no actual task registration was tested by
the builder. Full Windows/Linux results and independent review are recorded in
the local continuity/handoff, not inferred from focused collection.

```powershell
& $testPython -B -m pyflakes task_binding_repair_upload_check.py tests/test_task_binding_repair_upload_check.py tests/test_forward_daily_owner.py tests/test_forward_task_binding_diagnostic.py
if ($LASTEXITCODE -ne 0) { throw 'STOP: lint failed' }
& $testPython -B -m mypy --strict --follow-imports=silent task_binding_repair_upload_check.py tests/test_task_binding_repair_upload_check.py tests/test_forward_daily_owner.py tests/test_forward_task_binding_diagnostic.py
if ($LASTEXITCODE -ne 0) { throw 'STOP: strict typing failed' }
```

4. ONE owner-uploaded PR. Require quality/resilience/CodeQL and all required checks
   green on the EXACT FINAL commit. Then owner merges, verifies main checks, and
   makes a NEW clean merged tools checkout. No edits after green without new CI.
   No agent push/dispatch/hosted mutation is authorized.

## Owner recovery AFTER green merge — one command, inspect, next command

5. Normal non-elevated PowerShell in the NEW clean merged tools checkout, matching
   recorded merge SHA and clean Git status. Existing disabled poll must stay in
   place; do not delete, modify or manually recreate any task.

```powershell
$bootstrapPython = 'C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
.\forward_daily_owner.ps1 -SessionDate 2026-10-16 -Action CheckSetup -BootstrapPython $bootstrapPython -ConfirmRun
```

Require SETUP_PREREQUISITES_CHECK_PASSED_NOT_COMMISSIONED. Next:

```powershell
.\forward_daily_owner.ps1 -SessionDate 2026-10-16 -Action CheckTasks -BootstrapPython $bootstrapPython -ConfirmRun
```

Require EXISTING_TASK_BINDINGS_CHECKED_NOT_SETUP_ACCEPTANCE, existing_disabled_verified
poll, absent_roles audit for the reported starting state. The tool must establish
all effective bindings, not only the omitted fields. If state has changed, an
unexpected task exists, any binding mismatches, or a query is unavailable, STOP
for review. No deletion, replacement, pin relaxation or manual enablement.

6. After both read-only checks pass, ONE reviewed recovery Setup may complete the
   partial installation. This is not a poll/Start retry and does not reset a marker.

```powershell
.\forward_daily_owner.ps1 -SessionDate 2026-10-16 -Action Setup -BootstrapPython $bootstrapPython -ConfirmRun
```

Require SETUP_VERIFIED_TASKS_DISABLED and personally see/dismiss the harmless
notification. Expected registered_roles_attempted audit only, disabled_roles_verified
poll and audit. The exact existing poll is reused, not overwritten; audit is new
and disabled. A further block requires safe JSON/review, never blind repetition.

7. Fresh FRIDAY official download with ACTUAL completion time, Prepare, then Start
   exactly as FRIDAY_CAPTURE_2026-10-16.md. Setup+fresh Prepare by08:00 for08:00Start;
   hard09:15freeze; Start strictly before09:20:30. No deadline waiver because tests
   or uploads took time. If not safely accepted: NO_GO, tasks disabled, no backfill.
   Setup's deadline is checked before task operations, not again after them;
   completion after a deadline is NOT permission to prepare or capture late.
   Prepare and Start retain their separate deterministic deadline gates.
   No notification, clock, provider/Drive, custody, training or actual recurrence
   is certified by offline tests. Keep approved Python/base runtime installed.

## Technology radar and next leverage

Adopted: existing free PowerShell/Python/Git, primary Microsoft schema/native API
references, real pinned-generator fixtures, independent read-only review and
disposable Linux. Adapted: exact staged-manifest checking from the prior reviewed
package, with a NEW immutable baseline/control; old controls unchanged. Rejected:
generic optional-field ignoring, assumed RunLevel safety, XML/task rewriting,
deleting the poll, ACL changes, a paid service or an installer. Native COM
roundtrip requiring a Scheduler connection is not run on the owner's PC.

Next highest leverage remains a daily witness pack binding actual first scheduled
poll, final audit, gaps and alert delivery; task-enabled acknowledgement is not
successful capture. Historical audit/legacy writes, clock stop/dispersion, option
schedule skip reasons, storage commissioning and licensed frozen paper-study/
ML gates remain separate open items, not completion or Friday-readiness claims.

Primary references: [Task Scheduler schema](https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-schema),
[Principal privilege levels](https://learn.microsoft.com/en-us/windows/win32/taskschd/principal-runlevel).
They explain the distinction between declared defaults and positive native
privilege proof; the owner's read-only observation supplies the actual PC fact.
