# Permanent storage implementation — reviewed packages, not one large upload

## Current handoff: 2B2A merged; 2B2B offline export/local checkpoint

Exact merged main: ed951e2c36ecb5dd6755cf781c72a40b7454bf0d; read-only checks
confirm quality, resilience and CodeQL successful. RECOVERY_EXPORT_PACKAGE.md
defines the new six-path group: consistent single-SQLite export, original-key
verification and separate local checkpoint CAS/readback/uncertain-response retry.
Multi-file inventories fail closed; local separate paths are not independent-device
custody. No real export, encrypted replica, persistent proposal reload, cross-file
barrier, runtime activation or hot deletion is commissioned. These remain next,
before legacy intent/remote retries and every-reader wiring. Owner key preservation,
older-key checks and dummy disk encryption rehearsal proceed in parallel now.

## Historical handoff: 2B1 merged; 2B2A authenticated identities

Owner reports PR8/main b213ec87b11ee4c50b197110c6d26e1105a633c0 green,
160 focused clean-clone tests and full PR CI. No fingerprint/hosted setting changed.
RECOVERY_BUNDLE_PACKAGE.md defines the next exact seven-file group: offline
authenticated source-witness/component bindings, not a persistent backup.
It reuses catalog receipt authentication and requires an independent reviewed
inventory/checkpoint. Signed proposed checkpoints do not establish durable custody.
Actual consistent export, cross-file freeze and independently retained encrypted
replicas/checkpoints are the next subpackage, before legacy intent/remote retry
and every-reader/factory work. No migration, runtime activation or deletion yet.
Current private key backup, older-key coverage and harmless disk encryption
rehearsal remain owner steps; they block commissioning, not synthetic coding.

## Historical review handoff after Package 2A merge

Update after owner Package 2A merge: exact public main is
56c5508566a5ff700c2411d68617d8f0566193c4. Owner reports green status checks and
99 focused tests. Package 2B is split: LOCAL_LEDGER_RETRY_PACKAGE.md defines a
seven-file 2B1 retry-identity fix with its candidate fingerprint. It does not ship
unfinished remote/factory changes or claim whole-application recovery. Remaining
2B work is authenticated backup/witness custody, cross-file identity, legacy
delivery intent and remote retry semantics. Key names exist, but current private
backup/historical coverage and USB encryption/restore remain unverified.

Owner reports Package 1 merged at e9067cf with exact-merge quality/resilience/CodeQL
green and promotion held. Package 1 below is historical and must not be uploaded
again as a new group. Package 2A's exact eight-file offline upload group is in
LOCAL_STATE_RECOVERY_PACKAGE.md; key/USB owner instructions are in
OWNER_KEYS_AND_BACKUP_RUNBOOK.md. The USB is available, not yet commissioned.
The five-table spooled recovery proof is implemented offline; legacy intent,
explicit effective_at retry semantics, trusted witness/export custody and live
remote/history-aware adapters remain Package 2B/3 work. No live activation occurs.
The earlier 62508fd inventory baseline stays pinned, not silently rewritten.

## Decision in plain language

Start by making the unfinished work auditable, then land the offline building
blocks. Next prove recovery and exact history reading before connecting them to
the running app. Only after that may the owner commission ledger archival.
Universe deduplication and complete non-ledger retention follow; all-writer limits,
independent alerts and measured steady-state acceptance finish the system.
History remains available for analysis/ML in verified private files. This is not
a plan to discard evidence or tune the parked rules.

The source of truth is the local folder, but it is NOT identical to main. Main
was initially inventoried at 62508fd50f6d1e363afabc8961857c98afcd5c05; current main
is now the exact ed951e2 SHA above. Local sources include
unuploaded runtime changes and SQL drafts. Do not upload by folder selection.
PERMANENT_STORAGE_LOCAL_INVENTORY.md lists the differences and their stages.

Current owner-reported allocation is 456,260,405 bytes, with 43,739,595 bytes
nominal headroom. Two measured scans grew by 671,744 and 704,512 bytes. Those
figures justify only the current scan-only restart; they do not bound all writers
or prove permanent capacity. Keep the unchanged 24 MB transitional admission,
other four modes/F&O/release holds and normal verified archival. Do not reduce
evidence sampling, lower gates or pause working capture to accommodate drafts.

## Package 1: P0 inventory + P1 offline originals/catalog (ready for review)

Deliverable: executable source comparison and missing-companion checks, plus the
existing four pure original-event/catalog libraries and four offline test files.
Their original-key verification, byte limits, immutable pages and exact cold/hot
reconstruction can be reviewed without enabling a hosted reader or deletion.
They remain unimported by the current live factories. No app/runtime replacement,
SQL migration, workflow or secret change is included.

Complete upload group: 14 files. Paths are relative to
C:\Users\banga\Desktop\kiran_share_market; preserve ROOT versus tests/.

ROOT (9):

- storage_package_inventory.py — NEW offline inventory/package validator.
- STORAGE_MAIN_BASELINE_2026-10-07.json — NEW pinned public path/blob metadata.
- PERMANENT_STORAGE_LOCAL_INVENTORY.md — NEW stage-by-stage inventory.
- PERMANENT_STORAGE_PACKAGES.md — NEW package/gate/owner instructions, this file.
- AUTOMATION_PROGRESS.md — UPDATED continuity record.
- ledger_segments.py — EXISTING local-only pure sealed-original verification;
  two redundant casts removed and oversized row counts rejected before parsing.
- cold_catalog.py — EXISTING local-only immutable paged identity/frontier lookup.
- catalog_receipts.py — EXISTING local-only signed root/rotation receipt checks.
- ledger_cold_store.py — EXISTING local-only preparation and exact merged reading.

tests/ (5):

- tests/test_storage_package_inventory.py — NEW inventory/dependency/failure and
  isolated-core-import tests.
- tests/test_ledger_segments.py — EXISTING synthetic originals/signature/limit tests,
  plus the early oversized-input rejection regression.
- tests/test_cold_catalog.py — EXISTING authenticated page/absence/corruption tests.
- tests/test_catalog_receipts.py — EXISTING root/receipt/generation/rotation tests.
- tests/test_ledger_cold_store.py — EXISTING cold/hot identity/boundary/retry tests.

Do not include tests/test_ledger_segments_sql.py or any other SQL-harness storage
test in this first group: they require the held migrations and additional code.
Do not include modified production_repository.py, equity_runtime_health.py,
recovery_drill.py, release_verification.py or mypy-automation.ini yet.

Local review commands from the development root:

```powershell
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_storage_package_inventory.py tests/test_ledger_segments.py tests/test_cold_catalog.py tests/test_catalog_receipts.py tests/test_ledger_cold_store.py --basetemp "$env:TEMP/storage-p1-$([guid]::NewGuid().ToString('N'))" --tb=short
.venv/Scripts/python.exe storage_package_inventory.py --check-package storage_package_inventory.py STORAGE_MAIN_BASELINE_2026-10-07.json PERMANENT_STORAGE_LOCAL_INVENTORY.md PERMANENT_STORAGE_PACKAGES.md AUTOMATION_PROGRESS.md ledger_segments.py cold_catalog.py catalog_receipts.py ledger_cold_store.py tests/test_storage_package_inventory.py tests/test_ledger_segments.py tests/test_cold_catalog.py tests/test_catalog_receipts.py tests/test_ledger_cold_store.py
```

Require PACKAGE_CHECK_PASSED_REQUIRES_REHEARSAL with no blockers. The check rejects
new/changed local import dependencies omitted from the package, rather than
assuming main has the local folder's versions. It does not verify every dynamic
resource, third-party dependency, runtime compatibility or receipt authenticity.
Tests/isolated rehearsal and exact-SHA CI remain required; its approval_authority
is always false. The tool does no network/write/secret loading or app imports.

Owner creates one review branch/PR with these complete files, checks folder
placement, waits for quality/resilience/CodeQL for the exact complete PR SHA,
merges outside active collector/archive runs, then verifies resulting main SHA.
Do not enable dashboard promotion or apply migrations. No equity fingerprint input
changes in this first group; no EXPECTED_EQUITY_CODE_SHA256 update is needed.
The isolated PC capture installation is separate and must not be overwritten.

## Package 2: offline whole-local recovery proof (next implementation)

Extend the existing narrow local_ledger_recovery.py proof with checkpoint state:
durable_scan_jobs, durable_scan_candidates and checkpoint_outbox, including
fences, original items/results, pending/acknowledged/conflicted deliveries and
finalization markers. Use a bounded consistent SELECT-only snapshot and a trusted
source witness taken before restore. Do not take a target's own witness as proof
that missing source state never existed. Add bounded spooling for larger histories.

Prove crashes before/after remote commit/ACK, missing/orphan delivery intent,
changed requests, stale fences, quarantined conflicts and missing checkpoint rows.
Keep local and remote HMAC envelopes separate. Remote lookup must establish both
authenticated presence and authenticated absence; an unavailable object is NOT
absence. The eventual adapter belongs to Package 3.

Source audit found that current duplicate checks in local append and the local
draft remote append omit effective_at, while the recovery request comparison
includes it. Test and correct explicit timestamp mismatch semantics before
commissioning retries; account for callers that omit effective_at on a retry.
Do not upload the whole draft remote repository just to fix that one issue.
The legacy append/send/queue-after-failure path has a crash window and needs an
explicit delivery-intent contract. An original with no outbox row is not proof
that no remote delivery was intended.

Exit gate: original source/restore witnesses match; every required local delivery
and checkpoint identity is covered; damaged/unavailable state fails explicitly.
Offline proofs still report application_recovery_verified=false until the entire
application/remote dependency contract is commissioned. No automatic repair or send.

## Package 3: complete historical readers, retry-safe writers and factory plan

Finish LedgerRuntimeReader/storage access and private object/key/root adapters;
route all actual readers: events, global audit, pending observations, matured
decision dataset, decision/outcome reconciliation, recovery and ML joins. Add
bounded history streaming/spooling, not an ever-growing in-memory list.

Factories currently inject neither cold reader nor complete historical key ring.
Do not claim optional constructor support is live wiring. Add source/target-bound
adapter tests, exact as-of/availability semantics and no hot-only fallback when
catalog generations show archived history. Verify preserved IDs, effective times,
payloads, original signatures and retries across an archive boundary.

Exit gate: restored private synthetic/disposable whole application reads the same
original witness/datasets; missing cold objects/keys/roots block, never yield an
apparently valid empty training set. Resolve and test every reader/writer entry
point, not only events(). 2025/2026 holdout data remains unexamined.

IMPORTANT: build order is not hosted activation order. New live reader/factory
code cannot reach main's collectors before its reviewed additive schema/role/root
prerequisites are installed and verified. Prepare an inactive-compatible version
or hold that upload until the owner prerequisite sequence is ready. Release being
held does not protect collectors that run main.

## Package 4: archive publication, atomic commit and owner commissioning

Finish private Drive upload/download verification, original keys and signed root
receipts, protected hot heads, exact captured-source deletion with atomic root
advancement, generation fencing and archived-idempotency handling. No network
request while holding database write locks. Independent root checkpoints and a
second private copy must detect rollback/loss, not just byte corruption.

Three existing migrations remain review/test drafts. Do not apply them as-is or
put them in an automatic migration path. Re-review schema/security/contracts when
Package 3 is settled. Real independent disposable PostgreSQL connections must
exercise append/archive/root races; SQL emulation alone is insufficient.

Owner sequence, after gates pass: private survivor backup and restore proof ->
fresh read-only prechecks -> separately reviewed additive disabled schema/roles ->
verify grants/guard defaults -> install compatible readers/adapters -> exact-SHA
checks/owner configuration -> authenticated root bootstrap -> preview/export-only
-> reviewed tiny deletion trial -> invariants/restore -> bounded expansion.
Exact SQL, roles and click-by-click steps are written at that point, not guessed
now. Failures at every publication/commit/ACK boundary must have safe retry receipts.

## Package 5: universe normalization and all non-ledger sources

Store identical instrument payloads once while preserving immutable snapshot and
version membership, genuine source changes and PIT identity. Shadow old/new reads
and require exact fingerprint equivalence before removing overlap.

Add cold-aware daily-volume, quotes, scanner, outcomes and control/metadata
retention. Preserve required completed-session lookbacks and active/recovery
references. Completed outcomes must remain exactly accessible after leaving hot
storage. Bulk bars/depth/option history stays in private files. Contracts cover
writers AND historical readers, including training joins and archive metadata.
Each source has its own schema/key/restore/preview/trial acceptance, not generic
DELETE. Compaction, if needed once after retention, remains a separate reviewed
physical-capacity/backup/lock decision. No recurring compaction is the design.

## Package 6: every-writer admission, alerts and steady-state acceptance

Enforce measured heap/index/TOAST budgets with bounded real write batches and
concurrency-aware admission across dashboard, all collector modes, research,
archive metadata and monitoring. The current check outside a transaction is not
a reservation. Prove protected working sets fit the proposed 308 MB target before
activating the future thresholds. Do not lower a threshold to make it pass.

Independent missed-collection/archive and capacity alerts must still notify when
the DB is read-only or a producer never starts. Owner sets up any required alert
accounts/settings from a reviewed runbook; the agent creates none.

Exit gate: ten complete consecutive regular-session cycles of the intended full
workload, peaks below 350 MB, no growing archive/delivery backlog, physical budgets
met, analytical worst-case working-set bound, second-copy whole-app restore and
identical frozen ML dataset hashes. Ten days alone does not prove indefinite
boundedness. Only then expand remaining collection modes and F&O one at a time.

## What is needed from the owner

Now: review the six-file Package 2B2B group; Packages 1, 2A, 2B1 and 2B2A are merged.
Preserve the current isolated capture/scan-only setup. No hosted action is required
for 2B2B. Continue existing storage/archive
observations; notify a guard failure or unexpected growth without changing limits.

Before Package 3/4: confirm privately whether the original legacy and historical
signing keys still exist (availability only, never values in chat/logs/repo).
Unavailable legacy keys protect the affected history; no fabricated replacement.
Agree the second private backup destination and permitted licence retention;
check archive-worker and runtime historical-reader access separately. Drive folder
capacity alone does not establish licence permission or rollback protection.

The agent can continue offline Packages 2/3 without asking you to pick low-level
implementation details. Owner writes, credential provisioning and commissioning
wait for explicit reviewed steps. No package is allowed to trade away evidence,
weaken a safety gate, place orders or retune research rules.

## Validation record

Final focused suite: 116 passed in 13.17s. Final full suite: 2406 passed,
4 skipped, 2 subtests passed in 578.92s. Pyflakes is clean; strict mypy passes
for the inventory tool and four core libraries (five modules). Final manual
self-review fixed early oversized-input rejection and removed redundant casts;
its failure-path regression passes. The package dependency check has no blockers.
The full local suite includes unuploaded drafts; it is
not equivalent to CI for this 14-file package on main. The isolated import test
uses only the four pure libraries and main-matching evidence_ledger.py, without
the unfinished production repository. Exact uploaded-SHA CI remains an owner gate.
