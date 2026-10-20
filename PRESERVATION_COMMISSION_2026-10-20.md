# Tuesday holiday: Package A commissioning, one normal PowerShell block at a time

## 20 October commissioning repair: existing measurement/key are preserved

The owner reports A measurement and dedicated-key recovery succeeded, but signing
stopped at JSON_INTEGER_BOUND before the hidden prompt and without a witness/head.
The signer incorrectly used a signed generation limit for native identity numbers.
Read PRESERVATION_INTEGER_REPAIR_2026-10-20.md FIRST and use its resume blocks only
after that repair merges green. Keep the existing selection, probe, measured bytes,
key copies, independent fingerprint and original inventory unchanged. Do NOT restart
Blocks1-12 or generate another key just because this signing attempt was blocked.
Existing reports are observations made at their measured_at time, not a new claim
that the external disk is currently connected or that the archive was restored.

Package A is owner-reported merged in PR50; builder independently checked current
public main e2e1d0d797e453e2fd9d12fd0df7fb8bcb968b99. This document is NOT an
attestation, private measurement or authorization for deletion. No capture folder,
state, task, service, ACL, original file or archive needs changing.

Prefer Tuesday20October in daylight, rested, with no capture running. Wednesday's
proven manual route is independent. Package B source/tests can progress in parallel;
its private invocation requires the verified A witness and a separate local
synthetic containment gate first. Do not rush a virtualization install before capture.

## Role mapping: accepted, subject to actual private paths/anchors

- catalog: catalog-all.json (retained original catalog pin)
- bundle: drive-archive.zip (retained original bundle pin)
- inventory: inventory.json
- reconcile: the preserved reconcile output
- verify: the preserved verifier output
- footer: the preserved footer diagnostic output
- other: ArchiveRecovery.txt

catalog-all.json and ArchiveRecovery.txt can contain identical bytes; A rejects
duplicate FILE IDENTITIES, not equal hashes. Keep both if these are the actual seven
selected originals. Equality is not independence or extra coverage. The `other`
location remains FIRST_OBSERVED per the new inventory; the already known matching
catalog bytes do not become a newly authenticated historic location. No renaming,
hard-linking, moving, re-encryption or rewriting originals is required.

## Before beginning

Use a clean tools checkout of merged A, normal NONADMIN PowerShell, and the explicit
reviewed venv Python3.13.9 (never bare py). Verify the checkout HEAD/status, interpreter
and effective normal token with the established read-only checks. Do not use either
capture venv. Do not copy a helper into a clean tools checkout after checking it.
All private outputs below must be new absolute paths OUTSIDE repositories/capsules.
Use an existing suitable private directory; no ACL adjustments. Keep real paths,
hashes, key material and secrets out of chat, GitHub, screenshots and shared logs.

Block1: set `$ErrorActionPreference='Stop'`; set `$preservationPython` to the explicit
3.13.9 executable. Privately assign `$DestCipher`, `$SourceCipher`, `$Probe`,
`$Selection`, `$Measured`, `$Key`, `$Public`, `$RecoveredKey`, `$Witness` to actual
absolute paths. Probe/selection/report/key/public/witness outputs MUST NOT exist.
The ciphertext paths already exist. A blank/unset variable is a STOP, not a prompt
to guess or substitute a source path. Keep a private worksheet of these roles.

Block2 (preview only):
```powershell
& $preservationPython -B archive_preservation_inventory.py
if ($LASTEXITCODE -ne 0) { throw 'Preview blocked' }
```
Require PREVIEW, zero private/operational I/O.

Block3 (metadata probe preview):
```powershell
& $preservationPython -B archive_preservation_inventory.py --probe-destination $DestCipher --output $Probe
if ($LASTEXITCODE -ne 0) { throw 'Probe preview blocked' }
```

Block4 (one actual metadata probe):
```powershell
& $preservationPython -B archive_preservation_inventory.py --probe-destination $DestCipher --output $Probe --confirm-probe
if ($LASTEXITCODE -ne 0) { throw 'STOP: preserve output; no retry' }
```
Require DESTINATION_PROBED_NOT_ENROLLED. Physically identify the external enclosure
and selected destination. Examine the private probe locally, not in chat. Its
binding.volume is a current observation, not automatic enrollment. Record the
expected volume separately only after checking the selected device/path. Different
volumes still do not prove different physical disks; that remains NOT_VERIFIED.

Block5 (selection preparation, NOT another hash enrollment). Have the private
worksheet available LOCALLY. Enter its recorded values at the prompts, not freshly
computed replacements. This creates only a NEW selection; it reads no originals.
Use the two retained pins and five first-observed entries. The private probe is NOT
automatically adopted as a volume anchor. Keep the worksheet unchanged. Cancel if
uncertain; do not upload it or guess. Selection preparation is not custody.

```powershell
$ErrorActionPreference = 'Stop'
$recordedAt = Read-Host 'Recorded inventory time with timezone, exactly as recorded (not now)'
$parsedAt = [DateTimeOffset]::MinValue
if (-not [DateTimeOffset]::TryParse($recordedAt, [ref]$parsedAt) -or $recordedAt -notmatch '(Z|[+-][0-9]{2}:[0-9]{2})$') { throw 'Recorded aware time required' }
$originals = @(foreach ($role in @('inventory','catalog','bundle','reconcile','verify','footer','other')) {
    $selectedPath = Read-Host "$role - absolute path from your private worksheet"
    $sizeText = Read-Host "$role - recorded byte size"
    $selectedSize = [long]0
    if (-not [long]::TryParse($sizeText, [ref]$selectedSize) -or $selectedSize -le 0) { throw 'Positive recorded size required' }
    $selectedSha = (Read-Host "$role - full recorded SHA256, retained pin for catalog/bundle").ToLowerInvariant()
    if ($selectedSha -notmatch '^[0-9a-f]{64}$') { throw 'Full recorded hash required; never re-pin' }
    [ordered]@{role=$role;path=$selectedPath;bytes=$selectedSize;sha256=$selectedSha;anchor_kind=$(if ($role -in @('catalog','bundle')) {'ORIGINAL_RETAINED_PIN'} else {'FIRST_OBSERVED'});observed_at=$recordedAt}
})
$enrolledVolume = Read-Host 'Separately enrolled expected external volume, checked against physical selection'
if ([string]::IsNullOrWhiteSpace($enrolledVolume)) { throw 'No volume enrollment' }
$reported = [ordered]@{}
foreach ($field in @('external_disk','disconnected_storage','extraction_rehearsal','drive_readback','superseded_stale_attempt')) {
    $answer = Read-Host "$field - owner report: type YES or NO"
    if ($answer -cnotin @('YES','NO')) { throw 'Explicit YES or NO required' }
    $reported[$field] = ($answer -ceq 'YES')
}
$selectionData = [ordered]@{version='preservation-selection-v1';originals=$originals;source_cipher=$SourceCipher;destination_cipher=$DestCipher;expected_destination_volume=$enrolledVolume;owner_reports=$reported}
$selectionBytes = [Text.UTF8Encoding]::new($false).GetBytes(($selectionData | ConvertTo-Json -Depth 12))
$selectionStream = [IO.File]::Open($Selection,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
try { $selectionStream.Write($selectionBytes,0,$selectionBytes.Length);$selectionStream.Flush($true) } finally { $selectionStream.Dispose() }
[pscustomobject]@{status='PRIVATE_SELECTION_CREATED_NOT_MEASURED';originals=7;original_reads=0;custody_verified=$false} | ConvertTo-Json -Compress
```

Block6 (measurement preview):
```powershell
& $preservationPython -B archive_preservation_inventory.py --selection $Selection --output $Measured
if ($LASTEXITCODE -ne 0) { throw 'Measurement preview blocked' }
```

Block7 (one measured readback):
```powershell
& $preservationPython -B archive_preservation_inventory.py --selection $Selection --output $Measured --confirm-measure
if ($LASTEXITCODE -ne 0) { throw 'STOP: preserve sidecars; do not change anchors or retry' }
```
Require PRESERVATION_MEASURED_NOT_CUSTODY. No decryption secret is used.

## Dedicated key custody and first generation

Choose a NEW random unlock secret, preferably generated/stored in your existing
encrypted password manager or a separately stored sealed paper record. It must NOT
be the7-Zip passphrase in the existing notebook, or a production signing key. Store
the encrypted DER key on the PC in its private folder; make an encrypted-file copy
on the external disk in a separate key directory. The secret must not travel with
those key files or archive. Keep the independently retained public fingerprint and
accepted head separately from the bundle/key copies (paper or other offline trust
record). Same-account Drive copies add a location, not an independent account domain.
No additional password-manager service/account is required by this package.
For NEW key creation, the secret is 16-1024 UTF-8 BYTES inclusive (not characters).
Run a single command, wait for its hidden prompt, enter only the dedicated secret;
never paste a multiline command block while input is waiting. Preview states these
bounds but does not read or validate a secret. Already recovered keys stay in use.

Block8 (key preview):
```powershell
& $preservationPython -B archive_preservation_witness.py --mode keygen --key-output $Key --public-output $Public
if ($LASTEXITCODE -ne 0) { throw 'Key preview blocked' }
```

Block9 (one key generation):
```powershell
& $preservationPython -B archive_preservation_witness.py --mode keygen --key-output $Key --public-output $Public --confirm-run
if ($LASTEXITCODE -ne 0) { throw 'STOP: unknown key publication; preserve all outputs' }
```
Hidden dedicated unlock prompt twice; require DEDICATED_KEY_CREATED_NOT_TRUST_ENROLLED.
Never type the unlock secret into a variable, CLI argument, clipboard helper or log.

Block10 (private public-fingerprint enrollment):
```powershell
$PublicSha = (Get-FileHash -LiteralPath $Public -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
if ($PublicSha -notmatch '^[0-9a-f]{64}$') { throw 'Fingerprint not established' }
```
Examine/record this value PRIVATELY with key identity/current-approved status in your
independent trust record. This is explicit enrollment, not proof from the bundle.
Make the external encrypted-key copy using exact literal source/destination paths
and a new destination (do not overwrite). Retain its private hash/size. Retrieve a
separate encrypted copy into the new `$RecoveredKey` path; no plaintext key export.

Block11 (recovery preview), then Block12 (same command with --confirm-run):
```powershell
& $preservationPython -B archive_preservation_witness.py --mode check-key --key $RecoveredKey --trusted-public-key $Public --trusted-public-key-sha256 $PublicSha
if ($LASTEXITCODE -ne 0) { throw 'Key check preview blocked' }
```
```powershell
& $preservationPython -B archive_preservation_witness.py --mode check-key --key $RecoveredKey --trusted-public-key $Public --trusted-public-key-sha256 $PublicSha --confirm-run
if ($LASTEXITCODE -ne 0) { throw 'STOP: key recovery not verified' }
```
Require KEY_RECOVERY_VERIFIED_NOT_ARCHIVE; zero writes. Hidden key-unlock prompt,
not7-Zip. This does not restore an archive/database or check key revocation.

Block13 (first-generation preview):
```powershell
& $preservationPython -B archive_preservation_witness.py --mode sign --generation 1 --confirm-first-generation-enrollment --key $Key --trusted-public-key $Public --trusted-public-key-sha256 $PublicSha --observation $Measured --output $Witness
if ($LASTEXITCODE -ne 0) { throw 'Signing preview blocked' }
```

Block14 (one NEW-stream signing; never re-bootstrap a lost existing stream):
```powershell
$signedText = & $preservationPython -B archive_preservation_witness.py --mode sign --generation 1 --confirm-first-generation-enrollment --key $Key --trusted-public-key $Public --trusted-public-key-sha256 $PublicSha --observation $Measured --output $Witness --confirm-run
if ($LASTEXITCODE -ne 0) { throw 'STOP: signing outcome not established' }
$signed = $signedText | ConvertFrom-Json
if ($signed.status -ne 'OWNER_OBSERVATION_SIGNED_NOT_CUSTODY') { throw 'Unexpected signing status' }
```
Privately record the proposed generation1 and exact digest from `$signed.digest`
in the independently retained candidate-head record. Do not treat the envelope's
own digest/key as an accepted trust root. Nothing has automatically advanced a head.

Block15 (independent verifier, no private signing key/password):
```powershell
& $preservationPython -B archive_preservation_witness.py --mode verify --witness $Witness --trusted-public-key $Public --trusted-public-key-sha256 $PublicSha --latest-generation 1 --latest-digest $signed.digest --confirm-run
if ($LASTEXITCODE -ne 0) { throw 'STOP: first witness not verified' }
```
Require PRESERVATION_SIGNATURE_VERIFIED_NOT_CUSTODY. Check the observation belongs
to the measured generation. Only then explicitly mark that exact generation/digest
accepted in the independent trust record. Preserve all originals, sidecars and
attempt history. Revocation discovery/rotation and authenticated custody remain
separate; key loss never permits checkpoint reset. Report only redacted statuses.

## Other facts and Wednesday

Elevated-run Temp contamination was OWNER-REPORTED; it was not an A failure. Use the
new normal-user test helper only from a clean committed checkout, never a capture
venv or dirty source folder. It allocates unique normal-user scratch and does not
move/delete/chmod old folders. A full suite remains not verified until completed.

Wednesday plan stands: genuine21October download of19Octoberclose, fresh host/clock
checks, tasks disabled, Prepare AND policy freeze before09:15; Start once around08:00
(do not start before07:50:30, the90-minute first-slot wait bound). Stay through both
supervised polls, admission/enable acknowledgement and automatic09:30:30 receipt.
AC/awake/logged in until final15:30:30 and scheduled15:40audit. Never-sleep does not
prevent restart/sign-out/clock/network failure. No guided/manual mixing, extra Setup,
retry, catch-up, marker reset or clock/pin bypass. No new B tool is a capture dependency.

Do not drop any open item: A commissioning/B; DB backup facts/fresh capacity;
authenticated custody, same-generation typed/full restore, cold-reader/writer proof,
retention/Drive failure domain; actual production failure-alert delivery; PG17
non-loopback/manual-start decision; Windows Time12:48/dispersion; missing14October
audit; legacy audit2/shared-root writes; option captureoff; unknown sessionsJSON
ending1October; receipt authentication/historical keys; full local suite; gated
ML/backtests/licences/labels/frozen paper study; extra ciphertext in Downloads.
The Downloads duplicate is NOT another independent copy; preserve it until a
separately reviewed cleanup inventory/authorization. No deletion is authorized now.
