# Package A native-identity repair and safe resume (20 October 2026)

## Status and decision

Builder read public main a69870ba0bc59fc206824fe6d9f1db138ae1aec0. Owner reports
Package B/PR51 green and inactive. No private artifact, key, capture folder/state,
task, service, database or hosted setting was accessed/changed for this repair.
Source confirms the reported mismatch: producer emitted an exact uint64 device ID;
signer reused the signed63-bit generation limit for every JSON integer. This is a
serialization-contract defect, not evidence corruption or a bad key.

Owner-reported: destination probe/enrollment and seven-file measurement succeeded;
dedicated key creation and recovered-key check succeeded; generation1 signing
stopped before the hidden prompt/publication; no witness/head exists. The owner's
extraction_rehearsal=false report stays false. Earlier reported extraction checks
do not silently override the selection or establish a new typed/full restore.

## Representation contract, not an evidence-bound relaxation

- Device IDs: exact nonnegative uint64, 0..2**64-1. File IDs: exact nonnegative
  uint128, 0..2**128-1. Python3.12+ may return128-bit Windows st_ino. Producer rejects
  bools/floats/negative/overflow identifiers with NATIVE_ID_INTEGER_BOUND.
- Bounded preservation JSON scalar integers: abs(n)<=2**128-1. Separate
  MAX_JSON_INTEGER is shared with the producer's maximum native identity width.
- Generations/predecessors remain strict literal integers1..2**63-1; booleans,
  zero, negative and overflowing generations still fail. File/selection/envelope
  sizes, structure/depth, hashes, native-path/handle and exclusive-output gates stay.
- This is an additive v1 integer-profile extension. Already accepted canonical
  bytes/domain/signatures do not change. Old validators reject newly supported
  wide integers; use the repaired verifier and B host from the reviewed merge.
- Never truncate, cast to float, stringify identifiers in a saved report, convert
  through JavaScript/PowerShell JSON and re-save, or re-pin original evidence.
  This bounded Python JSON profile is NOT RFC8785/I-JSON or IEEE754 interoperability.
- Sizes emitted in this inventory are already capped at1GiB. Nanosecond timestamps
  are compared as Python integers within the file APIs but are NOT serialized into
  the current measurement. Timestamp strings retain their original aware values.
- Full signing ENVELOPE size/shape is checked before reading the encrypted key or
  prompting. A new read-only check-observation mode makes that gate visible without
  producing a signature, head, key or file. Preview alone still validates no input.

The existing measured.json can be signed UNCHANGED after this repair if its new
preflight passes. It records the original measured_at observation, not current
physical custody. Its original collector_sha256 is retained; no remeasurement,
selection rewrite, original-pin change or first-observed re-enrollment is needed.
If any input changed or preflight blocks, preserve and stop for review. Do not
create a replacement measurement merely to get signing to pass.

## One reviewed upload (11 paths, exact base above)

Copy from C:\Users\banga\Desktop\kiran_share_market to SAME relative destination
in a clean LF clone at a69870ba0bc59fc206824fe6d9f1db138ae1aec0:

Modified:
1. archive_preservation_inventory.py
2. archive_preservation_witness.py
3. tests/test_archive_preservation_witness.py
4. tests/test_archive_preservation_upload_check.py
5. tests/test_outcomes_private_upload_check.py
6. PRESERVATION_COMMISSION_2026-10-20.md

Added:
7. tests/test_preservation_integer_contract.py
8. preservation_integer_upload_check.py
9. tests/test_preservation_integer_upload_check.py
10. PRESERVATION_INTEGER_REPAIR_2026-10-20.md
11. PRESERVATION_INTEGER_UPLOAD.json

Historical A/B manifests/checkers stay BYTE-UNCHANGED. Their source-hash tests now
recognize only this explicit reviewed successor for six named paths, require each
old expected hash to equal its enrolled predecessor, and check replacement bytes
against the new manifest. No skip/current-hash fallback is added. The new upload
gate checks both old base bytes and new worktree/index bytes. All other old pins
stay direct checks. Neither old checker is repurposed for this new upload.

Normal PowerShell, one block at a time; set ErrorActionPreference=Stop and the
explicit research-venv3.13.9 path in $repairPython. Never either capture venv/bare py.
Stage exactly11 paths before the checker; keep mypy caches outside the clone.

```powershell
& $repairPython -B preservation_integer_upload_check.py --base a69870ba0bc59fc206824fe6d9f1db138ae1aec0
if ($LASTEXITCODE -ne 0) { throw 'Repair package blocked; no pin edits' }
```

```powershell
$repairTestTemp = Join-Path $env:TEMP ('preservation-integers-' + [guid]::NewGuid().ToString('N'))
& $repairPython -B -m pytest -q -rs -p no:cacheprovider tests/test_preservation_integer_contract.py tests/test_preservation_integer_upload_check.py tests/test_archive_preservation_inventory.py tests/test_archive_preservation_witness.py tests/test_archive_preservation_upload_check.py tests/test_outcomes_private_upload_check.py tests/test_outcomes_private_container.py tests/test_outcomes_private_worker.py tests/test_workflow_runtimes.py --basetemp $repairTestTemp
if ($LASTEXITCODE -ne 0) { throw 'Focused tests failed; preserve scratch' }
```

```powershell
& $repairPython -B -m pyflakes archive_preservation_inventory.py archive_preservation_witness.py preservation_integer_upload_check.py tests/test_archive_preservation_witness.py tests/test_archive_preservation_upload_check.py tests/test_outcomes_private_upload_check.py tests/test_preservation_integer_contract.py tests/test_preservation_integer_upload_check.py
if ($LASTEXITCODE -ne 0) { throw 'Lint failed' }
```

```powershell
$repairTypeTemp = Join-Path $env:TEMP ('preservation-types-' + [guid]::NewGuid().ToString('N'))
& $repairPython -B -m mypy --strict --follow-imports=silent --cache-dir $repairTypeTemp archive_preservation_inventory.py archive_preservation_witness.py preservation_integer_upload_check.py
if ($LASTEXITCODE -ne 0) { throw 'Strict typing failed' }
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw 'Whitespace failed' }
```

Check Git identity PRESENCE before commit, without printing it. No attribution or
trailers; one-line PR description: Repair preservation native integer contracts.
Final-commit quality FULL Linux suite, resilience and CodeQL must be green before
owner merge. If main advances, stop for reconciliation, not pin bypass. A full local
Windows run is still a separate outstanding gate; normal_user_test_run.py from a
fresh committed checkout with --with-pglite provides unique normal-user scratch.
No runtime test or hosted green result for the future commit is implied here.

## Resume A only AFTER green merge and fresh clean tools checkout

Keep the existing key, public file, independent fingerprint, key recovery proof,
selection, probe and measured.json. Do NOT generate a key or restart A from Block1.
Blocked signing is preserved as history, not erased. Source has no sign-attempt
marker/head publication before that failed integer parse. The owner reports no
witness was written: authorize one NEW signing output path after preflight, not a
same-slot capture retry or a reused partial output. Any contrary observation stops.

Normal NONADMIN PowerShell. Set $repairPython to the explicit research3.13.9 path;
privately restore $Measured, $Key, $Public, $PublicSha from the preserved paths and
independent fingerprint record. Do NOT compute a replacement trust fingerprint.
Choose a NEW absolute private $Witness path outside every checkout/capsule. Do not
paste any path/hash/secret/report into chat or GitHub. These assignments do not
read/reset a journal. Require the witness path not to exist:

```powershell
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($Witness) -or -not [IO.Path]::IsPathRooted($Witness)) { throw 'New absolute witness path required' }
if (Test-Path -LiteralPath $Witness) { throw 'Existing output: preserve; do not sign' }
```

Block1 PREVIEW (zero input reads/writes/passwords):
```powershell
& $repairPython -B archive_preservation_witness.py --mode check-observation --observation $Measured --generation 1 --confirm-first-generation-enrollment
if ($LASTEXITCODE -ne 0) { throw 'Preview blocked' }
```

Block2 read-only validation of UNCHANGED measured bytes:
```powershell
& $repairPython -B archive_preservation_witness.py --mode check-observation --observation $Measured --generation 1 --confirm-first-generation-enrollment --confirm-run
if ($LASTEXITCODE -ne 0) { throw 'STOP: preserve measurement; no retry or re-pin' }
```
Require OBSERVATION_SIGNING_PREFLIGHT_PASSED_NOT_SIGNATURE, credential_reads0,
writes0. This does not authenticate the measurement or authorize custody/deletion.

Block3 signing PREVIEW; again reads nothing:
```powershell
& $repairPython -B archive_preservation_witness.py --mode sign --generation 1 --confirm-first-generation-enrollment --key $Key --trusted-public-key $Public --trusted-public-key-sha256 $PublicSha --observation $Measured --output $Witness
if ($LASTEXITCODE -ne 0) { throw 'Signing preview blocked' }
```

Block4 ONE signing command. Run ONLY this block and wait for the hidden prompt;
do not paste more lines until it finishes. The already recovered dedicated unlock
secret is16-1024 UTF-8 BYTES, not characters. Never the7-Zip/production secret.
```powershell
$signedText = & $repairPython -B archive_preservation_witness.py --mode sign --generation 1 --confirm-first-generation-enrollment --key $Key --trusted-public-key $Public --trusted-public-key-sha256 $PublicSha --observation $Measured --output $Witness --confirm-run
```

Block4b ONLY after the hidden prompt and command have finished:
```powershell
if ($LASTEXITCODE -ne 0) { throw 'STOP: preserve any partial output; no retry' }
$signed = $signedText | ConvertFrom-Json
if ($signed.status -ne 'OWNER_OBSERVATION_SIGNED_NOT_CUSTODY') { throw 'Unexpected signing result' }
```
The PowerShell parser handles only the small redacted status/generation/hex digest,
NOT measured.json/native IDs. Wait for completion before entering Block4b.
No hidden-prompt command pasting.
Record generation1 and $signed.digest PRIVATELY as the candidate head in the
independent trust record. The envelope alone never supplies accepted trust.

Block5 verify against that independently retained candidate head/key fingerprint:
```powershell
& $repairPython -B archive_preservation_witness.py --mode verify --witness $Witness --trusted-public-key $Public --trusted-public-key-sha256 $PublicSha --latest-generation 1 --latest-digest $signed.digest --confirm-run
if ($LASTEXITCODE -ne 0) { throw 'STOP: signature/head not established' }
```
Require PRESERVATION_SIGNATURE_VERIFIED_NOT_CUSTODY. Then explicitly mark only that
exact generation/digest accepted in the separate record. Preserve original measured
bytes and all failed/successful attempt outputs. No old receipt is authenticated
retroactively and no first-observed location becomes a historic measurement.

## B and recovery order

B's host imports the SAME repaired witness consumer. Its Python JSON parsing keeps
native integers exact. A synthetic test reaches B's LOCAL_SYNTHETIC_ADMISSION with
the wide IDs, then deliberately stops; it is NOT real private/native acceptance.
B worker/image/original16MiB verifier are unchanged and868/876 stays. Run the existing
manual synthetic Linux workflow and local Windows containment acceptance before
any separately commissioned private run; no private input in Actions. Docker/WSL2
availability, eligibility and native acceptance remain NOT VERIFIED.

Order: A signature/independent head -> native B admission -> contained eight-batch
structural check -> authenticated custody -> same-generation isolated typed/full
restore with schema/roles/functions and cross-batch conflict policy -> cold readers/
writers -> bounded retention LAST. No deletion, key rotation or settings change.

## Holiday collector and Wednesday

Owner reports manual collector175/176 failed20October with the old-current-IST-date
exchange-status error. Source at this base confirms that error is a DATE mismatch,
not an81482-second freshness threshold. It occurs before this scan's universe/
quotes/scanner writes, but AFTER run/lease bookkeeping; do not call it zero writes.
It does not prove provider NORMAL_CLOSED or inspect database effects. A weekday/time
scan window lacks holiday-aware skip classification even though cash_session()
contains20October. Do not relax the guard or run again on the holiday. A future
separate holiday-aware collector change must preserve unknown/special-session gates.
Other collector modes are not covered by this scan-specific inference. Actual175/
176 logs/database effects were not independently inspected by the builder.

Wednesday21October remains the proven manual route in its INSTALLED capsule:
fresh21October download of genuine19October close; tasks disabled beforehand,
fresh host/clock/restart checks; Prepare AND policy freeze before09:15; Start ONCE
around08:00 (not before07:50:30 under the existing90-minute wait bound). Stay through
both supervised polls/enable admission and personally see09:30:30 automatic receipt;
AC, awake and signed in through15:30:30/final15:40audit. No B dependency, new tools,
guided/manual mixing, catch-up, same-slot retry, journal reset or clock/pin bypass.

## Open-items ledger: none silently cleared

Owner reports opaque measurement/key recovery only; A signature/head remains blocked
pending this repair. B native/private acceptance; DB backup facts/fresh capacity;
authenticated custody/Drive failure domain; matching typed/full restore; cold readers/
writers; retention; actual production failure-alert delivery; PG17 non-loopback/
manual-start decision; Time12:48/root dispersion; missing14October report; legacy
audit2/shared-root writes; OPTION_CAPTURE_ENABLED off; unidentified sessionsJSON
ending1October (DO NOT edit); legacy receipt/historical-key authentication; complete
Windows suite; gated ML/backtesting/licences/labels/frozen study; holiday failures.
Preserve the extra Downloads encrypted copy, Desktop inventory and Downloads ZIP:
same size is not identity and none counts as independent custody. No cleanup today.

## Technology radar and evidence

Adopted exact Python integers plus existing cryptography/Ed25519; no new tool,
plugin, service, paid tier or installation. Adapted v1 numeric representation, not
the archive decoder profile. Rejected float/string mutation of existing evidence,
automatic key replacement, historic pin edits and a collector bypass. Separate
reviewer checks builder changes. Next leverage: matching restored-generation/schema
and conflict-policy proof after B, rather than deleting valid-looking files.

Official sources reviewed20October2026:
- https://docs.python.org/3.13/library/os.html (st_ino may be128bits on Windows)
- https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_info
  (uint64 volume serial,128-bit file identity)

Builder verification (20October, clean exact-base candidate):
- Focused selection253 passed,1 skipped (Windows symlink privilege unavailable).
- Eight-file pyflakes clean; strict mypy clean for the three runtime/checker modules.
- Exact11-file staged gate passed, failures[]; whitespace clean. Separate reviewer
  checked old/new transition negatives, unchanged historical pins, source/index
  parity, full-envelope ordering and all25 PowerShell document blocks.
- A broader Windows suite was attempted with explicit3.13.9, non-admin check,
  credential environment excluded, unique scratch and mandatory PGlite SELECT1.
  It was STOPPED/non-green after native-operation failures; NO completed aggregate
  pass/fail/skip count is available and it is NOT a full-suite pass.
- Isolated unchanged-path diagnostic:151 passed,2 skipped,1 failed at
  tests/test_archived_directional_replay.py::test_archive_roundtrip_deduplicates_and_restarts.
  Failure: PermissionError/WinError5 at os.link in unchanged
  automated_development_checks.write_once. This execution environment denied native
  hard-link publication; the responsible sandbox/security/filesystem rule is NOT
  established. Other failures seen in the partial full run are not classified.
  A local baseline Git-clone attempt also met an MSYS native-namespace denial;
  no baseline full-suite pass is claimed. No permissions or publishers were changed.
- Independent isolated SQL maintenance selection:20 passed. This does not substitute
  for the complete suite. Existing normal_user_test_run.py remains the owner's
  repeatable NORMAL-window full-run route after merge. If the same native denial
  occurs there, preserve it for diagnosis; no elevation/ACL/copy fallback.

Private A resume/B execution, Linux execution of this repair, a complete Windows
suite and future exact-SHA hosted CI remain NOT VERIFIED until actually completed.
The focused result is not permission to ignore a failing final-commit CI gate.
