# Morning handoff — permanent storage, 8 October

## Superseded upload routine

Owner has now merged A and B. The remaining C..L are combined into one complete
storage PR after the capture/upload-tools PR. Use CONSOLIDATED_UPLOADS_2026-10-08.md
and its exact manifest/check/test lines; the thirteen separate groups below are
historical scope descriptions, not today's one-at-a-time instructions. No hosted
commissioning or release promotion is implied. Do not re-copy A/B.

## Plain-language summary

The original three groups have been extended to THIRTEEN local groups (A..L).
They now include bounded cold-history reading, original-ledger consumer adapters,
segment sealing/readback/restart tests, and tested read-only storage/retention
inventories, bounded transaction-held capacity admission and independent-watch
calculations. Added explicit read-only repository integration and indexed evidence
receipts for local recovery. Recovery/universe groundwork remain in the first groups.

This is meaningful implementation progress, NOT a permanently solved or commissioned
storage service. The app factories are unchanged. There is no permission to delete
ledger history, apply held migrations or enable F&O ingestion. No hosted resource,
credential, installed capture, task, cron, release expectation or sealed period
was changed/read. Morning's installed NSE owner-file routine remains untouched.

Public main baseline verified read-only:
9ce3af9bcf1e8a64a1e04eb5ba57c40a5080d39f (Package 2B2B merge, complete public tree).
Exact-SHA quality/resilience/CodeQL succeeded; release publication remains held.
The owner has not uploaded ANY of these overnight groups yet.

Reviewed clean-public candidate dashboard fingerprint (A..J together):
`03ad7baa68ebaad1f64b1cd3c356455e1c18cb8f23f027652de303b64b4f8478`.
This is NOT a request to change Streamlit now. Held release still uses old source.
Compare this with the exact post-merge clean clone before any supervised handover.

## Final upload order — supersedes the earlier three-group handoff

A -> B -> C -> D1 -> D2 -> E -> F -> G -> H -> I -> J -> K -> L

Start each group on a FRESH branch from main after the preceding group merges.
Upload the COMPLETE final files, not diffs. Check the PR's changed paths against
the list below, including tests/ and sql/ placement. Wait for exact-SHA quality,
resilience and CodeQL, merge, then confirm post-merge main checks. Do not upload
the working folder, staging folders, caches, private data, key files or secrets.

All paths below are relative to C:\Users\banga\Desktop\kiran_share_market.
There are 62 unique upload destinations. Only recovery_bundle.py, ledger_cold_store.py,
PERMANENT_STORAGE_PACKAGES.md, AUTOMATION_PROGRESS.md and release_verification.py
plus production_repository.py, equity_runtime_health.py and package_release.py
already exist on this public baseline; the other 54 are new public paths.
G and I are staging exceptions explained below. Each package's named runbook
states what changed and its exact focused test/lint/type commands.

### Group A — Restart and independent-copy audit (6 files)

- `recovery_bundle.py`
- `recovery_proposal.py`
- `recovery_replica_audit.py`
- `tests/test_recovery_proposal.py`
- `tests/test_recovery_replica_audit.py`
- `RECOVERY_RESTART_PACKAGE.md`

### Group B — Universe payload shadow codec (3 files)

- `universe_payloads.py`
- `tests/test_universe_payloads.py`
- `UNIVERSE_SHADOW_PACKAGE.md`

### Group C — Capacity planning and continuity (6 files)

- `storage_transition.py`
- `tests/test_storage_transition.py`
- `STORAGE_TRANSITION_PACKAGE.md`
- `OVERNIGHT_STORAGE_HANDOFF_2026-10-08.md`
- `PERMANENT_STORAGE_PACKAGES.md`
- `AUTOMATION_PROGRESS.md`

### Group D1 — Bounded original-history staging (4 files)

- `ledger_cold_store.py`
- `ledger_history_stream.py`
- `tests/test_ledger_history_stream.py`
- `COLD_HISTORY_STREAM_PACKAGE.md`

### Group D2 — Read-only cold reader and local sealing (10 files)

- `ledger_read_contract.py`
- `ledger_source_capture.py`
- `ledger_runtime_reader.py`
- `ledger_archive_publication.py`
- `cold_local_objects.py`
- `tests/test_ledger_read_contract.py`
- `tests/test_ledger_staged_reader.py`
- `tests/test_cold_local_objects.py`
- `tests/test_ledger_archive_publication.py`
- `COLD_READER_AND_SEALING_PACKAGE.md`

### Group E — Structural inventory and safe retention preview (4 files)

- `sql/storage_layout_inventory_read_only.sql`
- `sql/daily_volume_retention_read_only.sql`
- `tests/test_daily_volume_retention_preview.py`
- `STORAGE_STRUCTURAL_COMMISSIONING.md`

### Group F — Atomic historical-consumer adapters (3 files)

- `ledger_history_consumers.py`
- `tests/test_ledger_history_consumers.py`
- `COLD_CONSUMER_ADAPTER_PACKAGE.md`

### Group G — isolated Windows verification-timeout repair (3 destinations)

- ROOT release_verification.py — COMPLETE source from staged_release_timeout_fix/release_verification.py, NOT the dirty root draft.
- tests/test_release_timeout_recovery.py
- RELEASE_TIMEOUT_REPAIR_PACKAGE.md

Do NOT upload the staged_release_timeout_fix folder. In the clean clone copy its
release_verification.py to ROOT and review exactly those three PR destinations.
Candidate is public-main source plus a narrow timeout/cleanup repair and one
non-behavioural local type annotation. Held cold-release additions are excluded.
The dirty root release_verification.py is preserved and still HELD.

### Group H — Bounded write admission and independent-watch contracts (6 files)

- `storage_write_guard.py`
- `storage_capacity_watch.py`
- `tests/test_storage_write_guard.py`
- `tests/test_storage_capacity_watch.py`
- `tests/test_storage_guard_sql.py`
- `STORAGE_GUARD_AND_WATCH_PACKAGE.md`

Guard is inactive until ALL actual writer transactions are wired and accepted.
Watch evaluator sends no alerts: independent host/transport/delivery is uncommissioned.
No expiring reservations or existing collector threshold changes. Exact tests and
native PostgreSQL commissioning steps are in its runbook. Local SQL harness has no
real backend PID; it cannot prove multi-connection ownership. Production gate stays
strict. No new skips or false global-enforcement/notification-delivery badge.

### Group I — Actual optional historical repository APIs (8 destinations)

- ROOT production_repository.py — COMPLETE source from staged_historical_repository/production_repository.py, NOT the held dirty root.
- ROOT equity_runtime_health.py — COMPLETE source from staged_historical_repository/equity_runtime_health.py, NOT the held dirty root.
- ROOT package_release.py — COMPLETE source from staged_historical_repository/package_release.py, NOT the held dirty root.
- `ledger_historical_views.py`
- `ledger_historical_repository.py`
- `tests/test_ledger_historical_views.py`
- `tests/test_historical_repository_bridge.py`
- `HISTORICAL_REPOSITORY_PACKAGE.md`

Do NOT upload the staging folder. Three public-main-only candidates map to ROOT.
Default app/collector factories remain unchanged; optional mode is read-only and
rejects appends even with borrowed connections. Four actual read APIs use complete
cold-aware cuts. External PIT/cost/quote verification, training and production
eligibility stay FALSE. Raw forward returns are NOT called net/excess returns;
unknown/mismatched labels stay nullable. This changes fingerprint members and
explicit release seeds, requiring the supervised owner handover below.

### Group J — Original evidence receipts for local recovery (3 files)

- `ledger_delivery_proofs.py`
- `tests/test_ledger_delivery_proofs.py`
- `LEDGER_DELIVERY_PROOFS_PACKAGE.md`

One verified cut provides exact original requests or verified absence via the
unique retry index. Actual synthetic five-table verifier tests recognize remote
commit/local ACK lag with no resend/ACK. Missing keys/corruption/closed stages and
unsigned history fail. Checkpoint/run immutable-fence receipts remain required.
Final D1/F files include indexed retry lookup and context-error suppression fixes.

Group E contains SELECT-only owner SQL, NOT migrations. For its local test, configure
the existing disposable SQL harness exactly as CI does:

```powershell
npm ci --prefix tests/sql-harness --ignore-scripts --no-audit --no-fund
$env:EQUITY_TEST_PGLITE_MODULE=(Resolve-Path 'tests/sql-harness/node_modules/@electric-sql/pglite').Path
python -m pytest -q tests/test_daily_volume_retention_preview.py -p no:cacheprovider --basetemp "$env:TEMP/volume-preview-$([guid]::NewGuid().ToString('N'))" --tb=short
```

No new dependencies or lock changes are required. The pinned inventory baseline
62508fd file remains deliberately unchanged. A check against that older baseline
can flag already-merged companion files: do not rewrite it or ignore blockers to
make uploads pass. The sequential checks recorded here used verified public-main
metadata and the preceding groups' explicit source overlays. Exact clean-clone
rehearsal and full PR CI remain the owner's final packaging gate.

Connected read-only size check returned database440986771/cluster456260405,
headroom43739595, query_read_only=on. Database-reported measurement timestamp:
2026-10-07 20:48:44.592711+00. Do not substitute this earlier timestamp for fresh
owner admission. Constraint inventory confirmed quote/volume time-bearing keys,
scanner's global observation_id and prediction-target RESTRICT reference, and
global ledger identities; structural instructions now distinguish those sources.

## What changed and why

ColdLedger now walks bounded digest metadata, oldest first, with one decoded
segment resident. Every original's event and retry locator must match. Staging
verifies ALL originals, global identities, original signatures, independent terminal
heads and the final source fence before exposing rows. A corrupt last segment or
late source change cannot produce a seemingly valid shorter history.

The reader depends on a read-only SQL/GET contract, not archive deletion code.
Native original decoding rejects duplicate JSON keys and non-finite constants.
Synthetic local sealing verifies immutable segment, catalog and signed receipt
readback and reconstructs original events after reopening. Default local objects
are read-only; opt-in writes are create-only, with exact retry and retained failures.

Consumer adapters apply that complete-cut contract to events, retry lookup/absence,
continuity audits and streamed research pairs. Empty or unsigned history is not
called complete HMAC evidence. Compatibility result lists are bounded. These are
injected libraries: actual production factories and historical dataset callers
still require explicit integration, not an automatic import or secret switch.

Daily-volume preview preserves the 20 available prior non-null captured dates PER
instrument, including sparse histories; current/future/null rows remain protected.
That is not a deletion rule or certified exchange volume. It reports counts/row-byte
estimates and explicit false dependency, cold-reader and deletion authority.

The earlier universe codec shares only identical raw bytes while preserving every
snapshot/header/non-raw identity. Capacity planning never credits future savings
before old files disappear. At the last owner reading, only 19,739,595 bytes remain
ABOVE the existing 24 MB admission margin, before concurrent growth. That is not a
fresh admission measurement or a verified migration peak.

## Owner steps, in order

1. Keep the existing 08:55 owner-file preparation/supervised capture routine on its
   installed isolated folder. These upload groups do not change that installation.
2. Review and upload A through J as listed. Keep scan-only recurrence, other modes/
   F&O and release holds unchanged. A..H alone need no expectation change; I DOES
   change public fingerprint members. Do NOT update Streamlit while held release
   runs old source. Later supervised owner promotion/hash handover is described in
   HISTORICAL_REPOSITORY_PACKAGE.md. Never compute expectations from the dirty folder.
3. Finish the encrypted password-manager note for the CURRENT original signing
   key and privately reopen it; check older vault versions for historical keys.
   Report availability only, never values/screenshots. Do not rotate/re-sign history.
4. Perform the existing harmless 7-Zip GUI encrypted dummy rehearsal on the empty
   external disk (AES-256, encrypted filenames). Windows Home has no BitLocker To Go.
   Keep real plaintext exports/extractions OFF that unencrypted disk. Keep encryption
   password and independently expected checkpoints recoverable outside primary Drive.
5. Confirm licensed private retention/copying duration and allowed readers. Software
   cannot create licence permission.
6. After E is merged, run each block of sql/storage_layout_inventory_read_only.sql
   separately in Supabase SQL Editor; run the one daily-volume block separately.
   Save only metadata privately. Owner/BYPASSRLS results do not prove runtime-role
   access. Record fresh physical disk/WAL/quota readings and the viewing time.
7. Review STORAGE_STRUCTURAL_COMMISSIONING.md for the later transition gates.
   Do NOT execute old permanent-storage migrations, install extensions, partition/
   drop/rewrite tables, alter the quote purge, or re-enable held modes from this handoff.

Paid capacity on the SAME database may be necessary if reviewed shadow-copy peak
cannot fit. It provides runway, not permanent retention. No purchase or upgrade
was performed or presumed. Splitting F&O into a second database is not the chosen
default: it adds identity, recovery, monitoring and credential boundaries before
the existing ones are proved.

## Remaining implementation and acceptance

Successor K complete upload group (after J):

- `operational_receipt_history.py`
- `tests/test_operational_receipt_history.py`
- `OPERATIONAL_RECEIPT_HISTORY_PACKAGE.md`

K adds authenticated bounded immutable-fence checkpoint/run receipt reading. It
preserves old receipt identity after newer ownership and returns UNAVAILABLE for
missing evidence, never guessed absence. No current-row backfill, live writer,
schema change, ACK, resend or restore. The original writer must still prove receipt
and operational change share one transaction. K's package runbook records gates.
FINAL K/L/J/local recovery181passed9.48s; all38new Python strict types/all44selected
Python lint/imports PASS. Final independent read-only peer review finds no remaining
actionable defect after budget, encoding, journal-key binding and finite-parser
fixes. Sequential K/L exact-public dependency closures PASS/empty blockers.
Final clean-public46892 EXIT0:2809passed,4unchangedskips,2subtests495.81s.
Local35031 EXIT0:3095passed,4unchangedskips,2subtests644.69s. L unused field-list constant
removed after full collection; final-source K/L91passed2.63s, Lalone34passed2.58s,
strict/lint clean. No test/skip removal. A..J fingerprint remains unchanged,
independently recomputed. All thirteen sequential package closures pass.
No tests remain running. Goal is usage-limited, NOT complete; the same-transaction
six-table recovery extension is the recorded next offline implementation, followed
by the existing atomic writer/factory/retention/commissioning critical path.

Successor L complete upload group (after FINAL revised K):

- `finalization_intents.py`
- `tests/test_finalization_intents.py`
- `FINALIZATION_INTENTS_PACKAGE.md`

L preserves original local terminal intents under exact run/token identities,
requiring caller-owned transactions and exact remote proof before ACK. Older
intent ACK cannot finalize newer owned job. Bounded logical journal/pending reads,
corrupt/oversized metadata rejection and rollback tests; NO live sender wiring or
real-state initialization. The new sixth table still needs whole-cut/recovery
coverage; the five-table witness must not silently be treated as enough.
K's FINAL request identity/decoder files include the L dependencies; upload these
final complete K files, not earlier versions. K/L do not change fingerprint members.

Full application cut/inventory (not just one SQLite) -> independently recoverable
encrypted copies/checkpoints -> legacy/remote append and ACK reconciliation ->
actual live factories and EVERY historical dataset reader -> authenticated
publication and atomic source/root commit -> universe SQL adapter and bounded
source-specific retention/partition cutover -> all-writer reservations and
independent alerts -> measured steady state and independent whole-app restore.

The disconnected disk cannot provide automatic nightly replicas. Unreplicated
history must remain protected and fit the hot/staging bound through owner delay.
If that delay cannot fit, require more hot capacity or an independently commissioned
online replica—not a relaxed two-copy gate. Missing old keys or raw quote evidence
stay missing. Archive-before-future-purge ordering still needs commissioning.

These owner dependencies block REAL custody/retirement, not all remaining offline
work. Live consumer/factory integration, cross-file barriers, source-specific cold
adapters and reservation/alerts still require engineering. No ML study or holdout
analysis was started while that storage critical path remains unfinished.

## Held files — explicitly NOT in these groups

ledger_archive_repository.py was refactored LOCALLY to share the read contracts and
native-original decoder. It is the one extra held implementation change this round;
do not upload it. Its SQL delete/root-CAS guards and concurrency acceptance need a
complete later package. Existing dirty production_repository.py,
equity_runtime_health.py, equity_research_observations.py, recovery_drill.py,
release_verification.py, ledger_storage_access.py, cold_drive_objects.py, packaging
configuration and review-only migrations remain held. They are not obsolete and
are not implicit dependencies of these thirteen groups. I instead supplies separate
PUBLIC-base staged repository/health/packaging candidates; never substitute drafts.

The unchanged older stage inventory is historical/pinned; this exact group list
is the current upload authority. A matching local draft or passing all-drafts test
does not mean that draft exists on public main.

## Verification record

First three groups: 263 focused tests; separate source-only overlay 263; isolated
OIDC/Settings boot 2; strict 9-file types and root/tests lint clean; full suite
2703 passed, 4 unchanged skips, 2 subtests (final earlier batch).

Continuation through E: 2775 passed, 4 unchanged skips, 2 subtests in 635.06s.
Clean-public overlay (held runtime/private configuration excluded): 85 focused
tests passed in 16.06s. Native/public SQL fixture used, not the dirty local fixture.
Initial boot rehearsal caught a copied policy-file newline/checksum mismatch;
re-copying the exact public-blob policy and sidecar fixed it without editing policy.
Combined corrected isolated public boot plus F consumer tests: 18 passed in 16.05s.

F adds16 cases; publication self-review adds3 transport-redaction cases and G adds2
cleanup cases. All seven storage-group dependency checks have no blockers.
Strict 13 continuation source/test files and earlier 9 files PASS; root/tests lint
PASS. Fullsuite64129 with F:2791passed,4unchangedskips,2subtests555.07s,exit0.
Publication focused54passed; strict source types PASS. G2 synthetic cleanup cases
pass; its staged source check-untyped-defs and new-test strict checks PASS.
Corrected-resource public full rehearsal had2504pass/1fail: the pre-existing
Windows verification child-process lock. G fixes it without relaxing the timeout.
Actual corrected public G/release/AppTest focused23passed58.46s.
FINAL A..G public overlay82063 EXIT0:2510passed,4unchangedskips,2subtests373.92s.
Local73361 EXIT0:2794passed,4unchangedskips,2subtests635.45s; G's2newcases came
after that collection and passed separately, not claimed as part of a2796fullsuite.
H adds112focused cases (112passed3.21s); strict5newfiles/lintPASS. Updated all-group
public and local full-suite results must be recorded before final H handoff.
No test/assertion removed; no additional skip.

Final successor checks: D1/F/I/J135passed15.20s; ALL34new Python source/test files
strict types PASS, all40selected Python paths lint PASS. Publication test typing
cleanup separately16passed2.05s in clean-public overlay after strict sweep caught
missing test annotations; no test/assertion/skip removal. Exact eleven-group
sequential import/resource closure checks all pass with empty blockers against
verified public9ce3af9 plus preceding group overlays; pinned62508fd unchanged.
AST self-review confirms repository import+seven intended methods only, health
RELEASE_FILES only, packaging RUNTIME only. Full runtime-source public95503 EXIT0:
2718passed,4unchangedskips,2subtests411.96s; local76507 EXIT0:3004passed,
4unchangedskips,2subtests595.67s. Actual extracted import/OIDC/AppTest/release
probes passed. Publication test typing tidy-up after full collection separately
passed16cases; runtime source unchanged. No tests remain running.

Manual self-review covered signature-versus-continuity claims, late-fence atomicity,
global retries, private SQLite spills, bounded result lists, reader/delete separation,
duplicate JSON fields, source preservation, partial-file recovery, disk/quota peaks
and sparse-date retention. Fixed Windows handle/cleanup and context-error masking
issues; tests cover the corrected cases. Offline tests do not prove real hosted
multi-connection races, encrypted custody, hardware durability or publication timing.
