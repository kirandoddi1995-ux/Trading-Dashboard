# Morning capture failure and storage response — owner review package

No tasks, credentials, hosted settings, database rows or Drive objects were changed.
The two complete replacement Python files are staged separately so active tasks
continue to read unchanged root files. Do not run the staged scheduler directly:
its imports still resolve to the workspace. It is a review package, not an isolated
capture installation.

## Findings

Read-only Task Scheduler inspection confirms all three tasks use this workspace's
Python and runner. Prepare and polls returned 2; receipts only said SCHEDULER_BLOCKED.
Today's config.json does not exist. Therefore polls cannot capture; an overnight
source fingerprint change is not established as the preparation failure. Current
licence acknowledgement and clock checks passed. A bounded official NSE prior-close
GET reproduced ReadTimeout. Its roughly 20-second duration fits the preparation
receipt timing, but the historical receipt cannot establish its original exception.
No token or private path was printed. Audit's not-yet-run result is not a failure.

At 09:47:54 IST the SELECT-only measurement was current database 479,104,147 bytes,
cluster 494,377,781: nominal headroom 5,622,219 bytes. Compared with the owner's
09:20 cluster reading, allocation increased 319,488 bytes. This short interval
does not identify the growing table or predict the day's collection bursts.
An initial query excluding non-connectable databases understated cluster usage;
it was corrected to sum ALL pg_database rows. Use the corrected saved query.

Outcomes: parent allocation 60,178,432; heap 253,952; parent indexes 393,216;
TOAST total 59,498,496. Parent reports zero dead tuples and autovacuum 01:28 UTC
today, but TOAST independently reports 12,646 live / 2,900 dead chunks, last
autovacuum Oct 4 23:16 UTC. Neither relation has custom reloptions. Parent vacuum
statistics do not certify that TOAST has just been cleaned. These are estimated
statistics, not an exact free-space map. Allocated minus live payload bytes is
NOT an exact removable-bloat estimate.
NAV: allocation 43,532,288, estimated 61,537 live / 9,122 dead rows. Ledger
allocation 55,508,992 with 9,619 estimated live rows and zero dead. No automatic
safe ledger pruning has been commissioned; do not delete its history.

The SQL issued for storage is in sql/capture_morning_storage_read_only.sql.
Transactions were READ ONLY, 10-second statement and 2-second lock timeouts;
the connector itself remains owner/BYPASSRLS, not a restricted read-only login.
The follow-up blocker check found zero transactions older than five minutes,
zero snapshot-retaining slots, zero prepared transactions and zero running vacuum.
Recheck immediately before maintenance; younger transactions can still delay cleanup.

## What the staged repair changes

- nifty_previous_close.py: requests transport failures, including streamed reads,
  become NSE_CLOSE_TRANSPORT_UNAVAILABLE without raw exception text. TLS, origin,
  date/hash checks, timeouts and no-fallback behaviour are unchanged.
- forward_nifty_schedule.py: polls identify SESSION_NOT_PREPARED before credentials
  or capture. Failure receipts identify the mode. Post-close audit reports an
  incomplete session with 75 missed decisions when both recipe and state are
  absent. Unexplained state without a recipe blocks instead of claiming zero rows.
  Existing source-hash mismatch codes are preserved rather than generic failures.

This improves diagnosis and missing-day accounting, not network availability.
There is no retry loop, relaxed clock check, synthetic close, after-open preparation,
catch-up decision or widened sampling window. Source availability remains a
commissioning blocker until a genuine pre-open preparation succeeds.

## Owner steps, in order

1. Today: do not rerun prepare after 09:15 and do not copy yesterday's recipe into
   today. Preserve receipts. In Task Scheduler, you may disable the poll task to
   stop repeated known failures. Do not delete tasks or research state. The original
   audit will still fail generically today if the repair is not installed first;
   that is expected and must not be reported as a successful capture day.
2. Storage NOW: follow STORAGE_FIRST_RELIEF.md, starting with read-only measurements,
   latest-NAV fingerprint, preview, verified export and the 100-row deletion trial.
   Only you perform deletion. Continue reviewed bounded NAV archival; retain latest
   values. Do not wait for the unfinished permanent package or upload its runtime.
3. Before maintenance, recheck long transactions/slots/prepared transactions/running
   vacuum using the existing storage-relief read-only checks. If clear, run these
   separately in Supabase SQL Editor, outside a BEGIN block:

   ```sql
   VACUUM (ANALYZE) equity_research.outcomes;
   VACUUM (ANALYZE) quant_app.mf_nav;
   ```

   Re-run the morning size/TOAST checks and NAV fingerprint. Stop on errors. Ordinary
   vacuum enables relation-local reuse; physical shrink is not guaranteed. No FULL,
   REINDEX, table rewrite or truncate at this headroom. NAV reuse cannot absorb new
   ledger pages. Avoid optional manual scans while the admission guard is unfinished.
4. After today's tasks have finished (or you have disabled all three and verified
   none is running), preserve copies of the two root Python files privately. Review
   staged_capture_repair/forward_nifty_schedule.py and nifty_previous_close.py, then
   replace their ROOT counterparts as one maintenance operation. These are complete
   files, not diffs. Do not replace shared modules while capture tasks run.
5. Upload those two files to the repository ROOT, the new regression test to tests/,
   and this runbook if desired. Do not upload the staged directory as a runtime path
   or the unrelated permanent-storage working set. Run the normal CI. Task actions
   need no change for this repair; no live fingerprint expectation change is requested.
   After 15:40, you may run the audit task once with the repaired root files. If
   today's recipe and state are both absent, expect SESSION_CAPTURE_INCOMPLETE,
   SESSION_NOT_PREPARED, 75 missing decisions and exit 1 (not success). If unexplained
   state exists, expect BLOCKED instead. Never rerun prepare to disguise today's gap.
6. Tomorrow before the open: verify credentials privately, keep the workspace and
   .venv unchanged for the capture day, and watch preparation. Require CONFIG_PREPARED
   (or validated CONFIG_ALREADY_PREPARED), correct previous-session date and no
   BLOCKED receipt. If preparation fails, do not enable polls expecting recovery.
   Share the stable failure code only. Resume scheduled polling only after preparation
   succeeds; verify the first poll and the after-close audit. Lost slots stay missing.

## Offline verification before replacing files

From the workspace, run:

```powershell
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_staged_capture_repair.py tests/test_forward_nifty_schedule.py tests/test_nifty_previous_close.py --basetemp "$env:TEMP/capture-check-$([guid]::NewGuid().ToString('N'))"
```

The new test uses the staged complete files before replacement. After replacement,
existing tests exercise the installed files. The separate staging regression test
requires the staging folder locally; CI portability is addressed by its explicit
root-file fallback once the owner uploads only the replacement root files.

Permanent storage admission, independent alerts, all-table archival and immutable
capture-release installation remain unfinished. These changes do not claim that
the database is safe for the rest of the day or that forward capture is commissioned.

Verification: full suite 2,114 passed / 4 unchanged skips / 2 subtests passed;
final focused set 60 passed (including one additional loader test added after
full-suite collection). All 47 existing capture/source tests also passed against
the staged replacements. Replacement-file lint and strict type checks passed.
Self-review addressed missing-state ambiguity, transport-error secrecy and CI
root-file loading. Active task imports were not edited. Equity fingerprint did
not change from the interim workspace; do not set a live expectation from it.

Sources: [PostgreSQL routine vacuuming](https://www.postgresql.org/docs/17/routine-vacuuming.html)
and [Supabase database size](https://supabase.com/docs/guides/platform/database-size).
