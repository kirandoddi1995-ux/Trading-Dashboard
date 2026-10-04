# Intraday F&O research costs and margins

This release does not lift the option-entry hold, send orders, or produce
execution evidence. Directional replay remains cost-free underlying research,
not option P&L. The new calculator covers same-day NSE long option and long
or short futures price scenarios. Short options, expiry exercise, physical settlement,
BSE/MCX and overnight positions are not covered. Margin is NOT a loss cap.

## Commissioning

Do not configure guessed rates. `intraday_fo_costs.round_trip` requires a policy
with `exchange: "NSE"`, `reviewed: true`, `effective_from` and `effective_to`
(ISO dates), `reviewed_at` (aware ISO timestamp available before entry),
`rounding: "PER_SIDE_PAISE_HALF_UP"`, and
`gst_components: ["brokerage", "exchange", "ipft", "sebi"]`.
Check that rounding and GST basis match your applicable broker contract note.
The engine uses Decimal; pass prices/rates as decimal strings, not floats.

`rates` must have `OPTION` / `FUTURE` dictionaries containing:
`brokerage_cap`, `brokerage_rate`, `stt_sell`, `stamp_buy`, `exchange`, `ipft`,
`sebi`, `gst`. All are absolute fractional rates, except brokerage cap in rupees.
For example 0.15% is "0.0015", not "0.15". Options use the per-executed-order
cap; futures use min(cap, turnover * rate). Distinct executed option orders
must be counted; partial fills within one order are not separate orders.
Unequal capped futures orders are rejected: calculate each executed order
separately instead of averaging turnover. Do not double-count exchange + IPFT.

`sources` must map EACH rate name above to its reviewed official HTTPS source.
URL presence is provenance metadata, not proof of authenticity: review the
actual dated circular and your account plan. No tariff is enabled automatically.

Verified source references for review (not historical defaults):

- NSE circular NSE/FA/73061, 27 February 2026, effective 1 March 2026:
  https://nsearchives.nseindia.com/content/circulars/FA73061.pdf
  Futures exchange 182.99 + IPFT 0.01 rupees/crore; option premium exchange
  3552.99 + IPFT 0.01 rupees/crore. Divide by 10,000,000 to obtain rates.
- Broker charges: https://upstox.com/brokerage-charges/
  Review the dated STT table, brokerage plan, stamp, SEBI and GST rules.
  The page contains different historical periods: never apply current charges
  to 2022–2025 replay. Account plan must be confirmed, not inferred.
- Broker margin contract: https://upstox.com/developer/api-documentation/margin/
  `data.required_margin` is funding before benefits; `data.final_margin` is
  post-benefit collateral; `data.margins` contains per-leg components.
  No locally guessed SPAN/exposure leverage is used.

For app scenario calculation, optionally configure `INTRADAY_FO_COST_POLICY_JSON`
as a JSON string containing `policy` above, `exit_deadline` (aware timestamp for
THIS trading date), and `deadline_source` (reviewed broker instruction).
This is deliberately not an undated universal 15:20 default. Include your
chosen buffer before the actual broker deadline. Missing/expired policy blocks
option and futures proposals; it does not fall back to the previous 0.7% or
generic futures fee allowance. Futures retain separately labelled heuristic
spread/slippage/impact estimates, not measured execution evidence.
Planned exit by deadline is a scenario, not an exit guarantee. Signal reversal
execution, slippage, failed exits and automatic square-off fees still require
recorded fills and monitoring. Unplanned broker charges are outside this model.

The option card takes the larger stop/target one-lot fee scenario, then scales
that conservative allowance per lot. It can overstate brokerage for multiple
lots in one order. It is not an exact multi-order contract-note reconciliation.
Existing stop/risk sizing is NOT converted into proof that full premium loss
fits the account risk budget. Entry hold must remain until that separate sizing
and actual basket margin commissioning is reviewed.

`fresh_margin` requires aware request time, maximum 30-second age, and identical
retained request basket. It does not make a second price source or backtest
margin history. The existing scalar app helper returns required funds and has
a 30-second cache; it is not a complete basket approval gate. Missing evidence
returns unavailable, never zero or final margin as available funds.

## Signal and collector changes

Daily equity setup indicators/probabilities use prior-date completed daily
bars, even after the same day's close (clock alone is not EOD finality).
Live executable entry prices remain separate. F&O bias uses completed 5-minute
bars and completed 15-minute/hour trend bars; no daily win probability applies.
Index volume does not supply confirmation. Volume pacing remains an explicitly
uniform-time heuristic, not a validated opening/midday U-curve; stale/unknown
source dates are not time-adjusted.

Collector `summary` describes latest stored snapshots, including unchanged
ones, and splits horizon/coverage and unknown touch status. It changes no
research labels, bars, outcome eligibility or governance evidence.

## Local verification

`.venv\Scripts\python.exe -m pytest -q tests/test_intraday_directional_replay.py tests/test_signal_data_boundaries.py tests/test_intraday_fo_costs.py`

Use only development data for replay; keep 2025/2026 unscored. Optimization
precomputes causal indicators; exact-prefix regression covers output equality.
An already-running process retains its old code until restarted.
