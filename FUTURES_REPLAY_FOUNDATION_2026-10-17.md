# Quote-faithful futures PAPER foundation

`quote_faithful_futures_replay.py` is a pure typed standard-library API for one
contract and one predeclared directional round trip. No IO, fitting, options,
Greeks, portfolio allocation, contract roll selector or live/capture integration.
Its inputs and synthetic tests are not licensed real data or authenticated fills.

Supply frozen plan/input hash, same-day session bounds, known/effective/expiry
contract metadata, tick, lot units, currency, point value, explicit dated costs
and versioned two-sided quotes. Amounts/rates are bounded decimal strings; there
are no guessed prices, default fee schedules, float coercion or statutory-cost
claims. Rate fees apply to adverse paper notional; fixed fees apply per leg.
Prices must be on tick, depth is displayed units (not lots), and expiry-day entry
is forbidden. Costs and contract metadata must be known by the entry decision.

Entry and exit times are predeclared in the frozen plan, not retrospectively
chosen from outcomes. At each decision plus explicit latency, only quotes whose
event time AND availability meet the threshold qualify. The earliest availability
is selected, not the best hindsight price. The first qualifying stale, missing or
shallow quote withholds the pair; it is not skipped for a favorable later quote.
Same-time arrivals are ambiguous and rejected. Quote revisions retain the same
event timestamp, increasing version and strictly increasing availability. Later
revisions do not overwrite an earlier selected version; both remain hash-bound.

Buy uses ask, sell uses bid, with explicit adverse tick stress per side; spread
is already included in those touches and is not deducted twice. Fees are charged
on each side's stressed notional. Gross/net reference amounts use exact decimal
arithmetic with supplied lot units and point value, independent of ambient Decimal
precision. These deterministic accounting amounts are NOT measured executable PnL.
Displayed depth is not a queue/impact guarantee; stress prices are assumptions,
not quotes claiming liquidity at an unobserved deeper price level.

The engine preflights BOTH legs before committing any PAPER fills. If exit quote,
depth or timing is unsupported, the result has no committed legs and no gross/net
amount. `paper_flat=true` then means the initial paper state stayed flat, NOT that
an actually filled position was magically closed. A supported pair ends paper-flat
by the supplied intraday close. This atomic reference calculation does not model
real after-entry exit failure, liquidation, partial fills or position recovery;
never use it as a live execution/recovery policy. Missing exits cannot be priced
from close/last/mid or carried overnight.
This API has no complete-cohort denominator or aggregate performance estimator.
Retain and count every rejected/withheld planned trial. Reporting only supported
pairs would create selection bias; no Sharpe, win rate or expected return may be
derived from a success-only subset. The complete frozen-cohort adapter is next.

The API follows the availability/frozen-prefix philosophy of
`research_dataset_boundary.py` and the conservative no-carry/no-expiry-entry
principles of `nifty_futures_research_contract.py`, but imports neither. It does
not reinterpret reference-direction labels as PnL or replace the older contract's
next-bar-open research method. An adapter would need separately reviewed source,
prefix, licence, study, calendar, contract selection and cost verification. A
supplied input hash alone does not prove consumed-prefix completeness or freezing.

Manifest bytes bind the plan, costs, metadata, full supplied quote/version stream,
selected quote hashes, withholding reason and accounting output. Hashes are not
signatures or independent custody. Bounds: 4,096 quotes, 8 MiB manifest, 10,000
lots, 100,000 units per lot, explicit latency/staleness at most 60,000 ms, and
at most 100 adverse ticks per side. Monetary inputs have at most eight decimal
places and magnitude 1e12; rates cannot exceed one. These are resource limits,
not evidence of realistic latency, statistical adequacy or suitable costs.

Every output keeps training eligibility, promotion, approval authority, real fill
evidence and executable-PnL verification false. Provenance is explicitly SYNTHETIC
or CALLER_UNAUTHENTICATED, never REAL by assertion. No existing gates are changed.
Tests use generated 2022 toy quotes/metadata only, never market records/returns.
