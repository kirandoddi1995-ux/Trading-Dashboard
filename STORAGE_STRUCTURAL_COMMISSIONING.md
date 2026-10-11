# Structural storage commissioning — review first, no writes authorised

The choice remains one hot Supabase database, immutable verified private Drive
history and an independently recoverable encrypted copy. Extra capacity on the
same database is preferable to adding another database merely to evade the quota.
No purchase or hosted setting change is authorised here.

## Morning steps that are safe now

1. Finish the encrypted current-key note; privately reopen it. Check historical
   key availability without reporting values. Do not rotate the original key.
2. Rehearse encrypted dummy files on the external disk. Keep real plaintext
   exports off that unencrypted disk. Preserve the independently expected backup
   contract/checkpoint separately from a replaceable backup bundle.
3. Run each block of `sql/storage_layout_inventory_read_only.sql` separately in
   Supabase SQL Editor, and retain the metadata privately. Run the one block of
   `sql/daily_volume_retention_read_only.sql` separately. These are read-only;
   owner/BYPASSRLS results do not prove restricted runtime access.
4. Check physical disk/WAL and quota-enforcement state in Infrastructure. Record
   the viewing time; a dashboard widget can lag. Do not treat WAL as quota space.
5. Leave scan-only recurrence, release hold and the installed NSE routine unchanged.

## Transition order and capacity decision

At the last owner reading, cluster allocation was 456,260,405 bytes. Preserving
the CURRENT 24,000,000-byte admission margin leaves only 19,739,595 bytes for
new transient database allocation, before reserving concurrent growth. This is
an illustration, not a fresh admission result or a reservation.

Do not credit future savings before old files actually disappear. Neither live
row estimates nor sampled distinct counts are a bound on a rewrite, dictionary
or new indexes. Unknown upper bounds block in `storage_transition.py`.

- First commission full original-ledger recovery, independent custody and all
  reader/factory paths. Seal a small exact dependency-safe prefix with no deletion,
  reopen it independently and compare original signatures/identities. Local sealing
  through `cold_local_objects.py` is now testable; it is not a replica or SQL commit.
- Shadow-normalise universe raw payloads without changing old snapshot hashes or
  PIT identities. Stage outside Supabase first. Compare every header/member/non-raw
  field and raw byte identity. This estimates real dictionary benefit without
  spending the narrow database transition allowance.
- If a reviewed live dictionary/shadow-table migration cannot fit at its peak,
  require owner-approved capacity on the existing database before copying. Do not
  improvise destructive in-place conversion to make it fit.
- Introduce future append-only quote/scanner partitions only after reviewing
  PK/unique/FK/trigger/RLS/role dependencies. A global unique key cannot simply
  become a partition-local key; PostgreSQL partition uniqueness includes the
  partition key. Keep the old table until exact transfer and readers are verified.
- Commission source-specific bounded cold readers and archive-before-retirement.
  Partition retirement must be dependency-aware with authenticated root, exact
  source identities, an already verified independent copy and restore evidence.
  Ordinary DELETE/VACUUM can yield reuse but does not establish a low physical peak.
- Enforce all-writer reservation/admission and independent capacity alerts, then
  demonstrate bounded allocation over the intended workload and backup delay.

No executable DROP/DELETE/partition-conversion SQL is included. Its exact form
depends on the inventory, original-key coverage, reader proofs and measured shadow
size. Those facts are not available tonight; an apparently runnable template would
hide the most important uncertainty.

## Source-specific protections

Read-only connected constraint inventory during this continuation confirmed:
market_quotes has PRIMARY KEY(observed_at,instrument_key); market_daily_volumes
has PRIMARY KEY(instrument_key,trade_date). These include possible time partition
keys, but do not alone approve routing/RLS/triggers/retention. Prefer quotes and
daily volumes for the first later partition feasibility study, not a blanket
conversion of every source.

scanner_observations has PRIMARY KEY(observation_id), referenced by
prediction_targets.observation_id with ON DELETE RESTRICT. Date partitioning
must preserve GLOBAL observation identity and that inbound reference; adding
date to a local key is not an equivalent design. The ledger also has global
event_id/event_hash/idempotency and aggregate-sequence uniqueness. Keep its
sealed-segment/protected-head design, not naive date partitioning.

Universe canonical/version membership keys are respectively(snapshot_date,
instrument_key) and(snapshot_id,instrument_key), with separate header foreign
keys. The dictionary adapter must preserve those distinct contracts.
This inventory establishes constraints, not all dependency/custody approvals.

Ledger: preserve original HMAC material, globally unique retries, protected heads,
active/recoverable references and every unreplicated segment. No payload trimming.
Current held production factories still do not instantiate the cold reader.

Daily volume: current collector uses the last 20 available non-null captured dates
PER INSTRUMENT strictly before as-of date. These are captured maxima, not certified
exchange daily volumes. Missing dates stay missing. The preview deliberately keeps
current/future/null rows and makes no training/PIT completeness or deletion claim.
Historical/as-of queries require an authenticated cold lookup, not only today's
20-date hot baseline.

Universe: protect current/latest complete and all referenced snapshot versions.
Share raw bytes without collapsing genuinely different headers/non-raw members.
Cold references participate in dictionary liveness. Never cascade-delete unresolved
scanner or research dependencies.

Outcomes: latest active decision/horizon evidence stays available, including
coverage-incomplete/unknown first touches. Frozen analysis must preserve original
source hashes and labels; completed horizon is not complete coverage. Bulk candles
belong in verified cold objects, not silently absent behind a broken hash pointer.

Quotes/scanner: preserve active/recoverable and research dependencies; archive
original raw quotes BEFORE future raw purging. Existing NULL raw values cannot be
recovered by assertion. Partition/session gaps remain visible to analytical readers.

## Acceptance still required

Owner real-key restore and encrypted-independent-checkpoint/replica custody;
factory wiring and all historical readers; actual PostgreSQL multi-connection
race/role tests; exact no-delete trial; verified archival trial; measured peak and
all-writer reservation; independent missed-run/capacity alert; ten representative
complete workload cycles plus an analytical worst-case capacity bound. A finite
free tier cannot guarantee unlimited history or unlimited backup lag.

Sources checked 8 Oct 2026:
[Supabase database versus disk size](https://supabase.com/docs/guides/platform/database-size),
[PostgreSQL partition constraints/locking](https://www.postgresql.org/docs/17/ddl-partitioning.html),
[PostgreSQL snapshot isolation](https://www.postgresql.org/docs/17/transaction-iso.html).
Supabase changelog markdown fetch was unavailable; HTML changelog was checked.
