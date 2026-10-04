# NIFTY futures: costs and data commissioning round

## Scope and hard boundary

This round builds offline research tools, not new signals or a live trading
permission. There is no database ingestion, automatic downloader, order call,
live tariff configuration or strategy replay. 2025 validation and 2026 holdout
returns remain unexamined. Public 2025/2026 tariff and contract-rule research
does not authorize inspecting their price performance.

## Costs: component schedules, not one date-wide fee rate

`fo_cost_commissioning.py` selects a separate non-overlapping dated record for
brokerage, STT, exchange, IPFT, SEBI, stamp and GST. Missing dates, unknown
values, unreviewed evidence, invalid units and overlapping periods block.
Rates must be decimal strings; fractional 0.0005 means 0.05%, NOT 0.0005%.
Each VERIFIED record needs an HTTPS source without credentials/query strings,
the retained evidence file's SHA-256, published_on, effective_from/to and an
aware reviewed_at. Dates are inclusive; split at each actual rate change.
Review metadata and hashes record operator review, not automatic proof that
a circular was interpreted correctly. Keep source documents privately.

Historical commissioning is retrospective: reviewed_at is the actual review
time, not backdated to 2022. published_on must be no later than the trading
date. The new research interface deliberately leaves the existing live-time
provenance guard in intraday_fo_costs.py unchanged.

The JSON template contains official STT reference values but leaves them
UNREVIEWED until the retained sources and review metadata are completed:

- 2022 to 31 March 2023: futures sell 0.01%, NSE/FATAX/32385 (16 May 2016).
  https://nsearchives.nseindia.com/content/circulars/FATAX32385.pdf
- 1 April 2023: 0.0125%, NSE/FATAX/56235.
  https://archives.nseindia.com/content/circulars/FATAX56235.pdf
- 1 October 2024: 0.02%, NSE/FATAX/63809 (9 September 2024).
  https://nsearchives.nseindia.com/content/circulars/FATAX63809.pdf
- 1 April 2026: 0.05%, NSE/FATAX/73524 (31 March 2026).
  https://nsearchives.nseindia.com/content/circulars/FATAX73524.pdf

Other historical components remain UNKNOWN, not silently held constant. Obtain
every applicable NSE transaction/IPFT revision, SEBI fee order, stamp law and
GST basis/rate before splitting their periods. A useful current reference is
NSE/FA/73061, effective 1 March 2026 (futures exchange 182.99 + IPFT 0.01
rupees/crore, separately):
https://nsearchives.nseindia.com/content/circulars/FA73061.pdf
It is NOT a 2022-2024 tariff. Avoid counting IPFT twice in an inclusive charge.

Working brokerage is flat INR 20 per executed order, explicitly ASSUMED.
Upstox's current public futures plan says min(INR 20, 0.05% turnover), whereas
options are flat INR 20. That is not proof of Kiran's plan or its history:
https://upstox.com/brokerage-charges/
The engine supports FLAT_PER_ORDER or MIN_CAP_TURNOVER with turnover_rate.
Do not infer historical account terms from today's website. A verified plan
record requires a contract note/plan confirmation; do not put account details,
contract notes or credentials in GitHub or chat.

The scenario supports exactly one executed order on each side, whole lots,
Decimal prices and per-side paise rounding. Partial fills within the same
order are not extra orders. Multiple-order and broker-square-off charges
are not included; unsupported order shapes must not be represented as one.
Reconcile component rounding and GST basis against contract notes. Each dated
GST record must specify taxable_components explicitly (a nonempty unique subset
of brokerage, exchange, IPFT and SEBI). There is NO default GST base. Split
periods whenever the taxable base changes, not only when the rate changes.
SEBI's portal notes that its fees are subject to 18% GST from 18 July 2022:
https://siportal.sebi.gov.in/
Review the applicable dated notification and broker pass-through before filling
this interval; do not assume today's GST base throughout 2022. The template's
taxable_components is intentionally null until review.

Any assumed component yields ASSUMPTION_ONLY and cost_policy_commissioned false.
All reviewed components yield REVIEWED_RESEARCH_ONLY; approval_authority and
fill_evidence stay false. Net scenario P&L is not a claim of actual fills,
tradable edge, historical margin sufficiency or eligibility for live trading.

### Contract-specific terms

Create a PRIVATE terms.json array of reviewed records using the same provenance
fields plus contract_key, expiry (actual ISO date), lot_size, exchange "NSE",
segment "FUTURE" and underlying_key "NSE_INDEX|Nifty 50". Store separate
effective periods per contract key if terms changed. Never apply a single lot
size timeline blindly across all expiries: old and new contract sizes can
coexist during transitions. Lookup requires an exact key/date match. Most
recent lot size and provider metadata alone are not historical NSE authority.

NSE's October 2025 circular illustrates these contract-specific transitions:
https://nsearchives.nseindia.com/content/circulars/FAOP70616.pdf
Reconcile archived NSE contract files/circulars with provider lot size and
tick units. Do not assume a raw provider tick value is in rupees.

PRIVATE trade.json contains contract_key, entry/exit decimal strings, lots,
entry_side BUY/SELL and aware entered_at/exited_at. Costs apply actual selected
contract lot size and SELL turnover (entry for a short, exit for a long).
Expiry-day scenarios are rejected under this first research policy.

```powershell
.venv\Scripts\python.exe fo_cost_commissioning.py --ledger "C:\Users\banga\Documents\TradingResearch\reviewed-fees.json" --terms "C:\Users\banga\Documents\TradingResearch\terms.json" --trade "C:\Users\banga\Documents\TradingResearch\trade.json" --review-as-of "2026-10-05T18:00:00+05:30"
```

Use the ACTUAL review timestamp; the timestamp above is syntax only. The public
template is deliberately not ready to calculate. Do not upload private inputs.

## Upstox availability: prove one contract/session, then decide bulk scope

The expired historical endpoint documents 5minute OHLCV/OI and bar START times:
https://upstox.com/developer/api-documentation/get-expired-historical-candle-data/
Both expired-contract and history APIs require Upstox Plus (UDAPI1149).
Expiry discovery covers only SIX MONTHS, not a documented 2022 onward list:
https://upstox.com/developer/api-documentation/get-expiries/
An analytics token is not proof of Plus entitlement or archive depth. No paid
subscription or data purchase is authorized by this tooling.

`nifty_futures_history.py` takes a reviewed actual expiry, asks the expired
futures endpoint for its key, validates NIFTY/NSE/FUT identity and positive lot
size, and uses ONLY that returned key to request five-minute bars. It never
constructs a key from a symbol or guessed Thursday/Tuesday. Requested prices
and expiry are restricted to 2022-2024. No 2025/2026 price probe is permitted.
Requests stay within a month; this is a conservative local bound, NOT a claim
about the expired endpoint's documented maximum or oldest retained date.

Choose an actual 2022-2024 expiry from independently retained NSE records and
one regular session before it. Do not guess an expiry just to run the command.
The endpoint may reject older contracts or return no candles. That means
availability is UNPROVEN, not zero volume or a valid empty history.

First run (replace dates with the independently checked contract/session):

```powershell
.venv\Scripts\python.exe nifty_futures_history.py --start YYYY-MM-DD --end YYYY-MM-DD --expiry YYYY-MM-DD --output "C:\Users\banga\Documents\TradingResearch\futures-probes"
```

Expect PREVIEW, network_calls 0, no token prompt. To perform that SAME reviewed
probe, append --confirm-network. Token entry uses a hidden prompt, is never
saved, and HTTP bodies/transport exceptions are never printed. Requests verify
TLS, reject redirects, have bounded timeouts/response size and transient retries.
No changes to dashboard streaming or scheduled workflows are made.

The immutable gzip artifact retains provider contract, retrieval timestamp,
contract hash, candles and row hash. It is stored outside the repository and
read back for verification. Incomplete sessions retain explicit missing and
unexpected times in session_check (FAIL); even PASS leaves replay_ready false.
Provider lot size still needs dated NSE reconciliation. Compare a real sample
with an independent record and confirm bar-start semantics and session calendar
before bulk acquisition. No hidden trimming, backfilling or bid/ask reconstruction.
If the artifact already exists, the CLI stops before token entry/network access.

Only after entitlement AND older-contract depth are observed should we build
the bulk inventory. If 2022-2024 is inaccessible, leave its futures P&L unknown;
do not open 2025/2026 to solve the problem. Decide on a documented alternative
dataset or restrict work to clearly labelled spot-direction research.

## Frozen execution/roll contract for this first round

`nifty_futures_research_contract.py` records research policy v1:

- At session open, choose the nearest eligible listed contract. Roll TWO
  reviewed trading sessions before actual expiry; no weekday guesses or
  future-volume selection. No intraday roll or carried position, so no cross-
  contract price difference is booked as trading P&L. Require next-contract
  data on roll day; missing data excludes the session, never falls back to the
  expiring contract. Listing evidence must precede the session decision.
- No entries in a contract on its expiry day. Do not claim expiry settlements
  can be modelled as an ordinary candle close.
- Completed signal bar, next-bar open price REFERENCE; not a guaranteed fill.
  Reversal exits act at the next open; no same-bar re-entry. Final exit must use
  a reviewed dated broker deadline with an explicitly frozen buffer, never the
  15:30 close as a presumed executable square-off. Deadline integration is a
  prerequisite for the eventual replay, not implemented by this probe.
- Adverse tick stress per side is frozen to 0/1/2/4. Zero is reference-only;
  all other levels are ASSUMED combined spread/slippage stresses, not measured
  fees or observed fills. Round buys up/sells down to a verified rupee tick.
  No quote size, latency, impact or margin history is fabricated. Set the
  primary scenario before any next hypothesis run; other cases are sensitivity,
  not alternatives from which to pick a winning backtest.
- OHLC cannot establish intrabar stop priority/fills. Such exit rules remain
  unsupported; define completed-bar rules or acquire finer execution data.

No new hypothesis is implemented or run in this release. Costs, data depth,
calendar, lot/tick terms and broker deadline must pass review first. Fewer
trades and futures-first screening are hypotheses, not guaranteed remedies.

## Local tests

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_fo_cost_commissioning.py tests/test_nifty_futures_history.py tests/test_nifty_futures_research_contract.py --basetemp "$env:TEMP\fo-commission-review-$([guid]::NewGuid().ToString('N'))"
```

Production modules and equity release fingerprint are unchanged. All tools
remain local/manual. No Drive upload, Supabase query, subscription change or
GitHub action is performed by this round.
