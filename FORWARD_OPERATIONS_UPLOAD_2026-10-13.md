# Future-session capture operations: one inactive upload

Baseline reviewed: `f874f6a97440af58c2bf5bcf8038b351f2f95cf6`.
The Research Lab package is already merged in this baseline. This operations PR
is compatible with that merged tree; no prerequisite upload or rewind is needed.
No existing producer, clock guard, app, task, capture folder
or state is changed by uploading. No new workflow. No fingerprint update required.

## Findings and decisions

### Reconciliation after Research Lab merged

The previous baseline was `0223f0033672e072e522017f2cdfe7cab0478e18`.
The actual public-main diff in `equity_runtime_health.py` adds three lines to
`RELEASE_FILES`: the four Research Lab modules and the literal versioned recipe
source. No clock function, import or capture behaviour changed. The complete
operations import closure still has 32 prerequisite modules plus the pinned audit
test (33 pins). Only this prerequisite's LF-normalised hash changed, to
`8e9fdd006d3fc9300b6e6b2393dce90a9d6c9ee1bcef68e608a1b1951d86a34b`.
The reviewed pin is refreshed to those actual main bytes, not the held root draft.
The checker is unchanged: exact current HEAD, staged ten-file package and every
transitive prerequisite remain mandatory. Two regression cases cover newer exact
HEAD acceptance and stale-base rejection. No safety gate is removed or relaxed.

If the original ten files are already staged on this baseline, re-copy ONLY:
`FORWARD_OPERATIONS_UPLOAD_2026-10-13.md`,
`FORWARD_OPERATIONS_UPLOAD_2026-10-13.json`, and
`tests/test_forward_ops_upload_check.py`, from the source prefix below to the same
destinations. Re-stage these three, then rerun the checker and focused commands.
Do NOT copy `equity_runtime_health.py` from the workspace root; keep merged main's
version. If main advances again, review any new pin failures before proceeding.

The supplied receipts establish clock rejection, not its network root cause.
The producer queries `time.cloudflare.com` directly via UDP; Windows service
status and a successful Windows resync are not substitutes for its own check.
Keep the one-second uncertainty/offset gate and the single bounded probe.
No capture-time resync, alternate clock acceptance, same-slot retry or catch-up.
Repair Windows time only as a separate owner action before capture. A future
reviewed transport retry must have a measured deadline and must never cross the
slot or silently substitute a timestamp; it is not commissioned here.

`0x80070002` means ERROR_FILE_NOT_FOUND, not decimal exit 2 (which is `0x2`).
Therefore inspect the executable/action history separately; receipts establish
which invocations actually reached the clock guard. `0xC000013A` is a console
termination status, not proof the owner pressed Ctrl+C. Its COMMIT outcome stays
unknown until read-only journal inspection; never reset or repeat the slot.

Microsoft references:
- [Windows Time tools](https://learn.microsoft.com/en-us/windows-server/networking/windows-time-service/Windows-Time-Service-Tools-and-Settings)
- [0x80070002](https://learn.microsoft.com/en-us/troubleshoot/windows-server/installing-updates-features-roles/troubleshoot-windows-update-error-0x80070002)
- [NTSTATUS values](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-erref/596a1078-e883-4972-9bbc-49e60bebca55)

## Exact source → destination

Source prefix for EVERY row: `C:\Users\banga\Desktop\kiran_share_market\`.
Destination is relative to the clean newest green main clone. Copy only these
ten files; no staged replacements, runtime changes, private files or progress
file are part of this upload.

| Source suffix | Destination |
|---|---|
| forward_session_ops.py | forward_session_ops.py |
| forward_ops_host.py | forward_ops_host.py |
| forward_ops_plan.py | forward_ops_plan.py |
| forward_ops_task.ps1 | forward_ops_task.ps1 |
| forward_ops_upload_check.py | forward_ops_upload_check.py |
| tests\test_forward_session_ops.py | tests/test_forward_session_ops.py |
| tests\test_forward_ops_plan.py | tests/test_forward_ops_plan.py |
| tests\test_forward_ops_upload_check.py | tests/test_forward_ops_upload_check.py |
| FORWARD_OPERATIONS_UPLOAD_2026-10-13.md | FORWARD_OPERATIONS_UPLOAD_2026-10-13.md |
| FORWARD_OPERATIONS_UPLOAD_2026-10-13.json | FORWARD_OPERATIONS_UPLOAD_2026-10-13.json |

Capture `$uploadBase = git rev-parse HEAD` BEFORE copying. Stage only this list.
Then, in that clone:

```powershell
python forward_ops_upload_check.py --base $uploadBase
python -m pytest -q tests/test_forward_session_ops.py tests/test_forward_ops_plan.py tests/test_forward_ops_upload_check.py tests/test_overnight_capture_audit.py tests/test_forward_versioned_capture.py
python -m pytest -q tests/test_research_lab.py tests/test_research_lab_grounding.py tests/test_research_lab_statistics.py tests/test_research_lab_upload_check.py tests/test_streamlit_boot.py tests/test_historical_repository_bridge.py tests/test_release_packaging.py
python -m mypy --strict --explicit-package-bases --follow-imports=silent forward_session_ops.py forward_ops_host.py forward_ops_plan.py forward_ops_upload_check.py tests/test_forward_session_ops.py tests/test_forward_ops_plan.py tests/test_forward_ops_upload_check.py
python -m pyflakes forward_session_ops.py forward_ops_host.py forward_ops_plan.py forward_ops_upload_check.py tests/test_forward_session_ops.py tests/test_forward_ops_plan.py tests/test_forward_ops_upload_check.py
```

The checker verifies the entire import closure against reviewed public main,
and reports path/expected/actual hashes. Do not remove or relax a failing pin.
The manifest is a reviewed control file, not a signed artifact.
Merge only after full CI passes. Uploading never commissions or installs tasks.

## Owner steps: next regular session only

Read the latest report using this cause → action guide. No item authorizes a
clock bypass, catch-up, same-slot retry, lock deletion or journal reset.

| Report | Plain meaning and safe next action |
|---|---|
| WINDOWS_TIME_SERVICE_NOT_RUNNING / NOT_AUTOMATIC | Windows time maintenance is not ready. Review Services → Windows Time before the open; start/repair it as an owner action, then verify the independent probe. |
| CLOCK_MEASUREMENT_UNAVAILABLE + TIMEOUT / FAILED | The independent time check could not complete. Windows resync alone is not proof of network access to the producer's clock server. Check DNS/UDP 123/firewall privately; keep capture blocked until a future guarded check passes. |
| CLOCK_OFFSET_OR_UNCERTAINTY_EXCESSIVE | Time differs too much or the measurement is too uncertain. Repair/resync before capture; do not enlarge the one-second gate. |
| POLL/AUDIT_TASK_ACTION_MISMATCH | The scheduled date, mode, executable or capsule/state binding is wrong/missing. Review the new disabled plan; do not edit a frozen day's config. |
| LOCAL/CAPTURE_DISK_RESERVE_NOT_MET | A required volume lacks the reviewed reserve. Arrange safe storage without deleting history; leave polling off until checked. |
| PROCESS_TERMINATED_COMMIT_UNKNOWN | The child was interrupted. Inspect the journal read-only; never assume nothing committed or replay that slot. |
| VERSIONED_COVERAGE_INCOMPLETE | Real observations are preserved but some slots are missing. Exclude a complete-session cohort; don't replace gaps with zeros. |


1. Leave 13 Oct's folder, state, configuration, task export and journal intact.
   Do not delete the old raw-only folder/task. Preserve the 41 real observations
   and 34 missing decisions. Complete-session research must exclude this session;
   partial-observation research needs a separately preregistered missingness rule.
   None of these tools changes the ledger, fabricates labels, or proves remote custody.
2. After merge, create a NEW code capsule from clean merged main using the existing
   capture-install routine and its virtual environment. Do not copy unfinished
   workspace files and do not install into today's folder. Select a private
   operations-report directory OUTSIDE the code and capture-state directories,
   for example `$forwardOpsRoot` under the owner's private application-data tree.
   Verify its Windows ACL is owner-only. Reserve 1 GiB free on that volume. This
   reserve is an operational floor, not a forecast of archive growth.
   Rehearse local notification from this new capsule only:

```powershell
& $futurePython -c "from forward_ops_host import notify; print({'launched_not_delivered': notify('NOTIFICATION_REHEARSAL')})"
```

   Confirm that you actually see and dismiss it. A successful process launch alone
   does not pass this owner test. No credentials or capture state are accessed.
3. Before 09:15, verify Windows Time is Running/Automatic and run its existing
   status query. If repair is needed, do it manually outside capture, then test
   the producer's independent measurement. Inspect Event Viewer around 12:48:
   System → Service Control Manager, and Windows Time-Service Operational. Around
   11:25 inspect TaskScheduler Operational and console/process history. Share
   only timestamps, event IDs and safe classifications, not raw task arguments.
4. Define tomorrow's date explicitly (14 Oct is an example, never reuse it later),
   the NEW capsule path, its Python path, existing private capture-state root,
   operations root and owner SID. Generate REVIEW_ONLY_DISABLED plans:

```powershell
$captureDay = '2026-10-14'
$ownerSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$plans = & $futurePython forward_ops_plan.py --session-date $captureDay --owner-sid $ownerSid --code-directory $futureCode --python-executable $futurePython --state-root $forwardPrivateState --ops-root $forwardOpsRoot | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $plans.status -ne 'REVIEW_ONLY_DISABLED') { throw 'Plan blocked' }
foreach ($entry in $plans.plans.PSObject.Properties) {
    if (Get-ScheduledTask -TaskName $entry.Name -ErrorAction SilentlyContinue) { throw 'Task already exists: review; do not overwrite' }
}
foreach ($entry in $plans.plans.PSObject.Properties) {
    Register-ScheduledTask -TaskName $entry.Name -Xml $entry.Value -ErrorAction Stop | Out-Null
    if ((Get-ScheduledTask -TaskName $entry.Name -ErrorAction Stop).State -ne 'Disabled') { throw 'Disabled state not confirmed' }
}
```

Run from the future capsule. XML has no encoding declaration. These are owner
OS writes, not performed by the agent. If registration fails part-way, leave
everything disabled and inspect which names exist; don't blindly rerun/overwrite.
The plan currently assumes Windows at `C:\Windows`; inspect the executable path
before registration if your installation differs. Native registration and visible
notification delivery still require owner rehearsal; XML parsing is not proof of that.

5. Set `$pollName = "KiranTrading-Versioned-$($captureDay.Replace('-',''))-poll"`
   and `$auditName = "KiranTrading-Versioned-$($captureDay.Replace('-',''))-audit"`.
   Before preparation, rehearse the ACTUAL PowerShell launcher that the tasks use:

```powershell
& "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -WindowStyle Hidden -File (Join-Path $futureCode 'forward_ops_task.ps1') -PythonExecutable $futurePython -CodeDirectory $futureCode -StateRoot $forwardPrivateState -OpsRoot $forwardOpsRoot -SessionDate $captureDay -Mode preflight -PollTask $pollName -AuditTask $auditName
if ($LASTEXITCODE -ne 0) { throw 'Native launcher/preflight blocked; leave all tasks disabled' }
```

   Inspect the newly appended private operations report: PREOPEN_HOST_CHECK_PASSED
   is required. The hidden child writes its report rather than a visible console.
   This also catches script-policy, virtual-environment and action failures BEFORE
   automatic capture. Do not silently add ExecutionPolicy Bypass or relax system
   policy to make it work. If Windows refuses the reviewed script, stop and review
   the policy/signing requirements with the owner; no task may be enabled on the
   strength of Python-only diagnostics. A separate Python-only diagnostic command is:

```powershell
& $futurePython forward_session_ops.py --root $forwardPrivateState --ops-root $forwardOpsRoot --session-date $captureDay --mode preflight --poll-task $pollName --audit-task $auditName --confirm-ops --notify-local
```

   Expect PREOPEN_HOST_CHECK_PASSED. This reads task/service/disk status and makes
   one independent NTP check. It does NOT check Upstox auth, Drive or the day's
   frozen policy; a supervised poll is still necessary. Disabled tasks are
   reported, not silently enabled. Network availability is not inferred from ping.
6. Follow the existing owner-file prepare and versioned prepare-policy runbook
   using the new capsule, explicit future date and freshly attested downloaded
   previous-close file. Freeze before 09:15. Do not automatically attest a source,
   reuse yesterday's freeze, overwrite a prepared day, or run preparation late.
   Human download/provenance attestation remains necessary; this package does not
   claim to fix the NSE Python transport.

   From the new capsule, using the freshly reviewed private file and the actual
   download timestamp (not a guessed time), run these separately and stop on any
   failure. Preview first by omitting each confirmation flag:

```powershell
& $futurePython forward_nifty_schedule.py --root $forwardPrivateState --mode prepare --owner-close-file $ownerCloseFile --owner-download-at $ownerDownloadAt --attest-nse-source --confirm-run
if ($LASTEXITCODE -ne 0) { throw 'Preparation blocked; do not proceed' }
& $futurePython forward_versioned_capture.py --root $forwardPrivateState --session-date $captureDay --mode prepare-policy --confirm-versioned-research
if ($LASTEXITCODE -ne 0) { throw 'Policy freeze blocked; do not proceed' }
```

   Expected statuses: CONFIG_PREPARED_OWNER_FILE, then VERSION_POLICY_PREPARED.
   Verify the printed prepared date is the intended day; do not infer successful
   preparation from exit 0 on a skipped holiday. The index capture window remains
   09:15–15:30; the 15:40 audit is not a derivative window extension.
7. Keep the scheduled poll disabled. At ONE future 09:20:30 slot and ONE future
   09:25:30 slot run the wrapper with `--mode poll` and the same other arguments.
   Both must return POLL_REMOTE_VERIFIED. Inspect the private operations report.
   A CLOCK_UNVERIFIED report now distinguishes unavailable/stale/invalid/excessive
   measurement and allowlisted probe timeout/busy/failure. No same-slot retry.

```powershell
& $futurePython forward_session_ops.py --root $forwardPrivateState --ops-root $forwardOpsRoot --session-date $captureDay --mode poll --poll-task $pollName --audit-task $auditName --confirm-ops --notify-local
```
8. Only after these successes and BEFORE 09:30:30, enable the new date-pinned poll and audit tasks
   explicitly. Disable the legacy raw-only audit for this future session; leave
   its definition/export intact. The new audit is a read-only versioned replay at
   15:40, never the old scheduler audit. Do not run two poll tasks together.
   Verify NextRunTime is 09:30:30 and observe its first automatic result. If setup
   runs late, stop and review new future-slot plans; never start the missed trigger.
   The hidden launcher avoids the recurring console. InteractiveToken requires
   the owner to remain signed in and the PC awake. Missed launches never catch up.
9. A blocked poll launches one local message box per day/category and appends a
   redacted health report outside capture. Launch is NOT proof you saw the alert.
   An interrupted child gets an UNKNOWN COMMIT warning. A crash before startup,
   sleep, logoff, full disk or absent process can still defeat notifications;
   if an operations report cannot be saved, a best-effort REPORT_UNAVAILABLE
   notification may repeat because safe on-disk deduplication is unavailable.
   independent external monitoring remains pending and is not falsely claimed.
10. At 15:40 inspect the audit report. Exit 0 means complete LOCAL coverage only;
    exit 1 means verified but incomplete coverage; exit 2 means audit blocked.
    Every missing slot is MISSING_NOT_OBSERVED, never a zero return or decision.
    Slot-specific failure causes are NOT_ESTABLISHED because a bad local clock
    can make receipt timestamps unreliable. Remote custody and training remain
    false even for a complete local session. Disable the day's tasks afterwards;
    date pins prevent next-day capture but are not evidence of owner review.

## Daily automation scope

Generate all three disabled plans together; preflight, polls and new-format audit
can then execute with hidden windows when individually commissioned by the owner.
Preparation and enabling remain explicit. Do not enable preflight after its
08:50 slot to obtain a catch-up run; use the manual command before 09:15 instead.
An unattended daily routine is deferred until source provenance, clock/network
availability, custody and independent missed-run alerts are commissioned. Saving
owner effort cannot mean silently accepting yesterday's source or a bad clock.

## Verification and limitations

Reconciled current-main verification: 56 operations tests passed; the unchanged
Research Lab profile passed all 112 cases; their combined run with capture/audit
compatibility passed 195 cases. Strict typing passed on 16 operations/Research Lab
files and the existing 19-file profile. Full-tree Pyflakes and PowerShell launcher
syntax checks passed. All 36 operations import-closure modules loaded with network
operations forbidden; all existing health functions/classes have identical ASTs
to the previous baseline. Exact staged ten-file checker passed with all 33
prerequisite pins and no failures. Full offline regression against this baseline
plus the operations package: **4,018 passed, 4 unchanged skips, 2 subtests passed**
in 1,616.82 seconds. No test count dropped (56 added operations cases). The owner
must still require green exact-commit CI.

The accompanying progress checkpoint records exact test counts and clean-main
rehearsal results. Tests are synthetic/offline, including gaps, holidays/special
sessions, IST boundaries, no writes to journal, no probe retry, interruption,
disabled XML and pin diagnostics. Windows task registration, actual local message
visibility and tomorrow's capture are owner acceptance, not verified here.
No installed folder, private state, service, task or hosted resource was inspected
or modified by the agent. The app's release expectations remain unchanged.
