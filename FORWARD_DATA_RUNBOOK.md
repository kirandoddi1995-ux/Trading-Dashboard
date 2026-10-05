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
An owner-run Windows task adapter is now available below. It generates disabled
tasks; the agent has not installed, enabled or run any of them.

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

## Windows automatic previous-close preparation and supervised scheduling

The owner verified the private development export/replay: 55,596 rows, 737 accepted
/ 6 excluded sessions, original trade lists unchanged, two identical frozen replay
results. This is development reproducibility, not a new strategy result. Historical
2025/2026 files remain sealed. Nothing in this Windows adapter reads them.

### Policy and limitations

- Official source: NSE **Indices Daily Snapshot**, fixed HTTPS dated archive
  `https://nsearchives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv`.
  [NSE report catalogue](https://www.nseindia.com/all-reports) lists Daily Snapshot.
  No alternate hostname/provider, stale file, guessed close or scraping workaround.
- The reviewed calendar selects the exact prior non-closed session, including
  special sessions, not merely yesterday/last Friday. The target session must be
  regular. Unreviewed years fail closed; holidays and special target days skip.
- Require exactly one NIFTY 50 **price-index** row, exact report date, positive
  finite Decimal close and valid CSV. Retain the whole bounded source bytes, SHA,
  fixed URL, close date and actual retrieval time inside the immutable v2 config.
  Automatic recipes require retrieval on the target IST date before its open;
  a cached earlier fetch cannot be silently substituted.
  That source is included in existing Drive logical backups via the config.
  Publication time stays unknown; do not infer it from a dated filename.
- Real preparation/clock/CSV transport remains **uncommissioned**. A public archive
  probe timed out in the agent's environment; it did not establish endpoint/schema
  availability on your PC. Synthetic fixtures verify parser failures, not live
  NSE service behaviour. Verify the first download before enabling any task. If
  NSE blocks access or changes schema, stop: do not bypass it or substitute data.
- Price-index official close can differ from an intraday final candle close. This
  adapter deliberately uses the official daily close; it does not quietly switch
  to broker LTP or claim independent verification of every received intraday bar.
- Existing v1 manual recipes remain supported by the old one-poll CLI. The new
  automatic scheduler requires v2 official-source recipes; they cannot be silently
  mixed. Changed code/environment requires a new future config, not rewriting an
  old one. Recheck/restore old captures needs the matching saved source version.
- PC must be awake and your normal Windows user must be signed in. Locking the
  screen is fine; signing out/sleep is not. No SYSTEM/elevation/Windows password,
  forced wake, catch-up or run-on-login trigger. Independent off-PC missed-run
  alerts remain a later commissioning requirement.

### 1. Review/upload and install dependencies normally

Keep the files in their listed folders. Wait for green CI before using the new
code. No new Python or PowerShell dependency is needed. Do not copy credentials,
datasets or private task XML into GitHub. No equity fingerprint secret change.

Use normal, **non-admin** PowerShell as the same Windows user who will run the
tasks. The installer expects India Standard Time and will refuse another PC
timezone; it does not change your timezone or permissions.

Choose a private per-user state directory (not the repository or public sync):

```powershell
$forwardRoot = Join-Path $env:LOCALAPPDATA 'KiranTrading\Forward'
.venv\Scripts\python.exe forward_nifty_schedule.py --root $forwardRoot --mode prepare
.venv\Scripts\python.exe forward_windows_credentials.py
```

Expected PREVIEW: network_calls 0 / credential_reads 0, and credential setup
preview with no reads or writes. These checks do not prove token/source access.

### 2. One-time private credential setup

Generate/verify the Analytics Token and its real expiry yourself; no refresh flow
is invented. Run locally in a real terminal:

```powershell
.venv\Scripts\python.exe forward_windows_credentials.py --store
```

Hidden prompts request the existing five values listed above, including licence
acknowledgment exactly `true`, covering permitted use/retention of both Upstox
inputs and the NSE source snapshot. Automatic preparation checks this same vault
acknowledgment before fetching anything. Paste one-line OAuth JSON privately. Never put a
value on the command line, in this chat, in a transcript or in the repository.
Avoid clipboard history/cloud clipboard sync when transferring secrets.
The helper stores application-specific generic credentials in **Windows Credential
Manager**, under `KiranTrading/Forward/`, current user only. Values are not printed
or written to plaintext files. Limit 2,560 UTF-8 bytes per value; oversize input
fails, never truncates. Partially failed setup is not a success: rerun all values.

The scheduled process retrieves them into its own memory/environment and restores
the prior environment afterwards. An expired/revoked token or missing vault entry
blocks capture. The store is not protection against compromise of your own Windows
account/admin access. PRIVATE_CREDENTIALS_STORED confirms storage/structure, not a
successful broker login. The OAuth refresh credential is handled by the existing
Drive transport; no automatic Upstox token renewal is claimed.

References: [Credential storage/read API](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credreadw),
[credential scope/persistence](https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw).

### 3. Generate, inspect and register **disabled** tasks

Replace the start date with the first intended supervised day. Nothing below
enables capture. The first call only writes private XML plans; inspect them in
$forwardRoot\task-plans, then the second call verifies exact plans before registering.
No existing task or XML is overwritten.

```powershell
.\scripts\install_forward_tasks.ps1 -PrivateRoot $forwardRoot -StartDate '<YYYY-MM-DD>'
.\scripts\install_forward_tasks.ps1 -PrivateRoot $forwardRoot -StartDate '<YYYY-MM-DD>' -RegisterTasks
Get-ScheduledTask -TaskName 'KiranTrading-Forward-*' | Select-Object TaskName,State
```

Expected three **Disabled** tasks:

- prepare: daily 09:00 IST, pre-open only; real clock probe, then exact NSE file.
- poll: 09:20:30 IST and every five minutes through **15:30:30**, 75 slots.
- audit: 15:40 IST; local read-only journal/remote-ack coverage report, no network.

Each uses the normal signed-in user, least privilege, IgnoreNew overlap handling,
two-minute execution limit, no stored Windows password, no StartWhenAvailable
catch-up and no forced wake. Per-poll lateness is limited to two minutes after the
nominal completed-bar close. A missed/late run stays missing. Thirty-second offset
does not assert broker candles are published within thirty seconds: confirm in
the pilot. No sampling-window or option-recorder settings have changed.

References: [Task triggers](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasktrigger?view=windowsserver2025-ps),
[register tasks](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/register-scheduledtask?view=windowsserver2025-ps).
XML syntax/policies are tested offline; actual Windows registration is owner-
verified, not claimed by local unit tests. If registration fails partway, any
created tasks remain disabled. Do not enable a partial/incorrect installation.

### 4. First supervised day

Before 09:15, while watching the PC:

```powershell
.venv\Scripts\python.exe forward_nifty_schedule.py --root $forwardRoot --mode prepare --confirm-run
```

Expected CONFIG_PREPARED, previous_close_date matching the last genuine NSE
session, source SHA and network_calls 1. Review that day's private config.json:
v2, correct date/previous date, official NIFTY close, source URL/retained CSV/hash,
actual retrieval time before freeze/open, correct calendar and code environment.
Failure has a sanitized code and receipt; late preparation never creates a recipe.
A retry of an existing valid frozen recipe reports CONFIG_ALREADY_PREPARED without
fetching again. No source revision is silently applied after freezing.

After a five-minute close, ideally at 09:20:30, run the first poll manually:

```powershell
.venv\Scripts\python.exe forward_nifty_schedule.py --root $forwardRoot --mode poll --confirm-run
```

Watch for REMOTE_VERIFIED and its recorded/missing counts, actual receipt times,
and no secrets. Then enable **only the poll and audit tasks** for that supervised
day if the result is correct. This is an owner action, not done by this agent:

```powershell
Enable-ScheduledTask -TaskName 'KiranTrading-Forward-poll'
Enable-ScheduledTask -TaskName 'KiranTrading-Forward-audit'
```

If manual capture completes the first slot before the task fires, the existing
idempotency guard prevents duplicate observations. Keep the PC awake/signed in;
watch the first scheduled results and private scheduler-receipts. Task Scheduler's
History may need enabling manually to view trigger history. The first day may be
partial if enabling misses a slot; never reconstruct that observation later.

At day end, SESSION_CAPTURE_COMPLETE requires 75 journal records **and** a verified
remote acknowledgment of 75. It separately reports unavailable decisions (warmup
or missing context), so collection completeness is not usable-signal completeness.
SESSION_CAPTURE_INCOMPLETE exits 1; blocked errors exit 2. Inspect receipts/state;
Task Scheduler start or exit 0 alone is not evidence of complete capture. These
local receipts are not independent notifications if the PC itself is asleep/off.

After a clean supervised day and the private Drive restore/recheck drill above,
you may separately enable the prepare task for following sessions:

```powershell
Enable-ScheduledTask -TaskName 'KiranTrading-Forward-prepare'
```

That is the explicit recurring commissioning decision. No daily owner close entry
is then required. Owner intervention remains necessary for outages, token rotation,
source changes, unreviewed calendar years, revised bars or stale crash locks.

### 5. Stop safely

```powershell
Disable-ScheduledTask -TaskName 'KiranTrading-Forward-prepare'
Disable-ScheduledTask -TaskName 'KiranTrading-Forward-poll'
Disable-ScheduledTask -TaskName 'KiranTrading-Forward-audit'
```

Disabling future triggers does not stop a currently running instance; wait for its
bounded completion or use Task Scheduler's End deliberately. A forced stop may
leave a producer lock; verify no active process before clearing only that lock.
Keep all configs, journals, source bytes, receipts and Drive history. No data or
credential deletion is required. Do not call recurring operation reliable until
the later independent missed-run/watchdog alert has been deliberately tested.
