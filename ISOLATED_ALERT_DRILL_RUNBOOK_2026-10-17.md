# Isolated full failure-route drill — owner commissioning after merge

Not yet native-proven. This procedure is for one supervised synthetic task,
after exact-final-SHA CI is green and the owner merges this package. Do not run
it from the working source folder or copy it into an installed capture capsule.
Use a fresh clean reviewed tools checkout. Monday's manual route does not need it.
The controller checks the Git root, clean status and tracked drill files before
commissioning. Keep its checkout unchanged. This is not authorization to trust an
arbitrary clean local commit: the owner must first verify the reviewed merged SHA.

## Scope, exactly

The worker extracts exact SHA-pinned production function bodies: failure report
save, category selection, once-marker/launch records, notification transport and
write-once publication. It does not import capture/health modules or invoke the
producer, source APIs, clock probes or credentials. It deliberately submits a
SYNTHETIC CLOCK_UNVERIFIED report into a new isolated directory. No real clock is
changed and no poll fails deliberately. The actual production failure detector,
producer CLI, independent alerts and outage delivery remain separate/unproven.
The pins bind reviewed public-main sources at597a19d, not an independent read of
the installed capsule's function bytes. Native success cannot establish that
installed-capsule equivalence; no capsule is inspected or replaced by this drill.

Only one exact task named `ResearchOps-SyntheticAlert-<32hex>` can be changed.
It has no triggers, starts Disabled, Interactive/Limited, no wake/catch-up/restart,
two-minute execution limit and IgnoreNew. It is manually started once, not put on
a recurring schedule. Setup enumerates existing task metadata without printing it;
subsequent task queries and mutations address only this synthetic name.

State is only `%LOCALAPPDATA%\KiranTrading\AlertDrills\<32hex>`; there is no capture
root argument. Never edit this state, reuse an uncertain ID, erase a marker or
retry an attempt. On BLOCKED/unknown stop and share only redacted JSON. Preserve
all files/task definitions; do not delete/unregister anything to make it pass.
Do not generate a new ID to evade a blocked/unknown attempt; review it first.
Binding failures name only fixed field keys (for example run_level/no_restart),
never the actual account, command, arguments or paths. Share these keys and the
fixed reason/stage; do not export full task XML or raw native error messages.
There are no ACL, service, privilege, time, firewall or hosted changes.

Allowed only weekend or after16:00IST, normal non-Administrator Windows session,
with the personally true no-capture-running attestation. Leave all capture tasks
and installed files alone. Keep the interactive desktop available for the popup.

## Run one block at a time; stop on any unexpected status or nonzero exit

In the fresh merged tools checkout, normal PowerShell, block1:

```powershell
$ErrorActionPreference='Stop'
$drillPython='C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
$nativePowerShell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
& $drillPython -I -B -c "import sys; print(sys.version.split()[0]); assert sys.version_info[:3] == (3,13,9)"
if ($LASTEXITCODE -ne 0) {throw 'PINNED_PYTHON_REQUIRED'}
$drillId=[guid]::NewGuid().ToString('N')
```

Require3.13.9/exit0. Keep these variables in this window; generate the ID once.
Block2, inert preview (does not read files or query tasks):

```powershell
$ErrorActionPreference='Stop'
& $nativePowerShell -NoProfile -File .\isolated_alert_task_drill.ps1 -Action Setup -DrillId $drillId -Python $drillPython
if ($LASTEXITCODE -ne 0) {throw 'STOP_REVIEW_PREVIEW'}
```

Require PREVIEW with all counters0. Block3 explicitly creates isolated state and
registers only the new disabled dummy task:

```powershell
$ErrorActionPreference='Stop'
& $nativePowerShell -NoProfile -File .\isolated_alert_task_drill.ps1 -Action Setup -DrillId $drillId -Python $drillPython -ConfirmNoCaptureRunning -ConfirmRun
if ($LASTEXITCODE -ne 0) {throw 'STOP_REVIEW_SETUP_NO_RETRY'}
```

Require `ISOLATED_DUMMY_TASK_REGISTERED_DISABLED`; no capture task is enabled.
Note its eight-letter `correlation_code` (letters a-p). It is a public drill
identifier, NOT a credential or provider token. Match it against the popup.
If registration/readback is uncertain, do not repeat Setup or start anything.
Block4 is the single native attempt. Watch for the existing notifier's caption
`NIFTY capture alert` containing **synthetic <correlation_code> clock review required**.
This is this drill, not a production incident. Read and dismiss it with OK promptly.
After Start returns, the polling loop has a150-second monotonic budget, not a hard
end-to-end timeout: synchronous Scheduler calls can stall. A stall is an unknown
outcome, never permission to restart the command or reset its attempt marker:

```powershell
$ErrorActionPreference='Stop'
& $nativePowerShell -NoProfile -File .\isolated_alert_task_drill.ps1 -Action Run -DrillId $drillId -Python $drillPython -ConfirmNoCaptureRunning -ConfirmRun
if ($LASTEXITCODE -ne 0) {throw 'STOP_REVIEW_RUN_NO_RETRY'}
```

Expected `ISOLATED_FAILURE_ROUTE_RECORDED_AWAITING_OWNER_ACK`, scheduler_result2,
launch_acknowledgedtrue and task_disabled_owner_witnesstrue. The dummy worker's
exit2 is intentional; the controller itself returns0 only after the synthetic
route and disabled-task witness check pass. `popup_seen:null` means not yet
attested, not that the owner did not see it. A launch is not delivery proof.

The controller writes its exclusive attempt marker BEFORE enabling. Any unknown
Start outcome consumes that attempt. It disables the exact synthetic task on
normal completion and attempts disable in finally on a failure after enable.
If readback/disable is unknown the result stays unknown; best effort is not proof.
Do not rerun even if a marker seems absent. Share the fixed reason/stage and wait
for reviewed read-only reconciliation. No administrative fallback is authorized.

Only if you personally saw that synthetic popup and dismissed it, block5:

```powershell
$ErrorActionPreference='Stop'
$seenCode=Read-Host 'Type the eight-letter code from the synthetic popup you personally saw (NOT a password/token)'
& $nativePowerShell -NoProfile -File .\isolated_alert_task_drill.ps1 -Action Acknowledge -DrillId $drillId -Python $drillPython -SeenCode $seenCode -ConfirmNoCaptureRunning -ConfirmNotificationSeen -ConfirmRun
if ($LASTEXITCODE -ne 0) {throw 'STOP_REVIEW_ACK_NO_RETRY'}
```

Require `ISOLATED_FAILURE_ROUTE_OWNER_ACKNOWLEDGED`. The acknowledgement is
write-once OWNER_ATTESTED synthetic visibility, not a cryptographic human identity
or independent delivery proof. `production_failure_verified:false` and
`independent_delivery_verified:false` correctly remain false.

Keep the finished synthetic task disabled and retain its isolated records. No
recurring trigger exists. No capture task is changed. Share only redacted status,
stage/reason and whether the popup was personally seen, never private paths or
report contents. If the popup did not appear, do not attest, rerun or reset markers.

Later read-only inspection of these existing drill records (same pinned tools):

```powershell
$ErrorActionPreference='Stop'
& $nativePowerShell -NoProfile -File .\isolated_alert_task_drill.ps1 -Action Inspect -DrillId $drillId -Python $drillPython -ConfirmNoCaptureRunning -ConfirmRun
if ($LASTEXITCODE -ne 0) {throw 'STOP_REVIEW_INSPECTION'}
```

Inspect validates historical controller/worker/report/alert/launch/task-witness
records; it does not make a new native task query. Its task-disabled field refers
to that recorded witness, not a fresh observation. If the existing owner-ack is
valid, status is ISOLATED_FAILURE_ROUTE_ACK_RECORDED with its owner-attested
provenance. This reports the retained attestation, not a new human acknowledgement.

## What acceptance proves and what it does not

A successful owner drill demonstrates one limited task -> deliberate fixture
failure -> pinned report/category/dedup/launch functions -> existing local popup
transport -> explicit owner-seen acknowledgement path, isolated from production.
It does not exercise the production producer/import graph, simulate an actual
clock outage, prove every failure category, certify future popup visibility,
establish outage-independent alerting or commission real capture/storage alerts.
Those limits remain in the programme acceptance record after a success.
