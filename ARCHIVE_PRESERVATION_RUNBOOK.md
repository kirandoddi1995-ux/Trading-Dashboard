# Package A: present-day preservation witness (inactive)

Base: `1175e5515de0f9b7f6a682cdddda9f2f4a94eb4a`. One new-file-only PR.
No capture dependency, new schedule, hosted write, deletion, decoding, production
key read or automatic commissioning. The owner alone merges after exact-head CI.

## Decision and evidence boundary

The seven-original inventory and external hard disk are now OWNER-REPORTED as
recorded/reconnected/rechecked. The invalid stale-drive attempt is superseded,
not erased. Two original retained anchors remain original anchors; the other five
are FIRST_OBSERVED at 18:15 IST on 19 October, not historically authenticated.
No private inventory, artifact, encryption secret or real signing key was read by
the builder. Existing public synthetic resource acceptance is a different gate.

This package hashes opaque files only. Windows uses a read-only native file handle,
read sharing only, its file ID and final volume GUID; the same handle supplies the
bytes hashed. A wrong selected destination volume blocks even when bytes match.
There is no local-source fallback, cached PSDrive lookup, label-based acceptance,
null-hash equality or permission change. Linux uses descriptor device/file identity.
The private expected destination volume must be separately enrolled by the owner,
not blindly copied from an unexamined probe. Inspect the physical drive/cable and
actual selected path. Keep all volume IDs and paths private.

Different volumes do NOT establish different physical disks (partitions/VHDs can
share one disk). Physical-disk mapping is NOT implemented in A and cannot clear a
custody gate. External-device identification, disconnected storage, extraction and
Drive readback are typed OWNER REPORTS. Remote Drive object identity, failure-domain
independence, old receipt authenticity and database restore remain NOT VERIFIED.
A signature authenticates this present statement, not the historical truth of its
assertions. Every preservation report retains custody/restore/deletion/training false.

The dedicated Ed25519 key is unrelated to production ledger/catalog keys and to the
7-Zip passphrase. Never reuse/derive either. Public-key verification plus an externally
retained current generation AND digest prevents silently treating an old valid
signature as the latest record. A bundle's own claimed public key is not a trust root.
No key rotation, revocation, enrollment or checkpoint advancement happens implicitly.

## Upload: one block at a time, normal PowerShell

Use the existing clean-clone routine, LF checkout (`core.autocrlf=false`), exact base
above, a new branch, and explicit reviewed Python 3.13.9. Never bare `py`.
If main has advanced, STOP for a regenerated package; do not loosen pins/rebase by
editing this manifest. Do not copy the whole working folder or private inventory.

Copy these exact source-relative paths from
`C:\Users\banga\Desktop\kiran_share_market` to the SAME relative destinations in
the clean clone (eight files, all new):

1. `archive_preservation_inventory.py`
2. `archive_preservation_witness.py`
3. `tests/test_archive_preservation_inventory.py`
4. `tests/test_archive_preservation_witness.py`
5. `archive_preservation_upload_check.py`
6. `tests/test_archive_preservation_upload_check.py`
7. `ARCHIVE_PRESERVATION_RUNBOOK.md`
8. `ARCHIVE_PRESERVATION_UPLOAD.json`

No old manifest/checker, workflow policy, production runtime, capture helper or
private evidence file belongs in this upload. JSON/code hashes in the public
manifest are LF-normalized; recovery artifacts are always raw-byte hashed.

Set `$preservationPython` to the existing explicit venv Python path and require
`& $preservationPython -I -B -c "import sys; print(sys.version.split()[0])"`
to print `3.13.9`. Set `$ErrorActionPreference='Stop'`. Check every native exit
code explicitly; ErrorActionPreference alone does not enforce native exit success.

Stage only the eight paths listed above, then run:

```powershell
& $preservationPython archive_preservation_upload_check.py --base 1175e5515de0f9b7f6a682cdddda9f2f4a94eb4a
if ($LASTEXITCODE -ne 0) { throw 'Package blocked; preserve output, do not alter pins' }
```

Require `PRESERVATION_PACKAGE_VERIFIED_REQUIRES_TESTS_AND_EXACT_COMMIT_CI`, failures[].
The checker enforces exact base, exact stage-zero regular new paths, worktree/index
hashes, original prerequisite hashes and no unrelated staged/untracked files. It
prints only public paths/hash mismatch details, not private evidence.

Focused tests:

```powershell
& $preservationPython -m pytest -q -p no:cacheprovider tests/test_archive_preservation_inventory.py tests/test_archive_preservation_witness.py tests/test_archive_preservation_upload_check.py tests/test_workflow_runtimes.py
if ($LASTEXITCODE -ne 0) { throw 'Focused tests failed' }
```

Lint and scoped strict typing (real temporary cache, never NUL):

```powershell
& $preservationPython -m pyflakes archive_preservation_inventory.py archive_preservation_witness.py archive_preservation_upload_check.py tests/test_archive_preservation_inventory.py tests/test_archive_preservation_witness.py tests/test_archive_preservation_upload_check.py
if ($LASTEXITCODE -ne 0) { throw 'Lint failed' }
$preservationTypeCache = Join-Path $env:TEMP ('preservation-mypy-' + [guid]::NewGuid().ToString('N'))
& $preservationPython -m mypy --strict --follow-imports=silent --cache-dir $preservationTypeCache archive_preservation_inventory.py archive_preservation_witness.py archive_preservation_upload_check.py
if ($LASTEXITCODE -ne 0) { throw 'Typing failed' }
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw 'Whitespace gate failed' }
```

Run the full suite from this clean clone using the repository's reviewed Node24 /
locked PGLite prerequisites, not from the source folder containing nested clones.
Record platform, interpreter, failures/skips and complete counts; do not relabel an
interrupted/sandbox-denied run as passed. Hosted Linux quality/resilience/CodeQL on
the exact FINAL commit SHA are mandatory before owner merge. No workflows are added
or enabled by A. Native Windows focused tests are separate evidence from Linux CI.

Before committing, `git config --get user.name` and `git config --get user.email`
must each exist; if missing the owner sets REPO-LOCAL identity privately. Commit and
PR description have no attribution/trailers; PR description is one plain line.
Suggested plain description: `Add inactive destination-bound preservation witness`.

## After merge: separate commissioning, not automatic

Do not run private measurement during live capture. No original needs modification,
re-encryption, moving or insertion of a new manifest into the existing ciphertext.
All new sidecars, key material and trust records stay outside every repository and
tools checkout. Choose genuinely NEW output names; on partial/unknown write STOP,
preserve it, do not delete/reset/overwrite/retry it. This is not ACL/WORM storage.

First preview, even with private paths omitted:

```powershell
& $preservationPython archive_preservation_inventory.py
```

Require PREVIEW, all I/O counters zero. Preview does not validate private paths.
Counters refer to private inputs and operational outputs, not Python's own module
loading/cache activity. Use `-B` before the script name if bytecode-cache writes
must also be suppressed; isolated `-I` omits sibling modules and is not this CLI route.
Use `--help` for the separate witness CLI's explicit key/sign/verify operations;
that CLI also defaults to preview. Do not supply passphrases in command arguments,
environment variables, clipboard commands, logs or chat.

### Private selection contract

Create a new private selection JSON by adapting the existing seven-file inventory.
It must have exactly these top-level keys: `version`, `originals`, `source_cipher`,
`destination_cipher`, `expected_destination_volume`, `owner_reports`.
`version` is `preservation-selection-v1`.

`originals` has exactly seven objects, one per role:
`inventory`, `catalog`, `bundle`, `reconcile`, `verify`, `footer`, `other`.
Map these semantic roles to the actual seven preserved files; do not rename or
invent an artifact. If the inventory's seven roles do not fit, STOP for review.
Every object has EXACTLY `role`, `path` (absolute), `bytes` (positive integer),
`sha256` (64 lowercase hex), `anchor_kind`, `observed_at` (aware ISO timestamp).
The `catalog` and `bundle` use `ORIGINAL_RETAINED_PIN` and their retained full pins,
NOT newly enrolled measured hashes. The five others use `FIRST_OBSERVED` and the
recorded 19 October 18:15 IST inventory facts. A current mismatch is a block, not a
request to replace the anchor. Keep the original measurement time truthful.

`source_cipher` and `destination_cipher` are the explicit PC and external-disk
absolute paths to the EXISTING encrypted file. Cipher expected size/hash are fixed
in code from the retained owner anchor: 161194257 bytes and the full 9c9b22af…1519e
hash. No decryption/passphrase is used in measurement. No 7-Zip child is launched.

For volume enrollment, reconnect/physically identify the external disk and select
the actual destination. The following separate probe reads metadata only, writing
a NEW private probe sidecar (no path/ID printed):

```powershell
& $preservationPython archive_preservation_inventory.py --probe-destination $preservationDestination --output $preservationProbe
```

This is PREVIEW. After reviewing the selected path and confirming no capture running:

```powershell
& $preservationPython archive_preservation_inventory.py --probe-destination $preservationDestination --output $preservationProbe --confirm-probe
if ($LASTEXITCODE -ne 0) { throw 'Probe blocked; preserve state' }
```

The private sidecar's `binding.volume` is an observation, NOT automatic enrollment.
Independently check it corresponds to the selected external destination before
recording it as `expected_destination_volume`. A label/drive letter/Fixed media type
is insufficient. Identical source/destination volume is rejected; unknown physical
mapping means NOT VERIFIED even when different-volume measurement succeeds.

`owner_reports` has exactly five Boolean fields: `external_disk`,
`disconnected_storage`, `extraction_rehearsal`, `drive_readback`,
`superseded_stale_attempt`. True means the owner reports that observation, not that
software proved it. Earlier readbacks must not be backdated into new measurements.

Preview measurement with the selection/output variables, then, in a separate block:

```powershell
& $preservationPython archive_preservation_inventory.py --selection $preservationSelection --output $preservationReport --confirm-measure
if ($LASTEXITCODE -ne 0) { throw 'Measurement blocked; no anchor changes or retry' }
```

Expected `PRESERVATION_MEASURED_NOT_CUSTODY`. It reads the exact selected nine files
(seven originals, two ciphertexts), not recursive discovery, Parquet, or row pages.
The original files remain unchanged. An open-handle measurement is a present fact,
not proof of what the source contained before acquisition.

### Dedicated signature key and independent verifier

Only AFTER merge/review and a deliberate owner commissioning session, choose new
private `$preservationKey` (encrypted DER PKCS8) and `$preservationPublic` (32-byte
public key) paths. Confirm an existing private directory is suitable; this package
does not change its permissions. A key cannot protect authenticity if an attacker
can replace the separately trusted public-key fingerprint/current checkpoint.

Preview first (omit the last switch), then in a separate block:

```powershell
& $preservationPython archive_preservation_witness.py --mode keygen --key-output $preservationKey --public-output $preservationPublic --confirm-run
if ($LASTEXITCODE -ne 0) { throw 'Key operation unknown or blocked; preserve outputs' }
```

The hidden prompt needs a NEW dedicated signature-key unlock secret (16 to1024
UTF-8 bytes), NOT the 7-Zip passphrase or any production secret. Key generation
returns `DEDICATED_KEY_CREATED_NOT_TRUST_ENROLLED`: enrollment is still separate.
Keep the encrypted key backup and unlock secret separately. Rehearse recovery
using a separately copied encrypted key and compare the recovered public key to
the independently retained fingerprint before relying on it. Key recovery is NOT
an archive or database restore. No actual key/recovery was run by the builder.

Record the public-key raw-byte SHA256 and identity privately in an independent
trust record, plus its currently approved status. Do not take that fingerprint
from an untrusted envelope. For an explicitly NEW stream only, sign generation1
using the measured report as `$preservationReport`, a new `$preservationWitness`,
and the independently retained public fingerprint `$preservationPublicSha`:

```powershell
& $preservationPython archive_preservation_witness.py --mode sign --generation 1 --confirm-first-generation-enrollment --key $preservationKey --trusted-public-key $preservationPublic --trusted-public-key-sha256 $preservationPublicSha --observation $preservationReport --output $preservationWitness --confirm-run
if ($LASTEXITCODE -ne 0) { throw 'Signing blocked; do not replace any state' }
```

Do not interpret this as permission to create a new stream after losing an old
checkpoint. Preserve the proposed witness digest privately, confirm it through
the independent verifier/public trust record, then explicitly accept generation1
and that exact digest in the external checkpoint record. The signer does not write
or advance that accepted trust record. A signature does not independently verify
the supplied observation or provenance labels.

Separate verifier (no private key or passphrase), using `$preservationGeneration`
and `$preservationLatestDigest` from the independently retained accepted checkpoint:

```powershell
& $preservationPython archive_preservation_witness.py --mode verify --witness $preservationWitness --trusted-public-key $preservationPublic --trusted-public-key-sha256 $preservationPublicSha --latest-generation $preservationGeneration --latest-digest $preservationLatestDigest --confirm-run
if ($LASTEXITCODE -ne 0) { throw 'Signature/current-anchor verification failed' }
```

Require `PRESERVATION_SIGNATURE_VERIFIED_NOT_CUSTODY`. For later generations the
signer additionally requires `--previous-witness`, externally accepted
`--latest-generation` and `--latest-digest`; skipped predecessors/missing heads
block. It never silently advances an anchor. Keep private hashes/paths out of chat.

Dedicated key enrollment, encrypted key recovery rehearsal, independently retained
public-key fingerprint and latest accepted checkpoint are OWNER steps. Revocation
discovery and key rotation are NOT implemented: the owner must withhold a revoked
key, stop the stream, and obtain a separately reviewed rotation plan. Verification
cannot learn revocation from an unavailable registry. Key loss/revocation never
authorizes resetting a checkpoint. No signing result is authenticated custody.

The implemented encrypted-key recovery check is read-only and uses a separately
retrieved encrypted key copy as `$preservationRecoveredKey`:

```powershell
& $preservationPython archive_preservation_witness.py --mode check-key --key $preservationRecoveredKey --trusted-public-key $preservationPublic --trusted-public-key-sha256 $preservationPublicSha --confirm-run
if ($LASTEXITCODE -ne 0) { throw 'Key recovery not verified; preserve evidence' }
```

Preview by omitting `--confirm-run` first. It prompts only for the dedicated key's
unlock secret, not the7-Zip passphrase. No output key or checkpoint is written.
Record the resulting key-only status privately; it is not archive custody/restore.

## Wednesday 21 October (unchanged; independent of this package)

20 October is closed; previous regular session for Wednesday is Monday 19 October.
Download genuine `ind_close_all_19102026.csv` ON 21 October, with its real completion
time, source attestation and fresh host/clock checks. Personally seen 21 October
Setup popup on 16 October is OWNER-REPORTED; it does not prove today's readiness.
Keep both dated tasks disabled until the proven manual route admits recurrence.
Prepare AND policy freeze strictly before09:15 IST. Start ONCE around08:00; do not
start before07:50:30 because the first-slot90-minute wait bound can consume an
attempt before rejection. Never leave Start until the09:20:30 deadline.

Normal non-admin PowerShell, explicit reviewed3.13.9, correct clean tools/capsule,
AC power, awake AND logged in. Never-sleep does not prevent sign-out, update restart,
clock failure or network loss. Use existing read-only host/restart checks; do not
self-heal or bypass the clock. Stay for supervised09:20:30/09:25:30 receipts, reviewed
enable acknowledgement, and personally observe automatic09:30:30. Final15:30:30 and
scheduled15:40 audit still require dated proof. No alternate guided route, extra
Setup, catch-up or same-slot retry. Monday's missing capture stays missing.

## Recovery order and all open items

A: present anchored inventory/destination witness and dedicated trust lifecycle;
then B: contained private verification bridge (original16MiB verifier unchanged);
then authenticated custody plus same-generation isolated typed/full restore;
then exact cold-reader proof; retention LAST. Different Google folders under one
account are not independent account/provider failure domains. Disconnected external
disk adds a different OWNER-REPORTED domain, not automatic authenticated custody.
No encrypted copy, signature or successful CI permits deletion.

Track, not cleared: eight outcomes batches blocked only at16MiB (868/876 remains);
receipt authentication and DB backup facts; fresh DB capacity; Drive object identity,
retention/account availability; guarded live writers/readers and bounded retention;
production ledger signing-key custody/historical keys (the new dedicated key does
not authenticate those old records);
actual production failure-alert delivery; PostgreSQL17 non-loopback listeners/manual
startup decision (A needs no database/service); Windows Time12:48 stop/root dispersion;
missing14October saved audit and legacy audit exit2/shared-root writes; option capture
off; unidentified sessionsJSON ending1October; full owner local suite not run; and
ML/LLM/backtesting gated on licences, labels and a frozen paper study. Do not drop or
silently clear any item. DB service isolation needs a separately approved owner step,
not an incidental installer/config/ACL change during A.

## Technology radar

Adopt existing Python3.13.9, cryptography Ed25519, Windows native handle identity,
ordinary public CI and an independent read-only reviewer. No new paid service,
terminal plugin, agent trading authority, database extension or installation needed.
Keep7-Zip solely for encryption/recovery, never signing. Defer physical-disk mapping
and provider-authenticated Drive identity until a separately reviewed custody gate;
neither can be inferred from a matching volume or downloaded file. Reject blanket
runner-policy exceptions and production-key reuse. Next leverage: Package B proving
the eight retained large-row artifacts in bounded containment, without content in
logs or weakening the original verifier.

References reviewed for this implementation:
- https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew
- https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew
- https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/
- https://supabase.com/docs/guides/platform/backups

Supabase guidance was checked only for the recovery boundary, not to access the
project. Its current backup documentation recommends regular off-site exports for
Free projects; do not assume a downloadable provider backup exists. Owner can view
Database > Backups read-only and record availability/date/type without generating
tokens or starting a restore. Neither this inventory nor a table export substitutes
for a same-generation full database restore rehearsal. No relevant database feature
or migration is implemented in A.

## Builder verification and independent handoff, 19 October

VERIFIED in a fresh LF public clone at the exact base above with only these eight
additions staged: package checker failures[], focused selection124 passed/1 skipped,
pyflakes six files clean, strict mypy three source modules passed, staged whitespace
check clean. The skip is native symlink creation privilege absent; no privilege or
permission changes were attempted. Default preview of BOTH CLIs passed under
Windows PowerShell5.1 and PowerShell7 with zero private/operational I/O counters.
Actual Windows native same-handle checks used tiny synthetic opaque files; full
seven-original/two-cipher contracts used synthetic bindings, NOT private originals
or real external hardware. Signature tests use disposable synthetic keys only.

Independent checker (separate agent, no edits) found bounded-config reopening and
mapped-network admission gaps; both fixed. Canonical signing encoding now checks
its aggregate bound incrementally. Combined Windows tests exposed pathname versus
CRT-handle ctime semantics: fixed by checking ctime within each API, retaining
cross-API inode/device/size/mtime checks and native read-only sharing. Regression
included. Reviewer then independently checked all payload/prerequisite hashes,
source-to-clone equality, eight-addition index and checker tests12 passed; no
remaining blocker within the explicitly limited scope.

NOT VERIFIED: full local suite execution/completion, Linux execution for THIS
package, final-SHA hosted CI, operational key custody/recovery, actual selected-disk
measurement, remote provider identity, historical receipt authentication, private
content verification, database restore or deletion eligibility. A full-tree
collection found7118 tests; collection is not execution. Broader execution attempts
were interrupted without complete aggregate pass/fail/skip totals; do not count
them as full-suite success. Collection also emitted a sandbox temporary-directory
cleanup PermissionError; this is not a clean full-suite result or permission to
change ACLs. WSL availability check was denied in this sandbox;
no installation/elevation/ACL workaround was used. Hosted Linux exact-final-SHA CI
and owner Windows commissioning remain explicit gates, not a claim made by builder.

Owner-reported preservation and Wednesday readiness facts above remain claims,
not builder access to private files or a promise of successful capture. Original
archive verifier/pins,868/876 result, deletion hold, workflow no-I/O hold, release
hold, Streamlit expectations, installed capture, tasks, journals and services are
unchanged. Nothing is automatically enabled or signed by merging this package.
