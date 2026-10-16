# Weekend follow-up: one new reviewed PR, not a re-upload of PR37

Exact pre-commit base: `a6e5be8484565be0f3d1669d6c3e004f692478e8`.
If main differs, stop for a reviewed reconciliation; do not edit this pin.
Old22-file manifest/checker remain historical and unchanged. This package does
not modify producer, coordinator, capsules, credentials, tasks, clock gates or
expectations. It can be uploaded outside capture; Monday does NOT depend on it.

## Exact paths and upload order

One group,13 files. Source root:
`C:\Users\banga\Desktop\kiran_share_market`.
Destination root: the owner's new clean public upload clone at the exact base.
Every source suffix below maps to the IDENTICAL destination suffix; no staged
replacement folders or hidden substitutions. M = tracked modification, A = new.

```text
M .gitignore                                      -> .gitignore
A forward_saved_audit_status.py                   -> forward_saved_audit_status.py
A tests/test_forward_saved_audit_status.py        -> tests/test_forward_saved_audit_status.py
M PROJECT_STATUS_LEDGER_2026-10-16.csv             -> PROJECT_STATUS_LEDGER_2026-10-16.csv
M FRIDAY_OWNER_STATUS_2026-10-16.md                -> FRIDAY_OWNER_STATUS_2026-10-16.md
M OPERATIONS_EVIDENCE_2026-10-16.json              -> OPERATIONS_EVIDENCE_2026-10-16.json
M WEEKEND_OWNER_PLAN_2026-10-16.md                 -> WEEKEND_OWNER_PLAN_2026-10-16.md
M FORWARD_OBSERVER_RUNBOOK_2026-10-16.md           -> FORWARD_OBSERVER_RUNBOOK_2026-10-16.md
A WEEKEND_COMMISSIONING_STATUS_2026-10-17.md       -> WEEKEND_COMMISSIONING_STATUS_2026-10-17.md
A weekend_followup_upload_check.py               -> weekend_followup_upload_check.py
A tests/test_weekend_followup_upload_check.py     -> tests/test_weekend_followup_upload_check.py
A WEEKEND_FOLLOWUP_UPLOAD_2026-10-17.md            -> WEEKEND_FOLLOWUP_UPLOAD_2026-10-17.md
A WEEKEND_FOLLOWUP_UPLOAD_2026-10-17.json          -> WEEKEND_FOLLOWUP_UPLOAD_2026-10-17.json
```

Use the established clean-clone routine, normal non-Administrator PowerShell.
Create one branch from the exact base, copy only these paths and stage all13.
The ledger CSV is already tracked after PR37. The new narrow ignore exception
also allows it in future clean staging; do not use broad `git add -f` for CSVs.
No secrets, cache, private backup or installed-capture folder belongs in the PR.

Block1: in the upload clone, set the reviewed test interpreter explicitly and
check version. This is not a bare launcher or a request to install Python:

```powershell
$reviewPython = 'C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
& $reviewPython -I -B -c "import sys; print(sys.version.split()[0]); assert sys.version_info[:3] == (3,13,9)"
```

Require3.13.9/exit0. Block2, after copying and staging exactly13 files:

```powershell
& $reviewPython -B weekend_followup_upload_check.py --base a6e5be8484565be0f3d1669d6c3e004f692478e8
```

Require `WEEKEND_PACKAGE_VERIFIED_REQUIRES_TESTS_AND_EXACT_COMMIT_CI` and failures[].
The checker validates LF-normalized bytes in index/worktree, unchanged prerequisite
bytes in base/index/worktree, exact A/M paths, modes and clean unstaged state. It
does not create a commit, run tests or assert commissioning. Hash failures name
path, expected, actual and staged hashes. Missing reads produce a redacted block.

Block3, focused tests (temporary test directories must be outside the code tree):

```powershell
$testScratch = Join-Path $env:TEMP ('weekend-followup-' + [guid]::NewGuid().ToString('N'))
& $reviewPython -B -m pytest -q tests/test_forward_saved_audit_status.py tests/test_weekend_followup_upload_check.py tests/test_project_status_ledger.py tests/test_operations_evidence_matrix.py tests/test_forward_live_status.py tests/test_forward_observer_upload_check.py tests/test_forward_daily_owner.py::test_disabled_setup_partial_registration_proofs --basetemp=$testScratch -p no:cacheprovider
```

Require exit0; record actual pass/skip counts and shell. Block4, lint/type checks:

```powershell
& $reviewPython -B -m pyflakes forward_saved_audit_status.py weekend_followup_upload_check.py tests/test_forward_saved_audit_status.py tests/test_weekend_followup_upload_check.py
$typeCache = Join-Path $env:TEMP ('mypy-weekend-' + [guid]::NewGuid().ToString('N'))
& $reviewPython -B -m mypy --strict --cache-dir=$typeCache forward_saved_audit_status.py weekend_followup_upload_check.py
```

Require both exit0. Never `--cache-dir=NUL`; a normal disposable cache directory
avoids the owner's reported mypy2.4.0 internal error. No cache cleanup required.

Block5, before committing, inspect only identity presence (not the values):

```powershell
$authorName = & git config --get user.name
$authorEmail = & git config --get user.email
[pscustomobject]@{name_present=(-not [string]::IsNullOrWhiteSpace([string]$authorName));email_present=(-not [string]::IsNullOrWhiteSpace([string]$authorEmail))} | ConvertTo-Json -Compress
git diff --cached --check
```

If identity is absent, set only this clone's `git config --local user.name` and
`user.email` to your own chosen identity privately; no invented values, global
changes or screenshots. Then repeat this read-only identity check, not Setup.
Commit message suggestion: `Add saved-audit inspection and refresh operations status`.
PR description, ONE plain line:
`Add bounded saved-audit inspection and refresh weekend commissioning records.`
No attribution lines or trailers in either. Exact-final-SHA hosted CI must be
green before owner-only merge. Run full offline CI on the PR; local focused
counts are not full-suite proof. After merge, use a fresh clean tools checkout.

## Read the saved Friday audit safely, only after this package is reviewed

This is optional and not a capture action. From the new clean tools checkout,
normal PowerShell, explicit interpreter, first preview:

```powershell
$reportRoot = Join-Path $env:LOCALAPPDATA 'KiranTrading\ForwardOps'
& $reviewPython -B forward_saved_audit_status.py --ops-root $reportRoot --session-date 2026-10-16
```

Require PREVIEW/reads0/writes0/task_queries0. Separate next block:

```powershell
& $reviewPython -B forward_saved_audit_status.py --ops-root $reportRoot --session-date 2026-10-16 --confirm-read-only
```

Reads only bounded exact-date operations report files, not capture state/journal,
prices, config, receipt markers, tasks or credentials. Links/reparse paths are
rejected by the shared reader. A missing/in-flight/malformed/conflicting report
is NOT success. Multiple candidates are shown, never silently latest-selected.
For Friday compare the claimed counts75/75/0 and generation
`17f7fbd62eafd8770ef2370becc5936a8fef16e4d6d71bee03f66d0ac08aabe9`.
`SAVED_AUDIT_REPORT_CLAIMS_VALIDATED` means internal report consistency only.
Even matching the owner-reported15:40 task result cannot cryptographically prove
scheduled origin: the old report has no task-run identifier. Do not rerun the
write-capable old audit to manufacture a report. No report found means preserve
state and report that absence; never reset a marker or recipe.

## Verification and technology choices

Builder: synthetic Windows/Linux checks are recorded in the final handoff, not
inferred from PR37. Independent checker reviews source separately. Owner's
reported PR37/drill/tool evidence is not independent private-byte verification.
New follow-up exact-SHA CI and actual saved report remain owner steps.

Focused rehearsal: Windows110passed/2skipped; offline Linux104passed/8skipped.
Windows skips two synthetic link cases exercised on Linux; Linux skips eight
WindowsPowerShell5.1 task-Setup fixtures exercised on Windows. Both platforms:
strict mypy passes for2 production files, pyflakes for4 Python files. This is not
a full-suite run. Manifest payload hashes are separately tested. Actual staged
acceptance at the owner's newbase and hosted exact-final-SHA CI remain pending.

Adopted: existing bounded stdlib reader, explicit version-pinned Python, native
task binding checks, reviewed manual coordinator. Adapted: report-only inspector
with slot-map conflict detection and historical-session support. Deferred: full
dummy-task failure route, guided native commissioning, independent custody and
restore. Rejected for capture: broad terminal plugins or autonomous service/
clock fixes. No extra account, paid service, runtime agent or connector needed.

Official references: [PostgreSQL17 service control](https://www.postgresql.org/docs/17/app-pg-ctl.html),
[mypy cache options](https://mypy.readthedocs.io/en/stable/command_line.html),
[Microsoft task registration](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/register-scheduledtask).
Server/service control is separate from using clients; no startup change is
performed or authorized by this package. Highest-leverage next build: an isolated
dummy-task failure/notification/acknowledgement drill, then authenticated independent
restore. Neither Friday coverage nor a synthetic popup clears those gaps.
