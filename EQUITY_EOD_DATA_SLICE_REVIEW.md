# Cash-equity first data slice: private research proposal

## 27 October: acquisition-to-report implementation, inactive until owner run

The prepared decoder/pilot/verification changes are now combined with
equity_private_acquire.py, equity_real_report.py and their two test files in ONE
review. No formulas, app.py, technical_indicators.py, event_backtest.py, dependencies,
release branch or workflow are changed. The existing isolated strict-type CI step
already consumes mypy-equity-study.ini; extend its original file list to include
the two new modules, without replacing any old check.

The owner has approved private own-use12names/2022–2024/36annual requests. None
has been made by the builder. The CLI default is a zero-operational-I/O preview.
Explicit owner execution uses one hidden prompt for an existing read-only token;
no token file, environment token, capture credential or new-token generation is
used. Exactly36fixed HTTPS GETs maximum, no retries, redirects, extra instrument
master or calendar requests. Unexpected response schemas/bodies are not retained;
valid candle originals are saved byte-for-byte after secrecy and structure checks.
Any failure preserves the consumed directory and successful originals; no automatic
retry/resume/delete. Output stays outside Git, capture roots and Supabase, with a
rolling512MiB local free-space buffer and a72MiB raw-response budget. Socket
timeouts are not advertised as hard DNS or batch wall-clock limits.

One owner run produces exact original JSON, bound request/results, input/source
manifests, a derived decimal-text Parquet file with readback, and readable private
HTML plus JSON. It sends no data to an LLM, public repo, app host or archive service.
No signing/custody claim or cleanup permission is conferred. Reports are price/
cost scenarios: cash, fixed-initial-weight buy-and-hold and the separately labelled
existing daily technical sanity component.2022warms indicators;2023–2024 are
retrospective development, not untouched OOS.2025/2026 rows are rejected. Missing
names remain unavailable/reserved cash; no winner renormalization or neutral data
substitution. Corporate actions, dividends, exchange-calendar completeness and
historical executable-price/availability evidence are not manufactured.

Source-equivalent copies preserve derive_long_trade_levels, event_signal and
event_levels. Tests compare their complete ASTs after annotation removal and run
them against allowlisted pinned-source references. The original indicators and
event replay are imported unchanged. The frozen15-session horizon comes from the
existing level-function default, not a claim about the owner's current UI setting.
No GARCH/model fit, strategy search or full scanner reproduction is performed.

### Frozen current security identifiers, not historical key-continuity proof

RELIANCE INE002A01018; TCS INE467B01029; INFY INE009A01021;
HDFCBANK INE040A01034; ICICIBANK INE090A01021; ITC INE154A01025;
LT INE018A01030; SUNPHARMA INE044A01036; BHARTIARTL INE397D01024 (fully paid);
NTPC INE733E01010; TATASTEEL INE081A01020; M&M INE101A01026 (ordinary equity).
No automatic alias/ISIN substitution is allowed. Tata Steel's pre-split history
may require provider clarification; a missing response stops rather than silently
switching to the older security key or adding requests.

Identity references only (not price series or trading-performance evidence):

- https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_FILING_INDAS_120725_17102025193607_iXBRL_WEB.html
- https://www.tcs.com/investor-relations/investor-faqs
- https://www.infosys.com/investors/shareholder-services/faqs.html
- https://v.hdfcbank.com/content/dam/hdfc-aem-microsites/Annual_Report_FY22/pdfs/Report%20on%20Corporate%20Governance.pdf
- https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_FILING_GOVERNANCE_154340_29042026190952_iXBRL_WEB.html
- https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_FILING_GOVERNANCE_152178_22042026190850_iXBRL_WEB.html
- https://nsearchives.nseindia.com/corporate/ixbrl/PRIOR_INTIMATION_75521_15012026111426_iXBRL_WEB.html
- https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_FILING_79348_14022025130435_iXBRL_WEB.html
- https://www.airtel.in/about-bharti/equity?icid=header
- https://ntpc.co.in/sites/default/files/inline-files/NTPC_SE_NP_22092025_signed.pdf
- https://nsearchives.nseindia.com/content/circulars/CML59581.pdf
- https://www.mahindra.com/annual-report-FY2023/196/

The original rationale below remains background; retrieval/report wiring is now
built but not commissioned. No real result exists until supervised owner execution.

Review base: 0f5a1d8a00454b59077151858f9b5c4f162cc200. Inactive additions and
extension of the existing strict-typing file list only; no check is removed.
No scanner, profiling, risk, replay, app dependency or capture code is changed.
No orders, retrieval, secrets, installation, database writes or training are enabled.

## Recommended source and scope

Use Upstox Historical Candle V3 daily data through the owner's existing read-only
route, for private own-account research. Its published developer reply supports
local historical storage and private backtesting/ML. Another developer reply
distinguishes private replay/retention from redistribution. This is useful provider
clarification, not a blanket licence for public data display, shared datasets,
third-party access or a commercial service. Do not transfer data to a public repo
or external model provider. Any broader app audience requires separate review.

Primary references, reviewed 26 October 2026:

- https://community.upstox.com/t/clarification-on-upstox-historical-candle-v3-data-usage-for-personal-backtesting-and-ml-research/18061/2
- https://community.upstox.com/t/clarification-on-storing-upstox-nse-market-data-locally-for-private-research-backtesting/18112/2
- https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/
- https://upstox.com/developer/api-documentation/analytics-token/

The reply identifies absent delisted/merged histories and historical symbol/ISIN
mapping. It describes split/bonus back-adjustment, not dividend adjustment.
Those limitations are not repaired by successful API authentication. Current
back-adjusted values are not automatically historical executable prices or a
point-in-time dataset; reconcile factors/effective dates and cash dividends before
trade/size/fee claims. Do not silently use adjusted prices as original fills.
The Analytics Token is documented as free and read-only; no static IP is required
for historical data. Only one exists per account: this package never regenerates
or rotates it, which could disrupt an existing capture route.

## Frozen pilot, not trade recommendations

The proposed 12-name engineering set is RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK,
ITC, LT, SUNPHARMA, BHARTIARTL, NTPC, TATASTEEL and M&M. It is a purposive current
survivor set, chosen before this study's returns are examined, not historical index
membership or representative all-market selection. Report selection/survivorship
limitations. Never silently substitute a missing name or select on measured returns.
This is the first pipeline slice; it does not finish the entire cash-equity segment.

Dates are 2022-01-01 through 2024-12-31 only. Use 2022 for indicator warmup and
development, then chronological 2023/2024 evaluation with overlap purging/embargo.
Prior usage means retrospective development, not newly untouched out-of-sample
evidence. 2025/2026 stay sealed. Existing-rule behavior must be frozen and compared
with cash and the same-cohort buy-and-hold baseline before variants/models.
NIFTY can be a separately admitted price reference; do not call price returns TRI.

The proposal gives 36 annual equity request windows (12 names x 3 years), with
no requests executed. No index request is hidden in that budget. Resolve and
freeze real ISIN keys first, retain exact responses privately, derive Parquet
only after quality checks, and do not write this bulk history into Supabase.
No fixed row count is claimed: exchange sessions, gaps and missing names are facts
to measure, never rows to invent. No catch-up is performed on the live capture.

## Costs: explicit scenarios until the dated fee ledger is verified

Show 30/60/100 bps round-trip stresses without choosing the best-looking level.
These are not the owner's actual tariff, a fee certificate or executable-price
evidence. Separately build the dated fee ledger from official circulars and the
applicable broker schedule: STT both sides for delivery, buy stamp, exchange/IPFT,
SEBI, brokerage caps/minima, GST on its correct base, DP per ISIN/day and slippage.
Current charges must not be applied retrospectively.

NSE FA56129 documents the 2023 change and separate IPFT contribution. FA64232
documents the 2024 uniform fee change. Earlier slabs and actual broker pass-through
need their own evidence; neither circular alone proves the owner's invoice.
Brokerage, DP charges and rounding are not inferred from today's marketing page.
No new fee schedule or cost model is wired into the existing replay by this patch.

- https://nsearchives.nseindia.com/content/circulars/FA56129.pdf
- https://nsearchives.nseindia.com/content/circulars/FA64232.pdf
- https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies

## What the new code proves

equity_eod_pilot.py returns a hashed, inactive proposal, not permission or data.
equity_daily_ingest.py accepts explicit bytes only: bounded JSON, exact candle
shape, finite positive OHLC, integer quantities, ISIN-key shape, local session
labels, date bounds, duplicates, chronological normalization and original hash.
It reads no file or credential and sends no request. Its short accepted-label
allowlist is structure checking, not proof that the API request used daily bars.
Instrument binding remains caller-supplied, not provider-signed. All data rights,
calendar/action/admission/training/performance flags remain false. A good decoder
does not prove a complete or unbiased dataset, or restore the missing histories.

The owner-verification scripts replace pasted Python -c text with file invocation.
Preview performs no launches/writes. Confirmed preflight verifies Python and a
synthetic temporary-file cycle. FullSuite is one script invocation: failure stops
before the pinned external receipt runner can execute. The external runner and
public clone are separately bound; no arbitrary command string is evaluated.
The native tests must execute on PowerShell 5.1 and 7; parser-only tests are not
being described as native execution. Existing source/clock/hash gates stay intact.

Real source admission, retrieval, action reconciliation, dataset-to-report wiring,
prospective paper validation, all models and deployment remain uncommissioned.
