# Package 5A — lossless universe payload shadow codec

This is an offline codec, not a migration or permission to remove either universe
table. It addresses repeated raw payloads without merging snapshot membership,
source observations, version availability times or historical PIT identities.

## Complete upload group B (three paths)

- `universe_payloads.py` — new: bounded raw-byte content-addressing, complete
  membership reconstruction and independent full-source fingerprint equality.
- `tests/test_universe_payloads.py` — new: repeated/changed payloads, identity,
  ordering, framing, Unicode, missing/corrupt data, collision and size failures.
- `UNIVERSE_SHADOW_PACKAGE.md` — this file, new.

Use a fresh branch/clean clone after group A is merged. This group has no runtime
imports and no dependency on A; the order merely keeps review manageable.

```powershell
python -m pytest -q tests/test_universe_payloads.py -p no:cacheprovider --basetemp "$env:TEMP/universe-shadow-$([guid]::NewGuid().ToString('N'))" --tb=short
python -m mypy --strict --follow-imports=silent universe_payloads.py
python -m pyflakes universe_payloads.py tests/test_universe_payloads.py
```

Review exact paths and wait for PR checks. No fingerprint expectation change.
Do not include `production_repository.py` or any held SQL migration.

## Contract and integration requirements

`Member` contains instrument key, every non-raw field serialized by a reviewed
adapter, and exact raw bytes. The full snapshot header is supplied separately.
The codec preserves bytes, row order and member keys, retains per-snapshot
references, and shares only equal raw payload bytes. It hashes length-prefixed
fields, so different concatenations cannot accidentally share a source witness.
Caller-provided bytes are opaque: this module does not parse a Postgres row,
certify source authenticity or establish that an adapter omitted no column.

Equivalent JSON with different serialization is deliberately NOT collapsed.
For Postgres JSONB, a future adapter must pin and test a canonical serialization
of actual logical JSONB values, handling numeric representations and Unicode.
An assumed Python JSON round trip is not enough. Do not change historical source
hashes by silently reserializing them. The codec's source fingerprint is a NEW
shadow witness, not a replacement for existing universe/source hash algorithms.

One snapshot is capped at 10,000 rows, 1 MiB per value and 32 MiB aggregate source
bytes, before processing unlimited rows. A failed iterator or missing/corrupt
payload produces a redacted failure, never a truncated successful universe.
Reconstruction verifies each referenced digest AND the independently retained
full source fingerprint. A different header, key, field, order or missing member
therefore blocks. Caller/adapter owns its source-read/I/O deadlines and immutable
object custody. No live files/data were read to test this.

Next structural adapter must prove all of the following before hosted cutover:

- Snapshot/header rows and every canonical/version column round-trip exactly;
  preserve availability/observed/effective dates, IDs and existing fingerprints.
- Shadow current/latest-complete plus historical PIT reads, instrument removals,
  symbol/lot changes and repeated same-day snapshots. Old and new readers agree.
- A unique raw hash is collision-checked against actual bytes, not trusted alone.
  Shared raw payloads do not imply that every non-raw membership column is shared.
- Foreign keys and all protected references prevent dictionary garbage collection
  while a hot or cold membership references it. Cold reference retention includes
  analytical and recovery datasets, not only live scanners.
- New normalized writes remain inactive until compatible reader/role/RLS grants
  and independently authenticated cold lookup are installed. No hot-only fallback.
- Capacity plan includes old tables plus new dictionary/reference/index allocation;
  then measured bounded batch shadow ingest, tiny owner cutover trial and restore.

The observed 5,631 distinct payloads among 58,740 version rows motivates this
approach; it is not a measured capacity guarantee. Reference rows, metadata and
indexes still consume space. No savings are credited before they actually occur.
Preserve the old tables until every consumer and restore gate is satisfied.
