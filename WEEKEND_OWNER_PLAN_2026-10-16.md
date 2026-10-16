# Friday complete; weekend order and Monday routine

## What Friday established

OWNER-REPORTED, not a builder read of private evidence: manual read-only Audit
VERSIONED_COVERAGE_COMPLETE;75raw polls/75recorded/0missing; all75slots09:20–15:30
OBSERVED_DECISION. Generation:
17f7fbd62eafd8770ef2370becc5936a8fef16e4d6d71bee03f66d0ac08aabe9.
capture_writes0, operational_cause_per_slotNOT_ESTABLISHED, full_session_cohort_eligible,
training_eligible and remote_custody_verified allFALSE. No promotion/replay/retuning.

At18:03 owner read task state: poll last15:30:31/result0/missed0; audit last15:40:00/
result0/missed0. BothReady with no next run. Scheduled audit ran; its report content
was not independently read by builder. The manual audit separately supplies the
coverage/generation witness. No visible blocked-poll alert proof exists; a healthy
75-slot day would not be expected to trigger one. Data completeness is not custody,
licence approval, a frozen-study admission, a fill label or a learned trading edge.
See FRIDAY_COMPLETION_WITNESS_2026-10-16.json: owner metadata only, not a signature.

## 1. Retire Friday's tasks, do not erase anything

Keep Friday capsule/state/reports/markers and task definitions. No uninstall,
unregister, journal reset or recipe edit. These are date-pinned TimeTriggers with
end boundaries, not next-day recurring capture. Ready/no next trigger alone does
not prove bindings, but does not imply a Monday run. Disable the finished exact
two tasks as hygiene AND because the reviewed Setup refuses any old capture task
that is not Disabled. No broad disable-all command.

Owner may run this ONE block in normal PowerShell after preserving the audit.
It explicitly authorizes disabling only the two16Oct tasks, no deletion or edits
to their actions/triggers. The builder has NOT run it:

```powershell
$finishedNames = @('KiranTrading-Versioned-20261016-poll','KiranTrading-Versioned-20261016-audit')
foreach ($finishedName in $finishedNames) {
    $finishedTask = Get-ScheduledTask -TaskPath '\' -TaskName $finishedName -ErrorAction Stop
    if ([string]$finishedTask.State -cnotin @('Ready','Disabled')) { throw 'FINISHED_TASK_RUNNING_QUEUED_OR_UNKNOWN_STOP' }
}
foreach ($finishedName in $finishedNames) {
    Disable-ScheduledTask -TaskPath '\' -TaskName $finishedName -ErrorAction Stop | Out-Null
    $finishedTask = Get-ScheduledTask -TaskPath '\' -TaskName $finishedName -ErrorAction Stop
    if ($finishedTask.Settings.Enabled -isnot [bool] -or $finishedTask.Settings.Enabled -ne $false) { throw 'DISABLE_NOT_VERIFIED_STOP' }
}
[pscustomobject]@{status='FINISHED_16OCT_TASKS_DISABLED_VERIFIED';roles=2;deletions=0;capture_writes=0} | ConvertTo-Json -Compress
```

If partial/unknown, stop and inspect; do not re-enable either or blindly repeat.
This is not a capture-slot retry. Do not change unrelated or legacy tasks here.

## 2. Upload the refreshed package, replacing the unuploaded18-file version

Use FORWARD_OBSERVER_UPLOAD_2026-10-16.md/json: ONE22-file additive PR at exact
green base0b0aad4efa102643cc5dc4073dc7fc915281c1bf. New exact hashes/checker replace
the earlier unuploaded manifest. No runtime files inside Friday are changed.
Require pre-commit package check, focused tests and green CI on final SHA, then
owner merge. If main moved, reconcile before copying; never loosen hash/base pins.

The new forward_guided_owner.ps1 stays OUTSIDE the pinned clean tools checkout.
It delegates only to the unchanged coordinator in the clean0b0aad4 tools checkout;
does not copy itself there. It verifies both coordinator/contract hashes, clean
Git state/exact HEAD, non-admin context and explicit interpreter. Core calendar,
source, licence, fresh NTP, slot, admission and marker gates stay in that coordinator.
No generic command parameter, alternate Python, bypass, silent attestation or retry.

## 3. Weekend Setup ahead: Monday first, Wednesday second

The existing reviewed coordinator already supports Setup up to7days ahead.
This weekend is suitable for19Oct and21Oct.20Oct is closed; never set up polling
for it. The actual pinned calendar must agree; a date in this document is not a gate.
Prepare is NOT done this weekend. Fresh download/Prepare remain session-morning.

You do NOT have to wait for the new wrapper to do Setup with the existing green
routine. In its NORMAL clean tools checkout, one date at a time:

```powershell
.\forward_daily_owner.ps1 -SessionDate 2026-10-19 -Action CheckSetup -BootstrapPython $bootstrapPython -ConfirmRun
.\forward_daily_owner.ps1 -SessionDate 2026-10-19 -Action Setup -BootstrapPython $bootstrapPython -ConfirmRun
.\forward_daily_owner.ps1 -SessionDate 2026-10-19 -Action CheckTasks -BootstrapPython $bootstrapPython -ConfirmRun
```

Require CheckSetup's expected read-only status, then SETUP_VERIFIED_TASKS_DISABLED,
then CheckTasks' read-only binding status with both roles verified disabled and no
absent roles. CheckTasks CANNOT precede Setup on a new date: it requires the dated
capsule/venv to exist. No standalone CheckTasks on an uncreated Monday capsule.
No retry if blocked/unknown. Confirm the Setup notification personally. Only then
repeat this sequence with21Oct. Both dates' poll/audit tasks remain DISABLED. Leave
all other capture tasks disabled. If OTHER_CAPTURE_TASK_NOT_DISABLED, investigate
the exact residual task; do not bulk-disable or edit bindings. This weekend work
is not blocked by independent custody,7-Zip or PostgreSQL client installation.

AFTER the new wrapper merges green, the same sequence can be one explicit action
from its separate checkout. Define $reviewedToolsRoot to the existing CLEAN0b0aad4
checkout, not the observer checkout or a capsule; no private values need sharing:

```powershell
powershell.exe -NoProfile -File .\forward_guided_owner.ps1 -SessionDate 2026-10-19 -Action SetupAhead
powershell.exe -NoProfile -File .\forward_guided_owner.ps1 -SessionDate 2026-10-19 -Action SetupAhead -ToolsRoot "$reviewedToolsRoot" -BootstrapPython "$bootstrapPython" -ConfirmRun
```

Use EITHER the three original blocks OR wrapperSetupAhead per date, not both after
success. SetupAhead delegates CheckSetup/Setup/CheckTasks once each with required
ConfirmRun; any failure stops. Wednesday is a separate invocation after Monday
Setup success. Native wrapper commissioning is not yet owner-proven; the original
green route remains the fallback BEFORE any attempt, not a retry after an unknown.

## 4. One guided command on a session morning

Design now built in source, inactive/uninstalled: Morning delegates Prepare then
Start once. No new scheduler or daily credential/login automation. Required input:
genuine official session-morning download, its ACTUAL completion timestamp,
owner's NSE-source attestation and confirmation that the Setup notification was seen.
The reviewed Start itself executes the two supervised polls then conditionally
enables audit first/poll last. The wrapper does not infer truth from an exit code
or manufacture missing evidence; each child status must match its exact stage.

Recommended: wake/check host07:15, download near07:45–07:55, one Morning command
around08:00. All gates/preparation must complete before09:15; no last-second launch.
Wrapper rejects Morning before07:50:30 BEFORE invoking any child/attempt marker,
because earlier Start could exceed the unchanged90-minute wait. It does not sleep
overnight, wait through an earlier irreversible preparation, or relax the clock.
Owner stays available through first automatic09:30:30receipt, PC awake to audit.

Monday source is16Oct close, genuinely downloaded19Oct; Wednesday source is19Oct
close, genuinely downloaded21Oct because20Oct is closed. Never relabel saved bytes.
After weekend Setup, using actual existing private variables in normal PowerShell:

```powershell
powershell.exe -NoProfile -File .\forward_guided_owner.ps1 -SessionDate 2026-10-19 -Action Morning
powershell.exe -NoProfile -File .\forward_guided_owner.ps1 -SessionDate 2026-10-19 -Action Morning -ToolsRoot "$reviewedToolsRoot" -BootstrapPython "$bootstrapPython" -CloseFile "$closeFile" -DownloadedAt "$downloadedAt" -AttestNseSource -ConfirmNotificationSeen -ConfirmEnableAfterTwoPolls -ConfirmRun
```

Preview is zeroIO. Before confirmedMorning, require the wrapper's green exact-SHA
CI/merge and reviewed owner commissioning; use only one route. Do NOT run Morning
after a separate Prepare/Start, nor retry it after a block. The switches must be
true human statements, not flags an agent supplies automatically. Owner-file
download is still manual; Python NSE transport remains unresolved. No claim of
fully unattended daily capture or no owner presence is made.

New source wrapper is Windows-only. Synthetic child/argument/order/stop tests are
Windows/Linux rehearsals, NOT a live wrapper acceptance. It preserves allowlisted
child stage/code/exit/effect/marker/rollback metadata on failure; unknown stays
unknown. Review actual original coordinator reports, never reset a marker.

## 5. Weekend backlog, blockers and explicit order

NOT blocked by Friday75/75: disabled future Setup, tool installs, diagnostics,
synthetic drills and custody preparation. Friday results remove the lack of a full
capture-day witness; they do not clear any of these other acceptance gates.

1. **Alert/sleep/update:** after capture is idle, labelled popup and one-shot awake
   native API drills in FORWARD_OBSERVER_RUNBOOK. They do not prove production
   failure routing. Full isolated dummy-task wrapper drill still needs a separate
   reviewed disabled task/fixture package and explicit owner commissioning; never
   redirect production tasks/state. No deliberate blocked poll. Review Windows
   active hours/restart notifications and complete pending restarts before Monday;
   neither active hours nor a process awake request guarantees no forced restart.
2. **14Oct audit:** preserve original capsule/pins. Use the existing reviewed
   read-only audit path with14Oct date AFTER private path/version review. This
   new wrapper has no historical-audit action, and Friday is not a substitute.
   A new code version cannot be silently installed into the old capsule. No actual
   historical audit has been run by builder here; needs owner output/approved path.
3. **Legacy result2/shared writes:** retain old task definition, last-result metadata,
   dated scheduler receipts and file metadata. Diagnose against the exact old code
   without executing old audit or changing shared state; result2 alone gives no
   attribution. Needs read-only owner observations and possibly a bounded forensic
   helper; not solved by Friday's clean versioned audit.
4. **Time stop/dispersion:** read-only Windows System event history around the
   affected12:48 local time; inspect service control, time-service and update/restart
   events. Distinguish14Oct owner's later report from13Oct known CLOCK_UNVERIFIED
   sequence; do not guess which day caused a stop. Read-only event helper design
   pending; no broad logs/secrets collected. Running/Auto and FridayPASS do not
   explain the cause. No clock uncertainty waiver or automatic service repair.
5. **OPTION_CAPTURE_ENABLED:** owner inspect exact scheduled workflow run/commit,
   job condition and repository variable NAME/state (no token). Do not enable it
   or infer missing snapshots exist. A separate read-only GitHub workflow review
   is needed; this package adds no workflow or hosted setting change.
6. **Tools/custody:** install free7-Zip from7-zip.org; official PostgreSQL17 client
   binaries via postgresql.org (no server/service needed just to obtain clients).
   Check executable versions by explicit paths. Protect signing-key note privately,
   harmless AES-256 disk rehearsal, Drive capacity/retention check, then verified
   same-generation full-image/six-table replica+restore. Existing capture does not
   wait on these installs; deletion absolutely does wait on custody+restore.
7. **Storage commissioning:** after custody, consistent-cut real export/restore
   acceptance; guarded all-writer/cold-reader wiring and native unknown-COMMIT/
   race proof; universe dedup; source-specific bounded retention; capacity watch
   and independent alerts. No hosted SQL, deletion, or schedule enabling here.
   Full Supabase restore separately includes project settings/external objects;
   a NAV-only or six-table restore does not cover the whole project. Free-tier
   exports/off-site backup remain necessary; do not commission paid PITR.
   First obtain a fresh read-only capacity snapshot using the already reviewed
   sql/storage_burst_diagnostics_read_only.sql.11Oct's394MB/estimated runway is
   dated, not a current measurement. No Supabase query was run by builder here.
   The previously exposed quant_app_runtime password is a separate security item:
   rotation completion is unconfirmed. Use RUNTIME_PASSWORD_ROTATION_OWNER.md's
   reviewed quiescent same-role owner sequence before expanding hosted writers;
   never print URLs/passwords, broaden grants or reset the postgres password as a
   substitute. No hosted credential change is performed/commissioned here; PC
   broker/Drive credentials are separate and need not be replaced for that reason.
8. **Token/runtime:** record only actual Analytics expiry date privately; existing
   FORWARD_TOKEN_EXPIRES_AT gate remains.30-day reminder plan is not a scheduled
   alert or fresh provider auth proof. Keep explicit reviewedPython3.13.9 and its
   base runtime; do not invoke defaultpy3.15, uninstall it, or repin merely because
   both versions exist. No new Python install is needed for Monday.
9. **Research:** real ML/LLM/backtesting stay off pending licensed dataset use,
   point-in-time labels, preregistered frozen paper study and enough independent
   sessions. Friday75observations are highly correlated, not75independent days.
   No retro-replay, holdout inspection, automated rule retuning or claimed edge.

Technology radar: adopted existing coordinator plus a narrow pinned delegated
wrapper; adapted nullable task metadata and explicit per-test scopes. Kept arbitrary
terminal/MCP plugins out of capture operations; they are not security sandboxes.
No new connection/account/key is needed. Free7-Zip/PostgreSQL clients fill real
custody gaps; paid services/default-runtime migration add no necessary capability.
Next highest leverage: isolated full failure-alert wrapper acceptance plus independent
same-generation restore, not more model complexity on a single full capture day.

Primary references: https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/get-scheduledtaskinfo
https://learn.microsoft.com/en-us/windows/deployment/update/waas-restart
https://www.nseindia.com/resources/exchange-communication-holidays
https://supabase.com/docs/guides/platform/backups
https://www.postgresql.org/docs/17/app-pgdump.html
