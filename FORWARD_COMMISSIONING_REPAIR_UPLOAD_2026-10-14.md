# Exact inactive commissioning repair upload — 14 October 2026

Base: `161ffe082343c20cf118950fdb49e5315bb54e7f` (verified in the clean clone
`C:/Users/banga/AppData/Local/Temp/commissioning-161ffe0`). Final pins must be
generated after main/Dewey freeze their public source bytes; never hash held
workspace prerequisites instead of this actual public baseline.

Copy/stage exactly these ten destinations in a clean rehearsal clone:

Source prefix for EVERY path is `C:/Users/banga/Desktop/kiran_share_market/`.
Destination prefix is `C:/Users/banga/AppData/Local/Temp/commissioning-161ffe0/`.
Only the listed source suffix maps to the identical destination suffix; do not
copy a whole workspace, installed capsule or held prerequisite draft.

- `forward_session_ops.py`
- `tests/test_forward_session_ops.py`
- `forward_ops_host.py`
- `forward_morning_readiness.py`
- `tests/test_forward_morning_readiness.py`
- `forward_commissioning_upload_check.py`
- `tests/test_forward_commissioning_upload_check.py`
- `FORWARD_COMMISSIONING_REPAIR_2026-10-14.md`
- `FORWARD_COMMISSIONING_REPAIR_UPLOAD_2026-10-14.md`
- `FORWARD_COMMISSIONING_REPAIR_UPLOAD_2026-10-14.json`

No capture job, app, storage reader, recipe, installed capsule, task, private file,
progress file or source prerequisite replacement belongs to this package.

Control JSON must be strictly under 128 KiB and have exactly `version`, `group`,
`base`, `files`, `prerequisites`, `seeds`, `extra_pins`. Constants/API are exported
by `forward_commissioning_upload_check.py`: version `forward-commissioning-repair-v1`,
group `forward_commissioning_repair`, base above, exact `FILES`, `SEEDS`,
`EXTRA_PINS`, `verify(root, changed)`, `index_matches(root, names)`, `main(argv)`.
Pins use `{destination, sha256_lf}` with CRLF normalized to LF; only this control
JSON has a null self-hash. Prerequisites are exactly
`(guarded.guarded_members(root, list(SEEDS)) | set(EXTRA_PINS)) - set(FILES)`.
They include the existing guarded/common checkers and full transitive public
operations dependencies. Unsupported computed/aliased/relative imports, omissions,
duplicate keys/types, links, untracked/unstaged paths and staged-byte differences
all block. Every prerequisite and the new control is independently index-bound.

Capture the exact public base before copying. Stage ONLY `FILES`. Main supplies
the absolute path `$testPython` to its existing external test venv interpreter
and `$publicPgliteModule` to the already available public package module path;
neither is an installation request. Run from the candidate clone:

```powershell
$ErrorActionPreference = 'Stop'
if ($testPython -notmatch '^[A-Za-z]:[\\/]' -or -not (Test-Path -LiteralPath $testPython -PathType Leaf)) { throw 'STOP: absolute existing test interpreter required' }
if (-not (Test-Path -LiteralPath $publicPgliteModule)) { throw 'STOP: public test module unavailable; no installation' }
$env:EQUITY_TEST_PGLITE_MODULE = $publicPgliteModule
$testTemp = 'C:/Users/banga/AppData/Local/Temp/commissioning-focused-' + [guid]::NewGuid().ToString('N')
if (Test-Path -LiteralPath $testTemp) { throw 'STOP: temporary test path already exists' }
& $testPython -B forward_commissioning_upload_check.py --base 161ffe082343c20cf118950fdb49e5315bb54e7f
if ($LASTEXITCODE -ne 0) { throw 'STOP: exact package gate failed' }
& $testPython -B -m pytest -p no:cacheprovider --basetemp $testTemp -q tests/test_forward_commissioning_upload_check.py tests/test_forward_session_ops.py tests/test_forward_morning_readiness.py tests/test_forward_versioned_capture.py tests/test_overnight_capture_audit.py
if ($LASTEXITCODE -ne 0) { throw 'STOP: focused tests failed' }
& $testPython -B -m mypy --strict --follow-imports=skip --no-incremental --cache-dir=nul forward_commissioning_upload_check.py tests/test_forward_commissioning_upload_check.py
if ($LASTEXITCODE -ne 0) { throw 'STOP: strict typing failed' }
& $testPython -B -m pyflakes forward_commissioning_upload_check.py tests/test_forward_commissioning_upload_check.py
if ($LASTEXITCODE -ne 0) { throw 'STOP: lint failed' }
# Main alone, after final reviews and source freeze, runs the complete candidate:
$fullSuiteTemp = 'C:/Users/banga/AppData/Local/Temp/commissioning-full-' + [guid]::NewGuid().ToString('N')
if (Test-Path -LiteralPath $fullSuiteTemp) { throw 'STOP: full-suite temporary path already exists' }
& $testPython -B -m pytest -p no:cacheprovider --basetemp $fullSuiteTemp -q
if ($LASTEXITCODE -ne 0) { throw 'STOP: full candidate tests failed' }
```

Main runs full source-specific typing/lint, release/fingerprint checks and the full
OFFLINE suite on final bytes. Hosted CI remains an owner prerequisite; this agent
did not request or run hosted CI. Exact local HEAD is enforced; whether it is newest/green is an
owner/main verification, not a fabricated network check. If public main advances,
review/rebase and regenerate all actual-baseline pins; never loosen a mismatch.
This checker is an unsigned reviewed control, not a cryptographic approval.

The owner assessment, same-format read-only 14 October audit, legacy raw-audit
export/disable and tomorrow-only deadline are in the accompanying runbook. No
agent inspected installed state/tasks/credentials or performed hosted writes,
third-party installation, owner auditing or commissioning.

Verification handoff: main reports the final candidate focused command (the five
files listed above) completed with 139 passed and 41 subtests passed in 76.21s.
This checker/test pair separately passed 14 focused offline tests, strict typing
and pyflakes. Main reports full-tree pyflakes, 19 baseline strict modules and seven repaired
source/test files passed strict typing, and 38 closure-module imports passed with
socket/provider/subprocess access denied. Main reports the public/candidate equity
fingerprint unchanged; no expectation update is authorized. Main's final local
OFFLINE candidate suite completed PASS: 4,442 passed, four unchanged skipped,
48 subtests passed in 1,287.99s (21m27s). The public baseline had 4,360 tests:
this candidate adds 82 tests and 41 subtests, with no baseline drop. Main also
reports the read-only host PowerShell script passed parser syntax validation;
it was NOT EXECUTED against Windows tasks. Hosted CI for the exact final commit
remains an owner requirement; no hosted CI run was requested or performed here.
None of these checks proves trigger execution, supervised receipt
acceptance, fresh-capsule acceptance or independent remote custody.
