# Preserved legacy generation: next recovery stage

## Assessment and order

Owner reports PR44 merged green as `a9bbcd4359a3f941fad24f7202aba155c1582eb2`.
Reported focused173/2skip and final-SHA hosted green are owner evidence; builder
did not run that hosted workflow or the owner's private files. The122 selected
batches /98755 recorded deleted rows now have an owner-reported complete byte and
footer match. That is meaningful progress, not logical restore or custody.

Preserve these EXACT raw file pins (no reformatting or repacking):

- Inventory: `110ce3642a7afc96d71204c9f1a9f116fd9900d81959887e9db642e8a0acdc32`
- ZIP: `4f6bd76d5368226d23fb9d369b4635e0fd485247755e443f7d18add2b9dd095b`

JSON key order/pretty-printing is not a problem: parsing is structural, while the
file hash deliberately binds the saved representation. The inventory's Drive IDs
are identifiers, not OAuth secrets. Do not repost them or put private files in a
PR; redact the chat copy through available owner UI if desired, without altering
the preserved file. No token/password rotation is justified solely by pasted IDs;
actual permissions and any genuine secret exposure are separate questions.

Priority: private key custody and harmless encrypted-disk rehearsal → preserve
encrypted independent replica of BOTH pinned files → measured readback → isolated
logical reconstruction/restore from each replica → authenticate current witnesses
against separately retained anchors → native PostgreSQL/application acceptance →
writer/cold-reader wiring → bounded retention. No past deletion becomes authorised
retroactively. No new deletion, hosted restore, compaction or research unsealing.

## What this package implements

`legacy_archive_rehearsal.py` has two deliberately separate surfaces:

1. **Owner directory-only CLI.** Exact hash-bound inventory/ZIP; only ZIP names and
   central-directory metadata are classified. It reads the opaque compressed ZIP
   for hashing but never opens a ZIP member, decodes rows, writes, contacts Drive,
   reads keys or runs capture. Results contain counts by the six existing schemas,
   incident/outside-incident pairs, orphan sides, nonstandard names and other files.
   Whole ZIP memory is bounded by the existing2GiB limit; this is not constant-memory
   streaming. Run outside capture, with adequate RAM; oversized/split/unsupported
   inputs require review, not repacking or relaxing pins.
2. **Inactive row-rehearsal and authentication APIs.** `reconstruct` calls the full
   legacy codec after complete byte/footer acceptance. It recomputes content batch
   identities, validates unique source keys WITHIN each batch, and checks every
   analytical column against original row JSON. Each batch is recreated/read back
   in a separate in-memory SQLite TEXT journal. No filesystem target or PostgreSQL
   connection exists. Cross-batch versions stay separate; no silent merge/dedup.
   Only digests/counts enter the witness, never raw row values.

This second surface is NOT commissioned on real files. All builder fixtures are
generated synthetic2022 rows. No real2025/2026 archive rows were decoded here.
No CLI exposes row reconstruction, signing, keys, a production restore or deletion.

The signed witness uses existing `catalog_receipts` HMAC-SHA256 and dedicated
`legacy-archive:drive-rehearsal` / `legacy-archive:disk-rehearsal` scopes. Verification
requires predecessor and successor anchors supplied from independently protected
state, expected inventory/ZIP hashes and the correct keyring. The body and receipt
must agree. Wrong keys/scopes, body substitution, changed input generations,
rollback anchors, omitted batches and expanded authority fail closed.

HMAC authenticates a key holder's current statement; it is NOT public-key
nonrepudiation, historical provenance, trusted time, physical independence,
encryption proof or evidence that a particular runtime executed honestly. Do not
bootstrap a trusted anchor from the same untrusted bundle or treat a new signature
as an old pre-deletion receipt. Caller-supplied witness objects are not execution
attestation. Root durability/CAS, runtime-source measurement and commissioning
remain outside this pure API. Existing catalogue/ledger roots are never changed.

Successful row reconstruction keeps PostgreSQL restore, persistent-target,
application recovery, encryption, physical independence, historical custody,
trusted clock, runtime identity, deletion authority and training flags FALSE.
An in-memory TEXT-journal roundtrip is not a typed Postgres/FK/RLS/role restore.
Existing two-replica six-table/full-image rehearsal applies to its own signed
generation format; this legacy ZIP cannot be relabelled as that newer format.

## Older files and the extra manifest

878 Parquet files minus122 selected incident batches suggests756 outside pairs,
but does NOT prove their dates, content, database deletion status or restorability.
One extra manifest may be an orphan or a nonstandard backup object. Do not delete
it or select arbitrary older batches for analysis. The directory-only result is
the next bounded classification, not a full archive health or date audit.

A common top-level folder prefix is not necessarily an explicit directory ZIP
entry. The new report separates central entries, explicit directory entries and
files to reconcile1758 versus878+879, and the previous1514-extra count. An additional
non-archive file is possible; it is not established until classified. No private
filenames, Drive IDs or raw errors are printed.

## Drill interpretation — preserved attempt remains consumed

Source research associates140 with task registration update,142 with disabling,
and325 with instance queued.110 is the recorded demand request. That pattern is
consistent with admission/queueing followed by the controller's disable, not a
proved process or worker start. No retained start/action-completion events were
reported, but `history_complete=false` means their absence is not proof no process
ran. Native0 is still not the worker's expected confirmed outcome. No retry/newID,
ACK, cleanup, re-enable, clock change or permission change is authorised.

Future drill architecture should separate Scheduler admission from actual worker
start: read-only power/interactive-session/condition checks before consuming a
new admission; a durable first-stage startup receipt with safe argv mode,
interpreter/script identity and classified failures; bounded queue/execute phase
deadlines; distinct intentional/failure result codes; native instance correlation;
disable readback; separate owner notification acknowledgment. No new native drill
is configured here. Do not infer battery/session cause from these four events.
Production failure-alert delivery remains unproved and is not a Monday dependency.

## Exact upload package — six additions, one PR

Base: `a9bbcd4359a3f941fad24f7202aba155c1582eb2`. Source root:
`C:\Users\banga\Desktop\kiran_share_market`. Each source below maps to the SAME
relative destination in the clean public clone; no staged substitutes:

1. `legacy_archive_rehearsal.py`
2. `tests/test_legacy_archive_rehearsal.py`
3. `LEGACY_REHEARSAL_HANDOFF_2026-10-18.md`
4. `legacy_rehearsal_upload_check.py`
5. `tests/test_legacy_rehearsal_upload_check.py`
6. `LEGACY_REHEARSAL_UPLOAD_2026-10-18.json`

Normal PowerShell, new branch of the established clean-clone routine, one block
at a time. Stop if newest green main differs; do not edit pins merely to pass.

```powershell
$ErrorActionPreference='Stop'
$reviewPython='C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
$sourceRoot='C:\Users\banga\Desktop\kiran_share_market'
$expectedBase='a9bbcd4359a3f941fad24f7202aba155c1582eb2'
$head=& git rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $head -cne $expectedBase) {throw 'EXACT_BASE_REQUIRED'}
$dirty=@(& git status --porcelain)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -ne 0) {throw 'CLEAN_CLONE_REQUIRED'}
$paths=@('legacy_archive_rehearsal.py','tests/test_legacy_archive_rehearsal.py',
 'LEGACY_REHEARSAL_HANDOFF_2026-10-18.md','legacy_rehearsal_upload_check.py',
 'tests/test_legacy_rehearsal_upload_check.py','LEGACY_REHEARSAL_UPLOAD_2026-10-18.json')
foreach ($path in $paths) {Copy-Item -LiteralPath (Join-Path $sourceRoot $path) -Destination (Join-Path $PWD $path) -ErrorAction Stop}
& git add -- $paths
if ($LASTEXITCODE -ne 0) {throw 'STAGE_FAILED'}
& $reviewPython -B legacy_rehearsal_upload_check.py --base $expectedBase
if ($LASTEXITCODE -ne 0) {throw 'PACKAGE_CHECK_BLOCKED'}
```

Require LEGACY_REHEARSAL_PACKAGE_VERIFIED_REQUIRES_TESTS_AND_EXACT_COMMIT_CI,
failures[]. Do not copy private JSON/ZIP, key notes or generated test directories.

```powershell
$ErrorActionPreference='Stop'
& $reviewPython -B -m pytest -q -p no:cacheprovider tests/test_legacy_archive_rehearsal.py tests/test_legacy_rehearsal_upload_check.py tests/test_archive_recovery_review.py tests/test_catalog_receipts.py tests/test_archive_commissioning_hold.py
if ($LASTEXITCODE -ne 0) {throw 'FOCUSED_TESTS_FAILED'}
& $reviewPython -B -m pyflakes legacy_archive_rehearsal.py legacy_rehearsal_upload_check.py tests/test_legacy_archive_rehearsal.py tests/test_legacy_rehearsal_upload_check.py
if ($LASTEXITCODE -ne 0) {throw 'LINT_FAILED'}
$typeCache=Join-Path $env:TEMP ('legacy-mypy-'+[guid]::NewGuid().ToString('N'))
& $reviewPython -B -m mypy --strict --follow-imports=silent --cache-dir $typeCache legacy_archive_rehearsal.py legacy_rehearsal_upload_check.py
if ($LASTEXITCODE -ne 0) {throw 'TYPES_FAILED'}
& git diff --cached --check
if ($LASTEXITCODE -ne 0) {throw 'DIFF_CHECK_FAILED'}
```

Check identity presence without printing it before committing:

```powershell
$ErrorActionPreference='Stop'
$identityName=& git config user.name
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($identityName)) {throw 'OWNER_SET_REPO_LOCAL_NAME_FIRST'}
$identityMail=& git config user.email
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($identityMail)) {throw 'OWNER_SET_REPO_LOCAL_EMAIL_FIRST'}
```

Commit: `Add inactive legacy reconstruction and anchored witness foundation`.
PR description (one plain line): `Add directory-only archive classification and inactive authenticated row-rehearsal APIs.`
No attribution/trailers. Require remaining independent source review and exact-final-
SHA hosted checks green; owner alone merges. Previous PR44 green is not this PR's
acceptance. Builder could not read the owner's separate clean clone (permission
denied); no permission changes attempted. New pins match local public-source
fixtures, not a builder-verified Git/index at this exact base. Owner checker is
mandatory. Linux/native/full-repository acceptance remains separately unverified.

## Owner directory-only check AFTER green merge

From a fresh clean checkout of this merged package; normal PowerShell, explicit
reviewed interpreter. Keep the same private path variables or enter them locally:

```powershell
$ErrorActionPreference='Stop'
$reviewPython='C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
$recoveryInventory=Read-Host 'Preserved private inventory JSON path'
$recoveryBundle=Read-Host 'Preserved private Drive ZIP path'
$inventoryPin='110ce3642a7afc96d71204c9f1a9f116fd9900d81959887e9db642e8a0acdc32'
$bundlePin='4f6bd76d5368226d23fb9d369b4635e0fd485247755e443f7d18add2b9dd095b'
& $reviewPython -B legacy_archive_rehearsal.py --inventory $recoveryInventory --bundle $recoveryBundle --inventory-sha256 $inventoryPin --bundle-sha256 $bundlePin
if ($LASTEXITCODE -ne 0) {throw 'DIRECTORY_PREVIEW_BLOCKED'}
```

Require PREVIEW, all input/write/credential/row-decode counters0. Separate block:

```powershell
$ErrorActionPreference='Stop'
& $reviewPython -B legacy_archive_rehearsal.py --inventory $recoveryInventory --bundle $recoveryBundle --inventory-sha256 $inventoryPin --bundle-sha256 $bundlePin --confirm-directory-read
if ($LASTEXITCODE -ne 0) {throw 'DIRECTORY_REVIEW_BLOCKED_PRESERVE_INPUTS'}
```

Share only summary JSON. This does NOT authorise real row-rehearsal/signing APIs.
They need a separately commissioned, resource-isolated owner adapter and readback
targets, measured runtime pins, protected key custody and independent review.

## Minimum owner prerequisites and remaining path

1. Keep both preserved files and originals; inspect18Oct scheduled archive log
   for no-I/O hold, not merely green. Keep DELETEfalse and releasefalse.
2. Secure the existing ledger signing-key note privately, including any available
   historical versions. Never paste keys or connection strings. Do not replace
   missing historical keys with a new key and claim old signatures verified.
3. Complete the existing harmless7-Zip AES-256/header-encryption rehearsal on the
   empty external disk using a password-manager-held password. No plaintext key
   backup to that disk, no password in command history, no ACL changes.
4. After that reviewed rehearsal, preserve encrypted copies of BOTH exact files
   and their fingerprints off the PC. Ciphertext hash/7-Zip integrity/readback and
   recovered plaintext hashes must all be measured. A same-PC copy alone is not
   independent custody. No real backup is commissioned by these source changes.
5. Future operational witness signing should use a dedicated recovery HMAC key,
   not casually expose/reuse the historical ledger key. Provision and retain it
   privately only under the reviewed commissioning adapter; no key is generated,
   read or requested in chat here. Independently retain predecessor/successor
   anchors with the key note/replica; same-bundle self-pins cannot reject rollback.
6. Supply Drive used/limit/retention and actual DB-backup availability facts only.
   Do not assume free-tier daily backups; do not click a hosted restore action.

Still open: native Postgres/application full restore and exact-cut capture;
authenticated custody with real replicas; all writer/cold-reader factories;
dedup/retention/capacity-alert commissioning; PostgreSQL non-loopback exposure
decision (no service changes); unattributed Windows Time issue;14Oct saved-report
absence; legacy auditexit2/shared-root writes; guided/daily SID integration and
separate-date guided rehearsal; undefined OPTION_CAPTURE_ENABLED and frozen1Oct
research sessions unchanged. Friday75/75/0 stays unsigned owner-reported evidence.

Monday19Oct uses proven manual Prepare→Start with genuine16Oct close.20closed/
21regular remain owner calendar facts. No new package dependency, capsule/task
change, catch-up or same-slot retry. ML/backtesting remains mandatory: dataset,
PAPER replay/cohort foundations are merged; licensed labels, frozen studies,
calibration/walk-forward/model registry and real performance/promotion remain gated.

## Technology radar and verification limits

Reuse existing lossless archive codec, bounded ZIP parser, in-memory SQLite and
HMAC anchored receipts. No new dependency, paid plan, plugin, account or process
agent. Considered: typed native Postgres restore (required later, not simulated by
SQLite); full DB rollback (rejected for this incident); broad extraction, archive
cleanup and automatic key reads (rejected). A good toolkit does not establish edge.

Next highest leverage: one protected independent replica plus a matching measured
restore witness. In parallel, a future drill needs actual startup evidence, not
more retries of the consumed task. Runtime agents may report only, never decide.

Primary references: Supabase database backup/changelog guidance; the existing
TaskScheduler library's Event325 definition and Microsoft historical event links;
BSI Windows event catalog for140/142; project archive and anchored-receipt source.
The old Microsoft325 link could not be fetched. Queue interpretation is corroborated
by source, not a proven cause or complete history of this PC's task.

Builder verification: selected Windows regression run **71 passed, zero skipped**:
all19 new tests, final manifest-content test, anchored-receipt tests and archive
commissioning-hold tests. This is NOT the full five-file owner suite: synthetic
Git/index negative cases and private-path cases still require the owner rehearsal.
Pyflakes clean for4 files; strict mypy passes2 modules. Six payload paths and8
prerequisite hashes match locally. Source/prerequisites agree with the disposable
public-source fixture, not a verified Git object at current main.

Independent agents remained usage-limited. Final independent source review,
Linux rehearsal, the actual-base staged checker and exact-final-SHA hosted CI
remain required before merge. Real directory classification, row reconstruction,
HMAC witness creation, encrypted replicas and native/application restore are NOT
builder-verified; no real archives or keys were read and no backups commissioned.
