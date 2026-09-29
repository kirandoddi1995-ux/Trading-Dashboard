# Local review: settlement and corporate-action monitoring

No migration, broker call, email, hosted configuration or deployment was performed.
This is a monitoring/blocking layer, not an order or automatic-liquidation system.

Existing artifact hashes verified unchanged:

- ZIP: `3B41E98A2188896003510C565C69EB3E92BE380FFEC274D5CB87769C526F270F`
- SHA256_MANIFEST.json: `6F0AEB86721F0F3A00B409948B353309262F18148884BF6EE9F65FE64A7206D0`

## Verification results (local, 2026-09-29)

- Baseline after access repair: **832 passed, 4 skipped, 2 subtests passed**. The original eight artifact-access failures are gone.
- Final full suite: **860 passed, 4 skipped, 2 subtests passed**, 310.05 seconds.
- Skips: two Windows symlink-permission cases and two Linux-bash workflow cases. SQL tests ran with the local PGlite harness; no hosted database was used.
- Full-project Pyflakes: passed. Deployment canary: all checks passed.
- Actual current release built and extracted/imported in a disposable test directory: passed. Original release ZIP/manifest were not replaced.
- Windows destination-DACL/byte-preservation and verification-timeout regressions: passed.
- SQL idempotency, restricted roles, acknowledgement versus resolution, email crash leases, historical lookup and owner-only adjustment publication: passed.
- Hosted token/IP access, SMTP inbox delivery, actual broker data and independent scheduling remain deliberately untested pending deployment review.

## Changes and file scope

All paths below are relative to `C:\Users\banga\Desktop\kiran_share_market` (16 changed/new files including this guide). Upload those files only after review; do not upload scratch test directories or credentials. The existing release ZIP and SHA256_MANIFEST.json are intentionally not updated.

- `package_release.py`: prepare only newly staged ZIP/manifest DACLs using a temporary sibling file's inherited destination permissions; verify bytes and DACL before atomic per-file replacement. Existing artifacts, staging-directory permissions and credentials are untouched. Failure before publication preserves both old artifacts. The two replacements are individually atomic, not a transactional pair.
- `release_verification.py`: on Windows verification timeout, terminate the particular verifier process tree before temporary-directory cleanup. Import verification and the hard timeout remain mandatory.
- `derivative_settlement.py` (new): Decimal obligation calculations and reviewed expiry-specific broker deadlines. Long call/short put receive shares and require funding; short call/long put deliver shares. Broker quantities are underlying units, not lots multiplied again. Missing final prices produce potential obligations, not assumed exercise/settlement.
- `derivative_corporate_actions.py` (new): exchange-source/lineage/exact-term validation, separate pricing events, and mandatory post-adjustment quote refresh.
- `derivative_monitor.py` (new): account-bound GET-only broker polling, unresolved-position retention, retryable emails and independent watchdog command. No order-placement or liquidation endpoint.
- `derivative_contracts.py`: historical monitoring lookup tolerates expired/inactive contracts but does not bypass entry validation.
- `derivative_repository.py`: historical references, owner-only adjustment publication, monitor state, retained positions and leased email deliveries.
- `derivative_preflight.py`: additive fresh-monitor/policy/adjustment checks. Missing configuration blocks new entries/rolls. These checks cannot grant model/risk approval.
- `app.py`: options/futures monitor panels, acknowledgement-only controls and lifecycle context for preflight.
- `equity_runtime_health.py`: release fingerprint includes the three new modules.
- `sql/derivative_monitor_review_only.sql` (new): four private tables, restricted monitor/watchdog roles, runtime acknowledgement privilege and research isolation. Review and execute manually only.
- Tests: `tests/test_release_packaging.py`, `tests/test_derivative_foundations.py`, `tests/test_derivative_repository_sql.py`, `tests/test_derivative_monitor.py` (new).

## Before deployment

After uploading these exact source files, set Streamlit's `EXPECTED_EQUITY_CODE_SHA256` to:

```toml
EXPECTED_EQUITY_CODE_SHA256 = "b3cfaf59b808f6e0e7dc38b0f2766c67e6bc5c2b6228dc6ab8925a12a7bb98b8"
```

Other expected-build/policy values are unchanged. This hash is not an approval to trade and must be recomputed if any fingerprinted source is edited.

1. Review the SQL after the existing derivatives foundations migration. It creates four private tables (`records`, `state`, `positions`, `alerts`) and adds monitor SELECT policies on the two existing reference tables. It does not delete data or change settlement/position tables. Runtime cannot create reference/reconciliation evidence. Research has no access. Provision role passwords privately; no passwords are in the draft.
2. Configure the monitor process environment privately:
   - `DERIVATIVE_MONITOR_DATABASE_URL`: connection for `quant_derivative_monitor`.
   - `DERIVATIVE_MONITOR_ACCOUNT_ID`: exact Upstox profile user ID.
   - `DERIVATIVE_MONITOR_TOKEN`: valid read-only Analytics Token, or a manually renewed supported access token.
   - `DERIVATIVE_MONITOR_TTL_SECONDS`: 300 by default; allowed 30–900. Schedule comfortably more frequently than the TTL and allow for API latency.
   - `DERIVATIVE_ALERT_SMTP_JSON`: JSON object with `host`, `port` (SSL, normally 465), `username`, `password`, `sender`, `recipient`. Use a dedicated mail credential, never a personal password in code.
3. Streamlit secrets need `[derivatives_monitor]` with `account_id` matching the monitor. No monitor/broker/email secrets are needed in the dashboard.
4. Run `python derivative_monitor.py` from a scheduler independent of Streamlit. The code executes once and exits. A nonzero exit indicates attention/failure; do not suppress scheduler failures.
5. On a different host, run `python derivative_monitor.py --watchdog` with a **different** database credential for `quant_derivative_watchdog` and its own SMTP configuration. It needs no Upstox token. It sends a direct email on missing/stale heartbeat even if the database is down. It does not persist retries when the database is unavailable; the independent scheduler must rerun and alert on failed executions. Repeated stale checks can send repeated emails.
6. Reconcile any positions/settlement obligations that predate installation. An empty initial API response is not proof that historical obligations are settled. Test actual email arrival, token failure, stopped-monitor heartbeat, and reference provisioning before relying on the deployment.

## Reference provisioning (deliberately owner-reviewed)

There is no automatic approval/scraping of broker circulars. The owner must retain the official source document and its SHA-256 and provision immutable, hash-versioned records using the existing owner review process. A source hash is not a copy of the source: retain the documents in the private archive. `records.version` is `derivative_contracts.digest(payload)`, not ordinary JSON SHA-256. Its `known_at` and instrument key must correspond to the payload. The monitor/runtime cannot insert these records.

- `BROKER_POLICY`: `reviewed=true`, official HTTPS Upstox `source`, lowercase `source_sha256`, `contract_version`, `expiry_at`, `known_at`, `valid_until`, `entry_cutoff`, `exit_by`, `broker_deadline`. Require entry cutoff <= planned exit <= broker deadline <= contract expiry. No hardcoded expiry deadline.
- `ADJUSTMENT_REVIEW`: `status=VERIFIED`, `contract_version`, `rule_version`, `checked_at`, `valid_until`, `quotes_after`, `event_version`. Also needed for a reviewed no-adjustment state; refresh for the current rules. Quote and Greek snapshots must be after `quotes_after`.
- `CONTRACT_ADJUSTMENT`: exact old/new master hashes, official venue circular URL/hash, `known_at`, `effective_at`, `reviewed=true`, and exact replacement instrument key/strike/lot/expiry/tick terms. `publish_adjustment()` atomically stores both masters, replacement rules and linked review. It does not synthesize ratios or modify old versions. Changed instrument keys remain separately monitored until old obligations are reconciled.
- `PRICING_EVENT`: retained separately; cannot pass the contract-adjustment validator. This patch does not introduce a dividend forecast or return/pricing model.
- `FINAL_PRICE`: `source_type=EXCHANGE_FINAL_PRICE`, `verified=true`, source hash, matching contract/rule versions, expiry timestamp and official `price`. Even an ITM result is **not** settlement confirmation.
- `RECONCILIATION`: imported and verified broker report, not manual acknowledgement or research data: `source_type=BROKER_REPORT`, `verified=true`, `outcome` (`EXIT_FILLED`, `SETTLED`, `ADJUSTED`), `position_fingerprint`, `source_sha256`, `broker_reference`, `confirmed_at`. Adjustment receipts also bind `new_contract_version`, `new_rule_version`, `new_signed_units`. Broker disappearance alone never resolves a retained position.

## Visible behavior and limits

Dashboard shows retained quantities, potential delivery/funding, reviewed deadlines, status and email acceptance/failure. AUTH_REQUIRED, missing data, stale heartbeat and unresolved obligations block entries. Acknowledgement records that you saw an alert; it does not clear the condition. Exits are not disabled by monitor health; existing position-wide exit restrictions remain.

Funding is gross strike consideration for exercised stock options; futures require the official final price. Charges/margins and available settlement cash are not fabricated. Reported margin and holding/T1/pledged quantities are context only. Shortfall fields remain unknown until reconciliation. There is no assumed portfolio netting and no promise that a hedge can be closed safely or that a broker will square off successfully.

Emails contain condition codes, not credentials/account/position data. Delivery is at least once: crash after SMTP acceptance can produce a duplicate. Failed sends retry with bounded backoff; persistent active conditions repeat after six hours. SMTP acceptance does not prove inbox delivery. Persisted positions are current retained monitor state, not a substitute for the existing execution ledger or complete position history.

Storage is deliberately compact: upsert current account/position/alert state, no poll-by-poll OHLCV/raw broker-response archive. Contract/circular history is immutable and grows with reviewed reference versions, not ticks. Monitor actual size before adding broad instruments. No existing archive/retention pipeline is changed.

## Hosting recommendation

Use a small always-on VPS with a stable public outbound IP for the monitor; whitelist that IP with Upstox. Keep the watchdog on another host. A continuously running personal PC with static ISP egress is an alternative, but power/sleep/network failures make it less reliable. Standard GitHub-hosted runner IP ranges are not a fixed egress address; do not whitelist the entire range. Larger static-IP runners or cloud NAT are alternatives but likely unnecessary infrastructure for this workload. No specific provider or hosted scheduler is embedded in the code.

Upstox documents Analytics Tokens as read-only, valid for one year, with static-IP requirements for User/Orders/Portfolio APIs: https://upstox.com/developer/api-documentation/analytics-token/
GitHub recommends static-IP larger runners or self-hosted runners for IP allowlists: https://docs.github.com/en/actions/reference/runners/github-hosted-runners

The watchdog needs only database/email access, so GitHub Actions can be a secondary watchdog if scheduling delays are acceptable; it is not a real-time expiry safeguard. No hosting option makes automatic liquidation part of this implementation.
