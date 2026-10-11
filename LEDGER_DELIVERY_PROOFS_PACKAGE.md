# Group J — original evidence receipts for local outbox recovery

Three NEW destinations, upload AFTER I:

- ROOT `ledger_delivery_proofs.py`
- `tests/test_ledger_delivery_proofs.py`
- ROOT `LEDGER_DELIVERY_PROOFS_PACKAGE.md`

Final Group D1 source/test also add an indexed, detached retry lookup. Group F
uses it instead of scanning every event for each pending retry, and preserves
caller errors when source contexts suppress or replace them. Upload FINAL files.

```powershell
python -m pytest -q tests/test_ledger_delivery_proofs.py tests/test_local_state_recovery.py tests/test_ledger_history_stream.py tests/test_ledger_history_consumers.py -p no:cacheprovider --basetemp "$env:TEMP/delivery-proof-review-$([guid]::NewGuid().ToString('N'))" --tb=short
python -m pyflakes ledger_delivery_proofs.py tests/test_ledger_delivery_proofs.py
python -m mypy --strict --follow-imports=silent ledger_delivery_proofs.py tests/test_ledger_delivery_proofs.py
```

No dependencies, credentials, source data, hosted settings or installed capture
changes. NOT called by live factories or delivery senders. No dashboard fingerprint
change beyond the separately reviewed Group I candidate.

## What this proves

evidence_receipts(explicit_consumers) pins ONE complete original-history cut.
lookup(retry) returns exact original request fields or that cut's verified absence.
The unique retry index avoids quadratic rescans. Unknown keys, changed final fences,
corrupt bytes, unsigned history, invalid identity and closed spools fail:
unavailable NEVER becomes absent.

Tests exercise the ACTUAL five-table local recovery verifier with synthetic local
outbox records and independently staged remote originals. Remote commit without
local ACK is recognized without sending or acknowledging. Nested payloads are
detached and source bytes unchanged.

Empty complete history establishes absence only through the protected source
contract, never an arbitrary callback/current hot row. Receipts are historical at
the pinned cut, not future append locks. Any later resend still needs commissioned
global idempotency/root/head fences.

## Still held

Only the EVIDENCE callback for local_state_recovery.verify is supplied. Checkpoint
and scan-finalization receipts require independent authenticated history preserving
the ORIGINAL fencing token. Current-row-only readers cannot prove overwritten
older fences. Never invent ABSENT callbacks in real recovery; tests use explicitly
synthetic callbacks and do not commission them.

Whole-application freeze/restore, cross-file cache/catalog consistency, native SQL
race/role tests, independent encrypted replicas/custody, cold-aware append and live
factories remain unfinished. No receipt authorizes retention, deletion, resend,
local ACK, source overwrite or production evidence upgrades.

No owner steps are needed to upload this inactive library. Actual recovery must
use the independently retained source witness and commissioned source/receipt
adapters. Missing adapters remain blockers, not bypasses.
