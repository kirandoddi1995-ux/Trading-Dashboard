# Permanent storage: current acceptance boundary and next build order

## Decision in plain language

Keep one small operational database and verified private history. Fix repeated
universe payloads and bound every source, including the ledger and metadata.
Do not add a second operational database merely to postpone the same growth.
The owner's Oct 11 dashboard report gives breathing room, not permanent safety:
394 MB is not a fresh exact cluster-byte measurement. Keep the existing conservative
500,000,000-byte limit, 24 MB admission floor and currently held modes unchanged.

Supabase distinguishes database quota from physical disk and organization-average
fair-use restrictions; a second Free project is not a reliable quota workaround.
[Official database-size documentation](https://supabase.com/docs/guides/platform/database-size).
Payment/plan changes remain an owner decision; no purchase is implied here.

## What this package actually finishes

- An eager sixth-table snapshot extension runs INSIDE the existing five-table
  SQLite read transaction. It closes the source before exposing detached spools.
  It validates the terminal journal's exact schema, canonical original requests,
  fences, timestamps, ACK hashes, row/byte/deadline limits and independent witness.
  Existing five-table witness/validation/current-token restrictions remain intact.
- Sixth-table verification checks exact historical immutable remote receipts;
  missing proof stays missing. An old intent receipt cannot finalize a newer job.
  No sender, live state initialization, restore or deletion is activated.
- A manual-only native Postgres 17 disposable runner tests six capacity-guard
  cases with distinct backend PIDs, a restricted role, RLS and concurrent clients.
  Preview opens nothing. No project DSN, credentials or hosted database is used.
- A reviewed password-rotation procedure and one exact-upload manifest/checker.

This is NOT complete cross-file recovery: the existing signed bundle encodes a
five-table witness. The separate sixth witness must be independently retained;
do not infer it from the restored target or claim existing bundles semantically
authenticate it. Next work must version authenticated custody to bind both
witnesses and the complete protected SQLite image before any live sixth-table use.
Full-image hash equality alone does not prove an immutable consistent source cut
in the presence of WAL/sidecars or concurrent replacement. No such shortcut exists.

## Build chain and exit gates

1. **Retire the exposed runtime credential now**, following the separate owner
   runbook. This is independent of storage uploads. No signing-key rotation.
2. **Independent custody + full-image/six-table recovery.** Owner saves the original
   signing key privately; verify historical key coverage and a dummy encrypted
   external-disk restore. Engineering binds both source witnesses, signed catalog
   anchors and original image into a versioned, restartable two-replica proposal.
   Test swapped/missing/stale copies and every crash boundary. Do not claim a
   disconnected disk provides unattended daily replication: deletion must stop
   when the required second-copy generation is missing or too old.
3. **Native acceptance, then writer/factory wiring.** Run the new native guard
   workflow. Extend native tests to original immutable receipt writes, append vs
   seal/delete/root CAS races, fencing takeover, unknown COMMIT and permissions.
   PGlite remains useful but is not this proof. Wire guarded writes and complete
   cold-aware recovery into ALL factories only after these paths pass.
4. **Universe shadow normalization.** Store each EXACT raw payload by content hash;
   retain all snapshot headers, member identities, effective/available/source
   times and non-raw fields. Compare full old/new PIT reconstruction and genuine
   changes before switching readers. Never dedup by stripping business fields.
5. **Source-by-source bounded retention.** Quotes/scanner observations, daily
   volumes, outcomes and original ledger segments each need a reviewed dependency
   contract, exact cold lookup, verified private replicas and restore proof before
   pruning. Keep unresolved delivery/position/decision dependencies hot. Volume
   lookback uses completed sessions per instrument, not a calendar-day DELETE.
   Captured maxima are not certified final exchange volume.
6. **One physical transition + steady-state proof.** Fresh SQL/physical-disk
   measurements must cover old + new + indexes/TOAST + scratch/WAL + reserve at
   PEAK, not credit future savings. No automatic VACUUM FULL/repack. Partition only
   suitable sources after PK/FK/PIT review: a partitioned unique constraint must
   include the partition key, so date-partitioning a globally identified ledger
   is not a harmless drop-in change. Verify allocation over a complete retention
   cycle, restore original identities, then accept ingestion limits and alerts.

[Postgres partition constraints](https://www.postgresql.org/docs/17/ddl-partitioning.html)
and [vacuum behavior](https://www.postgresql.org/docs/17/routine-vacuuming.html)
support the transition distinction: reusable space is not guaranteed shrinkage.

## Every writer, not just scans

Commissioning inventory must include dashboard evidence/checkpoints, scheduled
collector (each mode), equity research, archive/catalog/manifests, raw-quote purge,
daily-volume updates, reference ingestion, monitor/watchdog and owner maintenance.
Current storage_write_guard covers cooperating bounded append transactions ONLY.
An advisory lock does not constrain uncooperative writers or PostgreSQL allocation;
an application measurement outside the transaction is not a disk reservation.
Updates/deletes can allocate space and are not ordinary bounded appends.
[Postgres advisory locks](https://www.postgresql.org/docs/17/explicit-locking.html#ADVISORY-LOCKS).

Each adapter needs: dedicated connection, exact transaction ownership, fresh
measurement, conservatively measured allocation envelope, shared lock namespace,
original idempotency, unknown-COMMIT reconciliation and no HTTP inside SQL locks.
Do not wrap an auto-committing repository call in the guard and claim enforcement.
Never loosen a bound to turn a rejected pilot green.

Independent alerts must verify actual delivery and missed-run detection outside
the producer host. Pure alarm evaluation is not commissioned notification.
Alert tests use synthetic data; no Sentry/Healthchecks/email accounts are created.

## Native owner test after upload/green main

GitHub -> Actions -> **Disposable native storage guard conformance** -> Run workflow
-> choose the reviewed main commit -> check confirmation -> Run. This intentionally
creates ONLY an ephemeral service with public synthetic fixture credentials.
No project secrets are referenced. Check the run's SHA, all provisioning steps and
`NATIVE_GUARD_CASES_PASSED`, six cases, global_enforcement_commissioned=false.
An unchecked confirmation skips the job; skipped is not native PASS.
If it fails, preserve the fixed-code receipt; do not run the fixture SQL on Supabase.

Cases: distinct native PIDs/restricted sandbox; committed append visible on another
connection; concurrent contender blocked then admitted after commit; failed body
rolled back and lock released; rogue caller COMMIT detected without claiming undo;
duplicate PK insert rolled back without retry. These do NOT certify ledger pruning,
allocator bounds under real workload, pooler routes or whole-app recovery.
The workflow uses the existing action versions and a Postgres 17.6 tag matching the
reported server family; the image tag is not a cryptographic content pin. Record
the service image digest/version from the owner run before relying on its result.
[GitHub service-container documentation](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers).

## Owner work in parallel

Rotation can proceed without these uploads. Save the original ledger key in an
encrypted password-manager note; check older versions by names/coverage only.
On the empty external disk, rehearse a harmless dummy archive using 7-Zip AES-256
and encrypted filenames; reopen/extract it and compare original bytes. Keep the
password/recovery note independently secured, not on that disk. Do not archive
real keys or market files until the rehearsal succeeds. Existing key/replica
tools still require independently reviewed anchors and privately supplied files.

Keep Monday Oct 12 capture separate: installed folder untouched, fresh owner-file
previous-close preparation with calendar-verified Oct 9 if it is the last regular
session, actual download time, supervised future-slot poll and remote receipt.
No reuse of Oct 8's file/config/time and no catch-up. Current tasks remain disabled
until the owner makes the supervised commissioning decision.

Storage is still an engineering project, not just remaining owner clicks. Analysis
and ML start from frozen development-only files after exact historical joins,
missing-label semantics, costs and PIT evidence are proven; 2025/2026 stay sealed.
