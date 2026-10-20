# Read-only mount acceptance and bounded diagnostics (20 October 2026)

## Status: three distinct evidence levels

OWNER-REPORTED: PR53/main b18f5af, A generation1 signed and independently verified
as PRESERVATION_SIGNATURE_VERIFIED_NOT_CUSTODY; accepted head retained privately.
Existing B local Windows/WSL2/Linux-engine acceptance passed14 checks/watchdog on
the prior image. Hosted run1 failed input_readonly; its variable was removed.
No private attempt occurred. None of those reports is authenticated physical
custody, restore, deletion approval or acceptance of the NEW proof profile.

BUILDER-VERIFIED: public main base is b18f5af7e73f37f0eb61bc1fab47bf41d4786f4b;
old source accepts only errno EROFS and probes only catalog, not bundle. It does
not report the observed denial class. No hosted rerun, private artifact/secret,
capture installation/task, service, setting, ACL or owner data was touched.

INFERENCE: UID65534 cannot write a host-owned0644 synthetic file on ordinary Linux.
Permission checking may return EACCES before EROFS, even with a read-only mount.
Docker Desktop may expose different file-permission semantics. This plausibly
explains the platform difference; old logs do NOT establish the actual errno.
Do not label a runner defect, actual writable mount or proven DAC cause yet.

## Permanent proof, not an errno bypass

Profile is now kernel-readonly-v2. The existing14 check labels remain, but the
proof is versioned and stronger; old-image/old-report schemas are rejected.

For each fixed SYNTHETIC target (root/, catalog, bundle):
1. Open read-only/no-follow; require correct object type.
2. Read bounded /proc/self/fdinfo for that descriptor's mnt_id.
3. Match exactly one bounded /proc/self/mountinfo record at the expected target,
   require its ro flag AND independent fstatvfs(fd).f_flag/ST_RDONLY.
4. Attempt write-open: no truncation or creation on input files; root-only creation
   probe stays inside the disposable synthetic container. Never write actual inputs.
5. Recheck identity and mount view after the probe. Only EROFS or EACCES denials
   qualify, AND ONLY when all independent read-only/identity proofs passed.

RW+EACCES fails. EROFS without kernel proof fails. Missing/changed mount identity,
wrong object type, successful write-open, EPERM/ENOENT/ELOOP/unknown denial or failed
readback fails closed. EACCES means access denied ON a verified read-only mount;
it does not establish which protection caused denial. No permission or umask change
is needed, even for synthetic fixtures.

Before any actual private decode, root read-only kernel admission is mandatory;
BOTH actual input descriptors also get NON-MUTATING read-only/identity admission
before and after use, retaining the pre-read device/inode/size/times/mount-ID
snapshot and requiring it to match afterward. No write probes run on private inputs. Exact Docker requested/
effective mounts, nonroot/capabilities/network/resource/watchdog checks stay intact.
Host/daemon compromise and host remounting outside observed gates are not solved.

## Diagnosable output without private values

readonly_probes has exactly root, catalog, bundle. Each has only:
- read_fd_opened, kind_matches, mount_bound, mount_readonly, identity_stable: booleans.
- write_open_result: EROFS, EACCES, EPERM, ENOENT, ELOOP, OTHER_DENIAL,
  OPEN_SUCCEEDED or NOT_ATTEMPTED.

The host rejects unknown fields/types/labels and inconsistent derived check flags.
It emits only this closed vocabulary, not raw errors, paths, IDs, permissions,
mount tables or file contents. Input diagnostics cover BOTH files. A failed valid
proof reports SYNTHETIC_CONTAINER_CHECK_FAILED with failed_checks and these details,
instead of the previous generic reason. Malformed proof/profile errors block with
fixed codes. Worker JSON duplicate keys are rejected and response bounds remain.
Only a new native run can tell which observed predicate/class failed on that host.

## One additive/modified upload group: exact11 paths

Base b18f5af7e73f37f0eb61bc1fab47bf41d4786f4b. Source root
C:\Users\banga\Desktop\kiran_share_market; SAME relative destinations in a fresh LF
clean clone. No commits/pushes/merges by builder; owner alone uploads/merges.

Modified7:
1. outcomes_private_worker.py
2. outcomes_private_container.py
3. tests/test_outcomes_private_worker.py
4. tests/test_outcomes_private_container.py
5. tests/test_outcomes_private_upload_check.py
6. tests/test_preservation_integer_upload_check.py
7. OUTCOMES_PRIVATE_RUNBOOK.md

Added4:
8. outcomes_readonly_upload_check.py
9. tests/test_outcomes_readonly_upload_check.py
10. OUTCOMES_READONLY_REPAIR_2026-10-20.md
11. OUTCOMES_READONLY_UPLOAD.json

Historical A/B/integer manifests/checkers stay unchanged. Historical hash tests
recognise only this explicit successor for7 enrolled old-source hashes; the new
gate binds old base blobs and new index/worktree hashes. No skip/hash fallback.
Workflow, base-image/wheel pins, original archive verifier and private evidence pins
are unchanged. Verification remains868/876; no key/witness/measurement regeneration.

Normal non-admin PowerShell, one block at a time, ErrorActionPreference Stop;
$readonlyPython is the explicit RESEARCH Python3.13.9 (never bare py/capture venv).
Stage exactly11 paths, then:
```powershell
& $readonlyPython -B outcomes_readonly_upload_check.py --base b18f5af7e73f37f0eb61bc1fab47bf41d4786f4b
if ($LASTEXITCODE -ne 0) { throw 'Package blocked; do not edit pins' }
```
```powershell
$readonlyTestTemp = Join-Path $env:TEMP ('readonly-tests-' + [guid]::NewGuid().ToString('N'))
& $readonlyPython -B -m pytest -q -rs -p no:cacheprovider tests/test_outcomes_private_worker.py tests/test_outcomes_private_container.py tests/test_outcomes_private_upload_check.py tests/test_preservation_integer_upload_check.py tests/test_outcomes_readonly_upload_check.py tests/test_preservation_integer_contract.py tests/test_archive_preservation_inventory.py tests/test_archive_preservation_witness.py tests/test_archive_preservation_upload_check.py tests/test_workflow_runtimes.py --basetemp $readonlyTestTemp
if ($LASTEXITCODE -ne 0) { throw 'Focused tests failed' }
```
```powershell
& $readonlyPython -B -m pyflakes outcomes_private_worker.py outcomes_private_container.py outcomes_readonly_upload_check.py tests/test_outcomes_private_worker.py tests/test_outcomes_private_container.py tests/test_outcomes_private_upload_check.py tests/test_preservation_integer_upload_check.py tests/test_outcomes_readonly_upload_check.py
if ($LASTEXITCODE -ne 0) { throw 'Lint failed' }
```
```powershell
$readonlyTypeTemp = Join-Path $env:TEMP ('readonly-types-' + [guid]::NewGuid().ToString('N'))
& $readonlyPython -B -m mypy --strict --follow-imports=silent --cache-dir $readonlyTypeTemp outcomes_private_worker.py outcomes_private_container.py outcomes_readonly_upload_check.py
if ($LASTEXITCODE -ne 0) { throw 'Strict typing failed' }
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw 'Whitespace failed' }
```
Check repo-local identity presence, no attribution/trailers. One-line PR description:
Strengthen read-only mount proof and add bounded containment diagnostics.
Exact-FINAL-SHA Quality FULL suite, Resilience, CodeQL Analyze AND Code scanning
results must all be green before owner merge. If main advances, reconcile first.

## Owner native acceptance AFTER green merge: one fresh attempt per gate

1. Keep original Linux failure and old local/image receipts. No delete/reset/prune,
   same-root retry, variable left enabled or private invocation.
2. Manually enable outcomes-private-conformance.yml only for the reviewed test with
   OUTCOMES_PRIVATE_CONFORMANCE_ENABLED=true AND confirm_disposable ticked. Dispatch
   once on the reviewed merged commit. It builds the new public source/image.
3. Inspect fixed output: kernel-readonly-v2, all14 checks true, all3 probe records
   accepted, autonomous_watchdog_verified true. On block preserve JSON/run ID; do not
   rerun. Remove variable/disable again after the single run, success or failure.
4. Independently stage/build a NEW local public context, NEW image-ID receipt, NEW
   empty config and NEW synthetic run root, using OUTCOMES_PRIVATE_RUNBOOK.md's
   existing commands from the fresh merged tools checkout. Enroll the actual new
   image ID; do not substitute the previous image or copy an IID from an archive.
5. Run local synthetic acceptance once. The old Windows pass is historical, not
   the new profile's acceptance. Require the same14+3+watchdog proof.
6. Only after BOTH gates pass may the owner separately commission a private run
   using the existing trusted A key/head and new image. Every private attempt still
   performs fresh local synthetic/watchdog admission. No private data in Actions.

Merge alone enables nothing. No native workflow/build/selftest/private execution
was run by the builder. The host's existing Docker client is not a new tool gap;
do not reinstall, elevate, change permissions or weaken checks to get this green.

## Full open-items and deliberate scope

Bundle only B proof/diagnostics, regression and exact-upload tooling now. A signature
verification is owner-reported complete, NOT custody. Existing key/head/selection/
measurement stay unchanged; no repeat commissioning/re-sign needed for this code.

Still open: new B native/private acceptance; DB backup facts/fresh capacity;
authenticated custody, same-generation isolated typed/full restore with schema and
cross-batch conflict policy; cold readers AND guarded writers; retention/Drive's
failure domain; actual production failure-alert delivery; PG17 non-loopback/manual
start; Windows Time12:48/root dispersion; missing14October audit; legacy audit2/
shared-root writes; OPTION_CAPTURE_ENABLED off; unidentified sessionsJSON ending
1October (do not edit); legacy receipt/historical-key authentication; complete local
suite incl unclassified failures/WinError5 hard-link denial; licensed labels/frozen
paper study and gated ML/backtests/LLM; duplicate encrypted/ZIP/inventory copies;
holiday175/176 failures. Nothing is cleared by a synthetic containment pass.

Wednesday21October manual capture remains independent: fresh21October download of
genuine19October close; disabled tasks before Prepare/policy freeze<09:15; Start
once around08:00 under the existing wait bound; personally see supervised polls and
09:30:30 automatic receipt; AC/awake/signed in through15:30:30 and15:40audit. No
capture files/state/tasks, clock gates, release hold, workflows or secrets changed.

Technology radar: adopt Linux per-descriptor mount identity/ST_RDONLY plus Docker
configuration readback and fixed-vocabulary diagnostics; adapt errno assumptions,
not the security goal. Reject EACCES-only acceptance, chmod/chown/umask changes,
root execution, skipped hosted gate, paid tools and suppressions. No install needed.
Next leverage after B: matching-generation typed restore and conflict-policy proof,
then cold-reader/writer integration, retention last.

Official sources reviewed20October2026:
- https://man7.org/linux/man-pages/man2/open.2.html
- https://man7.org/linux/man-pages/man3/statvfs.3.html
- https://github.com/torvalds/linux/blob/master/fs/statfs.c
- https://docs.docker.com/engine/storage/bind-mounts/

Builder verification on the clean exact-base Windows candidate:327 focused tests
passed,1 skipped (Windows symlink privilege unavailable). Eight-file pyflakes
clean; strict mypy clean for the3 runtime/checker modules; exact11-file staged gate
passed with failures[]; whitespace clean. Separate reviewer verified the retained
pre-read snapshot fix, closed diagnostic schema, index/hash parity, unchanged old
pins and all16 PowerShell document blocks. No full-suite pass is claimed; previous
native hard-link/unclassified failures remain open rather than silently skipped.

Native acceptance of THIS profile on hosted Linux or local Windows, private decode,
and future exact-SHA hosted CI remain NOT VERIFIED. No new container/native workflow
was executed by the builder. Do not infer operational acceptance from mocks.
