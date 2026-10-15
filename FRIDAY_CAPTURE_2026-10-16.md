# Friday 16 October — three commands, no pasted prompts

## Thursday evening update — Setup diagnostics follow-up

The original 33-file package is now merged as
`d5cd80f41a52de902d23cb81d761e7bb720e710c` (owner reports exact-commit CI green).
Do not repeat that upload. Use the seven-file follow-up manifest
`DAILY_SETUP_REPAIR_UPLOAD_2026-10-15.md`; historical 20/33-file manifests remain
unchanged records, not checks for this new modified tree.

The owner-reported Setup block at REVIEWED_TOOLS_CHECKOUT happened BEFORE
operational writes and before any Start marker, capsule creation or task mutation.
That old stage also covered the Python bootstrap and private-ops permission read,
not just Git. Direct Git checks passed in both owner-verified normal and elevated
PS5.1 windows. Subsequent owner checks establish that `py` is unavailable, while
the existing reviewed test interpreter reports3.13.9/exit0. That missing launcher
is sufficient to explain the old bootstrap block. Private-ops and later Setup
acceptance are still NOT established.
An elevated Setup would stop at NORMAL_WINDOW_CHECK; System32 alone proves nothing.
Do not reset a marker, change ACLs/ownership/safe.directory or relax a pin.

The follow-up exposes separate Git, Python and private-ops stages and fixed public
codes, nonempty blockers for controlled rejections, safe native exit code/category,
and whether operational state was reached. It removes the launcher dependency:
an explicit existing local executable must prove exactly3.13.9 with an isolated
positive sentinel. No PATH search, launcher auto-install or version relaxation.
It supplies controller checks and creates the capsule's own venv; scheduled tasks
still use ONLY that capsule's interpreter. Keep the approved bootstrap/base runtime
installed: a venv is not a standalone Python distribution. No installation is
needed for the owner's verified existing interpreter.

`CheckTools` remains public-Git-only. `CheckSetup` checks the same normal-token,
Git, explicit interpreter and private-ops prerequisites as Setup, then exits BEFORE
capsule writes/task mutation. Neither is morning GO: capsule/calendar/clock,
provider, credentials, tasks and notification delivery remain unverified.

After the reviewed follow-up merges with exact-final-SHA green CI, use a NEW clean
merged tools checkout, normal PowerShell. Set the verified interpreter once:

```powershell
$bootstrapPython = 'C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
.\forward_daily_owner.ps1 -SessionDate 2026-10-16 -Action CheckSetup -BootstrapPython $bootstrapPython -ConfirmRun
```

Require SETUP_PREREQUISITES_CHECK_PASSED_NOT_COMMISSIONED. Then Setup below may
be run once under the reviewed recovery procedure. This is not retrying a market
slot or resetting Start. If Setup blocks, stop and share only its redacted JSON;
the new stage/code identifies the remaining prerequisite. CheckTools passing
alone does not resolve or authorize bypassing a Python/private-ops block.

Target successful Setup THURSDAY evening. An 08:00 Friday Start requires accepted
Setup and fresh FRIDAY download/Prepare by 08:00. Hard 09:15 freeze and strictly
before09:20:30 Start gates remain unchanged. If prerequisites cannot be cleared
safely, Friday is NO_GO, no backfill; keep tasks disabled. No promise is made that
a diagnostic code change itself establishes host readiness.

**15 October is owner-reported NO CAPTURE, NO BACKFILL.** All six old tasks remain
disabled as reported; this tool does not change them. The five-file 14 October
copy under private KiranTrading storage is a same-drive selected-evidence safety
copy, not independent custody. Do not repeat it just to prepare Friday. It does
not cover top-level scheduler receipts or ForwardOps; keep those untouched.

This replaces the date-hardcoded eleven-block morning ritual, not the reviewed
producer. The date parameter derives capsule and task names. Known roots are
`%LOCALAPPDATA%\KiranTrading\Forward` and `ForwardOps`; there is no Read-Host.
Use a NORMAL PowerShell window: the tool refuses an elevated Administrator token.
No ACL changes, automatic time repair, old task edits or installed agent roles.

## Before Friday — do the slow setup early

The original combined33-file PR has merged; use the seven-file follow-up described
above. All required checks must be green on its exact final commit. Run the
script from a clean reviewed MERGED tools checkout, OUTSIDE every frozen
capsule. Do not copy it into the 14 October capsule or modify its source pins.
The tools checkout contains the script and adjacent pure contract; it is not a
capture capsule and needs no credentials. The capture capsule still uses exact
public1251530731cce5b75fad8601567b9320d07b710d and its own environment.

In a normal PowerShell, from that tools checkout, ONE command:

```powershell
.\forward_daily_owner.ps1 -SessionDate 2026-10-16 -Action Setup -BootstrapPython $bootstrapPython -ConfirmRun
```

Setup can run on 15 October evening or 16 October before09:15. It verifies normal
window, private existing ops directory, creates a NEW date-derived public capsule
if absent, verifies exact Git/policy bytes and pinned dependencies, checks the
reviewed calendar, and registers ONLY Friday poll/audit tasks DISABLED. Existing
Friday tasks are reused only if disabled and exact bindings match; never replaced.
It displays a harmless notification rehearsal. You must see and dismiss it.
Expected `SETUP_VERIFIED_TASKS_DISABLED`; no fresh producer clock proof yet.
If an environment install fails, do not replace pins or overwrite old capsules.
Re-running Setup can verify an existing clean public capsule; a partial/incorrect
environment blocks its package/dependency check rather than silently repairing it.

Friday names: `KiranTrading-Versioned-20261016-poll` and `...-audit`.
They point to `kiran_forward_20261016`, never to the old raw-only audit.
No task is enabled by Setup. No Windows service is changed by any action.

## Friday by08:00 — fresh owner file, one preparation report

Check AC power, no sleep/hibernation/restart during capture, and stay logged in.
If Windows Time needs resync, do the separate owner administrator operation once,
then CLOSE that admin window and return to a NORMAL one. Do not bypass a failed
fresh NTP check. Windows Root Dispersion8.07s is not the producer's measured
offset/uncertainty: only its independent fresh check establishes its gate result.

Download the official file in Chrome on FRIDAY morning:
`https://nsearchives.nseindia.com/content/indices/ind_close_all_15102026.csv`.
The reviewed validator requires the download date to equal the session date.
An evening15October download is therefore not eligible for16October preparation.
You may inspect/retain that copy, but download again Friday; never change its
attested timestamp or substitute file modification time. Record the actual
completion timestamp including `+05:30`. Neither example below invents a time.

Set only the two genuine owner inputs in this same normal window, one line each:

```powershell
$closeFile = "$env:USERPROFILE\Downloads\ind_close_all_15102026.csv"
$downloadedAt = 'REPLACE_WITH_ACTUAL_FRIDAY_COMPLETION_ISO_TIME_WITH_+05:30'
$bootstrapPython = 'C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
```

Choose the actual downloaded filename if Chrome added a suffix. Then ONE command:

```powershell
.\forward_daily_owner.ps1 -SessionDate 2026-10-16 -Action Prepare -BootstrapPython $bootstrapPython -CloseFile $closeFile -DownloadedAt $downloadedAt -AttestNseSource -ConfirmRun
```

Expected `MORNING_GO_SUPERVISED_START_REQUIRED`: exact disabled task bindings,
fresh preflight/clock gate, owner-attested prior close and policy freeze passed.
Preparation, including policy freeze, MUST finish before09:15. Source provenance
remains OWNER_ATTESTED_NOT_INDEPENDENTLY_VERIFIED. Provider/Drive verification
still belongs to the supervised polls, not the pre-open report. If it blocks,
use the redacted code/stage/owner_step; no recipe overwrite or blind retry.
Only the new day's config/policy and existing producer reports are written.

## One supervised start — waits, verifies, then conditionally arms recurrence

After successful Prepare and having actually seen Setup's notification, run once
from08:00 onward and strictly BEFORE09:20:30:

```powershell
.\forward_daily_owner.ps1 -SessionDate 2026-10-16 -Action Start -BootstrapPython $bootstrapPython -ConfirmNotificationSeen -ConfirmEnableAfterTwoPolls -ConfirmRun
```

This is explicit owner authorization for TWO future supervised invocations and
conditional task enabling. Leave the window open. It waits for09:20:30 and09:25:30,
invokes each slot once, and requires the reviewed producer's success contract,
fresh clock PASS, durable/remote receipt flags and fresh-session counts1/74 then
2/73. Raw-only evidence is not an accepted decision. A persistent exclusive
`2026-10-16-guided-morning-v1.attempt` marker in ForwardOps prevents another Start.
It is not delivery or custody proof. Never remove/reset it or repeat Start after
failure/interruption; preserve and reconcile read-only. The existing producer
keeps its own licence, clock, source, locking and no-catch-up gates unchanged.

After both successful results it revalidates config/policy and fresh host health
while BOTH tasks remain disabled: service/sync, unchanged NTP gate, disk reserves
and exact actions. The reviewed health function is called directly; the old
preflight CLI's09:15 cutoff is not bypassed or changed. Every potentially slow
admission read happens BEFORE submitting poll enablement. A stalled check cannot
arm polling. Exact disabled XML and the09:30 deadline are checked again.

It enables AUDIT FIRST and verifies that task, then writes an immutable private
`2026-10-16-guided-activation-v1.json` precommit witness binding the reviewed base,
task-plan digest, two poll-report digests and health-report digest. This is local
process evidence and owner authorization to ATTEMPT enabling, not a custody,
enabled-state readback, successful execution or trade-approval receipt.
Polling enablement is the FINAL external operation. The fixed09:30:30 trigger
was verified from the disabled task XML; actual next-run readback remains unknown.
After an ordinary failure or cancellation, cleanup attempts to disable FUTURE
poll triggers, never terminates a producer. Audit may remain enabled for the
incomplete session. Read the rollback status; failure is not called success.
An enabling error can mean its acknowledgement failed after taking effect.
The controller therefore also attempts rollback in that case; only a readback
with polling disabled earns the disabled status. An unconfirmed rollback needs
the owner's task-state check, never an assumption that capture is off.
Cooperative pipeline cancellation also attempts this cleanup before verified
commissioning. Forced process termination, window destruction or power loss
cannot guarantee cleanup or a report: check actual task state as owner, retain
the attempt marker, and never rerun Start to discover what happened.
An acknowledgement returned before09:30 yields
`POLL_ENABLE_ACKNOWLEDGED_AFTER_VERIFIED_ADMISSION`, with
`enable_proof=TASK_SCHEDULER_ACKNOWLEDGEMENT_ONLY`; enabled-state readback,
next-trigger readback and first-trigger execution are explicitly NOT VERIFIED.
A missing/late acknowledgement is OUTCOME UNKNOWN, not proof of automatic
deadline disarming: Windows can apply a request before its response stalls.
All admission requirements already passed before this owner-authorized commit
attempt, but the owner must reconcile actual task state without retrying it.
Inspect the actual09:30 scheduled operations receipt before calling recurrence
operational. No synchronous child verifier is started after polling is enabled.
The producer process report is not independent custody or a restore proof.

The scheduled poll remains index-only09:15–15:30, final poll15:30:30, audit15:40.
Friday is regular in the reviewed calendar.17–18October are weekends,19regular,
20Dussehra CLOSED. No weekday inference for unknown/special dates. Official
[NSE annual notice](https://nsearchives.nseindia.com/content/circulars/CMTR71775.pdf).

## Deadline/failure branches and post-session

- Setup not complete: keep every new task disabled; prepare a later eligible day.
- No fully frozen config/policy before09:15: no capture, no backfill.
- No supervised Start before09:20:30: no automatic commissioning that day.
- Either poll fails, raw-only, interrupted or unknown: no same-slot retry. Keep
  future polling disabled; retain any accepted/raw/unknown evidence unchanged.
- Two successes but no acknowledged enablement before09:30: outcome unknown or
  partial rehearsal. Check actual task state; do not assume disabled, enable
  late, retry or catch up. Two slots are not a complete research day.

After15:40, if necessary ONE read-only audit (valid incomplete coverage is not a
tool failure):

```powershell
.\forward_daily_owner.ps1 -SessionDate 2026-10-16 -Action Audit -BootstrapPython $bootstrapPython -ConfirmRun
```

The date-pinned scheduled audit runs automatically only after Start arms it.
After bounded completion, owner can disable those two tasks; never delete history
or force-stop a running invocation. New dates need new disabled task identities.
No workflow, release hold, Streamlit expectation or storage deletion changes.

## Other open investigations — separate from Friday admission

The14October read-only historical audit and private scheduler-receipt inventory
remain pending. Use OVERNIGHT_CONTINUITY_2026-10-15.md's original-capsule path if
current source pins block; never rewrite frozen pins. Legacy result2 does not
identify a cause or prove no writes. Actual notification delivery remains an
owner observation. WindowsTime12:48 stop needs redacted Event Viewer times/IDs,
not a guessed cause. Public skipped option jobs had zero executed steps and an
unsatisfied schedule gate inference; no setting change or historical catch-up.
None of these unknowns is silently upgraded to verified by the Friday report.
