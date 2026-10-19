# Outcomes large-row recovery: PR49 policy reconciliation, inactive candidate

## PR49 correction (supersedes the original nine-addition upload instructions)

PR49 is OPEN, unmerged, head 088fab77bc2bc847d2d798eb2cbe429a9a81c997, parent/base
07313864a9033a8b97f041012c77f55d54cb127a. Read-only GitHub confirmed mergeable=true,
no inline review threads, two verify failures; CodeQL/resilience passed. Owner's
Linux result was 1 failed,6735 passed,276 skipped,76 subtests. This was a builder
integration omission: focused tests did not include the repo-wide workflow policy.
The first failure concealed two later conflicts: SHA-pinned actions versus tags,
and Python 3.13.9 versus the default 3.13 selector. All three are addressed together.

Decision: retain the optional native Windows workflow, because Windows Job Object
acceptance cannot be established on Ubuntu. Do not broaden the default runner,
matrix, action or Python policy. tests/test_workflow_runtimes.py grants only the
canonical outcomes-resource-conformance.yml path a whole-file LF-normalized SHA256
exception. It redundantly checks the two exact images, two reviewed action SHAs,
exact Python patch, manual confirmation and unset-variable gate, read permissions
and no secrets/schedule. Any changed workflow bytes require fresh explicit review.
Other workflows, other paths with the same filename and reusable workflow checks
retain the existing policy. Adversarial mutations are tested. The workflow itself,
its activation gates and every archive/resource guard are unchanged in this repair.

This is now TEN paths: the original nine additions plus ONE base-file modification
(tests/test_workflow_runtimes.py). Manifest contract is v2, with that file's exact
base hash and an optional explicit PR49 update mode pinned to the full old head
AND its single expected parent. It is not an arbitrary-HEAD or ancestor bypass.
Do not force-push, reset a branch or regenerate prerequisite pins to pass a check.
For the existing PR, use "Updating the EXISTING PR branch" below; the initial
exact-base Block 1 is only the alternative clean-base package rehearsal.

## Decision and evidence boundary

The owner's PR48 diagnostic is strong evidence of a size-policy mismatch, not proof
of corruption or of valid contents. All 18 manifest/byte-hash observations passed;
only the original 16 MiB column-expansion predicate rejected eight batches. Preserve
the original BLOCKED report and all pins. The generic verifier remains 868/876.
Do not rerun it with altered limits, substitute this candidate result for acceptance,
or change ARCHIVE_DELETE_ENABLED=false or the scheduled no-I/O hold.

Owner-reported rejected ordinals: 135,266,318,386,395,626,698,757. Largest column
28,452,331 bytes; their declared file expansions total 362,104,820. The previous
721,587,435-byte verifier total omitted rejected footer returns. On these identical
inputs the corrected full declared total is 1,083,692,255 bytes. This is neither
decoded-memory use, unique-row count, authentication nor restore proof.

Source-only investigation at the pinned public base found a plausible mechanism:
equity_research_outcomes.evaluate_touches retains source_candles, session_calendar
and missing_minutes; the collector supplies candle arrays; save_outcome retains the
outcome JSON. The repository's display report omits large arrays, not the stored
payload. drive_archive.parquet_bytes writes payload JSON and exact whole-row JSON
in _row_json, duplicating much of that content. No private rows were inspected.
This does NOT establish why any particular real row is large or legitimate.
Do not strip or reserialize old evidence, retune rules or modify the producer here.

## What this ten-path package does

outcomes_large_profile.py is a pure metadata classifier, not an admission gate.
Only equity_research.outcomes payload and _row_json have a candidate 32 MiB cap;
the other three fixed columns remain 16 MiB. It also requires one row group,
1..100 rows, one chunk per column, all other original predicates, a 32 MiB member,
256 KiB footer and 128 MiB declared file budget. Candidate assessment always says
commissioned=false, private_decode_authorised=false, custody/restore/deletion=false.
The 32 MiB candidate is fixed and reviewed, not dynamically increased to fit data.
An eventual decoder must additionally enforce a 1 MiB exact row bound and the
4 GiB aggregate budget, sequentially, with no private output through public logs.

outcomes_resource_conformance.py accepts ONLY eight fixed synthetic cases, no file
paths, commands, credentials or real data. Preview launches nothing. Cases cover
small and large rows, dictionary compression, oversize columns, a single huge row,
memory denial, wall timeout and output flooding. It reuses the existing archive
codec on invented 2022-labelled test records only; these are not research evidence.

Windows: suspended CreateProcess, explicit two-pipe handle inheritance, native job
assignment and limit readback before resume; 768 MiB process/aggregate commit,
15 CPU seconds, two processes (venv redirector plus real Python), kill-on-close.
The child queries membership/limits of the named outer job, then closes that query
handle. Parent requires a reaped child, an empty job, and bounded error-free output.
Linux: prlimit/readback before the workload GO message; 3 GiB RLIMIT_AS (virtual
address space, NOT RSS), 15 CPU seconds, no core/file output. Existing tighter hard
limits reject rather than being raised. Wall is 30 seconds (2 for timeout case),
combined output 4 KiB. Resource limits are NOT a filesystem/network sandbox. The
runner therefore deliberately provides no private-archive entry point. A batch
size of one alone does not bound Arrow's page or dictionary allocation.

## Recovery order: no deletion or private decoding commissioned here

1. Preserve opaque originals NOW: pinned ZIP, complete catalog, pinned diagnostic
   and original verification reports plus inventory. Use the reviewed encrypted
   independent-disk procedure, test archive extraction/hash equality in a separate
   private destination and disconnect/store the disk separately. Keep its password
   and signing-key note out of the project and separate from the encrypted copy.
   This can proceed before column decoding. Do not overwrite any existing copy.
2. Establish authenticated custody of this exact generation: independently reread
   stored bytes, bind full hashes, catalog coverage, object IDs and both witnesses
   to a signed generation receipt with an independently retained trust anchor.
   Signing old receipt claims now does not make their historic deletion claims true.
3. After both native platform suites pass, build/review a separate private bridge
   with fixed full input pins and bounded selected-member admission. Its decisions
   must be tied to actual bytes, not an editable diagnostic JSON. No private bridge
   or real row decoder exists in this package; no command below runs one.
4. Explicitly commission an isolated typed restore, checking schemas, exact row
   identity/counts, duplicate/conflict handling, constraints and cold-reader lookup
   over retained original bytes. Recovery-only content handling must not become
   2025/2026 research inspection or training. Keep any comparison output private.
5. Cold readers and guarded live writers need end-to-end proof before changing the
   hot window. Retention is LAST, generation-specific and fail-closed on missing
   custody/restore/lookup proof. Existing unauthenticated receipts never suffice.

No actual independent copy, custody, private decode, typed/Postgres restore, cold
lookup or deletion authority has been established by this package. Deleted-row
claims remain unauthenticated, including the two no-deletion batches. Do not restore
everything into the constrained hosted database; use an explicitly isolated target.

## Exact upload: repair the same PR49, nine additions plus one reviewed modification

Base: 07313864a9033a8b97f041012c77f55d54cb127a (PR48 merge). If main has moved,
STOP and reconcile; do not remove or loosen pins. Public prerequisite content was
read from this exact SHA; the checker compares base, index AND working bytes.

Source root: C:\Users\banga\Desktop\kiran_share_market\
Destination root: the owner's NEW clean public clone at the exact base above.
For each following relative path, copy source-root + path to clone-root + SAME
path, preserving directories. This is the complete source-to-destination map:

```
tests/test_workflow_runtimes.py                   -> tests/test_workflow_runtimes.py
outcomes_large_profile.py                         -> outcomes_large_profile.py
outcomes_resource_conformance.py                  -> outcomes_resource_conformance.py
tests/test_outcomes_large_profile.py              -> tests/test_outcomes_large_profile.py
tests/test_outcomes_resource_conformance.py       -> tests/test_outcomes_resource_conformance.py
.github/workflows/outcomes-resource-conformance.yml -> .github/workflows/outcomes-resource-conformance.yml
OUTCOMES_LARGE_HANDOFF_2026-10-19.md               -> OUTCOMES_LARGE_HANDOFF_2026-10-19.md
outcomes_large_upload_check.py                    -> outcomes_large_upload_check.py
tests/test_outcomes_large_upload_check.py         -> tests/test_outcomes_large_upload_check.py
OUTCOMES_LARGE_UPLOAD_2026-10-19.json              -> OUTCOMES_LARGE_UPLOAD_2026-10-19.json
```

No CSV, credentials, local continuity files, old packages, real reports or archive
bytes belong in this upload. Normal non-Administrator PowerShell, one block at a
time. Use only the existing explicit venv, never bare py. Do not install or alter
the capture environment. The reviewed archive dependencies must already be present.

Block 1, from the clean clone after copying, checks identity presence and stages
only these paths. It does not set an identity or create a commit:

```powershell
$ErrorActionPreference = 'Stop'
$python = 'C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
if ((& git rev-parse HEAD) -ne '07313864a9033a8b97f041012c77f55d54cb127a') { throw 'EXACT_BASE_REQUIRED' }
& $python -I -B -c "import sys; assert sys.version_info[:3] == (3,13,9)"
if ($LASTEXITCODE -ne 0) { throw 'REVIEWED_RUNTIME_REQUIRED' }
if (-not (& git config user.name) -or -not (& git config user.email)) { throw 'REPO_IDENTITY_REQUIRED_OWNER_STEP' }
& git add -- tests/test_workflow_runtimes.py outcomes_large_profile.py outcomes_resource_conformance.py tests/test_outcomes_large_profile.py tests/test_outcomes_resource_conformance.py .github/workflows/outcomes-resource-conformance.yml OUTCOMES_LARGE_HANDOFF_2026-10-19.md outcomes_large_upload_check.py tests/test_outcomes_large_upload_check.py OUTCOMES_LARGE_UPLOAD_2026-10-19.json
if ($LASTEXITCODE -ne 0) { throw 'STAGE_FAILED' }
& $python -B outcomes_large_upload_check.py --base 07313864a9033a8b97f041012c77f55d54cb127a
if ($LASTEXITCODE -ne 0) { throw 'PACKAGE_BLOCKED_INSPECT_FIXED_RULE_PATH_AND_HASH' }
```

Block 2, focused tests INCLUDING workflow policy (eight native cases deliberately skipped here):

```powershell
$ErrorActionPreference = 'Stop'
& $python -B -m pytest -q -p no:cacheprovider tests/test_workflow_runtimes.py tests/test_outcomes_large_profile.py tests/test_outcomes_resource_conformance.py tests/test_outcomes_large_upload_check.py tests/test_outcomes_footer_diagnostic.py tests/test_archive_catalog_verify.py tests/test_archive_recovery_review.py
if ($LASTEXITCODE -ne 0) { throw 'FOCUSED_TESTS_FAILED' }
```

Block 3, lint and strict checks on the new modules (legacy imports followed silently,
not a claim that the old untyped drive_archive module passed strict typing):

```powershell
$ErrorActionPreference = 'Stop'
& $python -B -m pyflakes outcomes_large_profile.py outcomes_resource_conformance.py outcomes_large_upload_check.py tests/test_outcomes_large_profile.py tests/test_outcomes_resource_conformance.py tests/test_outcomes_large_upload_check.py tests/test_workflow_runtimes.py
if ($LASTEXITCODE -ne 0) { throw 'LINT_FAILED' }
$typeCache = Join-Path ([IO.Path]::GetTempPath()) ('outcomes-types-' + [guid]::NewGuid().ToString('N'))
& $python -B -m mypy --strict --follow-imports=silent --cache-dir $typeCache outcomes_large_profile.py outcomes_resource_conformance.py outcomes_large_upload_check.py
if ($LASTEXITCODE -ne 0) { throw 'TYPES_FAILED' }
& git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw 'STAGED_DIFF_FAILED' }
```

Commit/PR via the established owner routine. Suggested commit and one-plain-line PR
description: Reconcile the reviewed native outcomes workflow with the runtime policy
No attribution/trailers. Require green hosted checks on the EXACT final commit,
owner-only merge, then green main. Do not change release hold or Streamlit pins.

### Updating the EXISTING PR branch without resetting it

You do not need to re-copy unchanged profile, harness, their two tests or workflow.
Re-copy exactly these FIVE files from the source root to the SAME destination paths
in a fresh clean checkout of the existing PR49 branch at the exact full head above:

```
tests/test_workflow_runtimes.py
outcomes_large_upload_check.py
tests/test_outcomes_large_upload_check.py
OUTCOMES_LARGE_HANDOFF_2026-10-19.md
OUTCOMES_LARGE_UPLOAD_2026-10-19.json
```

Before copying, require git status --porcelain empty and git rev-parse HEAD equal
088fab77bc2bc847d2d798eb2cbe429a9a81c997. If it differs, STOP; do not reset it. If using
a new clone, use the existing outcomes-large-profile-20261019 branch, not a new PR.
After copying run this block INSTEAD of Block 1's exact-base staging/check block:

```powershell
$ErrorActionPreference = 'Stop'
$python = 'C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
if ((& git rev-parse HEAD) -ne '088fab77bc2bc847d2d798eb2cbe429a9a81c997') { throw 'REVIEWED_PR49_HEAD_REQUIRED' }
if ((& git rev-parse 'HEAD^') -ne '07313864a9033a8b97f041012c77f55d54cb127a') { throw 'REVIEWED_PARENT_REQUIRED' }
if ((& git branch --show-current) -ne 'outcomes-large-profile-20261019') { throw 'EXISTING_PR49_BRANCH_REQUIRED' }
& $python -I -B -c "import sys; assert sys.version_info[:3] == (3,13,9)"
if ($LASTEXITCODE -ne 0) { throw 'REVIEWED_RUNTIME_REQUIRED' }
if (-not (& git config user.name) -or -not (& git config user.email)) { throw 'REPO_IDENTITY_REQUIRED_OWNER_STEP' }
& git add -- tests/test_workflow_runtimes.py outcomes_large_upload_check.py tests/test_outcomes_large_upload_check.py OUTCOMES_LARGE_HANDOFF_2026-10-19.md OUTCOMES_LARGE_UPLOAD_2026-10-19.json
if ($LASTEXITCODE -ne 0) { throw 'STAGE_FAILED' }
& $python -B outcomes_large_upload_check.py --base 07313864a9033a8b97f041012c77f55d54cb127a --update-pr49
if ($LASTEXITCODE -ne 0) { throw 'PACKAGE_BLOCKED_INSPECT_FIXED_RULE_PATH_AND_HASH' }
```

The checker still requires the combined TEN-path staged tree against the base,
9 A + 1 M; it verifies all unchanged original package payloads and prerequisites.
Then run focused Block 2, lint/types Block 3 and the full-suite block below before
committing. Append one normal corrective commit on the existing branch; owner may
push that commit normally to update PR49. No amend/rebase/force-push. The checker is
pre-commit only; its pinned old-head mode deliberately stops accepting new HEADs.
After committing, record the full new SHA and require all hosted checks green on
that exact SHA before owner merge. Do not re-run the old failing commit unchanged.

### Full-suite pre-upload policy from this repair onward

Focused tests are triage, not release-wide evidence. Before handing off a package,
run the workflow-policy tests and the full OFFLINE suite on the final package tree
in a representative clean environment. Run Windows and Linux where available;
record platform, runtime, pass/fail/skip counts, SQL-engine setup and exact tree.
If an environment is unavailable, say NOT VERIFIED; never silently exclude its
failures or call that platform green. Exact-final-SHA hosted Linux CI remains a
mandatory merge gate. Native manual stress workflows remain separately opt-in.

The full-suite owner block uses the existing reviewed Node/PGlite install. It does
not install packages or change capture settings. If the SQL fixture is absent in a
fresh clone, the separate locked setup block below installs it locally, without
install scripts, audit or funding requests. Missing Python test tools must be
reported rather than weakening/skipping tests. Do not run
full tests in an installed capture capsule or while they contend with capture.

Only if the clone lacks its SQL fixture, first use this separate block (Node 24
must already be installed; do not substitute another major or install system tools):

```powershell
$ErrorActionPreference = 'Stop'
& node -e "if(process.versions.node.split('.')[0]!=='24')process.exit(2)"
if ($LASTEXITCODE -ne 0) { throw 'REVIEWED_NODE24_REQUIRED' }
& npm ci --prefix tests/sql-harness --ignore-scripts --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw 'LOCKED_SQL_FIXTURE_INSTALL_FAILED' }
```

```powershell
$ErrorActionPreference = 'Stop'
$sqlFixture = Join-Path $PWD 'tests\sql-harness\node_modules\@electric-sql\pglite'
if (-not (Test-Path -LiteralPath $sqlFixture)) { throw 'REVIEWED_SQL_FIXTURE_REQUIRED' }
$previousSqlFixture = $env:EQUITY_TEST_PGLITE_MODULE
try {
    $env:EQUITY_TEST_PGLITE_MODULE = $sqlFixture
    & node -e 'const {PGlite}=require(process.env.EQUITY_TEST_PGLITE_MODULE); (async()=>{const db=new PGlite();try{await db.waitReady;await db.query(String.fromCharCode(83,69,76,69,67,84,32,49));}finally{await db.close();}})().catch(()=>{process.exitCode=1;});'
    if ($LASTEXITCODE -ne 0) { throw 'SQL_ENGINE_PREFLIGHT_FAILED' }
    & $python -B -m pytest -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw 'FULL_SUITE_NOT_GREEN_KEEP_PR_UNMERGED' }
} finally {
    $env:EQUITY_TEST_PGLITE_MODULE = $previousSqlFixture
}
```

Record every skip; they are not passes. Only the shell-local SQL fixture environment
value is temporarily changed and restored; no persisted system setting is changed.

## Optional owner commissioning: synthetic workflow ONLY, after green merge

Default is no schedule and no automatic execution. Workflow requires BOTH a manual
confirmation and repository variable OUTCOMES_RESOURCE_CONFORMANCE_ENABLED=true.
Do not set it just to upload. If the owner explicitly chooses this synthetic test:
set that one variable, run Disposable outcomes resource conformance on the reviewed
main SHA with confirm_disposable ticked, require all eight cases PASS on BOTH
ubuntu-24.04 and windows-2022, then remove the variable/disable the workflow again.
No secrets, artifacts, database, Drive, alerts, capture or real-data inputs are used.
Any failure: preserve log, no blind rerun or edits to input pins. Even full success
does not commission private decoding, custody, restore, training or deletion.

## Verification ledger and technology choices

### PR49 repair verification (current; supersedes the original package counts)

- Read-only public PR/log check confirmed the exact old head/base and its sole
  hosted failure; the repaired final commit has NOT been uploaded or tested by CI.
- Windows, explicit Python 3.13.9: complete focused selection INCLUDING workflow
  policy and external-path tests: 157 passed,9 skipped. Eight skips are the opt-in
  native cases; one is the existing unsupported symlink test. Policy-only:38 passed.
- Actual staged Git check PASSED in an isolated public clean-base checkout (9A+1M).
  Actual --update-pr49 staged check also PASSED in a separate public checkout at
  the exact reviewed PR head/parent, with five replacement paths. No commit/push.
- Lint passed for seven Python files; strict typing passed for three new modules
  with --follow-imports=silent. Legacy imports are not newly strict-certified.
- Both pinned actions' action.yml files were read at their exact official SHAs;
  both use Node24. Workflow bytes/native harness are unchanged from the first
  package; the prior Windows eight-case native result is historical, not a rerun.
- Full Windows suite ATTEMPTED in a clean LF public-base clone plus the ten staged
  package paths, Node24/PGlite preflight passed, SQL lock matched, fresh external
  synthetic TEMP. It is NOT GREEN: an unchanged archive-replay test reproduced
  WinError5 at automated_development_checks.write_once -> os.link. The sandbox
  denies immutable hard-link creation. Other partial-run failures were not all
  classified. The run was deliberately interrupted after diagnosing this boundary,
  process exited1, and no complete full-suite totals were produced. Do not cite
  partial dots or focused counts as full-suite evidence. No full run left running.
- Linux native/full suite for this repair NOT RUN locally (Docker access previously
  denied). Do not elevate or change permissions. Owner normal-environment full
  suite and exact-final-SHA hosted Linux CI are required before merge.
- Independent checker reviewed the narrow policy, update mode and owner commands;
  no remaining code blocker found. Hard-link denial was not bypassed. Native
  Windows PowerShell quoting in the SQL preflight was repaired without shell-mode
  or system-setting changes.

These checks do NOT establish private decoding, content authenticity, independent
custody, restore or deletion authority. Those flags remain false.

### Original inactive-package verification (historical only)

Builder: native Windows synthetic eight-case CLI passed after hardening, with caps,
process reaping and empty-job readback. Focused selection: 111 passed, 8 native-case
skips, 2 existing private-path tests deselected. The full selection was attempted:
default sandbox TEMP failed to create test directories (111 pass/8 skip/2 errors);
a workspace test TEMP then correctly hit PRIVATE_INPUT_OUTSIDE_SOURCE_REQUIRED
(111 pass/9 skip/1 fail). No guard was loosened. The owner's full focused line above
must run all tests in a normal environment; these two boundary tests remain
builder-unverified in a faithful external TEMP. Independent review found three edge cases (malformed
containers, launch pipe cleanup, read-error false PASS); all were fixed and receive
regression tests. Independent pure selection: 32 passed, 8 native skips; no remaining
blocker found in that delta. Lint passed for all six new Python files; strict type
checks passed for three new modules with --follow-imports=silent.
Strict checks cover three new modules; legacy imported code is not newly certified.
Linux native execution NOT VERIFIED locally: Docker engine pipe permission denied;
no elevation or permission changes attempted. Hosted matrix and exact owner staged
checkout acceptance remain owner-pending despite the builder's isolated rehearsal.
The repair's full-suite attempt/limitations are recorded above. No private archive,
row or credential was opened.

Adopted: existing lossless codec, Arrow, Windows Job Objects and Linux prlimit;
separate independent reviewer. Adapted: explicit suspended Windows venv launch,
because CPython's Windows venv redirector creates a second process and an inner job.
Rejected: globally raising guards, trusting a footer as contents, auto-accepting
receipts, in-process private decode and paid storage. Docker may provide stronger
filesystem/network isolation for a later private bridge, but is not available to
this builder. Process resource caps alone are not advertised as that isolation.

Primary references studied:
- [Windows jobs](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
- [AssignProcessToJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject)
- [CPython 3.13.9 Windows venv launcher](https://github.com/python/cpython/blob/v3.13.9/PC/venvlauncher.c)
- [Python resource limits](https://docs.python.org/3.13/library/resource.html)
- [Arrow ParquetFile API](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.ParquetFile.html)

Earlier open items stay open: production failure-alert delivery; legacy audit/shared
root review; 14 Oct missing saved audit; time-service attribution/dispersion;
OPTION_CAPTURE_ENABLED skipped runs; fresh hosted capacity snapshot; key custody,
disk restore rehearsal and Drive capacity/retention; exact-cut authenticated full
restore/cold readers/retention; local PostgreSQL service decision; guided-wrapper
commissioning/SID checks; real ML/backtesting licences, labels and frozen paper study.
Nothing here depends on or changes the live capture capsule, tasks or state.
