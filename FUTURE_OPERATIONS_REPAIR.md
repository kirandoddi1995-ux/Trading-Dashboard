# Future operations repair — inactive public package

Reviewed public main: `da4a9be7d5b3e805c76cc7c677795d6eebd33a36`, in
`C:/Users/banga/AppData/Local/Temp/overnight-main-da4a9be`.
Only six new files belong to this group:

- `future_ops_diagnostics.py`
- `requirements-forward-operations.txt`
- `tests/test_future_ops_diagnostics.py`
- `future_ops_task.ps1`
- `FUTURE_OPERATIONS_REPAIR.md`
- `MORNING_CARD_2026-10-14.md`

Main owns the per-group JSON and shared `overnight_programme_upload_check.py`.
No existing source, manifests, progress, installed capsule, private state,
credentials, scheduled tasks or hosted system was modified. Installed folders,
private state, credentials and real tasks were not inspected. No installation,
push or hosted write was performed. Current capture remains outside this repair.

## Dependency closure

The public static closure rooted at `forward_session_ops.py` reaches 33 local
modules, including lazy imports in poll and audit. It imports `numpy`, `pandas`,
`pyarrow`, `google.auth`/`google.oauth2`, `requests`, `urllib3` and `cryptography`.
For example, operations reaches replay/technical indicators and therefore NumPy
and pandas; archive code reaches Arrow and Google authentication. A narrow archive
requirements file alone does not install that complete import set. Missing NumPy
is a dependency blocker already covered by the owner's full public requirements,
not evidence that the capture source needs modification.

The new requirements file explicitly pins those seven distribution roots, their
publicly constrained runtime dependencies, and `tzdata` for Windows zone data:
18 entries. Every version is copied from public `requirements.txt`,
`requirements-archive.txt` or `constraints.txt`; constraints limit versions but do
not themselves install packages. The checker validates all 18 pins and follows
local AST import edges without importing capture code. Unknown external imports
block packaging. Metadata checks do not prove binary loading or successful
provider authentication. This is full static import coverage, not a newly resolved
wheel lock or a claim that any environment was installed here. The owner must
perform `pip check` and import acceptance in the separate future environment.

## Diagnostic contract

`python -B future_ops_diagnostics.py` returns `PREVIEW` with zero diagnostic IO:
no path resolution, dependency lookup, clock/task query, notification or callback.
JSON output itself is the only output. Imports are standard library only.

Explicit `--allow-read-only` permits only the selected mode:

```powershell
python -B future_ops_diagnostics.py --mode package --allow-read-only
python -B future_ops_diagnostics.py --mode dependencies --allow-read-only
# Owner-only future-host query; not executed by this agent:
python -B future_ops_diagnostics.py --mode clock --allow-read-only
python -B future_ops_diagnostics.py --mode task --task-name KiranFuture-rehearsal --allow-read-only
```

`package` reads only public source/requirements in its own capsule. `dependencies`
queries distribution metadata without importing capture. `clock` executes only
`w32tm.exe /query /status`; it discards raw output and never claims the capture NTP
guard passed. `task` permits only an explicit root-folder `KiranFuture-*` identity
and returns classified state/result, never action arguments or principal details.
Task state and process exit zero are informational, never commissioning approval.
All subprocess diagnostics have a 12-second timeout. Exceptions are classified
and redacted; failures exit 2. No service start/config/resync, task registration,
enabling, retry, capture read/write, credentials or provider operations exist.

The unchanged producer queries `time.cloudflare.com` directly via UDP and retains
its one-second offset/uncertainty guard. Windows Time service state/query success
cannot substitute for this independent measurement. A service startup setting
alone does not establish clock correctness or the cause of a rejected probe.
Owner service/network repair is separate, before capture, with host policy review.
Microsoft documents read-only `/query` separately from mutating `/config` and
`/resync`: [Windows Time tools](https://learn.microsoft.com/en-us/windows-server/networking/windows-time-service/Windows-Time-Service-Tools-and-Settings).

## Parent-exit hypothesis and separate rehearsal

A PowerShell parent may finish before a detached child when it starts a process
without waiting. `-Command` can also collapse a native nonzero exit to 1 unless
the script explicitly propagates it. These are hypotheses to check against future
action history, not established causes of today's outcomes. The existing public
`forward_ops_task.ps1` already uses `-Wait -PassThru` and `exit $process.ExitCode`;
there is no public-source evidence requiring it to be overwritten.

The new `future_ops_task.ps1` is a synthetic diagnostic launcher only. It directly
invokes the Python child synchronously and explicitly exits `$LASTEXITCODE`.
It has no capture arguments, no route to poll/audit/preflight, and no task/service
mutation. Use a future action with `powershell.exe -NoProfile -NonInteractive
-File` and absolute reviewed paths; do not use a detached parent, `-NoExit`, or a
surrounding command that masks the exit. Microsoft describes `-File` exit behavior
and explicit native exit preservation in [about PowerShell.exe](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_powershell_exe?view=powershell-5.1).

Owner rehearsal may run after 09:15 IST on the declared date, even though the
original capture preflight correctly refuses after-open execution. It does not
call that preflight or relax its guard. Before permission, launcher preview exits
without testing paths or starting children. Owner-only acceptance commands:

```powershell
# Set $futureCode and $futurePython to the reviewed NEW capsule/environment.
& powershell.exe -NoProfile -NonInteractive -File "$futureCode/future_ops_task.ps1"
# Must report PREVIEW, parent exit 0, no child.
foreach ($expected in @(0,1,2)) {
    & powershell.exe -NoProfile -NonInteractive -File "$futureCode/future_ops_task.ps1" -PythonExecutable $futurePython -SessionDate 2026-10-14 -SyntheticExit $expected -AllowRehearsal
    if ($LASTEXITCODE -ne $expected) { throw 'STOP: future parent exit mismatch' }
}
& powershell.exe -NoProfile -NonInteractive -File "$futureCode/future_ops_task.ps1" -PythonExecutable $futurePython -SessionDate 2026-10-14 -AllowRehearsal -NotifyLocal
if ($LASTEXITCODE -ne 0) { throw 'STOP: future notification launch failed' }
```

Notification launch is not delivery proof. Owner must see and dismiss the exact
synthetic message in the intended interactive session and retain a dated redacted
acceptance note. This uses a detached local UI so the child can finish; missing
interactive UI/assembly may prevent display despite successful launch. No
notifications or native rehearsal were executed here. No new scheduled task is
registered by this package. A future synthetic task requires separate owner
commissioning; enabled capture tasks remain forbidden until full acceptance.

Task results: `0x41301` means running; `0x41302` disabled; `0x41303` never run.
They are scheduler states, not capture failures. `0x80070002` is a file-not-found
HRESULT, distinct from process exit decimal 2 (`0x2`). `0xC000013A` is termination;
neither the actor nor capture commit is established by that result. Signed and
unsigned 32-bit forms are classified identically. Never infer a committed slot
from exit zero or repeat a slot after unknown commit. Sources:
[Task Scheduler constants](https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-error-and-success-constants),
[Windows error codes](https://learn.microsoft.com/en-us/windows/win32/debug/system-error-codes--0-499-),
[NTSTATUS values](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-erref/596a1078-e883-4972-9bbc-49e60bebca55).

## Offline verification and handoff

Run in the reviewed public clone, with no installation:

```powershell
python -B -m unittest discover -s tests -p test_future_ops_diagnostics.py -v
python -B -m mypy --strict --follow-imports=normal --no-incremental --cache-dir=nul future_ops_diagnostics.py tests/test_future_ops_diagnostics.py
python -B -m pyflakes future_ops_diagnostics.py tests/test_future_ops_diagnostics.py
python -B future_ops_diagnostics.py --mode package --allow-read-only
python -B future_ops_diagnostics.py --mode clock
```

The test suite uses fake subprocesses/version responses and fixed times; native
launcher assertions inspect only the new source. It verifies the public AST
closure, missing pins/imports, timeout/access/malformed response redaction, separate
permissions, existing-task exclusion, signed codes, after-open boundary and
notification failure/launch distinction. Runtime PowerShell exit propagation and
visible notification remain owner acceptance blockers, not asserted tested here.
The local mypy version is 1.17.1, pyflakes 3.2.0, Python 3.13.9; public development
requirements pin mypy 2.4.0, which was not installed by this agent. Python emits
an existing real-location warning before execution; checks still return normally.

Recorded results: 14/14 unit tests passed; strict mypy reported no issues in both
files; pyflakes produced no findings; public package check returned
`PUBLIC_IMPORT_CLOSURE_PINNED`; unpermissioned clock mode returned `PREVIEW`.
All these commands exited 0. `git diff --exit-code` exited 0 and the untracked
file inventory was exactly the six owned files. No real dependency/clock/task
host check, notification, installation or capture run was performed.
`powershell.exe -NoProfile -NonInteractive -File C:/Users/banga/AppData/Local/Temp/overnight-main-da4a9be/future_ops_task.ps1`
also returned `PREVIEW` and exited 0; it started no Python child.

Upload only the six named files through main's group checker. No broad copy from
the working directory and no update to existing manifests/progress/checkers.
Main must review exact new bytes and run its shared package gate on final main;
this group's static dependency check does not authorize upload, merge, install,
capture commissioning, trading, training or task enabling.
