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
| Custody (new, per batch) | Before any lock (building the `CustodyCheck`): this batch's data and manifest files are untrashed, carry their identity, match their exact bytes, and their Drive head revision ids are pinned. Inside the delete transaction, right before the DELETE (quick form; Drive calls have 3 s connect / 7 s read socket timeouts, which are not a hard total deadline because google-auth checks `max_allowed_time` only after a request returns; the hard bounds are the server-side 30 s idle-in-transaction and 5 s lock timeouts, which abort the transaction): identity, trashed flag, revision ids unchanged, and Drive's sha256 wherever Drive reports one. A missing revision id or missing pins fail closed. Lock waits bounded by `lock_timeout` 5 s (applies to the advisory lock, `FOR UPDATE`, dependency locks and the DELETE's row locks); idle-in-transaction bounded at 30 s | An immutable lease: Drive can change after the check, and one batch is one copy (two files, not two copies); the final recheck then fails the job loudly but cannot restore lost bytes. That real Drive returns `headRevisionId` for our files is not yet observed: an `export` run now logs `custody_probe` per batch to show it without deleting |

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

### Since 8401eaa (own adversarial review, 5 Nov)

6. The under-lock quick check ignored file contents: a file replaced after the full byte check
   passed. It now compares pinned Drive revision ids (and Drive's sha256 where reported). Revision
   ids, not sha256, are the primary signal, because Drive may omit sha256 (rclone Drive docs) and a
   sha256-only rule could refuse every same-run delete before the storage deadline.
7. Correction (5 Nov, own review): lock waits were already bounded at 5 s by the connection option
   `lock_timeout=5000`; an earlier `SET LOCAL lock_timeout = '15s'` wrongly lengthened that bound.
   It is now `'5s'`, set explicitly before the advisory lock;
   a SQL-harness test shows it in force inside the deleting transaction and gone after it.
8. `CustodyCheck` can only be built through the full byte check (its constructor runs it).
9. `export` mode logs a non-deleting `custody_probe` for each batch, so real Drive behaviour is
   observed before any delete depends on it.
10. Comparison with published practice: see project note
    `research_2026-11-05_backup_verification_before_delete.md` (AWS REL09-BP04, PostgreSQL
    retention workflow, Kestra verified archive, GitLab 2017 postmortem, Drive API docs).

### Round 3 independent review of 8401eaa (ChatGPT, 5 Nov) — blockers closed here

Each was reproduced with a failing test first (tests/test_archive_custody_hardening.py, PGlite):

11. **Rows not bound to the verified batch.** Custody for an archive of row Z let `acknowledge()`
    delete row A. Now `acknowledge()` snapshots the texts, recomputes `batch_identity` and the row
    count from that snapshot, requires them to equal the manifest, and deletes only that snapshot
    (`ROWS_NOT_THE_VERIFIED_BATCH`).
12. **Receiver context.** A genuine check for database A authorised deletion through repository B.
    Now the context is derived from the receiving repository and the check's own Drive transport and
    must equal both the check's context and the proof's.
13. **Partial manifest binding.** Substituted Drive file ids passed. Now the check is bound to all six
    fields of the upload record, and only a check that completed the full byte check (pinned
    revisions) is accepted; a constructor-bypassed object is refused.
14. **Final check missed content changes** — already closed by items 6-8 above (found independently
    by own review); now also reproduced through real `run_batch()` with Drive reporting no checksum.
15. **Ordering test did not call `run_batch()`.** Renamed; a real ordering test now shows the full
    check (both files read) happens before `acknowledge()` and no download happens under locks.
16. **Wording.** The 10 s Drive limit is not a hard deadline (google-auth checks `max_allowed_time`
    after a request returns); the hard bounds are the server-side timeouts. The NAV "lossless restore"
    test runs on PGlite, not a native PostgreSQL server, and covers one synthetic path only.
17. **Copy verifier.** A count could certify an empty folder or the wrong set of batches; malformed
    manifests were accepted. `verify_local_archive_copy.py` now qualifies a copy only against a frozen
    inventory (exact batch ids, counts, hashes) whose sha256 is supplied separately (the anchor); each
    manifest must be the exact expected bytes; files outside the inventory fail; a path inside a known
    cloud-sync folder is refused. `--self-check-only` reports `SELF_CONSISTENT_ONLY` with
    `deletion_authority: false`. Physical independence (separate disk) remains the owner's evidence.
    A fingerprint mode (`--expect-batches N --expect-set-sha256 HASH`) avoids moving an inventory
    file: N and HASH come from `INVENTORY_SET_SQL`, run read-only on the database at copy time; a
    PGlite test shows that SQL and the verifier's rebuild agree byte for byte.

### CodeAnt review of PR #72 (e5f402a) — each reproduced first

18. `prove()` pinned a manifest that matched identity fields only; altered `postgres_types`,
    `numeric_encoding` or extra fields became the baseline. Now the manifest must be the exact bytes
    its database record implies. Not yet observed on real Drive: if any older manifest differs in
    bytes, `restore-check` now fails closed for it, and that is investigated, not loosened.
19. The custody check ignored folder membership; a file moved out of the archive folder passed.
    Both forms now require the archive folder in the file's `parents`.
20. The copy verifier followed links; links to files outside the copy counted. Links, junctions and
    anything resolving outside the folder are now failures. Files over the archive size limit are
    refused before being read.
21. Not changed: delete mode does not run the cross-batch key check (it needs every batch read,
    about an hour). It stays an activation gate: a full `restore-check` must pass before any
    supervised delete, and nightly deletion stays off.

### Round 4 independent review of 2e96336 (ChatGPT, 5 Nov) and follow-ups

Verdict: safe to keep merged as inactive code (PR #72 merged by owner as 92e156a, zero file
difference from the reviewed head); nightly deletion stays OFF. Its independent checker caught all
ten targeted mutations. Windows full run: 8,045 passed, 22 skipped, 2 failed — both failures were
fixture symlink creation refused by Windows (WinError 1314) before the verifier ran. Hosted Linux:
7,706 passed. Follow-ups closed on branch archive-followups-20261105:

22. The custody full check now decodes the downloaded data bytes against the claimed batch id, table
    and row count (`archived_rows`), so a record naming batch A but pointing at batch B's bytes is
    refused by the check itself, not only by the production call order. Reproduced first.
23. Link tests now require `LINK_NOT_ALLOWED` explicitly (a verifier that silently ignored links
    would also mismatch), skip only when the OS refuses to create the link (WinError 1314), and a
    Windows-only directory-junction test (no privilege needed) is added.

Operational order agreed for any prune (owner decides each step): exact-byte capacity reading;
non-deleting export with `custody_probe: ok` for every candidate; freeze the catalog; full
`restore-check`; fresh fingerprint; verify the independent disk copy against that same generation;
only then a supervised prune of exactly those preserved batches. The current delete mode cannot
restrict itself to a verified set — that gate must exist before any prune.

### Preserved-generation prune (5 Nov) — the deterministic gate before any prune

The round-4 review found that `delete` mode cannot restrict itself to batches verified on an
independent copy (it uploads and deletes new batches in the same run). Two additions close that:

- **Bulk export** (`--mode export`, any table or `growing`, up to `--max-batches` per table): pages
  forward by each table's order key, uploads and records batches, deletes nothing, and logs a
  `custody_probe` per batch. A page whose content-addressed batch is already in the catalog is
  passed over without uploading and does not count against the bound, so a repeated run continues
  where the previous one stopped (CodeAnt review of PR #74). `prune-preserved` honours a one-time
  `--nav-cutoff` for NAV batches, as delete mode does.
- **`--mode prune-preserved`** with `--preserved-before T --preserved-batches N --preserved-sha256 H`:
  (1) runs the full proof (every batch, insert rehearsal, cross-batch key check); (2) refuses unless
  the catalog batches recorded at or before T have exactly count N and fingerprint H — the pair the
  owner verified on the independent copy with `verify_local_archive_copy.py`; (3) prunes only
  exported, not-yet-pruned batches of that generation; (4) rebuilds each batch's rows from the
  archive file itself, re-proves custody, and runs the normal deleting transaction; (5) stops the
  whole run on any retained (changed) row. T is always taken from the database clock at full
  precision. Manual dispatch only: the nightly schedule cannot reach it (tested). Job limit 180 min.

Owner sequence (each step is the owner's decision):
1. `restore-check` (read-only) passes.
2. `export`, table `growing`, max batches 100; repeat until each table exports fewer than the
   bound; every batch `custody_probe: ok`.
3. Take T, N, H read-only from the database (`SELECT clock_timestamp()::text`, then
   `GENERATION_SQL` at T).
4. Download the Drive folder again to the external disk; verify it with
   `--expect-batches N --expect-set-sha256 H` → `COPY_MATCHES_INVENTORY`.
5. `prune-preserved` with T, N, H (max batches up to 200 per run; repeat until nothing is pruned).

Limits: DELETE frees space for reuse inside the same table after vacuum; it does not lower the
collectors' size reading. Nightly deletion stays OFF.

### Round 5 (ChatGPT, 5 Nov evening) — storage bridge, applied unchanged and re-checked

- **Generation race closed.** `verified_at` is insertion time, not commit time: a batch inserted
  before T but committed after the fingerprint check could have entered the candidate list without
  being on the verified copy. Count, fingerprint and candidates are now read in ONE statement
  (`preserved_candidates`). Candidates honour the selected `--table`.
- **Short delete rolls back.** If fewer rows can be deleted than were preserved, the batch's
  transaction rolls back (rows kept, batch stays pending) instead of being marked complete.
- **Compact future quote writes.** New `market_quotes` rows store a retention marker instead of the
  raw provider payload (no code reads it; typed fields and the daily-volume trigger are unchanged).
  Owner decision: the original payload of future rows is not kept.
- Universe de-duplication deferred: dropping member rows would leave dated headers claiming members
  that readers cannot resolve.
- Re-checked here: all six files byte-identical to the reviewer's hashes; four deliberate mutations
  (no rollback, no table scope, no generation check, raw payload kept) each caught.
- Prune timing: run #96 took 114 min for the full proof alone. The first supervised prune is one
  batch (`max_batches=1`) on one table; larger runs need measured per-batch timing first.

## Still open (not fixed here; nightly deletion stays paused)

- **Per-generation preservation.** A one-time disk copy does not protect batches uploaded later.
  Nightly deletion must not return until each new batch is independently preserved and verified
  before its source rows are pruned (review round 3).
- **Storage deadline.** If prerequisites are not ready before collectors reach their stop, reduce
  growth through the existing collector policy rather than weakening preservation checks (owner's
  decision).

- **No real restore drill** into a disposable database with application queries (AWS REL09-BP04).
  A free GitHub Actions job with a PostgreSQL service container can do it.
- **No cooling-off period**: a batch is deleted in the run that uploads it. Published workflows wait,
  then re-verify, before deleting.

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
