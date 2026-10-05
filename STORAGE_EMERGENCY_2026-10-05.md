# Storage emergency: verified findings and owner sequence
Date: 2026-10-05. No hosted changes were made by the agent.

## Decision
Treat this as an immediate storage incident, not spare capacity for derivatives.
Defer derivative installation and reference ingestion in the existing project.
With paying/pausing unavailable, remove avoidable writes, use the existing verified
archive where its predicates permit, and measure actual allocation after maintenance.
Neither a new F&O database nor ordinary vacuum guarantees relief for the old ledger.
There is no safe promise of indefinite operation inside 500 MB with an unbounded
append-only ledger; ledger tiering needs its own tested restore/read design.

## Independent checks
The connector ran as postgres (owner/BYPASSRLS), NOT a restricted read-only login.
Each check used BEGIN READ ONLY, a 10-second statement timeout, a 2-second lock
timeout, and ROLLBACK. Exact queries are in sql/storage_emergency_read_only.sql.
Block 1 returned relation statistics; its first SELECT was not retained by the
connector, so block 2 deliberately repeated the size measurement.
Block 5 initially failed on an unquoted alias; the corrected SELECT succeeded.
Only catalog, sizes, counts, retained dates and master-field differences were read.
No prices, historical rule performance or frozen research outcomes were examined.
No passwords, connection strings or raw market rows were printed or saved.

At 18:16:26 UTC: cluster 493,984,565 bytes, current database 478,710,931 bytes,
matching the owner's 18:05 measurement exactly. Nominal decimal headroom:
6,015,435 bytes (6.015 MB), NOT 21.3 MB inferred from the current database alone.
The earlier current-database increase was 6,774,784 bytes. At that pace one
comparable active day exceeds current headroom. This is a scenario, not a daily
forecast: allocation occurs in bursts and free pages may be reused.
All nine derivative tables were absent. Existing three application/archive/research
roles have login but neither superuser nor BYPASSRLS. No long transactions over
five minutes, prepared transactions, replication slots or active vacuum were found.

Block 1 relation allocation, decimal bytes, includes indexes and TOAST:
- universe_membership_versions: 82,534,400 total; 64,413,696 heap; 18,071,552 indexes.
- market_quotes: 80,969,728 total; 59,154,432 heap; 21,766,144 indexes.
- scanner_observations: 61,505,536 total; 44,326,912 heap; 6,791,168 TOAST.
- outcomes: 60,178,432 total; 253,952 heap; 59,498,496 TOAST.
- universe_membership: 56,418,304 total; 44,818,432 heap; 11,550,720 indexes.
- evidence_ledger_events: 55,500,800 total; 6,971,392 heap; 43,089,920 TOAST.
- mf_nav: 43,532,288 total; 36,978,688 heap; 6,504,448 indexes.
- market_daily_volumes: 8,306,688 total; 4,481,024 heap; 3,784,704 indexes.

Block 2 found 445 actual outcomes, 89 decisions, 33,409,348 stored payload bytes,
newest recorded October 2 07:17:19 UTC. The 534 estimate was stale. Difference
between live payload and allocation is NOT a proven recoverable bloat estimate.
There are no new outcome rows after October 2: this is not today's growth source.
The completed-cohort candle redesign is lower urgency than the ledger.

Today's universe has TWO versions, TWO hashes, 5,360 version members, not one
version per scan. Date/hash identity is deterministic. Local PIT changed=True can
reflect a fresh local store; it does not prove a new remote version.
However, archive_universe previously deleted/rebuilt canonical members on every
unchanged call, creating churn. The patch skips those writes and member conflict
attempts for existing versions, preserves first-observed time, and serializes writers
per date. A repeated canonical header with a missing member count now errors
instead of certifying incomplete data. Real revisions and new dates remain retained.
The two current master representations differ in many raw fields across all 2,680
matching keys. This suggests differing writer representations; it does NOT justify
dropping fields or merging historical hashes. Cross-writer normalization is separate.

Block 2/5 ledger: October 5 added 1,669 events / 5,102,225 stored payload bytes.
760 DECISION_EVALUATED events account for 3,323,555 bytes and ten batch evaluations
for 1,406,011 bytes. This is LIVE append-only evidence, not update/delete bloat.
October 4: 985 events / 2,380,669 bytes. September 28–October 1 each had roughly
1.3 MB/day despite far fewer events: scheduled batch evidence also grows.
The patch removes automatic first Quick Scans on page load/redeploy, not audit
writes from requested scans. The scheduled collector remains unchanged.

Block 3 normal eligibility: outcomes 0, market_quotes 0, NAV 706.
Zero eligible can be a successful archive run; no new manifest alone does not
prove a scheduled job failed. The other 14-day tables can still grow inside their
window with more observations, versions or instruments.
Block 5 NAV candidate at cutoff October 4: 61,235 older rows with a newer row for
the same scheme. No catalog foreign keys reference NAV, outcomes or ledger.
Absence of foreign keys is NOT absence of application dependencies.
Local dashboard NAV history comes from external providers, not this table; its
durable overview counts NAV rows. Scheduled collection writes AMFI NAV daily.
External consumers/restore users are not proven absent.

## Owner steps: read-only before every write
1. Review/upload the complete group below. Keep ARCHIVE_ENABLED and
   ARCHIVE_DELETE_ENABLED at their reviewed current settings; do not enable
   derivatives. Wait for checks on the exact newest main commit and checked release
   promotion. Update Streamlit EXPECTED_EQUITY_CODE_SHA256 only after promotion,
   at TOML root; use the reviewed hash in AUTOMATION_PROGRESS.md. Expected outcome:
   release expectations match; opening Quick Scan shows a button and creates no scan.
   Existing running delivery and explicit scans still operate.

2. In Supabase Reports check Database Size and infrastructure disk/WAL usage;
   also run blocks 1–5 separately if desired. Save totals/time only, not credentials.
   Expected: cluster matches approximately, and fresh eligibility counts are known.
   Do not treat database-only bytes or table row estimates as quota headroom.
   The official dashboard metrics can lag. Do not infer free filesystem space from
   database quota alone.

3. Run the existing archive workflow manually on main in preview for currently
   eligible sources. It is "Verified Drive archive (7-day outcomes, 14-day other
   sources)" under Actions. No SQL migration or DATABASE_MIGRATION_URL is needed.
   Expected: normal NAV may show about 706; outcomes/quotes may show zero.
   Run export mode, max_batches=1, before a trial deletion for any nonempty source.
   Expected: selected/verified match, deleted=0; export deliberately tests one batch,
   not a full export. Existing row-match protection and verification stay intact.

4. If you approve moving old NAV evidence to private Drive, use the workflow's
   EXISTING nav_cutoff field, initially 2026-10-04 (recompute date/count if later).
   Table mf_nav, mode preview, batch_size=100, max_batches=1. Expected at the
   checked date: 61,235 candidates; newest per scheme survives by SQL predicate.
   First confirm no external reader requires this hot history. This is a one-time
   cutoff, NOT a change to the scheduled 14-day policy. Do not drop mf_nav or
   delete unexported rows simply because F&O is now the main focus.
   Then mode export with identical inputs: verified=selected, deleted=0.
   Only after review choose delete, max_batches=1, batch_size=100.
   Expected: exported/verified/deleted all match; retained=0. Inspect the Drive
   manifest and restore-format evidence. Stop on mismatch or archive error.
   After the trial, reviewed bounded runs may use batch_size=1000, max_batches=10;
   repeat previews between runs until eligible_remaining=0. The job concurrency
   group already serializes archives. A completed export is not yet a successful
   restore test; validate a downloaded batch with the existing verifier offline
   before relying on it as the only copy. Keep the manifest and original schema.

5. Owner only, after fresh blocker checks and archive acknowledgement: run ordinary
   VACUUM (ANALYZE), each separately and outside any transaction block:
   VACUUM (ANALYZE) quant_app.mf_nav;
   VACUUM (ANALYZE) quant_app.scanner_observations;
   VACUUM (ANALYZE) quant_app.universe_membership_versions;
   VACUUM (ANALYZE) equity_research.outcomes;
   VACUUM (ANALYZE) quant_app.market_daily_volumes;
   A completion with low dead counts means cleanup, NOT guaranteed physical shrink.
   Keep measurements before/after each. Free space is table-specific: NAV cleanup
   cannot absorb ledger inserts. Ordinary vacuum may truncate empty end pages.
   Do NOT run VACUUM FULL, CLUSTER, REINDEX or rebuild/drop a large primary key now:
   locks, WAL and temporary duplicate allocation require a separate capacity plan.

6. Repeat cluster/relations/live ledger-day bytes after maintenance, after the next
   archive, and after the next collection. Expected: dead counts reduced; unchanged
   universe calls no longer rewrite rows; no new outcomes absent real changes.
   If allocation fails to fall sufficiently, this package has NOT solved runway.
   No changes were made to policy thresholds or platform read-only protection.
   SQLSTATE 25006/53100 means write failure; do not claim remote recovery/durability
   from local pending outbox. Follow owner-reviewed provider recovery guidance or
   escalate to provider support rather than automatically overriding read-only mode.

## Ledger-safe longer-term relief
Never apply generic age-based deletion, truncate, disable append-only triggers,
or reset hashes/sequence numbers. Existing recovery/idempotency readers depend on
the ledger and full chain. Drive export alone is insufficient permission to delete.
Next implementation: sealed immutable contiguous chunks per aggregate, schema
and row hashes, first/last sequence and predecessor hashes; verified offline
restoration plus archived/live chain readers and durable idempotency lookup.
Only then an explicit anchor/checkpoint migration with tested rollback and owner
approval can release database history. Keep signing material private and retain
decision dependencies; no silent genesis reset. Current code does NOT implement
this tiering. This work takes priority over new strategy variants or derivative
collection. Payload normalization/content-addressed blobs can reduce future copies,
but is a schema/provenance change, not dropping risk/control fields to fit a quota.

## F&O storage choice
Bulk bars/options/forward bundles stay in licensed private Drive. Operational
references, reviewed rules, positions, monitor state and alert retries belong in
transactional Postgres, not files polled as the live safety source.

Verified official sources on October 5, 2026:
- [Supabase pricing](https://supabase.com/pricing): 500 MB/project, two active Free
  projects, inactivity pausing, no included automatic database backups.
- [Supabase size guidance](https://supabase.com/docs/guides/platform/database-size):
  cluster sum is reported Database Size; 500 MB Free read-only threshold is separate
  from 1 GB disk. It ALSO documents organization-average fair-use restrictions.
  Do not assume a second project automatically escapes the organization's quota;
  confirm the dashboard/account treatment before relying on this option.
- [Neon October 2 announcement](https://neon.com/blog/neon-free-plan-1-gb-per-project):
  now 1 GB/project (older 0.5 GB pages are stale), 100 CU-hours/project/month and
  six-hour instant restore window. Extra storage is not unlimited free uptime:
  a continuously awake 0.25 CU for 30 days would use 180 CU-hours.
- [Render free docs](https://render.com/docs/free): free Postgres expires after
  30 days. Not appropriate for persistent safety/audit state.

My choice for a separate F&O database is a small Neon project, conditional on
verified compute/connection/cold-start behaviour and owner acceptance. This avoids
depending on unclear shared Supabase organization headroom; it is NOT commissioned
or a fix for the equity ledger. Same-provider second Supabase remains an alternative
only after its quota treatment is confirmed. Keep equities where they are for now:
moving everything urgently is a much larger recovery/identity/secret risk.

Before ANY new database owner step, implement and test dedicated F&O routing for
runtime, ingestor, monitor and watchdog; no fallback to equity or owner credentials.
Today app derivative reads use the durable equity connector: changing only the
ingestor URL would NOT split the system. Portability of roles/RLS/extensions and
quota measurement must be tested on disposable Postgres; the current Supabase
cluster-size admission query cannot be assumed portable to Neon permissions.
Prepare explicit owner project/create-role/secret/migration/verify/restore steps
once the routing patch exists. No new hosted project or settings are requested by
this emergency patch. Monitor/watchdog cadence must not silently exhaust compute,
and a free service's downtime must block entries, not bypass controls.

## Complete upload grouping
If the earlier 12-file derivative commissioning group was not uploaded, upload
that complete group listed in AUTOMATION_PROGRESS.md together with this patch.
Its new module is already part of the release fingerprint; partial upload is unsafe.
This patch adds/changes these seven paths (existing pilot/progress replace earlier copies):
- app.py
- production_repository.py
- tests/test_universe_storage_sql.py
- sql/storage_emergency_read_only.sql
- STORAGE_EMERGENCY_2026-10-05.md
- DERIVATIVE_PILOT_COMMISSIONING.md
- AUTOMATION_PROGRESS.md

With the earlier 12-file group and two overlapping documents, the combined reviewed
package has 17 unique paths. In addition to the seven above, those ten dependencies are:
- derivative_commissioning.py
- derivative_repository.py
- equity_runtime_health.py
- mypy-automation.ini
- .github/workflows/derivative-references.yml
- tests/test_derivative_commissioning.py
- tests/test_derivative_repository_sql.py
- sql/derivative_pilot_storage_read_only.sql
- DERIVATIVE_DATABASE_COMMISSIONING.md
- DERIVATIVE_FOUNDATIONS.md

Local PowerShell commands from the project folder (offline; no credentials):
```powershell
$env:EQUITY_TEST_PGLITE_MODULE = Join-Path (Get-Location) 'tests/sql-harness/node_modules/@electric-sql/pglite'
.venv\Scripts\python.exe -m pytest -q tests/test_universe_storage_sql.py -p no:cacheprovider
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
$lintFiles = @(Get-ChildItem -File -Filter *.py) + @(Get-ChildItem tests -File -Filter *.py)
.venv\Scripts\python.exe -m pyflakes $lintFiles.FullName
.venv\Scripts\python.exe -m mypy --config-file mypy-automation.ini
```
The SQL harness must already exist; do not count its skipped tests as verification.
Validation counts, reviewed fingerprint and final owner boundary are recorded in
AUTOMATION_PROGRESS.md. No requirement/lock changes, schema migrations, pushes,
hosted mutations, ledger deletions or research tuning are included.

Final verification: five targeted tests passed; full suite 1,742 passed, four
unchanged skips, two subtests passed. All root/test Python pyflakes clean; strict
mypy passed for 19 configured modules. Existing offline app boots/import checks
are included in that suite. Final self-review added missing-membership failure,
corrected old auto-scan comments and quota assumptions; no known patch defect found.
Real storage reuse, external NAV readers and provider commissioning remain unverified.

Reviewed EXPECTED_EQUITY_CODE_SHA256 after checked release promotion:
f7ff707c03609986b56276cc1a724d27b71e7ec6b977fccf0d43533e0feb30ae

