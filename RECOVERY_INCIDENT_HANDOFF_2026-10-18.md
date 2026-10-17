# Archived-byte recovery review and preserved drill history

## What changed, and what has not been proved

Owner reports PR43 merged green as `f2be345c34bb3c058273b142ccf3589cc3e80b7a`.
The latest SQL result records **122 completed manifests and 98,755 deleted rows**
in the fixed 11–17 October window: quotes44/42700, scanner24/21350, canonical
universe30/13347, versioned universe24/21358. These are recorded receipt sums,
not unique row identities, authenticated custody, or a successful restore.

Historical deletion happened before the present commissioning hold, without the
required independent custody/full-restore evidence. The stated no-deletion-before-
custody policy was therefore not satisfied by that earlier path. It would be
incorrect to say no deletion occurred, or to retrospectively call it commissioned.
The old upload code did perform byte/content round-trip checks before its delete
path; the owner has not independently verified today's copies or a restore. That
is a recovery-verification gap, not proof the data is lost. Keep the hold. Do not
reinsert archives into Supabase, overwrite objects, reset receipts, regenerate
missing evidence, compact the database, or authorise further deletion as remediation.

Priority: preserve original archive bytes → compare every affected receipt with
downloaded bytes/footers → independently encrypted replica → isolated matching
logical/full restore → authenticated custody → guarded readers/writers → retention.
This package implements the first operational byte-review tooling, NOT the later
restore/custody gates. No row-page reader, strategy analysis, labels or training
is invoked. Hashing reads full compressed bytes; Parquet footers may contain
data-derived statistics, which the checker does not inspect. No real archive or
2025/2026 market data is read by the builder. Every fixture is synthetic.

Owner-reported cluster size is360823605 at2026-10-17T18:25:14Z. Against the
500000000-byte planning ceiling this is139176395 nominal bytes, or115176395 above
the24000000 collector admission margin. These are arithmetic on one dated report,
not fresh live admission, observed growth, guaranteed runway or backup proof. The
earlier394MB headline and historical55-day estimate should not be reused as fresh
capacity evidence. No cause for physical size reduction is established by deletes
alone. WAL/system disk and database quota are different measurements.

## Preserved drill: interpretation and next design

The owner reports Disabled, native result0, last_run20:25:20 IST on17Oct, with
recipe/admission/controller markers present and no worker claim/report/launch/
witness/ACK. This is **not synthetic completion**. The pinned confirmed-worker
path exits2 on both intended completion and caught failure; preview exits0.
Independent PS5.1/PS7 source probes did not reproduce a callback/argument scope
defect. Missing confirmation could explain preview/zero, but contradicts the checked
planned action, so it is only a hypothesis. A different scheduled environment could
explain a different state root, but does not by itself explain zero.

No exact worker cause is established. Do not run the worker to inspect it. The
consumed attempt and its expired17Oct-only bridge stay untouched: no retry, new ID,
ACK, reset or cleanup. The next read-only helper queries retained event metadata
for only this task and17Oct14:54–15:03 UTC. It prints event ID, UTC time and numeric
ResultCode only, never messages, accounts, arguments or action paths. It reads log
enabled state but cannot enable it. No retained events or a disabled log does NOT
prove nothing executed. Multiple records are not automatically a single instance;
history completeness and worker cause remain unestablished.

A future drill needs a new independently reviewed capsule: exclusive durable
launch admission; startup receipt containing safe argv mode/confirmation facts,
script identity and interpreter version before semantic checks; per-stage fixed
failure codes; a distinct intentional synthetic outcome; exact native completion
correlation; disable readback even on unknown COMMIT/start; separate human receipt
for a personally seen correlation code. Persist redacted worker output, not raw
stderr/transcripts. It may test production function bodies in isolation, never
break a capture poll to produce evidence. This document commissions no new drill.

## One additive upload

Exact base `f2be345c34bb3c058273b142ccf3589cc3e80b7a`; eleven added paths and zero
existing runtime changes. Source root is
`C:\Users\banga\Desktop\kiran_share_market`; each relative source maps to the
IDENTICAL relative destination in the clean upload clone:

1. `archive_recovery_review.py`
2. `tests/test_archive_recovery_review.py`
3. `ARCHIVE_RECOVERY_FOUNDATION_2026-10-17.md`
4. `preserved_drill_history.ps1`
5. `tests/test_preserved_drill_history.py`
6. `sql/archive_deleted_inventory_read_only.sql`
7. `tests/test_archive_deleted_inventory_sql.py`
8. `RECOVERY_INCIDENT_HANDOFF_2026-10-18.md`
9. `recovery_incident_upload_check.py`
10. `tests/test_recovery_incident_upload_check.py`
11. `RECOVERY_INCIDENT_UPLOAD_2026-10-18.json`

No staged substitutes. Do NOT recopy previous package files, capture folders,
credentials, private ZIP/JSON, SQL-harness node_modules, or local draft migrations.
The older foundation filename reflects work started17Oct; it is not a run-date gate.

### Upload blocks: owner normal PowerShell, one at a time

Use the established clean-clone/new-branch routine at the exact base. If main has
moved, stop for reviewed reconciliation; never edit a pin merely to pass.

```powershell
$ErrorActionPreference='Stop'
$reviewPython='C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
$sourceRoot='C:\Users\banga\Desktop\kiran_share_market'
$expectedBase='f2be345c34bb3c058273b142ccf3589cc3e80b7a'
$head=& git rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $head -cne $expectedBase) {throw 'EXACT_BASE_REQUIRED'}
$dirty=@(& git status --porcelain)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -ne 0) {throw 'CLEAN_CLONE_REQUIRED'}
$paths=@('archive_recovery_review.py','tests/test_archive_recovery_review.py',
 'ARCHIVE_RECOVERY_FOUNDATION_2026-10-17.md','preserved_drill_history.ps1',
 'tests/test_preserved_drill_history.py','sql/archive_deleted_inventory_read_only.sql',
 'tests/test_archive_deleted_inventory_sql.py','RECOVERY_INCIDENT_HANDOFF_2026-10-18.md',
 'recovery_incident_upload_check.py','tests/test_recovery_incident_upload_check.py',
 'RECOVERY_INCIDENT_UPLOAD_2026-10-18.json')
foreach ($path in $paths) {Copy-Item -LiteralPath (Join-Path $sourceRoot $path) -Destination (Join-Path $PWD $path) -ErrorAction Stop}
& git add -- $paths
if ($LASTEXITCODE -ne 0) {throw 'STAGE_FAILED'}
& $reviewPython -B recovery_incident_upload_check.py --base $expectedBase
if ($LASTEXITCODE -ne 0) {throw 'PACKAGE_CHECK_BLOCKED'}
```

Require RECOVERY_INCIDENT_PACKAGE_VERIFIED_REQUIRES_TESTS_AND_EXACT_COMMIT_CI,
failures[]. Then:

```powershell
$ErrorActionPreference='Stop'
& $reviewPython -B -m pytest -q -p no:cacheprovider tests/test_archive_recovery_review.py tests/test_preserved_drill_history.py tests/test_archive_deleted_inventory_sql.py tests/test_recovery_incident_upload_check.py tests/test_archive_commissioning_hold.py tests/test_research_frozen_cohort.py
if ($LASTEXITCODE -ne 0) {throw 'FOCUSED_TESTS_FAILED'}
& $reviewPython -B -m pyflakes archive_recovery_review.py recovery_incident_upload_check.py tests/test_archive_recovery_review.py tests/test_preserved_drill_history.py tests/test_archive_deleted_inventory_sql.py tests/test_recovery_incident_upload_check.py
if ($LASTEXITCODE -ne 0) {throw 'LINT_FAILED'}
$typeCache=Join-Path $env:TEMP ('recovery-mypy-'+[guid]::NewGuid().ToString('N'))
& $reviewPython -B -m mypy --strict --follow-imports=silent --cache-dir $typeCache archive_recovery_review.py recovery_incident_upload_check.py
if ($LASTEXITCODE -ne 0) {throw 'TYPES_FAILED'}
& git diff --cached --check
if ($LASTEXITCODE -ne 0) {throw 'DIFF_CHECK_FAILED'}
```

The SQL execution case skips unless the disposable PGlite harness is configured;
the static read-only contract test still runs. Builder rehearses the real query
against synthetic WASM Postgres separately. No local PostgreSQL service is used.

### Pending Linux rehearsal (owner only, before merge)

The builder did not execute this rehearsal: approval review was unavailable.
From the same public-only upload clone, with the existing local Docker image,
run the following one block. Do not mount a private archive, credentials or capture
folder. The image digest below is the existing zero-network rehearsal environment,
not a request to pull or install an image. If absent, stop rather than substitute.

```powershell
$ErrorActionPreference='Stop'
$publicCheckout=$PWD.ProviderPath
$harnessModules='C:/Users/banga/Desktop/kiran_share_market/tests/sql-harness/node_modules'
$rehearsalImage='sha256:fa2715e71bdf3366cb82a7ce8f422011dc106d26e5d6ff7a570b5d8521b39ece'
& docker run --rm --network none --mount "type=bind,source=$publicCheckout,target=/work,readonly" --mount "type=bind,source=$harnessModules,target=/sql-node,readonly" --workdir /work --env PYTHONDONTWRITEBYTECODE=1 --env EQUITY_TEST_PGLITE_MODULE=/sql-node/@electric-sql/pglite $rehearsalImage /usr/local/bin/python -B -m pytest -q -p no:cacheprovider tests/test_archive_recovery_review.py tests/test_preserved_drill_history.py tests/test_archive_deleted_inventory_sql.py tests/test_recovery_incident_upload_check.py tests/test_archive_commissioning_hold.py tests/test_research_frozen_cohort.py --basetemp /tmp/recovery-incident --tb=short
if ($LASTEXITCODE -ne 0) {throw 'LINUX_REHEARSAL_NOT_PASSED'}
```

Preserve counts and skips; Windows PowerShell executable cases should skip on
Linux, while PS7 cases run in this image. Missing public SQL modules is a blocker
for that SQL rehearsal, not permission to connect to any PostgreSQL server.
The manifest gate still runs on the owner in the clean staged clone, not in Docker.

```powershell
$ErrorActionPreference='Stop'
$identityName=& git config user.name
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($identityName)) {throw 'OWNER_SET_REPO_LOCAL_NAME_FIRST'}
$identityMail=& git config user.email
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($identityMail)) {throw 'OWNER_SET_REPO_LOCAL_EMAIL_FIRST'}
```

One commit message: `Add offline archive recovery review and bounded drill history`.
One plain-line PR description: `Add inactive archive byte verification and read-only preserved drill event diagnostics.`
No attribution/trailers. Require all checks green on the exact final PR SHA;
owner alone merges. Then use a fresh clean checkout of merged main for owner tools.
No activation, setup or enabling step is part of uploading this package.

## Owner operational steps after merge

1. Keep archiveDELETEfalse, releasefalse, undefined option capture off; inspect the
   next scheduled archive log for `ARCHIVE_SCHEDULE_HELD_NO_IO`. Green alone is not
   archive success. Do not rerun old jobs. Preserve original Drive files and run logs.
2. Run `sql/archive_deleted_inventory_read_only.sql` unchanged in the SQL editor.
   It returns one JSON cell of receipt metadata only, in a repeatable-read read-only
   transaction with timeouts and ROLLBACK. Save the JSON OBJECT value, not a quoted
   JSON string, CSV wrapper or results-table label, as private UTF-8 without BOM
   outside every source/tools checkout. Do not paste/upload its Drive IDs publicly.
   Expected incident denominator is122/98755 with the four table totals above;
   discrepancy is review-required, never edit the inventory or code to match.
3. In the normal Drive browser, download the existing verified archive folder once
   as a ZIP. Keep the original filenames and the original downloaded ZIP privately;
   do not extract, rename archive members, upload, delete or overwrite remote files.
   The reviewer accepts a flat ZIP or one common folder prefix, not ZIP64/split ZIPs.
   Unrelated existing archive entries may remain; they are counted but not decoded.
   If the download is split, incomplete, unsupported or too large, preserve it and
   report BLOCKED; do not repack it to conceal a format/coverage issue.
4. Set private path variables locally, then run the separate preview/read blocks
   below. The confirmed operation hashes compressed bytes and checks Parquet
   footer/schema/row counts against every selected receipt; it does not decode
   market rows or `_row_json`, fit anything, contact Drive/DB or write files.
   A match is NOT row-content verification, a restore, signed evidence, independent
   custody, whole-history coverage or deletion permission. Invalid row values can
   pass a byte/footer check against matching receipts; synthetic tests demonstrate
   this limitation deliberately. Share only the redacted summary JSON.
5. For the consumed drill, optionally run the separate historical preview/read
   blocks below. No ACK, worker invocation, cleanup or retry follows any result.
6. Separately finish encrypted signing-key custody and harmless7-Zip disk rehearsal.
   Preserve the original download/metadata now; make an encrypted independent-disk
   replica only under that reviewed procedure, never a plaintext key/disk copy.
   Supply Drive storage used/limit and retention facts, plus whether any DB backup
   actually exists and its date (facts only; no restore button or credentials).

### Offline archive check (fresh merged tools checkout)

Choose private full paths in the normal owner window; do not paste the paths here:

```powershell
$ErrorActionPreference='Stop'
$reviewPython='C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
$recoveryInventory=Read-Host 'Private inventory JSON full path'
$recoveryBundle=Read-Host 'Private original Drive ZIP full path'
& $reviewPython -B archive_recovery_review.py --inventory $recoveryInventory --bundle $recoveryBundle
if ($LASTEXITCODE -ne 0) {throw 'PREVIEW_BLOCKED'}
```

Require PREVIEW, zero input reads/writes/network/credentials. Separate block:

```powershell
$ErrorActionPreference='Stop'
& $reviewPython -B archive_recovery_review.py --inventory $recoveryInventory --bundle $recoveryBundle --confirm-read
if ($LASTEXITCODE -ne 0) {throw 'RECOVERY_REVIEW_BLOCKED_PRESERVE_INPUTS_AND_JSON'}
```

Do not install unpinned packages if PyArrow is missing. The reviewed archive
requirements already pin PyArrow24.0.0; request an isolated, reviewed dependency
setup rather than changing capture or its interpreter environment during a session.

### Historical event check (independent, no task or file changes)

```powershell
$ErrorActionPreference='Stop'
& .\preserved_drill_history.ps1
if ($LASTEXITCODE -ne 0) {throw 'HISTORY_PREVIEW_BLOCKED'}
```

Require PREVIEW, all counters0. Separate block:

```powershell
$ErrorActionPreference='Stop'
& .\preserved_drill_history.ps1 -ConfirmReadOnly
if ($LASTEXITCODE -ne 0) {throw 'HISTORICAL_REVIEW_BLOCKED_NO_RETRY_ADMISSION'}
```

The helper cannot run or modify any task, enable logs, read private drill files,
change ACLs or print raw event XML. Its fixed UTC window is20:24–20:33 IST17Oct.
If no records remain, that branch stays unknown. Do not widen to unrelated logs
or enable history to manufacture evidence of the past.

## Open-item order and boundaries

- Monday19Oct: proven manual Prepare→Start, genuine16Oct close. No dependency on
  this package.20Octclosed/21regular remain owner calendar facts, not a new calendar
  implementation. Guided commissioning is a later separate-date route only.
- Storage: byte preservation/review is first; then authentic generation-bound
  custody and a matching isolated logical/full restore. Production reader/writer
  wiring, dedup, bounded retention and capacity alerts remain uncommissioned.
  Do not claim the present archive contains a consistent six-table/full-DB cut.
- PostgreSQL: non-loopback listeners remain a separate exposure/dependency review;
  no established connection once is not proof it is safe or unused. Prefer an
  on-demand isolated loopback-only test service, but no service/network/ACL changes
  are authorised by this package. No test connects to port5433.
- Time service/root dispersion: still unattributed. Preserve fresh clock gates;
  no automatic time reset, retry, threshold relaxation or alleged root cause.
-14Oct: saved report not found ≠ missing observations. Legacy auditexit2 and
  shared-root writes remain unknown; never rerun a historical writer to fill a gap.
- Guided/daily SID comparison remains a separate integration/rehearsal item;
  historical guided pin0b0aad4 is not newly commissioned.
- OPTION_CAPTURE_ENABLED undefined staysoff; frozen equity sessions end1Oct,
  not automatically extended. Skipped runs are not captured evidence.
- Friday75/75/0 remains unsigned owner-reported evidence; no retrospective cohort
  eligibility, remote custody, real fills or training admission inferred.
- Mandatory ML/backtesting: merged dataset/PAPER/cohort foundations remain intact.
  Next research work is reviewed feature/label and full-session walk-forward
  evaluation/registry, after licensing and frozen-study boundaries. Real training,
  live decisions, performance claims and promotion remain gated, not abandoned.

## Technology radar and next highest leverage

Adopt stdlib ZIP streaming and PyArrow footer-only parsing, existing PS5.1/PS7,
PGlite for synthetic SQL syntax/data tests, and network-disabled Linux rehearsal.
Use independent builder/checker agents for source review, never runtime decisions.
Adapt browser Drive download to avoid another OAuth/secret integration. No new
account, paid plan, plugin or service is required. Do not use DuckDB/Polars row
queries, broad desktop automation or raw transcripts in this recovery check.

Next leverage: bind the verified byte generation to an encrypted independent
replica and an isolated restore witness. In parallel design classified immutable
startup/completion receipts for a FUTURE drill; never reinterpret native zero as
successful alert delivery. No toolkit creates a trading edge.

Primary sources reviewed: Supabase database-size/backups/changelog documentation,
Apache Arrow ParquetFile metadata API, Google Drive browser download guidance,
and Microsoft Scheduler troubleshooting/status and event-log documentation.
## Verification status — do not confuse a prepared package with commissioning

Windows history helper:43 synthetic cases passed, independently rerun by checker.
Inventory SQL:2 tests passed, including execution in synthetic PGlite, not Supabase.
Earlier full archive tests:36 passed/1 symlink-privilege skip. After final schema-copy
test/typing changes,36 in-memory archive cases passed with2 private-path cases
explicitly deselected in that run. No ACL/privilege change was attempted for a skip.
Final lint:6 Python files clean. Strict mypy:2 modules passed.

The independent checker found no blocker in the history helper or the main byte/
footer design. The final per-table denominator/input-hash/schema-copy additions
have builder regression coverage; final independent re-review was interrupted by
the agent usage limit. The Linux rehearsal DID NOT START: automatic approval review
failed due a usage limit. That is not a Linux test failure and was not bypassed.

The final combined Windows attempt finished **163 passed, 12 fixture setup errors**;
all12 errors were inability to create temporary pytest directories under the
sandbox's redirected TEMP. This is NOT a passing rehearsal. No permissions were
changed and no assertion failure is being relabelled as a pass. The final manifest
content/hash test passed separately (1); all11 payload paths and9 prerequisite
pins match locally. The final Linux suite was not run. Actual-base Git/index
checker, project-
wide full suite, final-SHA hosted CI, real native history, real archive byte review,
logical restore and authenticated custody are not established by the builder.
Upload may be prepared for review/CI; do not merge until the documented focused
checks, remaining independent source review and exact-final-SHA hosted gates pass.
No owner operational check is commissioned merely by preparing this manifest.
