# Observe without controlling capture

## Friday complete: preserve it; do not run capture again

Owner-reported16Oct evidence: Start completed; supervised remote receipts1/74 then
2/73, clockPASS; enable acknowledged; owner saw first automatic09:30:30receipt.
Final owner report now establishes manual Audit75/75/0missing, all75observed slots,
generation17f7fbd62eafd8770ef2370becc5936a8fef16e4d6d71bee03f66d0ac08aabe9.
At18:03 poll last15:30:31 and scheduled audit15:40:00 bothresult0/missed0/Ready/
no nexttrigger. This is OWNER evidence, not builder private-state verification.
Training/cohort/custody remainFALSE. Preserve Friday capsule/files/state; no repeat
Start, capture run, deliberate failure or marker reset. Exact finished-task disable
and weekend19/21Oct Setup are in WEEKEND_OWNER_PLAN_2026-10-16.md. The scheduled
audit actually ran; its report contents were not independently inspected here.

This package is additive and inactive. Review/upload/CI may happen during capture
in a SEPARATE public clone, but no commissioning/install/action in its live capsule.
The builder did not read today's state or query its tasks. New tools were exercised
only on synthetic fixtures; no real popup, power request, registry read or task
query occurred in building them. Do not silently turn source tests into a GO.

## 1. Midday status: narrow, single read; not a journal audit

After review and explicit owner choice, run FROM A SEPARATE OBSERVER CHECKOUT,
never copy into the installed capsule or dirty the reviewed tools checkout. Default
preview does not read supplied roots. Normal PowerShell; explicit Python3.13.9.
Use already-established private root variables; do not put values in an upload.

```powershell
& $bootstrapPython -B .\forward_live_status.py --root "$forwardPrivateState" --ops-root "$forwardOpsRoot" --session-date 2026-10-16
```

Require PREVIEW/zero reads. The opt-in READ-ONLY command, if owner chooses it:

```powershell
& $bootstrapPython -B .\forward_live_status.py --root "$forwardPrivateState" --ops-root "$forwardOpsRoot" --session-date 2026-10-16 --inspect-read-only
```

Only today's date-prefixed operations JSON and named versioned receipt/failure JSON
are opened (bounded65536 directory names/1024 selected files/32KiB per file).
Nonmatching historical names are not opened. No journal, config,
recipe, inputs, prices, SQLite, credentials, network API, task action or write.
Locality is not attested for mapped drives; this is not a hostile-filesystem sandbox.
Leaf regular-file/descriptor identity and before/after size/time checks reject
replacement/incomplete reads. Concurrent writes make this a non-atomic snapshot.

Read the result literally:

- scheduled_slots_elapsed counts the nominal :30 triggers elapsed by the observer's
  unverified PC clock; future_slots are NOT missing.
- The90s reporting grace is DISPLAY ONLY. It does not change the producer's slot
  acceptance window, authorize retry, or prove any slot failed.
- successful_process_reports are fully shaped unsigned terminal claims, not slots.
- highest_unbound_receipt_decision_count is only a cumulative unsigned manifest
  claim. Existing manifests have no session/slot identity; they are deduplicated by
  generation+spec hash, not trusted as exact coverage. A copied75-count receipt
  cannot prove this session or zero a missing count.
- elapsed_missing_count and missing_slots deliberately remain NOT_ESTABLISHED.
  Only the existing post-close journal audit can establish exact75-slot coverage.
- incomplete/invalid metadata is unknown evidence; never repair/retry capture.
- Exit0 means the observer ran, NOT capture GO, custody, clock or completeness.

Task state is a separate read, not inferred from an enable acknowledgement:

```powershell
powershell.exe -NoProfile -File .\forward_observer_tools.ps1 -SessionDate 2026-10-16 -Action TaskStatus
powershell.exe -NoProfile -File .\forward_observer_tools.ps1 -SessionDate 2026-10-16 -Action TaskStatus -ConfirmReadOnly
```

These query only the two exact dated tasks, output state/result/times without
account/action/path values, and never execute or change them. Missing/failed queries
and nonboolean enabled fields stay unknown. No binding or execution proof inferred.
Use only the reviewed observer script from its separate checkout. This is optional;
if not reviewed in time today, keep the successful existing procedure and wait for
the scheduled audit rather than rushing an unreviewed live diagnostic.

## 2. Friday close: the recorded complete-day witness

The owner supplied the final task execution and manual read-only audit evidence
above. Keep the actual results/generation privately. No missing slots are reported
for16Oct; do not invent cause labels. In any other incomplete audit retain gaps as
MISSING_NOT_OBSERVED or RAW_ONLY_NO_DECISION per the original audit; no backfill.
75/75 is not a trading or training approval. Acknowledgement is not execution.
If audit is missing/blocked, preserve state and report before any rerun. Do not
re-enable legacy raw-only audit or edit shared roots.14Oct forensic audit and the
legacy result2/shared-write investigation remain separate read-only work.

## 3. Synthetic local alert drill AFTER today

Once capture/audit have finished, after16:00IST, normal interactive PowerShell:

```powershell
powershell.exe -NoProfile -File .\forward_observer_tools.ps1 -SessionDate 2026-10-16 -Action AlertDrill
powershell.exe -NoProfile -File .\forward_observer_tools.ps1 -SessionDate 2026-10-16 -Action AlertDrill -ConfirmAfterSession -ConfirmNoCaptureRunning
```

Preview first. The second invocation explicitly authorizes ONE labelled synthetic
Yes/No message box with the same Windows Forms primitive as local notifications.
Choose Yes only after seeing/reading it. Save only redacted JSON privately.
No capture read, marker, dedup namespace, journal, task, credential or alert transport
is touched. No deliberate poll failure, no production marker reset. One rehearsal
per chosen attempt; investigate failures instead of blind repeated attempts.

owner_clicked_yes proves a button response to this synthetic popup only. It does
NOT prove the producer's failure classifier, async child launch, dedup/restart
path, unattended session or independent alert delivery. Existing synthetic tests
exercise routing/dedup separately. The next acceptance milestone is an isolated
dummy-task full wrapper drill with a private dummy operations root, then future
owner commissioning; it must never point at real capture. That full native path
remains unverified in this package.

## 4. Future preopen sleep/update precautions

No power/update setting is changed by this package. AFTER today's session, owner
may review Windows Settings > Windows Update: complete pending restarts before
capture; set active hours covering07:00–16:00 and enable restart notifications if
desired. This is a separate owner setting decision, not an automated change.
Active hours reduce restart risk, not guarantee immunity to update deadlines,
manual restart, crashes or power loss. Do not disable update services or install
shutdown-abort loops, mouse jigglers, registry policies or privilege changes.

Optional read-only future risk signals (two known pending-reboot registry keys):

```powershell
powershell.exe -NoProfile -File .\forward_observer_tools.ps1 -SessionDate 2026-10-19 -Action HostRisk
powershell.exe -NoProfile -File .\forward_observer_tools.ps1 -SessionDate 2026-10-19 -Action HostRisk -ConfirmReadOnly
```

No signal is NOT proof no restart is possible. Active hours/power policy remain
unverified. Review Settings before the next session; preserve any pending warning.

Harmless native API rehearsal AFTER session/16:00, with the same idle attestation:

```powershell
powershell.exe -NoProfile -File .\forward_observer_tools.ps1 -SessionDate 2026-10-16 -Action AwakeDrill
powershell.exe -NoProfile -File .\forward_observer_tools.ps1 -SessionDate 2026-10-16 -Action AwakeDrill -ConfirmAfterSession -ConfirmNoCaptureRunning
```

This requests then unconditionally releases the same native lease, without a
wall-clock wait (even if time moves backward); require both request
and release acknowledgement. It does not test all-day physical sleep prevention.
No native rehearsal was run by the builder. If blocked, do not commission the lease.

After separate owner commissioning/rehearsal, a FUTURE day's preopen lease can be
requested07:00–09:15IST in a dedicated normal window; not today:

```powershell
powershell.exe -NoProfile -File .\forward_observer_tools.ps1 -SessionDate 2026-10-19 -Action AwakeLease
powershell.exe -NoProfile -File .\forward_observer_tools.ps1 -SessionDate 2026-10-19 -Action AwakeLease -ConfirmAwakeLease
```

The process requests ES_CONTINUOUS|ES_SYSTEM_REQUIRED, ends15:50 or after9h,
and restores the previous thread flags in finally. Use the documented FRESH
powershell.exe -NoProfile -File process, not dot-sourcing/runspace reuse.
It changes no persistent power plan/ACL/task. Closing the
process ends protection. Native request/cleanup success, not effective all-day
sleep prevention, must be witnessed in a harmless post-session native rehearsal
before routine use (current native effect NOT VERIFIED). Use AwakeDrill above,
never fake a date/time to reach a gate. Manual sleep/lid closure,
battery depletion, sign-out and Windows Update restart are not prevented.
Keep AC/lid/logged-in safeguards and a post-session health report regardless.

## 5. Reusable operations runner: build on the reviewed coordinator

Do not add a second scheduler or a generic shell gateway. Existing daily_owner
already owns Setup/Prepare/Start/Audit; future consolidation should present one
guided morning command around it, validating exact source/interpreter hashes,
calendar, disabled bindings, health, genuine fresh download and policy, then
waiting for the two polls and enabling audit-first/poll-last only after admission.
Stop on unknown outcomes; preserve markers. No auto-date rollover or auto-retry.

The new forward_operations_runner.py is a PURE allow-listed PLAN, not execution.
Only Setup/Prepare/Start/Audit/Status/AlertDrill labels exist; unknown calendar
blocks. calendar-kind REGULAR is supplied metadata, NOT calendar verification.
Execution, token reads, attestation synthesis and task mutation are absent.
It preserves the two human attestations: actual source/download and personally
seen notification. Neither a plugin nor an LLM can check those on the owner's behalf.
Daily official download transport remains unresolved; no browser scraping bypass.

Setup Mon19Oct and Wed21Oct can be owner-run separately in advance (<=7days),
using the existing green pinned daily-owner routine, with tasks DISABLED.20Oct is
Dussehra closed per NSE; existing reviewed calendar must still agree before any
Setup/Prepare/Start. Do not schedule a20Oct capture or assume holiday metadata
commissions a new producer. Prepare remains genuine session-morning source.

## 6. Token and custody prerequisites: owner steps, after session

1. Record ONLY the Analytics Token's real expiry timestamp privately; do not read,
   decode, print or regenerate the token to produce a reminder. There is already
   an explicit producer FORWARD_TOKEN_EXPIRES_AT gate; do not replace it. The pure
   runner accepts an optional owner expiry date and reports unknown/expired/due
   within30days, without credentials or reminders being scheduled. Analytics
   validity is about one year, not the standard OAuth3:30AM rule. Coordinate renewal
   after hours because one active Analytics Token per account means replacement
   may affect consumers. No token or expiry was inspected here.
2. Install7-Zip only from7-zip.org after session; verify provenance before use.
   Do the harmless AES-256 rehearsal on the empty external disk, protect/archive
   the signing key as already reviewed, then actual same-generation restore.
   Do not delete anything before verified independent custody and restore.
3. Obtain PostgreSQL client tools through postgresql.org's Windows download path
   (portable binaries available); retain explicit approved paths. Match pg_dump
   major to server17 or a compatible newer reviewed version. A client install is
   not a full Supabase project restore; hosted changes stay owner-only/off.
4. Then commission consistent-cut exports + full-image/six-table custody together,
   all writer/cold-reader wiring, dedup, retention and capacity alerts, in that order.
   No generic green suite substitutes for each native/restore acceptance gate.

## Technology decision record

Adopt: fixed repo-native observer actions, explicit Python3.13.9/WindowsPS5.1,
stdlib bounded reads, source selectors and public JUnit per-concept reporting.
Adapt: Windows process-only awake lease; no persistent power plan or restart block.
Desktop Commander is free MIT, but its own security policy says allowed directories
and blocked commands are advisory, not a sandbox; arbitrary terminal execution
can bypass them. It is not a capture operator. If useful later, isolate it in a
disposable VM/container with public source only, no state/secrets/scheduler access.
Plugin directory search did not return an exact Desktop Commander integration;
that is not proof none exists. No plugin was installed/connected or permission
changed. Generic agents remain report-only; builder/checkers were kept separate.
PowerToys Awake is a free alternative, but another background app adds no necessary
capability to the narrow reviewed lease; not installed/evaluated natively here.
Paid monitors, cloud VMs and paid notification tiers rejected by zero-cost rule.

Sources reviewed16Oct2026 (provider documentation, not secondary issue claims):
- https://github.com/wonderwhy-er/DesktopCommanderMCP/blob/main/SECURITY.md
- https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate
- https://learn.microsoft.com/en-us/windows/deployment/update/waas-restart
- https://learn.microsoft.com/en-us/windows/powertoys/awake
- https://upstox.com/developer/api-documentation/analytics-token/
- https://www.nseindia.com/resources/exchange-communication-holidays
- https://www.7-zip.org/
- https://www.postgresql.org/download/windows/

Next highest leverage: close today's real-day witness WITHOUT interference, then
prove a synthetic alert end-to-end in an isolated dummy task. Do not add models or
general-purpose automation before the operations and custody evidence exists.
