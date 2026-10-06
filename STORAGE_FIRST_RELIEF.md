# First relief — separate from the unfinished permanent-storage package

No runtime upload or new migration is needed for the existing verified NAV archive
workflow. Do not upload the interim storage implementation to obtain this relief.
Owner executes all hosted actions. It protects NAV allocation reuse, not ledger
growth; do not treat it as a permanent solution or guaranteed physical shrink.

At 2026-10-06 08:51:16 IST: cluster494,058,293/current478,784,659 bytes. Increase
since 2026-10-05 22:18:59 UTC:57,344 bytes; since the owner's18:05UTC measurement:
73,728 bytes. Nominal decimal500MB cluster headroom5,941,707 bytes. These are
overnight observations, not a measured market-hours growth rate. Six ledger events
were recorded since18:05UTC, all in the21:00UTC bucket, stored payload total2,218
bytes. Cumulative Postgres insertion counters are not today's rate.
Recheck09:01:53IST:both allocations identical; zero ledger events since08:51:16.
This interval includes preparation, not the09:15market session. A previously
observed6.8MB daily burst exceeds today's5.94MB nominal remaining capacity, so
the quiet interval is not permission to wait for the complete storage package.

NAV read-only eligibility at cutoff2026-10-04:52,113 rows/14,230,681 row bytes.
This is NOT recoverable physical allocation. Existing scheduled archive already
reduced NAV live rows; use fresh preview counts, never the older61,235 estimate.
No user DELETE trigger exists on mf_nav; the existing archive performs latest-value
protection and exact-row/predicate matching in its deletion transaction. App NAV
history readers fetch external provider history, not this SQL NAV table; the SQL
table feeds ingestion and durable statistics. Latest NAV per scheme remains hot.

## Owner sequence

1. Run each block of sql/storage_first_relief_read_only.sql separately in Supabase.
   Keep counts, timestamp, allocation and latest fingerprint privately. These checks
   return no NAV values or secrets. Confirm dashboard usage too; Supabase's database
   report counts all databases in the cluster, not just current_database().
2. In GitHub Actions, select the existing “Verified Drive archive (7-day outcomes,
   14-day other sources)” workflow, Run workflow on main. Mode preview, table mf_nav,
   nav_cutoff2026-10-04, batch_size100, max_batches1. Inspect the exact cutoff and
   eligible count. Stop on mismatch/errors. No deletion occurs in preview.
3. Repeat with mode export, same inputs. Require successful verified Drive readback,
   selected=verified, deleted0. Export retained rows are expected. Do not store market
   data as public GitHub artifacts. Inspect the private Drive object's metadata.
4. If owner approves deletion and ARCHIVE_DELETE_ENABLED is already true, mode delete,
   same inputs, max_batches1: a100-row trial. Require verified/deleted equality and
   retained0; rerun latest fingerprint block and require it unchanged. Stop otherwise.
5. Repeat mode delete with batch_size500/max_batches20, measuring after each run;
   repeat only as needed until eligible_remaining0. Each batch is independently
   export-verified and re-matched; partial progress is safe, not one giant transaction.
   Latest-value fingerprint must remain unchanged (unless legitimate new NAV ingestion
   occurred; reconcile that separately before continuing). Do not shorten another table.
6. Owner runs ordinary VACUUM (ANALYZE) quant_app.mf_nav; outside a transaction.
   Re-run size/fingerprint/eligibility checks. Dead-row cleanup permits NAV reuse;
   physical size may stay unchanged. No VACUUM FULL, REINDEX or table rewrite at this
   headroom. Ledger cannot use free pages belonging to NAV.
7. Measure cluster and per-table sizes before/after today's collection and archive.
   Do not assume the quiet overnight slope continues. If allocation keeps rising
   toward the quota, relief has not protected the ledger: owner must limit optional
   manual scans/other optional SQL writes or accept read-only failure. New derivative
   collection remains held. No evidence deletion or safety-gate relaxation is fallback.

Keep the normal scheduled archive enabled; workflow concurrency serializes these
manual archive runs. Leave the latest NAV cutoff blank for normal scheduling.
No live secret, role password or connection string needs changing for these steps.

## Capture-hour source boundary

The installed task plans refer to forward_nifty_schedule.py in this workspace.
Static import closure intersects the interim manifest at equity_runtime_health.py
and release_verification.py, not production_repository.py. Keep those shared files,
all capture modules, their dependencies and requirements/.venv unchanged09:00–15:40
IST. A new poll starts a new interpreter; mixed multi-file edits can affect later
polls even if an earlier process imported successfully. The new local recovery module
is unreferenced by capture; editing it does not change the capture import graph.

The first sandboxed task listing could not certify the tasks. On Oct 6 an elevated
read-only listing confirmed all three registered actions point at this workspace.
No task was changed. Owner can also verify
Task Scheduler → Task Scheduler Library → each KiranTrading-Forward task → Actions:
program should be this workspace's .venv Python and arguments this workspace's runner.
Do not paste credentials/argument dumps into chat. An immutable owner-installed
capture release directory is the long-term fix, but do not switch running tasks
mid-session. No tasks were changed by the agent.

Sources: [Supabase database-size/read-only documentation](https://supabase.com/docs/guides/platform/database-size).
