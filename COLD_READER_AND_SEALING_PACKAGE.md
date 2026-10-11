# Group D2 — read-only cold integration and local sealing rehearsal

Upload after D1. Ten complete paths; preserve root versus tests/:

- ledger_read_contract.py — read-only injected SQL and GET interfaces, bounded snapshot settings.
- ledger_source_capture.py — bounded native-original decoding, rejecting duplicate JSON keys and non-finite constants.
- ledger_runtime_reader.py — protected cold-root/hot-head reader and atomic staged history. This file is NEW to public main, not a live factory replacement.
- ledger_archive_publication.py — injected segment/catalog/root-receipt publication with complete readback; no SQL deletion or automatic connection.
- cold_local_objects.py — explicit local content-addressed objects; GET-only by default, opt-in immutable writes for synthetic sealing/restart rehearsal.
- tests/test_ledger_read_contract.py
- tests/test_ledger_staged_reader.py
- tests/test_cold_local_objects.py
- tests/test_ledger_archive_publication.py
- COLD_READER_AND_SEALING_PACKAGE.md

The historical-reader contract deliberately does NOT import the SQL deletion
repository. Reading cannot require an archive-worker write interface. Publication
is separately injected and does not activate automatically on import.

## Owner review and commands

Fresh branch from exact main after D1; upload only these ten complete paths. Never
include ledger_archive_repository.py, production_repository.py, equity_runtime_health.py,
the review-only migrations, local configuration or any private objects. Full exact-SHA
PR CI and post-merge main CI remain mandatory. Keep capture, scan-only recurrence,
release hold and fingerprint expectations unchanged. No hosted step follows merge.

```powershell
python -m pytest -q tests/test_ledger_read_contract.py tests/test_ledger_staged_reader.py tests/test_cold_local_objects.py tests/test_ledger_archive_publication.py tests/test_ledger_history_stream.py tests/test_ledger_cold_store.py -p no:cacheprovider --basetemp "$env:TEMP/cold-reader-review-$([guid]::NewGuid().ToString('N'))" --tb=short
python -m pyflakes ledger_read_contract.py ledger_source_capture.py ledger_runtime_reader.py ledger_archive_publication.py cold_local_objects.py tests/test_ledger_read_contract.py tests/test_ledger_staged_reader.py tests/test_cold_local_objects.py tests/test_ledger_archive_publication.py
python -m mypy --strict --follow-imports=silent ledger_read_contract.py ledger_source_capture.py ledger_runtime_reader.py ledger_archive_publication.py cold_local_objects.py tests/test_ledger_read_contract.py tests/test_ledger_staged_reader.py tests/test_cold_local_objects.py
```

Tests use synthetic objects and injected snapshots, with no network or key discovery.
The restart rehearsal seals original events, reads back content-addressed objects,
authenticates the receipt and reconstructs originals after reopening. Writes require
the literal boolean True; string "false" cannot enable them. Existing corrupt or
partial files are never overwritten. Errors do not expose private paths or values.
Publication now redacts unexpected transport/source diagnostics at both preparation
and readback boundaries, while retaining the reviewed original-signature mismatch
category. Three extra failure tests cover put/get/re-verification exceptions.

## What this does not commission

Real encrypted Drive/external-disk custody; old-key coverage; cross-file application
restore; remote append/ACK reconciliation; live factories; every historical consumer;
SQL source/root commit; hot deletion; all-writer capacity reservation and alerting.

The reader's staged interface exhausts originals and rechecks the protected root and
heads before exposing them. A failed or changed source is not silently replaced by
hot-only history. Cold reads happen outside SQL snapshots; short snapshots and
bounded hot tails are used. Real multi-connection Postgres race acceptance remains
separate from offline tests.

Local object storage requires a privately controlled existing directory. It does
not assert encryption, filesystem power-loss durability, immutable permissions or
device independence. OS ownership/ACLs must prevent another process replacing
ancestors/files during access. A verified local copy alone grants no retirement.

The archive SQL repository was refactored locally to share these contracts, but is
HELD and explicitly excluded from this group. Its later reviewed package must bring
all deletion guards, SQL dependencies and concurrent-transaction acceptance together.
