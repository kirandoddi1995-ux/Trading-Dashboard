# Intraday NIFTY options: candidate specification and replay data contract

Review draft, 2026-10-04. Documentation only. No strategy, recorder, workflow,
database or approval gate is enabled by this document. All outputs are RESEARCH_ONLY.

Revision: an offline directional research runner now exists in
`intraday_directional_replay.py`; it is NOT connected to the dashboard or orders.
No real historical replay has yet run: no local intraday CSV/Parquet was found.
A read-only check of `market_cache.sqlite3` found 270 NIFTY rows, all at the same
time of day, spanning 2025-07-13 to 2026-08-13 in the stored timestamp strings.
That is not the required five-minute series; the cache has no interval column.
It compares C single-bar and C persistent bias WITHOUT volume, before option P&L.
A/B volume variants are deferred: same instrument key does not control for the
next-month-to-near-month change in trading activity. A maturity/roll-aware baseline
needs separate validation; the 20-session baseline below is withdrawn for use.

## 1. What the current code actually does

- `app.py:6660 determine_market_bias()` fetches daily history, injects a developing
  daily candle with `prepare_live_daily_bar`, calculates EMA20, RSI14 and MACD
  (12,26,9), and combines these with previous-close movement, PCR, OI additions,
  15-minute/hourly trends and volume confirmation.
- Its daily volume test uses a rolling mean including the current bar and a
  linear session fraction with a 5% floor. It is not a same-time volume baseline.
  Index volume cannot be used as traded participation evidence.
- `app.py:3181 get_timeframe_trend_label()` compares the last close with EMA20;
  deviations greater than +0.05% / below -0.05% are Bullish / Bearish. The helper
  itself does not exclude forming bars.
- `app_runtime.py:300 score_option_direction()` is the pure conflict-aware scorer.
  Its default minimum is 25; the effective minimum is always at least 25 even
  though the dashboard's initial setting is 15. Three factors and two named
  groups are required; the groups are not proof of statistical independence.
- `app.py:4642 compute_pcr_and_max_pain()` uses OI across the supplied chain,
  treating missing OI as zero. `app_runtime.py:110 option_oi_change_bias()` needs
  current and previous OI on paired strikes. Neither input can be faithfully
  reconstructed from the current narrow recorder inventory alone.
- `app.py:6794 build_option_recommendation()` maps bullish bias to CE and bearish
  bias to PE, selects near ATM, and calls derivative preflight. This remains
  subject to the option-entry hold; a research replay must never call an order API.
- `option_capture_job.py:85 capture()` returns immediately on the first CAPTURED
  snapshot within its bounded window. It is not a 60-second tick archive.
  `option_capture.py` defines four slots; `option_capture_archive.py` verifies
  slot files. These files support snapshot research, not full-session replay.
- `derivative_quotes.py:10 decode_v3()` retains packet and receipt timestamps,
  best bid/ask/sizes, OI, raw IV/Greeks and last trade time. Exchange book time is
  explicitly unknown. It does not retain every OHLC field in its normalized row.

Correction to the earlier proposal: switching daily indicators to five-minute
bars is a NEW strategy adapter, not reproduction of the existing dashboard.
Keep a separately named legacy shadow diagnostic if full original inputs become
available; never mix its results with the candidates below.

## 2. Frozen initial candidates

All three are new `intraday-nifty-bias-v1` research variants. They share the same
pure scoring arithmetic and conflict rules, contract selection, costs, sizing,
data eligibility and exits. No weights are optimized initially.

Shared adapter:

- Decisions at completed five-minute bar ends, anchored to the verified regular
  session start. For a normal 09:15 start, first bar is [09:15,09:20). Never assume
  weekday alone establishes an open session; reject unsupported special sessions.
- Five-minute NIFTY closes supply EMA20, RSI14 and MACD(12,26,9), using the same
  indicator library/version as the app. Previous sessions warm the indicators;
  today's values and trends use only bars available by the decision time.
- Previous close means the verified previous completed session close, not the
  last supplied bar. Session change uses the completed five-minute close.
- Fifteen-minute and one-hour EMA20 trends use completed bars only, with the
  existing +/-0.05% labels. Before today's first completed hour, no same-day hour
  confirmation exists: pass None, do not substitute yesterday's final hour.
  Higher-timeframe bars use the same session anchor; incomplete closing fragments
  are not promoted to full bars.
- NIFTY spot has no traded volume. VWAP is absent in this version: futures VWAP
  must not be compared directly with spot as though futures basis were zero.
- PCR and OI-change direction are absent for ALL three variants. Narrow-strike
  PCR is not the dashboard's whole-chain PCR; v1 makes no positioning claim.
- Effective minimum score is frozen at 25. Missing optional inputs earn no points;
  missing required prices, indicator warm-up or today's 15-minute trend is an
  unavailable decision, not a tradable Neutral. Store missingness separately.

Candidate A — single-bar bias: apply the adapted scorer at each decision.
Bullish/Mildly Bullish both mean +1; Bearish/Mildly Bearish mean -1. A usable
opposite direction triggers exit. Valid Neutral does not count as reversal.

Candidate B — persistent bias: identical scoring, but require two consecutive
eligible five-minute decisions in the same direction for entry AND reversal exit.
Neutral or unavailable resets the pending confirmation. Risk/deadline exits do
not wait for confirmation. Opposite signals must not be evaluated on a forming bar.

Candidate C — volume ablation: identical to A, with volume_confirmed=False.
This changes scoring and factor/group qualification as the existing scorer does;
it is not merely removing five display points.

WITHDRAWN initial volume hypothesis for A/B (not eligible for implementation):
use the identified nearest eligible NIFTY futures contract's
completed five-minute traded volume, divided by the median volume in the SAME
session-relative bucket over 20 previous complete eligible trading sessions.
Use the same instrument key throughout a baseline; do not splice rolled contracts.
Require all 20 sessions, positive median, verified units and no gaps in that bucket.
Confirmation means ratio >=1.0 (existing confirmation boundary, NOT validated).
Without that evidence A/B are NOT_EVALUABLE; only C can run. This prevents a
missing-volume substitution from making A/B secretly identical to C.

### Scoring arithmetic retained from the runtime

- Spot versus EMA20: +/-0.05% threshold, 15 trend points.
- Session move: absolute >=0.05%; min(10, abs(change_pct)/0.50*10) momentum points.
- RSI >52 bullish / <48 bearish: min(10, distance from threshold/18*10).
- MACD histogram positive/negative: 10 momentum points.
- Each aligned 15-minute / one-hour trend: 15 intraday points.
- Volume: 5 participation points to the pre-volume score leader, only with at
  least three existing factors; the source scorer resolves a tie to Bearish here.
- Net score = rounded bullish minus bearish scores, each capped at 100.
- Need absolute net >=25, three factors and two groups. Today's 15-minute trend
  must match. Scores below 45 need matching one-hour trend; a contrary known hour
  blocks any strength. Opposing a session move of at least 0.10% additionally needs
  strength >=45, both intraday trends aligned and at least four factors.
- Strength >=45 is strong; otherwise mild. Record raw factors and rejection
  reasons, not just the final direction. Preserve exact boundaries in tests.

## 3. Common position and execution rules

- Long options only, one open position per candidate; candidates are independent
  simulated portfolios, not combined exposure. CE for +1, PE for -1.
- Use the nearest listed NIFTY option expiry strictly AFTER the trading date;
  exclude same-day expiry in v1. If none is verified/captured, skip. This is a
  research policy, not a hardcoded exchange expiry weekday or weekly designation.
- Among strikes in that expiry, choose nearest ATM using underlying information
  available at decision time; equal-distance tie goes to lower strike. If that
  selected contract lacks an eligible book, skip rather than searching hindsight
  liquidity for a better-performing strike. Lot/tick/terms come from dated master.
- No replacement or rolling of an open position. Keep its instrument subscribed
  until exit/residual resolution even when ATM moves outside the selection band.
- Order time = decision availability time + registered latency. Primary scenario:
  1 second; stresses 2 and 5 seconds. These are unvalidated modelling assumptions,
  not measured broker latency. Select the first eligible observed book at or after
  that time, within a maximum 5-second wait; otherwise entry is NOT_FILLED.
- Buy at ask; sell at bid. Best-level size must cover quantity under verified
  provider units. Larger quantity requires recorded depth or skips. Displayed
  liquidity does not guarantee a fill: results are QUOTE_BASED_SIMULATION, with
  adverse tick/slippage scenarios, never genuine execution evidence.
- Primary research spread ceiling: 1% of midpoint, with positive uncrossed prices,
  positive usable size and age/skew within the provisional 5s/2s capture bounds.
  The 1% is a new frozen research assumption, NOT the app's existing 8% policy or
  evidence that a trade is safe. Report exclusion sensitivity, not tuned returns.
- The exit contract's actual bid is used; an entry-only spread ceiling must not
  prevent a risk/deadline exit. Invalid/missing exit books produce EXIT_UNRESOLVED,
  no zero loss, no last-price substitution, and no automatic removal from results.
- Account-feasible replay: risk budget B = capital * sidebar max_risk_pct / 100; position funding cap uses
  the existing max_position_pct. Whole lots only. Conservatively cap premium paid
  plus modelled round-trip charges within B, as well as funding/margin/liquidity.
  If one lot cannot fit, no trade. This is intentionally restrictive, not sizing
  from an assumed stop that might not fill. Settings are frozen per replay run.
- Net marked loss uses executable bid and accrued/estimated exit costs. Trigger
  exit at B independently of reversal. Because full premium is already bounded
  by B, this threshold may rarely trigger; a tighter premium stop is a separate
  future candidate, not silently added here. Gaps/cost uncertainty can exceed B.
- Separately run standardised ONE-LOT quote-based research, without claiming
  account affordability or approval. Report required premium, charges and margin;
  never inflate the user's risk setting to obtain samples. Compare that view with
  account-feasible replay, including every unaffordable/skipped candidate. Neither
  view can run from underlying candles alone.
- Deadline comes from dated broker instructions/product eligibility and verified
  session bounds. Initial system buffer: 15 minutes BEFORE the earliest applicable
  broker cutoff or regular session end, explicitly a provisional policy. No new
  entries from one completed five-minute interval before that system deadline.
  Missing instructions mean no entry. The research recorder continues through
  session end to observe failed close attempts; broker square-off is not assumed.
- Reversal, risk and deadline exits may happen independently: earliest observable
  trigger wins; ties prioritize deadline, then risk, then reversal. Risk monitoring
  uses observed quote events, not future candle lows. Data loss invokes an
  unresolved-position state and blocks new entries. No same-decision re-entry;
  after a completed exit wait for the next completed bar and applicable confirmation.

## 4. Quote source: recommended approach

Prospectively record ONE continuous Upstox V3 full-mode session for a bounded
NIFTY universe. Official feed docs describe bid/ask depth and quantities, OI and
packet timestamps: https://upstox.com/developer/api-documentation/v3/get-market-data-feed/
It is broker-distributed observed market data, not exchange tick-by-tick data or
independent confirmation. Verify completeness and units from the pilot; never
infer book exchange time or fill probability from packet timestamps.

Do not widen or repurpose option-capture-v1 behind its existing identity. Proposed
separate `option-session-v1` owns a continuous feed, dynamic subscriptions, bounded
disk spool and chunked Drive archives. Reuse reviewed TLS authorization, protobuf
definitions and OAuth verification, not the slot collector's first-snapshot loop.
Do not enable this recorder as part of the documentation delivery.

Start with NIFTY spot, one explicit futures-volume reference and CE/PE around ATM
in the nearest non-same-day expiry, initially +/-5 strikes. Add strikes causally
when ATM moves; enforce a hard total-key cap and retain held contracts first.
No data for newly subscribed contracts before subscription acknowledgment/valid
snapshot. Decisions outside captured coverage are unavailable, never backfilled.

Archive provider-delivered book updates and diagnostic heartbeats, not four
snapshots or five-minute OHLC of option LTP. Full-session updates are necessary
for observed loss/deadline exits; five-minute samples alone cannot establish them.
Retain 1-minute underlying bars with source/revision/availability provenance,
aggregating to 5/15/60 minutes without inventing prices in gaps. Sparse index
updates alone do not prove complete minute highs/lows. Validate provider bar
timestamp/completion semantics before the adapter can run.

Best hosting for initial measurement: an awake Windows PC with local scheduling,
clock checks, disk spool and an independent heartbeat check. An always-on host
can replace it using the same CLI/data contract. GitHub Actions remains useful
for the bounded pilot but is not the primary full-session scheduler. Verify the
account's actual stream entitlement BEFORE an additional persistent connection;
do not displace the dashboard. Shared-stream fan-out is an alternative architecture,
not something provided by the current separate collectors.

Market-data token eligibility, expiry, retention rights and connection limits need
account verification. No order API, account-position access, token refresh bypass,
licence assumption or hosted credential change is authorized by this draft.

## 5. Required durable records

Every chunk: schema/policy versions, session ID, trading date, venue, start/end,
source, recorder build/dependency hash, clock measurement, reconnect generation,
instrument inventory changes, row count, byte size, SHA256 and previous-chunk hash.
Every row: instrument/contract-version key, event type, packet timestamp, local
UTC receipt time, monotonic local sequence, last-trade time, exchange book time
(NULL when unknown), bid/ask/sizes, depth if available, OI, raw IV/Greeks, cumulative
volume, bar fields when present and raw decoded selected fields. Missing stays NULL.
Packet time does NOT refresh absent fields; field availability is separate.

Control records: subscribe/unsubscribe/ack, master changes, session status, clock
health, disconnect/reconnect, raw receive gaps, overload/dropped records, auth and
Drive failures, stop/cap reasons. New connection generation invalidates old books.
Absence of updates is not proof the book remained fresh or that no trades occurred.

Five-minute sealed chunks with Zstd Parquet; bounded raw-byte/file limits and disk
budget; exact caps chosen AFTER pilot bytes/minute measurement, before commissioning.
Each chunk commits to local spool before upload, then SHA256/download/content and
row-count verification plus manifest verification. Retry identities are immutable;
same identity/different bytes is a conflict. Delete local chunks only after verification.
Daily completeness manifest records expected/actual intervals, gaps, coverage per
contract and unclosed positions. Chunk success is not proof of complete-session success.

Zero Supabase tick storage. Drive holds history; manifest/health can also live there.
Store each payload once, avoid normalized-full-payload plus duplicated _row_json.
Storage = observed compressed bytes/minute * captured minutes * sessions retained;
measure raw/compressed sizes, queue depth, upload lag and Drive request/error rates.
Do not extrapolate the slot recorder's 2 MiB cap to a continuous session. Fail closed
on disk/byte caps and retain interrupted-session evidence; never silently downsample.
Private licensed storage only; verified archive copies can be mirrored to the PC.

## 6. Replay eligibility and conclusions

- Process records in observed availability order. Historical bars downloaded later
  may support a candle-only screen, but are not proven decision-time originals.
  Store revisions without overwriting earlier versions; use only then-known data.
- A signal-only replay may run from underlying bars without option books, labelled
  DIRECTIONAL_RESEARCH. It cannot report option profitability or executable fills.
- Quote-based P&L needs entries AND exits, contract terms, dated charges, margin
  assumptions and sizing inputs. Missing ones make that trade/run NOT_EVALUABLE.
  Never mark an unobserved exit at midnight or use the next day's bid silently.
- Excluded/missing periods are reported across candidates. Compare A/B/C on their
  shared eligible periods; report C-only periods separately. Do not discard hard
  days or unresolved positions to improve performance.
- Training/development periods precede a frozen held-out chronological period.
  No threshold search on holdout; changes create a new policy and need new holdout.
  Report costs, turnover, drawdown, maximum loss, fill-model stresses, coverage,
  unresolved exits and outcomes by regime, not just win rate. Calendar events and
  expiry-adjacent days must be identified, not assumed interchangeable.
- Pilot/5-10 sessions establish transport and data quality, not profitable edge.
  There is no promised number of weeks to validation: effective independent days,
  trade counts, uncertainty and regime coverage determine evidential strength.
- Research artifacts cannot populate genuine execution/outcome evidence tables,
  remove the Greek hold, satisfy missing-EV evidence or unlock model authorization.
  Any promotion needs separate reviewed validation and live execution calibration.

## 7. Implementation boundaries and acceptance tests

Next implementation design should separate a pure bar/strategy adapter, event replay,
shared dated Decimal cost/broker-margin adapter, continuous recorder/spool, archive
verifier and CLI. No Streamlit import is required to run offline replay. No order
credentials or database writes are required by the recorder. Current pilot unchanged.

Tests must cover: forming-bar exclusion; exact thresholds and warm-up; timestamps/
revision availability; completed higher-timeframe alignment; futures roll/baseline
eligibility; volume ablation; missing PCR/OI/VWAP staying absent; future quotes never
used early; no LTP fills; invalid size units/depth; ATM ties and uncovered strikes;
held subscriptions retained; reconnect/gap invalidation; immutable chunk retries;
Drive failure/local spool recovery; auth/clock/cap failures visible; latency/exit
ordering; missing exit residuals; no same-bar re-entry; lot/risk/cost rounding;
missing broker deadline; common-period comparisons; no research-to-approval routing.

## 8. First offline directional runner and required inputs

Implemented research subset: C single-bar versus C two-bar persistence; completed
five-minute EMA/RSI/MACD, completed 15-minute/hourly trends, frozen score 25, no
volume/PCR/OI/VWAP. It reuses `app_runtime.score_option_direction` and
`technical_indicators`, without importing Streamlit or any provider client.

CSV columns: timestamp (bar START), Open, High, Low, Close, available_at. Timestamps
must carry timezone offsets. Session JSON is an ordered array with open, close,
previous_close, source and availability_basis. Supply verified regular sessions
and previous completed-session closes; do not invent a weekday holiday calendar.
`prepare_nifty_replay.py` now produces these inputs from the source-hashed download,
the explicitly reviewed `nifty_session_calendar.py`, and daily Upstox artifacts.
Its quality report retains missing dates and bars; special sessions are excluded
and warm-up resets after excluded trading dates. Follow NIFTY_HISTORY_DOWNLOAD.md
before invoking replay. Readiness remains research-only and does not enforce the
separate development/validation/holdout scoring masks.
Only 375-minute sessions with all 75 aligned bars are supported. Incomplete days
are excluded and reported, not filled. Include several earlier complete sessions
for hourly EMA20 warm-up; first warm-up periods are explicitly unavailable.

availability_basis is `recorded_bar_end` or `historical_final_assumed_bar_end`.
For retrospectively obtained bars, the latter explicitly labels the bar-end
availability assumption; it cannot establish actual decision-time data or revisions.
Genuinely delayed bars are excluded in v1, not retroactively traded at earlier opens.
Raw import preserves timezone requirements; no implicit IST guessing.

Each decision acts at the NEXT five-minute bar OPEN as an underlying reference,
not a quote fill. Reversal closes there; re-entry cannot occur at that same open.
End-of-session close is explicitly labelled SESSION_END_CLOSE_REFERENCE. This
directional subset does not model broker cutoff, option risk stops, costs, margin,
latency or executions; those belong to the later quote-based contract above.
Report signed underlying return, adverse/favourable excursion and episode count,
not profit or an options win probability. Last-bar signals cannot open a position.

Run locally after data review:

```powershell
.\.venv\Scripts\python.exe intraday_directional_replay.py --bars "C:\private-data\nifty_5m.csv" --sessions "C:\private-data\nifty_sessions.json"
```

The CLI prints research JSON only and performs no network or database access.
Do not supply tokens or connection strings. The example paths are placeholders,
not files created by this delivery. Data provenance, available date range and a
chronological holdout must be agreed before interpreting a real result. No data
or validation claim follows from synthetic regression fixtures.

Needed from Kiran NOW: a data export or the location/source of available five-minute
NIFTY history, its timestamp semantics and date range. Capital, max_risk_pct and
max_position_pct are needed LATER for account feasibility; not this directional run.
Daily history is not an acceptable replacement. Expired-option candles do not
resolve the missing executable-quote history.

This document defines research policies, not an approved strategy or full-session
recorder. Transport and broker assumptions still require live observation.
