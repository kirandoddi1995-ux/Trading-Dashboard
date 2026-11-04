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
| Custody (new, per batch) | Before any lock: this batch's data and manifest files are untrashed, carry their identity and match their exact bytes. Inside the delete transaction, right before the DELETE: identity and trashed flag again (quick form, hard 10 s deadline, 30 s idle-in-transaction bound) | An immutable lease: Drive can change after the check, and one batch is one copy (two files, not two copies); the final recheck then fails the job loudly but cannot restore lost bytes |

"Converts back" is not "restores". A full restore drill into a disposable database remains open.
Drive is still the only copy; a second independent copy is the real answer to that risk.

## What changed from PR #71

1. `recheck_presence(repo, drive, proof)` now compares file bytes, not only identity: data files
   Drive gives no checksum for are downloaded and held to the database checksum. `prove()` now reads
   every manifest file and matches it to its database record before pinning its checksum, so a
   corrupt, unsampled manifest cannot become the trusted baseline (second review). Batches recorded
   after the proof are held to the exact bytes their record implies.
2. Custody of a batch uploaded in the run is confirmed twice: full bytes before any lock, and the
   quick identity/trashed form inside the deleting transaction. `acknowledge` accepts only a
   `CustodyCheck` object bound to that batch, database and folder, and re-checks the proof context
   itself, so a direct caller cannot pass a lambda or a proof for another database (second review).
3. `rehearse_insert` forces deferred constraints immediate before it rolls back (second review) and
   joins the deep check, with the cross-batch key check (full mode only).
4. A proof carries a context (database and folder fingerprint).
5. `manifest_record()` is the single definition of the manifest file.

## Still open (not fixed here; nightly deletion stays paused)

The second independent review (ChatGPT, 4 Nov, evening) recommends keeping nightly deletion paused
until an independently readback-verified second copy exists. The findings above close its four code
items; these remain:

- **No second independent copy.** Drive is the only copy; an alert cannot recreate lost bytes.
- Nightly mode cannot see cross-batch conflicts that full mode finds; a clean full check does not
  qualify later batches (needs incremental conflict qualification and a version policy).
- The insert rehearsal runs temporary DDL on the production connection and does not exercise
  foreign keys, triggers, row-level security, identity columns, or cold-reader parity.
- Lock-duration behaviour with concurrent writers is not tested on native PostgreSQL (PGlite only).

- Rotation uses the calendar day, not each batch's last successful deep check, so a run of failed
  nights delays a batch's turn. The nightly proof reports `deep_batches`; a periodic full
  `restore-check` run covers it. A scheduled weekly full check is a follow-up.
- Monitoring beyond GitHub's failed-run emails (missing runs, unexpected deletion counts).
- Second independent copy of the archive; full disposable-database restore drill.
- A failed job can still contain deletions committed earlier in the same run.
- Successful-check age tracking per batch and independently delivered alerts.

## Activation order

1. Independent review, then owner merge.
2. Run the workflow manually with mode `restore-check` (all batches). It must pass, including the
   new insert rehearsal and the cross-batch key check on every batch. A real finding here is a
   finding about the archive, not a reason to loosen the check.
3. One supervised `delete` run (table `growing`, small max batches).
4. Only then, and only with an independent copy in place, set `ARCHIVE_NIGHTLY_DELETE=true` again.
