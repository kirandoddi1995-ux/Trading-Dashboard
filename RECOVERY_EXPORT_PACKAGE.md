# Package 2B2B — consistent SQLite export and separate local checkpoint

## Decision

Exact merged 2B2A base: ed951e2c36ecb5dd6755cf781c72a40b7454bf0d. Read-only
GitHub checks show quality, resilience and CodeQL successful for that SHA.
Build and review this offline adapter now. Owner key preservation and harmless
encrypted-disk rehearsal proceed in parallel, before any real backup commissioning.

This package exports a consistent SQLite source image, verifies its original
signatures/state and binds its bytes to the authenticated generation introduced
in 2B2A. A separately located local SQLite checkpoint supports compare-and-swap,
stale-predecessor rejection, readback and exact retry after an uncertain response.
It is NOT the complete independent-backup service: there is no encrypted replica,
Drive upload, cross-file freeze, owner CLI, live restore or archival activation.
It refuses multi-file inventories rather than silently reducing their scope.

## Complete six-file review/upload group

ROOT (five):

- recovery_export.py — NEW typed offline exporter/verifier/local custody adapter.
- RECOVERY_EXPORT_PACKAGE.md — NEW scope, tests and remaining commissioning steps.
- OWNER_KEYS_AND_BACKUP_RUNBOOK.md — UPDATED owner priority and real-backup gate.
- PERMANENT_STORAGE_PACKAGES.md — UPDATED merged baseline and remaining sequence.
- AUTOMATION_PROGRESS.md — UPDATED continuity, decisions and validation.

tests/ (one):

- tests/test_recovery_export.py — NEW synthetic export, WAL, corruption, CAS,
  lock, restart/readback and uncertain-response regression tests.

Do not copy any other unfinished runtime, migration, test, private credential,
cache or environment file. Existing tests/test_local_state_recovery.py supplies
its synthetic fixture and remains UNCHANGED; include it in focused test execution,
not as a changed upload. Existing recovery_bundle.py/catalog/state/ledger sources
are dependencies already on main. No production fingerprint input/import changes.

## What is actually implemented

The library has no CLI and is not imported by the running app, capture tasks or
collectors. Callers explicitly supply all paths, reviewed single-source inventory,
original keyring, separate metadata key, timezone-aware time and generation IDs.
It reads the original SQLite source with mode=ro and a pinned read transaction,
then uses SQLite's backup API, not a copy of a live main file or WAL sidecars.
The [SQLite backup documentation](https://www.sqlite.org/backup.html) describes
snapshot semantics. Tests commit a concurrent WAL writer during the export and
prove the exported state stays at the pinned source snapshot.

New generation directory creation and file writes are exclusive; no overwrite or
reuse, including after failures. Failed/partial files remain for private inspection;
the library deletes nothing. A 30-second deadline is checked between backup steps,
with size guards before and during export. Original source driver reads use a
two-second busy timeout. These are not hard preemption of arbitrary filesystem
I/O or a total-operation deadline: integrity checking, five-table verification and
hashing have separate bounds. Those limits do not justify increasing sampling,
reducing evidence or changing production thresholds.

Witness comes from the exported SOURCE snapshot, before a restore exists. Full
image integrity and byte identity include tables outside the five-table witness;
original HMAC signatures and local intent/fence checks reuse local_state_recovery.
Missing original keys fail, even when metadata authentication succeeds. Originals
are never re-signed, repaired or given invented intent. No remote ACK is inferred.

Windows fsync requires a writable handle; this is used only on the newly created
image. SQLite 3.51 mode=ro also skipped CHECK validation in a regression fixture;
the exported image receives mode=rw with query_only=ON for integrity_check(1),
after requiring DELETE journal mode. Original source remains mode=ro. No INSERT,
UPDATE, DELETE or schema change is issued on either source or image by verification.
The [integrity-check documentation](https://www.sqlite.org/pragma.html#pragma_integrity_check)
also distinguishes structural checks from foreign-key checks. This package does
not claim every application-level invariant outside its existing five-table proof,
foreign-key validity, arbitrary extension compatibility or complete app recovery.

Custody bootstrap is explicit and refuses existing files. Read/commit never
bootstrap a missing/corrupt store. Store is capped at 64 KiB, exact schema/contract
and bounded rows; unexpected objects, malformed heads and nonzero genesis receipt
are rejected. Commit requires a verified generation and separate store path, then
uses BEGIN IMMEDIATE, DELETE journal and synchronous=FULL, followed by readback.
An exact retry re-verifies the files. A competing/stale predecessor never advances
the head; a lock or ambiguous commit requires private head inspection, not reset.
SQLite documents [synchronous](https://www.sqlite.org/pragma.html#pragma_synchronous);
hardware flush honesty and filesystem guarantees are not proved by these tests.

## Trust and durability limits — do not commission from this result

Separate PATH is not independent DEVICE or account custody. Caller must protect
private parent directories/ancestors and prevent generation mutation during use;
basic symlink/junction checks cannot establish Windows ACLs or resist a malicious
local writer. The checkpoint is trusted only under that separate custody model.
Its plaintext hashes/contract are not keys or market payloads, but remain private.
Tampering with or rolling back the independent store itself is not prevented by
an authenticated bundle; it still needs separately retained trusted-head custody.

File fsync and SQLite commits do not prove Windows directory-entry power-loss
durability, device loss recovery, encryption or two independent replicas. Results
explicitly leave independent_replica_verified, power_loss_recovery_verified,
application_recovery_verified and approval_authority false. This local checkpoint
must NOT become the hot-deletion gate. Disconnected disk cannot receive nightly
backups; unreplicated history stays protected. No hosted credentials/settings are
requested. No private data has been exported or inspected by the agent.

Reopen tests prove local-store connection restart/readback; they are not a full
process-death recovery or owner CLI rehearsal. The proposed-generation object is
caller-owned. Persistent proposal admission/reload, publication receipts, trusted
head replication, encryption and crash-safe cross-file publication belong to the
next adapter, before any actual owner export. Do not reconstruct trusted expected
heads from the restore target or treat a lost store as a new bootstrap.

## Exact-base owner rehearsal

In a CLEAN CLONE of exact ed951e2c36ecb5dd6755cf781c72a40b7454bf0d, copy only
these six complete files and inspect changed paths. If main advanced, review against
its new exact tree; do not change the historical Package 1 baseline to hide blockers.
Use the existing environment without copying it or secrets into the clone:

```powershell
$storageReviewPython='C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
& $storageReviewPython -c "import json,subprocess; from pathlib import Path; from storage_package_inventory import Baseline,check_package; sha='ed951e2c36ecb5dd6755cf781c72a40b7454bf0d'; rows=subprocess.check_output(['git','ls-tree','-r','--full-tree',sha],text=True).splitlines(); files={row.split('\t',1)[1]:row.split('\t',1)[0].split()[2] for row in rows}; members=['recovery_export.py','RECOVERY_EXPORT_PACKAGE.md','OWNER_KEYS_AND_BACKUP_RUNBOOK.md','PERMANENT_STORAGE_PACKAGES.md','AUTOMATION_PROGRESS.md','tests/test_recovery_export.py']; result=check_package(Path.cwd(),Baseline(sha,files),members); print(json.dumps(result)); raise SystemExit(2 if result['blockers'] else 0)"
& $storageReviewPython -m pytest -q -p no:cacheprovider --basetemp "$env:TEMP/export-focused-$([guid]::NewGuid().ToString('N'))" tests/test_recovery_export.py tests/test_recovery_bundle.py tests/test_local_state_recovery.py --tb=short
& $storageReviewPython -m pyflakes recovery_export.py tests/test_recovery_export.py
& $storageReviewPython -m mypy --strict --follow-imports=silent recovery_export.py tests/test_recovery_export.py
```

Require package check with no blockers and 181 focused tests passing. The fixture
import is a test-module dependency; tests/test_local_state_recovery.py must remain
at its correct committed tests/ path. Static package checking is not proof of all
dynamic resources, runtime compatibility, ACLs or real backup custody.

```powershell
$env:EQUITY_TEST_PGLITE_MODULE='C:\Users\banga\Desktop\kiran_share_market\tests\sql-harness\node_modules\@electric-sql\pglite'
& $storageReviewPython -m pytest -q -p no:cacheprovider --basetemp "$env:TEMP/export-full-$([guid]::NewGuid().ToString('N'))" --tb=short
```

Upload one complete reviewed branch/PR, wait for exact-candidate quality/resilience/
CodeQL, merge and verify post-merge checks. Local mixed-tree tests include unrelated
drafts, so they are not a substitute for clean-candidate CI. Keep release/mode/F&O
holds and scan-only recurrence unchanged. No fingerprint expectation update.

## Owner work now, implementation next

1. Follow OWNER_KEYS_AND_BACKUP_RUNBOOK.md to save/reopen the current key in an
   encrypted password-manager note. Do not rotate or paste keys into commands/chat.
2. Check older vault versions privately; report availability only. Missing older
   keys protect affected originals, not permission to replace/re-sign them.
3. Install/rehearse encrypted 7-Zip storage with harmless dummy content as already
   described; no real export yet. Verify decrypt/hash/readback; retain encryption
   credentials separately and disconnect the disk after the owner session.
4. Confirm applicable data-licence permission for private Drive, offline replicas
   and retention. UNKNOWN remains a commissioning blocker, not inferred permission.

Next implement the full reviewed app-state inventory, explicit cross-file barrier,
persistent authenticated proposal/reload and independently replicated trusted heads;
then immutable encrypted replica publication and disposable restore from the second
copy. Test process interruption at every boundary. After that: legacy intent/remote
retry, all historical readers/factories and finally owner archival commissioning.
This package is useful groundwork, not a permanent-storage completion claim.

## Final validation and self-review

Final focused: 181 passed. Full: 2,621 passed, 4 unchanged skips, 2 subtests passed
in 523.24s; 35 new tests over 2B2A. Root/tests pyflakes clean; strict new-module/
test types and main-equivalent 19-module types pass. Isolated imports and separate
synthetic app boot (2 tests) pass. Exact-tree static package check has no blockers;
all seven unchanged core/fixture dependencies match ed951e2 Git blobs.
Self-review fixed Windows sync handling, the integrity-mode regression and strict
schema enumeration; the final suite includes those fixes. The earlier full run
was intentionally interrupted for review and is not claimed passing. No existing
assertions removed, no gate weakened. Exact clean-candidate CI is still required.
