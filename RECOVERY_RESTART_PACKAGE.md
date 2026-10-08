# Package 2B2C — restart admission and extracted-copy audit

Offline foundation only. No installed capture, app factory, hosted schema,
workflow, credential discovery, encryption or deletion is changed. Neither
proposal admission nor a passing copy audit commissions permanent storage.

## Complete upload group A (six paths)

- `recovery_bundle.py` — modified: explicit authenticated proposal admission,
  separate from committed-checkpoint restore verification.
- `recovery_proposal.py` — new: reload a complete export after process death;
  reverify originals and checkpoint; resume through the existing CAS.
- `recovery_replica_audit.py` — new: independently expected checkpoint, full bytes
  and original signatures checked against two separately extracted copies.
- `tests/test_recovery_proposal.py` — new: restart before/after commit, lost state,
  tamper, competing successor, preserved predecessor and exact retries.
- `tests/test_recovery_replica_audit.py` — new: missing/corrupt/mixed copies,
  false topology, key failures and source mutation during audit.
- `RECOVERY_RESTART_PACKAGE.md` — this file, new.

Start a clean clone/PR from merged Package 2B2B main
`9ce3af9bcf1e8a64a1e04eb5ba57c40a5080d39f` or a later reviewed descendant.
Only these six paths belong in this PR. Put tests inside `tests/`, not at root.
No SQL or older local runtime drafts belong in it. Review complete files.

```powershell
python -m pytest -q tests/test_recovery_proposal.py tests/test_recovery_replica_audit.py tests/test_recovery_export.py tests/test_recovery_bundle.py tests/test_local_state_recovery.py -p no:cacheprovider --basetemp "$env:TEMP/restart-$([guid]::NewGuid().ToString('N'))" --tb=short
python -m mypy --strict --follow-imports=silent recovery_bundle.py recovery_proposal.py recovery_replica_audit.py
python -m pyflakes recovery_bundle.py recovery_proposal.py recovery_replica_audit.py tests/test_recovery_proposal.py tests/test_recovery_replica_audit.py
```

Require focused tests and exact-SHA quality/resilience/CodeQL checks before merge.
These modules are not in the live release fingerprint inputs and no live import
is added: do not change Streamlit expectations for this package.

## Crash boundaries and custody

Before preparing an export, independently retain its predecessor, reviewed
contract/inventory and original-key versions. `recovery_export.prepare()` writes
a NEW generation; it does not commit custody. After a restart:

1. `recovery_proposal.reload()` takes the independently retained predecessor,
   contract and keyrings, plus explicit existing generation and custody paths.
   It does not infer the predecessor from the downloaded bundle.
2. A partial directory, absent/corrupt custody, missing key, invalid original,
   wrong contract or changed image blocks. Files stay for private inspection.
3. Head equal to predecessor means READY_FOR_LOCAL_CAS. Head equal to the exact
   candidate means ALREADY_LOCALLY_COMMITTED. Another successor or a later head
   blocks; there is no “use latest”, genesis reset or overwrite fallback.
4. `resume()` rechecks all files and performs the original atomic CAS. Reload
   does not lock out competing writers; a race after reload must block at CAS.
5. A lost commit response remains uncertain until the actual head is read and
   the exact generation is verified. Never recreate the custody database.

Authenticated proposal admission derives the candidate digest to verify its HMAC,
NOT to prove it was committed. `recovery_bundle.verify()` / `verify_restore()`
retain their independent full-checkpoint requirement. Owner-preserved old roots
are needed to verify historical generations; a current head is not a substitute.
Protect predecessor/checkpoint custody against rollback outside bundle storage.
This local implementation does not prove hardware/power-loss durability.

## Two-copy audit: exactly what it proves

`recovery_replica_audit.verify_copies()` accepts the source export and reviewed
`drive` and `external_disk` extraction directories. It validates source, each
copy, then source again: whole SQLite bytes, bundle metadata, five-table witness
and original HMACs. It rejects overlapping directories and linked ancestors.
The independently retained checkpoint must equal the source's declared one.
Generation files must be immutable during this operation; callback-free reads
still rely on caller ACLs/quiescence.

It does NOT encrypt/decrypt, download, create replicas, verify that a directory
really lives on an external disk, or prove that Google Drive and the disk have
independent custody. Hard links and copied custody stores are not independent
failure domains. `encryption_verified`, `physical_independence_verified`, trusted
checkpoint durability, application recovery and deletion authority remain false.
This is intentionally not a boolean gate the owner can toggle to permit pruning.

Real backup creation/publication is still held. First complete the existing owner
key/version and harmless encrypted-disk rehearsal. Then implement the actual
encrypted-replica adapter, protected checkpoint replication and whole-app restore
under a reviewed source inventory. Do not export real state using improvised code
or place extracted/plaintext images on the unencrypted external disk.

## Cross-file scope remains explicit

The existing exporter supports one pinned SQLite snapshot only. Its five-table
witness covers ledger, delivery outbox, scan jobs/candidates and checkpoint outbox;
its full-image digest also detects changes elsewhere in that image. It does not
assert application semantics for every table. `app.py` also writes a separate IV
JSON cache; in-memory state, hosted receipts, cold roots/catalogs and reviewed
release expectations have their own custody. A separate IV copy plus SQLite
snapshot is NOT a consistent cut. Multi-file export remains blocked until every
writer participates in a tested cut/barrier (or a documented derived-state rebuild
with original provenance is proved). A producer lock not shared by those writers
does not establish quiescence. No current app lock is repurposed or bypassed.
