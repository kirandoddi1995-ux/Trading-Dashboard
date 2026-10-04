# Next intraday research round: economics before further strategy search

## Decision

Retain C_single_bar_no_volume and C_persistent_no_volume as failed development
benchmarks; do not advance either to 2025 validation now. Their existing spot
reference evidence does not demonstrate a tradable edge. This is not proof that
their true expectations, or all related strategies, can never be profitable.

The immediate new tool is an offline cost-hurdle screen, not another strategy
optimizer. It leaves episodes and production code unchanged and rejects
2025/2026 sessions and episodes, including excluded sessions. Nothing is stored
in Supabase.

## Run against the existing development report

From the project root in PowerShell:

```powershell
.venv\Scripts\python.exe development_cost_hurdles.py --report "C:\Users\banga\Documents\TradingResearch\nifty-development-2022-2024.json"
```

Keep research input/output private; do not upload them to GitHub. Verify:

- source_report_sha256 matches the report actually screened;
- accepted_sessions 737 and episodes 1089 / 1027 for this existing report;
- mode SPOT_REFERENCE_COST_SENSITIVITY, approval_authority false,
  futures_pnl/option_pnl null, cost_policy_commissioned false;
- original means/intervals remain unchanged; each sensitivity subtracts only
  the specified percentage-point hurdle (0, 0.02, 0.04, 0.05, 0.06, 0.08);
- missing evidence remains null, not zero.

These scenarios are NOT historical charges, futures execution returns, or
trade-level rupee P&L. Subtracting a constant shifts the interval exactly but
does not improve its statistical validity. Intervals preserve sessions, not
serial dependence across days, and have no strategy-search correction.

## Commission actual costs next

NSE/FATAX/73524, 31 March 2026, confirms rates effective 1 April 2026:
futures sale 0.05% of sell turnover, option sale 0.15% of premium, and exercised
options 0.15% (purchaser; intrinsic-value basis). These are different bases;
an option-premium percentage cannot be compared to a spot-index return.

Source: https://nsearchives.nseindia.com/content/circulars/FATAX73524.pdf

The 0.05 hurdle resembles the current futures sell STT but is still only a
constant entry-notional proxy: actual short/long sell turnover can differ.
The 0.06 all-in estimate is NOT verified or enabled by this release.
Do not apply 2026 tariffs to 2022-2024 as if they were historical expenses.
The same circular identifies earlier NSE/FATAX/56235 (1 April 2023) and
NSE/FATAX/63809 (9 September 2024). The latter confirms futures sell STT
0.0125% through 30 September 2024 and 0.02% from 1 October 2024, and options
sell STT 0.0625% to 0.10% on the same date:
https://nsearchives.nseindia.com/content/circulars/FATAX63809.pdf
NSE/FATAX/56235 confirms futures sell STT 0.01% through 31 March 2023 and
0.0125% from 1 April 2023, and option sale 0.05% to 0.0625% on that date:
https://archives.nseindia.com/content/circulars/FATAX56235.pdf
These STT references do not commission the complete historical fee schedule:
the other dated charges and account-specific brokerage still need review.
No historical tariff is automatically applied here.

Commission intraday_fo_costs.py using official dated exchange/IPFT, STT, SEBI,
stamp and GST sources, Kiran's actual brokerage plan, rounding conventions,
and a contract-note reconciliation. Separately retain spread/slippage and
execution uncertainty; taxes alone are not all-in costs. Verify broker product,
current square-off deadline, failed-exit handling and actual basket margin.
Margin is funding, not loss containment or a guaranteed exit.

## Bounded subsequent hypotheses (not implemented or selected yet)

After that commissioning, freeze at most TWO new economic hypotheses:

1. Persistent trend continuation with one entry per session, no reversal
   re-entry: test whether reducing churn improves the cost hurdle.
2. Completed 30-minute opening-range breakout with completed-bar trend
   agreement and one entry per session: test sustained range expansion.

Fewer trades are not intrinsically better; larger moves must be predicted
causally, never selected using future MFE. Do not implement a threshold sweep.
Before running these, register exact entry/exit times, bar confirmation,
warmup, neutral-state handling, missed signals, contract selection, stop
semantics, gap execution, fee schedules, slippage scenarios and an unambiguous
primary outcome. Registry must include every tried rule, including failures;
hash policy/code/data before scoring, not after choosing a winner.

All 2022-2024 has already been examined. Any new split or walk-forward inside
it is exploratory, NOT a pristine internal hold-back. Use chronological
walk-forward stability checks, yearly dispersion, exposure, tail loss and
session-end dependence; include zero-trade sessions. Predeclare uncertainty
assessment that accounts for session clustering and consecutive-day dependence.
For eventual two-candidate testing, register a family-wise multiplicity method
and one primary cost scenario before validation; sensitivity cases cannot be
searched for a favourable result. Bootstrap interval shifting alone is not
multiple-testing control. Do not repeatedly query 2025 to tune rules.

2025 remains frozen until the full research protocol and cost/data checks
justify a single authorized validation round. 2026 remains the final holdout.
"No tradable edge found" is an acceptable terminal research result.

## Futures research data contract

NIFTY spot is useful for inexpensive direction screening, not executable
futures returns. Before a futures P&L claim, retain dated contract keys,
expiry, authoritative lot/tick sizes, rollover selection with no hindsight,
aligned futures prices/quotes and explicit execution assumptions. Candle-only
futures results must remain hypothetical (no reconstructed bid/ask fills).
Do not stitch expiries without modelling basis/roll transitions, or use the
same-contract thin next-month volume as an automatically valid near-month
baseline. No fabricated margin history or fill probabilities. Option P&L
waits for sufficient recorded executable quotes and validated conventions.

## Tests

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_development_cost_hurdles.py tests/test_directional_replay_diagnostics.py tests/test_intraday_fo_costs.py --basetemp "$env:TEMP\cost-hurdles-review-$([guid]::NewGuid().ToString('N'))"
```

This release does not commission tariffs, alter approval rules, lift the
option-entry hold, start collection, or change the equity release fingerprint.
