# Bounded option evidence capture — research only

No database, trading, hold-release or hosted changes are made by this delivery.
The new workflow is disabled until explicitly configured. Existing entry hold,
equity scan workers and archive deletion are unchanged. The TLS follow-up below
does change the app's transport and release fingerprint; upload that fix together.

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
ten-minute slot lateness; actual timestamps are retained. Workflow triggers are
now five minutes before the targets to allow installation/startup; the process
waits (bounded) until the target before collecting. This reduces jitter, not a
guarantee of execution. This is a sampling policy,
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
Every new file/manifest carries `scheduled_at`, `capture_delay_seconds`,
`timing_quality` and `same_time_comparison_eligible`. Only complete captures within
60 seconds of the target, including retained provider packet times, have the last
flag true. This one-minute research stratum is provisional, not statistical proof
that two observations are equivalent. Delayed samples within ten minutes are
archived but fail the job and are excluded from same-time comparisons. Beyond ten
minutes no new acquisition starts. Legacy files without these fields are UNVERIFIED,
not grandfathered into a precise-time dataset. Nothing is backdated or backfilled.

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

- `OPTION_CAPTURE_ENABLED`: controls scheduled runs only; keep `false` for the
  supervised pilot. Set `true` only after separately approving recurring capture.
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
2. Configure credentials/variables, leaving OPTION_CAPTURE_ENABLED=false. Manually
   dispatch mode=capture, select the slot and tick confirm_one_run. This boolean
   authorizes this run only; it does not change repository settings. Manual audit
   also requires confirmation; preview remains offline without it. Unconfirmed
   capture/audit fails CAPTURE_DISABLED even if recurring collection is enabled.
   Authorization accepts a JSON boolean true, never the strings "true" or "false".
   Authorized manual capture uses the existing bounded wait: Python may start at
   most ten minutes before the slot, with the unchanged ten-minute late admission
   window. Job timeout is 25 minutes for setup, bounded wait, capture and upload;
   it does not extend sampling limits. Dispatch shortly before the slot, allowing
   setup time; GitHub queue delays can still cause failure. Do not rush review/CI
   to meet a slot. Both manual and scheduled runs share one concurrency group.
3. Inspect logs and the downloaded Parquet/manifest: status, selected keys, master
   terms, timestamps, actual missing reasons and file size. This live check has NOT
   been run by the coding agent. Treat repeated PARTIAL as a diagnostic, not a reason
   to loosen filters blindly.
4. Only after a separate commissioning decision, set OPTION_CAPTURE_ENABLED=true
   to enable scheduling. A manual audit of a one-slot pilot legitimately reports
   DAY_INCOMPLETE for missing slots. At 17:00 IST an audit downloads/verifies all four expected
   files; absent/partial/unverified/delayed slots fail as `DAY_INCOMPLETE`. A late
   first deployment may legitimately have missed earlier slots; do not fill those
   with later observations just to obtain a green audit.

GitHub may delay/drop scheduled jobs; missed slots are not retrospectively filled.
The same-host audit cannot detect a total GitHub outage if it too fails to run.
An independent heartbeat check/operator check is still needed for that failure mode.
Missing captures are potentially biased (for example, dropped high-load/event-day
samples); count missingness by date, slot and regime in any validation study.
For now use Actions for exploratory collection, measuring punctuality for 5–10
sessions. If fixed-time coverage matters or missingness is material, move this same
CLI to an always-on host with a local scheduler, synchronized clock and a separately
hosted heartbeat watchdog. A self-hosted runner still triggered by GitHub cron is
not the solution: the scheduling dependency remains. A Windows PC Task Scheduler
can serve a pilot if awake, powered and connected; it is not an unattended guarantee.
No paid host, external monitor or hosted setting was provisioned here.
These snapshots also consume one feed connection alongside the dashboard: check
account connection limits before enabling. Do not disconnect the dashboard to
make a capture pass.

## TLS follow-up: application streaming fixed locally

Inspection confirmed `app.py` called SDK 2.29.0's `MarketDataStreamerV3`, whose feeder
sent an Authorization bearer token with `CERT_NONE` and hostname checks disabled.
An attacker capable of intercepting the network connection could impersonate the
server, steal that credential and alter feed data. Encryption without server identity
verification does not prevent this. No interception has been established by this audit.

`secure_upstox_stream.py` now owns connection establishment. It obtains a signed
feed URL over certificate-verified HTTPS, validates the Upstox WSS hostname, rejects
redirects and non-101 handshakes, and verifies WSS certificates and hostnames. It
does not forward the bearer header to WSS. SDK subscription encoding and protobuf
decoding remain reused. No package installation is monkeypatched, no TLS fallback
exists, and application backoff is the sole reconnect owner. Errors exposed to the
app are sanitized; failed connections clear cached quotes. Existing REST fallback
retains its certificate verification. Recorder WSS also rejects redirects.

Upload `app.py`, `secure_upstox_stream.py` and `equity_runtime_health.py` together
with the capture/timing changes and tests. The new transport is included in the
release fingerprint and discovered by the existing package dependency gate.
Set `EXPECTED_EQUITY_CODE_SHA256` to:

```
a833cb201418fafaa02235b0ce16a76beb4e9491d01ee6e4e4b0471dc2a9d489
```

Other expected-version secrets are unchanged. Restart/redeploy so cached old
streamer objects are gone. Verify hosted connection and sanitized status messages;
never disable verification to fix a certificate error. Renew/rotate the affected
Upstox credential after deployment as a precaution, coordinating every consumer;
this is not a claim it was stolen. No credential or hosted setting was changed here.

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
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
