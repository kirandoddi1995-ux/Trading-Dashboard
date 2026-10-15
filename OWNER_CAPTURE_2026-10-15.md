# Owner procedure: one block at a time, 15 October 2026

## What is already known

Use only public main 1251530731cce5b75fad8601567b9320d07b710d for today's new
capsule. Do not copy the dirty kiran_share_market folder. Do not modify the
kiran_forward_20261014 capsule, its config/policy/journal/receipts/alert markers.
Nothing in this document was run on those private roots by the agent.

The old task's result **2** is only a process block/failure, not its cause and
not proof that it wrote nothing. The old scheduler saves scheduler receipts even
after blocked paths. Preserve the shared root and inspect dated scheduler-receipt
metadata privately. Never equate **0x80070002** with plain process exit 2: the
HRESULT also denotes an action file-not-found failure. Receipt-level evidence
and task event records determine which path ran.

14 October is a two-slot rehearsal *as reported*. The stale report wording does
not erase authenticated journal evidence, but two terminal exits alone cannot
prove valid evidence. Audit must verify exact code, environment, recipe, guards,
hashes and coverage. No remote custody or research eligibility inferred.

### Block 1 — establish private variables, deadlines, and disabled task state

Normal PowerShell, logged in as the account owning the credential vault and tasks.
Read-Host below asks paths, NOT tokens, passwords or connection strings. Keep
outputs private; share only redacted status/counts. An unknown path is a blocker.

```powershell
$ErrorActionPreference = 'Stop'
$sessionDate = '2026-10-15'
$reviewedMain = '1251530731cce5b75fad8601567b9320d07b710d'
$futureCode = 'C:\Users\banga\Desktop\kiran_forward_20261015'
$forwardPrivateState = Read-Host 'Existing private Forward state root (unchanged)'
$forwardOps = Read-Host 'Existing separate private ops-report root (unchanged)'
$pollName = 'KiranTrading-Versioned-20261015-poll'
$auditName = 'KiranTrading-Versioned-20261015-audit'
$ist = [TimeZoneInfo]::FindSystemTimeZoneById('India Standard Time')
function Now-Ist { [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $ist) }
function Require-Before([string]$hhmm) {
  $n = Now-Ist
  if ($n.ToString('yyyy-MM-dd') -ne $sessionDate -or $n -ge [DateTime]::ParseExact("$sessionDate $hhmm",'yyyy-MM-dd HH:mm',$null)) { throw 'STOP: deadline passed; leave new tasks disabled' }
}
Get-ScheduledTask -TaskPath '\' | Where-Object { $_.TaskName -like 'KiranTrading-*' } | Select-Object TaskName, State
```

Expect all capture tasks Disabled. If any is running, do not kill it or start a
second writer. Let it finish, classify unknown commits, then preserve/read-only
reconcile. A running/armed unknown task stops this sequence. Confirm the known
legacy audit is Disabled; it need not be disabled again or erased.

### Block 2 — preserve 14 October BEFORE any capture-root writer

Use the separately reviewed **forward_evidence_preserve.py** helper from this
package after its verification, or the owner's established verified
private backup procedure. This is NOT needed to upload before building public
code, but must happen before prepare/poll/audit writes in the shared state root.
The helper is standalone standard-library code: it may run from the reviewed
development file without installing anything into a frozen capsule. Public PR
upload is not capture activation. If the helper is not yet reviewed/available
and no verified owner backup exists,
do not replace this with an ad-hoc recursive copy of an active journal. Stop
capture commissioning and perform preservation first; a deadline may be missed.
Never upload evidence, private manifest, ops paths or credentials to GitHub.

```powershell
# $preservePython = existing reviewed interpreter; $preserveTool = reviewed helper
# in the DEVELOPMENT folder, not a new file installed into any frozen capsule.
$preservePython = 'C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
$preserveTool = 'C:\Users\banga\Desktop\kiran_share_market\forward_evidence_preserve.py'
$evidenceCopy = Read-Host 'NEW private backup directory outside all code/state/ops roots'
& $preservePython -B $preserveTool --source (Join-Path $forwardPrivateState '2026-10-14') --destination $evidenceCopy --session-date 2026-10-14
if ($LASTEXITCODE -ne 0) { throw 'STOP: preservation preview failed' }
# Confirm only after preview and all tasks disabled; follow the helper's manifest.
& $preservePython -B $preserveTool --source (Join-Path $forwardPrivateState '2026-10-14') --destination $evidenceCopy --session-date 2026-10-14 --confirm-preserve
if ($LASTEXITCODE -ne 0) { throw 'STOP: preservation not verified; retain partial output, do not retry over it' }
```

The destination parent must ALREADY have verified private permissions. The helper
does not set ACLs or repair permissions. If this blocks, stop; choose an already
private location or request a separately reviewed owner permission decision.
Machine SYSTEM/Administrators remain trusted; this is not an owner-only vault.
The helper's source/allowlist and sidecar restrictions are authoritative. A
local hashed copy is not independent encrypted custody or a full-image restore.
Do not report custody true. Top-level scheduler receipts and separate ops root
need separate preserved, read-only examination; this session helper does not
claim it copied them. New destination per attempt, retain failures.

### Block 3 — fresh exact-public capsule and its own virtual environment

This changes a NEW owner code directory only, never an old capsule. Internet is
needed for public clone/dependency installation, not tests or old audit. If any
step fails, do not continue and do not reuse a partial directory as a clean one.

```powershell
Require-Before '09:15'
if (Test-Path -LiteralPath $futureCode) { throw 'STOP: new capsule already exists; do not overwrite' }
git clone --config core.autocrlf=false --no-checkout --branch main --single-branch https://github.com/kirandoddi1995-ux/Trading-Dashboard.git $futureCode
if ($LASTEXITCODE -ne 0) { throw 'STOP: public clone failed' }
Set-Location -LiteralPath $futureCode
git checkout --detach $reviewedMain
if ($LASTEXITCODE -ne 0 -or (git rev-parse HEAD).Trim() -ne $reviewedMain) { throw 'STOP: reviewed commit unavailable; do not substitute a new revision' }
if (git status --porcelain) { throw 'STOP: public clone not clean' }
py -3.13 -c "import sys; assert sys.version_info[:3] == (3,13,9), 'Reviewed Python 3.13.9 required'"
if ($LASTEXITCODE -ne 0) { throw 'STOP: reviewed Python unavailable' }
py -3.13 -B -c "import hashlib; from pathlib import Path; p=Path('resilience_policy.json'); assert hashlib.sha256(p.read_bytes()).hexdigest()==p.with_suffix('.sha256').read_text().strip(), 'Approved policy byte checksum mismatch'"
if ($LASTEXITCODE -ne 0) { throw 'STOP: public byte materialization differs; never update the approved policy hash' }
py -3.13 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'STOP: new environment failed' }
$futurePython = Join-Path $futureCode '.venv\Scripts\python.exe'
& $futurePython -m pip install -r requirements-forward-operations.txt
if ($LASTEXITCODE -ne 0) { throw 'STOP: pinned environment install failed' }
& $futurePython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'STOP: dependency conflicts' }
& $futurePython -B future_ops_diagnostics.py --mode package --allow-read-only
if ($LASTEXITCODE -ne 0) { throw 'STOP: public closure check failed' }
& $futurePython -B future_ops_diagnostics.py --mode dependencies --allow-read-only
if ($LASTEXITCODE -ne 0) { throw 'STOP: installed versions mismatch' }
Require-Before '09:15'
```

Use a supported reviewed patch version; do not change environment checks or old
recipe pins because a different interpreter happens to be installed. Owner
credential vault stays unchanged and is NOT copied into this public clone.

### Block 4 — Windows Time owner resync, then READ-ONLY host inspection

If time-service settings already match, do not change them gratuitously. In an
ADMIN PowerShell only if needed, owner: `Set-Service w32time -StartupType Automatic`,
`Start-Service w32time`, then `w32tm /resync` once. Stop if resync fails; no capture
gate retry or automatic clock repair. Return to normal owner PowerShell for
all capture commands. Windows sync does NOT replace the producer's fresh NTP
measurement and one-second uncertainty/offset gate.

```powershell
Require-Before '09:15'
Get-CimInstance Win32_Service -Filter "Name='w32time'" | Select-Object State, StartMode
w32tm /query /status
if ($LASTEXITCODE -ne 0) { throw 'STOP: Windows Time query failed' }
powercfg /getactivescheme
powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE
powercfg /query SCHEME_CURRENT SUB_SLEEP HIBERNATEIDLE
```

Owner: AC power, lid open if laptop, sleep/hibernation off during capture, leave
this account LOGGED IN (locking is different from signing out). Check Settings →
Windows Update → active hours/restart scheduling so no restart is scheduled in
08:30–16:00. Do not disable updates globally. No agent settings changes or ACL
changes. InteractiveToken tasks do not promise execution when signed out.
Unknown stop at 12:48 is not diagnosed: Event Viewer → System, filter Service
Control Manager 7036/7040 and Kernel-Power/Power-Troubleshooter around that time;
Windows Time Operational and WindowsUpdateClient Operational if already enabled.
Retain only event times/IDs/public states, not raw messages/user paths. Do not
enable logs or delete service triggers just to make this morning pass.

### Block 5 — visible notification rehearsal, no capture

In the SAME normal interactive account/session, before enabling any task:

```powershell
Require-Before '09:15'
Add-Type -AssemblyName System.Windows.Forms
[void][System.Windows.Forms.MessageBox]::Show('REHEARSAL ONLY. No capture ran. Confirm you can see this message.', 'NIFTY notification rehearsal')
```

Owner must actually see and dismiss it. This establishes only this interactive
rehearsal, not future scheduler delivery. If invisible/unavailable, do not claim
notifications commissioned. No synthetic capture failure or old marker deletion.
14 October markers are day-pinned; new v2 15 October markers use a different
day/cause identity. Old markers are NOT rewritten or reused as delivery proof.

### Block 6 — generate and register exactly TWO date-pinned tasks DISABLED

Public planner returns THREE plans (including optional preflight). Register ONLY
poll and audit here; preflight is direct and remains before open. Never use old
raw-task plans/install scripts. Register-ScheduledTask errors terminate this block.

```powershell
Require-Before '09:15'
$ownerSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$planText = & $futurePython -B forward_ops_plan.py --session-date $sessionDate --owner-sid $ownerSid --code-directory $futureCode --python-executable $futurePython --state-root $forwardPrivateState --ops-root $forwardOps
if ($LASTEXITCODE -ne 0) { throw 'STOP: reviewed plan failed' }
$plan = ($planText -join "`n") | ConvertFrom-Json
if ($plan.status -ne 'REVIEW_ONLY_DISABLED') { throw 'STOP: wrong plan status' }
foreach ($name in @($pollName,$auditName)) {
  if (Get-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction SilentlyContinue) { throw 'STOP: target task already exists; inspect, never overwrite' }
}
foreach ($name in @($pollName,$auditName)) {
  $xml = [string]$plan.plans.$name
  if (-not $xml -or $xml -match '<\?xml') { throw 'STOP: plan absent or unexpected encoding declaration' }
  Register-ScheduledTask -TaskPath '\' -TaskName $name -Xml $xml -ErrorAction Stop | Out-Null
  $t = Get-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction Stop
  if ($t.Settings.Enabled -or $t.State -ne 'Disabled') { throw 'STOP: task is not disabled' }
}
```

If the second registration fails, the first is disabled; retain it and stop.
No optimistic success message. Actions must match Execute, ordered Arguments,
WorkingDirectory, exact date/root/code/interpreter and BOTH task names. Planner
uses hidden synchronous wrapper, owner InteractiveToken, no catch-up/restart-on-
failure, IgnoreNew, poll start09:30:30/end15:32, audit15:40. Read-only preflight
checks actions but not the trigger/principal/settings: owner must also review
Task Scheduler → each task → Triggers/General/Settings for those exact values.

### Block 7 — preflight ONLY before open

```powershell
Require-Before '09:15'
& $futurePython -B forward_session_ops.py --root $forwardPrivateState --ops-root $forwardOps --session-date $sessionDate --mode preflight --poll-task $pollName --audit-task $auditName --confirm-ops
if ($LASTEXITCODE -ne 0) { throw 'STOP: preflight blocked; no preparation or automatic polling' }
Require-Before '09:15'
```

Expected PREOPEN_HOST_CHECK_PASSED, clock PASS, both exact actions found, ≥1GiB
local reserve. It does not check provider/Drive/vault health. W32Time Auto/Running
does not prove NTP. Keep both new tasks disabled throughout supervised acceptance.

### Block 8 — real owner close download, config prepare and policy freeze

Before09:15 use browser direct official URL
`https://nsearchives.nseindia.com/content/indices/ind_close_all_14102026.csv`.
Record ACTUAL completion timestamp with +05:30 today; no example invented time,
file modification time or guessed source authenticity. Expected close14Oct.

```powershell
Require-Before '09:15'
$ownerCloseFile = Read-Host 'Private path to unmodified official 14 October CSV'
$ownerDownloadAt = Read-Host 'Actual observed 15 October download completion ISO timestamp with +05:30'
& $futurePython -B forward_nifty_schedule.py --root $forwardPrivateState --mode prepare --owner-close-file $ownerCloseFile --owner-download-at $ownerDownloadAt --attest-nse-source
if ($LASTEXITCODE -ne 0) { throw 'STOP: preview blocked' }
Require-Before '09:15'
& $futurePython -B forward_nifty_schedule.py --root $forwardPrivateState --mode prepare --owner-close-file $ownerCloseFile --owner-download-at $ownerDownloadAt --attest-nse-source --confirm-run
if ($LASTEXITCODE -ne 0) { throw 'STOP: preparation blocked; no overwrite/retry recipe' }
Require-Before '09:15'
& $futurePython -B forward_versioned_capture.py --root $forwardPrivateState --session-date $sessionDate --mode prepare-policy --confirm-versioned-research
if ($LASTEXITCODE -ne 0) { throw 'STOP: policy freeze blocked; leave tasks disabled' }
Require-Before '09:15'
```

Expect CONFIG_PREPARED_OWNER_FILE previous_close_date2026-10-14, clockPASS,
OWNER_ATTESTED_NOT_INDEPENDENTLY_VERIFIED; then VERSION_POLICY_PREPARED. Config
alone without policy is not ready. Failure may have written config: never delete,
change dates or overwrite it to try again. No preparation after open.

### Block 9 — one supervised09:20:30 poll, then one09:25:30 poll

Do not paste this block early to run a poll immediately. The bounded owner wait
is below; it never retries the producer. Run once for EACH target, second only
after first terminal acceptance. This strict owner wait refuses a target already
passed on entry. Producer keeps its own clock/license/source/lock gates.

```powershell
function Wait-FutureTarget([string]$clockTime) {
  $target = [DateTime]::ParseExact("$sessionDate $clockTime",'yyyy-MM-dd HH:mm:ss',$null)
  $previous = Now-Ist
  if ($previous -ge $target -or ($target-$previous).TotalSeconds -gt 900) { throw 'STOP: target passed or wait longer than15minutes; no catch-up' }
  do {
    Start-Sleep -Milliseconds 200
    $n = Now-Ist
    if ($n -lt $previous -or $n.ToString('yyyy-MM-dd') -ne $sessionDate) { throw 'STOP: clock moved backwards/date changed' }
    $previous = $n
  } while ($n -lt $target)
  if (($n-$target).TotalSeconds -gt 1) { throw 'STOP: interrupted wait; do not catch up' }
}
Wait-FutureTarget '09:20:30'
& $futurePython -B forward_session_ops.py --root $forwardPrivateState --ops-root $forwardOps --session-date $sessionDate --mode poll --poll-task $pollName --audit-task $auditName --confirm-ops
if ($LASTEXITCODE -ne 0) { throw 'STOP: first poll failed/unknown; do not repeat slot or enable tasks' }
```

Read result BEFORE proceeding: POLL_REMOTE_VERIFIED, codeREMOTE_VERIFICATION_COMPLETE,
stageLOCAL_RECEIPT_CONFIRMED, receipt_written/remote_verified/local_poll_committed
true, categoryNONE, clockPASS, expected versioned capture status. Private receipt
must exist and match this slot; no terminal report alone constitutes independent
custody. VERSIONED_INPUT_BLOCKED is raw evidence, NOT an accepted decision.
If interrupted or result unknown, stop and reconcile read-only, never same-slot
retry. Only after first acceptance, run this SECOND block once; do NOT repeat
the first wait or first command. Inspect second terminal result and receipt.

```powershell
Wait-FutureTarget '09:25:30'
& $futurePython -B forward_session_ops.py --root $forwardPrivateState --ops-root $forwardOps --session-date $sessionDate --mode poll --poll-task $pollName --audit-task $auditName --confirm-ops
if ($LASTEXITCODE -ne 0) { throw 'STOP: second poll failed/unknown; no same-slot retry or enabling' }
```

### Block 10 — enable audit FIRST, poll LAST, verify before09:30

Only after owner accepts BOTH exact supervised results/receipts and actually saw
notification rehearsal. Enter this block before09:30, never as a late catch-up.

```powershell
Require-Before '09:30'
Enable-ScheduledTask -TaskPath '\' -TaskName $auditName -ErrorAction Stop | Out-Null
$a = Get-ScheduledTask -TaskPath '\' -TaskName $auditName -ErrorAction Stop
if (-not $a.Settings.Enabled -or $a.State -ne 'Ready') { throw 'STOP: audit not enabled-ready; do not enable poll' }
Require-Before '09:30'
Enable-ScheduledTask -TaskPath '\' -TaskName $pollName -ErrorAction Stop | Out-Null
& $futurePython -B forward_morning_readiness.py --allow-read-only --session-date $sessionDate --code-directory $futureCode --python-executable $futurePython --state-root $forwardPrivateState --ops-root $forwardOps
$readinessExit = $LASTEXITCODE
if ($readinessExit -ne 0) {
  Disable-ScheduledTask -TaskPath '\' -TaskName $pollName -ErrorAction Stop | Out-Null
  throw 'STOP: readiness failed; future poll disabled, retain any running outcome'
}
$info = Get-ScheduledTask -TaskPath '\' -TaskName $pollName | Get-ScheduledTaskInfo
if ($info.NextRunTime.ToString('yyyy-MM-dd HH:mm:ss') -ne '2026-10-15 09:30:30') {
  Disable-ScheduledTask -TaskPath '\' -TaskName $pollName -ErrorAction Stop | Out-Null
  throw 'STOP: next trigger differs; no automatic admission'
}
```

Readiness exit0 is TASK_READINESS_CHECKED_ACCEPTANCE_PENDING, NOT proof of trigger
execution, custody or training. Observe first real scheduled09:30:30 poll and
its receipt. Task Scheduler result0 alone is insufficient. New blocked result:
inspect redacted report, do not retry; unknowncommit stays unknown. Last poll is
15:30:30. Date-pinned trigger expires; later disable both after bounded completion,
never delete tasks/history or force-stop an active invocation.

### Block 11 —15:40 new audit; preserve incomplete outcomes

Enabled new audit task must call forward_session_ops.py via the reviewed wrapper
with today date and same private roots. Legacy raw audit stays disabled. If no
task was enabled, use READ-ONLY audit manually after15:40, not old Producer audit:

```powershell
& $futurePython -B forward_session_ops.py --root $forwardPrivateState --ops-root $forwardOps --session-date $sessionDate --mode audit --poll-task $pollName --audit-task $auditName --confirm-ops --read-only-audit
$auditExit = $LASTEXITCODE
if ($auditExit -notin @(0,1)) { throw 'STOP: audit blocked/unknown; retain evidence without repairs' }
```

Exit1 can be valid INCOMPLETE coverage;2 is blocked. Every missing slot is
MISSING_NOT_OBSERVED; no zero-filled training rows. Always keep custody/training/
approval false. Freeze source capsule and private evidence once prepared; owner
source upgrade goes to NEXT capsule/session, not an in-place repair.

## Historical14Oct audit: do not change frozen pins

After preservation, try current code's `forward_session_ops.py --read-only-audit`
with --session-date2026-10-14 (same syntax as Block11). It may correctly block on
frozen source/environment mismatch. Do not bypass it. Separate original-capsule
historical audit procedure is in OVERNIGHT_CONTINUITY_2026-10-15.md; it uses the
original interpreter/validator and SELECT-only journal replay. No copy/install
inside original capsule; no old writable audit CLI, config patch or rollback.

## Daily permanence

This is intentionally supervised commissioning. Daily recipe/owner close/policy
must remain pre-open, one-date-only and immutable. Windows can schedule a
read-only pre-open health check later; no auto-resync or catch-up is commissioned.
Dependable regular operation still needs scheduler notification acceptance,
independent missed-run alert delivery, owner custody and a permitted automated
close source. Index capture is not F&O fills, market depth or licensed labels.
