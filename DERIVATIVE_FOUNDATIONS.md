# Derivative foundations — local review, not deployment authorization

## Boundaries

Five new modules normalize versioned contracts, V3 snapshots, official bans,
preflight and restricted reference storage. No changes to equity 1.30 / shared
2.00 thresholds, research records, order placement or existing governance rules.
Quick F&O ideas are now a **research shortlist**, never a second approval path.
Detailed option and futures candidates require preflight AND existing governance.
No quote or reference check creates execution evidence or supplies missing EV inputs.

## Review-only SQL

`sql/derivative_foundations_review_only.sql` creates only a new private schema,
five tables and the dedicated ingestion role. It changes no existing tables.
No application, collector or workflow executes this file. Supabase CLI was not
available locally; this draft follows the existing project `sql/` convention.
The local SQL tests execute it only in a disposable PGlite instance, never Supabase.

Runtime gets SELECT and decision-snapshot INSERT only. Ingestion gets reference
SELECT/INSERT and narrowly scoped health UPDATE; it cannot author exchange rules.
The existing research collector, anon and authenticated have no new access.
The database owner must review and provision exchange-rule records separately.
No hardcoded fallback expiry hours, lot sizes or settlement rules are supplied.

## Required configuration before activation

1. Review/apply the SQL manually. Privately set the new role's password and create
   a restricted connection string; never commit it.
2. GitHub secret `DERIVATIVE_REFERENCE_DATABASE_URL`: new ingestion-role URL.
3. GitHub variable `DERIVATIVE_UNDERLYINGS_JSON`: JSON list of 1–30 actual Upstox
   underlying keys. Scope narrowly; no full-exchange tick/history ingestion.
4. Keep `DERIVATIVE_REFERENCE_ENABLED` unset until review; set `true` to enable
   the dedicated workflow. It runs weekdays 03:15 UTC / 08:45 IST, plus manual
   dispatch for special sessions. Holidays do not become tradable merely because
   ingestion ran: dated session rules still govern eligibility.
5. Populate reviewed `exchange_rules` records with `version=digest(payload)`
   using `derivative_contracts.digest`, and the exact instrument key and known_at.
   Each payload requires:
   - source, known_at, effective_from/effective_until (aware timestamps);
   - instrument_key, exchange, segment, master_hash (`digest` of exact raw record);
   - expiry_at, session_open, session_close, session_date;
   - settlement CASH/PHYSICAL, explicit delivery obligation;
   - trading_status ACTIVE, corporate_action_status VERIFIED and notice version;
   - tenor WEEKLY/MONTHLY, tick_scale (verified source-unit conversion);
   - weekly_underlyings for NSE weekly contracts (reviewed exchange eligibility);
   - quote_policy: max_age_seconds, max_skew_seconds, max_spread_fraction, version.
   Numeric quote tolerances are reviewed operating policy, not empirical accuracy claims.
   Do not seed sample policies or fabricate exchange notices to turn blockers green.
6. Verify from the actual host: valid current master, dated ban file, live V3 full
   subscriptions, source/receipt timestamp behavior, actual price/size units,
   and rule-version alignment. Missing any of these explicitly blocks entries.

## Data semantics and limitations

- Supported execution reference adapters: NSE/BSE FO. NSE IX fails closed.
  BSE stock restriction rules are not inferred from NSE; unsupported stock venues
  fail closed. Listed tenors other than weekly/monthly remain unsupported.
- Upstox V3 `currentTs` is retained as provider message time, `ltt` as last trade
  time. Neither is relabelled as exchange quote time. Exchange quote time is NULL
  where unavailable. Partial updates never refresh retained old depth.
- The live feed must report NORMAL_OPEN for the actual derivative segment;
  unknown, auction, closed or halted segment states cannot qualify an entry.
  Reconnection clears both the segment state and previous executable snapshots.
- Index spot is a reference value, not an executable order book. Futures are
  required only when the calculation uses them. Buy/sell references are ask/bid,
  limited to observed top-of-book quantity. They are NOT fill simulations.
- Source refresh marks health UNKNOWN before network access. Schema/download
  failures do not mean an empty ban list. Current-date rules and status are required.
- Ban parser deliberately accepts only recognized one-column SYMBOL/SECURITY
  CSV schemas (including header-only empty). An unfamiliar official format fails
  closed and requires a captured, reviewed fixture before adding support.
  A live NSE download could not be verified locally (timeout); do not claim the
  scheduled ingestion is production-verified until its first real run passes.
- Exit assessment accepts complete clearing-corporation exposure evidence, not
  manual/research labels. It rejects increased/reversed exposure. No automatic
  broker position/CC-delta ingestion or exit-order placement is introduced here;
  unavailable evidence requires operator/broker review, not disabled monitoring.
- Raw REST chain displays and existing IV diagnostics remain research context;
  actionable entries require fresh V3 preflight and existing independent/model
  governance. This foundation does not certify those research models.

## Storage and release

Store changed contract versions once, a compressed scoped daily source snapshot,
small ban files and compact decision snapshots—not continuous ticks/full-exchange
chains. Pending health is mutable; historical reference snapshots are append-only
for runtime/ingestor roles. Repeated identical ingestion is idempotent.
These new tables are NOT yet part of the Drive deletion allowlist. Do not enable
wide-universe ingestion indefinitely without measuring growth and reviewing an
archive extension that preserves referenced versions. No retention claim is made.

Release import discovery includes the modules automatically. The explicit runtime
fingerprint and release resource list include the new sources/draft. Changing
app.py changes EXPECTED_EQUITY_CODE_SHA256; use the final reviewed fingerprint
provided with the test results, not a hash computed before review edits finish.
