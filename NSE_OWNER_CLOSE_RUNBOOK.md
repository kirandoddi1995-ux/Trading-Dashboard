# Explicit owner-file previous close: supervised next-session commissioning

## Decision and evidence

The owner Oct 7 offline check passed: 17,530 bytes, exact Oct 6 close date,
SHA256 aa9e81cd713d8a949700009b131c87c2e5752d59e01797d39989799d6256bbf7.
This establishes structure/date/hash, not independent source authenticity or
retrieval time. No agent read the private CSV. Python transport remains unresolved;
do not keep probing the CDN, spoof cookies/browser fingerprints, weaken TLS or
switch to an unverified close source.

Choose an explicit OWNER_ATTESTED file mode for the next supervised day, not an
automatic fallback. The existing automated NSE mode remains unchanged. The owner
must personally download the expected official file through the normal browser
on the target session morning and attest that it came directly from that exact
URL, is unmodified, and record the actual observed completion timestamp with its
timezone. If that cannot honestly be confirmed, do not prepare capture.

The recipe is nifty-forward-v3-owner-file, with distinct
nse-previous-close-owner-file-v1 provenance. It retains exact bytes/hash, actual
tool file-read time, owner-asserted download time and fixed source URL. Origin is
labelled OWNER_ATTESTED_NOT_INDEPENDENTLY_VERIFIED; publication_time remains null.
No file modification/import timestamp is relabelled as network retrieval.
Manual mode never approves trading or changes fills/signal rules.

## Install safely, while all capture tasks remain disabled

1. Preserve private copies of the existing installed code and all historical
   config/state/receipts; do not delete or overwrite recorded evidence.
2. In the isolated C:\Users\banga\Desktop\kiran_forward_20261007 code folder,
   owner installs ONLY these complete root files from this reviewed package:
   nse_owner_close.py, nifty_previous_close.py, forward_nifty_producer.py,
   forward_nifty_schedule.py.
   Do not copy the workspace's unfinished storage modules or staged folder.
   Other existing installed dependencies are retained. The previous-close root
   is aligned to the already-reviewed transport repair, not a source/TLS change.
3. Do not run old recipes under new code: capture's transitive environment hashes
   intentionally change. Old sessions remain reproducible with their old reviewed
   code; create a new recipe for the next session, never rewrite an old one.
4. Keep the automatic prepare task Disabled while this mode is in use. The poll
   and audit task definitions need no change. They are enabled only after the
   supervised preparation/first poll has passed. The agent changed no installed
   task/folder/settings/secrets.

## Oct 8 owner preparation (before 09:15 IST)

Oct 8 requires Oct 7's close, NOT the Oct 6 file just checked. On a later date,
use the reviewed calendar's previous session; holidays/weekends/special sessions
are not inferred from a filename or returned candles. Unknown calendars block.
Keep the licence acknowledgement in the existing same-user private credential
store. Existing token expiry, producer lock, clock, poll timing and capture guards
remain required. Never paste a token or credential into these commands.

1. Around 08:55, use the normal browser to download
   `https://nsearchives.nseindia.com/content/indices/ind_close_all_07102026.csv`.
   Keep it privately outside code/repo, without editing it. Personally note its
   actual completion time, e.g. an ISO timestamp with +05:30; do not copy a guessed
   example timestamp. This mode requires a download on the target session day.
2. Use the installed isolated folder and the existing private state root from
   your task's reviewed arguments. The state root is not the code folder. Preview:

```powershell
Set-Location C:\Users\banga\Desktop\kiran_forward_20261007
$forwardPrivateState = Read-Host 'Existing private Forward state root'
$ownerCloseFile = Read-Host 'Private path to this morning official CSV'
$ownerDownloadAt = Read-Host 'Actual observed download completion, ISO timestamp with timezone'
.venv/Scripts/python.exe forward_nifty_schedule.py --root "$forwardPrivateState" --mode prepare --owner-close-file "$ownerCloseFile" --owner-download-at "$ownerDownloadAt" --attest-nse-source
```

Preview must show PREVIEW, zero network/credential reads, and write nothing. Add
the attestation flag only if its statement is true; it does not establish external
authenticity. Once reviewed, confirm the SAME command once:

```powershell
.venv/Scripts/python.exe forward_nifty_schedule.py --root "$forwardPrivateState" --mode prepare --owner-close-file "$ownerCloseFile" --owner-download-at "$ownerDownloadAt" --attest-nse-source --confirm-run
```

Require CONFIG_PREPARED_OWNER_FILE, previous_close_date 2026-10-07,
source_network_calls 0, clock_check PASS, and the explicit owner-attested origin.
There IS a clock network check; source_network_calls 0 does not mean the confirmed
command is entirely offline. Only recipe/failure receipts are written privately;
no close price, CSV body, private path or secret appears in output. The existing
licence check runs before preparation. Source errors never trigger an NSE retry.
At/after 09:15, false/missing attestation, naive/future/previous-day asserted times,
invalid clock, bad CSV or an existing recipe: STOP. Do not overwrite or prepare late.

3. At the first normal five-minute slot (e.g. 09:20:30), supervise one poll:

```powershell
.venv/Scripts/python.exe forward_nifty_schedule.py --root "$forwardPrivateState" --mode poll --confirm-run
```

Inspect its private receipt, original-input/journal identity and remote Drive
acknowledgement using the existing capture runbook. POLL_COMPLETED alone does not
mean every decision is available or all 75 polls were captured. Only then enable
poll/audit tasks in Task Scheduler for their remaining normal slots. No catch-up
for missed slots. At 15:40 inspect audit and private backup verification; gaps
and warmup/unavailable decisions stay visible.

This supervised manual download/preparation is still daily owner work. It is not
an unattended-source fix. After successful polls, investigate a documented permitted
automated source/transport on an independently supervised host; compare exact dates/
values against official files before changing provenance. Do not secretly make
the task import whatever file happens to be in Downloads.

## Review/upload grouping and local validation

Capture root files: nse_owner_close.py, nifty_previous_close.py, forward_nifty_producer.py,
forward_nifty_schedule.py. Test: tests/test_nse_owner_close.py.
Local staged_capture_repair/forward_nifty_schedule.py is aligned too; it is not an
installed module or a replacement for uploading the ROOT scheduler. The new parity
test is conditional when that optional local staging folder is absent on GitHub.
This distinction matters: existing staged tests previously hid stale local root
scheduler AND previous-close files. Final checks also simulate staging absent.
Storage checklist root/test/docs can be reviewed separately; neither package
requires hosted SQL writes or dashboard release promotion.

From the development root:

```powershell
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_nse_owner_close.py tests/test_storage_commissioning.py tests/test_nifty_previous_close.py tests/test_forward_nifty_schedule.py tests/test_forward_nifty_producer.py tests/test_staged_capture_repair.py --basetemp "$env:TEMP/owner-source-$([guid]::NewGuid().ToString('N'))" --tb=short
```

Final validation: focused checks 167 passed; root-only GitHub-layout rehearsal
93 passed; full suite 2,363 passed, 4 skipped and 2 subtests passed. Pyflakes,
strict type checks on six root modules and changed-module imports pass. Self-review
caught and fixed the stale root modules and the missing upload dependency.
Details are in AUTOMATION_PROGRESS.md; require CI for the uploaded exact SHA too.
The equity release-fingerprint manifest is unchanged; no Streamlit expectation
update is needed for this package. Capture environment/source hashes DO change.
