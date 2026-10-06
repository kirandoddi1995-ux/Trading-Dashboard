# Revised first relief: protect admission before attempting cleanup

This small package is separate from the unfinished permanent-storage package.
No hosted changes, deletions, VACUUM, workflow dispatches or settings changes were
made by the agent. Capture-loaded files and PROJECT_ROADMAP.md are unchanged.

## Confirmed findings

At 10:32:24 IST, SELECT-only inspection confirmed cluster 495,180,597 bytes,
current database 479,906,963: nominal reserve 4,819,403 bytes below 500,000,000.
This agrees with the owner's 10:22 reading. The morning +1,122,304-byte growth
cannot safely be extrapolated as a smooth rate; remaining collector runs write bursts.
The same read-only measurement at 10:45:53 IST was unchanged. This short quiet
interval does not establish room for the 14:37 or 15:45 collection bursts.

A single ledger event at 10:08:16 IST is DECISION_BATCH_EVALUATED, with payload
622,246 stored bytes / 2,533,991 bytes as JSON. Only metadata/lengths were inspected,
not candidate values, prices or historical holdout performance. It is consistent
with the ledger's +638,976 allocation increase: payload bytes and allocated pages
are different measures. The scheduled Stage-1 collector packages its full universe
into a signed decision batch. One event is not necessarily a small event.

Daily volumes: heap 4,808,704; indexes 3,923,968; TOAST 8,192 bytes; estimated
66,358 live / 13,293 dead rows and 80,005 cumulative updates. The installed quote
trigger inserts a daily maximum for each instrument/date and unconditionally
updates the existing maximum on conflict, even if it did not increase. Real volume
increases also require updates. These counters do not identify exactly how much
churn was avoidable. Daily-volume history protects the volume baseline AND raw
quote archival; do not delete it or remove its trigger to save space.

Stable allocation with growing live rows elsewhere shows reuse is possible; it
does not prove unlimited reuse or spare capacity transferable to the ledger.
Parent/TOAST statistics and estimated live counts are not exact free-space maps.

Follow-up bounded read-only checks found zero transactions older than five minutes,
snapshot-retaining slots, prepared transactions and running vacuums. Recheck before
maintenance; this is a point-in-time observation, not a vacuum completion guarantee.
The daily-volume baseline is 66,358 exact rows, whole-row maxima fingerprint
`81d33e79573f613294106c7f0fac5791`. Its purpose is before/after comparison, not an
independent correctness certification of the market volumes.

## My revised decision

The previous “NAV relief first” order is insufficient as protection from today's
active writers. Use: stop admitting non-essential collector writes first, ordinary
maintenance on the actual churn table, verified NAV relief next, then permanent
ledger/other-table archival and transaction admission. Do not rush ledger deletion
or a table rewrite to meet a collector slot. Paying/pausing were previously ruled
out as preferred solutions; nevertheless no design can guarantee preservation if
unbounded new writes must continue while verified physical relief is unavailable.
This is an explicit temporary safety hold, not a claim that a pause solves storage.

## Owner actions before the remaining runs

1. If this reviewed package will not be fully on main before the next dispatch,
   open GitHub → repository → Actions → Scheduled evidence collector → the workflow
   menu → Disable workflow. Confirm no collector is still running; disabling does
   not stop an in-flight run. Prefer letting an existing bounded run finish rather
   than cancelling it mid-write; measure immediately and seek review if space falls.
   This affects the external dispatcher because it targets scheduled-collector.yml.
   Do not disable Verified Drive archive, independent capture or monitoring jobs.
   Leave archive switches enabled. Do not run optional dashboard scans or reload it
   unnecessarily: the app can auto-scan after restart. Record this collection gap
   honestly. If a hold is unacceptable, the remaining capacity risk is not solved.
2. To avoid an unnecessary dashboard restart/auto-scan when uploading this collector
   patch, owner may temporarily set DASHBOARD_RELEASE_ENABLED=false, let any existing
   publication finish, then upload the three executable/test files below as one
   consistent group. This pauses application promotion, not research collection.
   Do not change the live expected fingerprint. Restore promotion only after review
   and a safe capacity assessment; do not forget this temporary owner setting.
3. Upload collector_storage_preflight.py to repository ROOT,
   tests/test_collector_storage_preflight.py to tests/, and the complete
   .github/workflows/scheduled-collector.yml to .github/workflows/. Do NOT upload
   the unfinished permanent-storage readers, migrations or fingerprint changes.
   Wait for CI on the final main SHA. The dispatch workflow uses main independently
   of the dashboard's release branch. External dispatch must continue targeting main.
4. If disabled, re-enable this workflow only after the guarded version is on main.
   At today's size, its next requested run should fail visibly at storage admission
   BEFORE migration, runtime schema checking, lease/run creation or provider calls.
   Require COLLECTOR_STORAGE_BLOCKED, allowed false, exit 2. A permissions failure
   produces STORAGE_CHECK_UNAVAILABLE and also stops the workflow. This is not a
   successful collection and must not be labelled SUCCESS or silently skipped.
   No manual dispatch is required merely to prove the numerical policy: offline tests
   cover today's measurement. If you dispatch a check, keep apply_migrations false.
5. Run sql/storage_burst_diagnostics_read_only.sql blocks separately. Recheck quota
   in the Supabase dashboard and recheck maintenance blockers immediately before any
   VACUUM. Only you run ordinary commands, separately, outside BEGIN:

   ```sql
   VACUUM (ANALYZE) quant_app.market_daily_volumes;
   VACUUM (ANALYZE) equity_research.outcomes;
   ```

   Market daily volumes has actual update churn; outcomes has independently reported
   dead TOAST chunks. Preserve all rows. Read-only before/after maxima fingerprint
   and row counts should agree absent legitimate concurrent writers; reconcile any
   changes rather than claiming preservation from a guessed count.
6. Follow STORAGE_FIRST_RELIEF.md for existing verified NAV preview → export/readback
   → 100-row deletion trial → bounded deletion, protecting latest per scheme. Then
   ordinary NAV vacuum and measurements. The sequence within that archival operation
   is unchanged. It is supplementary relief, not protection for ledger page growth.
   No daily-volume/ledger deletion is authorised by this guide. No FULL/REINDEX,
   TRUNCATE, trigger removal or emergency ledger re-signing.
7. Require fresh allocation/usage and remaining burst estimates before resumption.
   The helper requires at least 24,000,000 nominal bytes (20 MB reserve + 4 MB allowance),
   and a restricted non-superuser/non-BYPASSRLS role. This is a conservative interim
   admission floor, NOT a proven maximum allocation per run or permanent resume
   criterion. Unknown size/clock/permissions block. Do not lower it to make collection
   pass. Keep derivatives held. If cleanup only creates internal reuse and headroom
   stays below the floor, the collector remains blocked while permanent work proceeds.

## Scope and important limitations

The new helper performs SELECTs in a read-only TLS-required connection with 5-second
connect, 10-second statement and 2-second lock bounds. It counts ALL cluster databases
and rejects missing/invalid measurements, stale/future clocks and unsafe roles.
There is no secret argument, raw exception output, credential dump or owner fallback.
It runs before any migration and rechecks immediately before requested collection.

This preflight is NOT transaction-enforced. Concurrent app/writer activity can still
consume capacity after a passing check, and a run can allocate more than the allowance.
It only covers this workflow: direct CLI invocation, other workflows and the live app
are not guarded. Essential durability, outbox delivery, archival and monitoring remain
separate; do not strand already-created evidence by indiscriminately revoking writes.
Finish the permanent all-writer transaction guard, alerts, cold readers and recovery.

The owner-level connector could not SET ROLE quant_app_runtime in a read-only probe.
Therefore runtime permission to sum all database sizes has NOT been verified here.
The workflow will fail closed if it lacks that permission. Do not substitute an owner
URL or grant broad privileges to clear it. Commission a narrowly scoped read-only
measurement interface as part of permanent admission if necessary.

The failed permission probe was separately executed as:

```sql
BEGIN READ ONLY;
SET LOCAL statement_timeout='10s';
SET LOCAL lock_timeout='2s';
SET LOCAL ROLE quant_app_runtime;
SELECT current_user;
ROLLBACK;
```

The connector reported permission denied to set that role; it did not establish
runtime privileges. No owner connection details or credential values were output.

The no-op daily-volume update is worth a separate reviewed SQL optimisation, with
maxima/permissions/concurrency tests. It does not solve genuine new-day rows or the
large immutable batch payloads, so this package does not rush that schema change.
Existing signed batches cannot be shortened/replaced; future payload redesign needs
versioned exact evidence references and restore/read-path tests.

## Local verification and upload group

```powershell
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_collector_storage_preflight.py tests/test_scheduled_collector_workflow.py --basetemp "$env:TEMP/storage-gate-$([guid]::NewGuid().ToString('N'))"
.venv/Scripts/python.exe -m mypy --strict --follow-imports=silent collector_storage_preflight.py
.venv/Scripts/python.exe -m pyflakes collector_storage_preflight.py tests/test_collector_storage_preflight.py
```

Executable upload group: the helper, its test and the workflow (three files).
Optional documentation: this runbook and sql/storage_burst_diagnostics_read_only.sql.
AUTOMATION_PROGRESS.md/STORAGE_UPLOAD_MANIFEST.md are continuity records containing
unfinished work, not a request to upload the entire working tree. No app fingerprint
file is changed by this package. Final full-suite result: 2,143 passed, four unchanged
skips, two subtests passed (586.37 seconds). Final focused check: 38 passed (3.09
seconds). Strict type checking and lint are clean. The full suite includes actual
offline app login/settings boot and disposable SQL tests. Self-review checked
role/clock/type failure paths, redaction, read-only connection settings, both
workflow checks and compatibility with the existing collector command. These
checks do not commission hosted runtime measurement permissions or global admission.

Sources: [PostgreSQL statistics](https://www.postgresql.org/docs/17/monitoring-stats.html)
and [ordinary vacuum behaviour](https://www.postgresql.org/docs/17/routine-vacuuming.html).
