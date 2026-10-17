# Archive incident byte/footer review — offline only

`archive_recovery_review.py` is a standalone preview-by-default CLI and in-memory
API. It imports only stdlib at module load; confirmed Parquet metadata review
requires installed PyArrow, imported lazily. It never imports the archive transport,
uses credentials, connects to DB/Drive, extracts ZIPs, writes receipts, invokes a
row reader, inspects column statistics or reads `_row_json`/market row values.
Hashing raw compressed ZIP and Parquet bytes is not decoding source rows.

## Exact owner export and browser download contract

The owner supplies the independently obtained read-only receipt inventory and a
browser download of the whole Drive archive folder as ONE ZIP. No Python transport,
token, personal name, handwritten batch mapping or manual 244-file renaming is
needed. Keep both files private, outside the source checkout. The builder has not
read a real inventory, archive, database or Drive resource.

Inventory JSON has exactly these envelope keys:

```text
format: archive-recovery-inventory-v1
window_start: 2026-10-11T00:00:00+00:00
window_end: 2026-10-17T18:25:14+00:00
measured_at: aware export timestamp, at/after window_end
batches: list of receipt objects
```

Every receipt has exactly `batch_id`, `source_table`, `row_count`, `file_sha256`,
`drive_file_id`, `drive_manifest_id`, `deleted_count`, `completed_at`.
Aware timestamps normalize to UTC. Completed positive-delete batches must fall
within the inclusive fixed window; for this reported all-rows-deleted incident,
each batch requires `row_count == deleted_count > 0`. IDs must be unique. No
truncated inventory or altered window can reduce the planned denominator.

Owner-reported fixed denominators are 122 batches / 98,755 deleted rows, including:

- `market_quotes`: 44 batches / 42,700 rows.
- `scanner_observations`: 24 / 21,350.
- `universe_membership`: 30 / 13,347.
- `universe_membership_versions`: 24 / 21,358.

All four table-level totals must match, not just their global sum. The fixed
schema registry recognizes the six public `drive_archive.SPECS` formats, but
this incident's receipts must match the four-table denominator above. These
known totals are not independent authentication of DB export completeness or IDs.

ZIP entries use ORIGINAL download basenames:
`{source_table}-{batch_id}.manifest.json` and `{source_table}-{batch_id}.parquet`.
All files are at root or below one common folder prefix. Extra history files are
counted, never opened/decompressed as members. The whole compressed ZIP is hashed,
including their bytes. Missing expected entries, duplicate identities/names, table
or hash mismatches fail closed. Traversal, absolute/backslash/ambiguous names,
symlinks, special entries, encryption and unsupported compression are rejected.

The actual Drive JSON contains exactly `format`, `batch_id`, `source_table`,
`rows`, `sha256`, `drive_file_id`, `postgres_types`, `numeric_encoding`.
It does NOT contain its own manifest Drive ID. The checker binds the data ID to
the receipt, but cannot authenticate manifest Drive ID or ZIP provenance. No
download filename or manifest claim substitutes for a Drive API/independent check.

## Invocation and evidence boundaries

Use an existing explicit reviewed Python environment. These relative script
invocations are interfaces only, not authorization to inspect any private bundle:

```powershell
& $reviewPython -B .\archive_recovery_review.py
& $reviewPython -B .\archive_recovery_review.py --inventory "$privateInventory" --bundle "$privateZip" --confirm-read
```

Preview performs zero input reads. Confirmed mode requires absolute non-UNC,
regular single-link inputs outside the source directory; symlink/reparse ancestors
are rejected. Descriptor/path identity, size and timestamps must remain stable
through the read. This is not a hostile-filesystem sandbox or mapped-drive locality
attestation; use trusted owner-local files, not untrusted or remote environments.

Stdout contains fixed status/codes/counts and exact-input SHA-256 digests, never
batch IDs, Drive IDs, private paths, raw JSON, metadata values or exception text.
`inventory_sha256` hashes EXACT inventory bytes, not canonicalized JSON;
`bundle_sha256` hashes the entire EXACT compressed ZIP stream. Changed extra ZIP
bytes change that digest even if planned coverage is unchanged. Digests bind a
generation, not authenticity, custody, a signed receipt or a write to storage.

Success `INCIDENT_BYTES_AND_FOOTERS_MATCH_NOT_RESTORE_OR_CUSTODY` means all planned
receipt/manifest byte hashes, footer metadata, schemas and structural row counts
match. Partial counts retain the fixed 122/98,755 denominator and remain BLOCKED.
No source row values are reconstructed, compared or authenticated. In particular,
the content-derived batch ID is NOT recomputed; analytical-column equality,
unique source keys and valid `_row_json` remain unverified. Synthetic tests even
use opaque invalid row JSON to prove footer success cannot establish logical restore.

All logical-restore, independent-custody, current-DB, inventory-completeness,
manifest-ID and ZIP-provenance verification flags remain false. This does not
remediate loss by itself, restore 98,755 rows, authorize deletion, prove a Drive
generation still exists or establish historical/licensed-data admission. Separate
authorized logical restore/reconciliation and authenticated independent custody
are still necessary. No existing deletion/commissioning gate changes.

## Resource/parser limits

Inventory/each manifest: 1 MiB; each Parquet: 32 MiB; ZIP: 2 GiB; central directory:
2 MiB / 4,096 entries; declared ZIP expansion: 4 GiB; member ratio at most 200:1.
Only stored/deflated standard non-ZIP64 archives are accepted; a larger/unsupported
download requires separate review, not a relaxed or partial denominator. Expected
members are read to bounded EOF and exact declared size/CRC, without extraction.

Parquet footer length is at most 256 KiB with bounded Thrift strings/containers,
64 row groups, fixed schema/metadata, chunk location checks, at most 16 MiB declared
uncompressed per column, 128 MiB per Parquet and 512 MiB over the whole incident.
These are metadata-declared expansion bounds; no pages are decoded. PyArrow/native
parser implementation and trustworthy owner-local inputs remain assumptions, not
a hostile-file security proof. Tests use synthetic Parquet/ZIP only, never real
archived market records, DB access, Drive access or credentials.
