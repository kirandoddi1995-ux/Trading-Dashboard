# Inactive storage candidate, 13 October 2026

## Outcome and ownership

New offline implementation for assigned E/F/G/H/Q. Existing sources, factories,
installed capture, actual data, hosted services, credentials and workflow settings
were not edited or accessed. Public documentation research is the only external
read. Main owns capacity measurement/alerts, Telegram, all packaging/wrappers and
the combined clean-public/full-suite/native verification record.

F remains PARTIAL ENGINEERING, not complete or merely externally blocked. No
production factory was switched and no global enforcement/cold-reader wiring is
claimed. There is no deletion primitive in this candidate. References, signatures,
owner review and even an otherwise satisfied plan never grant deletion authority.

## Exact files created by this stream

All destinations are relative to C:/Users/banga/Desktop/kiran_share_market:

1. overnight_storage_contracts.py
2. overnight_storage_journal.py
3. overnight_storage_factory_adapter.py
4. overnight_storage_harness.py
5. overnight_storage_switching.py
6. overnight_storage_sources.py
7. overnight_storage_staged_factories.py
8. overnight_storage_native_acceptance.py
9. overnight_storage_native_fixture.sql
10. tests/test_overnight_storage_contracts.py
11. tests/test_overnight_storage_journal.py
12. tests/test_overnight_storage_switching.py
13. tests/test_overnight_storage_sources.py
14. tests/test_overnight_storage_staged_factories.py
15. tests/test_overnight_storage_native_acceptance.py
16. tests/test_overnight_storage_custody_binding.py
17. OVERNIGHT_STORAGE_2026-10-13.md

No upload checker, JSON manifest or shared wrapper is owned here. Prefix-named
pytest temporary directories contain synthetic scratch artifacts, not package
members. The workspace has no usable Git repository; do not treat local source
identity or the selected reads as verification of public main.

## Implemented function coverage and limits

E: capacity_runway composes storage_capacity_watch and storage_transition. It
preserves 500,000,000-byte planning and the 24,000,000-byte floor, charges reviewed
owner-delay backlog and transient database/disk peaks, and gives no future
reclamation or dedup credit. Missing bounds, stale inputs, mismatched measurements
or unknown trends do not produce bounded runway. No operation/alert journal or
Telegram adapter was added.

F: switching.inventory parses supplied source bytes without import/execution.
Its 18-source lower-bound inventory includes app factories, ProductionRepository,
scheduled_collector, EquityScanRepository, ResearchRepository/collector,
DerivativeRepository/monitor, positions, model registry/training, mutual-fund
archive, prospective feature writer, runtime evidence, archive repository,
recovery drill and evidence-progress reader. Every callable in the selected
repository classes is conservatively listed, including connection/shared-reader
methods. Missing sources/symbols are explicit. Main must pass its actual clean
public bytes and pin; local held sources are NOT public-base proof. The local-only
ledger_historical_repository factory is deliberately not a required dependency.

invoke_staged executes three actual existing methods through an injected borrowed
session inside storage_write_guard.append_transaction: ProductionRepository.start_run,
EquityScanRepository.create_run, DerivativeRepository.mark_pending. SQL is accepted
only against exact trusted statement fingerprints for those methods. This is not
a SQL sandbox or an arbitrary/untrusted factory callback API. The only outward
results are bounded plain data. Session/cursor closure and transaction-state checks
block later use, including handles nested in result containers. Deferred legacy
commit requests cannot silently introduce a second commit/session. Allocation
limits (500k/1M) are declared SYNTHETIC fixture bounds, not measured production
bounds; non-fixture drivers are rejected before repository construction.

The fixture production instance explicitly assumes prevalidated fixture tables
and does not run full application schema validation. Real schema/role migration,
cached Streamlit factories, dynamic deployments and other callable methods are
not accepted by these three tests. They require further engineering and native
tests, not just reference hashes. Legacy multi-transaction, lease, special-lock,
reclamation and original-receipt methods must have dedicated migrations; no
generic connect-wrapper can safely change their semantics.

SourceRouter uses exact authenticated catalog lookup and tier-independent byte
readback, decoder witnesses and optional hot/cold parity for all 45 table identities
in storage_policy.BUDGETS. Missing per-source decoders fail closed. It does NOT
implement or switch every existing business historical-reader method; original
event/ACK semantics and consumer-specific reconstruction remain integration work.
bind_six_table_recovery calls the existing recovery_custody_rehearsal verifier
and then requires a signed exact source/candidate/catalog-generation/bundle/report
binding. Bundle and catalog generations are different namespaces. The existing
report's physical-custody/encryption/full-application limitations are preserved.

G: dedup_shadow and SourceRouter.shadow build real copy-on-write cold_catalog
patches and ShadowEntry maps. Raw content hashes are shared only within source;
snapshot, interval, revision and witness identities remain distinct. Old roots
stay readable. No raw fields are stripped, rounded or overwritten. Fixtures show
six-week repeated payloads becoming six content versions while retaining 42
snapshot identities; business payload normalization/backfill is not implemented.

H: per-source exact identities and supplied source cutoffs, count/byte bounds,
same-generation/root readback+restore witnesses, dependency/delivery blockers,
all-writer inventory, lookup parity and migration references gate bounded staged
plans. Source-specific latest/active/unknown states stay protected. Control,
schema, lease and frontier sources are always protected. The source contract
hash locates the expected policy; it does not prove dependency closure. Unknown
closure blocks. These are review candidates, never source locks, custody
commissioning or deletion capabilities.

Q: 21/28/42/84-day end-to-end cycles integrate authenticated catalog generations,
shadow maps, two named synthetic tiers, decoding/readback, retained bounded plans,
capacity runway, durable stage/verify/review journal state and guarded appends.
Mid-cycle corrupt/partial/clock/revision/full-disk/fencing/unknown-commit failures
retain the staged/verified interrupted candidate and previously reviewed days;
subsequent days do not run. Separate tests cover missing pages/keys, altered pins,
oversized reads, wrong source/revision, replica duplicates, custody/report cut
mismatch, SQLite allocator-full behavior, restart/idempotence conflicts and
durable fencing/revision CAS. This is a bounded synthetic rehearsal, not proof
of arbitrarily long steady-state storage or physical independent replicas.

The SQLite journal is only SYNTHETIC orchestration replay state (4096 records,
8192 metadata bytes, SQLite page limit, FULL synchronous commits). It discovers
no production path, never creates an existing journal, and never blindly retries
uncertain commits. Its hashes detect accidental corruption; no protection from
an attacker rewriting the whole file or faulty hardware is claimed.

## Verification and remaining work

### Main integration extension

The final group additionally includes exact-query repository routes, cold method
results, six-table materialization, and an actual-schema universe raw-payload
shadow (overnight_storage_universe.py and its tests). The universe projection
accepts only the two exact membership schemas and canonical supplied export rows,
keeps snapshot/date/instrument/source/observed metadata unchanged, shares only
identical raw objects, and reconstructs every original row with exact hash parity.
Duplicate PKs, altered objects/metadata, extra fields, missing objects, naive clocks,
forged authority and oversized inputs block. Original archive generations remain
primary. This is source-specific normalization engineering, not a hosted schema
backfill or verified Postgres reclamation. The 27 added tests pass. Final group
counts and the complete public suite are in the programme ledger.

The initial stream's 181-test count below is an intermediate result, not the final
extended package result. The final manifest/runbook is authoritative for paths;
the engineering stream's earlier file list omits Main's extensions.

Initial stream focused aggregate: **181 passed, zero failures/skips, 13.95 seconds** across
all seven new test files. The earlier strict parameter validator rejected the
production repository's genuine psycopg Jsonb wrapper; the new adapter now permits
only the exact default Jsonb type with bounded canonical JSON and no custom dumper.

Ruff passed on all 15 new Python source/test files. The earlier six-file strict
type run passed; a later expanded run exposed five new-test typing issues, which
were corrected. Final strict types INCLUDING ALL SEVEN TEST FILES and full-suite
verification must run in Main's clean-public candidate, not this dirty source
tree. They are not yet claimed passed. No assertion or test was removed and no
new skip was added. Default temp-folder permission errors were resolved using
fresh prefix-named workspace temporary directories.

Main executed the staged runner on local PostgreSQL 17.6: **four cases passed**
(three actual existing methods committed; accepted native commit with lost reply
reconciled without retry). Main also reported the original 23 shared native cases
passed. These are distinct results, not expanded-method/native or full production
factory coverage. Main owns the service, fixture provisioning and manual workflow.
No Docker mutation was performed by this stream. Hosted changes remain zero and
global enforcement/allocation commissioning remain false.

After Main provisions overnight_storage_native_fixture.sql as fixture admin in
the exact storage_conformance_sandbox database, run:

`python overnight_storage_native_acceptance.py --execute --confirm-disposable --port 55443`

Default invocation is preview with zero network calls. Execution uses only the
existing fixed loopback connector/public fixture password, verifies the shared
restricted profile and database marker, then requires the additional staged
fixture marker. No URL/password/env/passfile is discovered. Native cases are the
three existing methods and accepted native commit plus lost client reply with
explicit row-count reconciliation, no retry. Full production allocation bounds,
application-schema migration and global wiring remain false after a pass.

Engineering still needed: migrate/test remaining inventoried writers and consumers,
derive actual maximum-input allocation bounds, add original-receipt and business
decoder routing per source, close deployment inventory, implement consistent
source locking and readback/root publication across the real transports. External
commissioning still needed: independent authenticated measurements/delivery,
original keys, encrypted physically independent copies, durable external anchors,
licensed retention terms and independent full-application restore. No owner
attestation substitutes for these prerequisites. Packaging stays with Main.

## Official documentation researched

Supabase skills (including the advisory-lock reference) were read before database
work. The changelog markdown was fetched directly after the web tool rejected its
content type; no Supabase implementation/migration was run.

- [PostgreSQL transaction isolation](https://www.postgresql.org/docs/current/transaction-iso.html): a snapshot and exact row identity are required; serial synthetic tests do not prove native race acceptance.
- [PostgreSQL advisory locks](https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS): transaction-held locks coordinate cooperating participants; they are not global quotas.
- [Supabase Storage access control](https://supabase.com/docs/guides/storage/security/access-control): authenticated transport/authorization remains a separate adapter gate.
- [Supabase Storage optimizations](https://supabase.com/docs/guides/storage/production/scaling): object storage is a distinct tier, not implied database capacity relief.
- [Supabase changelog](https://supabase.com/changelog.md): checked for current compatibility; no remote project calls.
- [Amazon S3 object integrity](https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html): the candidate measures full content hashes; an object identifier/ETag is not used as content authentication.
- [Parquet file format](https://parquet.apache.org/docs/file-format/) and [page checksumming](https://parquet.apache.org/docs/file-format/data-pages/checksumming/): format/page integrity does not replace authenticated whole-file source manifests and recovery witnesses. No Parquet business decoder or writer is claimed here.
