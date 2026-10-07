# Permanent storage design — implementation in progress

Oct 7 decision/implementation order is now in PERMANENT_STORAGE_ROLLOUT.md.
NAV compaction and the accepted scan have provided 44.4 MB nominal headroom,
not commissioned this design. The new storage_commissioning.py checklist makes
proof/observation gaps explicit; receipt references are not independently verified
by it and it never authorises pruning. Existing review-only migrations remain held.

Scope is the entire eight-part goal, not the completed emergency patch.
Do not upload/commission this unfinished group as a complete storage solution.
No hosted writes or deletion commands have been run. Keep the derivative pilot held.

## Evidence, 2026-10-05 19:04 UTC
Read-only owner-level connector, 10-second statement and 2-second lock timeout:
cluster remains 493,984,565 bytes. Thirty-three existing application tables were
inventoried; nine derivative tables are absent. The remote ledger has 9,739 schema
v2 events and 43 schema v1 events, all HMAC-SHA256. Only format/count/size metadata
was read, never the frozen 2025/2026 performance datasets or signing material.
The exact inventory query is sql/permanent_storage_inventory_read_only.sql.

Follow-up 19:40 UTC confirms 493,984,565 cluster bytes and 478,710,931 current DB
bytes: 6,015,435 decimal bytes nominal cluster headroom, unchanged during this
check interval. The hosted timestamp is retained as returned, not relabelled to
the local Oct 6 date. A 19:41 metadata-only query shows outcomes' 60,178,432 total
includes 59,498,496 TOAST bytes and only 393,216 index bytes. This is NOT proof that
all 59 MB is bloat; live cumulative payloads also live in TOAST. Ledger's 55,500,800
total includes 43,089,920 TOAST bytes, with no recorded deletes. It needs evidence-
preserving retention, not an index-only cleanup. Canonical universe stats have
326,547 cumulative deletes and 358,649 inserts; versioned universe has ZERO updates
and 124,827 cumulative inserts. These counters span the statistics interval
(database stats_reset Aug 25), cannot prove per-scan behavior or today's growth.
Reported live/dead tuples are estimates, not exact evidence counts. No compaction
or deletion conclusion is based on those estimates alone.

GitHub read-only fetch confirms research-self-check.yml on main is the existing
offline workflow, with no secrets inheritance. A database report must be a SEPARATE
restricted read-only job; do not add database credentials to offline quality tests.
The connector's workflow-run helper only covers pull-request runs, so it cannot
prove push checks and was not used as evidence that this commit is green.

## Choice after comparing the feasible families
1. Keep the existing Supabase project as a bounded operational hot store, initially.
   [Current pricing](https://supabase.com/pricing) states 500 MB/project and two active
   Free projects, no automatic backup entitlement. Its [size documentation](
   https://supabase.com/docs/guides/platform/database-size) uses the cluster sum and
   also describes organization-average restrictions. A second project is not a
   substitute for correcting unbounded history. Confirm actual quota before reuse.
2. [Neon's dated October 2 announcement](
   https://neon.com/blog/neon-free-plan-1-gb-per-project) offers 1 GB/project,
   100 CU-hours/project/month, six-hour restore. It is the fallback Postgres host
   if the existing project cannot be safely reduced. Cold starts/compute caps and
   role/query compatibility require commissioning; it is not unlimited free uptime.
3. [Render Free](https://render.com/docs/free) expires after 30 days: reject for
   durable safety/audit state.
4. [Turso](https://turso.tech/pricing) offers 5 GB Free storage, 500 million rows
   read and 10 million written monthly, but it is not drop-in Postgres. Replacing
   SQL, RLS, locks, drivers and restore tooling would be a larger migration risk.
5. Existing licensed private Drive capacity (owner reports 5 TB) is the cold tier.
   Its [download API](https://developers.google.com/workspace/drive/api/guides/manage-downloads)
   supports retrieving original bytes for independent verification. Respect
   [Drive request limits](https://developers.google.com/workspace/drive/api/guides/limits),
   backoff and single-batch retry identity. Do not place data in public Actions.
6. [Cloudflare R2](https://developers.cloudflare.com/r2/pricing/) has a 10 GB-month
   standard-storage free tier and request allowances. An S3-compatible independent
   backup is attractive later but adds account/credential/charge controls. It is not
   needed to solve current storage when private Drive already exists.
7. Paid Postgres, short-lived credits and an awake PC as the sole archive service
   do not meet the owner's current constraints. Local SQLite is useful for offline
   recovery/cache, not the shared hosted operational authority.

Bounded storage changes the F&O recommendation: a separate database is NOT required
merely for capacity if the same project reaches the proven budget. Sharing one hot
Postgres avoids duplicate secrets/backups/monitoring; keep namespaces and roles
separate. Choose separate Postgres only for independently demonstrated isolation or
availability needs, or if physical allocation cannot safely reach the target.
This supersedes the emergency's provisional Neon preference, not its storage hold.

## Steady-state admission, not an arbitrary number of retention days
storage_policy.py specifies every existing application table, nine derivatives and
the bounded root, ledger-control and protected hot-head tables: 238 MB total allocated relation budgets
(heap/index/TOAST), plus 70 MB allowance for other cluster/catalog usage: planned
total 308 MB. All figures decimal bytes.
10 MB is reserved within that total for derivative tables. It is a design target,
not a measured capacity guarantee; adding archive/control tables must update it.
Warning at 350 MB; stop initiating non-essential writes at 400 MB; emergency at
450 MB; leave 50 MB for essential durability/recovery before the nominal 500 MB.
Admission includes explicit planned allocation, <=60-second fresh measurements,
complete inventory, unknown-table and per-table overshoot checks. Positive growth
can tighten permission; apparent shrink cannot relax a threshold.
A table budget is not achievable by deleting active dependencies or changing
evidence interpretation. If protected hot data exceeds it, stop non-essential
production and alert. Critical monitoring and already-created evidence are not
discarded. No trade is approved by a storage report.
Thresholds still need transaction-level integration across ALL writers, with a
shared short advisory admission lock and bounded payload/row batches. This module
alone does not enforce SQL writes or send alerts.

## Ledger segments: original events, authenticated cold lookup
Implemented core: ledger_segments.py builds deterministic bounded gzip segments,
pins file SHA256, applies a separate HMAC seal, verifies ORIGINAL v1/v2 signatures,
requires original key IDs, and checks contiguous per-aggregate chain boundaries.
It retains every signed field and original event hash. Unknown old keys block,
not silently fall back to the current key. Archive key bytes are never serialized.
The verification tests include real SQLite and durable Postgres writer output.
A size limit on decompressed bytes rejects compressed bombs, concatenated members
and trailing content. Restoring only checks bytes and produces records; it does not
write into a hosted database or authorize deletion.
Version-1 hosted compatibility remains an owner proof: legacy format counts alone
cannot demonstrate validity without the old keys/retained original material.
A further read-only query confirms all 43 v1 key IDs are NULL. Verification uses
only an explicitly bound legacy-schema-v1 key; no current-key fallback is allowed.

The next layer is essential for a PERMANENT solution:
- Immutable paged cold catalog indexed by aggregate and idempotency identity,
  content-addressed pages, bounded page size, authenticated root in Postgres.
- A fixed/rotating root and bounded HOT frontier, not one forever-growing SQL anchor
  or idempotency row for each historical event/aggregate. Old roots/pages live in
  verified Drive history; independently retained root checkpoints detect rollback.
- Appends first resolve cold duplicates/frontier; network happens outside SQL locks.
  Commit checks the same catalog generation under the aggregate/admission locks.
  Archive commits compare exact original rows, signatures, selected range/count,
  catalog generation and dependent hot references; crash/retry states are explicit.
- Protected unresolved/open-position aggregates stay hot. Entirely cold aggregates
  can reopen only after verified frontier lookup. Never restart sequence at genesis.
- Readers merge verified cold segments with hot rows and reject missing, overlapping,
  replayed or corrupted history. Raw SQL joins for matured_decision_dataset,
  decision_outcome_records and outcome reconciliation must migrate too: events()
  and a continuity checker alone are insufficient coverage.
- Local SQLite recovery and pending outbox use the same identity/frontier rules.
  At-least-once retries of an archived idempotency key must not mint a new event.

The [signed-log integrity model in RFC 5848](https://www.rfc-editor.org/rfc/rfc5848)
is relevant for sequencing, origin authentication and missing-message detection.
This implementation is NOT an RFC 5848 implementation or a blockchain. Hashes do
not prove external truth or availability; key compromise and root rollback remain
separate threats. Private Drive is not WORM: independent signed/root receipts and
restore drills are required, plus a second private copy for irreplaceable history.

## Non-ledger archival and physical allocation
Extend existing lossless verified Parquet export and exact row matching to every
growing table. Every table needs explicit schema/key/protection/reader/restore
tests, not a catch-all dynamic DELETE or all-fields blob with no restore contract.
Budgets describe protected hot windows in storage_policy.py. NAV keeps newest per
scheme; cold historical lookup replaces old SQL history before shortening its
window. Canonical universe protection follows readers' references, not weekends.
Scan headers/candidates cannot expire while recovery, delivery or positions need
them. Daily-volume lookbacks count completed sessions, never calendar days.
Research periods remain frozen; cold storage does not authorize re-tuning.

[Postgres partitioning](https://www.postgresql.org/docs/17/ddl-partitioning.html)
offers physically removable partitions, but existing global unique identities,
cross-table references and ledger triggers prevent a blind conversion. A rewrite
may require a second full copy. Do not attempt it inside 6 MB of quota headroom.
[Ordinary vacuum](https://www.postgresql.org/docs/17/routine-vacuuming.html) makes
dead space reusable but may not shrink allocated files; physical compaction or a
verified restore into a fresh project requires a separately approved owner window.
The final acceptance criterion is actual repeated cluster measurements below
target, not merely low live row counts or archive logs.

## Remaining implementation and acceptance order
1. Complete immutable cold catalog and signed-root receipts; test gaps, overlap,
   concurrent root changes, duplicate retries, corruption and key rotation.
2. Build archive repository/Drive transport with exact row transaction proof and
   restricted invoker SQL permissions. Test crash points before/after each phase.
3. Integrate all remote/local readers and recovery; demonstrate full-chain restore
   plus original hashes/idempotency behavior after hot deletion on disposable SQL.
4. Extend per-table archiving/protection/restore and NAV policy. Inventory all
   actual references, including logical/JSON references that foreign keys miss.
5. Enforce global/table guards at every initiating writer; create bounded alert
   state with independent notification and missed-report detection.
6. Add separate read-only daily report job, private Drive trends/receipts, no data
   artifacts public, stale measurements fail closed.
7. Freeze one upload group with migrations/runbook, full tests/lint/types/app boot;
   owner reviews and applies. Agent performs NO hosted writes.
8. Supervised archive/restore trials, physical allocation decision if needed,
   observe collection/archive cycles and quotas before lifting derivative hold.
9. Only if storage acceptance passes, produce the optional high-level F&O roadmap.

Existing migration credential is NOT a generic review-draft executor. In
.github/workflows/scheduled-collector.yml it is passed only on an explicit manual
apply_migrations input to `scheduled_collector.py --migrate`, which calls the
repository's built-in migration path. That path currently replaces the ledger
mutation function and drops/recreates its immutable triggers. Before ledger archive
guards are installed, it must be revised/tested so a later owner migration cannot
silently overwrite the reviewed archive guard. Normal runtime ensure_schema uses
validation, not this DDL path. Do not dispatch the owner migration workflow as a
shortcut to applying this unfinished design or the derivative SQL drafts.

Current proof: offline seal/policy cores and a paged Merkle catalog plus cold reader
prototype tested. cold_catalog.py preserves old roots, bounds page/value size,
verifies every content hash and rejects missing pages rather than asserting absence.
ledger_cold_store.py prepares bounded prefix segments, indexes both event UUID and
idempotency identities in the cold tree, and restores multi-segment history and
hot tails against an independent terminal head. A 900-event boundary batch fits
the 2000-update catalog bound and restores all 1803 cold entries. Metadata itself
lives in cold pages, not an SQL row per historical event. No SQL/network integration
or deletion authority is implied by these offline prototypes.
catalog_receipts.py signs an exact next generation including scope, predecessor
root and predecessor receipt hash. Verification requires an independently trusted
anchor and explicit signing-key ID; no automatic bootstrap on missing SQL state.
This protects linkage, not SQL atomicity or rollback of both object and anchor.
The 70 MB other-cluster allowance is now enforced by storage_policy.assess, and
cold-only readers reject duplicate UUID/idempotency identities across segments,
even if their signatures are otherwise valid.
The CLI-generated review-only root-control migration is local only. Its two-scope
anchor table has monotonic predecessor checks, explicit owner-only bootstrap,
runtime read-only access, a separate restricted archiver with update-only access,
RLS enabled/forced, no public execute or ledger DELETE grants. It rejects unknown
control versions/policies and unsafe existing roles rather than silently repairing
them. Reruns preserve committed roots. Disposable SQL tests exercise the actual
draft, role denials, root replay/skipped generations and transaction rollback.
This is metadata scaffolding, NOT the atomic archive/delete repository or a
ready-to-apply storage group. No hosted migration or anchor bootstrap performed.
The migration filename came from `migration new` on pinned CLI2.119.0, not a
hand-invented timestamp; see [official CLI reference](
https://supabase.com/docs/reference/cli/supabase-migration-new) and [pinned release](
https://github.com/supabase/cli/releases/tag/v2.119.0). CLI cache in supabase/.temp
is not part of the upload group. No login/link/db command was run.
Local milestone 5 adds `ledger_archive_publication.py` and
`ledger_archive_repository.py`: original native PostgreSQL JSON text is pinned
per selected row, private objects are uploaded and re-read, sealed originals and
both UUID/idempotency locators are checked, then a root lock/CAS and sorted
aggregate advisory locks protect a bounded SQL transaction. Source DELETE and
root advancement commit together. Source UPDATE is not granted: DELETE acquires
row locks and its guard checks the exact native-row digest after any wait.
Proof staging is one parameterised insert (900 rows/4500 parameters maximum),
not one round trip per event while holding the root lock. PostgreSQL17's
[transaction timeout](https://www.postgresql.org/docs/17/runtime-config-client.html#GUC-TRANSACTION-TIMEOUT)
caps the complete transaction at30s, in addition to statement30s/lock2s. A
per-statement timeout alone would allow a long multi-statement transaction.
The repository explicitly begins, commits and rolls back: the existing
ProductionRepository connection context only closes a connection and must never
be mistaken for committing it. Tests deliberately use a non-committing context.
Native timestamp formatting is also tested on PostgreSQL: JSON strips trailing
microsecond zeroes, whereas the original Python signer uses datetime.isoformat.
SourceCapture recovers that UTC representation for signature validation but pins
the untouched native JSON row separately for deletion. No event is rehashed to
make a mismatch pass. Unsupported legacy material/numeric normalization still
retains the source and requires compatibility proof, not guessed reconstruction.
An already-committed retry requires the exact successor root, all source UUIDs
absent, and a fresh remote verification; it never issues a blind retry delete.

The second CLI-generated review draft installs a one-row owner commissioning
control, disabled by default. It refuses wrong owner/role/version/policy shape,
retains UPDATE immutability, gates DELETE to the dedicated archiver, and checks
small indexed TEMP proofs rather than keeping another payload copy in Supabase.
Deferred triggers reject deletion without root advancement and root advancement
without complete deletion. They are additional transaction protections, not
proof of remote upload: the private archiver is trusted to run the publication
verifier; SQL contains no Drive credential or HMAC key. Runtime cannot commission
or delete. No owner commissioning steps are ready yet; all readers and unresolved
dependencies must be integrated before this control may be enabled.

Disposable SQL and offline private-object tests cover native rows, missing/altered
objects, wrong receipts/row proofs, disabled commissioning, skipped deletion by
another trigger, rollback, and safe repeated commits. Driver-native UUID handling
preserves original hashes. These tests do not establish real multi-connection
advisory-lock serialization or compatibility of the legacy production signing key.
The private Drive transport is now implemented locally, not yet commissioned or
wired into runtime/archive workers. Its tests inject HTTP responses; they do not
establish hosted identity access or Drive licence compliance.
Transport design check: Google's [custom-property documentation](
https://developers.google.com/workspace/drive/api/guides/properties) distinguishes
`appProperties` (restricted to the creating app) from `properties` (visible to
applications that can access the file). Do not copy the old app-private batch
discovery scheme into a different-identity cold reader and assume it can find
those files. New objects need cross-client content-addressed discovery using
non-sensitive kind/digest metadata while the files/folder remain private.
Per [Drive scope documentation](
https://developers.google.com/workspace/drive/api/guides/api-specific-auth), keep
runtime reading credentials separate from the existing write OAuth credential.
The owner must commission folder access and test discovery using the actual
reader identity; a synthetic transport cannot establish that permission.

Missing proof: production reader/writer integration and committed live anchors,
hosted guard integration/alert, all-table archival/restoration, full recovery after
pruning, nightly reporting and measured steady-state operation. Goal stays active.

Milestone6 transport: `cold_drive_objects.py` pins My Drive folder, kind and SHA,
requires private user-only sharing on folder AND file, refuses shared drives,
incomplete/paginated/duplicate searches, and verifies bounded downloaded bytes.
It creates objects only in explicit worker mode; default runtime mode is GET-only.
Existing objects are never overwritten/deleted, and an uncertain upload is
rediscovered and reverified before retry. Non-sensitive cross-client `properties`
support a different Viewer identity; no private payload/key is put in metadata.
Actual [file-list](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/list)
and [permissions-list](https://developers.google.com/workspace/drive/api/reference/rest/v3/permissions/list)
behaviour must be checked with that identity before source pruning. In particular,
uninspectable ACLs must block commissioning, not justify granting the app write access.
Credential parsing accepts only the fixed Google OAuth endpoint/default universe
and read-only scope, forwards no subject/delegation/quota-project fields, and
masks provider exceptions. TLS verification is explicit; redirects are refused.
No import starts a connection or reads a credential.

The legacy ProductionRepository migration path used to unconditionally replace
ledger mutation triggers. It now takes the same transaction advisory lock as
both review drafts, checks for the protected namespace, and refuses all legacy
DDL when present or unverified. This closes the check/DDL race between cooperating
paths; it does not protect against an owner deliberately bypassing that protocol.
Runtime schema validation is unchanged. The tested protection is not a replacement
for future cold-aware append/readers, protected terminal heads or all dependencies.

Milestone7 adds a CLI-generated, review-only protected hot-head migration. Heads
track only aggregates with hot rows and reserve2 MB; cold-only terminals stay in
the signed cold catalog. Tracking is disabled by default, and pruning now requires
tracking plus an explicit owner audit hash. There is no bootstrap from whichever
rows happen to survive during an ordinary read. The owner must verify available
original signatures and pin the terminals before enabling tracking; this cannot
prove pre-commissioning tail retention without an older independent receipt.
An actual insertion advances its head atomically in an AFTER trigger, so skipped
ON CONFLICT rows and rollbacks cannot create future heads. Full archival retires
the head only in the root's deferred commit check, after exact source deletion;
prefix archival retains the independent terminal. Cold reappend is gated by a
frontier proof bound to the protected root and reviewed reader fingerprint.
Application append preparation now verifies the snapshot's original chain,
the cold frontier and the global cold idempotency locator before opening a write
transaction. This is NOT insertion authorization: a writer must compare the
protected root and hot terminal again under locks before using that evidence.

The trigger-only [SECURITY DEFINER boundary](https://www.postgresql.org/docs/17/sql-createfunction.html#SQL-CREATEFUNCTION-SECURITY)
is intentional: the runtime and archiver get SELECT, never direct head mutation.
Private schema, fixed search path, checked trigger context and revoked public/
worker execute privileges restrict its use. Privileged code never reads arbitrary
caller views or custom types: staged objects must be physical temporary heap
tables with exact built-in columns, no RLS/rules/generated expressions. Otherwise
a caller's view could execute code under the owner's privileges. Hostile-view,
custom-domain, table/column/function grant and role-denial tests exercise this
boundary. Actual ACL/owner configuration and real concurrency still need owner
acceptance; no hosted advisor or mutation has been run.

`ledger_runtime_reader.py` takes root, hot rows and protected terminal in the same
bounded repeatable-read READ ONLY transaction, releases SQL, then verifies the
private receipt/pages/segments and original event HMACs. Missing objects/keys or
heads never shorten a successful result. Native PostgreSQL clocks are normalized
to the original signer representation without changing hashes. ProductionRepository
events can route through an injected reader; the hosted factory/configuration,
the live cold-aware append factory, other SQL joins and local recovery are NOT wired yet. Existing
tests restore before/after archival and merge a signed cold prefix with a later
hot event, including a2474-event hot chain crossing both capture/signature chunk
boundaries. Hot GUI reads are capped and require pagination rather than silently
truncating oversized histories; full historical streaming remains acceptance work.

### Append transaction integration constraint

`prepare_append` returns only verified original evidence, with no open database
transaction or deferred Drive request. Unknown signing keys, unavailable objects,
invalid retry identities and hot/cold identity overlap block preparation. A cold
retry lookup is global, even when its original aggregate differs from the new
request, allowing the writer to reject a conflicting request rather than reuse
an archived identity. Original signatures are not regenerated.

Writer integration needs a narrowly scoped protected-root locking
boundary. PostgreSQL locking reads require privileges beyond ordinary SELECT;
runtime must NOT receive broad catalog UPDATE solely to acquire a lock. Archive
and append must use the same root-before-aggregate order, compare the prepared
root and terminal, and roll back/re-prepare outside locks when either changed.
No Drive request may run while holding these SQL locks. See the official
[PostgreSQL lock documentation](https://www.postgresql.org/docs/17/explicit-locking.html).
Preparation alone does not commission cold-aware writes or permit live pruning.

The local writer integration now uses `lock_ledger_append` in the third unapplied
review draft. This intentional private SECURITY DEFINER boundary only acquires
locks and checks the exact primitive temporary proof; it does not edit permanent
metadata. Runtime has EXECUTE on this one function but no catalog UPDATE rights.
Known public/research/archive roles have no EXECUTE; unexpected grants fail review.
It checks commissioned reader fingerprint, protected root and expected hot head,
using root-before-aggregate order. Stale proof aborts; no HTTP runs under SQL locks.

An explicitly configured ProductionRepository verifies its active signing key
is present in the reader keyring, prepares history before opening the write
transaction, stages proof, and inserts against the verified original predecessor.
Cold retry identities restore all original signed fields and use the existing
request equality rule; conflicts cannot create new evidence. Shared sender
connections retain per-event commit/rollback and can recover after a failed retry.
Only stable reviewed control codes escape cold-writer driver failures.
The app/collector factories are still UNWIRED; other SQL readers/recovery paths,
large-history streaming, bootstrap and hosted concurrency acceptance remain open.
Do not commission pruning from these component tests alone.

Authenticated catalog traversal now enumerates cold-only aggregates rather than
discovering them from remaining SQL rows. Global audit checks original signatures
and identities across hot and cold history, with identical protected root/head
fences before and after traversal; concurrent changes fail the audit. A yielded
prefix is not an audit certificate: callers must exhaust the iterator successfully.
No SQL transaction remains open during Drive requests.

Optional training and readiness readers consume these verified originals, keeping
the decision/outcome pairing semantics and original feature values. Tests compare
actual legacy SQL results with results after complete verified archival, including
microsecond timestamps. Missing cold objects raise errors instead of producing an
apparently valid empty dataset. Local recovery, live
factory wiring and bounded historical spooling/streaming remain acceptance gaps.
The SQL test bridge now preserves positional duplicate-name columns and timestamp
precision, so its behavior matches the relevant psycopg contract more faithfully.

The optional pending-outcome reader now verifies original decisions/outcomes
before its scanner query. A bounded JSON array supplies only original pending
aggregate IDs and horizons to a read-only SQL join; no permanent staging writes
or current feature recomputation. Count/byte overflow blocks, never truncates.
It uses the verified reader's own connection source, releases SQL before the
final root/head fence, and sanitizes driver failures. Any matured original blocks
pending collection even when its payload is empty, matching the existing NOT
EXISTS rule. NULL horizons/targets stay absent; malformed horizon/target types
fail closed. Fixtures compare actual legacy SQL before/after complete archival.

### Recovery expectations and legacy fallback

An archived generation cannot be interpreted as an empty or shortened hot-only
ledger. Unconfigured readers check storage genesis and read source rows in the
same bounded repeatable-read/read-only transaction; missing controls, malformed
genesis or nonzero generations block. Unconfigured writers reject cold generations
before aggregate/retry lookup. SQL head/stage guards remain the independent race
boundary for a concurrent archive commit; no new mutation permission is granted.

The original-ledger recovery witness covers count and an ordered digest of signed
original identities. Each original HMAC and chain is verified before the witness
is certified; a prefix, empty target or intact previous-hash links are insufficient.
Expected witnesses must come from a reviewed source audit, never from the target.
The target reader must be constructed with the explicit target connection. Owner,
BYPASSRLS and privileged-role membership are refused; SELECT-only roles do not
need INSERT to run this scoped check. No values or raw driver errors are printed.

Known Supabase direct/pooler project aliases and Neon pooled/unpooled endpoint
aliases are normalized when checking source versus target URLs. Identity-changing
libpq query overrides are rejected. This does not prove network isolation for
unknown proxy aliases: endpoint ownership still requires owner review. A PASS
certifies original ledger recovery only; application_recovery_verified remains
false until the other data/recovery dependencies are restored and checked. The
CLI fails closed until its trusted source witness and private target reader are
wired. No production factory or automatic hosted restore has been enabled.

All storage read contexts share one explicit transaction initializer. SET
TRANSACTION enforces isolation/read-only mode even if a wrapper already issued
BEGIN; a prequeried weak transaction fails rather than silently keeping weaker
isolation. Callers always roll back. See [PostgreSQL transaction modes](https://www.postgresql.org/docs/17/sql-set-transaction.html).

### Local recovery is a distinct evidence domain

The app constructs ImmutableEvidenceLedger against its local SQLite file, not
against the remote Postgres ledger. The local ledger also contains events that
were never queued for remote delivery. The sender passes original request fields
to the remote repository; the remote repository creates its own signed envelope.
Matching an idempotency key does not imply identical local and remote event hashes.
Do not splice remote cold originals into the SQLite chain or use a remote witness
as a substitute for local verification.

Before commissioning archival, recovery acceptance must separately verify local
original chains, local pending outbox entries and remote committed receipts,
including crash-after-remote-commit/before-local-ack retry behavior. Pending
deliveries and their predecessors must remain available. Remote archival cannot
authorize deleting local events or outbox rows. Scan checkpoints are a third
dependency: the existing checkpoint readback explicitly is not a disaster recovery
test. A whole-application recovery claim requires all three domains, not just the
new original-ledger DR certificate. These checks and factory wiring remain open;
no SQLite pruning or repair has been implemented or authorized.

