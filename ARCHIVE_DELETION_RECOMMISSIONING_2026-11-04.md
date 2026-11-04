# Archive deletion recommissioning — 4 Nov 2026 (revised after independent review)

## Why this change

Supabase was at about 448 MB of the free 500 MB on 4 Nov and grows about 9.4 MB per trading day.
Collectors stop themselves near 476 MB, around 9 Nov. The project must stay on free tiers.
The verified Drive archive already moved and deleted about 690,000 rows (876 batches) up to
16 Oct. On 17 Oct deletion was held unconditionally until custody and restore were proven.
PR #71 (cb03cd4) replaced the hold with an evidence gate. An independent review (ChatGPT, 4 Nov,
reproduced with synthetic tests) found gaps in that gate. This change closes them. Nightly
deletion was paused (`ARCHIVE_NIGHTLY_DELETE=false`) until this is merged and independently reviewed.

## What each check proves — and what it does not

| Check | Proves | Does not prove |
|---|---|---|
| Presence listing (every batch, every run) | Each recorded data and manifest file exists, is untrashed, carries its batch identity, and Drive's own sha256 for the data file equals the recorded checksum | Anything about files Drive reports no checksum for (handled below) |
| Deep check (rotating 1/7 plus last 8 days; `restore-check` = all) | The bytes download, re-hash, recompute the content-addressed batch id, and every row converts back to the live row type | That rows would insert (next row) |
| **Insert rehearsal** (new) | Every row inserts into an empty temporary copy of the live table (defaults, CHECK and NOT NULL, unique indexes), then rolls back | Foreign keys, triggers, row-level security, or a restore into a real disposable database |
| **Cross-batch key check** (new, full mode only) | No key is archived twice with different content | Anything nightly (it needs every batch) |
| Custody (new, per batch, inside the delete transaction) | This batch's data and manifest files are untrashed, carry their identity, and still match their exact bytes, checked immediately before the DELETE | An immutable lease: Drive can change after the check; the final recheck then fails the job loudly |

"Converts back" is not "restores". A full restore drill into a disposable database remains open.
Drive is still the only copy; a second independent copy is the real answer to that risk.

## What changed from PR #71

1. `recheck_presence(repo, drive, proof)` now compares file bytes, not only identity:
   data files Drive gives no checksum for are downloaded and held to the database checksum;
   manifest files are held to the checksum pinned at proof time (or, for batches recorded after
   the proof, to the exact bytes their record implies; downloaded when Drive reports no checksum).
2. A batch uploaded in the same run is confirmed again (`confirm_custody`, includes Drive's
   trashed flag, because trashed files still download) inside the deleting transaction, after the
   locks and right before the DELETE. If it fails, nothing is recorded or deleted. `acknowledge`
   refuses to delete without this check.
3. `rehearse_insert` and the cross-batch key check join the deep check.
4. A proof carries a context (database and folder fingerprint) and `run_batch` requires it to match.
5. `manifest_record()` is the single definition of the manifest file.

## Still open (not fixed here)

- Rotation uses the calendar day, not each batch's last successful deep check, so a run of failed
  nights delays a batch's turn. The nightly proof reports `deep_batches`; a periodic full
  `restore-check` run covers it. A scheduled weekly full check is a follow-up.
- Monitoring beyond GitHub's failed-run emails (missing runs, unexpected deletion counts).
- Second independent copy of the archive; full disposable-database restore drill.
- A failed job can still contain deletions committed earlier in the same run.

## Activation order

1. Independent review, then owner merge.
2. Run the workflow manually with mode `restore-check` (all batches). It must pass, including the
   new insert rehearsal and the cross-batch key check on every batch. A real finding here is a
   finding about the archive, not a reason to loosen the check.
3. One supervised `delete` run (table `growing`, small max batches).
4. Only then set `ARCHIVE_NIGHTLY_DELETE=true` again.
