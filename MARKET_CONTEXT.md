# Market context v1 — descriptive, not actionable

## Boundary

This panel returns no decision, score, position size or authorization. Existing
VIX/regime calculations, model gates and the option-entry hold are unchanged.
Event warnings here DO NOT enforce an entry blackout. Missing calendars mean
unknown event coverage, not permission to trade. An enforced event policy needs
a separate reviewed integration and validated strategy/event evidence.

The panel appears on equities, options, futures and SMC pages. Opening it does
not fetch data. Explicit refresh uses the existing logged-in Upstox token;
missing/expired credentials show unavailable data, never fabricated observations.
Source times and receipt/first-known times are separate. Historical data fetched
today does not become evidence that the system knew it on an earlier date.

## Sources and existing coverage

- `prospective_collection.py` already selects global instruments and USD/INR
  futures, fetches quotes and collects FII/DII CASH flows. This layer reuses only
  its read adapters, not its SQL writer. Cash flows are not participant-wise OI.
- India VIX quote and daily history reuse the existing Upstox/history functions.
  Change is in VIX points. Percentile requires 252 distinct prior supplied
  sessions; insufficient history is unavailable. This is an empirical percentile,
  not a prediction or a newly validated sizing rule. Missing sessions still need
  review; no synthetic closes are inserted.
- Upstox's global GIFT indicator does not establish an expiry-specific futures
  contract. It is labelled an indicator. Overnight percentage remains unavailable
  unless supplied observations identify the SAME contract, official contract
  provenance, previous-session India-close anchor and current pre-open anchor.
  It never compares GIFT futures with NIFTY spot. Manually supplied anchors are
  not independently verified. GIFT/US/Asian cues are not summed as confirmations.
- USD/INR via Upstox is explicitly the nearest selected NSE currency FUTURE,
  with expiry recorded, not spot or the FBIL reference fix. Official FBIL/RBI
  reference observations can be imported separately, with timestamps and units.
- G-Sec benchmark yield needs a dated official CCIL/FBIL/RBI source entry.
  No reliable automated benchmark-yield endpoint was established for this build.
  Supply percent units and a benchmark identifier; a benchmark switch cannot
  produce a basis-point change. A zero-coupon curve is not automatically the
  benchmark-bond yield. India–US spreads are not treated as direct flow forecasts.
- RBI, Budget, elections: dated manual official-source entries. RBI repo, stance,
  liquidity and press conference are separate components. Election counting and
  results are separate. No dates, meeting counts or fixed post-event clearance
  are guessed. Window end does not resolve an event. A recorded review is not
  entry authorization.
- Rebalances: manual official MSCI/Nifty source records, announcement/publication
  separate from effective time. MSCI GIMI quarterly review and Nifty 50 normal
  semiannual schedules are context, not hardcoded dates or a substitute for
  actual announcements/exceptional changes. Estimated demand is not buying.
- Sector tags are qualitative hypotheses (IT/USD, banks/RBI, metals/China,
  aviation/fuel, FMCG/rural demand), never estimated weights or direction scores.

Reference documentation:
- https://upstox.com/developer/api-documentation/instruments/
- https://www.ccilindia.com/web/ccil/analytics
- https://www.fbil.org.in/
- https://www.rbi.org.in/ and https://www.indiabudget.gov.in/ and https://results.eci.gov.in/
- https://www.msci.com/eqb/gimi/stdindex/index_review.html
- https://www.niftyindices.com/resources/index-rebalancing-schedule

## Participant-wise OI

The opt-in weekday job requests the dated official file:
`https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_DDMMYYYY.csv`.
It checks the printed date, exact headers, all four participants, side totals
and aggregate totals. Original bytes and SHA-256 are retained. Counts are
contracts, not delta exposures; Client is not synonymous with retail and short
futures may be hedges. Publication time is left unknown when the file does not
provide it; receipt time is the earliest usable availability in this system.

The parser and transport are fixture-tested, NOT verified against a live download
in this implementation. A changed official layout, holiday/nonpublication, 404 or
blocked download fails the job visibly, not as a valid empty list. Review a first
manual collect before enabling scheduling. 20:35 IST is a collection attempt,
not a guaranteed publication or GitHub start time; inspect failed/missing runs.
This is not a complete exchange holiday calendar or a publication watchdog.

## Storage and operation

No migration and **zero additional Supabase writes**. Existing shadow collectors
still write their existing data; they are unchanged. UI state lives only in the
Streamlit session. Export it before restarting if needed. No automatic background
quote capture is claimed: the scheduled job captures participant OI only, and
requires no broker token. Existing global-cue capture remains separate.

Private archives use compressed JSON plus a manifest (heterogeneous, small,
dated records), not another raw quote table. Read-back checks compressed SHA-256,
exact content and row count before reporting success. Identical packet retries
reuse the content-addressed files; separate observations have distinct receipt
times and remain distinct. No database deletion is performed by this job.
Maximum 1 MiB uncompressed and 1,500 records per packet, including original source
files. At one scheduled packet per weekday this bounds uncompressed input near
252 MiB/year plus manifests; actual four-row OI packets should be much smaller.
Manual runs/exports add packets. Monitor Drive storage; no automatic pruning.

Configure GitHub **secrets**:
- `DRIVE_OAUTH_TOKEN_JSON`: existing validated OAuth authorized-user JSON,
  `drive.file` scope; do not use a service account for personal Gmail storage.
- `MARKET_CONTEXT_DRIVE_FOLDER_ID`: private folder accessible to that OAuth app.

Configure GitHub **variables**, only after review:
- `MARKET_CONTEXT_ARCHIVE_ENABLED=true`
- `MARKET_CONTEXT_LICENSE_ACK=true`: you have verified private capture/retention
  is permitted by the relevant data terms. Public accessibility is not a licence.

Both are opt-in; absent variables disable scheduled capture. Workflow preview
is offline and does not read credentials. First run preview, then a manual collect,
review the verified files and source date, then enable the weekday schedule.
Failures produce sanitized status only, never token/error-response contents.

Local equivalents, after installing `requirements-archive.txt`:
```
python market_context_job.py --preview
python market_context_job.py
python market_context_job.py --input market-context.json
```
Set the same environment variables locally if using the last two commands.
The CLI preserves record timestamps when archiving an exported packet. Manual
UI import stamps availability NOW and labels values unverified; an allowlisted
URL is provenance supplied by the operator, not proof of the document's contents.
Archives are not automatically consumed by training or decisions.

## Manual record shape (illustrative only, not a real observation)

Import a JSON object with `records` array. Every item requires `kind`, `series`,
`source_url`, timezone-aware `source_at` and `payload`. Numeric kinds need exact
`unit`: GSEC10Y=PERCENT, USDINR=INR_PER_USD, GIFT=POINTS, VIX=VIX_POINTS.
Example shape; replace every illustrative value/source with your reviewed record:
```
{"records":[{"kind":"GSEC10Y","series":"benchmark-yield",
"source_url":"https://www.ccilindia.com/REPLACE_WITH_ACTUAL_SOURCE",
"source_at":"2026-09-29T17:00:00+05:30","unit":"PERCENT",
"payload":{"value":"6.50","benchmark_id":"REPLACE_WITH_ACTUAL_BOND"}}]}
```
Events additionally require `published_at` and payload category RBI/BUDGET/ELECTION,
component, `window_start`, optional `window_end` and `review_completed_at`.
Use a unique series per event component. `source_at` is observation/publication,
not a future scheduled event time. Rebalances require `published_at` and payload
`effective_at`. Never invent a publication time to enable point-in-time research.

## Promotion beyond descriptive context

Before any risk filter or trade signal, review: availability at decision time;
incremental value beyond correlated global inputs; sector/horizon relevance;
out-of-sample regimes and costs; and missing/late feed behavior. These files
provide no promotion switch. Any future decision integration needs explicit
code review and tests; manual review flags cannot unlock approvals.

## Local verification and upload checklist (2026-09-30)

Full suite: **994 passed, 4 skipped, 2 subtests passed**, 109.59 seconds, including
the installed PGlite SQL harness. Pyflakes passed for changed Python files;
`market_context_job.py --preview` passed offline. No live source, broker, Drive,
Supabase or hosted UI verification was performed. Skips remain skips.

Upload these 10 files, preserving their paths:
- `app.py`
- `equity_runtime_health.py`
- `market_context.py`
- `market_context_sources.py`
- `market_context_ui.py`
- `market_context_archive.py`
- `market_context_job.py`
- `.github/workflows/market-context.yml`
- `tests/test_market_context.py`
- `MARKET_CONTEXT.md`

For this exact local release, update Streamlit's `EXPECTED_EQUITY_CODE_SHA256`
after uploading the matching files:
```
e6af7f13e19c5f2eb3bc691291221f257e04efdfb950c8b656d94f1bc3f8bfa8
```
No other release secret or policy hash is changed by this feature. The runtime
manifest now covers the three new UI/context source modules. No SQL migration,
dependency-file change or packaged release artifact is needed for this upload.
