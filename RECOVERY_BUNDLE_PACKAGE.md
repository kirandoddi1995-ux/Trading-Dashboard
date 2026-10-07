# Package 2B2A — authenticated backup identities, offline only

## Decision and boundary

Package 2B1 is merged at b213ec87b11ee4c50b197110c6d26e1105a633c0.
This seven-file package takes the next bounded step: bind the pre-restore source
witness, reviewed component inventory and every component's byte identity into
one authenticated generation. It does NOT implement a persistent backup, export
command, live restore, secure checkpoint store or whole-application recovery.
No SQL, workflow, runtime factory, installed capture or hosted setting changes.

The order is: authenticated identities (this package) -> consistent export and
durable independent checkpoint/replica custody -> legacy delivery intent and
remote retry semantics -> every historical reader/factory -> owner commissioning.
Actual export and custody belong together: an authenticated manifest alone must
never be mistaken for a retained recoverable backup.

## What the code guarantees, and what it cannot

`recovery_bundle.py` reuses the existing catalog receipt HMAC/chain codec in a
separate `backup:` namespace. A reviewed contract binds logical role, source ID
and format, without private paths. Mandatory `primary_state` is a SQLite image.
The manifest binds the five-table source witness, component SHA256/byte sizes,
generation/cut IDs, UTC time and signed contract digest. Verification requires
the contract, keyring and previous/current checkpoint supplied independently;
it never learns its trusted expectation from the restored target. Missing keys,
checkpoint or components fail closed; current-checkpoint verification rejects
older generations. An explicitly retained historical checkpoint can verify its
own historical generation: this is not a claim of global freshness.

The caller must actually retain the contract/checkpoint independently. This
library cannot prove that custody. `seal` returns a PROPOSED checkpoint, not a
committed one. `genesis` is explicit bootstrap only, not a lost-checkpoint repair.
The signing key attests declared metadata, not source authenticity. Declared cut
IDs do not prove that separately captured files represent one consistent instant.
Original event signatures still require their original keys and recovery adapter.

`measure` streams caller-opened bytes, capped at 1 GiB per component, 2 GiB total,
64 components and 128 KiB manifest; measurement checks a 60-second bound BETWEEN
reads. It neither opens paths nor rewinds/closes streams. The future adapter must
provide complete immutable images from their start and bounded I/O; a blocking
read cannot be preempted here. These are offline guard bounds, not a production
capacity/retention policy. No real private file is read by this package's tests.

`verify_restore` re-authenticates before requiring all byte identities and the
restored five-table witness to match. Its success is BACKUP_IDENTITIES_VERIFIED.
Capture consistency, custody persistence, original signatures, remote recovery,
whole-app recovery and approval authority remain explicitly false. Encryption
passwords, backup authentication keys and original ledger keyrings are distinct
roles; do not reuse, rotate or provision hosted secrets for this offline package.

Tests include two synthetic generations/key rotation, rollback/mixing, every
missing/extra identity, tampering, malformed/oversized inputs and redacted driver
errors. Integration tests use a quiescent disposable SQLite backup and original
signed events: intact restore passes; changing an auxiliary table outside the
five-table witness fails its full-image hash; deleting intent fails recovery.
This is not an atomic multi-file capture or live application restore rehearsal.

For the next adapter, use a transactional SQLite snapshot/backup rather than an
Explorer copy of an active main file. SQLite documents the backup snapshot
semantics in its [Online Backup API](https://www.sqlite.org/backup.html).
Cross-file consistency needs its own reviewed freeze/publication protocol; it
does not follow automatically from a consistent SQLite image.

## Complete upload group — seven files only

ROOT (five):

- recovery_bundle.py — NEW typed, bounded authenticated identity library.
- RECOVERY_BUNDLE_PACKAGE.md — NEW scope, review and owner runbook, this file.
- OWNER_KEYS_AND_BACKUP_RUNBOOK.md — UPDATED owner priorities and custody limits.
- PERMANENT_STORAGE_PACKAGES.md — UPDATED merged baseline and bounded next stages.
- AUTOMATION_PROGRESS.md — UPDATED continuity and validation record.

tests/ (two):

- tests/test_recovery_bundle.py — NEW deterministic synthetic regression tests.
- tests/test_local_state_recovery.py — UPDATED disposable full-image integration.

Do not include any other local-only storage runtime, migration, test, private
credential file or environment directory. Dependencies catalog_receipts.py,
local_state_recovery.py and evidence_ledger.py are already on main; they are NOT
modified or re-uploaded. The pinned Package 1 inventory remains historical.

## Owner review in a clean clone

Start from exact main b213ec87b11ee4c50b197110c6d26e1105a633c0, copy only these
seven complete files into the review branch and inspect changed paths. If main
has advanced, review against that new exact base before proceeding. Use the
existing environment without copying it or private files into the clone:

```powershell
$storageReviewPython='C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
& $storageReviewPython -c "import json,subprocess; from pathlib import Path; from storage_package_inventory import Baseline,check_package; sha='b213ec87b11ee4c50b197110c6d26e1105a633c0'; rows=subprocess.check_output(['git','ls-tree','-r','--full-tree',sha],text=True).splitlines(); files={row.split('\t',1)[1]:row.split('\t',1)[0].split()[2] for row in rows}; members=['recovery_bundle.py','RECOVERY_BUNDLE_PACKAGE.md','OWNER_KEYS_AND_BACKUP_RUNBOOK.md','PERMANENT_STORAGE_PACKAGES.md','AUTOMATION_PROGRESS.md','tests/test_recovery_bundle.py','tests/test_local_state_recovery.py']; result=check_package(Path.cwd(),Baseline(sha,files),members); print(json.dumps(result)); raise SystemExit(2 if result['blockers'] else 0)"
& $storageReviewPython -m pytest -q -p no:cacheprovider --basetemp "$env:TEMP/backup-binding-focused-$([guid]::NewGuid().ToString('N'))" tests/test_recovery_bundle.py tests/test_local_state_recovery.py --tb=short
& $storageReviewPython -m pyflakes recovery_bundle.py tests/test_recovery_bundle.py tests/test_local_state_recovery.py
& $storageReviewPython -m mypy --strict --follow-imports=silent recovery_bundle.py tests/test_recovery_bundle.py
```

Require PACKAGE_CHECK_PASSED_REQUIRES_REHEARSAL, blockers empty and 146 focused
tests passing. Package checking is dependency metadata, NOT a backup proof.
Full suite uses the existing SQL harness (same as previous rehearsals):

```powershell
$env:EQUITY_TEST_PGLITE_MODULE='C:\Users\banga\Desktop\kiran_share_market\tests\sql-harness\node_modules\@electric-sql\pglite'
& $storageReviewPython -m pytest -q -p no:cacheprovider --basetemp "$env:TEMP/backup-binding-full-$([guid]::NewGuid().ToString('N'))" --tb=short
```

Only merge after quality/resilience/CodeQL pass on the exact complete candidate.
The mixed local suite contains unfinished drafts and is not exact-public-tree CI.
No production fingerprint inputs/imports change; no new fingerprint or Streamlit
expectation update is required. Do not substitute a health display hash. Release
promotion stays held; capture and scan-only recurrence remain unchanged.

## Owner steps and next acceptance

Do the private current-key password-manager note and reopen check now, following
OWNER_KEYS_AND_BACKUP_RUNBOOK.md; this is credential preservation, not rotation.
Older vault-version checks and the harmless encrypted 7-Zip disk rehearsal can
follow in parallel. Report availability only; never key values/screenshots.
None blocks these offline synthetic tests; all applicable keys, permission and
independent-copy proofs block real archival/deletion commissioning.

Next package must inventory all actual recovery state without exposing values,
capture a consistent source generation with its witness, freeze dependent file
identities, publish only complete immutable generations and commit independent
trusted checkpoints safely across crashes/retries. Prove missing/corrupt first or
second copies protect history. Restore from a separately retained generation into
a disposable target, preserving original intent, signatures, fences and roots.
Drive + encrypted disconnected disk is the intended first commissioning route;
the disk cannot receive unattended nightly backups. Do not authorize hot deletion
on promises of a later copy. Licence retention remains an explicit owner gate.

## Final local validation

Focused: 146 passed. Full: 2,586 passed, 4 unchanged skips, 2 subtests passed
(553.02s); 69 more tests than 2B1, none removed/skipped to obtain a pass.
Root/tests pyflakes clean; strict new-module/new-test types and main-equivalent
19-module type checks pass. Offline imports and separate app boot (2 tests) pass.
Exact-main dependency check has no blockers; unchanged direct/transitive core
sources match public b213ec8 blobs. Self-review compared the modified existing
test with exact main, reviewed trust/boundary failures and required canonical
serialized identity comparison. No production fingerprint change or hosted write.
These are local results; complete candidate clean-clone CI is still required.
