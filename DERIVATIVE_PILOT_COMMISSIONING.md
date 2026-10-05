# NIFTY intraday safeguards: staged commissioning

**Storage hold, independently verified 2026-10-05 18:16 UTC:** cluster size
493,984,565 bytes leaves only 6,015,435 nominal decimal bytes below 500 MB.
Do not install derivative schemas or run the reference pilot in this project now.
See STORAGE_EMERGENCY_2026-10-05.md for the superseding sequence and separate
database design decision. The pilot's 24 MB admission requirement is not met.

This supersedes the ingestion/storage sequencing in DERIVATIVE_DATABASE_COMMISSIONING.md.
It is an owner-run plan, not confirmation that hosted safeguards are operational.
The 471,936,147-byte measurement is historical. Obtain fresh measurements first.
No migration, collection, order or deletion runs when this document is uploaded.

Quota reference: [Supabase database-size guidance](https://supabase.com/docs/guides/platform/database-size).
The 500 MB database-size threshold is distinct from the free disk allocation;
SQL cluster measurements and dashboard usage both matter. Restricted access and
fail-closed diagnostics follow the Supabase guidance reviewed for this change.

## Storage and boundaries

Keep raw forward bars, chain snapshots and replay inputs in the existing private
Drive archive, outside the public repository and Supabase. Existing option capture
and Windows forward tasks are independent; this change does not disable them.
Do not put market-data bundles in public Actions artifacts or releases.

Supabase keeps small operational references, reviewed rules, source health,
decision lineage, monitor state, positions and active/retry alert state. Source
snapshots retain only watchlist-scoped master records, not the full exchange master.
Historical contracts/rules cannot simply expire: decisions, adjustments and
monitoring may still depend on them. No derivative archive/delete path exists yet.
Build verified export, restoration and dependency-aware retention before recurring
reference ingestion, not a blind seven- or fourteen-day DELETE.

The CLI pilot uses conservative fixed decimal-byte admission thresholds:
500,000,000 nominal quota, 20,000,000 reserve, 4,000,000 pilot allowance,
10,000,000 combined derivative allocation budget, and 1 MiB per retained source.
It checks sizes, all nine tables/RLS and the restricted role on each new connection.
Missing measurements/permissions fail closed; do not grant a broad monitoring or
owner role to bypass a denied size query. The allowance is a planning estimate,
NOT a transaction size cap or quota guarantee. Other writers, indexes, TOAST and
concurrent sessions can consume headroom. Relation allocation counts indexes/TOAST;
it does not count every schema/function/catalog allocation.

This guard covers the reference CLI only, NOT runtime decision snapshots or monitor
upserts. Critical position monitoring should not be disabled to save disk. Do not
commission new live entries until operational write growth and recovery are proven.
SQL tables alone should remain empty except explicitly reviewed work.

## Owner steps, in order

1. Upload the complete local change group, preserving `.github/workflows/`, `tests/`
   and `sql/`. Wait for checks on the final main commit and checked release promotion.
   Update the Streamlit fingerprint expectation afterwards using the reviewed local
   hash, not an actual hash copied from the live screen. Build/policy are unchanged.
   Expected: all release expectations valid and matching; missing derivative banner
   remains until SQL is installed. No job is dispatched by uploading these files.

2. Leave `DERIVATIVE_REFERENCE_ENABLED=false`. Do not alter research/archive switches.
   Run `sql/derivative_readiness_inventory_read_only.sql`, then
   `sql/derivative_pilot_storage_read_only.sql` in the Supabase SQL editor. Also check
   Database Size usage on the dashboard. Save results privately with timestamps.
   Expected: nine absent tables, safe roles, no unexplained objects/grants, fresh size.
   Stop for owner review if partial derivative objects exist, roles are unsafe, or
   size disagrees materially with dashboard. Do not assume the old measurement.

3. Require at least 24,000,000 bytes nominal headroom for a pilot and review current
   collection bursts. Empty installation is smaller, but measure its actual effect.
   If headroom is insufficient, continue Drive research only and investigate existing
   storage through read-only checks. No quota-override, unverified cleanup or
   VACUUM FULL. This package does not delete evidence.

4. In SQL editor, review and run `sql/derivative_foundations_review_only.sql` as owner.
   Expected: commit, five reference tables; restricted ingestion role; no records.
   Run the inventory and storage SQL again. Stop if grants/RLS/size are unexpected.
   After any SQL error, stop and run `ROLLBACK;` in that session before fresh
   read-only checks. Do not continue or commit an aborted transaction. The draft's
   transaction prevents a partial installation from being committed.

5. Review and run `sql/derivative_monitor_review_only.sql` as owner. Expected: four
   more tables, monitor/watchdog roles and explicit policies. Repeat both read-only
   checks. Run `sql/derivative_runtime_smoke_read_only.sql`: nine readable empty tables
   as runtime, not permission errors. Existing drafts are transaction-wrapped and
   rerun-tested locally, but do not repair arbitrary schema drift automatically.
   Do not drop schemas to undo a problem. Stop writers, preserve records and inspect.

6. Configure the restricted `quant_derivative_ingestor` login privately in Supabase,
   then its connection in GitHub `DERIVATIVE_REFERENCE_DATABASE_URL`. No credentials
   in files, chat, SQL result exports or logs. Set `DERIVATIVE_UNDERLYINGS_JSON` to
   `["NSE_INDEX|Nifty 50"]`. Keep recurring switch false. Never use runtime/owner URL.
   `DATABASE_MIGRATION_URL` is NOT this URL and is NOT a derivative migration path:
   the scheduled collector's `--migrate` handles quant_app and its dispatch continues
   into collection. Do not dispatch that workflow to install derivative drafts.

7. Actions → Derivative reference ingestion → Run workflow on fully checked main →
   mode `preview`, confirmation unchecked. Expected PREVIEW, network_calls 0, writes 0.
   Then mode `check`, confirmation unchecked. This uses read-only database sessions
   with a ten-second statement timeout/two-second lock timeout; it does not fetch
   provider data. Expected PILOT_STORAGE_CHECK with empty blockers. A failed check
   stays failed; owner investigates permissions/tables/size instead of broadening role.

8. On a reviewed regular NSE session, supervise ONE mode `pilot` run with confirmation
   checked. It can write despite the recurring switch remaining false. No push/PR
   trigger exists. The workflow serialises runs; Python rejects schedules even if
   someone asks them to pilot. Scheduled enabled runs currently perform checks only.
   Expected SUCCESS with a nonzero NSE contract count. The ban download is the real
   hosted-access test; a failed fetch leaves pending health UNKNOWN and entries blocked.
   Receipt timestamps are now observed after response processing, never request start.
   A successful master and failed ban are possible: they are separate transactions,
   not an atomic all-sources commit. Do not treat SUCCESS as broker/quote validation.

9. Repeat inventory/storage SQL immediately after the pilot and after the next normal
   collection/archive burst. Inspect current-date master/ban source health privately
   and confirm both READY, matching hashes and receipt times. Record actual byte delta
   and timestamps. Do not retry pilots repeatedly to probe storage. The app should
   replace UndefinedTable with specific missing-reference/review/monitor blockers,
   NOT become trade-ready. An empty monitor is not a reported healthy monitor.

10. Owner reviews actual exchange contract conventions and dated rules, ban-source
    provenance, broker product/square-off policy, corporate-action/expiry safeguards
    and dated cost sources. Hashes establish identity, not truth. Existing cost model
    is not commissioned; an assumed ₹20 brokerage is still an assumption. Intraday
    NIFTY does not remove expiry, product or forced-square-off risks. Capture-only
    analytics token access does not prove account-position permissions.

11. Commission monitor on owner-controlled suitable static-IP host, restricted monitor
    login and verified broker account/position read access. First use recorded/sanitised
    scenarios, never open a real position merely for a test. Verify auth failure,
    stale poll, position reconciliation and email receipt. Commission an independent
    watchdog and failure alert path; a fresh AUTH_REQUIRED heartbeat is not healthy.
    Owner controls host, SMTP, secrets and scheduling; no hosted steps run here.

12. Before recurring ingestion or live suggestions, require verified dependency-aware
    retention, measured growth over collection/archive bursts, independent alerts and
    recovery drills. Then commission aligned executable quotes and the cost/margin
    engine against dated official inputs and broker observations. Keep option-entry
    hold and all evidence gates unchanged. Snapshot capture is research-only and is
    not continuous executable replay. Parked rules remain parked; 2025/2026 frozen
    research data remain unexamined; no automated tuning or order placement.

## Local validation

Run `.venv\Scripts\python.exe -m pytest -q tests/test_derivative_commissioning.py`.
For full SQL-inclusive tests, set `EQUITY_TEST_PGLITE_MODULE` to the existing local
`tests/sql-harness/node_modules/@electric-sql/pglite`, then run the full suite.
Run `python -m mypy --config-file mypy-automation.ini` in the same tested environment.
The existing full suite includes the offline app boot and disposable SQL migrations.
