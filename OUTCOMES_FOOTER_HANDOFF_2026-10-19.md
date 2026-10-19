# Outcomes footer investigation — diagnostic only,original BLOCKED result preserved

## Assessment

Owner reports PR47 merged main6a06f4d; read-only GitHub metadata resolves exact
base `6a06f4d828fb3be265510ca9a5f21b1e534ec583`. Confirmed owner verification:
868/876 matched,690858 matched footer rows,all8 failures in outcomes at ordinals
135,266,318,386,395,626,698,757;1752 member-open attempts,zero Parquet row pages,
network and writes. These are owner-reported,not builder private-file results.

The original code performs manifest matching and Parquet SHA matching BEFORE
entering the footer stage. Thus the reported stage is consistent with those two
checks passing for the8 files. It does not establish independent authenticity.
PARQUET_COLUMN_EXPANSION_BOUND multiplexes FIVE conditions:

- external column file_path present;
- codec not ZSTD;
- num_values different from row-group rows;
- total_uncompressed_size nonpositive OR above16MiB;
- total_compressed_size nonpositive OR above file length.

It is therefore premature to identify only the16MiB threshold as the cause.
Large outcome JSON is a plausible explanation: the public codec stores a payload
column and lossless original _row_json,so column chunks can be large even when
compressed files are small. A100-row group does not imply100 small rows. The
previously reported large average payload shape supports this hypothesis,but says
nothing conclusive about these8 batches. Matching hashes cannot rule out a bad
producer,unsafe declarations or consistently corrupted unsigned metadata.

The guard protects approval under a bounded-decoding policy. It is not proof of
corruption. Observing bounded footer declarations does not decode those pages.
Conversely,footer total_uncompressed_size is encoded-page bytes including page
headers,NOT a proved bound on decoded JSON/Python/Arrow memory or largest row.

The reported721587435 expanded-byte total EXCLUDES each failed _footer call:
the accumulator only increases when that function returns. It is not the complete
876-file total. Likewise690858 is matched footer rows,not decoded or unique rows.
The approximate723 rows in8 blocked batches remain declared counts,not established
missing unique observations. Receipt outcomes1513/1613 and universe71612/72112 are
unauthenticated deletion claims,not current-hot absence or unique recovery totals.

## Decision and next steps

1. Preserve the original BLOCKED report and three evidence files unchanged.
   Keep archive deletion and schedules held. Do NOT rerun the old verifier with
   changed limits,filtered catalog or edited manifests.
2. Owner can separately commission encrypted opaque preservation NOW after the
   harmless disk rehearsal. It need not await all876 passing. Use the existing
  7-Zip AES-256/header-encrypted external-disk procedure in
   ARCHIVE_RECOVERY_PLAN_2026-10-18.md,including the preserved BLOCKED report as a
   fourth opaque file. Record its own hash and compare it on readback as well.
   No inner-ZIP extraction,plaintext password in commands,key read or cleanup.
   This improves availability; it does not authenticate historical receipts.
3. Run the NEW diagnostic below after green merge. It observes all18 outcomes
   batches,including10 controls,and rechecks their manifests and byte hashes.
4. If the8 original codes/ordinals reproduce and ONLY the column-size predicate
   fails,design a separately reviewed large-outcomes recovery profile. Do not
   increase the generic16MiB limit. The profile must derive fixed limits from
   these measurements,test worst-case synthetic dictionary/large-value files,
   impose independent OS-level process-memory/time/disk limits and prove exact
   readback in isolation. Per-row iter_batches is NOT by itself a hard memory
   bound: a dictionary,page or single value can be large. No such profile is
   commissioned or implemented by this diagnostic.
5. If codec,external path,value count,offset,row-group totals,file budget or parse
   errors appear,keep the files quarantined and investigate producer/schema
   compatibility first. No external references are followed. A different error
   cannot be relabelled as a harmless large-payload case.
6. Complete matching authenticated independent custody,typed version-preserving
   isolated restore and cold-reader/application acceptance before any selective
   live restoration or retention. Preserve the six-table dependency/header and
   hot/cold overlap boundaries already documented. No bulk live UPSERT or rollback
   into the500MB database. Licensed/frozen-period research remains sealed.

## What the new tool does and does NOT prove

`outcomes_footer_diagnostic.py` validates the pinned full876 catalog/directory
using existing guards,then opens only the36 selected outcomes members. Nonselected
archives,including the five nonstandard names and one other file,remain unopened.
The same32MiB member,256KiB footer,Thrift limits,schema metadata and64 row-group
limits apply. The original helper files/constants are UNCHANGED and upload-pinned.
The CLI also fixes the original full ZIP pin. All18 are required; no subset switch.

For each outcomes file it reports:

- catalog ordinal,byte/footer sizes,declared row count and row-group count;
- for each of the FIVE FIXED PUBLIC column keys,max/sum compressed/uncompressed
  bytes and counts of failures of each named original predicate;
- location,row-group-size/count and128MiB file-total checks;
- result of invoking the original _footer guard unchanged;
- whether the only observed issue is16MiB size,AND the original result is the
  column-expansion error. Reproduction also requires the exact8 ordinals AND codes.

It prints no physical paths,Drive IDs,raw column paths,codec strings,statistics,
min/max market values,JSON contents or raw errors. No .statistics/.to_dict or
Parquet row-reader methods are called. The total for all18 and total for originally
blocked files are separate footer declarations. The latter can explain what the
earlier aggregate omitted,only if the original8 pattern reproduces on the same pins.

OUTCOMES_FOOTER_DIAGNOSTIC_ONLY_NOT_ACCEPTANCE(exit0) means the18 metadata
observations completed,NOT that any old rejection was waived. Original guard
results remain visible. BLOCKED(exit2) means the diagnostic itself could not
complete its bounded observations. Both retain full-catalog coverage,verification
authority,custody,restore,deletion,training and approval flags FALSE.

Memory is sequential and input/metadata bounded,not an OS-enforced process-memory
guarantee. The declaration of a large column is measured without allocating its
uncompressed page total. No new decoder,copy,restore,signature,network,credential,
task,capture or hosted-write action exists here. Original868/876 remains BLOCKED.

## One additive six-file PR

Exact base `6a06f4d828fb3be265510ca9a5f21b1e534ec583`.
Source root `C:\Users\banga\Desktop\kiran_share_market`; destination root is your
NEW clean public upload clone. Every relative source maps to the identical
destination-relative path:

1. `outcomes_footer_diagnostic.py` → `outcomes_footer_diagnostic.py`
2. `tests/test_outcomes_footer_diagnostic.py` → `tests/test_outcomes_footer_diagnostic.py`
3. `OUTCOMES_FOOTER_HANDOFF_2026-10-19.md` → `OUTCOMES_FOOTER_HANDOFF_2026-10-19.md`
4. `outcomes_footer_upload_check.py` → `outcomes_footer_upload_check.py`
5. `tests/test_outcomes_footer_upload_check.py` → `tests/test_outcomes_footer_upload_check.py`
6. `OUTCOMES_FOOTER_UPLOAD_2026-10-19.json` → `OUTCOMES_FOOTER_UPLOAD_2026-10-19.json`

Do not copy earlier package files,private report/catalog/ZIP/inventory,keys,CSV,
generated fixtures or local continuity docs. No installed capture dependency.

### Upload block1 — normal PowerShell,new clean clone root

Use established core.autocrlf=false clean-clone routine. If main changed,STOP for
a reviewed refresh,not a pin edit. Explicit reviewed3.13.9 interpreter only.

```powershell
$ErrorActionPreference='Stop'
$reviewPython='C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
$footerBase='6a06f4d828fb3be265510ca9a5f21b1e534ec583'
$head=& git rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $head -ne $footerBase) {throw 'EXACT_BASE_REQUIRED'}
$dirty=@(& git status --porcelain)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -ne 0) {throw 'CLEAN_CLONE_REQUIRED'}
& git switch -c outcomes-footer-diagnostic-20261019
if ($LASTEXITCODE -ne 0) {throw 'BRANCH_FAILED'}
$footerSource='C:\Users\banga\Desktop\kiran_share_market'
$footerManifest=Get-Content -Raw -LiteralPath (Join-Path $footerSource 'OUTCOMES_FOOTER_UPLOAD_2026-10-19.json') | ConvertFrom-Json
$footerFiles=@($footerManifest.files.PSObject.Properties.Name)
if ($footerFiles.Count -ne 6) {throw 'EXACT_SIX_PATHS_REQUIRED'}
foreach ($relative in $footerFiles) {
  $destination=Join-Path $PWD.ProviderPath $relative
  $parent=Split-Path -Parent $destination
  if (-not (Test-Path -LiteralPath $parent)) {New-Item -ItemType Directory -Path $parent | Out-Null}
  Copy-Item -LiteralPath (Join-Path $footerSource $relative) -Destination $destination -ErrorAction Stop
}
& git add -- @footerFiles
if ($LASTEXITCODE -ne 0) {throw 'STAGING_FAILED'}
& $reviewPython -B outcomes_footer_upload_check.py --base $footerBase
if ($LASTEXITCODE -ne 0) {throw 'FOOTER_UPLOAD_BLOCKED'}
```

Require OUTCOMES_FOOTER_PACKAGE_VERIFIED_REQUIRES_TESTS_AND_EXACT_COMMIT_CI,
failures[]. The checker verifies exact base,index/worktree,all six paths and eight
public prerequisite hashes. Manifest self-pin is null; its staged/worktree bytes
must match. Old guard/source hashes must stay pinned; no substitution.

### Upload block2 — focused tests,lint and types

```powershell
$ErrorActionPreference='Stop'
& $reviewPython -B -m pytest -q -p no:cacheprovider tests/test_outcomes_footer_diagnostic.py tests/test_outcomes_footer_upload_check.py tests/test_archive_catalog_verify.py tests/test_archive_commissioning_hold.py
if ($LASTEXITCODE -ne 0) {throw 'FOCUSED_TESTS_FAILED'}
& $reviewPython -B -m pyflakes outcomes_footer_diagnostic.py outcomes_footer_upload_check.py tests/test_outcomes_footer_diagnostic.py tests/test_outcomes_footer_upload_check.py
if ($LASTEXITCODE -ne 0) {throw 'LINT_FAILED'}
$footerTypeCache=Join-Path $env:TEMP ('footer-diagnostic-mypy-'+[guid]::NewGuid().ToString('N'))
& $reviewPython -B -m mypy --strict --follow-imports=silent --cache-dir $footerTypeCache outcomes_footer_diagnostic.py outcomes_footer_upload_check.py
if ($LASTEXITCODE -ne 0) {throw 'TYPING_FAILED'}
& git diff --cached --check
if ($LASTEXITCODE -ne 0) {throw 'WHITESPACE_FAILED'}
```

### Upload block3 — identity presence,then owner commit/PR

```powershell
$ErrorActionPreference='Stop'
$identityName=& git config user.name
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($identityName)) {throw 'OWNER_SET_REPO_LOCAL_NAME_FIRST'}
$identityMail=& git config user.email
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($identityMail)) {throw 'OWNER_SET_REPO_LOCAL_EMAIL_FIRST'}
```

Commit: `Add bounded outcomes footer diagnostics without relaxing guards`.
One plain-line PR description: `Separate outcomes footer failure predicates while preserving the original verification block and deletion hold.`
No attribution/trailers. Owner uploads/merges only after independent review and
exact-final-SHA hosted CI green. No workflow/task enablement,installation or service
change. Monday capture must not be touched.

## Owner diagnostic AFTER green merge

Use a fresh clean merged tools checkout; normal PowerShell. Keep old output and
evidence unchanged. This is a new diagnostic,not a retry of the original verifier.
Use the FULL catalog pin from the preserved verifier report;4e151219 is only an
abbreviation and must never be used as a hash. Do not generate a replacement pin
to accept changed bytes. Enter the full pin locally,not into chat.

Preview block:

```powershell
$ErrorActionPreference='Stop'
$reviewPython='C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
$allCatalog=Read-Host 'Original preserved all-history catalog JSON path'
$recoveryBundle=Read-Host 'Original preserved ZIP path'
$allCatalogPin=Read-Host 'Full catalog SHA256 from preserved verifier report (local only)'
if ($allCatalogPin -cnotmatch '^[a-f0-9]{64}$') {throw 'FULL_RECORDED_PIN_REQUIRED'}
if ((Get-FileHash -LiteralPath $allCatalog -Algorithm SHA256).Hash.ToLowerInvariant() -cne $allCatalogPin) {throw 'CATALOG_CHANGED_PRESERVE_DO_NOT_REPIN'}
$bundlePin='4f6bd76d5368226d23fb9d369b4635e0fd485247755e443f7d18add2b9dd095b'
& $reviewPython -B outcomes_footer_diagnostic.py --catalog $allCatalog --bundle $recoveryBundle --catalog-sha256 $allCatalogPin --bundle-sha256 $bundlePin
if ($LASTEXITCODE -ne 0) {throw 'FOOTER_DIAGNOSTIC_PREVIEW_BLOCKED'}
```

Require PREVIEW,all input/member/row/network/credential/write counters0. The
owner's separate Get-FileHash above reads the catalog; the Python preview does not.

Separate confirmed block:

```powershell
$ErrorActionPreference='Stop'
& $reviewPython -B outcomes_footer_diagnostic.py --catalog $allCatalog --bundle $recoveryBundle --catalog-sha256 $allCatalogPin --bundle-sha256 $bundlePin --confirm-footer-diagnostic
if ($LASTEXITCODE -ne 0) {throw 'FOOTER_DIAGNOSTIC_BLOCKED_PRESERVE_OUTPUT'}
```

Expected diagnostic completion: inspected18,member-open attempts36,nonselected
members/row pages/network/credentials/writes0. Compare the exact original8 pattern
and codes,not just a count. Retain the complete redacted output privately.
Share only summary counts,pattern-reproduced/size-only booleans,failed predicate
keys and per-failing-file fixed-column size maxima. No values or paths are needed.
If codes/ordinals differ,preserve and investigate; no additional acceptance inferred.
Exit0 here does NOT mean the old868/876 BLOCKED result changed.

## Custody,restore and remaining work

Keep encrypted opaque copying moving independently of this diagnosis. Key-note,
harmless encrypted-disk rehearsal,Drive used/limit/retention and actual DB-backup
availability facts remain owner prerequisites. No new signing or key reads here.
The future isolated recovery worker must preserve exact source bytes,versions and
row identities,perform lossless codec+typed Postgres/application readback and bind
the SAME generation to independent custody. No SQLite TEXT rehearsal substituted
for typed restore. No zero-filled history or automatic promotion from partial data.
Original archive deletion unconditionally denies; its eight-pin upload closure
includes that production source. No boolean can unlock deletion.

Carry forward unchanged: full writer/cold-reader integration,dedup/bounded retention,
capacity alerting;production failure-alert delivery;consumed drill preserved and
future drill requires startup evidence;localPG17 non-loopback service/exposure
decision;unattributed Windows Time/root dispersion;14Oct saved report absent(not
proof observations absent);legacy auditexit2/shared-root writes;guided/daily SID and
separate-date commissioning;OPTION_CAPTURE_ENABLED off;frozen research sessions
ending1Oct;Friday75/75/0 unsigned owner claim. Installed19Oct capture stays untouched.
No catch-up,same-slot retry,ACL/permission/marker/reset/release/Streamlit changes.
ML/backtesting remain mandatory,with real fitting/licensed labels/performance and
promotion gated by frozen paper-study/evidence policy;2025/2026 remain sealed.

## Research,technology radar and verification

[Arrow ColumnChunkMetaData](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.ColumnChunkMetaData.html)
documents the distinct size,codec,value-count and file-path fields.
[Apache Parquet format](https://github.com/apache/parquet-format/blob/master/src/main/thrift/parquet.thrift)
defines total_uncompressed_size as column-chunk uncompressed page bytes including
headers,not decoded-memory footprint. Current docs inform interpretation; installed
PyArrow/runtime pins are NOT upgraded. [Supabase changelog](https://supabase.com/changelog)
reviewed via HTML fallback after the markdown endpoint failed content-type handling.
Supabase skill used for recovery/hold boundaries; no DB access or schema work.

Adopt existing strict ZIP/Parquet metadata guards and synthetic large-column
fixtures. No new paid tier,plugin,account or dependency. Reject raw footer dumps,
statistics/minmax inspection,broad extraction,global budget increases and live
restore attempts. Future OS-isolated recovery is worth building after measurements;
iter_batches alone is not sufficient resource containment. Highest leverage remains
the encrypted independent replica and matching measured restore witness.

Builder Windows focused command above: **76 passed,0 skipped**. Includes19 new
diagnostic tests,12 new upload-checker tests,original876-verifier regression and
production deletion-hold regression. Lint4 files clean;strict mypy2 modules passes.
Synthetic large-column fixture reproduces the original rejection without changing
the guard. A source-level test forbids statistics/raw metadata dump/row-reader paths.
Independent reviewer reported31 diagnostic/package tests passing and no remaining
blocking findings. One causal-summary finding was fixed: both original error codes
and ordinal set are now required; a different parse error cannot be labelled a
size-only explanation. Five payload/eight prerequisite hashes match locally and
the prerequisites were fetched read-only at the exact public base before hashing.

Linux rehearsal NOT RUN: Docker daemon-pipe inspection was permission denied;
no ACL/permission changes or bypass. Owner actual-index gate and exact-final-SHA
hosted Linux/full-repository CI remain required. Counts overlap,not cumulative.
Actual private cause,complete876 expansion total,encrypted copy,custody,logical/
native/app restore,owner staged-checker acceptance and hosted CI are NOT established.
