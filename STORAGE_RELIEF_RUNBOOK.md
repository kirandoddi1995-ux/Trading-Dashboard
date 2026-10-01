# Reviewed storage relief: operator sequence

Local preparation only. No hosted operation has been executed by the assistant.
Revised relief verification (including delayed lock acquisition and manual batch
count control): full suite 1,051 passed, four skipped, two subtests passed.
SQL tests use disposable PGlite, including exact Parquet restore and read-only
diagnostic execution. They do not simulate real concurrent PostgreSQL sessions;
hosted lock contention and permissions are checked through your staged preview/
first bounded deletion. Changed Python files pass pyflakes. Equity runtime release
fingerprint remains 1c6a663975ed6e163adfb19d2f77bcab692961b71aa427c00b856186ede21d55.
Only outcomes changes to seven UTC calendar days; all other sources retain 14.
The latest outcome per decision is always kept. Outcome readers currently use the
latest snapshot; historical analysis after archival needs an explicit archive reader
or restore, not an assumption that Drive is queried automatically.

## Runway and the large Drive account

The previous 18.17 MB estimate is stored payload made eligible, not guaranteed
physical shrinkage. Do not add six reusable-space days to six headroom days as a
guarantee: allocation, TOAST/index cleanup, other tables and burst timing differ.
The latest reported ~18 MB headroom supersedes the older 33 MB scenario but still
needs a fresh measurement. Seven days is an operational review buffer, not a model
training requirement. A shorter window could be reviewed later with verified
archives and restore access; it is not implemented in this change.

The collector stops fetching at the configured calendar's final session date.
After that, stable responses compare equal (the mature cutoff is normalized), so
unchanged snapshots are not inserted. Provider revisions may still create rows.
Zero completed horizons means we cannot rely on this plateau yet: run check 4 to
see the actual horizon_close and coverage cutoff. Do not guess the final date.
The cumulative-candle redesign should follow this relief, not wait for another
quota emergency. Store immutable candle chunks once, with snapshots referencing
verified content and original observation/provenance times. Never mutate old
research evidence or pretend a later provider response was available earlier.

Your reported 7.44 GB used / 5 TB Drive capacity makes cold-history storage ample.
Keep verified historical data there; keep only live dependencies/recent data in
Supabase. Track daily archived bytes, successful downloads/checksums, batch counts,
failed or partial batches and restore-test success. Parquet uses Zstandard; actual
compression is measured, not inferred from PostgreSQL TOAST size. Transport limits
each Parquet file to 32 MiB. Outcome JSON is materialized before compression, so
small batches also avoid runner memory spikes. More Drive capacity does not fix
OAuth failures, API limits, schedule delays, or an untested restore path.

## Order (target before October 2; do not bypass review to meet the date)

1. **Supabase, read-only:** run blocks 1–6 of
   `sql/storage_relief_checks_read_only.sql` separately. Save results. Compare
   dashboard database usage too. Block 2 includes parent AND TOAST, not just the
   89 parent dead rows. Block 3 may need the SQL-editor owner to see all statistics.
   Long transactions, slots or prepared transactions warrant investigation; do
   not kill sessions or drop slots automatically. Nothing here guarantees every
   dead tuple is immediately removable.
2. **GitHub settings:** temporarily set ARCHIVE_ENABLED=false, so the newly
   deployed schedule cannot delete before your preview. This pauses automatic
   archival only, NOT collectors/trading. Allow an already-running archive to
   finish first. Set ARCHIVE_DELETE_ENABLED=false during review as well.
   Do not leave this staging state overnight unnecessarily.
3. **Review SQL locally:** `sql/drive_archive_storage_relief_draft.sql`. It requires
   the three previous Drive drafts already installed. First also run the index,
   grant and effective-reader checks in sql/storage_relief_access_checks_read_only.sql.
   The migration stops if enabling RLS would exclude an unreviewed reader role;
   do not remove that guard to proceed. It updates the existing
   outcome row guard to seven days, adds canonical source grants/policies/guard,
   and expands the manifest allowlist. It deletes NO source data and preserves
   canonical header rows. One narrow btree index on scanner_observations.universe_snapshot_date
   prevents repeated full-table dependency scans. The transactional index build
   can briefly block writers: run before market scans, with the five-second lock
   timeout intact. An existing wrong/invalid same-name index aborts the migration.
   No research role access is added.
   A narrowly scoped SECURITY DEFINER helper ONLY locks three fixed tables; only
   the archive worker can call it. This prevents dependency changes during final
   deletion without granting the worker header UPDATE/ownership. Locks are taken
   only after remote verification and are subject to connection lock timeouts.
   Existing runtime replacement permissions are not widened or removed.
4. **GitHub upload first:** with both archive switches off and no active or queued
   archive job, upload the reviewed files and wait for green CI before changing
   Supabase. No equity runtime fingerprint change is needed. Do not manually run
   the new archive code against the old schema.
5. **Supabase, reviewed change:** run that ONE new migration as owner. Expect COMMIT.
   It is transactional and rerunnable. On an error, ROLLBACK and investigate;
   do not proceed with a partially edited script. Do not rerun older archive
   drafts afterwards. Run read-only block 7: enabled guards, archive read/delete
   true, forbidden writes/research access false. Existing unexpected policies or
   grants require review rather than a blanket reset.
   Verify current-universe reads under quant_app_runtime, not only postgres;
   archive preview below checks quant_archive_worker. Owner reads bypass RLS.
6. **Actions, manual previews:** run Verified Drive archive with mode=preview,
   table=equity_research.outcomes, then table=universe_membership. Expect cutoff
   UTC today minus 7 / 14 respectively and eligible counts matching SQL taken on
   the same UTC date (allow concurrent new data). Preview does not contact Drive,
   export, write manifests or delete. Investigate surprising counts before continuing.
7. **Actions, export-only smoke test:** use mode=export for each source. This
   verifies ONE batch and records a manifest, deleting nothing. Defaults are 100
   outcome rows, 500 canonical rows, 1,000 for other tables. The new batch_size
   workflow input accepts 1–2,000; use 25–50 for a small first smoke test. Leave it
   blank for per-source defaults. The 32 MiB file limit and all verification remain.
   Download/verify
   that archive and inspect schema/row count. The regression suite exercises exact
   restore into an isolated table; do not restore into live tables just to test.
8. **Actions, approved deletion:** set ARCHIVE_DELETE_ENABLED=true; manually run
   mode=delete with batch_size=25 and max_batches=1 for outcomes, then canonical
   universe. Manual max_batches defaults to 1 and accepts 1–200; increase only
   after reviewing the trial. Scheduled runs retain their 20-batch limit.
   Canonical dependency locks are acquired after verified-row staging, immediately
   before deletion; locked dependency and exact-row checks remain intact.
   Expect selected=verified=
   deleted and retained=0; inspect eligible_remaining. Nonzero remaining means
   the chosen batch budget requires another reviewed run. Stop on any error,
   including lock timeouts, checksum failure, changed rows or retained rows. Never
   bypass guards or delete directly to make the count match.
9. **Supabase, read-only after deletion:** repeat blocks 1, 4, 5, 6. All latest
   outcome IDs must survive (new collector snapshots may advance them); current
   and latest-complete universe membership must survive. Headers stay present.
   Expect fewer eligible rows and matching manifests, NOT necessarily a smaller
   pg_database_size. A failed outcome row deletion rolls back that batch.
10. **Supabase, manual maintenance:** with blockers assessed, run these ordinary
    commands individually, outside BEGIN/COMMIT. No FULL, no REINDEX:

    ```sql
    VACUUM (ANALYZE) equity_research.outcomes;
    ```

    ```sql
    VACUUM (ANALYZE) quant_app.universe_membership;
    ```

    Expect completion; then repeat blocks 1–3. Look for newer last_vacuum timestamps
    and lower dead counts on parent/TOAST. An unchanged database size is normal.
11. **Resume archive schedule:** only after both manual runs are reviewed, set
    ARCHIVE_ENABLED=true (leave ARCHIVE_DELETE_ENABLED=true). Schedule remains
    20:15 UTC; delayed starts are possible. Record size before/after subsequent
    collection and archive cycles for at least three days. Stable allocated bytes
    despite successful new inserts is evidence of reuse, not an exact free-space
    inventory. Check Actions per-table completion, not only manifest timestamps.

## If capacity gets critical and payment/pausing remain ruled out

There is no guaranteed write-safe fallback with finite space and unchecked net
growth. Use the already-deployed verified archive in MANUAL preview/delete mode
for currently eligible rows, then ordinary vacuum. A manual run after UTC midnight
may release the next cutoff day earlier than the delayed nightly schedule. Do not
shorten retention ad hoc, drop primary keys, delete latest evidence or use TRUNCATE.
If nothing safe is eligible and allocation continues rising, one constraint must
change (ingestion volume, capacity, or a reviewed archival policy). We cannot
promise uninterrupted writes otherwise. Do not wait for read-only mode to decide.

## Stop / rollback

Set ARCHIVE_ENABLED=false and ARCHIVE_DELETE_ENABLED=false to stop new archive
deletions; do not disable collectors merely to roll back archival. Keep all verified
Drive files and manifests. New SQL is additive except the seven-day guard and
manifest CHECK replacement. Do not drop policies or reapply old drafts blindly.
Reverting code does not restore archived data. Restore verified original rows under
an owner-reviewed procedure before enabling any reader that requires them. The
seven-day outcome policy can be changed back to 14 by a separate reviewed function
replacement. Research append-only protections stay in place throughout.
