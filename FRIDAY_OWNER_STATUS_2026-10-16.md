# Friday: complete owner-reported75-slot capture; preserve evidence

## Superseding weekend update

PR37 is owner-reported merged green as a6e5be8484565be0f3d1669d6c3e004f692478e8.
Friday tasks are now Disabled and verified. Setup19/21Oct completed, both roles
Disabled; do not repeat Setup. AlertDrill and AwakeDrill passed on the owner PC,
not the production blocked-poll route. 7-Zip26.04 and PostgreSQL17.11 clients are
installed. The chronology below is historical. Current actions and unresolved
items: WEEKEND_COMMISSIONING_STATUS_2026-10-17.md. Monday uses manual Prepare->Start;
optional guided commissioning belongs to a different date, never both routes.

## Ready / not verified / first action

OWNER-REPORTED at about03:52 IST: PR36 merged green as
0b0aad4efa102643cc5dc4073dc7fc915281c1bf. Clean normal tools checkout;
CheckSetup and CheckTasks passed. One Setup registered audit only, verified poll
and audit DISABLED, reported Start marker NOT_REACHED. Notification seen/dismissed.
Do not repeat Setup, replace either task or reset a marker. No new upload is
needed before today's capture: keep using that clean reviewed tools checkout.

SUPERSEDING FINAL OWNER REPORT: manual read-only Audit VERSIONED_COVERAGE_COMPLETE,
75raw polls/75recorded/0missing; all75slots09:20–15:30 OBSERVED_DECISION.
Generation17f7fbd62eafd8770ef2370becc5936a8fef16e4d6d71bee03f66d0ac08aabe9;
capture_writes0. At18:03 owner queried poll15:30:31/result0/missed0 and audit
15:40:00/result0/missed0; bothReady/no nexttrigger. Scheduled audit DID run; builder
has not inspected its report or private journal. Full-session cohort/training/
remote custody all remainFALSE. Operational cause per slot NOT_ESTABLISHED.
No blocked-poll alert has been seen. Friday is complete, not to be prepared or
started again. Preserve capsule/state/reports/markers; owner may disable ONLY the
finished two tasks per WEEKEND_OWNER_PLAN_2026-10-16.md, without deleting definitions.
The timing/commands below are historical/future-session guidance, NOT permission
to repeat Friday. Use the weekend plan for19/21Oct and the refreshed22-file package.
No builder task/capture reads or mutations occurred. All times below IST.

## Exact unchanged timing rules, not new permissions

- Download eligibility begins16Oct00:00. No08:00 lower bound and no arbitrary
  eight-hour expiry exist. Thursday's bytes cannot be relabelled as Friday retrieval.
- Correct CSV is the15Oct previous-session close, actually downloaded on16Oct:
  https://nsearchives.nseindia.com/content/indices/ind_close_all_15102026.csv
- Required order is actual download completion <= file read <= config freeze
  <16Oct09:15. The policy freeze and final Prepare gate must also finish BEFORE
  09:15. There is no safe last launch second: operations take nonzero time.
- Preparing now is permitted if every gate passes, but it freezes today's source
  and policy. Recommended07:30–07:50 leaves time for health checks without creating
  a needless early irreversible preparation. No repeat or overwrite if blocked.
-08:00 is the operating target, not a new hard gate. Start's contract requires
  entry strictly before09:20:30, and substantial checks occur before its first wait.
  A launch at09:20:29 is NOT guaranteed to work.
- The first Wait-Slot accepts entry during[07:50:30,09:20:30):90minutes maximum
  to09:20:30. Do NOT launch Start early to experiment: it may write its exclusive
  attempt marker before rejecting an overlong/passed wait. Never reset/retry it.
- First supervised poll09:20:30; second09:25:30. Only both complete valid receipts
  plus fresh health allow audit-first/poll-last enabling before09:30. First
  automatic trigger09:30:30. Final index poll15:30:30; audit15:40. No window change.
- Wake too late to complete the remaining gates, a blocked/unknown result, missed
  admission or interrupted Start: stop,
  retain evidence/marker, inspect safe report and actual task state; no catch-up,
  same-slot retry, late manual enabling or time/pin waiver. NO_GO if gates cannot
  be met.08:00 target missed is not a licence to skip any check or rerun Start.

Source: forward_daily_contract.gate; Wait-Slot/coordinator in forward_daily_owner.ps1;
frozen125 nse_owner_close.validate/from_file and forward_nifty_schedule.prepare.
The independent checker inspected the clock rules from the actual public125
commit, not a substituted workspace health module.

## Time service: observation is not producer acceptance

BUILDER READ-ONLY observation around03:54: service Running/Auto, leap0,
Windows root dispersion4.1740335s, last successful sync02:49:28, time.windows.com.
No repair, resync, task/private-state read or settings change was performed.
This is not morning or all-day health proof. The earlier12:48 stop is unexplained.

Windows root dispersion is not measured local offset or the producer's independent
NTP exchange. Pinned125 probes time.cloudflare.com. Its evidence must be measured,
aware, aged0–60seconds, finite/nonnegative uncertainty and
abs(offset)+uncertainty <=1second. If that response itself has excessive root
dispersion, it fails; do not subtract or falsify it. Setup and Windows leap0 do
not certify this gate. Prepare, each poll and admission health remeasure it.

Near07:15, NORMAL PowerShell, read-only; not a GO report:

```powershell
Get-CimInstance Win32_Service -Filter "Name='w32time'" | Select-Object State, StartMode
w32tm /query /status
```

Require Running/Auto and inspect synchronisation. No proactive resync is needed
from the current observation alone. If stopped/unsynchronised or fresh gate fails,
keep capture off. Any owner service repair/resync is a separate administrator
operation BEFORE capture, followed by a return to normal PowerShell and the
unchanged fresh gate. Do not change LocalClockDispersion, ACLs or thresholds.
Do not force clock changes or restart services while Start is waiting/capturing.

## Minimum Friday owner sequence — normal window, one command at a time

1. Use the already clean merged tools checkout at owner-verified0b0aad4….
   Do not copy these new status/tool files into it and make it dirty. No Setup redo.
2. PC on AC; logged into the correct interactive owner session; stable network;
   lid open; no sleep/hibernate/restart through the final15:40 audit. Display
   timeout is not sleep. Do not assume a locked/logged-out or sleeping PC can show
   notifications. The tasks have WakeToRun false: they do not wake the PC.
   It may sleep BEFORE07:15 while tasks are disabled, but wake it manually early
   and let time/network settle. Do not rely on an uncommissioned wake timer.
3. Check Windows Time as above. Download the actual official CSV in Chrome;
   record its true completion time with+05:30. Do not substitute file mtime.
   Existing same-user Upstox/Drive credentials and the truthful licence
   acknowledgement are still required. No credential value was read here.
   This source expects UPSTOX_ANALYTICS_TOKEN, not a daily OAuth assumption:
   official documentation describes a free read-only1-year Analytics Token.
   Privately check its TYPE/expiry date only if uncertain. Do not generate/revoke
   another token just to inspect it (one per account), paste values into chat,
   or rerun the full credential-store helper and overwrite working Drive inputs.
   Prepare verifies licence but does not prove broker/Drive authentication;
   the future supervised polls must establish actual acceptance/readback.
4. Set the actual inputs and reviewed interpreter (no py/python PATH command):

```powershell
$bootstrapPython = 'C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
$closeFile = 'REPLACE_WITH_ACTUAL_PRIVATE_DOWNLOADED_CSV_PATH'
$downloadedAt = 'REPLACE_WITH_ACTUAL_FRIDAY_COMPLETION_ISO_TIMESTAMP_WITH_+05:30'
```

```powershell
.\forward_daily_owner.ps1 -SessionDate 2026-10-16 -Action Prepare -BootstrapPython $bootstrapPython -CloseFile $closeFile -DownloadedAt $downloadedAt -AttestNseSource -ConfirmRun
```

Require MORNING_GO_SUPERVISED_START_REQUIRED, tasks still disabled. It is a
preparation report, not provider/Drive/capture/custody/training proof. Before09:15
completion includes both actual config creation and version-policy freeze.

5. Around08:00, after seeing Setup notification and accepting conditional enable:

```powershell
.\forward_daily_owner.ps1 -SessionDate 2026-10-16 -Action Start -BootstrapPython $bootstrapPython -ConfirmNotificationSeen -ConfirmEnableAfterTwoPolls -ConfirmRun
```

Keep this normal window open and PC awake. Do not close it or launch another
Start/poll. Owner available through09:30:30 to inspect supervised results and first
scheduled receipt. Require POLL_REMOTE_VERIFIED with counts1/74 then2/73, code
REMOTE_VERIFICATION_COMPLETE, local commit/receipt/remote flags true, clock PASS,
zero retries. The enable acknowledgement is not enabled-state/trigger proof.
Inspect actual09:30:30 scheduled success before calling recurrence operational.
No agent command here enables tasks; only the existing reviewed owner Start does.

6. Keep session available through15:40 and inspect scheduled audit plus gaps.
   If an audit is genuinely absent, the existing post15:40 read-only Audit route
   is documented in FRIDAY_CAPTURE_2026-10-16.md; no competing duplicate producer.
   Disable dated tasks after completed invocations if required by the runbook;
   never delete evidence, stop a producer or backfill a gap.

## One plain status ledger

PROJECT_STATUS_LEDGER_2026-10-16.csv is the single row-per-concept ledger, with
six requested columns. In cells: S=source inspected; B=builder directly tested/
observed; O=owner-reported (not independently inspected); NV=not verified. An O
success is meaningful owner evidence, not an independently signed custody proof.
The combined test column names Windows/owner, Linux and hosted-CI evidence
separately. General component tests never commission real accounts or transports.
There are35 rows, including the unconfirmed exposed-runtime-password rotation,
NSE transport, standing agent commissioning and whole-Supabase restore scope.
That database account is separate from PC capture auth; do not rotate it as a
Friday capture fix or claim that a source PR retired the exposed password.

The builder's PR36-candidate full results: Windows6040passed/7skipped; Linux
5926passed/121skipped;76subtests each. Owner reports640focused/0skipped on newly
installedPS7.6.7 and green PR36/main. Builder's full run usedPS5.1/7.6.5, NOT7.6.7.
Seventeen named storage/research source files were compared to the tested public
candidate and match; that does not attest their live factory wiring or hosting.
No actual holdout prices, private journals or credential values were examined.

## Tool inventory and zero-cost recommendations

BUILDER CURRENT observations: explicit reviewed venvPython3.13.9; Git2.55.0;
Node24.16.0; Docker client29.8.2; this agent's current PATH selectsPowerShell7.6.5.
O: owner installedPowerShell7.6.7, InstallManager26.4 and default py3.15.0. Both
PowerShell observations can coexist because processes retain PATH or bundle their
own runtime. Reviewed tasks still use WindowsPowerShell5.1. No upgrade is needed
for Friday; no full-suite claim on7.6.7 is made beyond owner's640focused cases.

Do not run py to discover versions: Install Manager may install a runtime on
first use. Keep3.15 installed if desired; do not alter defaults/uninstall tonight.
Use the explicit reviewed3.13.9 interpreter for every pinned command. Keep its
base runtime installed; a venv is not a standalone distribution.

7z was absent from agent PATH and C:/Program Files/7-Zip/7z.exe. This is not a
whole-PC search; an undiscovered portable installation is possible. 7-Zip and
the encrypted-disk rehearsal are custody prerequisites, NOT capture prerequisites.
After capture, owner may install free official7-Zip and do the harmless rehearsal,
then key-note and independent restore steps. No disk/encryption/password actions
are performed now. PostgreSQL clients/uv need not be installed for Friday; a
working Docker client is not proof of a running disposable database or restore.

New additive owner_capability_inventory.py defaults to PREVIEW, zero reads. Its
explicit --inspect-tools reads only PATH locations and distribution metadata;
never executes discovered binaries (including py), imports backends, installs,
queries tasks/services, reads capture through a capture/credential API or sends
network requests. PATH/current-directory and interpreter distribution discovery
can nevertheless traverse UNC/mapped/network filesystems: locality is NOT
ATTESTED, not a zero-network-access proof. Do not use from an untrusted or remote
working directory/environment. No optional inventory is required before capture.
Its status is NOT_CAPTURE_GO even when all tools are found. Run it outside the
clean tools checkout using the explicit interpreter if desired; not required today.

## Explicitly deferred and upload scope

No new PR or installation is required for Friday's already reviewed path. The
new reporting module is inactive and no capture dependency is added. The following
five-file list is HISTORICAL, superseded by the22-file exact list in
FORWARD_OBSERVER_UPLOAD_2026-10-16.md. Do not upload only these five. Source root
C:/Users/banga/Desktop/kiran_share_market/ -> identical relative destinations:

```text
owner_capability_inventory.py
tests/test_owner_capability_inventory.py
tests/test_project_status_ledger.py
PROJECT_STATUS_LEDGER_2026-10-16.csv
FRIDAY_OWNER_STATUS_2026-10-16.md
```

Do not upload local continuity/progress, installed capture/state, secrets or caches.
Do not rerun the historical nine-file checker on this new five-file reporting
group. It is not an exact-public-tree package: a publication manifest/checker must
be prepared/reconciled against the newest green main before an owner PR. No
morning operation depends on that publication. Focused offline checks:

```powershell
& 'C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe' -B -m pytest -q -p no:cacheprovider tests/test_owner_capability_inventory.py tests/test_project_status_ledger.py
& 'C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe' -B -m pyflakes owner_capability_inventory.py tests/test_owner_capability_inventory.py tests/test_project_status_ledger.py
& 'C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe' -B -m mypy --strict --follow-imports=silent owner_capability_inventory.py tests/test_owner_capability_inventory.py tests/test_project_status_ledger.py
```

Deferred:14Oct historical read-only audit; legacy result2/shared-root provenance;
why Time stopped; live alert visibility/dedup/independent delivery; exact option
schedule variable/history; authenticated full custody/restore; all-writer/cold
integration; shadow dedup/retention/steady-state capacity; licensed frozen paper
study, real labels/fills/calibration/drift and model/LLM backend commissioning.
No source tests or synthetic PnL create an edge or real training eligibility.

Earlier five-file reporting verification:23 tests passed on Windows and23 on network-disabled
Linux, zero skipped on each; pyflakes and strict mypy passed for all three Python
files on both. These checks concern the inactive reporting artifacts, not today's
capture or a new hosted-CI commit. PR36's earlier full-suite results are separate:
Windows6040passed/7skipped; Linux5926passed/121skipped.
The earlier18-file package's99/1Windows and88/12Linux focused results are historical,
not the refreshed22-file package's results. Use its current upload/evidence files.

Restore terminology: a verified NAV backup or local capture journal is not a full
Supabase/project restore. Supabase recommends off-site exports for free projects;
database backups exclude Storage API objects, and custom-role passwords are not
included in daily backups. Inventory database, object files and external settings
separately; never assume a six-table export covers all of them. No real full restore
or custody commissioning has occurred here. Official reference:
https://supabase.com/docs/guides/platform/backups

Technology radar: adopted existing pinned Python/PS5.1 and deterministic gates;
adapted a stdlib-only non-executing tool inventory; retained plain CSV over a new
dashboard. Considered uv/default-manager migration and extra plugins, deferred:
they add no necessary Friday capability. Native COM, auto-clock repair, paid
services and new task/workflow activation remain outside this report.
Next highest leverage: one real dated witness covering first supervised polls,
first automatic poll, final audit, missing-slot causes and owner-seen alert.

References: https://learn.microsoft.com/en-us/windows-server/networking/windows-time-service/windows-time-service-tools-and-settings
and https://docs.python.org/3/using/windows.html#python-install-manager
Token distinction: https://upstox.com/developer/api-documentation/analytics-token/
and https://upstox.com/developer/api-documentation/get-token/
