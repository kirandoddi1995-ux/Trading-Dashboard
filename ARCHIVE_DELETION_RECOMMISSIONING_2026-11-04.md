# Archive deletion recommissioning — 4 Nov 2026

## Why this change

Supabase is at 413 MB of the free 500 MB and grows about 3 MB a day (361 MB on 17 Oct).
Collectors stop themselves near 476 MB, around 26 Nov. The project must stay on free tiers.
The verified Drive archive already moved and deleted about 690,000 rows (876 batches) up to
16 Oct. On 17 Oct deletion was held unconditionally until custody and restore were proven.
The owner chose to restart the Drive archive (4 Nov), so this change supplies that proof.

## What changes (existing lines, with reasons)

1. `archive_maintenance.require_commissioned_delete()` no longer refuses unconditionally. It
   passes only when `archive_restore_check.prove()` has produced a passing proof in the same
   process within six hours. Reason: replace a permanent hold with evidence. Flags and
   environment variables still cannot unlock it (tests keep that rule).
2. The DELETE also requires each archived row to load back into the live table exactly:
   `to_jsonb(jsonb_populate_record(NULL::table, archived)) = archived`. Reason: a row that would
   not restore exactly is kept, per row, inside the same transaction.
3. CLI: new `restore-check` mode (read-only, every batch) and a `growing` table preset
   (market_quotes, scanner_observations, universe_membership_versions, universe_membership).
4. Workflow: manual modes now include restore-check and delete. The nightly schedule stays a
   no-I/O hold unless the owner sets the NEW repository variable `ARCHIVE_NIGHTLY_DELETE=true`
   (plus the existing ARCHIVE_ENABLED and ARCHIVE_DELETE_ENABLED). Merging changes nothing live.
5. Tests: the hold tests now assert the evidence rule instead of a permanent refusal; algorithm
   tests stub a passing proof. No accuracy, scoring or trading logic is touched.

## The restore proof (archive_restore_check.py)

- Every batch, every night: one paged Drive folder listing; each recorded data and manifest file
  must be present, untrashed, carry its batch identity, and Drive's own SHA-256 must equal the
  recorded checksum (a batch without a Drive checksum is fully re-downloaded that night).
- Deep restore: a rotating seventh of all batches each night (every batch weekly) plus every batch
  from the last 8 days: download, re-hash, read the Parquet, recompute the content-addressed batch
  id from the archived rows, compare the archived manifest file, and load every row into the live
  row type in a read-only transaction. Rows must come back identical, or identical apart from
  columns added later (null). Any failure blocks all deletion that night and fails the job.
- `restore-check` mode does the deep restore for every batch.

## Activation order

1. Review and merge (owner).
2. Run the workflow manually with mode `restore-check`. It must pass for all 876+ batches.
3. Run mode `delete`, table `growing`, max batches 20, once, and check storage.
4. Owner sets `ARCHIVE_NIGHTLY_DELETE=true`. Nightly runs then archive, prove and delete.

## Still open

Drive is the only copy. A second, independent copy (owner's encrypted local preservation,
already designed in ARCHIVE_PRESERVATION_RUNBOOK.md) remains a follow-up, not a blocker for
this proof. App readers that need history older than 14 days read the archive, not Supabase.
