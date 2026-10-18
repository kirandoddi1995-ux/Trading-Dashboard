# Preserved archive recovery: verify broadly,restore selectively,delete nothing

## Judgment and current evidence

Treat the entire876-batch collection as recovery-critical,not just the11–16October
selection. Owner reports874 full-deletion receipts and2 with no deletion recorded
(one outcomes,one universe_membership),all876 pairs present,zero missing/orphan
sides/inconsistencies,90 operational-date-summary entries. This supports a wider
recorded-deletion history; it does NOT establish which logical rows are absent
today,whether later versions superseded them,or which reader is currently affected.
Do not sum archived rows across overlapping versions and call it unique data loss.

The earlier122/98755 byte/footer result and all newer private results remain
owner-reported. The builder has not opened those files or queried the database.
Original incident inventory and ZIP remain immutable; new catalog has a separate
raw-byte pin. Preserve all three even if a future check blocks.

Read-only GitHub access independently resolved merged main:
`6b873593f3cdc8dec8cbf265c6e15dfc21a7e0e9`(PR46). Public prerequisite SHA256
values were computed from files fetched at that exact commit; owner index check
still required. No GitHub write,push,setting,workflow or hosted DB change occurred.

## Order — do not wait for another package to prepare custody

1. **Preserve exact bytes off the PC.** Owner can prepare the harmless encrypted-
   disk rehearsal now. After explicitly commissioning preservation,use the bounded
   GUI procedure below. Do not make preservation of these unsigned legacy files
   wait for a new signing key. Key custody is a separate urgent requirement for
   ledger recovery and authenticated future witnesses. A copy helps availability;
   it cannot retroactively authenticate yesterday's unsigned receipts.
2. **Verify all876 pairs.** New owner-only offline verifier checks every catalogued
   manifest body,Parquet byte hash,schema and bounded footer row count. All must
   pass; no table/date subset can be called full coverage. No row pages are read.
3. **Authenticate custody and rehearse recovery.** Bind original ZIP,incident
   inventory,all-history catalog,byte/footer report,independent replica and recovered
   plaintext hashes to one generation with protected anchors and dedicated recovery
   signing material. Existing HMAC codecs are foundations,not current custody proof.
   Require readback from the actual disconnected disk,not a second same-PC copy.
4. **Build a dependency-aware isolated logical restore.** First preserve a fresh
   consistent-cut hot-data/schema/header snapshot using the reviewed exporter;
   an archive taken over90 receipt days is not one consistent-cut database image.
   Separate staging database
   or cold-store target; preserve original table,batch,row key,version and receipt
   identity. Verify counts/content-derived batch IDs/exact original JSON/schema,
   detect duplicate-key conflicting versions and missing parent/header records.
   No ON CONFLICT replacement into live tables and no generic whole-project rollback.
   Recovery-only machine processing needs its own reviewed commissioning;2025/2026
   data remains sealed against research/analysis. A footer cannot establish row dates.
5. **Prove app reads before changing live state.** Inventory every historical reader,
   exercise exact cold lookup and deterministic hot/cold overlap reconciliation,
   and measure present-day coverage gaps. Restore only missing,required,validated
   records to hot storage if there is a reviewed reason and capacity budget. Historical
   features must report unavailable/insufficient coverage until that reader is
   commissioned; never interpret archive existence as a working app data path or
   silently fill missing features with neutral/zero values. Prefer
   verified cold reads for bulk history; do not stuff the full archive back into500MB.
6. **Commission retention last.** No deletion before matching custody,restore and
   cold-reader evidence. Include evidence ledger,daily volumes and parent/header
   dependencies: this876-batch ZIP is NOT a full database/ledger backup.

Monday manual capture and its installed capsule are independent. No new task,
producer,calendar/window change,replay,catch-up or same-slot retry belongs here.

## New verifier — precise scope and bounds

`archive_catalog_verify.py` builds on the exact all-history parser and ZIP/file
guards already merged. It retains the876 denominator and six per-table counts:
market_quotes245,NAV231,universe_membership154,versions119,scanner109,outcomes18.
It requires874 full-deletion claims plus the exact2 no-deletion source counts.
These are scope checks,not authentication of those claims.

Confirmed CLI pins the original ZIP SHA256:
`4f6bd76d5368226d23fb9d369b4635e0fd485247755e443f7d18add2b9dd095b`.
The all-history catalog gets its own exact raw hash. Replacing either input or
filtering its receipts is not a recovery fix. Preserve the incident inventory pin:
`110ce3642a7afc96d71204c9f1a9f116fd9900d81959887e9db642e8a0acdc32`.

The default preview reads nothing. Confirmed run streams the ZIP hash in64KiB
blocks,checks the full directory,then reads one bounded selected manifest and
Parquet file at a time. Expected member-open attempts1752. The five nonstandard
names and one other file are counted and left UNOPENED. No extraction,network,
credentials,Parquet row reader,file write,signature creation or DB connection.
Output names only fixed source/stage/error keys and sorted catalog ordinal for a
failed batch; no paths,Drive IDs,market values or raw errors. Generic member-read
failures stay redacted. A failure can never become successful partial coverage.

Existing per-member/footer/row-group bounds remain unchanged. Batches max2000
rows,Parquet max32MiB,declared expanded batch max128MiB. This new all-catalog
review caps the SUM of footer-declared expanded sizes at4GiB; it never allocates
or decodes that declared total. The original fixed122 verifier's512MiB aggregate
budget is untouched. Catalog max5MiB,ZIP max2GiB,central directory bounds unchanged.
If a resource guard blocks,preserve the result and review; no flag enlarges bounds.
Do not relax a schema to accept an old producer mismatch without investigating it.
A schema-version mismatch alone does not prove the underlying bytes are lost.

Full success means only ALL_876_BYTES_AND_FOOTERS_MATCH_NOT_RESTORE_OR_CUSTODY.
Footer counts remain declarations,not decoded/logically restored rows. Matching
hashes establish consistency with the pinned catalog,not a signature or complete
source history. Content-derived batch IDs,historical row dates,Drive identity,
independent custody,logical/Postgres/application restore,deletion,training and
approval flags all remain false. The pure API accepts supplied pins for synthetic
fixtures; production CLI additionally fixes the real preserved ZIP pin.

## Why deletion stays blocked — permanent commissioning contract

Production `archive_maintenance.require_commissioned_delete()` still rejects
unconditionally BEFORE credentials,network or delete transactions. Environment
flags,workflow success,catalog matching and this report cannot unlock it. The
scheduled archive remains in the owner-confirmed18October no-I/O hold.

A future replacement needs one reviewed,transaction-enforced deletion capability,
not another enable boolean. Its acceptance contract must include:

- Exact candidate primary keys AND original payload hashes,source/schema/policy,
  generation root,selection cutoff and retained parent/live dependencies.
- Independently protected predecessor/successor anchors; authenticated manifest,
  two matching measured copy/readback receipts,and matching restore witness for
  this SAME generation. Reject missing,forged,stale,wrong-scope and rollback proofs.
- Proven cold-aware application readers and frozen-period custody/retention rules.
   Archive expiry is prohibited while a hot deletion depends on that generation.
   Dedup may share content-addressed payloads only with a complete reference graph;
   garbage collection must protect every retained generation and restore witness.
   Capacity budgets for free Drive and offline replicas need measured limits and
   sustainable retention,not an assumption of unlimited free history.
- Append-only receipt publication and root CAS/fencing; bounded source locks only
  during final recheck+exact-payload deletion+checkpoint transaction,not network IO.
- Unknown COMMIT reconciliation and replay-idempotence; failure retains source rows.
  No new generation may inherit an earlier generation's custody/restore approval.
- Native Postgres fault/race tests and deployment of the DB-side guard. Python-only
  gating is not sufficient if a writer can issue unrestricted DELETE elsewhere.
  Existing roles/grants require a separately owner-reviewed commissioning plan;
  NO permission/ACL change is made or requested by this package.
- Independent alerts on custody/restore age,copy capacity,archive/DB drift and
  blocked retention. Source retention must stop on expired/missing evidence.

Software cannot prevent a database owner from bypassing controls with direct SQL.
That authority boundary must remain explicit. Never claim a current perpetual
guarantee from a passing fixture or self-signed JSON. Current guarantee is narrower:
the reviewed production archive entry points remain DENIED and tested as such.

## One additive PR — exact six-file upload

Source root `C:\Users\banga\Desktop\kiran_share_market`; destination is your new
clean public upload clone at exact base6b873593f3cdc8dec8cbf265c6e15dfc21a7e0e9.
Each source-relative path maps to the SAME destination-relative path:

1. `archive_catalog_verify.py` → `archive_catalog_verify.py`
2. `tests/test_archive_catalog_verify.py` → `tests/test_archive_catalog_verify.py`
3. `ARCHIVE_RECOVERY_PLAN_2026-10-18.md` → `ARCHIVE_RECOVERY_PLAN_2026-10-18.md`
4. `archive_verify_upload_check.py` → `archive_verify_upload_check.py`
5. `tests/test_archive_verify_upload_check.py` → `tests/test_archive_verify_upload_check.py`
6. `ARCHIVE_VERIFY_UPLOAD_2026-10-18.json` → `ARCHIVE_VERIFY_UPLOAD_2026-10-18.json`

No prior package is recopied. No CSV/private input,key,receipt,generated data,
continuity doc or installed capture file is uploaded. All additions; inactive.

### Owner upload block1 — normal PowerShell at a fresh clean clone root

Use the established clone routine(core.autocrlf=false). If main changes,STOP for a
reviewed base refresh; do not alter this package's pins. Explicit interpreter only.

```powershell
$ErrorActionPreference='Stop'
$reviewPython='C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
$verifyBase='6b873593f3cdc8dec8cbf265c6e15dfc21a7e0e9'
$head=& git rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $head -ne $verifyBase) {throw 'EXACT_BASE_REQUIRED'}
$dirty=@(& git status --porcelain)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -ne 0) {throw 'CLEAN_CLONE_REQUIRED'}
& git switch -c archive-full-verification-20261018
if ($LASTEXITCODE -ne 0) {throw 'BRANCH_FAILED'}
$verifySource='C:\Users\banga\Desktop\kiran_share_market'
$verifyManifest=Get-Content -Raw -LiteralPath (Join-Path $verifySource 'ARCHIVE_VERIFY_UPLOAD_2026-10-18.json') | ConvertFrom-Json
$verifyFiles=@($verifyManifest.files.PSObject.Properties.Name)
if ($verifyFiles.Count -ne 6) {throw 'EXACT_SIX_PATHS_REQUIRED'}
foreach ($relative in $verifyFiles) {
  $destination=Join-Path $PWD.ProviderPath $relative
  $parent=Split-Path -Parent $destination
  if (-not (Test-Path -LiteralPath $parent)) {New-Item -ItemType Directory -Path $parent | Out-Null}
  Copy-Item -LiteralPath (Join-Path $verifySource $relative) -Destination $destination -ErrorAction Stop
}
& git add -- @verifyFiles
if ($LASTEXITCODE -ne 0) {throw 'STAGING_FAILED'}
& $reviewPython -B archive_verify_upload_check.py --base $verifyBase
if ($LASTEXITCODE -ne 0) {throw 'VERIFY_UPLOAD_BLOCKED'}
```

Require ARCHIVE_VERIFY_PACKAGE_VERIFIED_REQUIRES_TESTS_AND_EXACT_COMMIT_CI with
failures[]. Exact payload,prerequisite base/index/worktree hashes and staged paths
must match. Manifest self-pin is null; manifest staged bytes must equal worktree.

### Owner upload block2 — focused test line,lint,strict typing

```powershell
$ErrorActionPreference='Stop'
& $reviewPython -B -m pytest -q -p no:cacheprovider tests/test_archive_catalog_verify.py tests/test_archive_verify_upload_check.py tests/test_archive_catalog_reconcile.py tests/test_archive_commissioning_hold.py
if ($LASTEXITCODE -ne 0) {throw 'FOCUSED_TESTS_FAILED'}
& $reviewPython -B -m pyflakes archive_catalog_verify.py archive_verify_upload_check.py tests/test_archive_catalog_verify.py tests/test_archive_verify_upload_check.py
if ($LASTEXITCODE -ne 0) {throw 'LINT_FAILED'}
$verifyTypeCache=Join-Path $env:TEMP ('archive-verify-mypy-'+[guid]::NewGuid().ToString('N'))
& $reviewPython -B -m mypy --strict --follow-imports=silent --cache-dir $verifyTypeCache archive_catalog_verify.py archive_verify_upload_check.py
if ($LASTEXITCODE -ne 0) {throw 'TYPING_FAILED'}
& git diff --cached --check
if ($LASTEXITCODE -ne 0) {throw 'WHITESPACE_FAILED'}
```

### Owner upload block3 — identity before commit;final-SHA CI before merge

```powershell
$ErrorActionPreference='Stop'
$identityName=& git config user.name
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($identityName)) {throw 'OWNER_SET_REPO_LOCAL_NAME_FIRST'}
$identityMail=& git config user.email
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($identityMail)) {throw 'OWNER_SET_REPO_LOCAL_EMAIL_FIRST'}
```

Owner commit: `Verify all preserved archive batch bytes and footers`.
One plain-line PR description: `Add read-only full-catalog verification and a custody-first recovery plan while retaining the deletion hold.`
No attribution/trailers. Owner uploads and merges only after independent review
and exact-final-SHA hosted checks green. Nothing enabled; no Monday dependency.

## Owner offline verification AFTER green merge

Use a fresh clean merged tools checkout,normal PowerShell. Keep the same NEW
all-history JSON and original ZIP from the successful reconciliation. Do not rerun
the SQL export just to change inputs or discard the old catalog. Original incident
inventory is preserved but not an argument to this separate876 verification.

Preview block:

```powershell
$ErrorActionPreference='Stop'
$reviewPython='C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
$allCatalog=Read-Host 'Preserved private all-history catalog JSON path'
$recoveryBundle=Read-Host 'Original pinned private ZIP path'
$allCatalogPin=(Get-FileHash -LiteralPath $allCatalog -Algorithm SHA256).Hash.ToLowerInvariant()
$bundlePin='4f6bd76d5368226d23fb9d369b4635e0fd485247755e443f7d18add2b9dd095b'
& $reviewPython -B archive_catalog_verify.py --catalog $allCatalog --bundle $recoveryBundle --catalog-sha256 $allCatalogPin --bundle-sha256 $bundlePin
if ($LASTEXITCODE -ne 0) {throw 'ARCHIVE_VERIFY_PREVIEW_BLOCKED'}
```

Require PREVIEW and all reads/member-open/row/network/credential/write counters0.
Separate confirmed block(owner offline IO only):

```powershell
$ErrorActionPreference='Stop'
& $reviewPython -B archive_catalog_verify.py --catalog $allCatalog --bundle $recoveryBundle --catalog-sha256 $allCatalogPin --bundle-sha256 $bundlePin --confirm-byte-footer-read
if ($LASTEXITCODE -ne 0) {throw 'ARCHIVE_VERIFY_BLOCKED_PRESERVE_INPUTS'}
```

Require matched_batches876,full_catalog_byte_footer_coveragetrue,failures[],all
authority/custody/restore flags false. A block is evidence,not permission to try
another pin. Report only redacted summary/fixed errors; never paste members or
market values. This is NOT permission to call the legacy row-reconstruction API.

## Optional explicit owner commissioning: encrypted preservation only

This section is a separate owner choice,not activated by upload or verifier success.
It commissions ONLY copying exact opaque evidence files,not signing,restoring rows,
training,deleting or changing tasks. First complete the existing harmless7-Zip
AES-256/header-encryption disk rehearsal with throwaway text. Never format the disk
or change ACLs. Password stored privately in password manager; never in commands,
screenshots,chat,plaintext notes or shell history.

Then use7-Zip GUI to create a NEW .7z on the empty external disk containing just
the preserved original ZIP,incident inventory and all-history catalog. Select7z
format,AES-256 and **Encrypt file names**. Keep originals on PC/Drive; no source
deletion,overwrite,move or inner-ZIP extraction. Test the encrypted outer archive
with7-Zip GUI,password entered only there. Record its ciphertext hash privately.

For a restore-of-copy check,close/reopen the external archive from the actual
external disk and recover ONLY these three opaque files into a NEW empty private
readback folder outside all checkouts. Do not open their inner ZIP or JSON contents.
Compare recovered hashes to the two fixed pins and original all-catalog hash:

```powershell
$ErrorActionPreference='Stop'
$copyZip=Read-Host 'Fresh recovered opaque ZIP file path'
$copyIncident=Read-Host 'Fresh recovered incident JSON file path'
$copyCatalog=Read-Host 'Fresh recovered all-history JSON file path'
$originalAllCatalog=Read-Host 'Original preserved all-history JSON file path'
$zipMatch=(Get-FileHash -LiteralPath $copyZip -Algorithm SHA256).Hash.ToLowerInvariant() -ceq '4f6bd76d5368226d23fb9d369b4635e0fd485247755e443f7d18add2b9dd095b'
$incidentMatch=(Get-FileHash -LiteralPath $copyIncident -Algorithm SHA256).Hash.ToLowerInvariant() -ceq '110ce3642a7afc96d71204c9f1a9f116fd9900d81959887e9db642e8a0acdc32'
$catalogMatch=(Get-FileHash -LiteralPath $copyCatalog -Algorithm SHA256).Hash -ceq (Get-FileHash -LiteralPath $originalAllCatalog -Algorithm SHA256).Hash
[pscustomobject]@{opaque_zip_hash_match=$zipMatch;incident_hash_match=$incidentMatch;all_catalog_hash_match=$catalogMatch;logical_restore_verified=$false;authenticated_custody_verified=$false;deletion_authorised=$false} | ConvertTo-Json -Compress
if (-not ($zipMatch -and $incidentMatch -and $catalogMatch)) {throw 'OPAQUE_REPLICA_READBACK_MISMATCH_KEEP_ALL_FILES'}
```

Require all three matches. Keep the encrypted .7z on the external disk,readback evidence,originals
and passwords; safely disconnect disk. Do not clean up evidence automatically.
This establishes owner-reported encrypted opaque-copy/readback evidence,not native
Postgres or authenticated historical custody. Report facts only. Protected key
custody and dedicated measured signed witnesses remain separate commissioning.

## Remaining work and boundaries

Build next: isolated typed/version-preserving row materialization and matching
application/cold-reader rehearsal,then authenticated generation custody contract,
then writer+retention+capacity-alert commissioning. Need present hot schema,
parent/header coverage,original versions and recovery-target identity; do not assume
this six-table collection contains ledger events,daily volumes,Auth,secrets,roles,
schema migrations or external object bytes. Ask owner only for DB-backup availability
facts,not passwords. No free-tier managed backup is presumed available.

Carry forward unchanged: independent key note/historical keys;Drive capacity and
retention;production failure-alert delivery;consumed drill untouched/future drill
needs durable startup evidence;non-loopback localPG17 service/exposure decision;
Windows Time/root dispersion unattributed;14Oct saved report absent≠observations
absent;legacy auditexit2/shared-root writes;guided/daily SID and separate-date
guided commissioning;OPTION_CAPTURE_ENABLED off;frozen research sessions end1Oct.
Friday75/75/0 remains unsigned owner claim. Monday19manualPrepare→Start remains
independent;20closed/21regular are owner calendar facts. No capture/task/service/
permission/ACL/pin/release/Streamlit changes. No catch-up or same-slot retry.

ML/backtesting remain mandatory but not inferred from archive recovery. Dataset,
quote-faithful event replay,frozen evaluation/calibration/promotion and registry
must retain licensing,labels,point-in-time and sealed-period gates;no real training,
performance claim or trading authority from these source changes.

## Research,technology radar and verification record

Reuse existing bounded ZIP/Parquet footer guards,stdlib streaming and pinned
PyArrow;7-Zip GUI avoids exposing passwords in subprocess arguments. No new paid
plan,plugin,account or service. Native PG17 typed restore is needed later,not
substituted with the earlier SQLite TEXT rehearsal. Reject whole-project rollback,
blind UPSERT,bulk rehydration into500MB and boolean-only deletion admission.

Primary sources:
[Supabase backup boundaries](https://supabase.com/docs/guides/platform/backups)
recommend regular off-site exports for free projects; custom role passwords and
external Storage object bytes are not established by database backups.
[Postgres17 pg_restore](https://www.postgresql.org/docs/17/app-pgrestore.html)
restores Postgres dump formats,not arbitrary Parquet; this legacy ZIP needs a
schema-aware recovery adapter and isolated acceptance,not pg_restore on the ZIP.
[Arrow ParquetFile](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.ParquetFile.html)
separates footer metadata from row-reading methods. Latest docs do not change our
pinned runtime. [Supabase changelog](https://supabase.com/changelog) checked via HTML
after the markdown endpoint failed content-type handling; no hosted action needed.

Builder verification: final focused command above **90 passed,0 skipped**; this
includes12 new full876 verifier tests,12 upload-checker tests and existing
reconciliation/deletion-hold regressions. Lint4 files clean,strict mypy2 modules
passes. Independent reviewer reported12 passing
tests plus a separate partial-overflow check(1 matched/2 checked/876 expected),
BLOCKED and full coverage false; no blocking findings. Five payload hashes and
seven exact-public-base prerequisite hashes are checked by the focused manifest
test. These counts are overlapping selections,not cumulative independent cases.

Linux rehearsal NOT RUN: Docker image inspection hit daemon-pipe permission denied.
No permission/ACL change or bypass attempted. Exact-final-SHA hosted Linux/full
repository checks are required. Public prerequisite pins were compared to exact
GitHub source,but actual owner base/index/worktree checker acceptance is pending.
Real private-input verification,encrypted copy,signed custody,logical/native/
application restore and hosted CI are NOT established by synthetic tests.
