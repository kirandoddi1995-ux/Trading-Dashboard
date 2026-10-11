# L — Local finalization intent journal (inactive)

Upload AFTER K. This package preserves original terminal-run requests in a new
local SQLite journal, independently of the mutable current job. It does not
install a sender, open a real state file, perform network calls, configure keys,
change the five-table recovery contract, or authorize restoration/deletion.

## Complete files

- `finalization_intents.py` — new root module. Explicit caller-transaction-only
  initialization/queue/ACK; bounded pending reads and retained old-token intents.
- `tests/test_finalization_intents.py` — new tests/ module. Synthetic SQLite
  transaction rollback, idempotence, takeover, wrong/missing proof, corruption,
  capacity/time/batch bounds and pre-fetch rejection of oversized rows.
- `FINALIZATION_INTENTS_PACKAGE.md` — this new root runbook.

K's complete files are revised to export `request_identity` and budgeted canonical
`decode_request`/`decode_object`, with additional regression cases. Upload the FINAL K
versions before L; do not use earlier K files. No production import/fingerprint
membership or installed-capture changes in K/L.

Commands (PowerShell, repository root):

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_finalization_intents.py tests/test_operational_receipt_history.py tests/test_ledger_delivery_proofs.py tests/test_local_state_recovery.py -p no:cacheprovider --basetemp "$env:TEMP/finalization-review-$([guid]::NewGuid().ToString('N'))"
.venv/Scripts/python.exe -m mypy --strict --follow-imports=silent finalization_intents.py tests/test_finalization_intents.py operational_receipt_history.py tests/test_operational_receipt_history.py
.venv/Scripts/python.exe -m pyflakes finalization_intents.py tests/test_finalization_intents.py operational_receipt_history.py tests/test_operational_receipt_history.py
```

## What is actually implemented

`initialize` is explicit, requires an already-open transaction and existing job/
checkpoint tables, and fails if the journal already exists. Nothing calls it at
startup. It never discovers paths or recreates a missing source database.

`queue_terminal` validates the current local token, terminal status and exact
original error/finish request. Every current-token checkpoint must be delivered.
Same identity requires exact request bytes. New ownership has a separate identity;
old records are never replaced by this API. Queue and the local job's terminal
change must share the caller's transaction. No function commits or rolls back it.

`acknowledge` requires PRESENT, matching original request and matching historical
token from the separately authenticated remote adapter. It validates before
writing. An ACK for an older retained intent never marks the newer job finalized.
A repeated ACK checks the retained request digest; missing proof fails closed.
The digest is request identity, NOT a new signature or independent custody proof.

Logical cap: 20,000 intents and 32 MiB canonical request bytes. Requests are at
most 4 KiB; pending batches at most 50. Capacity blocks new intents while retaining
old ones; identical retries do not consume a new slot. Oversized stored requests
are replaced with NULL by the SQL SELECT before Python fetch, then rejected.
Decoded run/token identities must match the journal primary key; a valid receipt
for another run cannot be substituted. Job summaries are capped at 64 KiB before
fetch and reject duplicate keys, deep/wide structures and nonfinite constants or
overflowing numeric exponents, including unused nested metadata.
These are logical bounds, NOT SQLite heap/index allocator or power-loss proofs.
No implicit retention/pruning is implemented. A full journal requires separately
commissioned authenticated archive/recovery or additional capacity, not deletion.

## Still required before owner installation or live wiring

1. Extend the coherent application cut and restored identity to include this
   SIXTH local table. The old five-table witness does not verify it; ordinary
   whole-image backup bytes preserve it but do not certify its delivery semantics.
2. Reconcile immutable operational receipts against the original journal and the
   current local state; preserve uncertain commits and old ACK lag. Do not simply
   loosen `remote_finalized_token == current token` in the old verifier.
3. Wire the sender to queue original intent before network delivery and reconcile
   exact receipts before ACK. Remote heartbeat TRUE alone is insufficient proof.
4. Commission K's remote SAME-transaction immutable writer, signing/custody,
   restricted roles, retention, capacity and native multi-connection race tests.
5. Rehearse stop/back up/install/restore with a disposable source and exact public
   release package, including all local writers and recovery-takeover boundaries.

No owner action is needed now. Do NOT run initialization against real state, copy
these files to the installed capture, promote the release, or modify hosted SQL.
This is tested offline engineering, not a complete permanent-storage solution.
