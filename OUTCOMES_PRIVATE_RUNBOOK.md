# Package B: inactive contained private structural verification

## Current gate: kernel-readonly-v2 repair

Read OUTCOMES_READONLY_REPAIR_2026-10-20.md FIRST. The owner reports the older local
image passed14 checks/watchdog but hosted Linux failed input_readonly. Its exact
errno is unknown. The replacement requires descriptor ST_RDONLY AND exact FD mount
ID/target/ro readback AND denied write-open on root and BOTH synthetic inputs.
EACCES alone never passes. No chmod, umask, ownership, ACL or user change is made.
After the reviewed repair merges, build/enroll a NEW immutable image and repeat
BOTH native acceptance gates in fresh run roots. Old-profile receipts/images are
preserved but do not satisfy kernel-readonly-v2. Private decoding remains held.

Exact upload base: e2e1d0d797e453e2fd9d12fd0df7fb8bcb968b99 (PR50 merge).
This is ONE additive PR. No original verifier/profile/pin, production key, capture,
workflow setting, service, ACL, journal or deletion permission is changed.
Read PRESERVATION_COMMISSION_2026-10-20.md for Tuesday's separate A procedure.

## Order and boundaries

Commission A on Tuesday20October, no capture running; build/review B in parallel.
Private B requires the actual A signature verified against an independently retained
public-key fingerprint AND current generation/digest, plus matching original catalog
and ZIP anchors. Every private attempt FIRST runs fresh LOCAL synthetic containment
and autonomous-watchdog checks on the same enrolled image ID. No saved proof or CI
Boolean is accepted as a substitute. Merge alone activates nothing.

The private decoder selects ONLY catalog ordinals135,266,318,386,395,626,698,757 from
the pinned876-record cohort. It rechecks names/manifests/raw-byte checksums, original
failure pattern and separate candidate profile (32MiB only for payload/_row_json;
other bounds unchanged). It streams batches one row at a time, checks bounded exact
canonical recovery JSON, unique snapshot keys, typed-column equality, aware timestamp
normalization and original content-derived batch IDs. No strategy analysis, date/value
reporting, labels, statistical summaries, training, application replay or row export.
Parsing for recovery integrity is NOT examining sealed2025/2026 research performance.

The ORIGINAL verifier still rejects these files at16MiB and remains868/876. B's
distinct result is EIGHT_OUTCOMES_STRUCTURAL_CHECK_NOT_CATALOG_ACCEPTANCE; its868
field is explicitly HISTORICAL, not new generic verification. It never rewrites the
original report, catalog, ZIP, manifests or receipts. Receipt claims/authenticated
Drive IDs, physical custody, same-generation restore, cold readers and deletion
remain unverified/false. Failure is preserved, not repaired/re-pinned/replayed.

## Containment decision: not a native Windows Job Object

Existing PR49 resource tests prove resource caps, NOT filesystem/network isolation.
Windows Sandbox is not supported on Windows11Home. Do not install unofficial Home
patches, change edition, create AppContainer ACL grants or treat antivirus as a jail.
Chosen conditional route: Docker Desktop's Linux engine over WSL2, with a normal
Windows client and a non-root65534:65534 process. Docker Desktop is free for personal
use/education/non-commercial open source and qualifying small businesses, NOT all
organizations. Owner reviews applicable terms; no paid plan or login is required
by this package. This is not a VM/kernel-exploit or malicious-host guarantee.

Runtime admission uses an externally enrolled immutable IMAGE ID (not a tag),
pull=never, explicit LOCAL npipe/unix engine (no remote DOCKER_HOST/context), a new
EMPTY Docker client configuration (no owner Docker auth/config loading), --init,
network=none, read-only root, exactly TWO individual read-only private file mounts,
no socket/directory/key mounts, capabilities ALL dropped, no-new-privileges,
private IPC/PID/cgroup namespaces, no devices/ports/restart/logging, runc,
768MiB RAM+swap-total,1CPU,16PIDs, CPU60s/nofile64/core0 ulimits (no private core dumps). Config/image/command,
requested AND effective mounts and limits are inspected BEFORE start and AFTER exit.
Only explicit known Desktop path translations are accepted; unknown mappings block.

Worker independently requires Linux/nonroot/non-PID1/no-new-privileges/zero effective
caps/no routes/no host socket and finite cgroup-v2 memory/PID limits. Default kernel
SIGALRM120s terminates the non-PID1 worker, independent of Python GIL/client lifetime;
host wall150s and output4KiB caps are separate. Synthetic acceptance additionally
requires readable exact fixture bytes, independently verified read-only mounts and
EROFS/EACCES write-open denials, network denial, large-row
codec/content proof and a SECOND detached-start watchdog container exiting142 after
its1s alarm. --init plus non-PID1 matters: Linux namespace init ignores many default
signals. Killing only the Docker CLI is NOT cleanup proof.

Container intent is published before create. On error, an exact-name kill and
terminal readback are attempted; a failure sidecar records whether termination is
established. A lost daemon can leave cleanup UNKNOWN; this is never success/retry
permission. Containers/journals are retained, not automatically removed. Do not run
docker system prune, reuse a run root or delete a failed marker. Ask for bounded
read-only reconciliation using its private intent name. No actual private attempt
has occurred during development.

## What is available and what is not verified

Builder observed Docker CLIENT29.8.2. A local-engine info check failed in this sandbox;
that is NOT an owner-window engine measurement and not a reason to elevate/change
permissions. No Docker build/container, private decode or Windows engine acceptance
is claimed. Existing dual-platform8/8 PR49 tests remain a separate prior fact.

Owner read-only, normal PowerShell, one block at a time:
```powershell
docker --version
if ($LASTEXITCODE -ne 0) { throw 'Docker client unavailable; stop commissioning' }
```
```powershell
wsl --version
if ($LASTEXITCODE -ne 0) { throw 'WSL availability not established; stop commissioning' }
```
If Desktop/WSL2 is absent, review official Windows installation requirements first.
Current Docker docs offer a per-user --user installation using WSL2, without a
privileged system service; a missing Windows virtualization/WSL feature may still
require owner-authorized elevation/reboot. That authority is NOT granted by this
runbook. Do not add docker-users membership, share broader directories, change
firewall/ACLs or reboot near capture. If that setup cannot be approved Tuesday,
defer private B until AFTER Wednesday's15:40 audit; A/capture are not blocked by it.

## One reviewed upload group (14 new paths)

Source root C:\Users\banga\Desktop\kiran_share_market; SAME relative destinations
in a fresh LF clean clone at the exact base above:

1. outcomes_private_worker.py
2. outcomes_private_container.py
3. tests/test_outcomes_private_worker.py
4. tests/test_outcomes_private_container.py
5. docker/outcomes-private.Dockerfile
6. docker/outcomes-private.requirements.txt
7. .github/workflows/outcomes-private-conformance.yml
8. normal_user_test_run.py
9. tests/test_normal_user_test_run.py
10. PRESERVATION_COMMISSION_2026-10-20.md
11. OUTCOMES_PRIVATE_RUNBOOK.md
12. outcomes_private_upload_check.py
13. tests/test_outcomes_private_upload_check.py
14. OUTCOMES_PRIVATE_UPLOAD.json

No original A files/manifests or runtime-policy exception are included. The new
workflow uses the existing Ubuntu24.04/Node24-action/Python3.13 host policy; the
DECODER IMAGE is exact Python3.13.9 Linux AMD64. Docker Hub metadata supplied the
immutable AMD64 base digest and PyPI supplied the exact PyArrow24.0.0 wheel SHA256;
the Dockerfile/requirements pins are reviewed package payload, not new evidence pins.
Do not edit any original evidence anchor. Build stage copies only six public Python
files plus Dockerfile/requirements and a generated deny-all/allowlist.dockerignore
to a fresh context; NEVER docker-build the source
folder (which contains local private credentials) or mount the whole repository.

Normal PowerShell; explicit `$bridgePython`3.13.9 from the research venv, NOT either
capture venv, never bare py. Use -B and external mypy cache; check native exit codes.
Stage ONLY the14 listed paths, then:
```powershell
& $bridgePython -B outcomes_private_upload_check.py --base e2e1d0d797e453e2fd9d12fd0df7fb8bcb968b99
if ($LASTEXITCODE -ne 0) { throw 'Package blocked; no pin edits' }
```
Focused line:
```powershell
$bridgeTestTemp = Join-Path $env:TEMP ('bridge-pytest-' + [guid]::NewGuid().ToString('N'))
& $bridgePython -B -m pytest -q -p no:cacheprovider tests/test_outcomes_private_worker.py tests/test_outcomes_private_container.py tests/test_normal_user_test_run.py tests/test_outcomes_private_upload_check.py tests/test_workflow_runtimes.py --basetemp $bridgeTestTemp
if ($LASTEXITCODE -ne 0) { throw 'Focused tests failed' }
```
Lint/type blocks:
```powershell
& $bridgePython -B -m pyflakes outcomes_private_worker.py outcomes_private_container.py normal_user_test_run.py outcomes_private_upload_check.py tests/test_outcomes_private_worker.py tests/test_outcomes_private_container.py tests/test_normal_user_test_run.py tests/test_outcomes_private_upload_check.py
if ($LASTEXITCODE -ne 0) { throw 'Lint failed' }
```
```powershell
$bridgeTypeCache = Join-Path $env:TEMP ('bridge-mypy-' + [guid]::NewGuid().ToString('N'))
& $bridgePython -B -m mypy --strict --follow-imports=silent --cache-dir $bridgeTypeCache outcomes_private_worker.py outcomes_private_container.py normal_user_test_run.py outcomes_private_upload_check.py
if ($LASTEXITCODE -ne 0) { throw 'Typing failed' }
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw 'Whitespace failed' }
```
Check repo-local Git identity presence before commit. No attribution/trailers;
one-line PR description: Add inactive contained outcomes recovery bridge.
Exact FINAL SHA quality/resilience/CodeQL must be green before OWNER merge.
No push/merge/settings change is performed by the builder. If main advances,
stop for package reconciliation rather than loosening pins.

## Repeatable FULL Windows suite, separate from capture

Use a fresh, committed clean public tools checkout; do not run from the dirty source
folder, elevated window, capture venv or private-state directory. Git cleanliness
alone is not provenance: verify HEAD against the reviewed commit yourself first.
The helper rejects ignored files except SQL node_modules, so use -B for preparation
commands and put mypy caches outside the checkout. Never delete/reset old elevated
Temp directories to make a run pass. Choose a fresh checkout if contaminated.

Install the repository's reviewed requirements and automation tooling into the
existing RESEARCH venv only if missing. Node24 and `npm ci --prefix tests/sql-harness
--ignore-scripts --no-audit --no-fund` are the reviewed SQL prerequisite; no scripts,
global upgrades or changes to capture environments. Preview:
```powershell
& $bridgePython -B normal_user_test_run.py
if ($LASTEXITCODE -ne 0) { throw 'Test-runner preview failed' }
```
Confirmed full run (holiday, enough time/disk, no capture):
```powershell
& $bridgePython -B normal_user_test_run.py --run-confirmed --python $bridgePython --with-pglite
if ($LASTEXITCODE -ne 0) { throw 'Full suite not passed; preserve logs/scratch' }
```
It verifies non-admin token, exact3.13.9, ordinary clean Git root, Node24/PGlite
lock/version and actual SELECT1; allocates new UUID scratch outside checkout; puts
all child TEMP/TMP/TMPDIR and pytest basetemp there. No chmod/move/delete/retry.
Plugin autoloading matches the environment instead of silently disabling tests.
Record full pass/fail/skip totals and platform; no completed run has yet been claimed.
Omitting --with-pglite explicitly permits SQL skips and is not the required full gate.

## Native acceptance AFTER merge, synthetic only

Owner may enable the manual workflow only for this acceptance: variable
OUTCOMES_PRIVATE_CONFORMANCE_ENABLED=true plus confirm_disposable tick. It has no
schedule/secrets/private inputs. Run on the exact reviewed final commit; inspect the
fixed check names/status and watchdog proof, then remove the variable/disable again.
Hosted Linux proves only its own disposable backend. It cannot certify Windows
Desktop, an actual external disk, private row contents or custody. Never upload
real recovery files, keys or private outputs to Actions.

Local Windows acceptance must ALSO pass before private use. After owner-approved
Desktop availability, in the clean merged checkout choose NEW external private paths
`$BuildContext`, `$ImageIdFile`, `$DockerConfig`, `$SyntheticRun`. None may preexist.
Preview stage by omitting --confirm-run, then:
```powershell
& $bridgePython -B outcomes_private_container.py --mode stage --run-root $BuildContext --confirm-run
if ($LASTEXITCODE -ne 0) { throw 'Build context not established' }
```
Create a new EMPTY Docker config directory (no -Force), then run the fixed local
engine build; Test-Path for the IID file MUST be false:
```powershell
if (Test-Path -LiteralPath $ImageIdFile) { throw 'New image receipt path required' }
if (Test-Path -LiteralPath $DockerConfig) { throw 'New empty config path required' }
New-Item -ItemType Directory -Path $DockerConfig -ErrorAction Stop | Out-Null
docker --config $DockerConfig --host npipe:////./pipe/dockerDesktopLinuxEngine build --platform linux/amd64 --iidfile $ImageIdFile $BuildContext
if ($LASTEXITCODE -ne 0) { throw 'Build failed; no private run' }
$Image = (Get-Content -LiteralPath $ImageIdFile -Raw -ErrorAction Stop).Trim()
if ($Image -notmatch '^sha256:[0-9a-f]{64}$') { throw 'Immutable image ID missing' }
```
Review/retain the local image ID against the reviewed build context; do not accept
an arbitrary image/tag or a bundle-supplied image. Build networking is for PUBLIC
pinned dependencies only; runtime private networking is none and pulling forbidden.
Preview local selftest, then in a separate block:
```powershell
& $bridgePython -B outcomes_private_container.py --mode selftest --image-id $Image --run-root $SyntheticRun --confirm-run
if ($LASTEXITCODE -ne 0) { throw 'Local native containment NOT proven; preserve and stop' }
```
Require kernel-readonly-v2, all14 exact checks, the closed root/catalog/bundle
readonly_probes details and autonomous watchdog proof; no real rows exist in this
test. Unknown mapping/permissions/cgroup/init/denial mechanism blocks, never falls
back to uncontained Windows Python or asks for ACL changes. Windows itself is not
running a Linux process natively; Desktop's reviewed Linux VM/engine is the boundary.

## Private commissioning ONLY after both acceptance gates and verified A

This is a future OWNER commissioning step, not permission from this upload.
Private host invocation is restricted to Windows/non-admin/exact3.13.9; hosted
Linux can stage public code and run synthetic acceptance, but cannot invoke the
private CLI mode. All confirmed Windows modes verify normal token/version first.
Use the existing working catalog/ZIP, not external-disk or ciphertext/key mounts.
Retain original full pins. Privately select `$PrivateRun` (new), `$Catalog`, `$Zip`,
`$CatalogSha`, `$Witness`, `$Public`, `$PublicSha`, `$Generation`, `$AcceptedDigest`
from the actual A independent trust record. Do not recalculate expected pins or
derive accepted trust from the envelope itself. Current-approved key status is an
owner prerequisite; automatic revocation discovery/rotation remains absent.

Preview by omitting BOTH confirmation switches first. Only after reviewing preview:
```powershell
& $bridgePython -B outcomes_private_container.py --mode private --image-id $Image --run-root $PrivateRun --catalog $Catalog --bundle $Zip --catalog-sha256 $CatalogSha --witness $Witness --trusted-public-key $Public --public-sha256 $PublicSha --latest-generation $Generation --latest-digest $AcceptedDigest --confirm-run --confirm-private-decode
if ($LASTEXITCODE -ne 0) { throw 'STOP: preserve intent/results; no retry or cleanup' }
```
The consumed attempt, public synthetic proof and bounded redacted result are new
private sidecars; originals are read-only. A separate input-binding sidecar binds
the original pins, exact eight ordinals, image and externally verified A head/key;
its digest is included in the host result. These new unsigned sidecars are NOT
authenticated custody; future signing/restore must retain their exact identities.
If private file permissions prohibit the
non-root read, STOP: this package does not grant permissions or silently copy data
to a broader share. Success is a structural bridge receipt, NOT restore, global
custody, training eligibility or generic876/876 acceptance. Any failed batch remains
quarantined with its original evidence; no different profile/repin/catch-up.

## Technology and remaining work

Adopt existing cryptography/PyArrow, digest+wheel pins, Docker kernel configuration
readback and a separate reviewer. Adapt Linux isolation rather than pretending a
Windows Job Object is a jail. Reject unofficial Home Sandbox, broad terminal
plugins, remote Docker contexts, paid services, CI private uploads and ACL workarounds.
Free Desktop eligibility and usable WSL2 remain owner checks; no installation was
performed. Next leverage after B: authenticated custody + matching isolated typed
restore, including DB backup facts/capacity and PG service isolation, then cold
reader/writer proof and retention last. All detailed open items are preserved in
PRESERVATION_COMMISSION_2026-10-20.md; none is silently cleared here.
Add to the restore gate: original schema/roles/functions and an explicit cross-batch
version/conflict policy. Per-file valid rows do not establish which overlapping
versions belong in a restored table or prove point-in-time application recovery.
Image/wheel pins establish identity, not absence of vulnerabilities; native tests
are not a security audit of Docker/WSL/the host kernel.

Official sources reviewed19October2026:
- https://docs.docker.com/desktop/setup/install/windows-install/
- https://docs.docker.com/engine/containers/run/
- https://docs.docker.com/engine/network/drivers/none/
- https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/
- https://hub.docker.com/v2/namespaces/library/repositories/python/tags/3.13.9-slim-bookworm
- https://pypi.org/pypi/pyarrow/24.0.0/json

## Historical verification ledger (builder, 19 October 2026; not v2 acceptance)

- Final clean candidate at the exact base: 142 focused tests passed, zero skipped;
  this includes the existing workflow runner policy and both available PowerShell
  document parsers. These are offline tests, not Task Scheduler/Docker acceptance.
- Earlier unchanged A/original catalog/footer/profile regression selection:
  129 passed, 1 skipped (Windows symlink privilege unavailable). Not a full suite.
- Eight-file pyflakes clean; strict mypy clean for the four new runtime/checker
  modules; staged whitespace clean. The manifest/index checker passed, failures[].
- Separate read-only reviewer verified the 14 staged additions, payload/prerequisite
  hashes, source/index parity, and all 26 PowerShell document blocks. Review fixed
  containment admission and PID1/watchdog issues; it is not an independent pentest.
- Public A merge checks were inspected: 9 success and 6 skipped; do not infer
  OPTION_CAPTURE_ENABLED or any commissioning from generic skipped job names.
- Native B container execution on Linux/Windows, private A/B commissioning, the
  complete local suite and exact-final-SHA hosted CI for THIS package remain NOT
  VERIFIED. Prior PR49 resource results do not establish the new containment gate.

Final manifest hashes must cover this ledger too; no private evidence or real
capture state was accessed to construct it. Merge activates nothing.
