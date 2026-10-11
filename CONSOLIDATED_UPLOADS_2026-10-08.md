# Remaining uploads and capture handover — 8 October

This supersedes the thirteen one-at-a-time upload instructions. Owner reports A
and B merged; their source is NOT recopied. Use TWO PRs, each a fresh clean clone
of current main after its predecessor merges. No hosted settings/migrations,
capture installation or task changes are performed by the agent.

## Upload 1 — capture recovery and exact upload checker (14 paths)

Complete source → destination list follows. Sources are absolute. Destinations
are relative to the ROOT of your fresh clean clone, NOT the project workspace.

- `C:/Users/banga/Desktop/kiran_share_market/forward_nifty_job.py` → `forward_nifty_job.py`
- `C:/Users/banga/Desktop/kiran_share_market/forward_capture_diagnostics.py` → `forward_capture_diagnostics.py`
- `C:/Users/banga/Desktop/kiran_share_market/forward_drive_probe.py` → `forward_drive_probe.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_forward_capture_diagnostics.py` → `tests/test_forward_capture_diagnostics.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_forward_drive_probe.py` → `tests/test_forward_drive_probe.py`
- `C:/Users/banga/Desktop/kiran_share_market/FORWARD_DRIVE_RECOVERY_2026-10-08.md` → `FORWARD_DRIVE_RECOVERY_2026-10-08.md`
- `C:/Users/banga/Desktop/kiran_share_market/forward_drive_folder_check.py` → `forward_drive_folder_check.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_forward_drive_folder_check.py` → `tests/test_forward_drive_folder_check.py`
- `C:/Users/banga/Desktop/kiran_share_market/FORWARD_DRIVE_FOLDER_SELECTION.md` → `FORWARD_DRIVE_FOLDER_SELECTION.md`
- `C:/Users/banga/Desktop/kiran_share_market/AUTOMATION_PROGRESS.md` → `AUTOMATION_PROGRESS.md`
- `C:/Users/banga/Desktop/kiran_share_market/reviewed_upload_check.py` → `reviewed_upload_check.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_reviewed_upload_check.py` → `tests/test_reviewed_upload_check.py`
- `C:/Users/banga/Desktop/kiran_share_market/REMAINING_UPLOADS_2026-10-08.json` → `REMAINING_UPLOADS_2026-10-08.json`
- `C:/Users/banga/Desktop/kiran_share_market/CONSOLIDATED_UPLOADS_2026-10-08.md` → `CONSOLIDATED_UPLOADS_2026-10-08.md`

## Upload 2 — remaining storage C through L (53 paths)

This complete union includes all dependencies through L. Staged G/I candidates
map to ROOT; never copy the dirty root versions or staging directories.
No held supabase/migrations SQL is included or authorized.

- `C:/Users/banga/Desktop/kiran_share_market/storage_transition.py` → `storage_transition.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_storage_transition.py` → `tests/test_storage_transition.py`
- `C:/Users/banga/Desktop/kiran_share_market/STORAGE_TRANSITION_PACKAGE.md` → `STORAGE_TRANSITION_PACKAGE.md`
- `C:/Users/banga/Desktop/kiran_share_market/OVERNIGHT_STORAGE_HANDOFF_2026-10-08.md` → `OVERNIGHT_STORAGE_HANDOFF_2026-10-08.md`
- `C:/Users/banga/Desktop/kiran_share_market/PERMANENT_STORAGE_PACKAGES.md` → `PERMANENT_STORAGE_PACKAGES.md`
- `C:/Users/banga/Desktop/kiran_share_market/AUTOMATION_PROGRESS.md` → `AUTOMATION_PROGRESS.md`
- `C:/Users/banga/Desktop/kiran_share_market/ledger_cold_store.py` → `ledger_cold_store.py`
- `C:/Users/banga/Desktop/kiran_share_market/ledger_history_stream.py` → `ledger_history_stream.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_ledger_history_stream.py` → `tests/test_ledger_history_stream.py`
- `C:/Users/banga/Desktop/kiran_share_market/COLD_HISTORY_STREAM_PACKAGE.md` → `COLD_HISTORY_STREAM_PACKAGE.md`
- `C:/Users/banga/Desktop/kiran_share_market/ledger_read_contract.py` → `ledger_read_contract.py`
- `C:/Users/banga/Desktop/kiran_share_market/ledger_source_capture.py` → `ledger_source_capture.py`
- `C:/Users/banga/Desktop/kiran_share_market/ledger_runtime_reader.py` → `ledger_runtime_reader.py`
- `C:/Users/banga/Desktop/kiran_share_market/ledger_archive_publication.py` → `ledger_archive_publication.py`
- `C:/Users/banga/Desktop/kiran_share_market/cold_local_objects.py` → `cold_local_objects.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_ledger_read_contract.py` → `tests/test_ledger_read_contract.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_ledger_staged_reader.py` → `tests/test_ledger_staged_reader.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_cold_local_objects.py` → `tests/test_cold_local_objects.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_ledger_archive_publication.py` → `tests/test_ledger_archive_publication.py`
- `C:/Users/banga/Desktop/kiran_share_market/COLD_READER_AND_SEALING_PACKAGE.md` → `COLD_READER_AND_SEALING_PACKAGE.md`
- `C:/Users/banga/Desktop/kiran_share_market/sql/storage_layout_inventory_read_only.sql` → `sql/storage_layout_inventory_read_only.sql`
- `C:/Users/banga/Desktop/kiran_share_market/sql/daily_volume_retention_read_only.sql` → `sql/daily_volume_retention_read_only.sql`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_daily_volume_retention_preview.py` → `tests/test_daily_volume_retention_preview.py`
- `C:/Users/banga/Desktop/kiran_share_market/STORAGE_STRUCTURAL_COMMISSIONING.md` → `STORAGE_STRUCTURAL_COMMISSIONING.md`
- `C:/Users/banga/Desktop/kiran_share_market/ledger_history_consumers.py` → `ledger_history_consumers.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_ledger_history_consumers.py` → `tests/test_ledger_history_consumers.py`
- `C:/Users/banga/Desktop/kiran_share_market/COLD_CONSUMER_ADAPTER_PACKAGE.md` → `COLD_CONSUMER_ADAPTER_PACKAGE.md`
- `C:/Users/banga/Desktop/kiran_share_market/staged_release_timeout_fix/release_verification.py` → `release_verification.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_release_timeout_recovery.py` → `tests/test_release_timeout_recovery.py`
- `C:/Users/banga/Desktop/kiran_share_market/RELEASE_TIMEOUT_REPAIR_PACKAGE.md` → `RELEASE_TIMEOUT_REPAIR_PACKAGE.md`
- `C:/Users/banga/Desktop/kiran_share_market/storage_write_guard.py` → `storage_write_guard.py`
- `C:/Users/banga/Desktop/kiran_share_market/storage_capacity_watch.py` → `storage_capacity_watch.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_storage_write_guard.py` → `tests/test_storage_write_guard.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_storage_capacity_watch.py` → `tests/test_storage_capacity_watch.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_storage_guard_sql.py` → `tests/test_storage_guard_sql.py`
- `C:/Users/banga/Desktop/kiran_share_market/STORAGE_GUARD_AND_WATCH_PACKAGE.md` → `STORAGE_GUARD_AND_WATCH_PACKAGE.md`
- `C:/Users/banga/Desktop/kiran_share_market/staged_historical_repository/production_repository.py` → `production_repository.py`
- `C:/Users/banga/Desktop/kiran_share_market/staged_historical_repository/equity_runtime_health.py` → `equity_runtime_health.py`
- `C:/Users/banga/Desktop/kiran_share_market/staged_historical_repository/package_release.py` → `package_release.py`
- `C:/Users/banga/Desktop/kiran_share_market/ledger_historical_views.py` → `ledger_historical_views.py`
- `C:/Users/banga/Desktop/kiran_share_market/ledger_historical_repository.py` → `ledger_historical_repository.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_ledger_historical_views.py` → `tests/test_ledger_historical_views.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_historical_repository_bridge.py` → `tests/test_historical_repository_bridge.py`
- `C:/Users/banga/Desktop/kiran_share_market/HISTORICAL_REPOSITORY_PACKAGE.md` → `HISTORICAL_REPOSITORY_PACKAGE.md`
- `C:/Users/banga/Desktop/kiran_share_market/ledger_delivery_proofs.py` → `ledger_delivery_proofs.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_ledger_delivery_proofs.py` → `tests/test_ledger_delivery_proofs.py`
- `C:/Users/banga/Desktop/kiran_share_market/LEDGER_DELIVERY_PROOFS_PACKAGE.md` → `LEDGER_DELIVERY_PROOFS_PACKAGE.md`
- `C:/Users/banga/Desktop/kiran_share_market/operational_receipt_history.py` → `operational_receipt_history.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_operational_receipt_history.py` → `tests/test_operational_receipt_history.py`
- `C:/Users/banga/Desktop/kiran_share_market/OPERATIONAL_RECEIPT_HISTORY_PACKAGE.md` → `OPERATIONAL_RECEIPT_HISTORY_PACKAGE.md`
- `C:/Users/banga/Desktop/kiran_share_market/finalization_intents.py` → `finalization_intents.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_finalization_intents.py` → `tests/test_finalization_intents.py`
- `C:/Users/banga/Desktop/kiran_share_market/FINALIZATION_INTENTS_PACKAGE.md` → `FINALIZATION_INTENTS_PACKAGE.md`

## Same clean-clone routine for each upload

Before copying, from the fresh clone ROOT:
```powershell
$sourceRoot = 'C:\Users\banga\Desktop\kiran_share_market'
$uploadBase = (git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or (git status --porcelain)) { throw 'Fresh clean clone required' }
$uploadGroup = 'capture' # use 'storage' for Upload 2
$reviewRoot = (Get-Location).Path
$manifest = Get-Content -LiteralPath (Join-Path $sourceRoot 'REMAINING_UPLOADS_2026-10-08.json') -Raw | ConvertFrom-Json
foreach ($entry in $manifest.groups.$uploadGroup) {
    $target = Join-Path $reviewRoot $entry.destination
    $parent = Split-Path -Parent $target
    if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -ErrorAction Stop | Out-Null }
    Copy-Item -LiteralPath (Join-Path $sourceRoot $entry.source) -Destination $target -ErrorAction Stop
}
```
This mechanical copy is ONLY the explicit list above, not a folder upload. Save
$uploadBase before copying. Do not commit until the checks below pass. Do not
rewrite the old STORAGE_MAIN_BASELINE_2026-10-07.json or ignore its blockers:
this new checker compares the exact group/hash against your actual Git base.
It is advisory packaging, not dependency/CI/deployment approval. The manifest is
a reviewed control file and cannot self-hash. Text hashes normalize CRLF only.

Upload 1 package-check line:
```powershell
.\.venv\Scripts\python.exe reviewed_upload_check.py --group capture --base "$uploadBase"
```
Upload 1 focused-test line:
```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_forward_capture_diagnostics.py tests/test_forward_drive_probe.py tests/test_forward_drive_folder_check.py tests/test_reviewed_upload_check.py tests/test_forward_nifty_producer.py tests/test_forward_nifty_schedule.py tests/test_forward_windows_credentials.py -p no:cacheprovider --basetemp "$env:TEMP/capture-upload-$([guid]::NewGuid().ToString('N'))"
```

### E/SQL harness setup before Upload 2 focused tests

Use the clean clone's existing pinned harness, as CI does:
```powershell
npm ci --prefix tests/sql-harness --ignore-scripts --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw 'SQL harness installation failed' }
$env:EQUITY_TEST_PGLITE_MODULE = (Resolve-Path 'tests/sql-harness/node_modules/@electric-sql/pglite').Path
```
No extension install or Supabase write. E's two SQL files are SELECT-only
inventories, NOT migrations; do not apply or execute hosted SQL for this upload.

Upload 2 package-check line:
```powershell
.\.venv\Scripts\python.exe reviewed_upload_check.py --group storage --base "$uploadBase"
```
Upload 2 focused-test line:
```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_storage_transition.py tests/test_ledger_history_stream.py tests/test_ledger_read_contract.py tests/test_ledger_staged_reader.py tests/test_cold_local_objects.py tests/test_ledger_archive_publication.py tests/test_daily_volume_retention_preview.py tests/test_ledger_history_consumers.py tests/test_release_timeout_recovery.py tests/test_storage_write_guard.py tests/test_storage_capacity_watch.py tests/test_storage_guard_sql.py tests/test_ledger_historical_views.py tests/test_historical_repository_bridge.py tests/test_ledger_delivery_proofs.py tests/test_operational_receipt_history.py tests/test_finalization_intents.py tests/test_ledger_cold_store.py tests/test_local_state_recovery.py tests/test_release_packaging.py -p no:cacheprovider --basetemp "$env:TEMP/storage-upload-$([guid]::NewGuid().ToString('N'))"
```

Expected checker: UPLOAD_FILES_VERIFIED_REQUIRES_TESTS_AND_CI, blockers empty.
Extra/missing/wrong hash/stale HEAD blocks; don't delete tests or override hashes.
Review complete changed paths, including tests/ and sql/. The checker may allow
an expected path already identical in base (e.g. shared progress file). Require
full quality/resilience/CodeQL on exact PR SHA, then post-merge main green before
Upload 2. Keep DASHBOARD_RELEASE_ENABLED=false and live expectations unchanged.
Storage I changes fingerprint members; recompute from the exact clean merged
tree later. Earlier reviewed A..J hash was
03ad7baa68ebaad1f64b1cd3c356455e1c18cb8f23f027652de303b64b4f8478.
Capture/upload checker files are not decision fingerprint members. Do not take a
hash from the dirty workspace or use it to update the currently held release.

## Today after market close

Validation: the final Upload1 focused command passed 136 tests; Upload2 focused
command passed 547 tests in the known clean-public candidate overlay with its
disposable SQL harness. Upload checker tests (11), strict typing/lint/import passed.
These are not a fresh full-suite result or verification of the owner's unspecified
B merge SHA. Exact clean-clone checks and full PR/post-merge CI remain required.
Upload2 also requires exact A/B and Upload1 predecessor file hashes; no silent
baseline bypass. The control manifest is advisory, not a signed release authority.

1. Let today's unchanged poll task finish its last slot. Let audit run at 15:40.
   Read actual counts/remote acknowledgment and LastTaskResult. Today is INCOMPLETE:
   missed earlier decisions stay missing; successful later polls do not backfill.
2. After audit and any producer finish, disable poll/audit. Confirm no capture
   process remains. Keep prepare Disabled. Preserve today's original code set,
   config, inputs, journal and receipts privately; never delete/rewrite them.
3. If audit lacks acknowledgment of the latest local observations, supervise ONE
   backup-only using the original frozen code, before replacement; stop on errors.
   A cumulative backup for the one earlier observation is not proof of later rows.
4. Only after Upload 1's CI/main green, back up installed code, copy the reviewed
   forward_nifty_job.py AND forward_capture_diagnostics.py into the installed
   capture code directory between sessions. Retain probe/folder checker as additive
   diagnostics. No storage/I/health/staging files go into the installed capture.
   Match hashes, check imports and preview. Old Oct 8 config must NOT run under
   new code. Keep original code available for Oct 8 restore/backup.
5. Do not promote release, change Streamlit expectations, migrate SQL or enable
   other collector/F&O modes because these PRs merged. Storage is still NOT
   commissioned (six-table recovery/atomic writer/custody/native tests remain).

## Tomorrow (9 October) before session

Keep automatic prepare Disabled: its NSE transport remains uncommissioned.
Follow NSE_OWNER_CLOSE_RUNBOOK.md with tomorrow's actual session date and official
previous-session close. For a normal 9 October session the expected close is
8 October; the code's verified calendar, not this sentence, is authoritative.
Download the unmodified CSV in the browser tomorrow morning and note the ACTUAL
completion timestamp with +05:30. Don't reuse today's download timestamp/file.
For that previous session, the established URL pattern is
https://nsearchives.nseindia.com/content/indices/ind_close_all_08102026.csv.
Unavailable/mismatched source blocks preparation; do not substitute a guessed close.

At 08:55–09:15 use the installed code/private root and owner-file preparation
preview, then confirmation exactly as the existing runbook. Require zero source
network calls, PASS clock, correct previous-close date and explicit owner-attested
(not independently verified) origin. Do not overwrite existing config or prepare
late. Under the newly installed code the fresh config has new source hashes.
If Upload 1/install can't finish safely, retain today's original reviewed code
and prepare a fresh tomorrow config under it; no urgency overrides source freeze.

Supervise tomorrow's 09:20:30 poll with tasks still Disabled; require exit 0,
REMOTE_VERIFIED and correct original receipt/count. Only then enable poll/audit.
There is no catch-up. Prepare stays Disabled until a separately commissioned
automatic source exists.

## Optional hidden poll window — after supervised acceptance, not today

The smallest option is the SAME virtual environment's pythonw.exe for the POLL
action only. Do not change principal, InteractiveToken, arguments, working folder,
triggers, IgnoreNew, no-catch-up settings or two-minute timeout. Do not run as SYSTEM
or store Windows passwords. Hidden means no console output, NOT independent alerts.

Owner: with poll Disabled and no process running, export its XML privately first;
verify .venv/Scripts/pythonw.exe exists in the installed code environment. In Task
Scheduler → poll → Properties → Actions → Edit, change ONLY Program/script from
that environment's python.exe to its pythonw.exe. Preserve ALL other fields.
Do NOT check Settings → Hidden expecting it to hide the console (that hides task
listing, not the process window). Do not re-run the original installer over it.

Prove one FUTURE slot by running the task in its normal permitted slot (not an
immediate out-of-slot catch-up), then check fresh scheduler/capture receipts,
remote verification and LastTaskResult 0. No receipt or nonzero result is failure;
restore the original action while Disabled and investigate. If pythonw.exe is
absent, keep python.exe; do not install launchers merely to make it quiet.
The diagnostic job writes failure receipts, but startup/import failures may have
no receipt. This optional setting is owner-only; no task definition changed here.
Also require that the supervised test actually shows no console: windowed-launcher
behavior can depend on the installed Python build. Keep the visible action if not
verified; do not weaken identity or task settings for cosmetic convenience.

References: [Python Windows windowed executables](https://docs.python.org/3/using/windows.html)
and [Task Scheduler Hidden property](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-hidden-settingstype-element).

