# Recovery contracts: facts before restoration

Inactive additive package; exact public base `eb58dc2bdc29fe32ef2bc04df9f85ab381ed8d7f`.
This supersedes earlier *status claims*, not historical manifests or evidence.
No private files, keys, rows, hosted resources, services or installed capture were
read or changed by this build. No workflow, schedule or deletion is enabled.

## Owner measurements FIRST — no restore or signing command yet

These facts are needed before designing a real restore runner, not before
reviewing this inactive source package. Normal non-administrator PowerShell;
one block at a time. Never put credentials, dump contents, private paths or
encryption material into chat or public Git. No new installation is needed.

1. In Supabase Dashboard -> Database -> Backups, **view only**. Record privately:
   whether any backup is listed, logical/physical/unknown, available timestamps,
   displayed retention, size if shown, and whether download/restore is offered.
   Report `UNKNOWN` where the page gives no fact. Do NOT click Restore, enable
   PITR, buy anything, download a backup or create a token. A green backup listing
   is not proof of restoration. Free-plan recoverability must not be assumed.
2. In the dashboard SQL editor, run the reviewed file
   `sql/recovery_backup_facts_read_only.sql` once. It is a short read-only
   transaction, catalog metadata only, ending in rollback. It does not inspect
   2025/2026 business data. Stop on an error; do not change grants or retry to
   obtain missing visibility. If the editor leaves a failed transaction open,
   issue only `ROLLBACK;`. Preserve the result privately. Share only measurement
   time, version number, database/cluster byte counts (or explicit UNKNOWN), eight fixed relation
   sizes, PK columns and extension names/versions. Do not infer backup existence
   from this result. It does not capture a database snapshot or original DDL.
3. Read local filesystem capacity. This reports bytes, not volume labels or IDs,
   does not search files, and does not establish the drive's physical identity:

   ```powershell
   $ErrorActionPreference = 'Stop'
   $capacityFacts = @(Get-Volume -DriveLetter C,D -ErrorAction Stop |
     Select-Object @{Name='drive';Expression={[string]$_.DriveLetter}},
       @{Name='filesystem';Expression={[string]$_.FileSystemType}},
       @{Name='size_bytes';Expression={[uint64]$_.Size}},
       @{Name='free_bytes';Expression={[uint64]$_.SizeRemaining}})
   [pscustomobject]@{measured_at=[DateTimeOffset]::Now.ToString('o');
     volumes=$capacityFacts;writes=0;identity_verified=$false} |
     ConvertTo-Json -Depth 4 -Compress
   ```

   If D: is disconnected, report that; do not substitute a similarly named path
   or reconnect it just to satisfy a script. Inspect Docker Desktop's Resources
   page read-only for displayed disk-image limit/usage/location drive (omit the
   private path). A configured limit is NOT currently allocatable free bytes.
   If no actual VM/filesystem free-space figure is shown, report `UNKNOWN`.
   Do not resize, prune, move the disk image or launch a measurement container.
4. Without opening a dump or searching private directories, report any backup
   you already know exists: type/creation time/size/last successful restore, or
   `NOT_ESTABLISHED`. The recovery ZIP, its .7z wrapper, and B sidecars are not
   full PostgreSQL backups. Keep private filenames and hashes privately recorded.

The dashboard's daily database/disk widgets can lag. SQL allocation, physical
free disk, Docker VM capacity and D: free space are different measurements. The
500,000,000-byte planning limit is not a restore-space budget. No guessed 2x
multiplier or ciphertext compression ratio will admit a restore.

## Evidence ledger at this handoff

- **Public source verified:** fresh public clone HEAD equals the exact base
  above. Existing A/B code remains unchanged. New modules are pure byte/digest
  APIs; neither is a filesystem collector or a production admission gate.
- **Owner-reported:** A generation 1 signature verified against privately kept
  anchors; hosted Linux and local Windows B checks passed; contained B private
  check accepted eight batches/723 rows under kernel-readonly-v2; encrypted
  copies exist on PC, same-account Drive and a physical external disk; key backup
  also on that disk. No private anchors are copied into this package.
- **Not independently verified here:** those real private runs, their sidecars,
  current disk/DB facts, independent custody and any logical/typed/physical
  restore. A signature authenticates the statement, not its historical truth.
- **Unchanged denominator:** original generic verifier 868/876; separate B
  structural result 8 batches/723 rows. Do not relabel this as original verifier
  876/876, authenticated deletion receipts or a same-cut database backup.

## Chosen order and what this package actually delivers

1. Preserve all originals and current encrypted copies; retain the external
   offline copy and separate unlock record. Keep deletion and scheduled archive
   holds unchanged. No duplicate cleanup, key rotation or evidence re-encryption.
2. Collect the metadata facts above. In parallel review the additive contracts.
3. Build a destination-bound **measurement adapter**, then an authenticated
   evidence collection. `archive_recovery_binding.py` now defines a strict
   purpose/role schema for exact catalog, ZIP, ciphertext, B input-binding,
   B container-intent and B result references. It verifies both externally
   anchored parent and signed child and requires the exact predecessor and
   remeasured artifacts. It returns **SIGNED_REFERENCES_VERIFIED_NOT_CUSTODY**.
   It neither signs nor measures files. Its digest references do not validate
   B report semantics/image execution, Drive IDs or old receipt provenance.
4. Do not commission a new signing generation from this package. The next adapter
   must re-open real destinations with native stable-handle volume/file identity
   and no links; measure sidecars using bounded exact bytes, validate their B
   schema, image/profile, input-binding digest and A parent anchors, and keep an
   independently retained new head. It must bind re-extraction/hash comparison
   of all seven encrypted members and explicit physical custody observations.
   It must preserve generation 1 and the consumed B attempt, not overwrite or
   rerun either. The existing B private launcher expects an inventory-shaped A
   observation: a new binding head is NOT a drop-in replacement. Update that
   consumer contract explicitly before any future reuse, without a head reset.
5. Review original PostgreSQL schema, true PKs, roles WITHOUT passwords, grants,
   RLS, sequences, functions/triggers and extensions against historical producer
   migrations. `SPECS` is a row codec, not original DDL. The measured current PKs
   are not automatically the historical schema. A new live dump taken now cannot
   recover rows already deleted unless the archive recovery is independently
   integrated. A date range and an A signature generation are NOT an MVCC cut.
6. Build an isolated PostgreSQL rehearsal AFTER the facts: a digest-pinned
   compatible PG17 image, fresh disposable Docker-managed storage, **network
   none, no published ports, no host PGDATA or Docker socket mounted**, no real
   credentials, and no cron/HTTP dispatch or restored jobs. Invoke only internal
   tools through the future bounded runner. Pre/post native containment and
   autonomous timeout must be proven with synthetic data before private input.
   Do not use or start the existing non-loopback host PostgreSQL service; leave
   its manual-start setting unchanged. No host ACL/firewall/service edit here.
   Docker shares the host kernel/VM and is not an absolute security boundary.
7. First restore all valid archive versions to append-only provenance staging;
   keep `(table,batch,row ordinal,schema hash,key hash,full typed-row hash)` for
   every occurrence. Only exact canonical full-row equality under the same key
   and schema may be classified as duplicate. **No latest-file/receipt/date
   wins, ON CONFLICT overwrite or arbitrary timestamp tie-break.** Differing
   versions stay quarantined for an explicit source-specific policy.
   `archive_restore_policy.py` enforces digest-review counts, denominator,
   repeated source-position rejection, one schema per table and bounded memory;
   it never writes, discards rows, selects a winner or grants restoration.
8. Same-generation full DB restore remains a separate proof: one documented
   consistent live cut + complete schema/dependencies and snapshot-bound archive
   membership/version policy. A union of 90 days of legacy files is a recovery
   collection, **not** a same-time full DB. Some historical ambiguity may be
   irrecoverable; label it rather than inventing the missing version evidence.
9. Prove exact cold-reader/live-reader agreement, independent restore and alert
   delivery before source-specific retention. Retention and deletion are LAST.

The six legacy keys in source (must be checked against DDL) are NAV
`(scheme_code,nav_date)`, membership `(snapshot_date,instrument_key)`, versions
`(snapshot_id,instrument_key)`, quotes `(observed_at,instrument_key)`, scanner
`observation_id`, outcomes `snapshot_id`. Mutable values under these keys make
last-archive-wins unsafe. Full-row canonicalization must preserve NUMERIC,
timestamp timezone/precision, JSON and null semantics; do not hash float-rounded
or text-rendered approximations. Hash equality is not itself typed-row validity.

`review_space` accepts explicit reviewed NEW-allocation budgets per filesystem:
input copies + provenance staging + restored heap + indexes + WAL/temp + reserve.
It rejects unknown/nonpositive core budgets and overflow, reports fit only, and
always leaves restore authority false. Existing allocations must not be counted
twice. Actual peak/time/disk-full abort behavior still needs native rehearsal.

## Custody versus an observation signature

No new production key, key-discovery mechanism or signing mode is needed merely
to authenticate exact reference bytes: A's existing Ed25519 preservation envelope
and predecessor verification suffice with the new explicit purpose. This is NOT
permission to promote observation signatures into physical-custody attestations.
An adapter must independently bind measured destinations and extraction results;
operational custody acceptance also needs a separately retained trust head,
verified decrypt/restore, availability/retention checks and clear failure domains.
Never use the .7z passphrase as a signing key or reuse production ledger keys.
Drive under the same account is an additional remote copy, not protection from
account loss/deletion. External disk helps with account/network loss only while
disconnected and physically protected. Keeping both archive and encrypted key
backup there correlates media loss; a separate paper unlock record does not
restore a lost key file. Do not claim three independent custodians.

## Reviewable upload: ONE group, ten ADDITIONS, no replacements

Each source below is relative to the working source root; destination is the
identical relative path in the clean public clone. No installed capsule file is
in this list. Exact source -> destination:

```text
archive_recovery_binding.py -> archive_recovery_binding.py
archive_restore_policy.py -> archive_restore_policy.py
sql/recovery_backup_facts_read_only.sql -> sql/recovery_backup_facts_read_only.sql
tests/test_archive_recovery_binding.py -> tests/test_archive_recovery_binding.py
tests/test_archive_restore_policy.py -> tests/test_archive_restore_policy.py
tests/test_recovery_backup_facts_sql.py -> tests/test_recovery_backup_facts_sql.py
recovery_contract_upload_check.py -> recovery_contract_upload_check.py
tests/test_recovery_contract_upload_check.py -> tests/test_recovery_contract_upload_check.py
RECOVERY_CONTRACT_HANDOFF_2026-10-20.md -> RECOVERY_CONTRACT_HANDOFF_2026-10-20.md
RECOVERY_CONTRACT_UPLOAD.json -> RECOVERY_CONTRACT_UPLOAD.json
```

1. Fresh clean clone, `core.autocrlf=false`, exact base above. If main changed,
   STOP for reconciliation: no pin edits. Create one branch. Check repo-local
   commit identity presence, without printing it: `git var GIT_AUTHOR_IDENT`
   redirected to null; configure an owner-approved repo-local identity only if
   needed. Copy and stage ONLY the ten paths, including the SQL and tests folders.
2. In the clone, use the already verified explicit 3.13.9 interpreter. Set only
   task-specific variables; no bare `py` and no secret/environment dump:

   ```powershell
   $ErrorActionPreference = 'Stop'
   $researchPython = 'C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
   & $researchPython -I -B -c "import sys; assert sys.version_info[:3] == (3,13,9)"
   if ($LASTEXITCODE -ne 0) { throw 'REVIEWED_PYTHON_REQUIRED' }
   & $researchPython -B recovery_contract_upload_check.py --base eb58dc2bdc29fe32ef2bc04df9f85ab381ed8d7f
   if ($LASTEXITCODE -ne 0) { throw 'PACKAGE_CHECK_BLOCKED' }
   ```

3. Focused test line (synthetic only, same clone):

   ```powershell
   $ErrorActionPreference = 'Stop'
   $recoveryTestScratch = Join-Path ([IO.Path]::GetTempPath()) ('recovery-contract-tests-' + [guid]::NewGuid().ToString('N'))
   & $researchPython -B -m pytest -q -p no:cacheprovider --basetemp "$recoveryTestScratch" tests/test_archive_recovery_binding.py tests/test_archive_restore_policy.py tests/test_recovery_backup_facts_sql.py tests/test_recovery_contract_upload_check.py tests/test_archive_preservation_witness.py tests/test_archive_preservation_inventory.py tests/test_outcomes_private_worker.py tests/test_outcomes_private_container.py
   if ($LASTEXITCODE -ne 0) { throw 'FOCUSED_TESTS_FAILED' }
   ```

   ```powershell
   $ErrorActionPreference = 'Stop'
   & $researchPython -B -m pyflakes archive_recovery_binding.py archive_restore_policy.py recovery_contract_upload_check.py tests/test_archive_recovery_binding.py tests/test_archive_restore_policy.py tests/test_recovery_backup_facts_sql.py tests/test_recovery_contract_upload_check.py
   if ($LASTEXITCODE -ne 0) { throw 'LINT_FAILED' }
   $recoveryTypeScratch = Join-Path ([IO.Path]::GetTempPath()) ('recovery-contract-mypy-' + [guid]::NewGuid().ToString('N'))
   & $researchPython -B -m mypy --strict --cache-dir "$recoveryTypeScratch" archive_recovery_binding.py archive_restore_policy.py recovery_contract_upload_check.py
   if ($LASTEXITCODE -ne 0) { throw 'STRICT_TYPES_FAILED' }
   git diff --cached --check
   if ($LASTEXITCODE -ne 0) { throw 'STAGED_DIFF_CHECK_FAILED' }
   & $researchPython -B recovery_contract_upload_check.py --base eb58dc2bdc29fe32ef2bc04df9f85ab381ed8d7f
   if ($LASTEXITCODE -ne 0) { throw 'FINAL_PACKAGE_CHECK_BLOCKED' }
   ```

   Keep each block separate. Do not reuse inherited scratch or clean old scratch;
   never use NUL as a mypy cache. All local
   results are platform-scoped, not claims of native private restoration.
4. Commit once with no attribution/trailers. One-line PR description:
   `Add inactive recovery evidence binding, conflict review and backup fact measurements.`
   Require full Quality (including Linux), Resilience, CodeQL Analyze AND Code
   scanning results green on the exact final commit. Any change requires fresh
   hashes/checks. Owner alone merges; no automatic merge or hosted activation.
5. After merge collect the measurements above. Do not run a new signature,
   private decoder, restoration or deletion from this package. No new workflows.

## Verification record

The per-package manifest binds payload hashes and nine unchanged prerequisites.
It requires exact base/HEAD, ten staged regular-file additions only, no unstaged
or untracked files, and staged/worktree equality. Diagnostics show public paths
and expected/actual hashes, never arbitrary exception text or private paths.
Tests exercise real ephemeral Ed25519 signatures, tampering in each reference,
wrong external anchors, semantic escalation, rollback, duplicate/missing roles,
schema mixing, order-invariant conflicts, count bounds and space overflow.
SQL verification is STATIC safety review, NOT PostgreSQL execution. Real SQL
measurement, Linux/native restore and exact-final-SHA hosted CI remain separate.
Builder Windows clean-public-clone rehearsal: **237 passed, 1 skipped** on the
eight-file focused selection above. The skip is the existing symlink case; no
native/private acceptance is inferred. Pyflakes: zero findings in seven files;
strict mypy: three source modules passed; exact staged checker: failures empty;
staged whitespace check clean. Independent checker: 77 synthetic tests passed
with the manifest test intentionally deselected, then source/security review
of the final SQL and contracts; no remaining blocking finding. No full local
suite, hosted CI, native Linux or private restore was run for this new package.
No earlier full-suite pass claim is reused here.

## Full open-items check: nothing silently cleared

Bundled: backup/capacity measurement instructions; typed evidence-reference
binding contract; cross-batch conflict and peak-space review; this handoff.
Still blocked/pending: actual destination measurement adapter and authenticated
custody acceptance; B sidecar schema validation at the custody boundary; DB backup
existence/coverage/size and full schema/role/function facts; matching same-cut
typed restore and explicit version policy; cold readers/writers and retention;
Drive receipt/ID authentication and independent failure domain; actual DB backup
and recovery rehearsal. Original eight-batch generic16MiB blocks unchanged.

Deliberately deferred, separate from recovery: production failure-alert delivery;
Windows Time 12:48 stop/root dispersion; missing14Oct saved audit (absence of a
saved report is not absence of observations); legacy audit exit2/shared-root
writes; OPTION_CAPTURE_ENABLED off; which sessions JSON ends1Oct and whether it
is consumed by a live gate; historical receipt authentication/keys; full local
suite including unclassified failures and WinError5 hard-link case (no ACL
workaround); duplicate .7z/Downloads cleanup; holiday-aware collector skip for
runs175/176; gated ML/backtesting, licences, labels and frozen paper study.
Host PostgreSQL remains unsuitable as the private restore target; no start,
network/listen change or service configuration is authorised here.

Wednesday21Oct manual capture is independent and UNTOUCHED. Follow the installed
reviewed procedure only: genuine session-morning file, prior close19Oct per
reviewed calendar, personally witnessed notification, disabled dated tasks before
Prepare, Prepare before09:15, Start once around08:00 (not before07:50:30 and
strictly before09:20:30), and supervise the
first automatic receipt. Keep power/awake/login and fresh deterministic clock
gates. No catch-up, same-slot retry, bypass, new helper or recovery dependency.
If a current gate cannot establish the date/session or time, NO_GO rather than
editing a sessions JSON or clock threshold. This package asserts no readiness.

## Research / technology radar and next leverage

Adopted: existing Ed25519 chain, native destination identity design, PostgreSQL
catalog-only measurements and a future disposable PG17 target. Reused tested
Docker/Arrow containment rather than adding another runner or credential plugin.
Considered/deferred: full local Supabase stack (useful later for platform-level
restore but heavier than the first six-table typed rehearsal); restic/Borg
(additional repositories/keys, not proof of current provenance); pgBackRest/Barman
(physical-server access not established); DuckDB/Parquet (analysis tier, not a
Postgres schema/RLS/function restore); pg_verifybackup (physical base backups,
not a .7z collection of Parquet). No new paid service/tool/extension/install is
needed for the next metadata step. Builder and independent checker stay separate;
run-time agents can report only. No plugin is used as a deterministic authority.

Official references checked20Oct2026:
- [Supabase backups](https://supabase.com/docs/guides/platform/backups): automatic
  daily backups are documented for paid plans; free projects are advised to make
  off-site exports. Storage API objects are not included in database backups.
- [Database vs disk size](https://supabase.com/docs/guides/platform/database-size):
  cluster SQL allocation and physical disk/WAL are distinct; dashboard metrics
  update daily.
- [PostgreSQL17 pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html):
  single-database consistent backup; global objects need separate handling.
- [PostgreSQL17 pg_restore](https://www.postgresql.org/docs/17/app-pgrestore.html):
  restoring SQL can execute source-controlled code even for partial restores;
  inspect/restrict dependencies and jobs, not just table names.
- [Docker run](https://docs.docker.com/engine/containers/run/) and
  [Desktop resources](https://docs.docker.com/desktop/settings-and-maintenance/settings/):
  image identity, networking/mount controls and VM resources are explicit choices.
- [Supabase changelog](https://supabase.com/changelog) checked for current context;
  markdown endpoint could not be rendered, HTML page used instead.

Highest-leverage next build AFTER facts: one bounded native-handle collector for
the already-completed A/B evidence, with signed purpose-limited references and a
separate physical-custody/restore witness. Then synthetic native PostgreSQL
rehearsal proving conflict quarantine and disk-full/unknown-commit behavior before
the first private typed restore. Do not spend the remaining runway on a pretend
same-generation restore or more repeated compaction.
