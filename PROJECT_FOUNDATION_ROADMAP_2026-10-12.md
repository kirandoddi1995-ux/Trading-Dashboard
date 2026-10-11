# From reliable evidence to useful intraday decisions

Research and decisions as of 12 October 2026. This is a review-only engineering
roadmap, not trading or legal advice. No hosted settings, trading rules or
commissioning gates were changed. Installed capture and sealed 2025/2026 research
data were not accessed.

## Plain-language conclusion

The finished product should explain whether a specific intraday NIFTY idea has
credible evidence, can afford its real costs and risk, and is still timely. It
should often say **no trade**. It should never imply that a directional move,
an option candle, a simulated fill, or a green infrastructure check proves profit.
It never places orders.

Use one adequately funded hot Postgres database and verified private cold files,
not a second free database to postpone the same problem. Finish recovery before
deletion. Then move toward a small frozen research round and forward paper
evidence, rather than endlessly expanding the equity scanner.

Recommended chain:

**Credential safety → authenticated recovery → all-writer protection → bounded
hot/cold storage → data and execution contracts → frozen development research →
forward paper evidence → cautious decision support → later ML.**

Operational monitoring, regulatory review and backup drills run alongside this
chain. No missing link can be replaced by a reassuring dashboard label.

## What was built in this package

1. An inactive, separate operational journal: operation and original signed
   receipt commit together; expired ownership changes by compare-and-swap;
   delayed old writers fail after acquiring the lease lock. Nine disposable
   native cases supplement the existing six capacity and eight archive cases.
2. A signed backup binding that connects the five-table witness, sixth-table
   intent witness, full image and cut identity under one existing signed root.
   It rejects mixing otherwise valid artifacts from different cuts.

These are foundation components, not live wiring or verified independent custody.
The new journal does not write the existing equity operational tables. The
database checks receipt binding, not its HMAC; authenticity uses the existing
application verifier and privately held historical keys. Privileged owners can
alter infrastructure, so externally retained anchors remain necessary. A lost
COMMIT reply is tested by fault injection, not claimed as a real network-chaos test.

## Priorities and acceptance gates

| Order | Deliverable and dependency | What must prove it works |
|---|---|---|
| P0, owner first | Rotate exposed runtime password; secure historical signing keys. Keep collector/release changes separate. | Inventory every consumer by role and secret name; coordinated pause/update; one restricted login and supervised scan; old credential rejected without logging it. Never rotate ledger keys merely to rotate the DB password. |
| P1, this package | Original receipt/fence transaction tests and joint six-table/image binding. | Exact-main PR checks, then the disposable workflow: 6 + 8 + 9 cases. Whole-chain commissioning flags stay false. |
| P2 | Consistent export, authenticated independent custody, full-image and six-table restore. Depends on owner key note and encrypted external-disk rehearsal. | One measured cut; signed joint binding; separate encrypted replica and independently retained checkpoint; restore in an isolated directory; exact schema, rows, intents, original receipts and ledger roots. Rehearse missing key/object, mixed cut, stale anchor and corrupted replica. No deletion authority from matching counts alone. |
| P3 | Guarded writer and cold-aware recovery wiring, one factory family at a time. Depends on P1/P2. | Enumerate app, collector, research, archive, purge and maintenance writers; direct SQL/grants cannot bypass admission; concurrent guard/seal/delete/fence tests; exact cold lookup; uncertain delivery remains uncertain. Test restart with old local outbox/checkpoints, unknown COMMIT, missing cold object and unavailable historical key. |
| P4 | Universe shadow normalization and source-specific bounded retention. Depends on cold-reader parity and restore. | Exact bytes/content hashes and snapshot identity retained; dual-read parity before switching; archive dependency closure, authenticated publication and independently recoverable copy before removing hot rows. Peak quota and physical disk measured, not inferred from row text sizes. |
| P5 | Independently delivered capacity alerts and one daily health view. Can be built beside P2–P4. | Missing scheduled receipts trigger an alert even if PC/app is asleep; test missed, stale and failed delivery. Show local recording separately from Drive verification; calendar-aware expected slots; measured times and unknown states. No health check grants trading approval. |
| P6 | Dated instrument, data-quality, cost, margin and risk contracts. | Official effective dates, contract-specific lots/expiry and account-specific product; next-bar/quote execution without look-ahead; frozen fee/slippage assumptions; synthetic and development-only failure tests. Missing quotes/margins prevent executable scoring. |
| P7 | Small pre-registered development research round, then forward paper tracking. | 2022–2024 only; no retuning parked rules; immutable experiment/data/code hashes; session-clustered uncertainty, costs, drawdowns, MAE/MFE, exits and rejected opportunities. Explicit multiplicity control and internal development hold-back fixed before results. |
| P8 | Validated decision support, then optional ML. | Validation/holdout opened only by separate owner approval after freezing a candidate. Forward evidence distinguishes simulated from actual fills. Drift alerts do not retrain or promote models. No edge is an acceptable final result. |

### Permanent storage design

Hot storage holds recent operational state, active leases, ledger heads/roots and
bounded recent evidence. Cold storage holds immutable, content-addressed objects,
exact lookup catalogs, signed checkpoints and licensed research history. A hash
pointer is useful only if its object is retrievable and authenticated. Drive
failure must not cause deletion, false acknowledgement or guessed absence.

Do not blindly partition every existing table. A partitioned unique key must
include partition keys; ledger identity and chained roots make a drop-in dated
partition migration unsafe. Use ledger segments with retained heads/anchors;
consider date partitions first for independent append-only quotes/volumes after
all readers support exact cold lookup. Universe normalization needs shared
immutable payloads plus complete snapshot membership and reference-aware
retention, not deletion of repeated rows that still carry distinct history.
[Postgres partitioning](https://www.postgresql.org/docs/17/ddl-partitioning.html).

Set source budgets, archive deadlines and maximum hot ages from measured demand
and licence terms. Do not invent a universal retention duration tonight. Keep
original evidence, provenance, archive receipts and dependency catalogs together;
bound ledger receipts only after their historical verification path works. Normal
VACUUM makes space reusable; table rewrites require locks and additional peak
space. Reclamation is a separately reviewed maintenance action, not the design.
[Postgres vacuum guidance](https://www.postgresql.org/docs/17/routine-vacuuming.html).

Recommend Pro if its recurring cost is acceptable: the official starting price is
$25/month, with 8 GB included database disk and seven-day daily backups; extra
projects/compute and optional services can add costs. This buys engineering
runway, not correctness. Keep the existing conservative capacity policy until a
separate reviewed policy update; no automatic limit increase. At the owner's
approximate 394 MB, two 0.75 MB scans/day leave roughly 55 trading days above the
24 MB admission reserve, assuming no other growth. This is a planning estimate,
not a fresh measurement or guarantee.
[Pricing](https://supabase.com/pricing),
[database quota](https://supabase.com/docs/guides/platform/database-size).

Full Supabase recovery must include grants/RLS/functions/extensions, jobs and
configuration as well as table rows. Supabase backups do not contain Storage API
object bytes or custom role passwords. Separately inventory private credentials,
Drive objects, keys, anchors and local recovery state. Restore into a disposable
non-production database, with dispatchers and order paths absent, and run actual
restricted-reader/writer and app-boot checks before declaring the drill passed.
[Backup scope](https://supabase.com/docs/guides/platform/backups).

## Intraday F&O: decisions before new hypotheses

Start with NIFTY, not single-stock derivatives. Keep futures and long-option
research distinct; defer naked short options and multi-leg strategies until
margin, assignment/settlement and partial-leg risk are explicitly supported.
Index direction is not futures P&L; futures basis and spreads matter. Option
direction is not premium P&L; volatility, decay, spread and liquidity matter.
Five-minute underlying candles and four option snapshots cannot establish
executable five-minute option returns.

The dated instrument master must bind instrument key, lot, expiry, session,
source hash and availability time. NSE's lot circular changes NIFTY from 75 to 65
with transitional contract rules; a single calendar-date lot switch is wrong.
Current contract specifications use Tuesday expiry with holiday adjustment,
which must not be projected backward into old data.
[Lot circular](https://nsearchives.nseindia.com/content/circulars/FAOP70616.pdf),
[contract specifications](https://www.nseindia.com/static/products-services/equity-derivatives-contract-specifications).

Fees need dated STT, exchange, SEBI, stamp, GST and the actual brokerage plan.
Current NSE tables confirm April 2026 STT changes; they do not establish older
cost schedules. Upstox Plus terms list different F&O brokerage from the working
₹20 assumption. Verify the owner's actual plan against a contract note before
commissioning net-return calculations.
[NSE STT](https://www.nseindia.com/static/products-services/equity-derivatives-securities-transaction-tax),
[Plus terms](https://upstox.com/files/terms-and-condition/plus-pack.pdf).

Risk sizing should separate one-lot research feasibility from account approval.
For live suggestions require integer lots, verified capital/product/margin,
adverse-fill costs, maximum per-trade loss and aggregate daily exposure/loss
limits. A stop is not a guaranteed maximum loss in a gap or failed exit. Long
premium at risk and margin required are different concepts; do not treat intraday
margin as free leverage. Expiry-day short-index options have additional margin
requirements.
[Client margins](https://www.nseclearing.in/risk-management/equity-derivatives/client-margin-reporting),
[expiry-day ELM](https://nsearchives.nseindia.com/content/circulars/CMPT64639.pdf).

Upstox announced F&O square-off at 15:25 from 11 September 2026, while a
strategy-builder help page still says 15:20. Obtain current product-specific
instructions. Proposed first research cutoff: 15:10 IST, not activated here;
freeze it before testing. It is a buffer, not a guarantee. If timely exit evidence
is missing, record UNKNOWN, not an invented end-of-day fill.
The first executable research contract should admit verified regular sessions
only. Special sessions need their own dated hours and exit policy, not a fixed
15:10 deadline projected onto Muhurat or other shortened trading.
[Dated announcement](https://upstox.com/announcements/revised-timings/),
[strategy-builder help](https://upstox.com/help-center/how-to-place-an-option-strategy-using-strategy-builder-252634/).

The official expired-candle endpoint documents five-minute data and expired
instrument access requires Plus. Confirm entitlement and a known development
session before bulk requests. Contract rolls must preserve actual contract
identity and avoid manufacturing tradable continuous prices. The Analytics Token
is one-year and read-only: daily login is not inherently necessary for supported
market-data GET calls. Account-data access has separate static-IP requirements;
do not assume a GET-only token supports a POST margin endpoint.
[Expired candles](https://upstox.com/developer/api-documentation/get-expired-historical-candle-data/),
[Plus requirement](https://upstox.com/developer/api-documentation/announcements/expired-instruments-api/),
[Analytics Token](https://upstox.com/developer/api-documentation/analytics-token/).

## Data, paper evidence and model governance

Retain exchange and arrival timestamps, sequence/gap indicators and source hashes.
Validate duplicate/conflicting bars, OHLC ranges, bad/crossed quotes, missing depth,
staleness/skew, special sessions and corrections. Separate index volume from
futures/equity proxies. Reconcile official files without treating a browser-downloaded,
owner-attested file as independently authenticated. Corporate actions chiefly
matter for retained equity/stock-derivative history, with as-of adjustment rules;
do not silently rewrite raw history or apply them to NIFTY index returns.

Paper tracking needs immutable signal and decision time, candidate/code/data
identity, reason, contract, sizing feasibility, bid/ask-derived executable price
when available, fees and exit evidence. Keep rejected signals and missed fills.
Separate SIGNAL_ONLY, SIMULATED_EXECUTION and owner-reported actual execution.
No fills from quotes before the signal, no optimistic intrabar target/stop order,
and no synthetic liquidity. Report missing coverage alongside horizon completion.

Comparable systems support the same separation: QuantConnect documents distinct
fill and slippage models and live/backtest discrepancies; NautilusTrader uses
shared backtest/live components. Borrow parity contracts, not their order-routing
features. Prefix-invariance tests should ensure future bars cannot change an
earlier decision; Freqtrade's look-ahead analysis illustrates this failure class,
but passing such a tool alone is not proof for untriggered paths.
[Fill models](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/trade-fills/key-concepts),
[reconciliation](https://www.quantconnect.com/docs/v2/writing-algorithms/live-trading/reconciliation),
[shared engine](https://nautilustrader.io/docs/latest/concepts/backtesting/),
[look-ahead checks](https://www.freqtrade.io/en/stable/lookahead-analysis/).

Use the existing hash-frozen research registry first, not a new hosted ML platform.
Track hypotheses, rejected trials, code/dependencies, split boundaries, source
licences, features, label horizons and artifacts. Later ML needs purged/embargoed
time splits for overlapping labels, fit-on-training-only transforms, calibration,
cost-aware decisions and drift on both input quality and outcomes. Drift triggers
review or blocking, never automatic retuning/promotion. MLflow's experiment
tracking is a useful model for metadata, not a reason to add another database now.
[Experiment tracking](https://www.mlflow.org/docs/latest/tracking/).

SEBI's August 2026 study reports 87.7% of individual F&O traders lost money in
FY26. This supports a high evidence/cost bar; it does not prove that any particular
strategy, instrument or ML approach succeeds or fails. Public market studies are
not access to this project's sealed research holdout.
[SEBI study](https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1787233506209.pdf).

## Regulation and data rights — professional confirmation required

No order-placement path is a firm product boundary, not a blanket exemption from
advice regulation. Personal use by Kiran, distribution to other users, personalized
capital/risk recommendations, subscriptions and indirect compensation can change
the analysis. The February 2026 RA and IA master circulars address research/advice,
records, suitability and responsibility when using AI. Ask an Indian securities
professional which obligations apply to the actual users and business model.
[RA master circular](https://www.sebi.gov.in/sebi_data/attachdocs/feb-2026/1770375507051.pdf),
[IA master circular](https://www.sebi.gov.in/sebi_data/attachdocs/feb-2026/1770375291405.pdf).

Retail automated order rules are a separate question. SEBI's February 2025 framework
and September 2025 extension bring all brokers under the framework from April
2026. NSE's FAQ states that client API orders are tagged as algo orders even below
the registration-rate threshold; below ten orders/second is not a blanket
exemption. Static-IP, broker responsibility and black-box-provider requirements
must be reviewed before any future execution feature. This project adds none.
Consultations are proposals, not enacted rules. Recheck amendments before launch.
[Framework](https://www.sebi.gov.in/sebi_data/attachdocs/feb-2025/1738665456458.pdf),
[extension](https://www.sebi.gov.in/sebi_data/attachdocs/sep-2025/1759232056254.pdf),
[NSE FAQ](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/FAQ_Retail%20Algo_03112025_NSE.pdf).

Private encrypted storage does not itself grant market-data retention,
redistribution, derived-data or ML rights. Obtain written broker/exchange licence
scope, permitted retention and backup terms. Never put raw market data, account
information or credentials in this public repo or public workflow artifacts.
[NSE policy](https://www.nseindia.com/static/market-data/nse-data-policy),
[non-display policy](https://nsearchives.nseindia.com/s3fs-public/inline-files/Non_Display.pdf).

## Owner decisions and blockers

- Complete the pending encrypted key note, historical-version inventory and
  external-disk restore rehearsal. Report presence/proof statuses, never values.
- Approve a recurring database budget if affordable; Pro is recommended, not
  purchased or enabled. Otherwise keep scan-only admission and structural work
  ahead of new writers. No promise of runway from an old dashboard reading.
- Rotate the exposed runtime password through a coordinated consumer cutover;
  credentials and key custody are security prerequisites, not optional polish.
- Confirm Plus entitlement, actual brokerage/product and licence rights; resolve
  square-off instructions. No account probes were made tonight.
- Protect main through required PR checks. Use actual successful check contexts
  from a recent PR, including CodeQL language jobs, not an assumed aggregate name.
  Require current branch, resolved conversations, disallow force/deletion and
  apply to administrators where supported. A sole owner cannot self-approve, so
  do not blindly require another approver. A manual disposable workflow is not a
  required every-PR check until its triggering policy supports that. Preserve the
  release promoter's reviewed permissions and existing hold.
  [Branch protection](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches),
  [required checks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks).
- Choose an independent alert destination/account and retention terms only at
  commissioning. A daily view without independent missed-run delivery is not
  unattended reliability.

The next code package should be the consistent exporter/restore verifier joined
to this six-table binding, then factory integration—not broad new trading signals.
Owner custody delays do not justify starting hot deletion or claiming recovery.
