# Group H — bounded write guard and independent-watch evaluator

This adds inactive, injected code. It does not connect to any database, change
collector admission, schedule a watcher or deliver an alert. No runtime factory or
fingerprint member changes. Existing scan-only recurrence and release holds stay.

## Complete upload group (after G)

- `storage_write_guard.py`: cooperating writers share a transaction-held advisory
  lock; fresh restricted-role measurements before/after, original transaction/lock
  fence, unchanged 24 MB reserve plus the declared allocation, bounded SQL timeouts,
  explicit uncertain-commit and allocation-overrun failures.
- `storage_capacity_watch.py`: deterministic independent capacity and explicit
  scheduled-run deadline evaluation. Missing/stale measurements, missing receipts,
  failed/late runs and limited observed runway alert. No schedule fabrication or
  claims of authenticated transports, infinite runway or notification delivery.
- `tests/test_storage_write_guard.py`: ordering, competing writers, margins, stale/
  privileged/invalid measurements, clock offsets, original transaction ownership,
  lost lock, failures, overrun and uncertain commit cases.
- `tests/test_storage_capacity_watch.py`: synthetic capacity/deadline/receipt cases,
  missing sources, holidays through an explicit empty reviewed schedule, boundaries,
  exact booleans, input bounds and reproducible reporting.
- `tests/test_storage_guard_sql.py`: exact SQL against the existing disposable
  PostgreSQL harness, including native advisory-lock namespace and release semantics.
- `STORAGE_GUARD_AND_WATCH_PACKAGE.md`: scope, tests and commissioning instructions.

These six are new public paths. No held `storage_policy.py`, migration or dirty
production repository belongs in this group. Its older 350/400/450 MB policy is
NOT silently activated here. Current constants come from public collector
preflight (500,000,000 planning quota, 24,000,000 floor, 4,000,000 run allowance).

## Why transaction-held admission

An expiring reservation can be reclaimed while its writer is still alive. This
guard instead rejects a busy lock immediately and holds one lock through the
entire bounded transaction. Every cooperating writer must use the same connection
and lock namespace. The server releases transaction locks at transaction end;
advisory locks do not constrain clients that ignore them. See PostgreSQL's
[advisory-lock documentation](https://www.postgresql.org/docs/17/explicit-locking.html#ADVISORY-LOCKS).

The guard preserves the FULL 24 MB floor after its declared bound: a 4 MB append
needs 28 MB BEFORE it starts. This is deliberately more conservative than the
current standalone collector preview; it does not modify that running preview.
The bound includes indexes/TOAST/incidental database allocation, not just JSON
size. It never credits an anticipated archive, deletion or negative size trend.

Normal bounded SQL appends only. No archive fetch, Drive upload, user prompt,
compaction, DDL, partition conversion, two-phase PREPARE, nested transaction or
connection switching in the guarded block. SQL measurement functions and catalogs
are explicitly `pg_catalog` qualified. A native original transaction ID plus its
held advisory lock is checked again before commit. Commit/re-BEGIN is not a valid
way to evade the original transaction fence.

The target is PostgreSQL 17+, matching the owner's reported 17.6. Statement 10 s,
lock 2 s and transaction 30 s limits are LOCAL to this transaction. The latter
terminates an overlong session rather than issuing an expiring reservation that
leaves its writer running; pool recycling must handle that termination. Confirm
with [PostgreSQL timeout semantics](https://www.postgresql.org/docs/17/runtime-config-client.html).
The caller still needs bounded TLS-verified connection establishment and a
dedicated idle, autocommit-false restricted connection. No owner/BYPASSRLS writer.

Post-write checks are NOT allocator enforcement. PostgreSQL can allocate blocks
before a bound overrun is detected, and rollback does not promise to return those
bytes. On overrun: stop that writer, remeasure and investigate; no blind retry.
On uncertain COMMIT: independently reconcile the original run/event retry identity,
then decide. A cursor cleanup failure AFTER a successful commit is explicitly
`COMMITTED_CLEANUP_FAILED`, not permission to append again.

## Independent watch contract

The evaluator accepts fresh cluster allocation, an earlier observation within
24 hours, and explicit run start/deadline/identity facts from the reviewed session
calendar. A schedule hash locates that inventory; it is not proof of authenticity.
Only a terminal receipt bound to that run can satisfy it; a previous-day receipt,
string `"false"`, future success or a queue/HTTP 202 acknowledgement cannot.

An empty run inventory is meaningful only with an explicitly reviewed schedule
identity: e.g. an exchange holiday or no enabled producer. This module never
creates a weekday-only NSE calendar. A missing receipt is late AFTER its deadline;
an observed failure alarms immediately, and late eventual success retains lateness.

The two-point positive slope is diagnostic, not a guaranteed allocation forecast.
Flat/negative growth leaves runway unknown, not infinite. Actual floor breach or
inadequate runway for the bounded append still alarms. `UNKNOWN` is an alarm too;
first observation without a trend cannot silently appear healthy. Physical disk/
WAL, licence, archive authentication and replica custody are separate checks.

No notification service/host is commissioned. The future monitor must run outside
the failing producer and not depend on a database write to send its alarm. A
database-down/read-only failure must produce an unavailable measurement alarm.
The independent monitor itself needs a separately observed missed-heartbeat alert.
This code makes no claim that such alert delivery is already working.

## Exact local commands before upload

Use the clean public-main review clone after A through G, not this dirty folder.
The existing offline SQL harness must be present; no new test is skipped when it
is missing. If needed, install its locked dependencies as the existing CI does:

```powershell
npm ci --prefix tests/sql-harness --ignore-scripts --no-audit --no-fund
$env:EQUITY_TEST_PGLITE_MODULE = (Resolve-Path tests/sql-harness/node_modules/@electric-sql/pglite).Path
python -m pytest -q -p no:cacheprovider tests/test_storage_write_guard.py tests/test_storage_capacity_watch.py tests/test_storage_guard_sql.py
python -m pyflakes storage_write_guard.py storage_capacity_watch.py tests/test_storage_write_guard.py tests/test_storage_capacity_watch.py tests/test_storage_guard_sql.py
python -m mypy --strict --follow-imports=silent storage_write_guard.py storage_capacity_watch.py tests/test_storage_write_guard.py tests/test_storage_capacity_watch.py tests/test_storage_guard_sql.py
python -m pytest -q
```

Focused first local rehearsal: 112 passed, strict five-file types/lint clean. The first
native SQL rehearsal exposed a PGlite limitation: backend ID zero/lock PID NULL.
Tests now explicitly prove the STRICT production fence does not accept it, while
checking native two-int lock metadata and transaction release. No production
gate was relaxed and no extra skip was added. This is not a two-connection proof.
Self-review subsequently added preservation of caller failures through a faulty
cursor wrapper (including suppression/replacement), uncertain-commit suppression
and missing-request rejection. Re-run the final commands above; the original
112-case full rehearsal predates those seven additional cases and must not be
reported as the final full validation.

Final H focused119passed5.98s; the final A..J clean-public suite2718passed and
local suite3004passed, both with4unchangedskips/2subtests. All NEW code/tests strict
types and selected source lint pass. Native ownership/alert delivery still unproved.

## Later commissioning order — NOT authorised by this upload

1. Inventory EVERY database writer and its transaction boundaries: app persistence,
   scheduled scans/open/close/global/weekly, research outcomes, derivative monitor/
   ingestor/watchdog, archive manifests, housekeeping/quote purge and owner tools.
   Record disabled ones too. Other databases/internal service allocations remain
   an explicit uncoordinated bound, not covered by a database-local advisory lock.
2. Measure/test upper bounds including allocation bursts, retries, indexes/TOAST
   and failure residue. Only verified appends of at most 4 MB use this guard;
   reviewed larger transition operations keep their separate capacity plan.
3. Use an ISOLATED local PostgreSQL 17+ instance with synthetic data and two real
   connections. Verify native backend/transaction/lock fences, busy second writer,
   commit/re-BEGIN rejection, crash/session-timeout release, allocator overrun,
   uncertain commit/reconciliation and pool reuse. Do NOT use production for this
   rehearsal. Hosted activation requires a later explicitly reviewed owner step.
4. Wire all cooperating factories, remove bypasses and adopt ONE lock ordering:
   capacity lock before source/root/head locks. Prove concurrent archive/append/
   retry deadlock behavior before enabling. Do not wrap a slow remote fetch in TX.
5. Commission authenticated read-only measurements and session-specific terminal
   receipts on the independent monitor. Owner selects/configures alert accounts,
   private secrets and host; no purchase or setting change is presumed.
6. Simulate missing database, failed archive, stopped producer, stale readings,
   monitor stopped, holiday and a late-successful run. Independently receive each
   alarm, prove recovery and record evidence. Only then may all-writer/alert
   commissioning be reported. None of the current receipts claims that status.
