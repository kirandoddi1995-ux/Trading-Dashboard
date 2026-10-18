# All-history archive receipt reconciliation — review-only package

## Decision and evidence boundary

Widen the operational manifest review now, before custody commissioning. An
11 October completion cutoff cannot explain older NAV/outcome exports, null
completion fields, or the remaining directory pairs. This is a metadata census,
not a new recovery generation, market-data examination, or deletion permission.

Owner reports PR45 merged green as
`7021fdd3a5009341969c05ab5fe340e00eea825a`; focused118 passed/1 skipped.
The private directory-only result is owner-reported:1758 files, zero directory
entries,876 complete standard pairs =122 incident +754 outside selection,
five nonstandard archive names,one other file,no standard orphan sides.
This supersedes earlier756/extra-manifest guesses. No dates or contents of the754
outside pairs have been established. Their presence does not prove loss or restore.

Keep both original evidence files unchanged:

- Incident inventory SHA256:
  `110ce3642a7afc96d71204c9f1a9f116fd9900d81959887e9db642e8a0acdc32`
- Preserved ZIP SHA256:
  `4f6bd76d5368226d23fb9d369b4635e0fd485247755e443f7d18add2b9dd095b`

The NEW all-history metadata file gets its OWN raw-byte hash. Never replace the
incident inventory, reuse its hash for new bytes, edit a receipt, or widen the
fixed122/98755 incident acceptance constants to make another selection pass.

## What is built

`sql/archive_catalog_all_read_only.sql` returns one private JSON cell from ALL
`quant_app.archive_manifests` rows. It selects only operational receipt columns,
including verified_at/completed_at and nullable deleted_count. It has no date or
source filter; unknown sources remain visible to the offline denominator.
REPEATABLE READ/READ ONLY,UTC,10s statement and2s lock timeouts,then ROLLBACK.
No schema change,grant,maintenance,market-row access,Drive access or connection
string handling. Aggregate materialization is capped at4096 receipt objects;
the complete count still covers all rows. Text field lengths are checked before
aggregation; oversized fields block the entire export. Over4096 or4MiB records returns
BOUND_EXCEEDED_REVIEW_REQUIRED with an empty array,not a partial valid catalog.
Do not add LIMIT or discard rows to make the checker accept.

`archive_catalog_reconcile.py` joins that catalog to the preserved ZIP's central
directory. It opens ZERO ZIP members,reads no JSON manifest bodies or Parquet
pages,and prints no paths,Drive IDs,batch IDs,unknown source names or raw errors.
Default PREVIEW is zero input reads. Confirmed CLI permits only bounded,regular,
nonlinked private files outside the public source checkout,using existing reviewed
file/ZIP guards. The CLI hashes the entire ZIP sequentially in64KiB blocks on the
same guarded handle before directory inspection(maximum2GiB); it never loads the
whole ZIP into memory. Catalog and bounded directory metadata stay in memory.
No extraction,network,credentials or writes.

The report retains every structurally valid receipt and every ZIP file category:

- Per source: receipt paired/missing both/missing data/missing manifest; ZIP pairs
  and orphan sides without a database receipt. Unknown DB sources use a fixed key.
- Per source and UTC verification/completion day: receipt counts and declared
  row/deleted totals,including null deletion counts and inconsistent receipts.
- NO_DELETION_RECORDED means no positive deletion count in this receipt; it does
  NOT prove rows still exist or that no deletion happened by another route.
- DELETION_RECORDED_FULL/PARTIAL are database receipt CLAIMS only. Null deletion
  with completion,positive deletion without completion,bad counts/times and
  reversed/future timestamps are INCONSISTENT_RECEIPT,not silently excluded.
- Dates are receipt-event dates,not underlying market-row dates. Names join only:
  the reported file hash/Drive IDs are not authenticated or content-verified.
- A later DB receipt may legitimately have no file in this earlier ZIP. A ZIP pair
  may have no current DB receipt. Neither mismatch alone proves corruption/loss.
- Duplicate batch or reused Drive references,malformed identifiers,incomplete
  catalog,unknown fields/duplicate JSON keys and pin mismatches block the run.

All custody/restore/hash-content/historical-row-date/deletion/training/approval
proof flags remain false even when the metadata report succeeds. Nonstandard
names remain counted but unclassified; opening their bodies needs a separately
reviewed operational-metadata plan. No automatic repair or deletion follows.

## One additive PR — eight exact source to destination mappings

Source root: `C:\Users\banga\Desktop\kiran_share_market`.
Destination root: your NEW clean public upload clone at exact base below.
Relative source equals relative destination for every item:

1. `archive_catalog_reconcile.py` → `archive_catalog_reconcile.py`
2. `tests/test_archive_catalog_reconcile.py` → `tests/test_archive_catalog_reconcile.py`
3. `sql/archive_catalog_all_read_only.sql` → `sql/archive_catalog_all_read_only.sql`
4. `tests/test_archive_catalog_all_sql.py` → `tests/test_archive_catalog_all_sql.py`
5. `archive_catalog_upload_check.py` → `archive_catalog_upload_check.py`
6. `tests/test_archive_catalog_upload_check.py` → `tests/test_archive_catalog_upload_check.py`
7. `ARCHIVE_CATALOG_HANDOFF_2026-10-18.md` → `ARCHIVE_CATALOG_HANDOFF_2026-10-18.md`
8. `ARCHIVE_CATALOG_UPLOAD_2026-10-18.json` → `ARCHIVE_CATALOG_UPLOAD_2026-10-18.json`

All eight are additions. No staged replacements,CSV,private archives,keys,drill
state,generated data,capture files,or local continuity documents belong in this PR.
Safe to upload independently of Monday capture; do not install into its capsule.

### Upload block1 — normal PowerShell,at the new clean clone root

Use the established clean-clone routine with core.autocrlf=false. Exact base:
`7021fdd3a5009341969c05ab5fe340e00eea825a`. If newer main has merged,STOP for a
reviewed rebase/pin refresh; do not substitute a base or loosen hashes.

```powershell
$ErrorActionPreference='Stop'
$reviewPython='C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
$catalogBase='7021fdd3a5009341969c05ab5fe340e00eea825a'
$head=& git rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $head -ne $catalogBase) {throw 'EXACT_BASE_REQUIRED'}
$dirty=@(& git status --porcelain)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -ne 0) {throw 'CLEAN_CLONE_REQUIRED'}
& git switch -c archive-all-catalog-20261018
if ($LASTEXITCODE -ne 0) {throw 'BRANCH_FAILED'}
$catalogSource='C:\Users\banga\Desktop\kiran_share_market'
$catalogManifest=Get-Content -Raw -LiteralPath (Join-Path $catalogSource 'ARCHIVE_CATALOG_UPLOAD_2026-10-18.json') | ConvertFrom-Json
$catalogFiles=@($catalogManifest.files.PSObject.Properties.Name)
if ($catalogFiles.Count -ne 8) {throw 'EXACT_EIGHT_PATHS_REQUIRED'}
foreach ($relative in $catalogFiles) {
  $destination=Join-Path $PWD.ProviderPath $relative
  $parent=Split-Path -Parent $destination
  if (-not (Test-Path -LiteralPath $parent)) {New-Item -ItemType Directory -Path $parent | Out-Null}
  Copy-Item -LiteralPath (Join-Path $catalogSource $relative) -Destination $destination -ErrorAction Stop
}
& git add -- @catalogFiles
if ($LASTEXITCODE -ne 0) {throw 'STAGING_FAILED'}
& $reviewPython -B archive_catalog_upload_check.py --base $catalogBase
if ($LASTEXITCODE -ne 0) {throw 'CATALOG_PACKAGE_BLOCKED'}
```

Require ARCHIVE_CATALOG_PACKAGE_VERIFIED_REQUIRES_TESTS_AND_EXACT_COMMIT_CI,
failures[]. This checker verifies exact base/index/worktree and every prerequisite.
Its manifest self-hash is null deliberately; index and worktree manifest bytes must
match. No substitution of a successful check from another base or earlier package.

### Upload block2 — focused tests and static checks

```powershell
$ErrorActionPreference='Stop'
& $reviewPython -B -m pytest -q -p no:cacheprovider tests/test_archive_catalog_reconcile.py tests/test_archive_catalog_all_sql.py tests/test_archive_catalog_upload_check.py tests/test_archive_commissioning_hold.py
if ($LASTEXITCODE -ne 0) {throw 'FOCUSED_TESTS_FAILED'}
& $reviewPython -B -m pyflakes archive_catalog_reconcile.py archive_catalog_upload_check.py tests/test_archive_catalog_reconcile.py tests/test_archive_catalog_all_sql.py tests/test_archive_catalog_upload_check.py
if ($LASTEXITCODE -ne 0) {throw 'LINT_FAILED'}
$catalogTypeCache=Join-Path $env:TEMP ('catalog-mypy-'+[guid]::NewGuid().ToString('N'))
& $reviewPython -B -m mypy --strict --follow-imports=silent --cache-dir $catalogTypeCache archive_catalog_reconcile.py archive_catalog_upload_check.py
if ($LASTEXITCODE -ne 0) {throw 'TYPING_FAILED'}
& git diff --cached --check
if ($LASTEXITCODE -ne 0) {throw 'WHITESPACE_FAILED'}
```

The WASM SQL test skips if Node/PGlite are not configured. Record the skip; it is
not native Postgres acceptance. Existing disposable harness can be selected with
EQUITY_TEST_PGLITE_MODULE pointing to its reviewed @electric-sql/pglite directory.
Do not connect to the local5433 service or run synthetic fixture DDL on Supabase.

### Upload block3 — identity check,then commit/push/PR by owner

```powershell
$ErrorActionPreference='Stop'
$identityName=& git config user.name
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($identityName)) {throw 'OWNER_SET_REPO_LOCAL_NAME_FIRST'}
$identityMail=& git config user.email
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($identityMail)) {throw 'OWNER_SET_REPO_LOCAL_EMAIL_FIRST'}
```

Then owner commits `Add read-only all-history archive reconciliation` and uploads
the branch. One-line PR description: `Reconcile all archive receipt metadata against pinned directory names without reading market rows.`
No attribution/trailers. Require independent review and exact-final-SHA hosted CI
green before owner-only merge. New package does not enable any workflow or task.

## Owner metadata review AFTER green merge — one step at a time

1. Inspect the18Oct04:30 IST scheduled archive run's log. Require explicit
   ARCHIVE_SCHEDULE_HELD_NO_IO and zero DB/Drive/deletion activity; green alone is
   insufficient. If absent or different,stop and preserve the log; do not retry.
2. Owner runs ONLY `sql/archive_catalog_all_read_only.sql` in the existing
   Supabase SQL editor. No credential handling/grants/migration. This is an
   explicit owner read-only step,not builder execution. On timeout/error close
   or roll back the editor transaction; do not enlarge scope or retry blindly.
3. Save the ONE private_archive_all_catalog JSON cell as a NEW private UTF-8
   JSON file outside all public checkouts. Not the query-result wrapper array or
   quoted escaped JSON string. Preserve all records,including nulls. Do not paste
   receipt bodies,Drive IDs,JSON or private names into chat. BOUND_EXCEEDED blocks.
4. Keep the original ZIP and inventory unchanged. In a fresh clean merged tools
   checkout use the following preview and confirmed read blocks separately.

```powershell
$ErrorActionPreference='Stop'
$reviewPython='C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
$catalogPath=Read-Host 'NEW private all-history JSON path'
$recoveryBundle=Read-Host 'Preserved private Drive ZIP path'
$catalogPin=(Get-FileHash -LiteralPath $catalogPath -Algorithm SHA256).Hash.ToLowerInvariant()
$bundlePin='4f6bd76d5368226d23fb9d369b4635e0fd485247755e443f7d18add2b9dd095b'
& $reviewPython -B archive_catalog_reconcile.py --catalog $catalogPath --bundle $recoveryBundle --catalog-sha256 $catalogPin --bundle-sha256 $bundlePin
if ($LASTEXITCODE -ne 0) {throw 'CATALOG_PREVIEW_BLOCKED'}
```

Require PREVIEW,input_reads/network/credentials/writes/row_pages0. The hash is a
new local bytes pin,NOT an independent signature or proof of SQL completeness.

```powershell
$ErrorActionPreference='Stop'
& $reviewPython -B archive_catalog_reconcile.py --catalog $catalogPath --bundle $recoveryBundle --catalog-sha256 $catalogPin --bundle-sha256 $bundlePin --confirm-metadata-read
if ($LASTEXITCODE -ne 0) {throw 'CATALOG_RECONCILIATION_BLOCKED_PRESERVE_INPUTS'}
```

Share only the redacted summary. Successful status is
ALL_CATALOG_NAMES_RECONCILED_NOT_CONTENT_OR_CUSTODY. No follow-on signing,row
reconstruction,deletion,unsealing,repair,backup or restore is authorised here.

## Owner priorities and carried-forward open items

Monday19October remains manual Prepare→Start on its proven installed code and
genuine16October close file.20closed/21regular are owner calendar facts. No new
package is a Monday dependency. Keep the consumed drill389daf12415a482eb0231443ddfd8697
and old task/state untouched: no retry,newID,Run,ACK,cleanup or marker reset.

Weekend owner prerequisites: encrypted signing-key note/history,harmless7-Zip
AES-256/header-encryption disk rehearsal,Drive used/limit/retention and DB-backup
availability facts only. No real backup commissioned by this package. Then build
the protected independent replica + authenticated witnesses + matching isolated
typed/application restore; only then consider retention commissioning. The
existing legacy SQLite TEXT rehearsal is not a whole-database Postgres restore.

Not blocked by directory counts,but still OPEN: production failure-alert delivery;
future drill with durable worker-startup evidence; guided/daily SID integration
and separate-date guided commissioning(oldpin0b0aad4 not installed); local PG17
Running/Auto,non-loopback5433 exposure/service decision(no service or ACL changes);
unattributed Windows Time12:48/root dispersion;14Oct saved-report absent(not proof
of missing observations); legacy auditexit2/shared-root writes; OPTION_CAPTURE_ENABLED
undefined/off and frozen equity sessions ending1Oct; writer/cold-reader integration,
dedup,bounded retention,capacity-alert commissioning. DB345549971/cluster360823605
at17Oct18:25:14UTC remain dated owner readings,not live capacity checks.

Friday75/75/0 remains an unsigned owner-reported claim. ML/backtesting deliverables
remain mandatory: dataset boundary,paper replay/frozen-cohort foundations merged;
quote-faithful futures replay,evaluation/promotion/calibration/walk-forward/model
registry and licensed labels still require further work. Real fitting,performance
claims and promotion remain gated. Storage tools confer no trading edge.

## Research,technology radar and verification

Adopt existing strict ZIP/private-file guards and exact-byte pins; use stdlib only
for this checker. Reuse disposable PGlite for query behavior,not as evidence of
native deployment. Considered and rejected broad extraction,paid storage,new
connector/credential access,archive cleanup and whole-DB rollback for this review.
The next highest-leverage step is a protected independent replica with a matching
measured restore witness,not more blind archive/drill retries.

Primary research: [Postgres17 repeatable-read semantics](https://www.postgresql.org/docs/17/transaction-iso.html),
[Supabase backup boundaries](https://supabase.com/docs/guides/platform/backups),
[current changelog](https://supabase.com/changelog). Snapshot isolation makes this
query's receipt view stable; it does not authenticate it or make it match an older
ZIP snapshot. Free-tier backups must not be presumed available; external archive
bytes and role passwords are not established by database backup claims. The
changelog markdown endpoint failed content-type handling; HTML fallback reviewed.

Builder verification: Windows synthetic regression **88 passed,0 skipped** across
the metadata reconciler,new/previous receipt SQL,deletion hold and anchored receipt
tests. Both SQL tests executed in disposable PGlite,not native Postgres. The exact
four-file owner focused command above includes upload-checker tests and is a
different selection: **80 passed,0 skipped** with the WASM harness configured.
These counts overlap; do not add them together. Pyflakes clean for5 files;
strict mypy passes2 source modules with a real temporary cache.

Independent reviewer found2 resource-bound issues; fixed before handoff(SQL
pre-aggregation field/count guards,streamed ZIP hashing). Reviewer then reported
no remaining code blockers and32 passing/1 SQL-harness skip on its selection.
Those are reviewer-reported results,not a Linux or whole-repository result.

Linux builder rehearsal: NOT RUN. Even Docker image inspection was denied by the
sandbox's daemon-pipe permissions; no permission/ACL change or alternate bypass
attempted. Owner exact-final-SHA Linux CI is required. Actual-base staged acceptance,
full repository tests,private inputs,current DB metadata,encrypted custody and
native/application restore remain unverified. No real archive,market row,key or
database was read by this build. The package does not claim the new SQL has run on
Supabase or that any unreviewed older batch is recoverable.
