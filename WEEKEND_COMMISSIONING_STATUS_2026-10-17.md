# Weekend commissioning status — 17 October 2026

This is the superseding current-status handoff. Earlier Friday/weekend instructions
and progress history remain historical evidence, not instructions to repeat completed
steps. This document does not change a runtime gate or grant operational GO.
All operational times below are IST.

## Current position and provenance

Latest OWNER REPORT, not an independent read of tasks, private reports or installed
software:

- PR37 merged as `a6e5be8484565be0f3d1669d6c3e004f692478e8`.
- Finished 16 October poll/audit tasks are now disabled. Preserve their definitions,
  capsule, journal, reports, generation, recipe and markers; do not repeat Friday.
- 19 and 21 October Setup is complete; both dates' poll/audit tasks remain disabled.
  No additional Setup is needed. The repeated 21 October Setup used guarded existing
  task reuse, not force/overwrite; do not turn that behavior into a retry policy.
- Friday manual audit reported 75 raw polls, 75 recorded decisions, zero missing,
  all 75 slots observed; generation
  `17f7fbd62eafd8770ef2370becc5936a8fef16e4d6d71bee03f66d0ac08aabe9`.
  Cohort eligibility, training eligibility and remote custody remain false.
  Scheduled audit result 0 is not independent inspection of its saved report.
- Owner alert and awake drills now passed. This supersedes their earlier pending
  status. Synthetic popup visibility/native awake-request success does not prove
  production blocked-poll routing, independent delivery, all-day wakefulness,
  restart protection or failure recovery. No deliberate production failure drill.
- Owner reports 7-Zip 26.04 and PostgreSQL 17.11 installed, including a PostgreSQL
  server with automatic startup on port 5433. Installation is not restore acceptance.

SOURCE-VERIFIED behavior: the original coordinator checks date/deadline/calendar,
refuses Setup while any matching capture task is not Disabled, registers only
missing dated roles, and validates existing bindings/state without `-Force`.
It has no Setup-once marker: repetition is not inherently read-only or necessary.
Prepare and Start remain distinct guarded actions. These source facts do not
independently verify the owner-reported machine state above.

## Machine-setting decision

Keep the installed tools/server as they are for now. Under the standing non-admin
workflow, do not stop/uninstall the server, change startup/service settings, ports,
firewall, ACLs, privileges or database configuration. Do not start a fresh database
or expose port 5433 as part of this handoff. Review dependencies and idle usage
first; any later manual/idle-start policy requires a separately reviewed,
explicitly authorized owner change. No elevation or privilege-change instructions
are issued here. PostgreSQL clients can support later custody work; installing a
server was not a capture prerequisite and is not a reason to alter Monday capture.

## Monday 19 October: one manual Prepare → Start route

Use the existing clean reviewed original tools checkout and explicit approved
Python 3.13.9 path, not a default `py`/`python` and not an edited frozen capsule.
No Setup repetition. Keep the new guided route out of Monday's attempt; review and
commission it on a different eligible date before that date's first attempt.
Do not switch routes after any partial/unknown outcome.

Wake/check the host around 07:15; obtain the genuine official 16 October close
file on Monday morning and record its actual download-completion timestamp.
The existing pinned calendar/source checks remain authoritative. Never relabel
an old download. Keep private paths and credentials private.

The following command interfaces are verified in `forward_daily_owner.ps1`.
Variables must already contain the actual approved interpreter, actual downloaded
file and actual aware Monday completion timestamp; this document supplies none.
Run in a normal interactive PowerShell window, one step at a time:

```powershell
.\forward_daily_owner.ps1 -SessionDate 2026-10-19 -Action Prepare -BootstrapPython $bootstrapPython -CloseFile $closeFile -DownloadedAt $downloadedAt -AttestNseSource -ConfirmRun
```

Require `MORNING_GO_SUPERVISED_START_REQUIRED`; configuration, policy freeze and
final Prepare gate must all finish before 09:15. Attestation must be personally
true. Only after that successful report and the personally observed Setup
notification, use the same route once:

```powershell
.\forward_daily_owner.ps1 -SessionDate 2026-10-19 -Action Start -BootstrapPython $bootstrapPython -ConfirmNotificationSeen -ConfirmEnableAfterTwoPolls -ConfirmRun
```

Aim around 08:00. Start's wait-entry limit is 90 minutes before 09:20:30
(07:50:30 earliest wait entry); initial checks/attempt marker occur before waiting,
so boundary launches are not guaranteed safe. Never launch at the last second.
Keep the window/session available and PC awake through supervised 09:20:30 and
09:25:30, first automatic 09:30:30, final poll 15:30:30 and audit 15:40.
`WakeToRun=false`; the drills do not remove this availability requirement.
Start alone performs its guarded conditional enable. No separate manual enable,
parallel wrapper, catch-up, retry, backfill or marker reset. On blocked/unknown,
stop and review redacted stage/effect/rollback evidence.

20 October is closed in the reviewed schedule; Wednesday preparation remains a
genuine 21 October morning action using the prior session's close. Completed
Wednesday Setup is not completed Wednesday Prepare or automatic morning admission.

## Open items — not cleared by Friday coverage or the drills

### Fresh capacity snapshot: owner read-only, no market rows

The 394MB figure from11Oct is stale. Do not calculate current runway from it.
Through the established owner read-only SQL route, run only this metadata block
and report timestamp/bytes, not connection details. No new grants or credentials:

```sql
BEGIN READ ONLY;
SET LOCAL statement_timeout = '10s';
SELECT now() AS observed_at,
       pg_database_size(current_database()) AS database_bytes,
       (SELECT sum(pg_database_size(oid)) FROM pg_database) AS cluster_bytes;
ROLLBACK;
```

Use cluster bytes against the500000000-byte planning limit, then subtract the
24000000-byte admission floor for usable planning margin. This is a dated size
snapshot, not a write-capacity guarantee or provider quota redefinition. Do not
run unrelated payload/history queries from older diagnostics. No hosted database
query was run by the builder. Supabase's free-tier guidance recommends exports
and off-site backups; database backups do not include Storage API object bytes.
[Official backup scope](https://supabase.com/docs/guides/platform/backups).

### Remaining acceptance work, in order

1. **14 October audit:** preserve original pins/capsule; review and use only the
   appropriate read-only historical audit path. No builder/private inspection or
   completed historical-audit claim here.
2. **Legacy exit 2/shared writes:** preserve task/report/file metadata and trace
   exact old code without executing the old audit or altering shared state.
   Exit 2 alone does not establish cause or write attribution.
3. **Time 12:48/root dispersion:** bounded owner read-only event/metadata review
   remains needed. Distinguish Windows service/dispersion from the producer's
   fresh per-poll offset/uncertainty gate. No automatic service or clock repair.
4. **OPTION_CAPTURE_ENABLED skips:** inspect exact workflow commit/run/condition
   and variable state through a separately authorized review; no setting enable,
   hosted change or inferred missing snapshots.
5. **Custody/key/disk/Drive:** protect the signing-key note privately; validate
   encrypted-disk recovery, Drive capacity/retention and authenticated independent
   same-generation restore. Tool installation or local replica success is not
   independent custody. No deletion before accepted custody and restore.
   Start with the existing OWNER_KEYS_AND_BACKUP_RUNBOOK.md and
   CUSTODY_ALERT_PACKAGE_2026-10-12.md previews; installing7-Zip is not permission
   to copy a key or commission deletion. Keep the recovery passphrase and its
   independent recovery method separate from the encrypted archive. Validate
   recovery on disposable non-market rehearsal data first, never print keys.
6. **Fresh database/restore:** design an isolated fresh restore target only after
   dependency/credential review and owner authorization. Full-project restoration
   includes settings/external objects, not just six tables or NAV. Current server
   installation is not this drill. Previously flagged runtime credential rotation
   remains unconfirmed; no credential reads, resets or expanded hosted writers here.
7. **Storage:** consistent-cut exports, all-writer guards/cold-reader wiring,
   unknown-COMMIT/race acceptance, lossless deduplication, source-specific bounded
   retention, capacity controls and independent alerts remain commissioning work.
   No hosted migration, deletion or schedule activation is authorized here.
8. **ML/licence/paper labels:** real model/LLM/backtest use stays held pending
   licensed use, point-in-time labels, preregistration, frozen paper-first study
   and sufficient independent sessions. Seventy-five correlated observations are
   not 75 independent days, a fill label or evidence of a trading edge.

## Release provenance and upload frictions

The old 22-file manifest/checker and their exact base/prerequisite pins are
historical immutable package evidence. Do not repin, regenerate or insert this
new handoff into that package. Owner-reported PR37 merge is not a new execution
of its pre-commit exact-base staged checker. Preserve the recorded distinction
between synthetic checks, owner acceptance and exact-commit hosted CI evidence.

For any separately authorized future upload: the broad CSV ignore rule needs only
a narrow exception for the specifically reviewed public ledger, never all CSVs or
private exports. Git author identity, if needed, is local to the upload repository
with owner-approved values, not a global identity change. Put mypy cache in a
disposable temporary location outside the staged payload; never stage caches or
broaden ignore/permission policy to make a check pass. These are recorded upload
frictions, not commands to modify the completed package.

This handoff adds documentation only. No new tests, live-state verification,
native actions, machine-setting changes, hosted operations or commissioning are
claimed by its creation. No personal names, secrets or private paths are required.
