# PC capture folder selection — read-only diagnosis before correction

## Judgment

DRIVE_HTTP_404 at folder GET is consistent with a wrong ID, a missing/trashed
folder, a different account, or drive.file app-specific visibility. It is not
proof of token expiration. The transport ignores saved access tokens and refreshes
its validated authorized_user credential; a Drive 404 strongly suggests refresh
reached the API, but does not prove every future refresh will work.

The service-account writer on A proves only a folder permission. Files owned by
the user do not identify the uploading OAuth client. The PC code currently accepts
authorized_user OAuth only; do not put a service-account key in that entry.
Connector-visible inventory is from another identity/scope and excludes Trash;
absence there is not a complete proof that no object was ever uploaded.

Preferred smallest correction: use the current PC OAuth credential and a candidate
it can actually access. Prefer private B if its check succeeds, separating capture
from the working archive. If B fails but A passes, use A with the same PC OAuth.
No reauthorization is needed just because the saved folder is wrong. Do not use
C unless intentionally authorized to this app; its literal name is not an ID.
Do not delete any of A/B/C or change GitHub, permissions, scope or sharing now.

Google references:
[drive.file scope](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)
and [Drive API errors](https://developers.google.com/workspace/drive/api/guides/handle-errors).

## Complete separate upload group (four paths)

- New root: `forward_drive_folder_check.py` — hidden local equality comparison,
  or explicit read-only access test of a hidden candidate using current PC OAuth.
- New tests: `tests/test_forward_drive_folder_check.py`.
- New root: `FORWARD_DRIVE_FOLDER_SELECTION.md` (this file).
- Modified root: `AUTOMATION_PROGRESS.md` (continuity only).

Dependencies: previously reviewed `forward_capture_diagnostics.py`, unchanged
`drive_archive.py` and `forward_windows_credentials.py`. If the preceding seven-file
capture package is not on main, upload/review it first, or include that exact
reviewed dependency group in the PR. Do not copy unfinished storage drafts.
No dashboard fingerprint member changes. Full PR CI remains required.

Focused test command from the review clone:

Final local result: 39 tests passed, strict typing/lint/import/preview passed.
The three wrapper cases use synthetic mocked vault/Drive APIs only. No actual
vault reads, credential writes, network checks or installed-folder changes were
performed. Full suite was not rerun; require full PR CI before upload/merge.

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_forward_drive_folder_check.py tests/test_forward_drive_probe.py tests/test_forward_capture_diagnostics.py -p no:cacheprovider
.\.venv\Scripts\python.exe -m mypy --strict --follow-imports=silent forward_drive_folder_check.py tests/test_forward_drive_folder_check.py
.\.venv\Scripts\python.exe -m pyflakes forward_drive_folder_check.py tests/test_forward_drive_folder_check.py
```

## Owner: compare the saved entry without displaying it

Tasks remain Disabled. In each candidate's browser URL, copy only the ID after
`/folders/` and before any query string. Distinguish A/B by the stated creation
dates, not their identical names. IDs are entered at hidden prompts, never argv,
chat, screenshots or command history. Nothing is written by these checks.

Copy ONLY `forward_drive_folder_check.py` beside the already installed probe and
helper in the capture code folder. Its addition is not imported by the original
frozen producer/job and does not invalidate today's config. Do not replace any
frozen runtime file, edit config or install the changed job mid-session.

From that folder, as the same Windows user used for capture:

```powershell
.\.venv\Scripts\python.exe forward_drive_folder_check.py
.\.venv\Scripts\python.exe forward_drive_folder_check.py --compare
```

Preview must report zero reads/network/writes. Comparison prompts for A, B, C IDs
and then reads ONLY `OPTION_CAPTURE_DRIVE_FOLDER_ID` locally. It prints just
`stored_folder_match: A`, B, C or NONE. It does not read OAuth, call Drive or change
the entry. Duplicate/malformed candidates block before any credential read. NONE
means no equality with the supplied IDs; it does not prove which other folder it is.

## Owner: prove access using PC OAuth, not connector identity

Run the following once for B. If it fails, run once for A:

```powershell
.\.venv\Scripts\python.exe forward_drive_folder_check.py --check-candidate B
.\.venv\Scripts\python.exe forward_drive_folder_check.py --check-candidate A
```

Each prompts for that candidate's ID and reads ONLY `DRIVE_OAUTH_TOKEN_JSON`.
It does not modify the saved folder or capture evidence, upload, list data or
change permissions. OAuth refresh can POST to Google's token endpoint; the folder
inspection is GET. A pass checks folder type/not-trash/canAddChildren using that
actual credential. It is not independent ACL/privacy or backup verification.
Confirm selected folder has only expected private user/service-account ACLs in
Drive; no public/domain/link sharing. Never make it public to resolve 404.

Report only comparison label and each status/stage/category. Keep token values,
account/client identifiers, folder IDs and exception bodies private.

## Owner: change only the saved folder after a candidate passes

The existing `--store` tool rewrites all five credentials; it is unnecessary to
re-enter the working Upstox token/expiry/license and Drive OAuth for a folder-only
correction. The following reviewed owner wrapper uses the **existing module APIs**
to verify the chosen candidate again and update ONLY its folder entry. It reads
OAuth in memory; no token is printed, exported, regenerated or copied to GitHub.
This is an explicit owner local setting change, not performed by the agent.

Run in the installed capture folder after a candidate pass and private ACL review:

```powershell
@'
import getpass
import json
from drive_archive import DriveArchive, credentials
from forward_capture_diagnostics import close_drive
from forward_drive_folder_check import folder_id
from forward_windows_credentials import read_secret, write_secret
try:
    selected = folder_id(getpass.getpass('Verified candidate folder ID (hidden): '))
    oauth = credentials(json.loads(read_secret('DRIVE_OAUTH_TOKEN_JSON')))
    drive = DriveArchive(oauth, selected)
    try:
        drive.check_folder()
    finally:
        close_drive(drive)
    write_secret('OPTION_CAPTURE_DRIVE_FOLDER_ID', selected)
    if read_secret('OPTION_CAPTURE_DRIVE_FOLDER_ID') != selected:
        raise ValueError('readback')
    print('PC_FOLDER_UPDATED_VERIFIED')
    result = 0
except Exception:
    print('BLOCKED: PC_FOLDER_UPDATE_FAILED_RECHECK_CURRENT_ENTRY')
    result = 2
raise SystemExit(result)
'@ | .\.venv\Scripts\python.exe -
```

On failure, the entry may or may not have changed; do not assume rollback. Stop,
repeat the local comparison/probe and report fixed output only. No blind retries.
If it succeeds, run the original `forward_drive_probe.py --check`, then the
existing supervised backup-only instructions in `FORWARD_DRIVE_RECOVERY_2026-10-08.md`.
Require download-verified data+manifest and a receipt before a future supervised
poll/recurrence. Today's old frozen job stays installed. Never backfill missed slots.

If neither B nor A is accessible: leave the entry unchanged. Check Trash and confirm
the PC account/client provenance privately. Use the existing Desktop OAuth flow
with the intended client/account and drive.file only to establish a dedicated
folder if needed. That flow creates a new folder; don't treat it as A or B. Store
the new authorized_user credential and matching created folder through the existing
private-file setup, then probe and backup. Reusing GitHub's credential is considered
only after its type/provenance is established from an owner's private original;
GitHub secret names and A's ACL cannot establish it. GitHub secret values are not
retrievable as a safe export. Do not transplant service-account keys into the PC
OAuth schema or broaden scopes to hide a mismatch.
