# Upload 3 — exact-cut daily-volume cold reader (inactive)

## What this finishes, in plain language

A real source-specific decoder and calculation over authenticated original
snapshot bytes replaces the need to pretend an archived SQL query result is a
reader. It restores the original three daily-volume columns, verifies the whole
declared catalog cut and every requested replica, and computes prior captured
date averages. It does not connect to Postgres or replace any live factory.

The original table has no row availability/revision timestamp. **Only a query at
the declared snapshot's known_at instant is supported.** Earlier or later queries
fail, rather than inventing what the database knew at a historical decision.
This is a source-cut recovery/calculation, not admitted historical research data.

No complete SQL export, physical independent custody, native SQL numerical parity,
global wiring, exchange-final volume, historical PIT or deletion is certified.
Every such flag remains false. Catalog signatures authenticate a declaration and
exact original object set; they do not prove that an exporter collected every
database row. Empty or short histories are never extended with invented sessions.

## Exact upload order and paths

Keep the first two overnight groups unchanged. Upload and merge future operations
(10 paths), then application (17 paths), requiring each exact merged main green.
Only then branch from the newest green main for this separate six-file group.
Original public baseline: da4a9be7d5b3e805c76cc7c677795d6eebd33a36.
The new checker reuses the exact pinned common guard from Upload 1 and pins the
actual production-reader source, three-column SQL schema and full import closure.
Later incompatible main changes BLOCK the package; never remove a failing pin.

Source root: `C:/Users/banga/Desktop/kiran_share_market/`.
Copy only the following to the same relative paths in your clean clone:

| Source relative to root | Destination relative to clone |
| --- | --- |
| storage_daily_volume_reader.py | storage_daily_volume_reader.py |
| tests/test_storage_daily_volume_reader.py | tests/test_storage_daily_volume_reader.py |
| daily_volume_upload_check.py | daily_volume_upload_check.py |
| tests/test_daily_volume_upload_check.py | tests/test_daily_volume_upload_check.py |
| DAILY_VOLUME_READER_UPLOAD_2026-10-14.md | DAILY_VOLUME_READER_UPLOAD_2026-10-14.md |
| DAILY_VOLUME_READER_UPLOAD_2026-10-14.json | DAILY_VOLUME_READER_UPLOAD_2026-10-14.json |

Use the existing approved test environment and clean-clone PR routine. Set
`core.autocrlf false` before checkout, preserve the exact approved policy bytes,
stage exactly the six files and leave nothing untracked/unstaged. Do not copy the
unfinished workspace or installed capture. From the clone root:

```powershell
$volumeReviewBase = (git rev-parse HEAD).Trim()
python daily_volume_upload_check.py --base $volumeReviewBase
if ($LASTEXITCODE -ne 0) { throw 'STOP: exact daily-volume package failed' }
python -m pytest -q tests/test_storage_daily_volume_reader.py tests/test_daily_volume_upload_check.py
if ($LASTEXITCODE -ne 0) { throw 'STOP: daily-volume focused tests failed' }
```

Require PR checks and exact post-merge main green. Safe to upload during the
separate frozen capture: yes. Do not install into that capsule. No production
source, existing checker, migration, workflow or release expectation changes.
This group does not change the previously reported candidate equity fingerprint.

## Reader contract and failure behavior

`DailyVolumeRow`, `DailyVolumeSnapshot`, `encode_snapshot`, `decode_snapshot`,
`restore_witness`, `cut_declaration`, and `recover_prior_average_volumes` are
explicit library APIs. There is no default private-path/credential discovery.
The caller supplies original keys, independently pinned catalog anchors, bounded
page/replica adapters and exact candidates. Never infer anchors from recovered
targets. Catalog declaration binds the entire candidate set; no subset shortcut.

Limits: 64 KiB/object, 400 rows/object, 16 declared objects, 1,600 rows/whole cut,
128 keys, 400-date lookback, 512 catalog pages. These are engineering read limits,
not certified physical allocation or adequate whole-database coverage. Over-limit
cuts block; the code does not truncate the originals to fit. NUMERIC values retain
exact decimal text; malformed/NULL/boolean/nonfinite data blocks. Finite signed
and zero values retain the existing reader's arithmetic semantics, while final
nonpositive averages are omitted; this is not a data-quality approval.

Only dates strictly before the cut's IST date participate, most recent first per
instrument. The count is captured dates, not calendar days or verified exchange
sessions. Missing holidays/gaps are not filled. Conflicting or repeated primary
keys across objects block. A supplied hot cut must cover the whole declared
object set and match exact originals, not merely give numerically similar rows.
Every supplied tier must pass; one corrupt/missing copy blocks the result.
No second GET is used to obtain result rows after verification.

## Decisions grounded in primary documentation

The future SQL exporter needs one stable source transaction: ordinary Read
Committed permits successive statements to see different cuts; Repeatable Read
gives a stable snapshot, but is not itself a complete business-consistency or
custody proof. Set transaction characteristics before the first query. A read-only
transaction is not a guarantee of zero physical disk writes. No transaction or
export is run by this package. [Postgres isolation](https://www.postgresql.org/docs/17/transaction-iso.html),
[SET TRANSACTION](https://www.postgresql.org/docs/17/sql-set-transaction.html).

The existing SQL casts NUMERIC to double precision before averaging. Original
decimal values are preserved here; deterministic float normalization/fsum needs
native aggregate parity acceptance before an adapter can replace that method.
Exact NUMERIC storage and floating aggregation are different contracts.
[Postgres numeric types](https://www.postgresql.org/docs/17/datatype-numeric.html).

No network calls belong inside source locks. Advisory locks bind cooperating
transactions, not arbitrary writers. Future allocation/retention work still needs
all-writer enforcement and independent archive/restore proofs.
[Postgres advisory locks](https://www.postgresql.org/docs/17/explicit-locking.html#ADVISORY-LOCKS).
Supabase changelog reviewed 14 October: announced HTTP cipher change is not a
Postgres source-code change and this package makes no HTTP call.
[Official notice](https://supabase.com/changelog/cbc-tls-ciphers-deprecated).

## Owner actions now and later

Now: upload through the reviewed PR sequence only. No task, database command,
model, archive deletion or workflow needs enabling. Keep today's capture and
release hold unchanged. Rollback is a complete checked PR reverting these six
new files; no data/state was migrated.

Later, separately reviewed engineering must build the bounded consistent-cut SQL
exporter and authenticated object-set publisher, prove original row-count/digest
completeness and native hot/cold equality, then wire the actual factory. Signed
independent custody, restore, full dependency retention and capacity proofs are
required before pruning. Existing rows lack historical availability; it cannot
be reconstructed retrospectively by a migration or this reader.

## Final verification and independent review

Reader: 85 deterministic offline tests. Checker: 77; combined fresh-public-tree
focused run: 162 passed. Full sequential candidate: 4,360 passed, four unchanged
skips, seven subtests in 740.83 seconds. This adds 162 cases over Uploads 1/2's
4,198, with no tests dropped. Four new typed files pass strict mypy; the existing
19-file profile and full public-tree lint pass. All 31 public dependencies import
in an isolated process with credentials excluded and external I/O blocked.
The exact six staged paths, 33 prerequisite pins and whitespace check pass.

Independent reviews resolved the context-rounded Decimal magnitude cap and
private catalog/replica callback error disclosure; all transport errors now use
fixed codes. The new checker rejects unsupported dynamic-import forms before
dependency discovery and binds worktree/index bytes for every prerequisite.
The original common checker and earlier packages were not changed. Native SQL
parity and actual export/physical custody/global wiring remain unverified.
No operational commissioning follows from green tests.
