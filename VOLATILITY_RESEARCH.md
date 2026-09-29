# Volatility research workbench (v1)

## Boundary and deployment

This is a research engine, not a promoted trading model. Its only app caller is
the display-only workbench in the F&O area. The UI returns no report to the
decision path. There are no database writes, feed requests, scheduled jobs, order
calls, model-registry writes or promotion flags. Reports always contain
`mode=RESEARCH_ONLY` and `approval_eligible=false`, irrespective of input fields.
No SQL migration or new dependency is required.

Existing `iv_surface.normalize_iv_surface` DOES affect decisions today:
`app.py` maps `production_valid` to `_call_validation`/`_put_validation`; candidate
selection rejects an invalid leg with `independent_option_validation_failed`
before calling derivative preflight. This existing protection is unchanged.
The old path's implicit rate/dividend/expiry/IV conventions are NOT repaired by
this research work. Its replacement is a separate fail-closed deployment once
provider conventions, reviewed carry inputs and comparison policy are settled.

The new `greek_consistency` comparator runs in SHADOW only. It does not bypass or
replace the old gate. It requires explicit normalized conventions and per-Greek
absolute/relative tolerances; no values are invented. Even `CONSISTENT` is not
authority. Uploaded conventions/provenance are declarations, not authenticated
exchange or broker evidence. There is deliberately no live-chain auto-adapter
that guesses missing fields. No research report can substitute for official
clearing deltas, genuine fills, outcomes or existing governance requirements.

Upload the changed Python files, tests and this document manually. The app change
changes the release fingerprint; use the separately reported SHA for
`EXPECTED_EQUITY_CODE_SHA256` after uploading the exact reviewed files.

## What runs now

- Bid/mid/ask IV solving with explicit spot BSM carry. European options only,
  ACT/365F actual timezone-aware expiry. No extrapolation, guessed IV units,
  zero-filled missing fields or solver-boundary replacement.
- Spot delta, gamma, theta/calendar day, vega/volatility percentage point;
  vanna per volatility point, volga per squared volatility point, charm per
  calendar day, all per underlying unit. These are constant-IV/carry partial
  derivatives, not sticky-delta surface hedges or clearing-house deltas.
- Call/put parity interval intersection and observed-strike monotonicity,
  slope and convexity feasibility using linear programming.
- Multi-start raw SVI fitting to OTM total variance, spread-scaled residuals,
  with at least seven distinct strikes spanning the forward. Rejected fits
  remain rejected. No automatic repair to make the plot pass.
- Sampled butterfly-density diagnostics over observed coverage; same-delta
  interpolation with explicit spot-delta convention. Multiple/no roots are
  unavailable; wings are not extrapolated. Finite-grid tests are NOT a proof of
  global static-arbitrage freedom. Discrete dividends are not explicitly modeled;
  reviewed continuous-yield approximation is a research limitation.
- Cross-expiry fitted total-variance diagnostics on overlapping log-forward-
  moneyness. Not calendar strategy authorization or proof of executable arbitrage.
- Constant-tenor forward-ATM IV via bracketed total-variance interpolation;
  no nearest-expiry splice, extrapolation or negative forward variance hiding.
- IV rank and strict-less-than percentile on a consistent 252-session series.
  Insufficient history stays unavailable. Flat-history rank is undefined; rank
  is not clipped when today's IV exceeds the historical range. Dates must match
  the supplied completed-session calendar. Calendar itself must be reviewed.
- Adjusted daily close-to-close sample realized volatility (explicit annual
  session count); missing sessions/adjustments are not filled. IV minus trailing
  RV is descriptive, not expected profit. Both horizon lengths are reported.
- Full repricing under user-declared spot/time/IV shocks. IV change is in
  percentage points (e.g. -5 means 30% to 25%), not percentage change. Signed
  underlying units, not lots. Scenarios exclude fills, spread, costs, margin and
  settlement and cannot estimate actual event-IV contraction from no history.

## How to use

Open **Volatility research workbench** in the F&O area, upload a captured JSON
bundle, click Analyze, then download the report. Input is capped at 5 MB,
12 expiries, 300 contracts per expiry and 12 scenarios. Calculations only run on
button press, never inside scan workers. No credentials belong in these files.
Invalid payload errors are sanitized. Raw uploads are not persisted by this code.

Bundle schema (all numeric IVs are decimals):

```text
schema_version: 1
underlying, source, snapshot_id, convention_version: nonempty strings
as_of: timezone-aware timestamp; valuation/capture cut, not current wall clock
max_age_seconds, max_skew_seconds: explicit positive alignment policy
provider_conventions: exactly
  {model: BSM_SPOT, iv: DECIMAL, theta: CALENDAR_DAY, vega: VOL_POINT,
   quantity: PER_UNIT, day_count: ACT365F}
  Omit/unknown -> provider consistency NOT_COMPARABLE, not a unit guess.
tolerances: {delta: [absolute, relative], gamma: [...], theta: [...], vega: [...]}
  Explicit research comparison policy, not empirically certified tolerances.
slices: list of:
  expiry_at: actual timezone-aware contract expiry
  exercise: EUROPEAN
  spot, rate, dividend_yield: explicit numbers (rates decimal)
  reference_at: timestamp of underlying/carry valuation reference
  carry_source, adjustment_version: nonempty lineage strings
  contracts: list of:
    instrument_key, contract_version: nonempty lineage strings
    strike: positive number
    kind: CE or PE
    source_at, available_at: timezone-aware timestamps
    bid, ask, bid_size, ask_size: positive numbers; bid <= ask
    provider: {iv, delta, gamma, theta, vega} (optional -> NOT_COMPARABLE)
scenarios: optional list of:
  {spot_return, iv_change_points, elapsed_days, signed_units}
history: optional:
  target_days: positive constant maturity in calendar days
  capture_context: stable intraday capture definition, e.g. reviewed closing cut
  sessions: last 252 completed trading dates, sorted unique YYYY-MM-DD
  rows: [{series_key, session_date, observed_at, available_at, iv}]
realized: optional:
  adjustment_version: consistent adjusted underlying price lineage
  annual_sessions: explicit annualization convention (commonly 252)
  sessions: consecutive completed trading dates for the desired trailing window
  rows: [{session_date, available_at, adjustment_version, close}]
```

The generated historical `series_key` joins, using `|`:
engine version, underlying, source, convention_version, capture_context,
target_days formatted as a float (e.g. `30.0`), `FORWARD_ATM`.
Persist that exact key with future constant-tenor observations. Do not reuse a
key after changing the source/conventions/capture definition. Today and future-
available observations are excluded from the historical baseline. Duplicates
are rejected, not averaged. Availability timestamps must represent when the
information was genuinely available; this engine cannot verify imported claims.

Synthetic end-to-end fixtures live in `tests/test_volatility_research.py`; they
must never be recorded as market observations. The workbench is intentionally
not populated with synthetic "live" graphs.

## Historical data and storage constraints

Upstox's expired-contract endpoint documents OHLC, volume and OI, with a Plus
subscription requirement. It does not supply the contemporaneous bid/ask book,
Greek calculation timestamp, dividend curve or complete chain from each past
instant. Candle closes can support separately labelled approximate studies, not
reconstruction of executable historical surfaces. Check actual account access,
coverage, exchange licensing and redistribution rights before purchasing or
collecting. Never manufacture historical spreads/Greeks to fill the gap.

Source: https://upstox.com/developer/api-documentation/get-expired-historical-candle-data/

This implementation adds ZERO rows to Supabase. At the reported 83% of 500 MB,
only roughly 85 MB remains; full-chain JSONB accumulation is inappropriate.
Recommended next collection deployment: a small underlying universe, fixed
capture times, compressed date-partitioned Parquet in the existing verified
Drive archive, with deduplication, contract/carry lineage and checksums. Retain
only compact inventory/health records in hot storage if needed. Do not trust
Streamlit local disk as the sole archive. This change does not add a scheduled
collector or a Drive upload/delete path; those require a reviewed source adapter.

Illustrative sizing, NOT a measured compression claim: 5 underlyings * 3
expiries * 80 contracts * 4 captures = 4,800 rows/day. At 200-500 compressed
bytes/row this is 0.96-2.4 MB/day before metadata. Measure representative files
first, then apply a byte budget and capture limits. Do not store every rerun.

Source: https://supabase.com/docs/guides/platform/database-size

## Validation/promotion plan

Without long history we can test numerical derivatives, parity, convexity,
solver failures, input lineage, no-lookahead, fit recovery and isolation. These
tests establish implementation behavior, NOT market accuracy or profitability.
Recorded live observations are needed for model-error distributions, surface
stability, actual spreads, missing-data patterns and expiry behavior. Event
forecasts need repeated comparable events and out-of-sample evidence; 252 days
alone is not proof. IV history cannot exist before genuine collection/backfill.

Promotion requires a separate reviewed code change: declared prediction target,
coverage and error limits, walk-forward evaluation with point-in-time data,
cost/turnover evidence where applicable, explicit approved artifact version,
and a fail-closed consumer. No UI checkbox/environment switch promotes this
engine. Current candidate selection never reads its output. Static integration
tests guard that boundary and retention of existing rejection checks.

Raw SVI reference: https://arxiv.org/abs/1204.0646

## Official deltas in this app

The app has no automatic official contract-delta file ingestion. Existing
`derivative_restrictions._exit_check` requires complete position evidence marked
CLEARING_CORPORATION, date/validity and per-contract cc_deltas. Missing data fails
closed for the affected exit review. This engine must never populate cc_deltas.
Ordinary eligibility is NOT a claim that all regulatory position limits have
been independently validated by this app. Missing official data does not make
the portfolio empty or disable settlement/exit monitoring; use broker-assisted
position review when the automated exposure check cannot be established.

Official contract deltas are distributed through clearing-member channels/FTP
and SPAN data with prescribed dates/batches. Confirm access through the broker;
a retail market-data token is not evidence of access. Maintain the official
daily ban-entry restriction independently. Do not substitute Upstox delta or
local BSM delta or infer a contract delta from aggregate public OI.

Sources:
https://nsearchives.nseindia.com/content/circulars/CMPT68790.pdf
https://www.nseclearing.in/sites/default/files/2026-01/Recent_changes_in_Equity_Derivative_segment_focusing_on_position_limits%2C_Limit_Monitoring%2C_and_Securities_in_Ban_Period.pdf
