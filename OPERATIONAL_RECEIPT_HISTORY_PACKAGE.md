# K — Immutable operational receipt reader (offline only)

This package extends J's evidence-outbox proofs to checkpoint and terminal-run
requests. It does **not** commission the remote writer, restore anything, ACK
a delivery, permit resends, modify the schema or permit ledger pruning.

## Complete upload group

Upload after J, from a fresh branch on the resulting main:

- `operational_receipt_history.py` (new root): bounded signed-artifact encoding,
  whole-artifact read verification and indexed immutable-fence lookup.
- `tests/test_operational_receipt_history.py` (new tests/): exact older/newer
  identities, actual five-table recovery, ACK lag, missing proof, malformed and
  corrupt artifacts, signature/key/digest failures, limits and closed readers.
- `OPERATIONAL_RECEIPT_HISTORY_PACKAGE.md` (new root): this contract/runbook.

No production import or fingerprint membership changes. Existing A..J fingerprint
remains unchanged. No capture installation changes.

Local review commands (PowerShell from repository root):

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_operational_receipt_history.py tests/test_ledger_delivery_proofs.py tests/test_local_state_recovery.py -p no:cacheprovider --basetemp "$env:TEMP/operational-receipts-$([guid]::NewGuid().ToString('N'))"
.venv/Scripts/python.exe -m mypy --strict --follow-imports=silent operational_receipt_history.py tests/test_operational_receipt_history.py
.venv/Scripts/python.exe -m pyflakes operational_receipt_history.py tests/test_operational_receipt_history.py
```

## Why original immutable requests are necessary

The current remote candidate can be overwritten under a new scan fencing token;
the current run row can likewise acquire a different terminal state. Those rows
cannot prove what a previous acknowledged checkpoint/finalization actually asked
the server to commit. A trigger copying NEW row values also cannot recover the
original request: timestamps may be normalized, heartbeat NULL may mean retain
the previous finish time, and the candidate item is not currently part of its
idempotence comparison. No historical receipt may be fabricated from these rows.

This format retains original request fields and timestamp spelling, binds kind
and key ID inside every HMAC, rejects collisions even for identical duplicates,
and requires an independently retained artifact digest. Missing records return
UNAVAILABLE, never ABSENT. An old receipt reports its original token, not the
current live token; this is historical proof, **not** permission to send old work.
The entire artifact is verified before any lookup. Reads close on context exit.
Limits: 20,000 receipts, 32 MiB artifact, 2 MiB/request, bounded during encoding.
Size, nesting (32 levels) and structural token/node (1,000,000) budgets are checked
before full JSON serialization/parsing. Only strict UTF-8 is accepted; automatic UTF-16/32
detection cannot bypass the lexical budgets. Raw NUL/BOM input is rejected.
The artifact cap is smaller than the
five-table recovery cap: larger histories require a separately bounded multi-segment
receipt reader; do not increase limits or silently omit older receipts.

The present local five-table contract still requires a job's recorded finalized
token to equal its current token. K does NOT make an older terminal-finalization
token recoverable after a local takeover; an integration test requires that case
to remain blocked. Future local intent/history support must preserve the original
terminal request rather than loosening this equality check.

## Remaining writer/provenance gate — do not skip

`seal_receipts` authenticates supplied bytes, not the truth of a database commit.
It exists for deterministic synthetic fixtures and already proven original
receipts. The adapter must not be wired into real recovery until ALL are proven:

1. An explicitly reviewed remote writer inserts the exact original request and
   receipt atomically in the SAME operational SQL transaction, under the SAME
   active run-row lock/fence. Receipt failure rolls back the operational write.
2. Same receipt identity accepts only identical original request; conflicting
   item/timestamp/finalization requests reject. New ownership cannot mutate old
   receipt records. A pre-commission legacy row cannot initialize missing proof.
3. Unknown commit outcome remains reconcile-before-retry, not a guessed failure.
4. Restricted-role permissions, immutability, retention/cold lookup, capacity
   admission and native PostgreSQL multi-connection race tests pass. PGlite or
   stubbed transactions alone cannot certify real lock ownership/races.
5. Original key coverage, independent checkpoint custody, remote readback and
   independent encrypted replica are verified under the existing backup contract.

PostgreSQL executes trigger effects in the triggering transaction; trigger or
statement failure rolls back both. That property is useful but does not recover
original client intent by itself. [PostgreSQL 17 trigger documentation](https://www.postgresql.org/docs/17/trigger-definition.html).

No owner SQL or hosted action is authorised by this package. Keep release/capture/
collector holds unchanged. This closes a tested reader-contract gap; atomic
writer integration and end-to-end permanent-storage commissioning remain open.
