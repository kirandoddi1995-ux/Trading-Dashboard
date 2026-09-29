# Bounded option evidence capture — research only

No database, trading, hold-release or hosted changes are made by this delivery.
The new workflow is disabled until explicitly configured. Existing entry hold,
equity scan workers, collectors, archive deletion and release fingerprint are unchanged.

## Scope and limits

Start with NIFTY only. Optionally add two liquid NSE stock **instrument keys** after
reviewing the first files. Maximum three underlyings and 150 total instruments.
From the current NSE master select the nearest two available option expiries,
ATM plus up to five strikes on either side (paired CE/PE), and nearest two available
futures expiries. Fewer available expiries/strikes are visible in the inventory;
no synthetic contracts. Master fields, weekly flags, lots, ticks, raw expiry values,
selected contract definitions and master SHA-256 are retained. No invented expiry
weekday, settlement cutoff, rate, dividend or IV-unit conversion.

Four snapshots per weekday: 10:15, 11:45, 13:45, 15:00 IST. Each opens one V3 full
feed for at most roughly 60 seconds plus connection/receive timeout. Maximum
ten-minute slot lateness; actual timestamps are retained. This is a sampling policy,
not an authoritative exchange calendar. REST market status and feed segment status
must corroborate normal trading; confirmed closed sessions get a verified skip.
Unknown session states fail. Special weekend sessions are outside this initial schedule.

Each snapshot retains spot, futures and option best bid/ask and sizes, spread,
packet age, LTP/index reference and last-trade time, volume/OI, raw IV/Greeks,
raw per-instrument feed, local receive time and provider packet time. All selected
records need packet age <=5 seconds and cross-instrument timestamp skew <=2 seconds
for `CAPTURED`. These are **unvalidated capture-quality filters, not Greek tolerance
or execution-approval thresholds**. Index value freshness is checked separately.

Provider packet time is NOT proof of exchange book time or Greek calculation time;
those field-level times stay unknown. Missing fields stay null, not zero. Protobuf
default omissions stay unknown too; this can deliberately produce partial captures.
Partial updates replace rather than merge fields, preventing fresh timestamps on
old books. Partial/stale/crossed/incomplete samples and interrupted streams remain
research records with reasons and a failing job, never fabricated completed chains.
No reconnection combines epochs. REST LTP is used only to choose strikes, not as
the aligned captured execution reference. Future maturities remain explicit; these
files do not silently treat a different-maturity future as the option's forward.

## Storage and verification

Reuse `drive_archive.py` OAuth transport and `derivative_quotes.decode_v3`, not
the database-writing scheduled collector. One Zstd Parquet and a small JSON manifest
per slot. Analytical columns are strings to avoid extra numeric conversion;
`_row_json` retains original decoded types. No raw Protobuf binary or entire master
download is archived; selected master rows and the complete-master digest are kept.

Before success: download the uploaded Parquet; compare SHA-256; check identity,
row count, every analytical column and complete reconstructed rows; upload and
download-verify the manifest. Identity includes policy, date and slot. First verified
sample wins, including partial samples. Retries reuse it rather than replacing
history with a later cut. An orphan data upload can recover its manifest, including
a same-day manual rerun after the slot (no new market data is fetched). Conflicts
or duplicate Drive files fail explicitly. One writer only: workflow concurrency
prevents overlapping runs; a later host must provide equivalent serialization.

Hard data-file cap: 2 MiB per snapshot, therefore <=8 MiB per four-slot day plus
small manifests/health records (~2 GiB per 252 sessions at the cap). Actual size
should be measured from the first files; no unsupported compression forecast.
Supabase growth is zero. Drive quota is still finite. Review monthly; keep verified
historical files, optionally mirrored to the PC, rather than deleting them with the
operational 14-day archive job. Do not place this dataset under any automated
deletion rule. OAuth access does not itself grant market-data retention/redistribution
rights: confirm your provider terms before enabling; keep the folder private.

## Authentication and setup after review/upload

Upstox's current Analytics Token is read-only, lasts one year, and supports market
data and WebSocket access **without a static IP**. Account/portfolio reads still need
a whitelisted static IP. Thus GitHub-hosted runners are suitable for this collector,
unlike an account-position monitor. Reuse the existing Analytics Token: only one is
allowed per account; generating a replacement can affect other consumers.

GitHub Actions **secrets**:

- `UPSTOX_ANALYTICS_TOKEN`: existing token, not the daily access token.
- `DRIVE_OAUTH_TOKEN_JSON`: existing production-mode offline OAuth credential JSON.
- `OPTION_CAPTURE_DRIVE_FOLDER_ID`: private folder accessible to that OAuth app
  under `drive.file`. Initially copy the existing `DRIVE_ARCHIVE_FOLDER_ID` value:
  the new `options-` filenames and identities are separate from SQL archives.
  A dedicated folder is optional, but must be created/selected through the same
  authorized app; an arbitrary manually created folder may not be visible with
  that scope. Do not regenerate the existing OAuth token just to start capturing.

GitHub Actions **variables**:

- `OPTION_CAPTURE_ENABLED`: leave absent/false for review; set `true` to enable.
- `OPTION_CAPTURE_LICENSE_ACK`: `true` only after checking permitted private retention.
- `OPTION_CAPTURE_TOKEN_EXPIRES_AT`: actual expiry from Upstox, ISO8601 with timezone
  (do not use an invented future date).
- `OPTION_CAPTURE_UNDERLYINGS_JSON`: optional, defaults to `["NSE_INDEX|Nifty 50"]`.

No database secrets, order permissions, static IP or OAuth browser interaction is
used at runtime. Missing/expired/revoked broker credentials produce `AUTH_REQUIRED`,
not an empty chain. Logs contain fixed status codes and days to token expiry,
never credentials, signed feed URLs or raw exception text. Drive failures produce
a failing job even when a durable health receipt cannot be stored. Renew tokens
before expiry and maintain GitHub Actions failure notifications.

1. Upload the seven new files, run normal CI, then manually dispatch `preview`.
   Preview prints policy only: no broker or Drive access.
2. Configure credentials/variables. Run `capture` during one of the configured slots.
3. Inspect logs and the downloaded Parquet/manifest: status, selected keys, master
   terms, timestamps, actual missing reasons and file size. This live check has NOT
   been run by the coding agent. Treat repeated PARTIAL as a diagnostic, not a reason
   to loosen filters blindly.
4. Enable scheduling. At 17:00 IST an audit downloads/verifies all four expected
   files; absent/partial/unverified slots fail as `DAY_INCOMPLETE`.

GitHub may delay/drop scheduled jobs; missed slots are not retrospectively filled.
The same-host audit cannot detect a total GitHub outage if it too fails to run.
An independent heartbeat check/operator check is still needed for that failure mode.
These snapshots also consume one feed connection alongside the dashboard: check
account connection limits before enabling. Do not disconnect the dashboard to
make a capture pass.

Transport uses `websocket-client` with certificate and hostname verification. It
uses only the SDK's protobuf definition, not its streamer. Inspection of installed
SDK 2.29.0 found its feeder sets `CERT_NONE`; this new path avoids it. Any existing
application path using that feeder needs a separate security review; it was not
changed here.

Local CLI after installing `requirements-option-capture.txt`:

```powershell
python option_capture_job.py --preview
python option_capture_job.py --slot 1015
python option_capture_job.py --audit-today
```

The same CLI can run on another scheduler later; no Streamlit login/session is needed.

## Evidence timeline and governed hold release

Suggested planning ranges, NOT statistical certificates: first 5–10 sessions to
verify capture quality; 4–8 weeks for an initial convention/tolerance investigation
across several expiries. Stock monthly expiries and unusual regimes need longer.
A one-year IV rank/percentile series needs a consistent year of observations;
do not relabel this short, sparse archive as long history. Four daily points cannot
validate continuous intraday dynamics, fill probabilities or every near-expiry
instability. ±5 strikes may omit desired deltas; no extrapolated substitute.

Data alone cannot verify provider conventions. Before proposing any lift:

1. Document provider IV/Greek units, pricing model, spot/forward use, timestamp
   meaning, theta/vega scaling and actual expiry cutoffs, with authoritative evidence.
2. Supply versioned point-in-time trusted rates/dividend/corporate-action inputs.
   This capture deliberately stores unknowns rather than manufacturing them.
3. Build a reviewed enrichment/import adapter to the existing research workbench.
   Raw Parquet is **not** an automatically trusted comparator bundle. Preserve source
   hashes and missing fields through enrichment; do not fabricate rate/dividend facts.
4. Analyze mismatch distributions by expiry/moneyness/liquidity/regime on separate
   development and held-out dates; account for correlation between strikes and days.
   Pre-register tolerances and excluded/unstable regions before evaluating held-out data.
5. Review a versioned report with coverage, exclusions, errors and limitations.
   Explicit owner approval and a separate reviewed code/policy change are required.
6. Release narrowly, with drift checks and rollback; `NOT_COMPARABLE`, `UNSTABLE`
   and `MISMATCH` remain blocking. Even `CONSISTENT` never overrides other safeguards.

No amount of these same-provider samples becomes an independent price source or
official clearing-house delta. There is no collector flag, manifest field or research
output that unlocks approvals. The existing option-entry hold remains unchanged.

Sources checked September 30, 2026:
- https://upstox.com/developer/api-documentation/analytics-token/
- https://upstox.com/developer/api-documentation/v3/get-market-data-feed/
