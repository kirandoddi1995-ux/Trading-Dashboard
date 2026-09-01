# Fix verification — v16.0-AUDIT-FIXES

Implemented directly in the local project on 31-Aug-2026. The public Streamlit deployment has NOT been updated by these file edits. This record supersedes neither the historical audit nor the operator requirements below.

## Implemented

- Capital, risk settings, research navigation and scan filters survive widget cleanup. Buttons/uploads are excluded from preference restoration. Tested both with Streamlit's testing framework and browser navigation.
- Anonymous sessions receive separate unpredictable owners for positions, watchlists and signal records. No login/OIDC setup added. Original user databases and old rows were preserved.
- Historical setup outcomes deduct costs on every exit, use gap-aware conservative stops, exclude unfinished current-session candles, and share structural level/exit logic with research backtests. Historical samples are not advertised as validation of the entire stock-ranking strategy.
- Stale WebSocket receipts trigger REST recovery. The lightweight header also suppresses stale ticks and labels an unavailable feed instead of suggesting it is still loading. Exchange-status calls use authenticated, uppercase exchange names. Missing exchange status does not become a verified open market. Missing VIX no longer becomes an invented value of 15.
- Rate limits, provider circuit state, AI request budgets and scan jobs survive script reruns. Long Retry-After values are not shortened. Paid-AI requests also have a process-wide ceiling, input/output limits and finite request timeouts.
- Scan work runs outside the UI script. Completed/active jobs can be recovered after navigation within the same session. Deadlines release the UI; timed-out requests retain the concurrency guard until they finish, preventing overlapping orphan workers.
- Diagnostics distinguish submitted/processed/valid-data/technical-rejection/data-failure/displayed counts. Timing does not grow on rerenders. Every exclusion is retained for CSV export, with representative examples from each category.
- All stock views use the same action decision. Wide/unrealistic risk scenarios are Watch-only, not automatically sized buys. Net R:R and capital/risk budgets include consistent illustrative costs. Unknown sectors share a capped bucket; diversification limits are not silently loosened to fill ten rows.
- Option entry uses the ask and tracked exits use bids. Missing/crossed bid-ask quotes, missing current contract lots and expired/unknown expiries cannot create a sized proposal. Sizing is capped by visible ask depth. Original signal levels remain immutable; previous signal status appears separately from new proposals.
- Futures require a current contract quote, current spot, metadata lot size and an open session. MCX selection orders current contracts by expiry rather than alphabetically choosing a distant thin contract. No invented margin/quantity calculations are presented.
- MCX, NAV and technical charts use server-generated PNGs, with an optional self-contained interactive HTML download. This avoids the failing browser Plotly asset; it does not claim to diagnose the original CDN/browser failure.
- Provider candles accept optional OI, reject invalid OHLC/negative volume, and deduplicate timestamps without summing cumulative volume. Secrets are filtered from application logs and formula strings are neutralized in spreadsheet exports.
- Runtime and transitive dependencies are pinned to the tested isolated environment. No unrelated global Python packages were upgraded.

## Observed verification

- 70 automated regression tests passed in the final run in the project virtual environment (Python 3.13.9), including three new stale/closed ticker display cases.
- Dependency consistency check: no broken requirements.
- Dependency vulnerability database check: no known vulnerabilities found after updating the isolated environment's pip to 26.2.1. This is not proof of zero security vulnerabilities.
- Read-only Upstox checks: NSE and MCX both returned HTTP 200 / NORMAL_OPEN.
- Gemini 3.7 Flash and 3.6 Flash were available to the configured key; one tiny arithmetic request returned the expected answer. No account/portfolio data was sent by that probe.
- Browser: capital changed to ₹500,000, navigation to Research and back preserved it. The additional Settings-button regression found during testing was corrected and covered by an automated test.
- Browser, local pinned environment: Full NSE received 2,642/2,642 quotes, processed 250/250 candidates, with 195 valid-data evaluations, 66 rule passes, 55 data exclusions and zero timeouts. Three entries remained after strict diversification; displayed wide-stop examples were Watch, not Buy. Quote retrieval 2.40s, funnel 0.23s, analysis 36.34s, ranking approximately 0.01s, displayed total 38.99s.
- Navigated to Research during Full NSE processing and returned: the completed Full NSE job/result was recovered, not replaced by Quick results.
- Commodity browser check rendered the new chart and selected the nearest current contract, with actual computed ATR/RSI rather than zero/default placeholders.
- Mutual-fund browser scan evaluated 31/36 eligible Large Cap funds in 44.3 seconds, matched TER for 28/31, and showed historical validation plus the official-data limitation instead of a service-failure-only page. Five funds lacked the required ranking evidence; they were not filled with invented data.
- AMFI's official dated benchmark report was rechecked and still returned HTTP 403. It was not bypassed or replaced with invented benchmark values.
- Final afternoon browser check after restarting with all updated modules: RELIANCE research rendered a complete 1460×584 chart image; its neutral structure correctly withheld target and stop. The futures page showed spot, actual contract price, basis and metadata lot size, while withholding an actionable proposal after NSE reported NORMAL_CLOSE.

## Deployment

Extract `release-v16.0-audit-fixes.zip` and upload the included project files to the GitHub repository used by Streamlit. At minimum, all six runtime Python modules plus `requirements.txt` AND `constraints.txt` must be deployed together. Uploading only app.py will fail. Keep real secrets in Streamlit's Secrets settings, never in the repository.

Use Python 3.13 to match the tested environment. Streamlit's deployment controls, not a local filename, select the hosted Python version. See the [official deployment instructions](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy). Back up hosted data/configuration before any redeployment that might reset ephemeral storage. Restart/reboot the app after deploying the complete package so old imported helper modules are not retained in memory; a browser refresh alone is insufficient. Confirm the sidebar build reads v16.0-AUDIT-FIXES and repeat the hosted smoke checks.

## Explicit remaining requirements

These cannot honestly be called fixed by local source changes:

1. Revoke/rotate previously exposed provider credentials and update Streamlit Secrets. Provider-console access is required; credentials were not rotated here.
2. Make the hosted app private or run it privately. Per-session ownership protects record selection but does not authorize visitors to use shared provider quotas. No application login was added, as requested.
3. Deploy the updated files. There is no Git checkout in this local folder and no deployment/account authorization was available to complete a hosted rollout.
4. Supply current official same-date benchmark/Riskometer disclosures when the upstream service is blocked. The existing session CSV import remains available and explicitly labelled user supplied.
5. Process-restart/multi-replica job recovery requires durable storage/queue infrastructure. Current job recovery is process-local and session-scoped, with bounded retention; no claim of crash-proof persistence is made.
6. Complete sector/corporate-action/point-in-time datasets, broker-specific costs and prospective prediction validation require data and evidence beyond this repair. Future returns are not guaranteed. A correct no-trade/Watch result is valid output.

Test databases and cache files are separate from your original market_cache.sqlite3. They, secrets and the local virtual environment are excluded from the release archive.
