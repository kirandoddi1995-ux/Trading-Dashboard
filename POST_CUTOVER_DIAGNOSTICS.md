# Post-cutover checks and owner steps

## Confirmed versus unverified

- Source: live_governance requires three independently configured equity
  expectations. RuntimeAttestor already names the missing internal keys, but
  EQUITY_GOVERNANCE_BACKLOG strips its message. Logs now include booleans for
  EXPECTED_APP_BUILD, RESILIENCE_POLICY_SHA256, EXPECTED_EQUITY_CODE_SHA256;
  Settings / Equity runtime health shows the same presence checks. No values
  from Secrets are printed. Presence is NOT proof of a matching or valid value.
  RELEASE_EXPECTATION_MISSING is an intended fail-closed control for missing
  configuration, not a finding that should remain indefinitely by design.
- Hosted Streamlit logs/Secrets were not accessible through the available
  connector. Which expectation is actually missing remains unverified; matching
  Secrets across cutover does not establish that all three existed beforehand.
  Do not self-default missing expectations to the running app.
- Supabase read-only connector reached project Trading-Dashboard as postgres
  (owner/BYPASSRLS). SELECTs within READ ONLY transactions, timeout 5 seconds:
  database 471,936,147 bytes; zero derivative tables; only quant_app_runtime of
  the four expected derivative/runtime roles exists, superuser=false and
  bypassrls=false. Owner access does not test runtime visibility. The configured
  app DATABASE_URL could still point elsewhere; verify its project privately.
- The nine missing tables explain UndefinedTable independently of permissions.
  No database changes were performed. Catalog inspection cannot prove which
  query in the hosted app failed without its traceback; a wrong configured DB
  remains a separate possibility.
- Source: _expected_latest_completed_session_date correctly considers Oct 2
  closed, then requires Oct 5 immediately at its reviewed session close.
  _fetch_upstox_history_impl requests daily history through today; it does NOT
  hardcode yesterday. The gateway may reuse a post-close response for 300 seconds.
  Thus repeated refetch attempts need not be fresh network requests. The logs
  establish a missing expected candle, not its cause: delayed publication/CDN,
  an API limitation or another provider problem still needs a real response.
  Upstox documents minor CDN delays for intraday candles but no daily-publication
  SLA was verified. Never guess a grace period or build a daily candle from LTP.

## Local changes

Freshness expectations/markers/cache TTL and safety gates are unchanged. Missing
today's completed candle is labelled EXPECTED_SESSION_NOT_RECEIVED, not CURRENT.
Missing an earlier session is STALE_HISTORY; an unknown calendar stays unverified.
Process-local, bounded, thread-safe diagnostics replace per-instrument warning
spam with one warning per expected session/failure kind and a current-day Settings
summary. Samples are capped at five. These are observations, not a universe-wide
readiness claim; restart resets them. Successful receipt updates the diagnostics.
Other evidence gates, the option hold and the outbox threshold remain unchanged.

## Owner: upload, fingerprint, expectations

For exact TOML placement and value-free per-key source/error diagnostics, follow
RELEASE_EXPECTATIONS.md. Settings and equity governance now use the same resolver;
presence alone is still not proof of a matching reviewed value.

1. Upload the complete changed-file group with folder paths intact, preferably
   one reviewed merge. Wait for the exact final main SHA's gates and successful
   release promotion. No direct upload to release.
2. Update EXPECTED_EQUITY_CODE_SHA256 in Streamlit Secrets only AFTER the new
   release is promoted, using its reported/local reviewed fingerprint. Until
   then the deliberate hash mismatch blocks equity entries. Preserve all other
   credentials and settings. This is a fingerprinted app change.
3. In Streamlit Settings / Secrets, inspect NAME presence at the top level:
   EXPECTED_APP_BUILD must match the reviewed APP_BUILD;
   RESILIENCE_POLICY_SHA256 must match the reviewed policy file hash;
   EXPECTED_EQUITY_CODE_SHA256 must match the promoted release hash. These are
   Streamlit Secrets, not Actions variables. Use the reviewed local report from
   `python equity_runtime_health.py`; it prints public hashes only. Obtain build
   from the reviewed app.py APP_BUILD assignment, not an assumed new version.
   Current reviewed build: v22.5.7-FUTURES-HISTORY-HOTFIX. Current policy hash:
   034f87b769d6b000cfcb5ec8d309ef8b487dc3b4aeab1be623eaa16e9b578466.
   These are public release metadata, not credentials. Other policy settings
   still require independent evidence; do not invent calibration to unblock.
4. After restart, Settings / Equity runtime health: all presence booleans true,
   correct expected hash, clock/recovery/checkpoint PASS. Scan governance logs
   must no longer report RELEASE_EXPECTATION_MISSING or CONFIG_DRIFT. Other
   calibration/execution blockers remain legitimate; configuration is not approval.
5. After the next session, inspect history_freshness and its sample expected/latest
   dates. At the next pre-open Oct 5 must be present. If not, obtain one authenticated
   daily-history response privately, recording dates/status/receipt time only,
   not headers/tokens/raw errors. Investigate provider delivery rather than change
   the required date. A retry within 300 seconds can hit the same gateway snapshot.

## Owner: derivative database commissioning, independently

Installing empty tables does not start ingestion. It is reasonable after the
full existing read-only inventory passes; starting ongoing ingestion at this
headroom is not. Empty schema overhead should be small, but is not measured on
this host: compare actual before/after database AND nine table/index sizes.
The existing collection workload and dashboard quota must retain headroom.

1. Keep DERIVATIVE_REFERENCE_ENABLED unset/false; do not start a monitor/watchdog
   merely by installing SQL. Do not change existing archive settings. The
   separate supervised option recorder writes Drive, not these database tables.
   This supersedes the older commissioning guide's blanket recorder-off step
   and its stale 83%-capacity illustration; leave the already supervised recorder
   and unrelated archive controls alone. Use today's dashboard quota/measurements.
2. Run sql/derivative_readiness_inventory_read_only.sql. Save the report privately;
   check project, role attributes/memberships, effective grants and latest quota.
   Review DERIVATIVE_DATABASE_COMMISSIONING.md prerequisite/access sections.
3. Save a schema recovery reference. Run the ENTIRE reviewed
   sql/derivative_foundations_review_only.sql as owner in SQL Editor; rerun inventory.
   Then run the ENTIRE sql/derivative_monitor_review_only.sql; rerun inventory.
   Do not replay unrelated archive/equity drafts. Each file is transactional with
   timeouts; inspect after any error/disconnection rather than assume rollback.
4. Run sql/derivative_runtime_smoke_read_only.sql. It uses SET LOCAL ROLE inside
   a rolled-back transaction to check intended restricted-role reads. Confirm all
   nine tables, enabled RLS and named grants; do not replace runtime with postgres.
5. Expected empty-state screens: no UndefinedTable; instead missing contract/rule,
   missing source health and monitor-not-commissioned states. These are success
   of schema installation, NOT evidence that safeguards are operating. Broker
   policies, rules, ban source and historical contract/adjustment records still
   require reviewed commissioning; the option-entry hold is not lifted.
   The earlier reference-collector receipt/first-known timestamp issue documented
   in DERIVATIVE_READINESS_REVIEW.md must also be fixed/tested before ingestion
   is used as point-in-time evidence. This diagnostic patch does not commission it.
6. Measure bytes after creation. Do not enable recurring reference ingestion until
   bounded first-ingest size is measured and a reviewed verified archive/restore
   design protects positions/decision lineage. Existing Drive retention does NOT
   cover derivatives. Contract/source/rule/decision history accumulates; alerts
   and positions are upserts but new contracts/conditions also add rows. Never
   delete old contract versions by a generic 14-day cutoff.
7. Safest empty-schema backout is leave inert tables and jobs disabled. Do not
   drop schemas or roles, remove RLS or discard obligation evidence. Monitoring
   any real open obligations must not be stopped without a replacement.

## Read-only hosted queries run in this investigation

All calls used BEGIN READ ONLY, SET LOCAL statement_timeout='5s', COMMIT.
Connector returns only the final statement's rows, so compound calls were split
to confirm size/table count and role results explicitly. No credential catalogs,
table payloads or Secret values were queried.

```sql
SELECT current_user, pg_database_size(current_database()) AS database_bytes;
SELECT n.nspname AS schema, c.relname AS table_name,
       pg_total_relation_size(c.oid) AS total_bytes, c.relrowsecurity AS rls_enabled
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname IN ('derivatives_reference','derivatives_monitor') AND c.relkind='r'
ORDER BY 1,2;

SELECT pg_database_size(current_database()) AS database_bytes,
 count(*) FILTER (WHERE n.nspname IN ('derivatives_reference','derivatives_monitor')
                  AND c.relkind='r') AS derivative_table_count
FROM pg_class c LEFT JOIN pg_namespace n ON c.relnamespace=n.oid;

SELECT rolname,rolsuper,rolbypassrls,rolcanlogin FROM pg_roles
WHERE rolname IN ('quant_app_runtime','quant_derivative_ingestor',
                 'quant_derivative_monitor','quant_derivative_watchdog') ORDER BY rolname;

SELECT n.nspname AS schema_name,c.relname,pg_total_relation_size(c.oid) AS total_bytes
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE c.relkind='r' AND n.nspname IN ('quant_app','equity_research','equity_operations')
ORDER BY total_bytes DESC LIMIT 8;
```

Largest tables, bytes: universe_membership_versions 82,534,400; market_quotes
80,969,728; outcomes 60,178,432; scanner_observations 59,334,656;
universe_membership 56,418,304; evidence_ledger_events 51,118,080;
mf_nav 43,532,288; market_daily_volumes 8,306,688. These are allocated sizes,
not growth rates or reclaimable-space promises. Compare the platform quota too.

Sources:
https://supabase.com/docs/guides/platform/database-size
https://upstox.com/developer/api-documentation/get-intra-day-candle-data/
