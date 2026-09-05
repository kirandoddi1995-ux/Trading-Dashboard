# Quant Terminal production guide — v21.2 deployment hardening

## Deployment security (v21.2)

The hosted app now fails closed behind Streamlit's native OIDC login and a separate authorization
allowlist. Add the `[auth]` block from `.streamlit/secrets.example.toml` to Streamlit Secrets, set its
`redirect_uri` to the exact deployed app URL plus `/oauth2callback`, and register the same callback at
Google, Microsoft Entra, Okta, or another OIDC provider. Add the intended account to
`AUTH_ALLOWED_EMAILS` (or a controlled organization domain to `AUTH_ALLOWED_DOMAINS`). A valid login
that is not on the allowlist is denied. Never expose ID/access tokens or log raw identity claims.

Authentication can be disabled only for local development when all three controls are explicit:
`APP_ENV=development`, `APP_AUTH_MODE=disabled`, and the local process environment variable
`QUANT_ALLOW_INSECURE_LOCAL=1`. Production defaults to OIDC and missing configuration stops execution
before application data stores, provider clients, or recommendation paths are initialized.

Database authority is split:

1. Keep the existing Supabase owner/pooler URL only in GitHub Actions as `DATABASE_MIGRATION_URL`.
2. Run `database_runtime_role.sql.example` once in Supabase SQL Editor after replacing its password
   placeholder with a password-manager-generated value. Do not save or commit the completed SQL.
3. Build a Session Pooler URL for `quant_app_runtime` and store it as `DATABASE_URL` in both Streamlit
   Secrets and GitHub Actions. Percent-encode special password characters in the URL.
4. The workflow first runs owner-only migrations, then verifies the restricted runtime connection.
   The app and collector never execute DDL and reject admin roles, schema-CREATE privilege, RLS bypass,
   or update/delete rights on the immutable evidence ledger.

Do not put `DATABASE_MIGRATION_URL` in Streamlit Secrets. Rotate the old owner URL out of Streamlit
after the restricted URL passes the scheduled collector's connection check.

The repository does not depend on TensorFlow. A TensorFlow/protobuf conflict therefore indicates a
contaminated local Python environment, not an application dependency. On Windows run
`bootstrap_clean_environment.ps1` to create a dedicated Python 3.13 `.venv`. CI now runs both
`pip check` and `environment_preflight.py --strict`, so any installed-package mismatch blocks release.

## Advanced quantitative governance (v21.1)

The v21.1 hardening release connects PIT, execution-quality, kill-switch, EV, and portfolio-risk
contracts to live recommendation paths. It also isolates same-day scan runs, purges labels crossing
the untouched holdout, rejects non-finite policy inputs, and retains failed durable ledger deliveries
in a retry outbox. Exact one-minute target evidence is now the only production label path.

Every displayed setup is now written to an append-only evidence ledger with an idempotency key,
per-signal sequence number, previous-event hash, payload hash, model version, thresholds, timestamps,
cost assumptions and decision inputs. Database triggers reject updates and deletes. Configure a random
`EVIDENCE_LEDGER_SIGNING_KEY` of at least 32 bytes in both Streamlit Secrets and GitHub Actions secrets
to upgrade the chain from unkeyed SHA256 integrity to HMAC-SHA256 tamper evidence. Keep retired keys in
a restricted audit vault when rotating them; changing the key prevents verification with the old key.

The advanced governance policy is visible read-only in Settings. It defines point-in-time coverage and
feature-age limits, executable liquidity limits, calibrated expected-value requirements, portfolio
volatility/Expected-Shortfall/drawdown/concentration limits, fractional-Kelly caps and validation
requirements. Expected value, fill probability and Kelly sizing remain unavailable until their own
out-of-sample evidence is calibrated; rule confidence is never substituted.

Validation now reserves the most recent chronological period as an untouched holdout after purged,
embargoed development folds. It reports Brier decomposition, Wilson reliability intervals, moving-block
bootstrap intervals and Deflated-Sharpe evidence. A failed development or holdout check returns ABSTAIN.
Order-book imbalance, microprice, options skew/curvature/term structure and breadth calculations are
implemented as shadow features; they are not promoted into production ranking until incremental
out-of-sample value after costs is demonstrated.

## Durable evidence collection (v19.0)

The app keeps SQLite as a fast local cache and writes irreplaceable research evidence to the
`quant_app` schema in the configured Supabase PostgreSQL database. Configure the restricted runtime
Pooler `DATABASE_URL` in Streamlit Secrets and GitHub repository Actions secrets. Configure the owner
URL only as GitHub secret `DATABASE_MIGRATION_URL`. Also configure
the read-only `UPSTOX_ANALYTICS_TOKEN` in both places. Never commit either value.

The `Scheduled evidence collector` GitHub Action runs at 09:25 IST and 15:45 IST on weekdays,
plus weekly maintenance at 18:00 IST on Saturday. It archives the dated NSE universe, quote
coverage, exact scanner evidence already produced by the app, exact one-minute execution labels,
and official AMFI data. Every run is audited as success or failure in PostgreSQL. The collector is
read-only and contains no order-placement code.

Use GitHub **Actions → Scheduled evidence collector → Run workflow → all** once after deployment.
The owner-only migration step creates or upgrades the schema; the separate runtime connection check
fails if the role is privileged or either URL is missing. A
successful workflow is the deployment proof; merely seeing secrets listed in GitHub is not.

Production validation never mixes daily-open fallback labels with exact intraday labels. For a
signal produced during market hours, entry is the first available one-minute open after the
signal. For an after-market signal, entry is an OHLCV-weighted five-minute opening VWAP proxy on
the next session. One-minute bars resolve target/stop ordering; a single minute touching both is
scored stop-first. Benchmark return ends on the actual outcome date rather than the full horizon.

Probability claims remain blocked until all evidence gates pass. Monitoring begins only after at
least 500 completed predictions across 60 trading dates. Credible validation additionally requires
2,000 completed predictions across at least 252 trading dates, at least 200 completed outcomes in
each observed market regime, and at least 100 out-of-sample outcomes in each confidence range used
for a trade decision. Purged walk-forward folds, a 20-session embargo, costs, Brier score, log loss,
calibration error and No-Trade abstention remain mandatory.

The official AMFI open-ended report is `NAVOpen.txt`. Only positive-NAV Direct-Growth records that
are current are eligible for primary rankings. Zero-NAV segregated records, stale schemes, missing
TER/Riskometer/benchmark/AUM fields and ambiguous scheme matches are never converted to zero or
invented values. They remain unavailable or are recorded as data-quality evidence.

## Immediate operator actions

The source code now keeps credentials server-side, but code cannot revoke credentials that were previously exposed. Before deploying this version:

1. Revoke and recreate the Upstox token and Gemini API key in their provider consoles.
2. Replace the values in Streamlit Community Cloud **App settings → Secrets**. Never place them in a widget or committed file.
3. Configure OIDC and the application allowlist, then keep hosting access limited to trusted users as a second control.
4. If the deleted `API AND TOPKENS.txt` was ever pushed, remove it from Git history with a history-rewrite tool and invalidate every value it contained. Deleting the latest copy alone does not erase repository history or forks.

## Security and data isolation

- The application requires OIDC and an approved email/domain before loading application services. Hosting-layer privacy remains recommended as defense in depth.
- Positions, watchlists, and option-signal history use unpredictable per-session ownership. One visitor does not receive another visitor's rows. Browser-session loss starts a new owner; this intentionally provides no durable account recovery. Existing rows are preserved, not reassigned. This is not a replacement for hosting-layer authentication.
- Existing legacy rows use `__legacy__` and are not automatically assigned to a new user. Migrate them manually only after ownership is verified.
- SQLite is acceptable for one local instance, but not for horizontally scaled production. Move user state to managed PostgreSQL, add `user_id NOT NULL` foreign keys, enforce row-level security, encrypt backups, and use short-lived database credentials.
- Keep market-data caches separate from personal data. Apply retention limits to logs and never log access tokens, API keys, raw OIDC claims, or full provider error bodies.
- Put the application behind TLS, enable provider-side MFA, restrict hosting access to approved accounts, and review dependency/security alerts. Keep OIDC callback URLs and allowlists under change control.
- Use least-privilege provider keys, secret rotation, audit logs, per-user quotas, request-size limits, and secure HTTP headers at the hosting edge.

## Market data and reliability

- Upstox REST calls share one bounded rate limiter and respect `Retry-After`. Full-NSE output is rejected below 90% quote coverage.
- Technical scans now run in a process-cached job registry, independently of Streamlit reruns. Navigation in the same session can recover active/completed jobs. Quote retrieval remains a bounded first stage. Quick analysis has a 90-second deadline; Full NSE has 180 seconds. Timeouts produce explicitly incomplete results. Late results are discarded, and no second scan starts until timed-out worker requests drain.
- The registry is NOT durable across process restarts or loss of the browser session. For restart/multi-machine recovery, deploy a durable job queue and database snapshots. The implementation does not pretend to provide that infrastructure.
- Use a durable queue and a distributed lock (for example PostgreSQL advisory locks or Redis) when more than one application process is deployed.
- Partition candle storage by instrument/date, use idempotent upserts, validate OHLC relationships, deduplicate by instrument and exchange timestamp, and record source/ingestion timestamps.
- Normalize volumes to one unit and one session. Never add full-day historical volume to intraday cumulative volume. Exclude partial current-session bars from historical averages.
- Handle exchange calendars, holidays, corporate actions, symbol changes, futures rolls, and expired instruments explicitly.
- Monitor quote coverage, request latency, 429/5xx rates, stale-candle age, rejected rows, scan duration, worker timeouts, and result counts. Alert on data drift and sudden universe-size changes.

## Credible prediction models

The equity **Historical Win Rate** tests a base EMA/ADX setup using the screener's structural-level routine. It uses completed daily candles, next-bar entries, non-overlapping trades, conservative same-bar target/stop handling, gap-stop fills, costs on EVERY exit, and a confidence interval. It does not validate the complete ranking/filter strategy and is not a trained forecast.

Equity R:R and sizing share an illustrative 0.30% round-trip cost. Options use ask entry, bid-price exit barriers, 0.70% illustrative fees, and visible ask-depth caps; spread is not subtracted twice. Capital caps reserve those costs. Actual brokerage, taxes, gaps, impact and slippage can differ. Wide equity stops (>20%) or targets disproportionate to the horizon/ATR are Watch-only. These are screening guardrails, not empirical success probabilities. No trade is executed by these calculations.

For a genuine prediction system:

1. Define one target before modelling—for example, 5-day forward total return after costs, probability of hitting +2 ATR before -1 ATR within 10 sessions, or expected return and drawdown over a fixed horizon.
2. Build a point-in-time dataset containing adjusted OHLCV, corporate actions, index/sector membership, fundamentals as originally published, market regime, volatility, liquidity, derivatives positioning, and—only when licensed—news/sentiment. Include delisted stocks to avoid survivorship bias.
3. Generate every feature using information available strictly before the prediction timestamp. Lag fundamentals and prevent future-adjusted membership or revised data from leaking into training.
4. Use chronological walk-forward validation with purging and an embargo for overlapping labels. Keep a final untouched time period and report results by bull, bear, sideways, high-volatility, and low-liquidity regimes.
5. Simulate brokerage, taxes, exchange fees, bid/ask spreads, impact, slippage, rejected orders, partial fills, liquidity limits, and realistic next-bar execution.
6. Start with interpretable baselines: regularized logistic/linear regression, calibrated tree models, or monotonic gradient boosting. Compare them with a simple no-skill and fixed-rule baseline before considering deep learning.
7. Report probability calibration (Brier score, log loss, reliability plots), discrimination (ROC/PR where appropriate), expected value, turnover, drawdown, Sharpe/Sortino with caveats, and confidence intervals from block bootstrap or conformal methods.
8. Explain predictions with stable feature contributions and reason codes. Show sample size, model/version, data timestamp, expected horizon, uncertainty range, and conditions under which the forecast is invalid.
9. Paper-trade first, then use a small controlled rollout. Monitor feature drift, calibration decay, realized slippage, missing data, and performance relative to the locked validation baseline. Require documented approval before retraining or promotion.

## User experience

### Mutual-fund disclosures and prediction evidence (v15.1)

Deploy all six runtime Python files together: `app.py`, `app_runtime.py`, `scan_jobs.py`, `reliable_charts.py`, `technical_indicators.py`, and `mf_research.py`, plus `requirements.txt` and `constraints.txt`. No application-login configuration or new provider key is introduced.

- Find Top Funds loads up to twelve years of NAV history. Current features and each historical prediction use the same maximum five-year feature window. Missing months and incomplete calendar months are not forward-filled.
- Riskometer and Tier-1 benchmark names are retrieved from scheme-matched AMFI scheme-summary XML, with exact name matching inside the fund house. The at-launch Riskometer is not used. The document's save date is shown separately and is **not** claimed to be the risk effective date or proof that the monthly reading is current.
- The automatic benchmark-return adapter uses the public performance service embedded in AMFI's website. On 31-Aug-2026 the tested report route returned HTTP 403; the app reports this dependency failure and can still show available official summaries. It does not silently replace a TRI with a price index, ETF NAV, or a category median.
- Same-report 1/3/5-year excess returns (percentage points), declared benchmark, and reported Direct-plan IR can also be supplied using the downloadable disclosure CSV template. Import the fund and its benchmark returns from the **same dated report**, with AMFI scheme code, matching scheme name, source URL, and dates. Imports stay in the current Streamlit session and are labelled user supplied, not independently verified. Comparisons older than 45 days are withheld; this freshness rule is not evidence of source authenticity.
- Out-of-sample evaluation uses annual, non-overlapping twelve-month holdouts, at least three years of prior observations, and the actual deployed bootstrap-plus-category-shrinkage scenario routine. Each fold is recomputed from historical NAVs only. Current TER, AUM and Riskometer values do not enter old predictions. Test years are not used to select or tune the model.
- The target is the twelve-month NAV total return after an explicitly displayed illustrative round-trip cost (default 0.5%). Ongoing fund expenses are already included in NAV and are not subtracted twice. Taxes and actual exit loads are not simulated. A one-year ELSS NAV return is not a redeemable one-year investment.
- Evidence includes mean absolute error in percentage points, Brier probability error, actual coverage of the nominal 80% interval, fold dates, outcomes, and a historical rolling-return baseline. Small samples and failure to beat that baseline remain visible. `production_validated` is never set true by this historical test.
- This is scenario-model evaluation on the available current-category sample, **not validation of the complete fund-ranking strategy**. Survivorship, category reclassification, correlated funds, revised history, missing dead-fund outcomes and lack of a point-in-time category archive remain limitations. Prospective paper evaluation and a point-in-time universe are needed before claiming predictive investment skill.

Source pages: [AMFI scheme details](https://www.amfiindia.com/otherdata/scheme-details), [AMFI Riskometer disclosures](https://www.amfiindia.com/online-center/risk-o-meter), [AMFI fund performance](https://www.amfiindia.com/otherdata/fund-performance).

The interface is consolidated into **Today’s Picks**, **Research**, and **Settings**. Keep Today’s Picks decision-focused: data freshness, direction, entry, stop, target, risk/reward, position size, evidence range, and a clear no-trade state. Put diagnostics and model details in progressive disclosure under Research. Keep credentials, risk limits, positions, watchlists, and connection health in Settings.

Do not use “AI,” “institutional,” “probability,” or “confidence” as promotional labels unless the displayed number has a documented target, evaluation window, sample size, and calibration evidence. Always show stale-data and incomplete-scan warnings before recommendations.

## Deployment checklist

- Use Python 3.13 (tested on 3.13.9). Create a project virtual environment, upgrade pip, and install `requirements.txt`. Do not install into an unrelated Anaconda environment; the audit found an existing TensorFlow/protobuf conflict there.
- Run `python -m pytest tests -q` (install pytest separately), `python -m pip check`, and `python -m pip_audit` (install pip-audit separately). The tested isolated environment reported no known vulnerabilities on 31-Aug-2026; this is a database-based dependency check, not proof of zero security flaws.
- Optional `python provider_smoke.py --generate` makes read-only NSE/MCX status requests and one tiny Gemini arithmetic request using server secrets. It prints only status information, not secrets, account details, or model output. It may use a small amount of Gemini quota.
- Confirm the Streamlit deployment is private and accessible only to intended users.
- Verify Full-NSE quote coverage, scan lock behavior, timeout recovery, and no stale Quick results appearing as Full-NSE results.
- Confirm no secret file, local database, cache, export, or credential appears in the deployment commit.
- Pin and scan dependencies; rebuild regularly. Use a staging app before promoting to production.
- Add centralized structured logs, error tracking, uptime checks, database backups, restore drills, and an incident-response/credential-rotation runbook.

## Chart delivery and reproducibility

Charts render as server-generated PNGs, avoiding the failing Streamlit Plotly browser asset. A self-contained HTML download retains interactive zoom. This is a functional delivery workaround; the original deployed CDN/browser failure's root cause is not proven. Runtime dependencies are pinned to the tested versions. NumPy 2.4.6 is used because the tested pandas 2.3.3 combination produced resampling deprecation warnings with NumPy 2.5.2.

## What still requires an operator or external data

- Credential revocation/rotation, hosting privacy, and deployment require access to your provider/Streamlit/GitHub accounts. Local file changes do not perform those operations.
- AMFI's automatic benchmark report returned HTTP 403 again during the fix verification. Provide a current official same-date disclosure CSV through the existing import control; missing benchmark returns and unverified current Riskometer readings remain explicitly unavailable.
- Complete dated sector coverage, point-in-time/delisted-asset datasets, multi-year prospective prediction evidence, durable hosted storage/queues, and broker-specific execution-cost validation require data or infrastructure not supplied here. Unknown sectors are capped together, not fabricated as diversified sectors.
# Point-in-time prediction evidence (v17.0)

The application now archives the exact Upstox NSE BOD universe observed each day. It never applies a later
universe snapshot to an earlier replay date. Deploy the application daily to accumulate genuine membership
history; verified historical constituent files may be imported separately in the future, but current members
must not be used as a substitute.

The equity scanner stores versioned Stage-1 and Stage-2 observations. The Settings page can mature those
observations into 5/10/20-session labels using next-session-open entry, conservative stop-first handling for
same-bar ambiguity, 0.30% round-trip costs, and NIFTY excess returns. Validation uses purged expanding
walk-forward folds with a 20-session embargo, Platt probability calibration, Brier score, log loss, reliability
error, and an explicit No-Trade policy. Until the minimum out-of-sample evidence is reached and beats the
base-rate model, probability remains unavailable.

## Unified resilience control plane (v22.0)

Every live options, equity, futures, commodity, and technical-research candidate now passes through one
fail-closed safety state machine before it can be shown as actionable. The states are NORMAL, DEGRADED,
NO_TRADE, READ_ONLY, and EMERGENCY_STOP. More severe findings always win; exits and audit reads remain
available in every state. Emergency recovery requires explicit authorization and three clean windows.

The repository implements correlated decision IDs, SLO/error-budget evaluation, quote freshness/book/sequence
validation, optional independent quote reconciliation, policy/build attestation, calibration abstention,
append-only resilience events, an evidence-outbox backlog gate, model-promotion attestations, fill-state
surveillance, distributed collector leases with fencing tokens, recovery/retention checks, credential-free
game days, and capacity degradation contracts. Run `python resilience_acceptance.py --game-day` before release.

`resilience_policy.json` is configuration-as-code and must match `resilience_policy.sha256`. If an approved
policy change is made, update the sidecar in the same reviewed change and set `RESILIENCE_POLICY_SHA256` to
the approved file digest in the deployment environment. Do not put quotation marks around GitHub secret
values unless the quotation marks are intentionally part of the value.

The code cannot provision external services. Before claiming full production resilience, connect telemetry
export/alerts, a licensed secondary NSE quote source, Streamlit release rollback, secret-manager rotation,
Supabase PITR/isolated restore drills, and protected independent deployment/model approvals. Until configured,
these dependencies remain visibly unavailable or degraded; they are never reported as verified.
