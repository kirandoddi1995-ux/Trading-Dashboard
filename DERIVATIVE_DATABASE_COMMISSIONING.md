# Derivative database commissioning — owner-run only

## Recommendation

Do the read-only inventory now. Creating the empty derivative schemas is reasonable **after** the inventory matches the prerequisites below. Enabling scheduled collection or calling the protection system operational is premature. Keep the option-entry hold and all derivative jobs off during the database stage. Nothing in this package has been executed against Supabase.

## 1. Freeze enablement, not the existing archive pipeline

In GitHub Actions variables, confirm `DERIVATIVE_REFERENCE_ENABLED` is unset or `false`. Leave the option recorder off and do not start `derivative_monitor.py` or its watchdog. Do not change the working Drive archive schedule or its settings. Confirm no other host is already running the derivative processes.

**Expected:** no new derivative collectors start. The dashboard can remain fail-closed. If a monitor was in fact already running with real obligations, do not stop it without a separate monitoring plan.

## 2. Establish actual database state

Open Supabase **SQL Editor → New query**, paste the complete contents of `sql/derivative_readiness_inventory_read_only.sql`, and run it. Save/export the single `readiness_inventory` JSON cell locally, with today's date. This query works when both derivative schemas and roles are absent. It reads catalogs and sizes only, not positions, credentials or tokens. Negative estimated row counts mean unknown, not empty.

**Expected:** a JSON report with nine expected derivative table names, present/absent flags, application table columns/constraints, role attributes and memberships, effective derivative grants including column writes, derivative RLS policies, trigger/function fingerprints and database size. It does not change anything.

Use it to establish these earlier feature footprints (presence alone does not prove the full migration or its permissions were applied):

- Drive base: `quant_app.archive_manifests`, `market_daily_volumes`, and the volume-capture trigger on `market_quotes`.
- Drive scanner/universe extension: the manifest source-table constraint includes both source names; the prediction-target foreign key is RESTRICT, not CASCADE; archive permissions need separate verification if that pipeline is in doubt.
- Drive research outcomes extension: outcome protection triggers and function fingerprints exist. Fingerprints are comparison aids, not a claim the function is correct. Do not rerun that draft merely because a function name exists.
- Equity recovery/manual review: `equity_operations.scan_runs`, `scan_candidates`, `manual_quote_reviews`; the fencing extension adds nullable `checkpoint_fencing_token` to candidates.
- Positions and execution reconciliation: `equity_operations.positions`, `order_intents`, `order_results`.
- Research: `equity_research.source_decisions`, `observations`, `outcomes`.

An SQL Editor execution is not necessarily recorded in `supabase_migrations.schema_migrations`. Its existence or absence is not authoritative migration history. This inventory establishes objects, not who applied which file when. Do not bulk-run all old drafts: some use plain CREATE and some replace constraints/functions.

**Stop here** if any derivative table already exists with an unexpected column/constraint/policy, or if you cannot interpret an existing grant. Review the saved report before applying scripts. Do not paste passwords, connection URLs or secret settings; this report intentionally never selects password catalogs.

## 3. Check prerequisites and access boundaries

`quant_app_runtime` must already exist. For it and the three derivative roles, `superuser`, `bypass_rls`, `create_role`, `create_db`, `replication` must all be false. Application/research/worker roles must not own derivative tables or schemas. Inspect memberships in both directions: a research role inheriting or able to assume a privileged role defeats a direct REVOKE. NOINHERIT alone does not prevent SET ROLE. Unexpected memberships or effective access require review, not wider grants.

The drafts create missing derivative roles without passwords and never change existing role attributes/passwords. Existing roles with dangerous attributes are rejected. Existing memberships, table shapes and same-named policy definitions are **not automatically repaired**. Existing excess grants are not guaranteed to be removed by rerunning. The inventory is therefore a real stop gate, not a formality.

Roles used for direct connections also need LOGIN; review an existing role with `login=false` rather than assuming these scripts enable it. No password validity is inspected by the inventory.

Expected access after both drafts, beyond owner/admin administration:

- `quant_app_runtime`: SELECT the five named reference tables and four monitor tables; INSERT reference `decision_snapshots`; UPDATE **only** `alerts.acknowledged_at`. No table-wide UPDATE, DELETE, TRUNCATE or schema CREATE.
- `quant_derivative_ingestor`: SELECT/INSERT `contract_versions`, `source_snapshots`, `source_health`; UPDATE only `source_health.status`, `updated_at`, `source_hash`. No exchange-rule/monitor-record publishing or monitor-table access.
- `quant_derivative_monitor`: SELECT reference `contract_versions` and `exchange_rules`; SELECT all four monitor tables; INSERT/UPDATE `state`, `positions`, `alerts`. No reviewed-record publishing, DELETE or TRUNCATE.
- `quant_derivative_watchdog`: SELECT monitor `state` only; no positions or alert writes.
- `equity_research_collector`, `anon`, `authenticated`: no derivative schema/table/column access. Also inspect `quant_archive_worker` and `service_role`: there is no intended archive or Data API access here; unexpected effective grants are a stop condition. Keep both schemas out of the Data API exposed-schema list. Do not add REST grants to fix the Python connection.

The report separates table-wide privileges from column writes. For example runtime should have no table-wide UPDATE but should have `acknowledged_at:UPDATE` on alerts. Every one of the nine tables must have RLS enabled. Owner SQL Editor reads bypass ordinary RLS and cannot alone prove the runtime role works.

**Expected:** the intended permission set above, with no unsafe inheritance/ownership. Handle passwords and database URLs privately in your own dashboard/secrets, never in chat or repository files. Do not replace the runtime connection with postgres/admin to silence an error.

## 4. Save a recovery reference; apply foundations only

Save the inventory and a schema definition export locally before changes. If derivative tables already contain rows, obtain and verify a data backup before altering their security configuration. Do not assume the plan supplies a restorable backup.

Paste the **entire** reviewed `sql/derivative_foundations_review_only.sql` into a new SQL Editor query and run it once. Its dependency is the existing restricted runtime role, not any Drive/equity draft. It creates schema `derivatives_reference`, five tables and the ingestor role if missing. It grants named-table access and enables RLS. It neither inserts market records nor creates passwords.

**Expected:** success; rerun the inventory and see all five reference tables, RLS enabled and the listed grants. Monitor tables may still be absent. No obligation to change the app yet.

If an error occurs, stop. Run `ROLLBACK;` if the editor reports an aborted transaction, then rerun the inventory. Each file has BEGIN/COMMIT plus lock/statement timeouts: a failure before COMMIT does not intentionally publish a partial file. A lost client response can occur after a successful commit; inspect instead of assuming failure. Do not execute just the remaining lines.

## 5. Apply monitoring second

Only after step 4 verifies, run the **entire** `sql/derivative_monitor_review_only.sql`. It requires all five foundations tables and the runtime role. It creates schema `derivatives_monitor`, four tables and missing monitor/watchdog roles, and adds monitor SELECT policies on two reference tables.

**Expected:** all nine tables present and RLS enabled; role/grant inventory matches step 3. No broker records, scheduled tasks, cron jobs, emails or token handling start from this SQL.

These files can be rerun on their expected schema: tables/indexes/roles/policies are conditionally created, grants are repeatable, and the corrected ingestor read policy can be restored independently. This is **not** automatic reconciliation of arbitrary old tables or modified policies. Stop on drift; never DROP a table to make a rerun pass.

## 6. Verify runtime reads and the actual screen

Run the complete `sql/derivative_runtime_smoke_read_only.sql`. It temporarily assumes `quant_app_runtime` inside a read-only transaction, reads at most one row per table and rolls back. If your editor shows only the final ROLLBACK result, select the SELECT result in its results view; do not omit the role/transaction setup.

**Expected:** nine result rows, role `quant_app_runtime`, `rls_active=true` throughout and `visible_sample_rows=0` for empty tables. Existing data may show 1; this is a bounded sample, not a count. Permission errors or false RLS mean stop. A failed script may need `ROLLBACK;` before the next query. This tests role permissions, not the app's password or destination database.

Then reload the deployed options page, using the latest reviewed error-message changes:

- Settlement panel should say **“Monitor has not reported. New derivative entries are blocked.”**
- Entry preflight should say **“Current master/reviewed exchange rules unavailable.”**
- Option entry remains held. No READY/green protection claim is expected yet.
- Continued UndefinedTable means wrong project/connection target, incomplete script, or different deployed code—not a reason to widen privileges. “Database access denied” means investigate intended runtime role/grants/RLS. The generic unavailable banner can also mean a connection failure or that the latest UI fix was not uploaded.

## 7. Set a storage budget before any ingestion

Empty tables/indexes should be small (planning expectation: well below a few MB); use the inventory's actual bytes, not that estimate. The substantial cost starts with collection, not CREATE TABLE.

Growth drivers in the actual code:

- Contract versions are deduplicated by payload hash, but a changed contract record creates a new version.
- Source snapshots retain a compressed scoped master plus an instrument→version JSON manifest **per trading date and source hash**. Identical data on a new date still creates a snapshot; changed snapshots on the same date also accumulate.
- Selecting one underlying means its returned contracts across strikes/expiries, not one contract. The 30-underlying/10,000-record checks are ceilings, not recommended sizes or lifetime storage limits.
- Exchange rules, reviewed monitor records and eligible decision snapshots accumulate. Monitor state is one row; alert conditions are upserted; positions are retained per account/instrument/product, so new expiries grow that table over time. Frequent updates also create dead tuples until vacuum reuses the space.

Illustrative arithmetic, **not a forecast**: if a scoped daily manifest plus compressed source is 0.3 MB, unchanged contract versions still add about 6 MB over 20 sessions. If 1,000 contract versions also change daily at 1.5 KB each, add another 30 MB before index/tuple overhead, reviewed records and decisions. Measure the real universe: either regime is possible depending on master contents. Do not multiply a single-quote size by underlying count.

At 83% of a nominal 500 MB limit, nominal headroom is about 85 MB **before existing growth**. PostgreSQL database bytes and the dashboard quota display need not match exactly; watch both. Suggested temporary commissioning budget: 5 MB net derivative growth, daily measurement, and stop new derivative reference ingestion on reaching that budget or 85% total quota, whichever comes first. These are manual operating limits, NOT automatic code safeguards. Do not disable monitoring of real obligations to save space.

First permit only a reviewed, small, one-off ingestion after the timestamp issue and source checks below are addressed. Measure before/after bytes, exact contract counts and snapshot compressed/manifest sizes. Existing Drive archiving has **no derivative retention integration**. Before unattended ongoing accumulation, review a verified archival/restore policy protecting all contract/rule versions referenced by positions and decisions, and sources needed for lineage. No blind 14-day derivative deletion; no archive grants are added here.

## 8. Separate commissioning after the database stage

Do not yet set `DERIVATIVE_REFERENCE_ENABLED=true`. The current workflow uses the same switch for scheduled AND manually dispatched ingestion (08:45 IST weekdays); it is not a preview switch. SQL application does not change this variable.

Remaining gates before calling the system running:

1. Fix/test the previously identified collector receipt-time issue before using captures as first-known evidence; currently collection-start time is reused after network downloads. Verify a real hosted master and NSE ban file (including known-empty versus failed-download handling).
2. Owner-reviewed exact contract/session/expiry rules, corporate-action review and applicable expiry-specific broker policies must be published using official sources, not placeholder test fixtures. There is no automatic rule-population job. Rules are tied to exact master versions and session dates; ongoing review is necessary, not a one-time seed.
3. Privately configure reference, monitor and watchdog connections for their distinct roles. `DERIVATIVE_REFERENCE_DATABASE_URL` is the ingestor secret. The monitor uses `DERIVATIVE_MONITOR_DATABASE_URL`; the independent watchdog uses the same variable NAME in its own environment, but with the watchdog role's separate connection. Never share the monitor credential with the watchdog.
4. Privately configure broker account identity consistently between Streamlit `[derivatives_monitor].account_id` and the monitor's `DERIVATIVE_MONITOR_ACCOUNT_ID`, plus `DERIVATIVE_MONITOR_TOKEN` and `DERIVATIVE_ALERT_SMTP_JSON`. Missing/expired broker authentication must yield AUTH_REQUIRED, not an empty portfolio. No credentials are needed to apply the schemas.
5. Commission a host/cadence and separate heartbeat watchdog; there is no automatic deployment from these migrations. Observe broker reconciliation, a retained alert, receipt in your inbox, retry after controlled failure and a stopped-monitor alarm. SMTP acceptance is not proof of inbox receipt. Do not create a real position solely to test obligations.

The dashboard normally only reads these tables, except manual alert acknowledgement and recording an **eligible** preflight decision snapshot. With empty rules/monitor state the latter cannot pass. Once references and monitoring are valid, eligible futures paths can write decision snapshots during normal analysis; the option-specific hold is not a global futures-write switch. Ingestor and monitor processes write only when explicitly run by their host. Creating tables does not itself start any of them.

## 9. Back out without destroying history

- **Before COMMIT/error:** ROLLBACK and inventory. The foundation and monitor files are separate transactions; a failed monitor file does not undo a successful foundations file.
- **After successful empty-schema creation:** safest backout is leave the inert tables, keep new jobs disabled and retain the option hold. Do not DROP roles/schemas, use CASCADE, remove RLS or replay equity/archive drafts. The storage cost of empty tables is small.
- **After data starts arriving:** disable new reference ingestion if needed, preserve positions/rules/alerts and continue independent broker checks. Do not stop the only operational monitor while obligations exist without a replacement. Review any targeted security reversal against the saved inventory. No general destructive rollback is included because it could discard evidence or break dependencies.

## Local changes and verification

The two existing derivative drafts now have explicit prerequisites, unsafe-role rejection, transaction timeouts and named-table read grants; the foundations draft repairs a missing ingest read policy independently. No app behaviour, passwords, hosted settings or retention rules changed. New inventory/smoke scripts are read-only diagnostics, not migrations. Tests run only in a disposable local PGlite database.

Full local suite: **1,024 passed, 4 skipped, 2 subtests passed**, with **one warning** from the existing local TLS negative-test server thread receiving a connection reset during certificate rejection. No failing tests; the warning was not suppressed or described as hosted verification. Focused derivative SQL tests: **12 passed**. Changed-test Pyflakes check passed. Application release fingerprint is unchanged; no Streamlit secret update is required for these SQL/documentation/test changes.

PostgreSQL reference: https://www.postgresql.org/docs/current/ddl-rowsecurity.html (owners/bypass roles and privilege/RLS interaction); https://www.postgresql.org/docs/current/functions-info.html (effective privilege checks). Manual SQL Editor execution and hosted connection behaviour still require your verification.
