# One reviewed PR: isolated alert tooling + sealed-history guard + research evaluation

Exact clean pre-commit base:597a19d404cd1dc6c2734e48833c80e729d05d50.
PR38 and previous packages remain unchanged. If main differs, stop for reviewed
reconciliation; never loosen pins. This package is NOT needed for Monday manual
capture. Do not copy any file into a capture capsule or private state root.

## Exact source -> destination, one group15 files (13 additions,2 modifications)

Source root `C:\Users\banga\Desktop\kiran_share_market`;
destination root the owner's fresh clean public upload clone at the exact base.
Every suffix maps to the identical suffix. Only the history CLI and its existing
test file are modified; the other13 are new. No installed file is replaced.

```text
M download_nifty_history.py                      -> download_nifty_history.py
M tests/test_download_nifty_history.py            -> tests/test_download_nifty_history.py
isolated_alert_drill.py                         -> isolated_alert_drill.py
isolated_alert_task_drill.ps1                   -> isolated_alert_task_drill.ps1
tests/test_isolated_alert_drill.py              -> tests/test_isolated_alert_drill.py
research_session_inference.py                  -> research_session_inference.py
tests/test_research_session_inference.py        -> tests/test_research_session_inference.py
PROGRAMME_BUILD_AND_COMMISSION_2026-10-17.md     -> PROGRAMME_BUILD_AND_COMMISSION_2026-10-17.md
RESEARCH_METHODS_AND_DELIVERY_2026-10-17.md       -> RESEARCH_METHODS_AND_DELIVERY_2026-10-17.md
ISOLATED_ALERT_DRILL_RUNBOOK_2026-10-17.md        -> ISOLATED_ALERT_DRILL_RUNBOOK_2026-10-17.md
programme_next_upload_check.py                 -> programme_next_upload_check.py
tests/test_programme_next_upload_check.py       -> tests/test_programme_next_upload_check.py
PROGRAMME_NEXT_UPLOAD_2026-10-17.md              -> PROGRAMME_NEXT_UPLOAD_2026-10-17.md
PROGRAMME_VERIFICATION_2026-10-17.json           -> PROGRAMME_VERIFICATION_2026-10-17.json
PROGRAMME_NEXT_UPLOAD_2026-10-17.json            -> PROGRAMME_NEXT_UPLOAD_2026-10-17.json
```

All other paths above are A. One branch/one commit/one PR, owner-only merge. No staged G/I substitutions or
special export step. No secret, private CSV, cache, captured snapshot or backup.
Use existing clean-clone routine; stage exactly the15 paths above before checking.
Every owner block below runs separately in normal non-Administrator PowerShell.

### Block1: explicit interpreter and version

```powershell
$ErrorActionPreference='Stop'
$reviewPython='C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
& $reviewPython -I -B -c "import sys; print(sys.version.split()[0]); assert sys.version_info[:3] == (3,13,9)"
if ($LASTEXITCODE -ne 0) {throw 'PINNED_PYTHON_REQUIRED'}
```

### Block2: pre-commit staged checker, after copying/staging15 paths

```powershell
$ErrorActionPreference='Stop'
& $reviewPython -B programme_next_upload_check.py --base 597a19d404cd1dc6c2734e48833c80e729d05d50
if ($LASTEXITCODE -ne 0) {throw 'STOP_REVIEW_PACKAGE'}
```

Require PROGRAMME_PACKAGE_VERIFIED_REQUIRES_TESTS_AND_EXACT_COMMIT_CI and failures[].
The checker validates clean exact-base HEAD,13 A/2 M paths, staged/worktree hashes,
stage-zero regular modes, unchanged four source prerequisites at base/index/worktree,
manifest duplicate-key rejection, bounded non-link reads, no unstaged/untracked
extras. Manifest self-entry is null; every other file has a reviewed LF-normalized
SHA256. It does not run capture, tasks, services, credentials or hosted operations.
The two modified files have separate old-base hash pins; they are not treated as
unchanged prerequisites, and an upstream mismatch stops with path/expected/actual.
It is pre-commit only; do not expect it to pass against the later PR commit HEAD.

### Block3: focused tests; temporary state outside source tree

```powershell
$ErrorActionPreference='Stop'
$testScratch=Join-Path $env:TEMP ('programme-next-'+[guid]::NewGuid().ToString('N'))
& $reviewPython -B -m pytest -q tests/test_isolated_alert_drill.py tests/test_research_session_inference.py tests/test_programme_next_upload_check.py tests/test_forward_session_ops.py tests/test_download_nifty_history.py --basetemp=$testScratch -p no:cacheprovider -r s
if ($LASTEXITCODE -ne 0) {throw 'STOP_REVIEW_FOCUSED_TESTS'}
```

The native controller/cleanup blocks are exercised with fake Scheduler commands;
tests do not register/enable tasks, show real popups or read installed capture.
Windows/Linux results and skips belong in PROGRAMME_VERIFICATION_2026-10-17.json;
no count here substitutes for full CI or a later owner native drill.
Final focused result: Windows158passed/1skipped; Linux153passed/6skipped. The
Windows link-privilege skip is exercised on Linux; Linux skips six absent
WindowsPowerShell runtime cases exercised on Windows. Separately, existing
futures-history/readiness consumers passed42 tests on each platform. These are
not a full-repository test run or exact-final-SHA hosted CI.

### Block4: lint and strict typing with real temporary cache

```powershell
$ErrorActionPreference='Stop'
& $reviewPython -B -m pyflakes isolated_alert_drill.py research_session_inference.py programme_next_upload_check.py tests/test_isolated_alert_drill.py tests/test_research_session_inference.py tests/test_programme_next_upload_check.py download_nifty_history.py tests/test_download_nifty_history.py
if ($LASTEXITCODE -ne 0) {throw 'STOP_REVIEW_LINT'}
$typeCache=Join-Path $env:TEMP ('mypy-programme-'+[guid]::NewGuid().ToString('N'))
& $reviewPython -B -m mypy --strict --cache-dir=$typeCache isolated_alert_drill.py research_session_inference.py programme_next_upload_check.py
if ($LASTEXITCODE -ne 0) {throw 'STOP_REVIEW_TYPES'}
```

Never use NUL for the cache or a bare Python launcher. No pip install required.
Strict typing scope is the3 new production Python modules, not a claim that the
existing legacy untyped downloader is fully typed. Its CLI guard is exercised by
the history regression tests; all8 listed Python files receive lint checks.

### Block5: identity presence and whitespace, then owner commit/PR

```powershell
$ErrorActionPreference='Stop'
$authorName=& git config --get user.name
$authorEmail=& git config --get user.email
$identityPresent=(-not [string]::IsNullOrWhiteSpace([string]$authorName)) -and (-not [string]::IsNullOrWhiteSpace([string]$authorEmail))
[pscustomobject]@{identity_present=$identityPresent}|ConvertTo-Json -Compress
if (-not $identityPresent) {throw 'SET_OWNER_CHOSEN_REPO_LOCAL_IDENTITY_PRIVATELY'}
git diff --cached --check
if ($LASTEXITCODE -ne 0) {throw 'STOP_REVIEW_WHITESPACE'}
```

If identity absent, set only this clone's user.name/user.email to your own chosen
values privately; no global change and no invented values. Commit suggestion:
`Add isolated alert drill and sealed research guards`.
PR description ONE plain line:
`Add isolated alert-route acceptance, sealed-history guards and research evaluation.`
No attribution or trailers in either. Full hosted CI must be green on the exact
final SHA; owner alone merges. New tools checkout only after merge, never change
the currently installed/dated capture. No workflow is enabled by this upload.

## After merge, separate acceptance from upload

Read ISOLATED_ALERT_DRILL_RUNBOOK_2026-10-17.md. Only its explicit owner steps may
register, once-enable/start and re-disable the new no-trigger dummy task. No
production task or failed poll is used. Default preview stays inert. Native
acceptance is pending until the owner sees the labelled synthetic message and
provides the explicit acknowledgement after a successful route/disabled witness.

ML/backtest evaluation API is a pure library, not app-integrated or activated.
Its unadmitted method outputs cannot become real-data labels, predictions,
performance claims or promotion. Required future implementations and all open
items are in PROGRAMME_BUILD_AND_COMMISSION_2026-10-17.md and the research-methods
document; no owner prerequisite is an excuse to drop those engineering stages.
