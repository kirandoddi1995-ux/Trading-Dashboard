# Permanent storage: one bounded operational database, verified private history

## Plain-language decision

The database should hold what the running app needs now, not the project's whole
history. History stays available for analysis and ML in verified private files.
Collection, archival, historical reading and recovery must work as one system;
deleting older rows alone is not that system. The permanent design is NOT yet
commissioned. This document is the implementation/acceptance contract, not an
instruction to apply the existing review-only migrations.

Choose the existing Supabase project plus private Drive and a second private
backup. Do not split equities/F&O into two operational databases solely for space.
That would duplicate recovery, roles, secrets and monitoring without bounding
growth. Respect the earlier no-payment constraint. If the owner later changes it,
a paid upgrade is a sensible capacity/availability buffer, not a replacement for
this design. Never purchase or change plans automatically.

[Supabase pricing](https://supabase.com/pricing), checked Oct 7, lists Free at
500 MB database size, and Pro from $25/month with 8 GB disk and seven-day daily
backups. Extra compute/usage can change the bill. Free has no automatic backups.
[Database-size documentation](https://supabase.com/docs/guides/platform/database-size)
distinguishes the database quota from physical disk, and describes organization
average-size restrictions: creating another Free project is not a quota bypass.

## End-to-end chain

Source -> timestamped, bounded collection -> hot operational facts and original
signed evidence -> immutable verified private archive + authenticated catalog ->
exact hot/cold readers -> frozen private analysis/ML datasets -> app evidence.

Historical research reads files, not a giant training query on production.
Supabase stores current state and a bounded catalog/root/frontier, not one SQL
receipt/idempotency row for every historical event forever. Research never learns
from future-available data; effective_at, available_at, observed_at and original
identities are retained. Missing data, missing minutes and incomplete coverage
remain explicit. No reconstructed fill prices or synthetic evidence are permitted.
Frozen 2025/2026 validation/holdout inputs and experiments remain unexamined.

Private Drive is the first cold tier because it is already configured. It is
neither immutable WORM storage nor an always-available transactional database.
Use content-addressed originals, download/re-read verification, signed manifests,
independently retained root receipts, bounded caches and a second private copy.
Never put market files in the public repository or Actions artifacts/logs. Licence
and retention permission still apply even with 5 TB available. Offline PC backup
helps recovery; PC uptime must not be required for hosted cold reads/archival.

## What stays hot, what becomes cold

- Universe: current/latest-complete and every active decision/recovery dependency
  stays hot. Store each exact instrument payload once by content hash, and map
  immutable snapshot/version identities to it. Preserve genuine changes and source
  times; do not strip business fields to manufacture equality. Historical PIT
  reconstruction must match the original record/hash, including canonical/version
  identities. Migrate readers before removing duplicate payload copies. Existing
  date guards remain until their replacement is proven.
- Quotes and scanner observations: propose three hot days plus unresolved/recovery
  references, with exact cold lookup before shortening existing 14-day windows.
  Bulk depth/ticks, option snapshots and forward bars go directly to private file
  bundles; they do not belong in hot Postgres as full repeated payloads.
- Ledger: archive only verified contiguous original prefixes per aggregate.
  Preserve signatures, UUIDs, idempotency identities and predecessor links. Original
  v1/v2 keys are required; unknown legacy keys protect the affected history rather
  than being replaced with the current key. Protected terminal heads and catalog
  generations prevent truncation/replay; cold retries restore original identity.
  Archive/delete/root advancement must commit atomically after remote verification.
  No network request while holding SQL write locks. Unresolved positions/deliveries
  stay hot. Local SQLite and remote Postgres are separate signed chains: never splice
  one into the other. Checkpoints are a third recovery dependency.
- Daily volumes: retain the maximum required completed-session lookback across
  commissioned readers, initially the existing 20-observation default, plus active
  dependencies. Preserve instrument/contract identity, captured maxima, observation
  times and coverage. Captured maxima are not automatically verified final exchange
  volumes. Use the reviewed calendar, not a calendar-day cutoff. Archive older facts
  only after exact as-of historical lookup is supported. Futures roll/baseline
  commissioning is separate; never substitute NIFTY index volume.
- Outcomes: keep current active decisions and the existing seven-day superseded
  window until a cold-aware reader is commissioned. Finalized cohorts can eventually
  leave hot storage, but their latest outcomes must remain exactly accessible.
  This changes physical retention, not evidence meaning, and needs explicit owner
  review; it is not permission to delete the protected latest rows today.
- NAV and lower-volume tables: bounded current state and dependency-aware verified
  history. NAV remains useful historical data, not discarded merely because F&O
  is the current focus. Archive policies must cover every writer, including run/
  quality records, intents, alerts, receipts and metadata themselves.

## Capacity contract, not a hope about retention days

Existing storage_policy.py proposes 238 MB relation budgets plus 70 MB other
cluster allowance: **308 MB total**, including 10 MB derivative allocation.
These are engineering targets, not measured achievable sizes. Prove protected
working sets fit; do not remove dependencies or reduce sampling to force them in.
If a protected set outgrows its budget, report the capacity constraint.

Future commissioned policy: warning at 350 MB, stop initiating nonessential
writes at 400 MB, critical at 450 MB, preserving essential durability/recovery
reserve before the conservative 500,000,000-byte planning limit. Guard allocation
(heap/index/TOAST), not only live row bytes. Measurements must be fresh and complete.
Per-table byte/batch limits and a shared admission protocol must cover ALL writers,
including dashboard, scheduled collection, archival metadata, research, monitoring
and owner workflows. A check outside a transaction is not a disk reservation;
account for concurrent batches and enforce the actual bounded payload envelope.
Protected data may override a retention age but must never silently override capacity.

The current 455,555,893 bytes are above the future critical threshold. Do not turn
on that future policy and then bypass it to make scans pass. During transition,
keep the existing restricted 24 MB admission unchanged and only measured scan
recurrence admitted under its separate runbook. Other collector modes and F&O
ingestion stay held. NAV relief has bought implementation time, not permanence.

## Implementation order and concrete exit gates

1. **Freeze the contracts/inventory.** Enumerate each writer, reader, SQL/JSON
   dependency, legal retention, maximum working set and restore identity. Include
   metadata/control rows. Establish receipt/schema versions and original signing
   keys without exposing them. Unknown consumers/keys are blockers.
2. **Finish ledger recovery and factory wiring first.** The local cores already
   seal originals, verify private publication, protect roots/heads, read merged
   history and test SQL guards. Live factories, local outbox/checkpoint recovery,
   all readers and bounded history streaming remain unfinished. Complete those
   before enabling ANY ledger pruning. Prove retry after remote commit but before
   local acknowledgement does not mint another event. Test archive/append races
   with real independent disposable PostgreSQL connections, not only SQL emulation.
3. **Commission one ledger archive boundary.** On an isolated disposable restored
   database: prove cold-only/merged reads, global audit, training joins, pending
   outcomes and recovery before/after deletion have the same original witness.
   Inject missing objects, corrupt bytes, stale/rolled-back roots, unknown keys,
   partial deletion and crashes at each publication/commit boundary. Missing cold
   history must cause an explicit error, never an apparently valid empty dataset.
   Only then prepare owner-reviewed migration/bootstrap/preview/export/trial steps.
4. **Normalize the universe; extend non-ledger cold reading and retention.** Run
   shadow old/new reconstruction and compare exact PIT records/fingerprints across
   unchanged snapshots and genuine changes. Keep the old reader available through
   acceptance. Install volume/quote/scanner/outcome archive contracts individually;
   test dependency protection and private restore before reviewed deletion.
5. **Reach the physical budget once.** Ordinary vacuum primarily permits reuse;
   it does not guarantee file shrink ([Postgres vacuum documentation](
   https://www.postgresql.org/docs/17/routine-vacuuming.html)). After logical
   retention, select separately reviewed table-level compaction only where fresh
   physical disk, transient old+new copies, WAL, quota and lock duration permit it.
   Require survivor backup, private restore rehearsal, exact rows/schema/RLS/grants/
   indexes before/after and rollback/blocked receipts. No blind whole-database rewrite
   or large partition conversion. If a safe rewrite cannot fit, report a capacity
   decision; do not assume a second Free project or transient quota breach is safe.
6. **Enforce admission, archive liveness and independent alerts.** Wire the policy
   to all initiating writers after the footprint fits it. Monitor oldest eligible
   unarchived data, retained dependencies, verification failures, peak allocation,
   cold object/key availability and missed collection/archive jobs. Independent
   alerting must still work when Supabase is read-only or a producer never starts.
   No alert account/settings is created by the agent; prepare owner setup steps.
7. **Prove steady state; then expand.** Observe at least ten consecutive complete
   regular-session cycles, including every collector mode intended to be restored,
   the busiest workload and post-archive settling. Every peak must remain below
   350 MB, relation budgets hold, and backlog not grow. Also prove an analytical
   worst-case working-set bound including metadata/concurrency: ten days alone
   cannot prove indefinite boundedness. Require a private second-copy whole-app
   restore and frozen ML dataset hash reproducibility. Then admit remaining modes
   one at a time; derivative installation/ingestion follows its own measured trial.

Partitioning is a possible future physical-retention tool, not the first fix for
these small tables with global uniqueness/ledger invariants. No new partition SQL
is included in this package. The Supabase Sept 25 minor-upgrade notice also warrants
an owner extension/operator inventory before a future restore/upgrade; it is not
permission to run upgrade/reindex/encryption changes now.

## What “permanent” will mean, and what it will not mean

Success means normal collection/archive cycles keep hot allocation within a
proved working-set envelope without recurring emergency deletion/compaction;
history is exactly retrievable for ML and recoverable after host loss. No finite
free database or 5 TB archive promises infinite data retention or uptime. Growing
licence-approved history needs eventual capacity planning and archive verification.
Analysis/ML must not depend on a live database query that silently omits cold rows.

New storage_commissioning.py makes the missing proof categories and ten-session
requirements executable, with offline tests. It is a checklist over receipt hash
REFERENCES, not a signature verifier or a hosted guard. Even a complete checklist
cannot authorise deletion; receipt origin/signatures must be independently verified.
At today's footprint, permanent acceptance fails. Do not confuse component-test
success with this end-to-end commissioning gate.

## Owner actions now; hosted actions later

Now: keep the scan-only measured restart and normal archival separate from this
package. Do not apply the three review-only permanent-storage migrations or enable
their pruning control. Do not use DATABASE_MIGRATION_URL/apply_migrations as a
generic draft installer. Keep release/F&O and other collector modes held pending
their own acceptance. Keep private backups/receipts.

The next storage engineering milestone is the unfinished local ledger/outbox/
checkpoint recovery and live factory wiring, then a complete isolated restore
rehearsal. No further relief operation is the default next step. An owner migration
runbook with exact inspected SQL/role/grant/bootstrap ordering is prepared only
after those gates pass; inventing its clicks now would imply readiness that is
not established. Supabase/Postgres guidance informed this least-privilege,
reader-first, measured-allocation order.

For the independent forward capture repair, see NSE_OWNER_CLOSE_RUNBOOK.md.
