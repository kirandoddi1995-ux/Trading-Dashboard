# Certifi security prerequisite and PR 56 replacement

## Decision and evidence boundaries

Replace the open PR 56 package with ONE combined reviewed package on exact main
`563665a32e5454633b0c27256072a7249503c520`. Do not merge the old head
`980691627ea5cb2fcf0c4bc14c300aa706c1c538`. No agent commit, push or merge.
If main advances, stop: this package does not accept an arbitrary newer base.

Owner-reported: the old PR's local gates passed (532 passed, 2 skipped), CodeQL,
Code scanning results and resilience passed, but dependency audit failed. The
old exact SHA therefore has NO full-suite/smoke/game-day/canary/package pass.
Those steps were skipped, not successful. No evidence establishes compromise.
Public read-only verification found main still at 563665a and live-backup still
at 9806916. Main's latest recorded Quality run
[39485323110](https://github.com/kirandoddi1995-ux/Trading-Dashboard/actions/runs/39485323110)
succeeded (20 Oct, 19:39:31--20:02:06 UTC). This is a historical result, NOT a
fresh dependency audit against today's advisory database. No main rerun was made.

Builder verified from primary sources: the reviewed GitHub advisory
[GHSA-6q48-6c7w-9gw2](https://github.com/advisories/GHSA-6q48-6c7w-9gw2)
affects certifi >=2019.03.09,<2026.10.19. The patched
[2026.10.19 release](https://pypi.org/pypi/certifi/2026.10.19/json) is not yanked.
The advisory concerns emSign certificate trust; TLS hostname verification alone
does not fix an incorrectly trusted CA. Do not hand-edit the bundle, suppress
the advisory, disable TLS, ignore audit findings or rotate credentials merely
on an unsupported assumption of compromise.

The certifi dependency changes from 2026.7.22 -> 2026.10.19 in constraints.txt
AND the dedicated requirements-forward-operations.txt; future_ops_diagnostics.py
expects the same patched version. requirements.txt already imports that
constraint. No other dependency upgrade. Existing installed capsules stay frozen.
Official wheel SHA-256 (provenance reference, not a new runtime admission pin):
`42d35340cc5b9ba78e818ddbff0c5b1c2b779de448a340fd1b989f5fa8670e1b`.
The builder fetched the official wheel into bounded memory, verified this hash
and size 136,464 bytes, and loaded version 2026.10.19 in a NEW disposable test
environment. Existing test/capture environments were NOT upgraded. The isolated
environment reused existing offline tools; it is not a clean complete dependency
installation or proof of an installed production runtime.

The backup uses native libpq with verify-full and the explicitly supplied
dashboard CA, not certifi's Python bundle. Its reviewed CA selection, PostgreSQL
17.11 tool hashes, container digest and verify-full requirement do not change.
Historical signed evidence and consumed container identities remain historical;
do not retag, overwrite, rerun or re-sign them to imply a new environment.

## Permanent audit topology, without a softer gate

Independent review recommended the simpler permanent topology: move the
UNCHANGED mandatory [pip-audit](https://github.com/pypa/pip-audit) command after
offline tests/game-day, BEFORE canary and packaging in the same required verify
job. No new jobs, aggregate conditions or alternate release routes. Complete
requirements resolution still imports constraints. Findings and lookup or
resolution failures still make verify red and stop canary and packaging. Failed
earlier tests may skip the audit, but cannot yield a green quality gate.

This avoids losing full-suite feedback merely because a new advisory appears.
There is no continue-on-error, advisory ignore, partial dependency audit or
release exception. A future new advisory remains a genuine merge/release block
requiring a reviewed patch.
No new scheduled workflow, bot permission, automatic merge or settings change.
Existing reusable quality callers inherit the same hard gate.

Exact-final-SHA hosted CI must prove the unchanged hard-failure execution and the
full Linux suite. Static unit tests are not proof of a hosted run. Any new
dependency alert discovered on that SHA still blocks; do not blindly retry.

Local limits: the full Windows suite was deliberately INTERRUPTED around 19%
after failures/errors; no final full-suite counts or pass are claimed. An
isolated archive-family run reproduced unchanged research_input_archive ->
automated_development_checks.write_once -> os.link failing with WinError 5:
1 failed, 288 passed, 40 skipped, stopped at first failure. No ACL change,
atomicity fallback or test skip was introduced. Other broad-suite failures are
unclassified and remain open. A fresh full requirements pip-audit resolution
did not finish within the inspection window and was interrupted; NO local
complete-audit pass is claimed. Exact-final-SHA hosted audit/full suite remains
the hard merge gate. No background full-suite or audit run is left running.

Historical manifests remain byte-for-byte unchanged. Eleven historical
current-tree self-tests use a narrow successor map in live_backup_upload_check:
only 15 named modified paths, exactly enrolled predecessor hashes, and this
package's exact successor manifest. The staged checker additionally verifies
each old blob at the exact base and every replacement in index AND worktree.
The THREE critical dependency/diagnostic successors additionally have literal
new hashes in the checker: even a rewritten manifest cannot nominate an
arbitrary replacement for them. Tests reject that attempted substitution.
This is not permission to upload old packages against a changed base or remove
an old pin. Unrelated paths, wrong predecessors, duplicate keys, malformed
manifests, stage/mode changes, extra paths and dirty trees remain rejected.

## Upload, one owner block at a time

Builder verification of the hardened combined package: 734 passed, 2 skipped,
5 subtests passed across the 22 focused files below (13.09 seconds); pyflakes clean on all
19 Python payload files; Windows strict mypy clean on four modules. Skips are
the existing symlink-privilege case and Windows POSIX-shell parser limitation,
not permission to skip hosted Linux/native acceptance. Fresh exact-base staged
rehearsal returned LIVE_BACKUP_PACKAGE_VERIFIED_REQUIRES_EXACT_COMMIT_CI,
failures [], and git diff --cached --check was clean. No commit was created.

Builder/checker separation: two read-only reviewers independently traced CI
ordering, legacy pins and TLS consumers. Their recommendations were incorporated.
The final follow-up adversarial review hit the tool's usage limit and did NOT
complete; no independent final approval or native Windows/Linux acceptance is
claimed. No paid upgrade or substitute suppression was used. Owner/exact-SHA
CI review remains required. Full-suite/audit limits above remain explicit.

Normal PowerShell, explicit existing venv Python 3.13.9 only. No capture/task,
private evidence, account, ACL, service, clock or hosted-data command is needed.
The installed 21 Oct capsule and its runtime are not part of this upload.

Use a NEW clean public main clone, core.autocrlf=false, require HEAD exactly
`563665a32e5454633b0c27256072a7249503c520`, require clean status. Create a NEW
branch and replacement PR rather than force-pushing or rewriting PR 56 history.
Leave PR 56 unmerged and close it as superseded only after the replacement is
green. One plain-line description: `Patch certifi and preserve fail-closed backup admission`.
No attribution/trailers. Check repository-local Git identity presence before
committing; do not print personal values or set a global identity.

The exact file list is the `files` dictionary in LIVE_BACKUP_UPLOAD.json: copy
each relative source from C:\Users\banga\Desktop\kiran_share_market to the
IDENTICAL relative destination in the fresh clone. Copy nothing else. The JSON
manifest is not executable and the checker does not read private backup files.
There are 26 paths: 15 explicit modifications and 11 additions (including the
still-unmerged backup package). No old merged manifest/checker is rewritten.
Exact source -> destination mapping is the same relative path under source root
`C:\Users\banga\Desktop\kiran_share_market` and the NEW clean clone root:

```text
live_database_backup.py
live_backup_conformance.py
tests/test_live_database_backup.py
tests/test_live_backup_conformance.py
.github/workflows/live-backup-conformance.yml
live_backup_upload_check.py
tests/test_live_backup_upload_check.py
LIVE_BACKUP_HANDOFF_2026-10-21.md
tests/test_dependency_security.py
DEPENDENCY_SECURITY_HANDOFF_2026-10-21.md
constraints.txt
.github/workflows/quality.yml
tests/test_archive_verify_upload_check.py
tests/test_commissioning_next_upload_check.py
tests/test_legacy_rehearsal_upload_check.py
tests/test_recovery_incident_upload_check.py
tests/test_outcomes_footer_upload_check.py
tests/test_outcomes_large_upload_check.py
tests/test_archive_preservation_upload_check.py
tests/test_outcomes_private_upload_check.py
tests/test_preservation_integer_upload_check.py
tests/test_outcomes_readonly_upload_check.py
tests/test_recovery_contract_upload_check.py
requirements-forward-operations.txt
future_ops_diagnostics.py
LIVE_BACKUP_UPLOAD.json
```

After copying, stage exactly that list (read the public manifest's files keys).
Run, as separate blocks, stopping at any nonzero result:

```powershell
$ErrorActionPreference = 'Stop'
$python3139 = 'C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
& $python3139 -I -B -c "import sys; print(sys.version.split()[0])"
if ($LASTEXITCODE -ne 0) { throw 'Interpreter check failed' }
# Require printed version exactly 3.13.9. Never use bare py.
$paths = (Get-Content LIVE_BACKUP_UPLOAD.json -Raw | ConvertFrom-Json).files.PSObject.Properties.Name
git add -- $paths
if ($LASTEXITCODE -ne 0) { throw 'Stage failed' }
& $python3139 -B live_backup_upload_check.py --base 563665a32e5454633b0c27256072a7249503c520
if ($LASTEXITCODE -ne 0) { throw 'Package blocked' }
```

```powershell
$ErrorActionPreference = 'Stop'
& $python3139 -B -m pytest -q -p no:cacheprovider tests/test_dependency_security.py tests/test_live_database_backup.py tests/test_live_backup_conformance.py tests/test_live_backup_upload_check.py tests/test_workflow_runtimes.py tests/test_archive_preservation_inventory.py tests/test_archive_preservation_witness.py tests/test_archive_restore_policy.py tests/test_archive_recovery_binding.py tests/test_project_conductor.py tests/test_archive_verify_upload_check.py tests/test_commissioning_next_upload_check.py tests/test_legacy_rehearsal_upload_check.py tests/test_recovery_incident_upload_check.py tests/test_outcomes_footer_upload_check.py tests/test_outcomes_large_upload_check.py tests/test_archive_preservation_upload_check.py tests/test_outcomes_private_upload_check.py tests/test_preservation_integer_upload_check.py tests/test_outcomes_readonly_upload_check.py tests/test_recovery_contract_upload_check.py tests/test_future_ops_diagnostics.py
if ($LASTEXITCODE -ne 0) { throw 'Focused tests failed' }
```

Run pyflakes on both new backup modules, checker, new security test and modified
test files. Strict mypy uses a REAL new temp cache directory, never NUL, for
live_database_backup.py, live_backup_conformance.py, live_backup_upload_check.py,
future_ops_diagnostics.py. Windows strict typing passed for these four; the
Linux-target check reproduced exactly seven errors in the unchanged Package A
archive_preservation_inventory.py, not a Linux pass. This is type-stub checking,
not native Linux acceptance.
Run `git diff --cached --check`. Run the full offline suite before upload when
the owner machine can do so without disturbing capture; retain counts/skips/
failures. A platform restriction is reported, never relabelled as a pass.
Exact-final-SHA hosted Linux full-suite Quality, Resilience, CodeQL AND Code
scanning results must all be green before owner merge. If tests or manifest
change, all gates apply to the NEW final SHA, not an earlier SHA.

Do not upgrade the shared test venv or an installed capture during a live day.
A source merge patches NEW installations, not existing runtimes automatically.
After capture/audit, commission a separate reviewed rebuilt runtime/capsule
with the patched dependency, original clock/hash/source gates and full rehearsal.
Do not mutate a frozen capsule in place or change Streamlit expectations/release
hold. Inventory deployed versions with a future narrow no-credential observer;
until checked, existing installed/hosted runtime remediation is NOT VERIFIED.

## Remaining work: deliberate order and disposition

1. This security prerequisite and exact-final-SHA full CI first. Main's current
   audit status is not measured here; the unmerged vulnerable pin is confirmed.
2. After today's capture and scheduled/manual audit: owner native backup
   acceptance on the GREEN MERGED source, both hosted disposable conformance and
   Windows directory drill. These are not proven by unit tests. Keep workflow
   variables absent/disabled until explicit owner commissioning. No production
   connection before the source, tool/CA, directory and read-only facts gates.
   DB backup facts and fresh capacity are NOT measured by this dependency work;
   use the already reviewed read-only inventory/backup runbook before export.
3. Native backup and new generation, then signed collector joining existing A/B
   evidence with the exact backup generation. Do NOT claim same-generation full
   restore, custody or historic receipt authenticity from independent signatures.
   Collector build intentionally deferred: depends on real accepted backup
   artifacts and reviewed destination identity, not fabricated placeholders.
4. Typed isolated staging with schema/role/function/extension inventory and
   explicit cross-batch conflict policy; then exact cold-reader/writer proof;
   retention/deletion LAST after matching restore and independent custody.
   Non-loopback local PostgreSQL is not an accepted private restore target; no
   service/listener setting was changed. Same-account Google Drive is NOT an
   independent account failure domain. Signed A observation/B structural output
   remain different claims from authenticated destination custody and a matching
   restore. The original archive verifier remains 868/876; this patch does not
   promote the eight contained outcomes checks into original catalog acceptance.
5. Seven Linux-target typing errors in unchanged Package A inventory remain
   separate: changing that helper now would invalidate signed/pinned closure and
   expand this emergency prerequisite. No suppression or fake Linux pass. A
   subsequent native-platform-boundary repair must retain Windows acceptance.
6. Production failure-alert routing, Windows Time stop/root dispersion, missing
   14 Oct saved audit, legacy audit exit 2/shared-root writes remain open. No
   inference that a synthetic popup clears real failure delivery. Diagnostics
   later must be bounded/read-only and not touch today's capture or journals.
7. OPTION_CAPTURE_ENABLED remains off; sessions JSON ending 1 Oct requires a
   reviewed calendar-source update, not invented sessions. Holiday collector
   #175/#176 failures need a genuine exchange-calendar skip policy and tests;
   no failed holiday run is retried or backfilled in this package.
8. ML/backtesting/LLM remain gated on data licences, proper labels, frozen paper
   study and sufficient real evidence. No training, retuning or performance claim.
9. Duplicate Downloads/.7z copies are retained: no cleanup before authenticated
   inventory/custody and restore. Full local suite unclassified failures and
   WinError 5 hard-link case remain tracked until reproduced/classified; permissions
   are not changed to force green. No stale historical count is a current pass.

Technology radar: adopted the existing pinned pip-audit and official certifi
patch; adapted CI ordering so offline evidence precedes hard audit admission.
Rejected advisory suppression, bundle surgery, automatic dependency merges,
new paid services and terminal plugins for a deterministic dependency change.
No new plugin/account/service installation is needed. Next highest leverage:
an exact environment-to-source provenance inventory and successful real isolated
backup/restore, before retention or modelling.
