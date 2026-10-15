# Seven-file follow-up — diagnosable Setup, no pin or permission bypass

Base: d5cd80f41a52de902d23cb81d761e7bb720e710c. One owner-reviewed PR on that exact
green main tree; no direct push/main upload. If main has moved, STOP for reviewed
reconciliation. Do not edit BASE or historical manifest pins to force a pass.

## What is known

OWNER-REPORTED: PR34/f2b26f7 and main d5cd80f green; Setup blocked at the broad
REVIEWED_TOOLS_CHECKOUT stage with generic code/empty blockers. Direct Git root,
exit and clean checks passed in verified elevated and normal PS5.1 windows.
Subsequent owner checks: `py` unavailable; existing reviewed project test venv
prints3.13.9 and exits0. No installation or pin change is needed for that runtime.

VERIFIED IN SOURCE: that stage included Git checks, `py -3.13` bootstrap pin and
private-ops read-only permission validation. It precedes capsule writes, tasks
and the Start attempt marker. That attempt could not have created a no-retry
marker. This is a control-flow conclusion, not a private-state inventory or a
claim that no other process wrote anything. Elevation would reject earlier at
NORMAL_WINDOW_CHECK. Neither tools folder name nor merge shape is an expected-SHA
test; the pinned125 SHA applies to the separate producer capsule, unchanged.

The unavailable launcher is a sufficient cause of the old pre-write bootstrap
failure. NOT VERIFIED: private-ops and later real Setup acceptance. An initial
scope hypothesis was rejected
after correct literal-file/nested-file tests; LASTEXITCODE handling and path
normalization remain unchanged. Do not call this an established native-scope fix.

## Design

Adopt an explicit reviewed local `-BootstrapPython` executable for ALL controller
actions that need Python, with isolated execution and exact3.13.9/positive-sentinel
proof; no py launcher, PATH fallback, auto-install or version relaxation. It
creates a NEW capsule venv rather than copying or editing an installed environment.
Keep its approved base runtime installed: venvs are not standalone distributions.
No dirty-project modules are imported by the isolated bootstrap commands.

Add read-only CheckTools (public Git only) and CheckSetup (shared normal-token,
Git, pinned interpreter and private-ops checks, then EXIT BEFORE writes). Add
actual whole-file synthetic repository tests, distinct pre-write stages and
fixed public diagnostics. Keep original
producer, source, recipe, clock, version, no-catch-up and Start marker gates.
Git cleanliness query uses --no-optional-locks to avoid its optional index refresh.
CheckTools never reaches Windows identity, private ops, Python, capture or tasks.
CheckSetup reads the existing private-ops permission metadata as the owner, not
capture data, credentials or journal contents. Neither commissions capture.
Setup keeps its normal-token, exact Python3.13.9 and unchanged permission checks.
Known rejections retain a fixed code and blockers; unexpected exception text,
Git output, paths, filenames, identities and secrets are never printed.

Rejected: installing a launcher when a valid reviewed interpreter already exists,
guessing additional root causes, changing ACL/ownership/safe.directory, running
Setup elevated, resetting markers or relaxing producer/interpreter pins. Deferred:
new workflow services/LLMs. Existing PowerShell, Git, pytest and disposable Linux
are the zero-incremental-cost tools for this milestone. Builder and reviewer are
separate. Highest-leverage next improvement remains a dated witness pack binding
actual recurrence, audit and gaps, not an enable acknowledgement alone.

## Exactly seven source -> destination paths

```text
C:/Users/banga/Desktop/kiran_share_market/forward_daily_owner.ps1 -> forward_daily_owner.ps1
C:/Users/banga/Desktop/kiran_share_market/tests/test_forward_daily_owner.py -> tests/test_forward_daily_owner.py
C:/Users/banga/Desktop/kiran_share_market/FRIDAY_CAPTURE_2026-10-16.md -> FRIDAY_CAPTURE_2026-10-16.md
C:/Users/banga/Desktop/kiran_share_market/daily_setup_repair_upload_check.py -> daily_setup_repair_upload_check.py
C:/Users/banga/Desktop/kiran_share_market/tests/test_daily_setup_repair_upload_check.py -> tests/test_daily_setup_repair_upload_check.py
C:/Users/banga/Desktop/kiran_share_market/DAILY_SETUP_REPAIR_UPLOAD_2026-10-15.md -> DAILY_SETUP_REPAIR_UPLOAD_2026-10-15.md
C:/Users/banga/Desktop/kiran_share_market/DAILY_SETUP_REPAIR_UPLOAD_2026-10-15.json -> DAILY_SETUP_REPAIR_UPLOAD_2026-10-15.json
```

Do NOT upload progress/local handoff, scope probes, caches, private files,
installed capture/state, old manifests or the whole source folder. Exactly three
modified files and four additions. Old20/33 controls remain byte-identical.

## Owner upload blocks — stop after each output

1. Normal PowerShell, NEW clean public clone with core.autocrlf=false. Check HEAD
   equals the exact base above and status is empty. Create the review branch by
   the usual owner routine; do not run capture from it.
2. Copy/stage ONLY the seven listed files, preserving tests/. Record base before
   copying. Use the existing reviewed test interpreter as `$testPython`.
3. Run the exact new checker, not the historical33 checker:

```powershell
$setupBase = (git rev-parse HEAD).Trim()
& $testPython -B daily_setup_repair_upload_check.py --base $setupBase
if ($LASTEXITCODE -ne 0) { throw 'STOP: exact follow-up package failed' }
$setupTemp = Join-Path $env:LOCALAPPDATA ('Temp\setup-focus-' + [guid]::NewGuid().ToString('N'))
& $testPython -B -m pytest -q -rs -p no:cacheprovider --basetemp $setupTemp tests/test_forward_daily_owner.py tests/test_daily_setup_repair_upload_check.py tests/test_forward_daily_contract.py tests/test_forward_morning_readiness.py tests/test_forward_session_ops.py tests/test_nse_owner_close.py tests/test_project_conductor.py tests/test_daily_owner_upload_check.py
if ($LASTEXITCODE -ne 0) { throw 'STOP: focused regression failed' }
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw 'STOP: whitespace failed' }
```

The earlier owner result1092passed+52skipped equals1144collected focused cases.
That is consistent with one missing PowerShell runtime; read the -rs reasons to
confirm which. Our earlier environment had PS5.1 AND PS7. Neither skipped tests
nor a developer-host pass prove owner Setup. No PS7 installation is required to
operate the reviewed PS5.1 route; unavailable-runtime skips stay explicit.

4. Owner uploads ONE PR; require quality/resilience/CodeQL green for its exact
   FINAL commit, then owner merges and verifies main. No changes after green
   without new checks. Full/type/lint verification is retained in local progress:

```powershell
& $testPython -B -m pyflakes daily_setup_repair_upload_check.py tests/test_daily_setup_repair_upload_check.py tests/test_forward_daily_owner.py
& $testPython -B -m mypy --strict --follow-imports=silent daily_setup_repair_upload_check.py tests/test_daily_setup_repair_upload_check.py tests/test_forward_daily_owner.py
```

Check each native exit; do not call a failed first command passed because the
second succeeded. Disposable Linux verification is separate from hosted Ubuntu
CI; unavailable PowerShell cases are explicit skips, not passes. Runtime imports
are unchanged except the owner-only new checker importing the unchanged pinned
public checker helpers. Production fingerprint and Streamlit expectations stay
unchanged; release hold, collectors and workflows stay unchanged.

## After merge — one command at a time

5. NEW clean checkout of the recorded merge SHA; verify normal-token false via
   WindowsPrincipal.IsInRole(Administrator), clean Git status and matching HEAD.
   In normal PowerShell set the existing reviewed interpreter and run CheckSetup:

```powershell
$bootstrapPython = 'C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
.\forward_daily_owner.ps1 -SessionDate 2026-10-16 -Action CheckSetup -BootstrapPython $bootstrapPython -ConfirmRun
```

   Require SETUP_PREREQUISITES_CHECK_PASSED_NOT_COMMISSIONED. This is not clock,
   source, notification, task or capture acceptance. Narrower CheckTools is
   available for a public-Git-only check, not as a substitute for CheckSetup.
6. Then ONE reviewed Setup invocation for16October. This is an owner-authorized
   reviewed preparation attempt after a pre-write failure, NOT a market-slot
   retry and NOT a Start retry. Do not remove any marker. Require
   SETUP_VERIFIED_TASKS_DISABLED. Include `-BootstrapPython $bootstrapPython`.
   If blocked, stop/share only safe JSON. A Python
   or permissions failure still blocks; never fix it by weakening a pin or ACL.
7. Friday morning only: genuine official download and ACTUAL completion time,
   Prepare, then one Start. Follow FRIDAY_CAPTURE_2026-10-16.md. Thursday download
   is ineligible. Successful Setup Thursday evening is the target; Setup and
   fresh preparation by08:00 are needed for08:00Start. Hard09:15freeze and
   strictly-before09:20:30Start remain. If not safely ready: NO_GO, no backfill.
   Supply the same explicit BootstrapPython parameter to Prepare, Start and any
   manual Audit; scheduled producer tasks use their own reviewed capsule Python.

Primary references: [Python venv behavior](https://docs.python.org/3.13/library/venv.html),
[Python Windows launcher/manager behavior](https://docs.python.org/3/using/windows.html),
and [Git optional locks](https://git-scm.com/docs/git#Documentation/git.txt---no-optional-locks).
Launcher/manager auto-install/dry-run behavior is another reason to avoid it here;
the explicit executable must return an actual isolated version proof. These docs
inform the design; they are not evidence of the owner's Setup succeeding.

14Oct historical audit/legacy writes, actual alert delivery, time-service root
cause, option-schedule settings, storage custody/restore/retention and licensed
paper-study/ML gates remain separate open investigations, not Friday-ready claims.
