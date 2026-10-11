# Forward capture Drive recovery — 8 October

## Decision and limits

Keep all three capture tasks Disabled while diagnosing. Preserve the existing
config, input, journal and failure receipt. Do not rerun the missed 09:20 slot,
edit observation times, backfill decisions, delete state or rotate working GitHub
archive credentials speculatively. Later polls cannot recover earlier decisions.

The owner's one observation/context row is consistent with a committed poll,
but the old generic failure receipt cannot identify the failing operation.
Folder inspection, Google refresh, publication/verification, receipt writing or
cleanup are possible. No receipt means remote acknowledgment is unproved, not
that no remote object exists. The code validates a bundle after journal writes,
so even a local bundle-validation failure is possible before Drive inspection.
The new `local_poll_committed` flag is true only when record_poll returned,
false before that operation (including backup-only), and null if that operation
failed with a potentially partial commit. Null must not be read as no stored data.

This package improves diagnostics only. It DOES NOT implement a commissioned
local-only collector, change scheduling, loosen timing/clock/license/scope gates,
change research rules or initialize storage modules. Local persistence is not an
independent backup. Automatic local-only collection would need an explicit policy,
byte/free-disk bound, pending-backup tracking and alerts first; none is claimed.

## Separate complete upload package

Do not mix this into the thirteen pending permanent-storage groups. It can be
reviewed/uploaded first against current public main; it has no dependency on them.

- Root modified: `forward_nifty_job.py` — fixed stage/category codes and truthful
  local-commit/remote-verification/receipt-write flags in failure output/receipts;
  cleanup cannot mask a primary error. Existing exit codes and capture guards stay.
- Root new: `forward_drive_probe.py` — offline preview; explicit `--check` reads
  just the two Drive Credential Manager names and checks folder access. It does
  not upload, capture, write files or read the Upstox token. OAuth refresh may
  make a Google token POST; folder inspection uses Drive GET. It proves neither
  archive verification nor token equality with GitHub.
- Root new: `forward_capture_diagnostics.py` — shared fixed-code classifier and
  cleanup helper; lets the probe run beside the old frozen job without importing
  or replacing it.
- Tests new: `tests/test_forward_capture_diagnostics.py` and
  `tests/test_forward_drive_probe.py`.
- Root new: this runbook, `FORWARD_DRIVE_RECOVERY_2026-10-08.md`.
- Root modified: `AUTOMATION_PROGRESS.md` — continuity only. It also describes
  pending storage work; those referenced files are not activated by uploading it.

Use a clean current-main clone, these exact seven paths, a PR and green checks.
Never upload credential JSON, state, cache, staging directories or the whole
working folder. No dashboard fingerprint member changes here; do not change
Streamlit expectations or release hold. Full CI still runs before merge.

Local tests (from the review clone, with its existing Python environment):

Agent final focused result: 108 passed in 39.08s (no skips), strict mypy and
pyflakes clean on all five Python files, three module imports and offline probe
preview passed. Full suite was not rerun for this package: require full PR CI.
Synthetic post-commit failure is explicitly tested; null commit outcome preserves
uncertainty. No credentials, actual state or hosted resource was accessed.

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_forward_capture_diagnostics.py tests/test_forward_drive_probe.py tests/test_forward_nifty_producer.py tests/test_forward_nifty_schedule.py tests/test_forward_windows_credentials.py -p no:cacheprovider
.\.venv\Scripts\python.exe -m mypy --strict --follow-imports=silent forward_nifty_job.py forward_drive_probe.py forward_capture_diagnostics.py tests/test_forward_capture_diagnostics.py tests/test_forward_drive_probe.py
.\.venv\Scripts\python.exe -m pyflakes forward_nifty_job.py forward_drive_probe.py forward_capture_diagnostics.py tests/test_forward_capture_diagnostics.py tests/test_forward_drive_probe.py
```

## Owner steps: diagnose before changing credentials

1. Confirm prepare/poll/audit remain Disabled and no capture process is running.
   In Task Scheduler, inspect the poll task's Actions: identify its actual code
   directory, interpreter and `--root` private state directory. Do not assume
   the project folder or print any credential entry.
2. Privately back up the installed **code files only**, separately from state.
   For TODAY, copy ONLY `forward_drive_probe.py` and
   `forward_capture_diagnostics.py` into the installed `kiran_forward_20261007`
   code directory. Do not replace the pinned job, health, producer, scheduler,
   credentials module or any state/config file. Compare the two source/install
   SHA256 file hashes locally. The standalone probe is not imported by the old
   frozen capture closure. The agent has not done this installation.
3. In PowerShell, change directory to that installed code folder and use its
   existing interpreter (not the project environment):

```powershell
.\.venv\Scripts\python.exe forward_drive_probe.py
.\.venv\Scripts\python.exe forward_drive_probe.py --check
```

The first result must be PREVIEW with zero reads/network/writes. Run the second
once: it uses the same Windows user credential store as the scheduled capture.
Report only status, stage and category. No raw exceptions, tokens, provider bodies,
folder IDs or credential screenshots. Folder check success is not backup success.

Interpretation:

- `PRIVATE_CREDENTIAL_READ`: confirm the task/terminal runs as the setup user and
  the two named entries exist. Do not dump their values.
- `INVALID_OAUTH_CONFIGURATION` / `INVALID_DRIVE_FOLDER`: correct the private
  configuration through the existing credential setup tool, not environment hacks.
- `DRIVE_AUTH_REFRESH_FAILED`: refresh rejected/failed. It does NOT prove seven-day
  expiry; inspect OAuth client/account/audience status privately. Google documents
  External/Testing tokens with Drive scope expiring after seven days. Production
  status does not make tokens permanent. If reauthorization is needed, use the
  existing reviewed consent flow with the same client/account and narrow drive.file
  scope. Follow Google's verification requirements; don't widen scopes.
- `DRIVE_HTTP_401`, `403`, `404`, or `DRIVE_FOLDER_NOT_WRITABLE`: verify the original
  folder is accessible by this OAuth client/account and writable. With drive.file,
  browser access by the user alone does not prove app access. Do not make it public.
- `TRANSPORT_TIMEOUT`, `TRANSPORT_FAILED`, `TLS_FAILED`: investigate connectivity,
  clock/certificate/proxy without disabling certificate verification or adding
  unattended retries. The folder check may take time due to existing read retries.
- `UNCLASSIFIED_FAILURE`: report the stage/category; do not expose the original
  exception. Further targeted instrumentation may be needed.

If replacing credentials, keep the original folder choice deliberate: the consent
tool creates a new folder. Store the new OAuth JSON from a private outside-repo
file using `forward_windows_credentials.py --store --drive-oauth-file <private path>`
at its hidden prompts, preserving the other verified values and original folder
when access is verified. This tool rewrites all five entries: don't guess values.
Do not replace GitHub secrets unless separately established necessary. No agent
credential read or OAuth/network check was performed for this package.

Official reference: [Google OAuth token expiration](https://developers.google.com/identity/protocols/oauth2#expiration).

## One supervised backup of existing evidence

After the folder check succeeds, use **backup-only**, not a capture retry. This
does write/create remote backup objects and a local receipt, so it is an explicit
owner recovery action. Keep tasks disabled/no other producer active.

In the installed code directory, set the private root to the actual poll task
`--root` path (a path only, never a secret). Then execute this wrapper. It loads
the existing credential context in memory, restores the environment afterward,
and catches setup failures without a traceback. It does not fetch market data.

```powershell
$env:FORWARD_RECOVERY_ROOT = 'REPLACE WITH ACTUAL PRIVATE --root DIRECTORY'
@'
from datetime import date
from pathlib import Path
import os
from forward_nifty_schedule import credential_environment, session_paths
from forward_nifty_job import main
try:
    config, state = session_paths(Path(os.environ['FORWARD_RECOVERY_ROOT']), date(2026, 10, 8))
    with credential_environment():
        result = main(['--config', str(config), '--state', str(state), '--backup-only'])
except Exception:
    print('BLOCKED: BACKUP_SETUP_FAILED')
    result = 2
raise SystemExit(result)
'@ | .\.venv\Scripts\python.exe -
Remove-Item Env:FORWARD_RECOVERY_ROOT
```

Expected: exit 0 / REMOTE_VERIFIED / BACKUP_ONLY, recorded_decisions 1 if no
additional polls occurred. Both data and manifest must download-verify before
the receipt is written. A passed backup does not independently authenticate the
owner-sourced previous close. No earlier missing decision becomes observed.

Today's original job still gives a generic backup failure; do not replace it to
obtain better diagnostics mid-session. Preserve its output and report the probe
result instead. The prepared config pins the original job and transitive source
hashes: changing the job would block today's backup/poll with config mismatch.
Never edit/re-freeze that historical config or relax the hash comparison.

For a FUTURE session, install the reviewed new job along with the helper only
between sessions, then do fresh pre-open preparation. The new job does not permit
old configs against new sources. Preserve the original code set for old backups.
On a future instrumented failure, report only stage/category/three flags. Remote uncertainty
is not permission to delete or blindly re-upload. `DUPLICATE_DRIVE_BATCH_REVIEW_REQUIRED`
or a verification mismatch needs review, not retries. `remote_verified=true` with
`receipt_written=false` points at receipt persistence; check local space/permissions.
A cleanup failure may have a valid receipt already: don't assume backup failed.

## Resume criterion

Only after backup succeeds, run one supervised **future** poll using the existing
scheduler `--mode poll --confirm-run`, within its unchanged slot/lateness window
and same prepared day. Never run directly to bypass the scheduler window. Require
REMOTE_VERIFIED, exit 0 and correct observation/receipt counts before enabling
recurrence. If the market has closed, stop: retain today's incomplete evidence and
prepare the next session normally. Perform the post-session audit; today's missed
slots remain missing. No automatic task enablement is part of this package.
