# Package 2A — offline, consistent five-table recovery proof

## Decision and current boundary

Owner reports Package 1 merged as e9067cf, quality/resilience/CodeQL green.
Read-only public tree lookup confirmed exact commit
e9067cf6178ca2e65522ec32b09dae71ab5c46cd (378 entries, not truncated).
The one project import, evidence_ledger.py, matches main's Git blob
f0c1beb1478cce5d282766f18647361735346c4d. No hosted changes, private data reads,
2025/2026 examination, capture-folder edits or GitHub writes occurred.

This is a complete reviewable OFFLINE proof package, not completion or activation
of all Package 2 commissioning work. No live factory imports it. The existing
local_ledger_recovery.py draft and runtime files are not uploaded in this group.
Scan-only recurrence, 24 MB admission, the other collector modes/F&O/release holds
and the supervised owner-file capture plan remain unchanged. No fresh DB size
measurement was performed during this implementation.

## What is implemented

local_state_recovery.py reads these five local SQLite tables in one SELECT-only
snapshot: evidence_ledger_events, evidence_delivery_outbox, durable_scan_jobs,
durable_scan_candidates and checkpoint_outbox. It does not initialize schema.
Original HMACs and aggregate chains are checked with explicit historical keys;
unsigned or missing-key history cannot certify authenticated recovery.

Rows and identities are spooled to an ephemeral local SQLite database, not held
in an event-sized Python list/dictionary. Bounds: 1,000,000 total rows, 512 MiB
encoded state/spool capacity, 2 MiB encoded row, 64 KiB schema, 30-second source
snapshot. These are OFFLINE proof limits, not Supabase budgets or enlarged feed
capture limits. Limits fail explicitly; no prefix is accepted as complete.
SQLite caches are bounded and temporary storage is file-backed. A private existing
spool directory with adequate disk space/ACLs must be supplied explicitly.
No production CLI or scheduling is provided and no owner live invocation is
requested. The library's spool is temporary, not a surviving backup/export.

The source connection closes before detached remote-receipt checks. A witness
covers schema (including indexes/triggers), all five ordered record sets,
original items/results, delivery attempts/errors/times/ACKs, fences and finalization
markers. Retain the source witness independently BEFORE restore; generating a
witness from the restored target does not establish the missing source state.
Witness hashes establish equality, not independent authenticity by themselves.
The proof re-hashes its detached spool before use so post-capture changes cannot
quietly pass with the old witness.

Strict delivery scope: every original needs a matching equity outbox intent and
every completed candidate needs its checkpoint intent. A missing queue entry is
not interpreted as local-only or already acknowledged. Legacy/local-only intent
requires a separately reviewed adapter; it is blocked, never invented.
The proof checks candidate/job completeness, queue identity/request equality,
aware timestamps, valid fences, pending conflict quarantine, and finalization.

Injected remote adapters must independently authenticate PRESENT or ABSENT.
UNAVAILABLE, None, booleans, generic dictionaries and exceptions are not absence.
Local and remote HMAC envelopes are not spliced: the complete original request,
including effective_at, is compared. A remote commit before local ACK is reported
without sending or acknowledging anything. ACK without its remote receipt fails.
Pending old fences fail; historical finalized fences require a later history-aware
adapter rather than pretending the current run state describes the old receipt.

The receipts are an adapter contract, not cryptographic verification supplied by
this library. No hosted adapter is installed yet. Result always carries
application_recovery_verified=false and approval_authority=false, even on PASS.
Other app tables, PostgreSQL recovery, Drive roots, signing-key custody and
end-to-end application restoration are outside this five-table local proof.

ledger_key_availability.py is a separate owner-only presence checker: offline
preview, hidden explicit private TOML path, stable errors, no values/paths/key
hashes/network/output files. It checks existence of the exact key name, not
historical authenticity. OWNER_KEYS_AND_BACKUP_RUNBOOK.md explains the boundary.

## Exact upload group — 8 complete files

All paths below are under C:\Users\banga\Desktop\kiran_share_market.
Use ONE review branch/PR, preserving root versus tests/; no whole-folder upload.

ROOT (6):

- [local_state_recovery.py](C:/Users/banga/Desktop/kiran_share_market/local_state_recovery.py) — NEW offline spooled proof and typed receipt/witness contract.
- [ledger_key_availability.py](C:/Users/banga/Desktop/kiran_share_market/ledger_key_availability.py) — NEW owner-only secret-name presence checker.
- [LOCAL_STATE_RECOVERY_PACKAGE.md](C:/Users/banga/Desktop/kiran_share_market/LOCAL_STATE_RECOVERY_PACKAGE.md) — NEW scope, review commands and exact upload group.
- [OWNER_KEYS_AND_BACKUP_RUNBOOK.md](C:/Users/banga/Desktop/kiran_share_market/OWNER_KEYS_AND_BACKUP_RUNBOOK.md) — NEW safe owner key/encrypted USB/retention steps.
- [PERMANENT_STORAGE_PACKAGES.md](C:/Users/banga/Desktop/kiran_share_market/PERMANENT_STORAGE_PACKAGES.md) — UPDATED Package 1 merged and Package 2A/remaining gates.
- [AUTOMATION_PROGRESS.md](C:/Users/banga/Desktop/kiran_share_market/AUTOMATION_PROGRESS.md) — UPDATED continuity and verification record.

tests/ (2):

- [tests/test_local_state_recovery.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_local_state_recovery.py) — NEW synthetic source/restore, concurrency, HMAC/key, queue/fence, limits and receipt failure cases.
- [tests/test_ledger_key_availability.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_ledger_key_availability.py) — NEW synthetic presence-only/format/path/link/preview/redaction tests.

Do not upload ledger_recovery.py, local_ledger_recovery.py, recovery_drill.py,
production_repository.py, equity_runtime_health.py, SQL drafts or unrelated tests.
No workflow/migration/configuration/dependency files join this group.
The Package 1 inventory baseline remains deliberately pinned to 62508fd;
it is not a current-main inventory or deployment certificate. Its import check
can still check this explicit group because evidence_ledger.py is unchanged;
exact current-main CI/rehearsal remains necessary.

## Local commands before upload

From C:\Users\banga\Desktop\kiran_share_market:

```powershell
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_local_state_recovery.py tests/test_ledger_key_availability.py --basetemp "$env:TEMP/storage-p2-$([guid]::NewGuid().ToString('N'))" --tb=short
.venv/Scripts/python.exe -m pyflakes local_state_recovery.py ledger_key_availability.py tests/test_local_state_recovery.py tests/test_ledger_key_availability.py
.venv/Scripts/python.exe -m mypy --strict --follow-imports=silent local_state_recovery.py ledger_key_availability.py
.venv/Scripts/python.exe storage_package_inventory.py --check-package local_state_recovery.py ledger_key_availability.py LOCAL_STATE_RECOVERY_PACKAGE.md OWNER_KEYS_AND_BACKUP_RUNBOOK.md PERMANENT_STORAGE_PACKAGES.md AUTOMATION_PROGRESS.md tests/test_local_state_recovery.py tests/test_ledger_key_availability.py
.venv/Scripts/python.exe ledger_key_availability.py
```

Expect tests green, lint/type checks clean, package blockers empty and presence
checker PREVIEW reads/writes/network 0. No actual private key-file check has been
performed by the agent; only synthetic fixtures were read. Validate this group
again in a clean exact-main clone and require quality/resilience/CodeQL on the
complete PR and resulting merge SHA. Merge outside active collector/archive runs.
Do not promote release, apply SQL, change secrets, run a recovery tool on live
state or overwrite the installed capture folder. Main's release source manifest
does not include these modules; no equity fingerprint expectation update is needed.

## What comes immediately after 2A

Package 2B fixes/tests explicit effective_at retry mismatch and omitted-time retry
semantics, with atomic delivery intent and crash-boundary tests. That changes
live ledger code and requires its own hash/release/main-writer deployment review;
do not upload a whole draft runtime repository to patch one defect.
Define historical/legacy delivery policy and consistent source-witness signing,
durable export/restore (this ephemeral spool is not one), and cross-file backup
coordination where state lives in different files. Keep source identity/provenance
separate from target equality. The eventual independent remote adapters must be
tested against a disposable database, not only a mocked receipt.

Package 3 connects every historical reader and factory with original/historical
keys, authenticated cold roots, bounded streaming and fail-closed absence checks.
Package 4 installs only reviewed additive disabled prerequisites, then owner
root/bootstrap/export-only/tiny-trial/independent-restore commissioning. Package 5
normalizes PIT universe payloads and covers every non-ledger source/metadata.
Package 6 proves all-writer capacity and independent alerts under the full intended
workload. Main collectors must not receive incompatible runtime code before
their database prerequisites; holding Streamlit promotion is not protection for main.

## Verification record

Final focused: 99 passed in 7.17s; presence-only final subset 22 passed in 0.18s.
Strict mypy clean for two new modules; pyflakes clean. Both new modules import
offline without app/runtime-factory imports; package dependency blockers are empty.
Final full local suite: 2505 passed, 4 skipped, 2 subtests passed in 503.39s.
Manual final self-review fixed completeness, indexed lookup, bounded metadata,
exception/argument redaction and independent cleanup issues; regressions pass.
The full local suite includes unuploaded drafts, so exact complete-PR/main CI is
still required. No live app boot or hosted recovery commissioning is claimed.
No existing tests removed or safety gates weakened.
