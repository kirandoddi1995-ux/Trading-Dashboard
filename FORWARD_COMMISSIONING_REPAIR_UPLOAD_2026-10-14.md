# Exact inactive commissioning repair upload — 14 October 2026

## PR #33 portability correction — unmerged branch update

Main remains `161ffe0`; failed PR head reported by owner is `ba95d1f`.
The earlier 4,442-pass result below was **Windows only**, not Linux acceptance.
Hosted Linux CI reported 15 failed, 4,430 passed, one skipped and 48 subtests;
14 failures came from interpreting Windows fixture strings with PosixPath and
one from mixing a POSIX code location with Windows task-binding arguments.
Production guards correctly rejected those fixtures. Production sources,
checker rules, baseline and all prerequisite pins are unchanged.

The repair keeps real guards active. In-memory Windows adapters now explicitly
use PureWindowsPath on either OS; independent native-path guard cases still run.
No failed case is skipped, weakened, or removed. The old failure log is evidence
of the old commit, not a reason to retry it unchanged.

For the EXISTING PR branch, replace exactly these five repo-relative paths from
the matching paths under `C:/Users/banga/Desktop/kiran_share_market/`:

- `tests/test_forward_morning_readiness.py`
- `tests/test_forward_session_ops.py`
- `FORWARD_COMMISSIONING_REPAIR_2026-10-14.md`
- `FORWARD_COMMISSIONING_REPAIR_UPLOAD_2026-10-14.md`
- `FORWARD_COMMISSIONING_REPAIR_UPLOAD_2026-10-14.json`

Do not create a replacement PR, force-push, rebase, change production files, or
merge the failed head. For package rehearsal use a fresh clone at exact BASE
161ffe082343c20cf118950fdb49e5315bb54e7f and stage ALL ten canonical files below.
The checker deliberately requires that base HEAD; it is not a checker to run
with `--base ba95d1f` on the already-committed PR branch. After rehearsal, the
owner updates the five paths on the existing branch in an ordinary commit.
Require Quality, Resilience and CodeQL success for THAT exact new SHA before
merge. Old successful checks do not authorize a changed commit. No agent push,
workflow dispatch, enabling, hosted write or capsule install is performed.

### Linux before upload, both platforms before merge

Windows and Linux results must be named separately. Python patch version,
dependency pins, Node version, full/focused counts and source hashes belong to
each result. A local Debian Linux container is not an exact Ubuntu hosted runner;
hosted exact-commit CI remains authoritative. Differences in platform skips are
reported, not treated as dropped tests.

Local-only Docker recipe:
`C:/Users/banga/Desktop/kiran_share_market/reviewed_stage/commissioning_portability/Dockerfile`.
It is NOT an eleventh upload. Build context contains only the public baseline's
requirements.txt, requirements-automation.txt and constraints.txt; official
Python 3.13.9 and Node 24 bases are digest-pinned. Tests run with network disabled,
read-only mounts of the clean PUBLIC candidate and public PGlite dependency.
For the full suite, local-only run_linux.py exports tracked public files into a
fresh writable container copy (ignored host caches are excluded). This permits
the app's synthetic local SQLite cache without writing the host checkout.
No credentials/state/capture mounts, no ports and bounded CPU/memory. Do not use
the dirty workspace or private TradingResearch as Docker context or repo mount.
Run the focused line below and full suite on Linux before handing off the upload;
run Windows compatibility checks as well. A missing Linux environment means
LINUX_NOT_VERIFIED, never an inferred pass. Repaired Linux/Python 3.13.9 focused
run passed: 139 tests, 41 subtests, 322.52 seconds. Windows corrected reporting/
readiness tests passed: 98 cases. Full repaired Debian Linux/Python 3.13.9 run:
4,435 passed, 11 skipped, 48 subtests in 667.60 seconds (11m07s). Ten existing
mocked PowerShell installer cases skip because this container has no PowerShell;
one existing Windows DACL case is OS-specific. The corresponding Windows test
file passed all 11 cases separately. These are explicit local coverage limits,
NOT skips added to repair the 15 failures. Hosted Ubuntu CI must still execute
its complete coverage (including PowerShell) on the exact final PR SHA.

Image used: `sha256:bf219af81ce987b7b8ea5c4d3075425b6210d270ec3aa7368ee8ba127818ed06`;
Python 3.13.9, Node v24.21.0, pytest 9.1.1. The previously recorded Windows full
run is historical, before the fixture correction, not a new two-OS full claim.

Local Linux full command (new container name each time; existing names/receipts
must not be overwritten). `$publicCandidate` must be the clean staged public
rehearsal clone and `$publicPglite` only its reviewed public test engine:

```powershell
docker run --name kiran-portable-review-NEW --network none --cpus 2 --memory 4g --mount "type=bind,source=$publicCandidate,target=/source,readonly" --mount "type=bind,source=$publicPglite,target=/pglite,readonly" --mount "type=bind,source=C:/Users/banga/Desktop/kiran_share_market/reviewed_stage/commissioning_portability/run_linux.py,target=/runner.py,readonly" --workdir /tmp kiran-commissioning-portability:20261015 python /runner.py
if ($LASTEXITCODE -ne 0) { throw 'STOP: Linux check failed' }
```

Do not infer success from a detached container starting. Retain exit/result and
skip reasons. The image is local-only; building dependencies needs network but
testing must not. The Debian check is not the hosted Ubuntu check. No workflow,
setting, requirement, checksum rule or production adapter was changed for this.

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
fingerprint unchanged; no expectation update is authorized. The EARLIER Windows-only
OFFLINE candidate suite, before PR #33's fixture correction, completed PASS: 4,442 passed, four unchanged skipped,
48 subtests passed in 1,287.99s (21m27s). The public baseline had 4,360 tests:
this candidate adds 82 tests and 41 subtests, with no baseline drop. Main also
reports the read-only host PowerShell script passed parser syntax validation;
it was NOT EXECUTED against Windows tasks. Hosted CI for the exact final commit
remains an owner requirement; no hosted CI run was requested or performed here.
None of these checks proves trigger execution, supervised receipt
acceptance, fresh-capsule acceptance or independent remote custody.
