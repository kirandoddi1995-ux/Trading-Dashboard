# Rolling window — 7 Nov 2026

Goal: keep recent rows in Supabase and move older rows to the Drive archive, pruning them only after
verified custody. Every step stays owner-triggered (`workflow_dispatch`); nightly deletion stays OFF
(`ARCHIVE_NIGHTLY_DELETE=false`); nothing deletes automatically.

## Measured read-only on 7 Nov (Supabase `quant_app`)
- `sum(pg_database_size)` = 462,592,821 bytes; collectors pause at 476,000,000 (13.4 MB left).
- Catalog: 956 batches, last recorded 4 Nov 14:29 UTC (a supervised delete of 80 batches that day).
  Live rows older than 14 days: scanner 53,870, quotes 66,126, membership versions 28,376,
  canonical membership 35,696 (eligible once the scanner rows that reference those dates are pruned).
- Heap bytes in rows older than 14 days: scanner 33.3 MB, versions 17.2 MB, canonical 19.7 MB, quotes
  8.7 MB (about 110 MB including indexes).
- Ledger: 10,047 events, 86 MB (mostly TOAST). A `DECISION_BATCH_EVALUATED` event reaches 2.6 MB of
  JSON (~0.6 MB stored); about 1.3 MB stored per trading day.
- `market_daily_volumes`: about 2,730 rows (~0.35 MB) per trading day.

## What changed
1. **Ledger in the Drive export** (`evidence_ledger_events`, append-only).
   - Added to `drive_archive.SPECS` and to the new `APPEND_ONLY` set.
   - The archive job refuses to delete it: `delete` and `prune-preserved` on the ledger fail with
     `APPEND_ONLY_NEVER_DELETED`, `acknowledge(delete=True)` refuses a ledger batch, and prune
     candidates never include ledger batches. The archive role must hold no write privilege on it.
   - Pages hold at most one CLOSED UTC day (cutoff: before yesterday 00:00 UTC) and at most 6 MB of
     stored payload, so a page is the same every run and an event is not archived twice; a repeated
     export passes over pages already in the catalog.
   - Needs the owner to run `sql/drive_archive_ledger_export_draft.sql` once (read grant plus the
     catalog's table list). Without it, only a ledger export fails (`ARCHIVE_LEDGER_SELECT_GRANT_MISSING`).
2. **Incremental proof** (`--proven-after T0`, workflow input `proven_after`).
   - Presence, Drive checksum and exact manifest bytes for EVERY batch, as before.
   - Deep restore, insert rehearsal and the cross-batch key check only for batches recorded after T0
     (plus any batch Drive reports no checksum for).
   - The proof carries the ids it deep-checked. `prune-preserved` takes candidates only from batches
     recorded after T0 and refuses any candidate outside those ids (`BATCH_NOT_DEEP_PROVEN`).
   - T0 = the previous cycle's `preserved_before`. First cycle: `2026-11-05T00:00:00+00:00` (restore-check
     #96 deep-checked all 956 batches; none were recorded after 4 Nov 14:29 UTC).
3. **Time-bounded prune** (`--max-minutes`, workflow input `max_minutes`, default 150, at most 170).
   No new batch starts after the bound; the run ends with the usual presence recheck and reports
   `eligible_unpruned` per table. Repeat the run to continue.
4. **Generation printed by export**: an `ARCHIVE_GENERATION` line gives `preserved_before`,
   `preserved_batches`, `preserved_sha256` for the copy check and the prune.

Gap (a), rows newer than the archive: no code needed. `export` (table `growing`) already pages through
every eligible row and skips batches already in the catalog.

## Decisions
- **Window: 14 calendar days (about 10 trading days), unchanged.** Reasons: it is the reviewed constant
  every archive predicate and test already uses; with a weekly owner cycle the oldest hot row is at most
  about 21 days old, which fits the freed space (~110 MB) against ~5 MB per trading day of growth in the
  four reusable tables; and two weeks leaves time to notice a collector or scan problem while the rows
  are still in Supabase. Stage-2 passes and prediction-target parents are never archived regardless.
  A 7-day window would free ~45 MB more once, but does not change the limit described below.
- **`market_daily_volumes`: not pruned yet.** It grows ~0.35 MB per trading day, is the compact volume
  history that replaced raw quotes (the 20-day volume reader and the quote-deletion coverage check
  depend on it), and pruning it needs a DELETE grant and its own predicate. Revisit with the next step below.
- **Ledger never deleted** (owner rule). It is exported only.

## Limit found, and the step that closes it
DELETE frees space for reuse inside the same table only (PostgreSQL VACUUM docs). After a prune the four
big tables reuse their freed space for roughly 3-4 weeks, but the ledger (~1.3 MB per trading day), daily
volumes (~0.35 MB) and small tables keep raising `pg_database_size` by an estimated ~1.7 MB per trading
day. A prune alone would move the collector stop by only about 1-2 weeks.

Closing step (owner, Supabase SQL editor, outside the 10:07 and 14:37 IST runs): after a prune, run
`VACUUM FULL` on each pruned table, one statement at a time, smallest first. It writes a compact copy and
returns the freed space to the operating system, so `pg_database_size` falls by roughly the pruned
bytes (~110 MB in the first cycle, an estimate). It locks that one table while it runs (seconds to about
a minute at these sizes) and briefly needs extra space equal to the table's live size.
- Why this is safe here (Supabase docs, Database size): read-only mode is triggered by DISK usage
  reaching 95% of the 2 GB free disk, not by the 500 MB quota. The 500 MB quota is billed on the
  average daily database size. A peak of tens of MB for a minute is far below the disk limit and barely
  moves a daily average. The 476 MB collector pause is this project's own guard, read at the start of
  each run, so `VACUUM FULL` must not overlap a run.
- With it, each weekly cycle (export, copy check, prune, compact) keeps the hot tables at about the
  14-day window. Only the ledger keeps growing (~6-7 MB a week), so the runway is months, not days.
  Cold-sealing old ledger prefixes (`ledger_archive_repository.py`; this deletes ledger rows and needs
  the owner's explicit decision) or date partitions are the later fix for that.

## Tests
`tests/test_archive_rolling_window.py` (PGlite harness and synthetic Drive): ledger export by closed day
and byte budget, never deleted, grants, restore proof of ledger batches, incremental proof scope,
candidate refusal, deadline, input refusals, the workflow launcher, and that
`archive_recovery_review.SPECS` still mirrors every deletable table. Eleven deliberate mutations of the
new code were each caught. One pinned test changed: `test_only_outcomes_get_seven_days` now skips the
ledger, which has no deletion cutoff at all (`cutoff_for` and `predicate` still refuse it; exports use
`export_cutoff` / `export_condition`).
