# Live-market application audit — 31 August 2026

## Outcome

**The application works in part, but it is not ready for reliance on its position sizes or predictive claims.** Live data, equity screening, fund ranking and several sample calculations worked. A capital-setting reset, probability-accounting defect, stale-quote handling and chart failures need attention.

The one-time inspection began at 09:20 IST. Interactive checks ended around 09:41 IST. This was an audit, not a repair or deployment. No application code, credentials, trades, watchlists or stored positions were manually changed. A temporary capital input in the audit browser was restored to its original value. Ordinary app navigation can itself update the app's caches and recommendation-history records.

Application: https://trading-dashboard-jymw59l3buztc5vbynxu2s.streamlit.app/

Displayed build: `v15.1-MF-DISCLOSURES-VALIDATION`, matching the local build label. This is not a cryptographic comparison of deployed files.

## What worked, and what did not

- **Connection:** Upstox REST verified; WebSocket status became LIVE. NIFTY, SENSEX and BANKNIFTY prices changed between observations. An independent authenticated market-status request returned `NSE / NORMAL_OPEN`. This was not a continuous tick-by-tick reconciliation.
- **Initial page:** shell and controls observed by approximately 11 seconds; an options recommendation was present by approximately 29 seconds. These are observation bounds, not precise server measurements.
- **Quick Scan:** 95/95 quotes, 95 processed, 35 passes, 60 trend rejections, 10 displayed picks. No data failures or timeouts reported. App-reported time: 40.81 seconds (quotes 0.31, funnel 0.26, analysis 40.24).
- **Full NSE, first attempt:** returned to the no-result state without a completed result. Browser-to-Streamlit connection closes were observed. The cause is not established without production logs.
- **Full NSE, retry:** 2,640/2,642 quotes (99.924%), 250 shortlisted/submitted, 92 passes, 100 trend rejections, 58 data failures, 10 displayed picks. Zero timeouts reported. App-reported time: 91.01 seconds (quotes 7.25, funnel 0.71, analysis 82.97, ranking 0.03; displayed rounded components need not sum exactly to the total).
- **Full NSE responsiveness:** progress still showed 233/250 at an observation 108 seconds after clicking; completed results were observed by 175 seconds. The server's analysis time was 82.97 seconds. Therefore this is evidence of delayed/disconnected UI delivery, **not proof that the server's 90-second analysis deadline failed**. Browser logs also recorded attempts to rerun while disconnected. This browser connection is distinct from the Upstox price-feed connection.
- **Equity mode isolation:** switching to Full NSE did not present Quick results as a completed Full NSE result. The differing counts now have a legitimate two-stage explanation; all quoted equities do not receive deep historical analysis.
- **Futures:** NIFTY September futures setup and basis rendered by the 7.6-second observation. Arithmetic checked below. Margin lookup was not present despite the page description claiming it.
- **Commodities:** default ALUMINI November contract price displayed; ATR 0.00 and default RSI 50 accompanied an insufficient-data message. No trade was generated for that case. The chart failed to load. A nearer-contract selection was attempted but not confirmed applied, so it is not counted as a successful second-contract test.
- **Mutual-fund ranking:** Large Cap completed in an app-reported 36.0 seconds. 31/36 eligible funds ranked; official TER matched for 28/31. Top fund: ICICI Prudential Large Cap Direct Growth, shown as 82/100 after rounding. NAV dated 28 August 2026. This end-of-day NAV date is not inherently a live-market fault.
- **Mutual-fund lookup:** searching the same fund returned matching NAV, returns and drawdown. Its NAV chart failed to load.
- **Official disclosures:** declared benchmark Nifty 100 TRI and a Very High Riskometer label were available from an old summary. The app correctly warned that current monthly risk was not verified. Dated benchmark-return report failed with HTTP 403; actual excess-return comparisons remain unavailable.
- **Fund historical validation:** 8 annual tests for the leading fund, forecast MAE 9.12 percentage points, baseline MAE 9.63, central-80% interval coverage shown as 88%. The app correctly said the model did not beat the baseline on both measures and that the sample was limited. This is not validation of a tradable ranking strategy.
- **Technical research:** COFORGE's structure, target, stop, relative strength and volume-profile values rendered by the 15.6-second observation. The chart failed to load. Only representative arithmetic was checked, not every SMC label against independently sourced candles.
- **AI Copilot:** page and input rendered. No paid generation request was submitted; model availability, streaming response, content quality and response latency remain unverified.
- **Settings:** server-secret status displayed without browser credential fields. Capital persistence **failed**, as detailed below. No watchlist or position writes were exercised.

## Fixes to prioritize

### 1. High — investment capital silently resets after navigation

**Browser reproduction:** Settings initially displayed ₹10,00,000. Changed to ₹5,00,000 and confirmed the input value. Navigated to Research, waited for the new page, returned to Settings: input had reset to ₹10,00,000. Original value is now restored.

**Source:** `app.py:1759` and `app.py:1766`. Controls exist only on Settings; configuration is read directly from widget-owned session keys. Removing widgets during navigation allows their state to be cleaned up.

**Consequence:** subsequent calculations can use a higher default capital than intended. Similar persistence risks exist for risk percentages and other settings, but only capital was directly reproduced.

**Design:** keep durable session configuration separate from temporary widget keys; copy changes through callbacks. Display the effective capital/risk assumptions alongside every calculation. Add a browser regression: set capital and risk → leave Settings → interact/rerun elsewhere → return → verify unchanged. Recompute or explicitly label stored scan sizes when settings change.

### 2. High — historical win rate ignores transaction costs on target exits

**Source:** `app.py:3126`, particularly the target-hit branch. Target hits always count as wins; transaction cost is deducted only for horizon exits.

**Controlled reproduction:** target reward approximately 0.10%, assumed costs 0.30%. All 109 target exits were counted as wins, yielding a smoothed 99.1% despite negative net returns. This is a deliberately constructed unit case, not an observed market return.

**Design:** calculate an explicit executable entry and exit price for every exit reason, apply one consistent cost model, then classify positive net P&L. Include gaps, both-barrier ambiguity and slippage cases. Preserve the conservative treatment of ambiguous same-bar exits.

The estimator also uses a fixed 1.5-ATR stop / 2-ATR target, while displayed equity plans use structural stops/targets (`app.py:3075`). Its percentage is therefore not an estimated success probability for the exact displayed plan. Share the actual strategy implementation between research and live screening, version it, and validate that exact strategy chronologically.

### 3. High — old cached quotes can be treated as live

**Source:** `app.py:2808`. REST recovery is triggered by missing instrument keys, not stale timestamps. A controlled arbitrarily old quote was returned unchanged; the REST recovery stub was never called.

**Design:** enforce exchange/receipt timestamp freshness per instrument; distinguish market-open live ticks from closed-market snapshots. Refresh stale keys through the same shared rate limiter. Show an as-of time and disable actionable outputs when freshness requirements fail. The audit did not establish that every observed price was stale—this is a reproduced failure path.

### 4. High — option lifecycle status can describe a different signal

**Observation:** a freshly rendered options recommendation initially showed “EXIT (Target hit)”, followed by NEW on a later rerun.

**Source:** `app.py:905`, `app.py:5602`, `app.py:5659`. Lifecycle evaluation uses the previous persisted signal, but the card renders current recommendation values and the previous signal's status.

**Design:** give each signal an immutable ID and preserve its original contract, entry, target and stop. Render previous-signal lifecycle separately from new recommendations; never attach an old exit to a new contract. A displayed signal is not an executed trade.

### 5. High — single-user deployment is publicly accessible

A fresh audit browser could open the app without login. `app.py:668` assigns the same `CURRENT_USER_ID` to all visitors. Database queries may contain a user-ID condition, but a shared constant does not isolate visitors. “Private to your authenticated account” in My Positions is inaccurate for this build.

**Design:** consistent with the user's request for no app authentication configuration, restrict access at the hosting layer or run privately. Until then, do not store private positions here or expose shared paid-service quotas. Remove misleading privacy wording. Credential rotation and provider-console access were not verified or changed in this audit.

### 6. Medium — scan metrics and diversification claims overstate what is known

`app.py:6867` counts passes plus all rejections—including data failures—as “Successfully Analyzed”. “Final Picks” counts the 92 intermediate passes, not the 10 displayed choices. Show submitted, completed, valid-data evaluations, technical rejections, data errors and displayed picks separately.

The 58 Full NSE data exclusions may include insufficient history or invalid indicators, not necessarily API outages. The audit did not retrieve a complete per-symbol rejection export, so their individual causes are unverified.

All 10 displayed Full NSE picks were Unclassified. `app.py:691` / `app.py:695` use a limited sector map and individual fallback buckets for unknown symbols. This avoids treating all unknowns as one sector but does not prove diversification. Complete a dated sector mapping and label remaining exposure unknown; do not imply sector limits were verified for those names.

### 7. Medium — chart module fails; scan UI disconnects

MCX, mutual-fund NAV lookup and technical research showed:

`TypeError: Failed to fetch dynamically imported module: .../static/js/PlotlyChart.__5KNiOO.js`

This is a browser asset-loading error, not an observed Python indicator traceback. Its scope beyond the audit browser is unknown. Check the asset's HTTP result, browser/network/CDN behavior, deployment version consistency and production logs before deciding on a fix. Use version-pinned tested dependencies and a browser smoke test that waits for an actual rendered chart, not merely a page heading.

Persist long-running scan job IDs/results outside transient reruns; support reconnection to the active/completed job. Log session/run IDs, stage durations, memory, websocket disconnects and per-provider failures. Do not claim an OOM or server restart without logs.

### 8. Medium — invalid market-status request and resetting rate budgets

`app.py:1685` requests lowercase `nse` without authentication. Read-only checks returned 401 without a token, 400 “Invalid exchange” with a valid token and lowercase `nse`, and 200 `NORMAL_OPEN` with a valid token and uppercase `NSE`. Use the authenticated documented request. Label weekday/time fallback as unverified, not exchange-verified. [Upstox market-status documentation](https://upstox.com/developer/api-documentation/get-market-status/).

`app.py:1996` and `app.py:2162` instantiate rate-limit/quota objects at script top level, so full reruns reset their windows. Share budgets across reruns/workers (and across replicas where applicable). Honor the provider's Retry-After rather than truncating it to five seconds. Compare the internal budget with the provider's endpoint-specific limits; no actual rate-limit breach was measured in this audit. [Upstox rate-limit documentation](https://upstox.com/developer/api-documentation/rate-limiting/).

### 9. Medium — risk assumptions and recommendation wording differ

Options sizing uses 0.7% fees while R:R uses fees plus spread. Under the R:R assumption, the observed position's risk would exceed the displayed budget (sample below). This is an internal assumption inconsistency, not a measurement of actual broker costs. Use one explicit execution model and avoid double-counting spread already embedded in ask/bid prices.

Quick Scan showed COFORGE as Watch (67/100) while the headline said Buy. Derive both from the same decision object. “Institutional”, “validated”, “expected return” and “best trade” should not imply measured predictive skill that has not been established.

Full NSE BODALCHEM's stop was 40.43% below entry and its target 56.60% above entry for a 15-day setup. These follow the structural-level/risk-multiple formula; they are not proven likely outcomes. Apply horizon-aware feasibility checks and disclose wide-risk cases without inventing tighter levels to make a recommendation attractive.

## Independently checked sample arithmetic

These are historical audit snapshots, not current trading suggestions.

- NIFTY 24000 PE: entry ₹38.85, target ₹46.13, stop ₹34.97; 74 lots × 65 = 4,810 units. Capital = ₹186,868.50 (display ₹186,868). Fee-only stop risk = `4810 × (38.85 − 34.97 + 38.85 × .007)` = ₹19,970.88 (display ₹19,971). Using .0096 cost instead gives ₹20,456.74 versus the ₹20,000 budget. R:R formula `(0.1875 − 0.0096) / (0.10 + 0.0096)` = 1.6232, matching 1.62 after rounding.
- Quick COFORGE: entry ₹2,005.50, target ₹2,416.69, stop ₹1,711.79. Stop distance 14.65%, target move 20.50%, R:R 1.40. Reference risk sizing: min(floor(20,000/293.71), floor(200,000/2,005.50)) = 68 shares; capital ₹136,374. This reference quantity was not an executed order.
- Full NSE BODALCHEM: entry ₹111.31, stop ₹66.31, target ₹174.31. Displayed 444 shares × ₹111.31 = ₹49,421.64, matching ₹49,422. Stop risk before costs = 444 × ₹45 = ₹19,980. R:R 63/45 = 1.4. Historical win rate N/A correctly corresponded to only 18 samples versus the minimum 20; market opening alone does not resolve that evidence shortfall.
- NIFTY September futures: ₹24,204.50 minus spot ₹24,062.55 = ₹141.95 basis, matching the display. Target ₹23,867.20 and stop ₹24,457.47 imply approximately 1.333 reward/risk before costs.
- SMC COFORGE: ₹1,984.90 entry, target ₹2,108.83 and stop ₹1,908.36 imply +6.24% target move and approximately 1.619 reward/risk. This is a different setup from the equity screener, not the same strategy with interchangeable targets.
- ICICI Prudential Large Cap Direct Growth (AMFI 120586): NAV ₹120.41 dated 2026-08-28; 3-year starting NAV ₹83.69 dated 2023-08-28; 5-year starting NAV ₹65.86 dated 2021-08-27. Independently computed 3Y CAGR 12.89196%, 5Y CAGR 12.82573%, maximum drawdown −15.39326%, annualized 3Y daily-return volatility 12.54703%. Returns/drawdown match UI, and all match the application function. This checks arithmetic from the same public provider, not upstream NAV correctness against a second source.

Fund lookup displays a standalone scenario, while category ranking shrinks it toward peers. Thus the same fund's displayed ranges differed (lookup −4.7% to +31.5%, ranked −1.6% to +27.3%). Label those model scopes explicitly. “Positive in 87% of simulations” is not an 87% prediction-accuracy claim.

## Tests and evidence

- Existing regression suite: 37/37 passed, repeated locally in approximately 4.2 seconds. Passing this suite did not cover the newly reproduced issues.
- `audit_20260831_checks.py`: repeated cumulative-volume updates remain 1,500 rather than doubling to 3,000; stale-quote and cost-accounting failure paths reproduced; option/equity arithmetic checked. AST extraction avoids importing/running the whole application.
- `audit_20260831_nav_check.py`: public NAV retrieval and independent return/volatility/drawdown checks; no app execution or credential use.
- `audit-20260831-full-nse.jpg`: observed Full NSE counts, including the misleading success label.
- `audit-20260831-mcx-chart.jpg`: actual chart-loading error.
- Local `app.py` modification time remained 01:12:11 on 31 August 2026 during this audit. The newly created audit artifacts are not application fixes and do not need to be uploaded as an app deployment.

## Not verified and next acceptance checks

Not verified: private Streamlit logs, broker fills/margins, every symbol/category/expiry, fund benchmark returns currently blocked upstream, latest monthly Riskometer, paid AI response, cross-user penetration testing, secret rotation, production file hashes, holiday/after-hours behavior, restart durability, concurrency/load percentiles or future profitability.

Before another reliability sign-off: repair capital persistence and net-cost strategy accounting; add stale-data tests; separate immutable signal lifecycle from recommendations; fix chart delivery and reconnection; then repeat browser acceptance tests on the deployed build. Preserve explicit unknowns for missing official data. Prospective prediction validation needs a dated holdout process, point-in-time universe/category data, benchmark comparisons, realistic costs and a baseline—not a larger confidence number.
