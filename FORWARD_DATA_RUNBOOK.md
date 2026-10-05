# Private development export and supervised forward research

Local tools only. No new collector, workflow schedule, database table or app hook
is enabled. This slice records NIFTY **underlying directional diagnostics**, not
option quotes, futures execution, costs, fills or trade recommendations.

## Order and storage

1. Export the verified development partition offline; review its counts and frozen
   recipe, then run the existing development replay. Keep 2025/2026 historical
   validation/holdout sealed. Do not start new hypotheses or retune parked rules.
2. Review this producer's different, explicit session-reset context policy. It
   does not claim parity with the multi-session development replay. Freeze one
   upcoming regular session, including a verified previous close and source hash.
3. Preview offline, then commission a few supervised polls. Verify actual receipt
   times, missing decisions, clock failures, expired auth and private Drive restore.
4. Choose persistent hosting and independent missed-run alerts only after those
   observations. Nothing here automatically arms unattended capture.

Private Drive is the remote backup/archive, not the computer executing the job.
Never use the public repository, Actions artifacts or releases for market data.
The exact-input JSON/gzip bundle avoids duplicating candle payloads for every
decision; it stores one context plus prefix hashes and journal records. Each
verified upload is capped at 2 MiB compressed / 8 MiB expanded. No Supabase writes.
Each poll uploads an immutable full logical backup; monitor Drive object count
and cumulative bytes, not just the final day's bundle size. No automatic pruning.

Start on the awake PC. For unattended use, prefer a dedicated persistent VM/service
with durable disk and one supervised timer/process, independent of Streamlit sleep.
GitHub cron can be delayed or dropped, and ephemeral state complicates continuity.
A public-repository self-hosted runner should not share this credential-bearing
service with untrusted PR jobs. An always-on PC is possible but must be maintained.
No host/account or remote timer is configured by these files.

Current Upstox documentation says a one-year Analytics Token supports market-data
and historical-data APIs **without** a static-IP restriction; account/portfolio
APIs do require the whitelist. This revises the earlier blanket static-IP concern
for the research producer, not for the portfolio monitor. Actual account access
to the fixed intraday endpoint must still pass the supervised test. Do not assume
automatic token refresh or annual token provisioning has been verified.

Sources: [Analytics Token](https://upstox.com/developer/api-documentation/analytics-token/),
[intraday V3 bars](https://upstox.com/developer/api-documentation/v3/get-intra-day-candle-data/),
[GitHub scheduling](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows),
[Drive scope](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).

## Offline development export

Choose paths **outside the repository and OneDrive/public sync**. Examples are
placeholders: replace them with your actual verified download/readiness folders.
The source is the original combined CSV used by readiness, not a Parquet file.

```powershell
$download = 'D:\TradingResearch\nifty-download'
$ready = 'D:\TradingResearch\nifty-ready-v3'
$development = 'D:\TradingResearch\automation\development-inputs-1'
$qualityHash = (Get-FileHash -LiteralPath "$ready\quality.json" -Algorithm SHA256).Hash.ToLowerInvariant()
$sessionsHash = (Get-FileHash -LiteralPath "$ready\sessions.json" -Algorithm SHA256).Hash.ToLowerInvariant()
.venv\Scripts\python.exe export_development_inputs.py --source-csv "$download\combined.csv" --sessions "$ready\sessions.json" --quality "$ready\quality.json" --quality-sha256 $qualityHash --sessions-sha256 $sessionsHash --output $development
```

Expected: DEVELOPMENT_EXPORTED, development-only row/session counts and no approval
authority. Review export.json: bars.csv/sessions.json SHA-256, original source
hashes, accepted/excluded sessions. Incomplete and special sessions remain present
and excluded by the existing validator; nothing is trimmed/backfilled to pass.
Check those counts against development dates in readiness metadata. The exporter
hashes mixed source **bytes**, reads date metadata, and stops before interpreting
later numeric prices/previous closes. It does not score later data. Source files
are unchanged, and an existing output directory is rejected. A partial directory
without export.json is not a completed export; choose a new destination on retry.

Use export.json's `manifests.bars.sha256` and `manifests.sessions.sha256` with the
existing automated_directional_replay.py prepare/register/run instructions in
AUTOMATED_RESEARCH_RUNBOOK.md. The data root is $development, relative filenames
are bars.csv and sessions.json, and the recipe is strictly 2022-01-01–2024-12-31.
Review before registration. Do not reuse a report-only recipe as a bars recipe.

## Prepare one upcoming session before its open

Choose a verified regular trading date. No weekends, holidays, special sessions or
unreviewed calendar years. Verify the previous completed daily close yourself and
hash the retained source artifact; the CLI does not fetch it or guess a fallback.
Source hash is provenance, not proof that the price was independently verified.
Hashes and reproduction establish integrity, not independent price truth or
cryptographic proof of a genuine observation. The commissioned collector/host is
the trust boundary; synthetic OBSERVED fixtures are tests, not real capture evidence.

```powershell
$config = 'D:\TradingResearch\forward\session-config.json'
$state = 'D:\TradingResearch\forward\session-state'
.venv\Scripts\python.exe forward_nifty_job.py --config $config --state $state --prepare --trading-date '<YYYY-MM-DD>' --previous-close '<verified-close>' --previous-close-source-sha256 '<64-lowercase-hex-source-hash>'
.venv\Scripts\python.exe forward_nifty_job.py --config $config --state $state
```

Expected CONFIG_PREPARED then PREVIEW, network_calls: 0. Config is immutable and
binds instrument, date, exact regular hours, pre-open freeze, previous close,
calendar source and transitive code/dependency fingerprints. Review it. New code
or dependency versions require a newly reviewed future recipe; never rewrite an
old config. All paths stay private. Preparation refuses existing config files.

## Explicit supervised poll

Configure environment values privately in the chosen host's secret manager or
process setup. Do not paste them into chat, commit them, echo them, or put secret
values on a command line/history. No new secret file is written by these tools.

- UPSTOX_ANALYTICS_TOKEN: existing valid read-only token.
- FORWARD_TOKEN_EXPIRES_AT: its **actual** aware ISO-8601 expiry, no guessed date.
- FORWARD_CAPTURE_LICENSE_ACK=true: owner-reviewed retention/use permission.
- DRIVE_OAUTH_TOKEN_JSON: existing offline OAuth credential JSON, drive.file only.
- OPTION_CAPTURE_DRIVE_FOLDER_ID: existing private archive folder.

Confirm that the OAuth app can access the folder and it is not publicly shared;
folder ID alone does not prove privacy. drive.file is app-specific and cannot
read arbitrary Drive files. Keep the same authorized OAuth client/visible folder;
do not widen scope to solve a permission failure.

```powershell
.venv\Scripts\python.exe forward_nifty_job.py --config $config --state $state --confirm-run
```

One invocation = one current-day REST poll. No websocket/feed connection is added.
Run shortly after a five-minute close, not before open; forming candles are ignored.
A real bounded clock probe must verify offset/uncertainty within one second before
the fetch. This is a research timestamp-quality policy, not a validated trade gate.
Network timeouts/permissions/auth failures return exit 2 and sanitized BLOCKED
messages, with local failure receipts where disk permits. AUTH_REQUIRED is never
an empty successful dataset. Clock probe connectivity requires host commissioning.

Inputs commit locally with FULL-sync SQLite. Only the **newest** received completed
bar emits an observation; earlier bars fetched together are first-seen context,
not evidence of past decisions. Missing opening-prefix bars and the first 59 bars
produce unavailable diagnostics. With this conservative daily reset, early-day
signals are deliberately unavailable; do not interpret that as failed capture.
No index-volume confirmation is used. No futures/option execution is inferred.

Actual receipt/computation times are kept; availability is never backdated to bar
end. Missing decisions remain in the denominator of 75. A late first poll cannot
make a full day green. Closed-bar revisions stop for review, never overwrite data.
An exclusive local producer lock rejects overlapping polls. A crash can leave that
lock: verify no process still uses this state before removing **only the lock**.
Never run a second host against copied active state. Cross-host leadership is not
provided. A future timer should poll serially, skip overlap, and raise missed-run
alerts; a 30-second cadence is a commissioning proposal, not enabled automation.

REMOTE_VERIFIED means both uploaded bundle and manifest were downloaded and matched.
Also inspect capture_status, recorded_decisions and missing_decisions; it is not
proof of full-session coverage or economically useful signals. Local durability
survives Drive failure; private storage loss before verified backup remains a risk.
Retry just backup without a market token/new observation:

```powershell
.venv\Scripts\python.exe forward_nifty_job.py --config $config --state $state --backup-only
```

## Offline backup/replay drill

Download the data bundle privately from Drive and use the sha256 in its verified
manifest/receipt. Do not trust an unverified filename or upload data into GitHub.

```powershell
.venv\Scripts\python.exe forward_nifty_archive.py --archive 'D:\TradingResearch\backup.json.gz' --sha256 '<manifest-sha256>'
.venv\Scripts\python.exe forward_nifty_archive.py --archive 'D:\TradingResearch\backup.json.gz' --sha256 '<manifest-sha256>' --restore 'D:\TradingResearch\new-restored-state'
```

Recheck reproduces only recorded decisions from their exact first-seen prefixes.
It reports matched, missing_decisions and complete_session separately. A partial
matching subset never becomes a full-session pass. Restore preserves original
OBSERVED records/receipt times; it does not manufacture new observations. Only
restore.json proves restoration finished. Existing destinations are rejected.
Keep matching source/dependency versions privately for disaster recovery; mismatch
blocks offline reproduction/restoration. Do not feed these current-date bundles
to the development-only archived_directional_replay.py checker.

## Upload and checks

Keep each path in its correct folder. Upload code/config/docs together and test
files under tests/. No credential, market input, SQLite state or downloaded bundle
belongs in the upload. This batch changes no app-imported production source, so
EXPECTED_EQUITY_CODE_SHA256 remains unchanged.

```powershell
$env:EQUITY_TEST_PGLITE_MODULE = Join-Path (Get-Location) 'tests/sql-harness/node_modules/@electric-sql/pglite'
$testRoot = Join-Path $env:TEMP ('forward-tests-' + [guid]::NewGuid().ToString('N'))
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp $testRoot
.venv\Scripts\python.exe -m mypy --config-file mypy-automation.ini --cache-dir "$env:TEMP\research-mypy-cache"
$sourceFiles = @(Get-ChildItem -File -Filter '*.py' | Select-Object -ExpandProperty Name)
.venv\Scripts\python.exe -m pyflakes @sourceFiles tests
```
