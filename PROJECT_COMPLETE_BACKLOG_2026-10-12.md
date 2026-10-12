# Complete-program backlog — zero-cost, evidence-first

This register merges the 91 public project notes reviewed in full during the
unattended run. It is a requirements register, not a claim that implementation or
commissioning is complete. The local intake JSON records original source hashes
and coverage; it is not a deployment manifest. Old notes remain historical evidence.
Owner reports native 6 capacity, 8 ledger/archive and 9 operational cases passing;
no hosted state was checked in this run. Reported 394 MB and 0.75 MB/scan are not
fresh measurements. All new work stays inactive; release/capture/holdout unchanged.

## Decisions that supersede older plans

- Zero paid services: no Pro, paid PITR, paid VPS, new subscription or purchased
  independent feed prerequisite. Keep one bounded hot database with licensed
  private cold objects and the existing external disk once encryption and replica
  proofs pass. A second
  Free database is not an assumed quota escape or a free operational simplification.
- Never count estimated compression, deleted rows, ordinary vacuum or future
  savings as present quota headroom. Include transition copies, metadata, indexes,
  TOAST, concurrent writers and failed allocation. WAL/disk is a separate limit.
- Disconnected disk means replica delay, not automatic backup. Unreplicated objects
  stay protected and count against capacity. Finite free capacity cannot promise
  unlimited history, uninterrupted optional ingestion or unlimited backup delay.
- The two directional rules stay parked. Every part of 2022–2024 has been examined;
  a new internal split is exploratory, not pristine holdout. 2025/2026 stay sealed.
- Daily equity probabilities are not F&O evidence. Bars, paper references and
  actual executable quotes are distinct. Unknown outcomes stay unknown.
- Owner-only steps are prepared, never executed by this run. Missing evidence
  cannot become a PASS because a fixture, signature or caller flag exists.

## Priority and acceptance register

Plain-language delivery chain:

Recoverable authenticated copies → all readers and writers use those protections
→ archive and reclaim each source without breaking its dependencies → prove bounded
database growth and independent failure alerts → verify intraday data/calendar/cost
contracts → forward paper evidence → frozen research → ML only if evidence warrants it.

Do not deploy structural deletion ahead of recoverability to gain apparent speed.
Work on independent offline contracts in parallel, but commission in that order.
The next coherent engineering package is S02/S04: turn tested exported identities
into an explicit recovery/replica adapter and enumerate every live writer factory.
Its acceptance must include unknown COMMIT, original-key absence, broken cold links,
checkpoint rollback, stale fencing and no hot-only fallback. Owner key/custody
evidence stays a gate, not a Boolean input that a fixture can satisfy.

IDs remain stable as implementation continues. Component tests are not whole-chain
acceptance. Dependencies below are functional dependencies, not a reason to stop
all independent offline engineering while an owner task waits.

| ID | Work and acceptance | Dependencies / current status |
|---|---|---|
| P00 | Rotate exposed runtime DB password, same restricted role, all consumers/poolers; old credential fails and supervised scan succeeds | Urgent OWNER; inventoried procedure exists; no password read/reset here |
| P01 | Key-version custody, encrypted password-manager note, historical-key coverage and independent expected checkpoints | OWNER pending; never replace missing historical key or infer new genesis |
| P02 | 7-Zip encrypted dummy restore on empty external disk; actual cold-object replicas with separately retained expected root | OWNER rehearsal pending; same PC/path is not independent custody |
| P03 | Review market-data licence/non-display/retention/derived-ML and redistribution rights per source | OWNER legal/data-provider confirmation; encryption/private storage is not permission |
| S01 | One-cut six-table SQLite image export and both measured witnesses signed together; authenticated restore and CAS checkpoint | Implemented and component-tested, inactive; previous five-table exporter and six-binding were separate; independent custody still separate |
| S02 | Independent full-image and six-table replica readback, actual encrypted copy, durable predecessor/terminal witness custody | Inactive materialization and injected original-ACK/fence review implemented and synthetic-tested; actual authenticated adapters, encrypted device and power-loss recovery still pending; S01/P01/P02 |
| S03 | Full Supabase recovery drill including roles/grants/RLS/functions/extensions, cold roots, keys and Storage object bytes | OWNER source export; disposable restore must disable cron/network dispatch; no paid PITR assumption |
| S04 | Complete factory/reader inventory and cold-aware wiring: app, collector modes, evidence/training/readiness/pending joins, local retries/checkpoints/intents | S01/S02; optional injection is not global wiring; archived generation cannot fall back hot-only |
| S05 | Original HMAC ledger sealing, protected heads/root CAS, exact idempotent retries, append/seal/delete races | Native component evidence exists; key/custody and actual factory acceptance still pending |
| S06 | Immutable operational receipt publication, lease renew/completion/fencing takeover and unknown COMMIT reconciliation | Nine owner-reported native cases; disabled namespace not live-equity integration |
| S07 | Bounded multi-segment receipt/ledger lookup with authenticated absence and independent terminal head | S05/S06; single-artifact limits cannot be solved by silently dropping old fences |
| S08 | Guard all writers in transaction: app/outboxes/positions, collector modes, research, archives/control, purge/volume rollup, monitoring | S04; cooperating advisory lock alone is not universal enforcement; owner DDL/drift must fail closed |
| S09 | Source-specific capacity bounds, reserve for indispensable recovery/exposure monitoring, allocator residue and backup delay | S08; current 24 MB admission floor stays unchanged until reviewed commissioning |
| S10 | Lossless canonical/version universe dictionary shadow ingest and PIT reader equality, actual column/JSONB serialization | Offline codec exists; native adapter, collision checks, FK/cold-reference liveness and measured peak pending |
| S11 | Quote retention: archive original raw before purge, exact cold lookup and dependency-safe time partitions | S02/S04/S09; existing NULL raw cannot be reconstructed; review PK/trigger/RLS/direct-child access |
| S12 | Daily-volume retention and no-op-upsert avoidance; 20 prior non-null dates per instrument, historical exact cold lookup | Captured maxima are not official final volume; no common 14-day deletion rule |
| S13 | Scanner/prediction retention with global observation identity and RESTRICT dependencies | S02/S04; naive date-local PK is not equivalent; passed/recoverable/research rows protected |
| S14 | Outcome/candle content-addressing preserving original immutable payload identity, active horizons and unknown coverage | S02/S04; no stripping JSON or unknown touch→zero; revisions/availability must remain explicit |
| S15 | Universe/NAV/control metadata retention and referenced headers; measured physical reclamation/partition retirement | S10–S14; additive peak must fit before owner conversion; NAV relief not permanent solution |
| S16 | Exact source→archive→replica→restore→retire protocol, tiny no-delete and delete trials, workload steady-state bound | S02/S04/S08–S15/P03; no executable bulk deletion until all gates hold |
| O01 | Capacity/missing-run/token/key/replica alerts delivered independently of DB and archive failure domain | Offline watch exists; actual delivery/absence/failure drill pending; SMTP acceptance is not inbox proof |
| O02 | Daily calendar-aware health: recorded locally, remote-verified, missed, blocked, warm-up and disabled schedules separately | O01; no green health merely from scheduler exit or request queued |
| O03 | Branch protection and newest exact-SHA release gates; rollback/boot checks and safe manual upload groups | OWNER settings; solo owner cannot self-satisfy invented second-reviewer approval; release hold remains |
| O04 | RLS drift/least privilege/default grants/Data API exposure review under restricted roles | OWNER SQL only after offline proofs; FORCE alone does not enable RLS; no blanket revoke/ENABLE |
| O05 | Outbox burst/delivery backpressure, acknowledgement vs unfinished work, deterministic restore/restart and recovery UI | Existing diagnostics; scan self-burst still needs measured bounded batching, not higher gate thresholds |
| O06 | Secrets/private-file exclusion and immutable package manifests, exact-public-tree lint/type/import/boot/full-suite | Continuous; no sweeping dirty workspace or installed capture into uploads |
| D01 | Effective-dated exchange calendar, special sessions, expiry/lot changes, corporate actions and auction phases | New closing-time finding below; preserve reviewed dev identities; do not inspect sealed data |
| D02 | Provider-vs-exchange gaps/duplicates/bad ticks/revisions/previous close reconciliation with retained provenance | Owner-file attestation is not independent authenticity; no retry storm or guessed publication delay |
| D03 | Analytics token endpoint matrix, one-token rotation/expiry, static-IP feasibility and read-only account availability | OWNER account entitlement; GET-only token is not evidence POST margin endpoint is supported |
| D04 | Expired futures source access and depth, actual contract master/roll rules, licence and development-only probe | Existing Plus entitlement unconfirmed; no new paid plan, deep history or bid/ask assumed |
| D05 | Executable forward quote contract: availability clocks, bid/ask size, Greeks age, reconnect gaps, feed connections | Four snapshots/day cannot support five-minute fills; held positions must not be evicted by sampling caps |
| D06 | Forward/development feature parity including warm-up across sessions, futures-volume roll regime and index no-volume | Existing 60-bar same-session warm-up is not multi-session replay parity |
| T01 | Intraday capital/lot sizing, maximum planned loss, portfolio correlation/daily loss and actual margin/funds | D01/D03; stop is not guaranteed loss cap, margin is not risk, sidebar capital is not broker cash |
| T02 | Dated charges/lot sizes, brokerage assumption and contract-note reconciliation, Decimal/order-level aggregation | STT alone insufficient; no default ₹20 turned into verified broker plan |
| T03 | Causal next-bar execution, contract roll/basis, latency/spread/partial fills/rejections/expiry and deadline | D01/D04/D05/T02; underlying reference is not derivative fill; 15:10 research cutoff provisional |
| T04 | Forward paper episodes including rejected/no-attempt/missed/unresolved exits, immutable suggestion identity | T01–T03; no orders, no catch-up invented fills or zero-P&L missing outcomes |
| T05 | Derivative tables/roles and independent monitor/watchdog/funding/risk/delta/ban evidence commissioning | S16/D03/T01; tables alone not safeguards; held EXIT review must still provide broker-assisted warning |
| T06 | Option comparison hold, official clearing delta vs provider Greek, explicit rates/dividends/model/tolerance | Research SVI/parity/scenarios do not lift hold or prove executable arbitrage; no invented cc_delta |
| R01 | Repair default dataset unknown-label/return-basis/claimed-proof semantics; match cold and hot reader | Defect confirmed in default reader; inactive research_claim_projection building block tested; factory integration still pending, not a deployed fix |
| R02 | Small frozen exploratory development hypotheses, economic rationale, multiplicity/serial uncertainty and no-trade result | D02/T02/T03/R01; no retuning parked rules or opening validation to find a passing candidate |
| R03 | Durable experiment lineage, source/lock/artifact hashes, drift/data shift and explicit promotion approvals | Local frozen recipe exists; ephemeral registry/caller approval claims not production governance |
| R04 | Forward cost-adjusted evidence and live-vs-replay reconciliation before model trust | T04/R03; track missingness/selection/session-end dominance and drawdowns/tail exposures |
| R05 | ML last: adequate causal targets, purged temporal validation, leakage controls, baseline/calibration/uncertainty | R01–R04/P03; no promised 99% reliability, synthetic/live training mixture or fabricated labels |
| G01 | Professional RA/IA/algo/data/privacy applicability review, actual audience/compensation/personalization/distribution | OWNER professional; no-order/private-use description alone does not settle regulatory status |

## New market-session risk found during this run

Current NSE market-timings text lists Equity Derivatives close at 15:40 IST.
Upstox's dated CAS announcement says this replaces 15:30 from 3 August 2026 and
adds separate cash-security CAS states. This is material to effective-dated
calendars, bar completeness, official closes and risk deadlines, not permission
to extend the installed recorder or strategy. The general NSE page has a stale
footer; the direct FAOP74467 circular fetch failed. Before commissioning, obtain
the retained circular and amendments and reconcile the broker's current product
square-off rules. Do not infer that 75 spot bars and 77 futures bars are equivalent
or examine 2026 holdout to resolve it. [NSE timings](https://www.nseindia.com/static/market-data/market-timings),
[Upstox effective-dated CAS change](https://upstox.com/developer/api-documentation/announcements/closing-auction-session/).

Upstox documents a free one-year Analytics Token, market-data access without static
IP and account APIs with whitelisted static IP, limited to GET. So daily login
is not universally required; actual account endpoint coverage remains a separate
gate. [Analytics Token](https://upstox.com/developer/api-documentation/analytics-token/).

## Research basis and unresolved owner decisions

Comparable-system lesson: copy the separation of data availability, fee/margin
models, fill models and live/backtest reconciliation, not a platform's defaults.
QuantConnect documents immediate complete paper fills and zero default slippage;
its reconciliation guide identifies stale fills, data revisions and availability
timestamps as causes of divergence. For this project, paper references must keep
latency, missing depth, partial-fill uncertainty and costs explicit rather than
turning a candle touch into an executable option trade. No subscription or engine
replacement is proposed. [Paper model](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/brokerages/quantconnect-paper-trading),
[Reconciliation](https://www.quantconnect.com/docs/v2/writing-algorithms/live-trading/reconciliation).

Additional risks worth keeping in the acceptance chain: portfolio-wide correlated
NIFTY exposure, daily-loss/stale-feed stop-new-entry controls, expiry convexity and
assignment/exercise consequences if an intraday exit fails, and survivorship from
excluding missed/blocked/unresolved paper episodes. Neither a stop price nor a
successful signal predicts its realized execution loss. These are risk/test
requirements, not a strategy recommendation or permission to support overnight
positions. Exchange-rule changes are effective-dated inputs, not timeless constants.

Market research freshness: SEBI's official register now lists profitability and
trading-behaviour studies dated 20 August 2026, covering FY25–FY26. The direct PDFs
could not be fetched in this run; no secondary numeric loss rates or strategy
conclusions are promoted as verified here. Retrieve and review the official
reports before using their sample/denominator or cost conclusions. These are
public market-context sources, not this project's sealed validation/holdout files.
[Profitability study](https://www.sebi.gov.in/reports-and-statistics/research/aug-2026/study-profitability-of-individual-traders-in-the-equity-derivatives-segment-fy25-fy26-_103835.html),
[Trading behaviour study](https://www.sebi.gov.in/reports-and-statistics/research/aug-2026/study-trading-behaviour-of-individual-traders-in-the-equity-derivatives-segment-fy25-fy26-_103836.html).

Free Supabase recovery must use retained offsite exports and measured drills, not
claim paid PITR equivalence. Backups exclude custom-role passwords and Storage
object bytes. Keep these private and separately inventoried; a DB-only dump is
not a whole-project restore. [Supabase backups](https://supabase.com/docs/guides/platform/backups).

SQLite online backup provides a completed snapshot. We pin the source transaction
and derive both witnesses from its finished image; WAL side-file copying is not
the plan. [SQLite backup API](https://www.sqlite.org/backup.html).

The current RA master circular is dated 6 February 2026. Review the applicable RA,
IA, retail-algo, AI responsibility and data rules with a professional against the
actual intended use. This register is not legal advice or a regulatory exemption.
[SEBI RA master circular](https://www.sebi.gov.in/legal/master-circulars/feb-2026/master-circular-for-research-analysts_99571.html).

SEBI's 30 September 2025 extension makes the retail API-algo framework and exchange
modalities applicable to all brokers from 1 April 2026. This is an execution
framework, not evidence that an analysis-only app is exempt from RA/IA rules.
Keep order endpoints absent. Before distribution, have a professional assess the
actual audience, payment/benefit, personalized sizing and actionable recommendations,
AI responsibility, performance claims, record retention and market-data rights.
Do not rely on a disclaimer or an orders-per-second threshold as exemption.
[SEBI implementation extension](https://www.sebi.gov.in/sebi_data/attachdocs/sep-2025/1759232056254.pdf).

First owner actions: P00 credential rotation, P01/P02 key and encrypted-replica
rehearsals, P03 retention/licensing confirmation, O03 branch settings, D03/D04
existing account capabilities, and G01 professional review. Report names/statuses
only, never credential values. Confirm actual Drive capacity privately: the old
5 TB entitlement and generic 15 GB free allowance are not fresh admitted capacity.
All other offline engineering continues while those owner items wait.
