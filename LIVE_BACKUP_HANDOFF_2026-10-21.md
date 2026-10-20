# Protect surviving live data first — inactive package

**Ready:** an owner-run opaque logical-export wrapper, source tests, a disabled
synthetic native restore workflow, and this runbook. **Not ready/proven:** a real
live backup, native Windows directory locks, Linux native restore acceptance,
encrypted backup custody or a private typed restore. Installed capture is untouched.

Exact public base: `563665a32e5454633b0c27256072a7249503c520` (PR55).
No commits, pushes, merges, hosted reads/writes, private evidence/key reads,
capture/task/service/ACL changes or real backup runs by the builder.

## Decision and evidence boundaries

The missing surviving-live-data backup now comes first. A/B already preserve and
partly validate the legacy collection, but cannot recreate the current database's
schema, roles, functions or policies. A new backup will NOT recover rows deleted
before its snapshot. Preserve both tracks; do not replace one with the other.

- Builder verified public HEAD at the exact base, unchanged prerequisite source,
  synthetic tests and the staged source package. Independent review is separate.
- Owner-reported: A generation1 signed, B contained8-batch/723-row check passed,
  original verifier868/876, copies on PC/same-account Drive/external disk.
  None is newly inspected or promoted to authenticated custody here.
- Owner-reported SQL at20Oct20:06UTC: current DB345,214,099 bytes; eight target
  relations/PKs and listed extensions present. Plain SELECTs do not imply source
  writes, but `transaction_read_only=off` means transaction-level read-only
  enforcement was not demonstrated. These observations are not a consistent cut.
  No cluster-size result: do not subtract this current-DB value from the quota or
  reuse the old55-day runway as a current measurement. Reltuples are estimates.
- Owner-reported Free-plan page: no included project backups. This establishes
  no accessible included platform backup, not that some other manual dump exists.
  Until demonstrated otherwise, treat surviving live data as unbacked-up.
- Owner-reported C:87.8GB free; Docker object allocation is NOT Docker VM free
  space. D: intentionally offline: no need to reconnect it for source development.
- Latest host PostgreSQL observation is **Automatic/non-loopback/port5433**,
  superseding the earlier Manual-start report. Do not use/start/change it here.

## Permanent order

1. Merge and verify this inactive package. Commission its disposable synthetic
   acceptance separately, AFTER capture/audit, never during the installed session.
2. Make one supervised opaque live logical export, if all gates below pass.
3. Encrypt the NEW export and verify an off-PC copy/extraction; preserve originals.
4. Build the destination-bound collector binding A/B sidecars AND the new backup
   generation. Dedicated A observation signatures remain distinct from measured
   physical custody and from original receipt/Drive-ID authenticity. Never rerun
   the consumed B attempt merely to get new timestamps or sidecars.
5. Obtain a source-compatible isolated restore image/dependency plan; stage every
   legacy version with source positions, run conflict review, then establish any
   justified consistent-cut restore. Exact duplicate classification is not deletion.
6. Prove cold-reader agreement, matching restoration and delivery of alerts.
   Only then commission bounded retention, archive deletion and wider ingestion.

Keep archive deletion false, its scheduled workflow held, release/training/model
holds unchanged. Do not widen ingestion or run compaction/migrations as a backup
substitute. No automatic pause/resume of existing collectors is introduced.

## What the wrapper does — and does not

`live_database_backup.py` preview performs zero IO. Real execution is Windows,
non-admin, real console, explicit Python3.13.9, owner-approved native executable
hashes and exact PostgreSQL17.11 versions. The destination is a NEW local private
directory outside source. A12GiB free-space floor covers this exporter only, not
encryption, staging or a full restore. Dump cap4GiB; roles/TOC each16MiB; no silent
truncation. Failure consumes/preserves the directory and partials; no cleanup,
overwrite, automatic retry, password reset or permission broadening.

Fixed source: the existing project's session-pooler host, port5432, database
postgres and owner account. No arbitrary endpoint, local5433 fallback, source
SQL, table filter or command parameter is accepted. The wrapper does NOT load
Streamlit/GitHub/Windows credential stores, environment database URLs or secrets.
Native PostgreSQL prompts on CONIN$/CONOUT$; the wrapper never receives the
password. No password argv, PGPASSWORD, generated passfile or service discovery.
Default client certificate/key discovery is disabled; server TLS stays
verify-full with the owner's dashboard CA. Unsupported/non-console/MSYS contexts
block. Do not pipe, redirect or run it through an agent terminal.

Only fixed commands run: full-default custom-format `pg_dump`, separate
`pg_dumpall --roles-only --no-role-passwords`, and local `pg_restore --list`.
No schema/table/data exclusions, RLS-limited fallback, no-owner or no-ACL flags.
Permission/RLS failures block; a successful subset is never called a full backup.
Roles-only does not include every global object (e.g. tablespaces/parameter ACLs).
The two exports are NOT an atomic cluster snapshot. Native single-DB MVCC
consistency is not a historical archive cut or proof of role/config consistency.

Child stdout is binary-safe, bounded and hashed. All stderr is drained, bounded
and projected to fixed categories/phase names; any stderr, even exit0 warnings,
blocks success. Raw server messages are never echoed. Terminal input mode is
restored/checked on exit. Queue/thread startup, cancellation and child timeout
have cleanup paths. The watchdog is cooperative, not an autonomous sandbox for
a hung kernel filesystem write. Only the newly launched child is terminated.

Windows output guards hold the directory chain without delete sharing and create
files exclusively through native volume paths, not a cached PowerShell drive.
Reopened native identities and hashes are checked. This is not a defense against
a compromised OS, administrator or hostile code running as the same user before
the initial directory admission. Existing private-folder access remains the
owner's responsibility; the wrapper does not inspect or repair ACLs.
Every confirmed wrapper mode also requires an externally approved exact clean
source commit and revalidates the committed package/prerequisite hash closure.
It cannot be commissioned from this uncommitted working source folder.

Five sensitive plaintext files are retained: attempt.json, database.dump,
roles.sql, toc.list, manifest.json. They may contain authentication/configuration
data even though role passwords are omitted. Do not upload them or logs to Git.
The manifest is unsigned, its times are local clock observations, and hash/TOC
success is NOT a restore, custody, source-platform-completeness or ML claim.

## Upload: ONE PR, nine additions, no existing files replaced

Source root: `C:\Users\banga\Desktop\kiran_share_market`.
Copy to identical relative destinations in the clean clone at the exact base:

```text
live_database_backup.py -> live_database_backup.py
live_backup_conformance.py -> live_backup_conformance.py
tests/test_live_database_backup.py -> tests/test_live_database_backup.py
tests/test_live_backup_conformance.py -> tests/test_live_backup_conformance.py
.github/workflows/live-backup-conformance.yml -> .github/workflows/live-backup-conformance.yml
live_backup_upload_check.py -> live_backup_upload_check.py
tests/test_live_backup_upload_check.py -> tests/test_live_backup_upload_check.py
LIVE_BACKUP_HANDOFF_2026-10-21.md -> LIVE_BACKUP_HANDOFF_2026-10-21.md
LIVE_BACKUP_UPLOAD.json -> LIVE_BACKUP_UPLOAD.json
```

Normal PowerShell, one block at a time, clean-clone routine, autocrlf=false.
Check repo-local author identity presence before committing; do not print it.
No `.csv` force-add is needed. Stage exactly these nine regular-file additions.
If main has changed, STOP for reconciliation; never edit pins to pass the checker.

```powershell
$ErrorActionPreference = 'Stop'
$researchPython = 'C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
& $researchPython -I -B -c "import sys; assert sys.version_info[:3] == (3,13,9)"
if ($LASTEXITCODE -ne 0) { throw 'REVIEWED_PYTHON_REQUIRED' }
& $researchPython -B live_backup_upload_check.py --base 563665a32e5454633b0c27256072a7249503c520
if ($LASTEXITCODE -ne 0) { throw 'PACKAGE_CHECK_BLOCKED' }
```

Focused tests include the workflow-wide runtime policy that caught PR49:

```powershell
$ErrorActionPreference = 'Stop'
$liveBackupTests = Join-Path ([IO.Path]::GetTempPath()) ('live-backup-tests-' + [guid]::NewGuid().ToString('N'))
& $researchPython -B -m pytest -q -rs -p no:cacheprovider --basetemp "$liveBackupTests" tests/test_live_database_backup.py tests/test_live_backup_conformance.py tests/test_live_backup_upload_check.py tests/test_workflow_runtimes.py tests/test_archive_preservation_inventory.py tests/test_archive_preservation_witness.py tests/test_archive_restore_policy.py tests/test_archive_recovery_binding.py tests/test_project_conductor.py
if ($LASTEXITCODE -ne 0) { throw 'FOCUSED_TESTS_FAILED' }
```

```powershell
$ErrorActionPreference = 'Stop'
& $researchPython -B -m pyflakes live_database_backup.py live_backup_conformance.py live_backup_upload_check.py tests/test_live_database_backup.py tests/test_live_backup_conformance.py tests/test_live_backup_upload_check.py
if ($LASTEXITCODE -ne 0) { throw 'LINT_FAILED' }
$liveBackupTypes = Join-Path ([IO.Path]::GetTempPath()) ('live-backup-mypy-' + [guid]::NewGuid().ToString('N'))
& $researchPython -B -m mypy --strict --cache-dir "$liveBackupTypes" live_database_backup.py live_backup_conformance.py live_backup_upload_check.py
if ($LASTEXITCODE -ne 0) { throw 'STRICT_TYPES_FAILED' }
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw 'STAGED_DIFF_FAILED' }
& $researchPython -B live_backup_upload_check.py --base 563665a32e5454633b0c27256072a7249503c520
if ($LASTEXITCODE -ne 0) { throw 'FINAL_PACKAGE_CHECK_BLOCKED' }
```

Commit/PR contain no attribution/trailers; one-line description:
`Add inactive opaque live-database backup and isolated synthetic restore acceptance.`
Require exact-final-SHA full Quality/Linux, Resilience, CodeQL Analyze AND Code
scanning results green. Owner alone merges. Source merge does not commission IO.

## Native gates AFTER merge, only if the owner explicitly commissions them

Do this when installed capture AND audit have finished; no change to their route.
Use a fresh clean checkout of the reviewed merged package. No bare py (its default
is3.15). No test source, marker, recipe, journal, ACL, service or credential edits.
Set `$liveBackupReviewedSha` to the exact merged SHA whose hosted checks you
personally verified green. Copy it from that reviewed GitHub record, not from an
unverified current tree. Each confirmed wrapper command below requires that pin.

1. Preview: `& $researchPython -B live_database_backup.py` must return PREVIEW with
   zero reads/network/writes. It does not authorize export.
2. Owner may enable ONLY `LIVE_BACKUP_CONFORMANCE_ENABLED=true` temporarily and
   dispatch **Disposable live logical backup conformance**, confirmation ticked,
   on the exact reviewed main SHA. Then remove ONLY that variable. No schedule,
   source secrets/private input/artifact upload is used. It pulls a fixed
   LinuxAMD64 PG17.11 digest and restores a synthetic database into a SECOND fresh
   cluster, inside one network-none container, no ports/host bind/socket mounts.
   Ten cases check typed values, keys, RLS, ownership/grants, functions/triggers,
   sequence state and password-free roles. Failed case reports use fixed names.
   A final stopped-state check is required; container retained, never pruned.
   On BLOCKED, retain run ID/log and stop for review, not a blind rerun.
3. Native Windows namespace drill, separate NEW synthetic destination:

   ```powershell
   $ErrorActionPreference = 'Stop'
   $liveBackupDrill = Join-Path "$env:USERPROFILE\Documents\TradingResearch" ('live-backup-directory-drill-' + [guid]::NewGuid().ToString('N'))
   & $researchPython -B live_database_backup.py --mode directory-drill --reviewed-source "$liveBackupReviewedSha" --run-root "$liveBackupDrill" --confirm-no-capture-running --confirm-run
   if ($LASTEXITCODE -ne 0) { throw 'DIRECTORY_DRILL_BLOCKED_PRESERVE_NO_RETRY' }
   ```

   Require SYNTHETIC_WINDOWS_DIRECTORY_LOCK_PASSED and all three lock fields true.
   It creates only new synthetic directories/file; it attempts moves ONLY of
   those objects and requires native sharing violation32, not ACL denial5.
   Nothing is moved back or erased if a probe unexpectedly succeeds. No PG
   process, real secret or source connection. This is not physical custody.
4. Confirm the existing dashboard CA file is present; no password reset or new
   secret store. Enroll the installed tool hashes privately, only from the
   explicit trusted installation (first-observed enrollment, not publisher proof):

   ```powershell
   $ErrorActionPreference = 'Stop'
   $liveDumpPin = (Get-FileHash -LiteralPath 'C:\Program Files\PostgreSQL\17\bin\pg_dump.exe' -Algorithm SHA256).Hash.ToLowerInvariant()
   $liveRolesPin = (Get-FileHash -LiteralPath 'C:\Program Files\PostgreSQL\17\bin\pg_dumpall.exe' -Algorithm SHA256).Hash.ToLowerInvariant()
   $liveRestorePin = (Get-FileHash -LiteralPath 'C:\Program Files\PostgreSQL\17\bin\pg_restore.exe' -Algorithm SHA256).Hash.ToLowerInvariant()
   ```

   Set `$liveBackupCa` to the ALREADY owner-reviewed dashboard CA file path, not
   an invented path, key or downloaded executable. In the same normal console:

   ```powershell
   $ErrorActionPreference = 'Stop'
   & $researchPython -B live_database_backup.py --mode check-local --reviewed-source "$liveBackupReviewedSha" --ca-file "$liveBackupCa" --pin-pg-dump "$liveDumpPin" --pin-pg-dumpall "$liveRolesPin" --pin-pg-restore "$liveRestorePin" --confirm-run
   if ($LASTEXITCODE -ne 0) { throw 'LOCAL_TOOL_CHECK_BLOCKED' }
   ```

   Require LOCAL_NATIVE_TOOLS_CHECKED_NOT_SOURCE_OR_RESTORE. No source connection.
   If a path/tool/version/console is rejected, do not substitute bare py, a
   different executable or TLS settings. Tools are already owner-reported present;
   no install is needed for this package. Native password prompting/Unicode and
   cancellation remain an explicitly supervised first-use boundary, not a mocked
   test claim. If the expected hidden native prompt does not appear, STOP/Ctrl+C,
   do not type a password elsewhere or retry that attempt.

## One live opaque export — separate explicit owner commission

Only after exact-SHA source gates, real Linux native success, Windows directory
drill and tool check. The existing private parent must exist. Do NOT pre-create
the new run directory. Existing manually verified postgres credential is used at
native prompts only; never enter the7z unlock value or A key passphrase.
The flag below is an owner attestation of native acceptance, not machine-verified
CI authentication; absent/failed proof means DO NOT supply it.

```powershell
$ErrorActionPreference = 'Stop'
$liveBackupRoot = Join-Path "$env:USERPROFILE\Documents\TradingResearch" ('live-db-backup-' + [guid]::NewGuid().ToString('N'))
```

The next block is the native invocation **alone**. Do not paste any follow-up
commands or checks while either hidden password prompt is active. A clipboard
containing terminal commands is NOT a database password. Wait for both prompts,
the final JSON and the normal PowerShell prompt before executing another block.

```powershell
& $researchPython -B live_database_backup.py --mode export --reviewed-source "$liveBackupReviewedSha" --run-root "$liveBackupRoot" --ca-file "$liveBackupCa" --pin-pg-dump "$liveDumpPin" --pin-pg-dumpall "$liveRolesPin" --pin-pg-restore "$liveRestorePin" --confirm-no-capture-running --confirm-opaque-holdout-backup --confirm-native-acceptance --confirm-run
```

Only AFTER the invocation has returned:

```powershell
$ErrorActionPreference = 'Stop'
if ($LASTEXITCODE -ne 0) { throw 'BACKUP_BLOCKED_PRESERVE_PARTIALS_NO_RETRY' }
```

Expect two native hidden password prompts (database and roles), then
OPAQUE_LOGICAL_EXPORT_NOT_RESTORE. It copies holdout data opaquely for recovery,
does not inspect its values, derive labels or use it for analysis/training.
New native warnings, full disk, permission, authentication, timeout or interruption
block. Keep every partial and report ONLY fixed JSON phase/code, never native
messages/files. No same-directory retry, deletion, marker reset, grant change,
automatic narrower export or reusing a success-looking partial.

After successful export, separately encrypt exactly those five files into a NEW
7z AES256/header-encrypted archive using the existing reviewed7-Zip hidden-prompt
routine. Never overwrite archive-recovery-20261019.7z. Keep a private ciphertext
size/SHA256 anchor and manifest hash, test7z, copy off-PC, download/read back and
extract to a NEW private scratch directory; compare all five exact hashes.
Do not automatically delete plaintext, scratch, originals, containers or old
Downloads duplicates. D: can stay offline until the owner performs the copy;
its physical identity/capacity must be re-established then. Same-account Drive
is another remote copy, not account-failure independence. These remain measured
owner observations until the destination-bound custody adapter is commissioned.

## What still blocks real restore

The generic fixture proves PostgreSQL dump mechanics, not compatibility with
Supabase pg_cron/pg_net/vault or every platform object. Plain postgres17.11 lacks
those extensions; do NOT feed the real archive/roles to it, and never use host5433.
Review source server build, available matching Supabase-compatible image,
extension versions/config tables, role mappings, DDL/function/trigger/policy and
job dependencies FIRST. Disable/contain execution before any private DDL/data:
network-none, no host ports, no host PGDATA/socket/real credentials, jobs/workers
inactive. Some managed secrets/Storage objects/platform settings are outside a
logical DB dump. No roles-file execution on the owner PC or live database.

Archive conflict review remains separate immutable staging of every source
position under the merged policy. Exact duplicates may be identified, differing
versions never silently overwritten. A current dump + old ZIP is not one common
MVCC snapshot. A preservation-signature generation is not a DB cut. Preserve
unresolvable ambiguity and do not invent missing versions or 2025/2026 evidence.

## Single conductor / full open-items ledger

Reused, not duplicated: `project_conductor.py` and `programme_agent_team.py` already
define a pure front door and independent builder/reviewer/Windows/Linux gates.
They are source contracts, NOT a deployed standing LLM team, daemon or permission
sandbox. This handoff is the current recovery front-door memory. Runtime agents
may only monitor/report; no trading, training, secret acquisition or self-approval.
An automatic conductor/executor is deliberately deferred until the deterministic
backup/custody/restore gates have real evidence. No paid SDK or account is needed.

Bundled now: live opaque export, namespace drill, inactive synthetic native
acceptance, exact-base packaging and status continuity. Deliberately deferred:
destination-bound A/B/backup collector and authenticated custody; receipt/Drive-ID
authentication; fresh cluster capacity + Docker VM free-space proof; private
source-compatible same-cut typed restore, cross-batch run, cold readers/writers,
retention; D: measurement until reconnect; actual production failure-alert
delivery; host PostgreSQL Automatic/non-loopback decision; Windows Time stop and
dispersion; missing14Oct audit report (not proof observations are absent);
legacy audit exit2/shared-root writes; option capture off; identification/consumer
of sessions JSON ending1Oct; duplicate ciphertext/Downloads cleanup; holiday-aware
skip for collector175/176; full local suite/unclassified/WinError5 hard-link
failures; legacy preservation-helper Linux-targeted type annotations (below);
ML/backtesting licences, labels and frozen prospective paper study.
None is silently cleared. Wednesday21Oct manual capture and all its installed
files/state/tasks are unchanged and have no dependency on this package.

## Verification, research and technology radar

Builder native Docker access: read-only version query denied by managed sandbox;
no elevation, ACL change, service startup or workaround attempted. Native restore,
real Windows directory locks, TLS/password prompt and private export remain
UNVERIFIED until the explicit owner gates. New source tests use synthetic pipes,
mocked kernels and files; this is not native platform acceptance. POSIX syntax
test intentionally runs in Linux CI, not MSYS under Windows. Existing symlink
privilege skip remains explicit. Full local suite has NOT been newly claimed.
Clean-public-clone builder Windows focused run: **532 passed, 2 skipped**. Skips:
POSIX shell syntax is a Linux-CI gate rather than a Windows MSYS invocation;
the existing symlink test lacks native privilege and no permission was changed.
Pyflakes: six source/test files clean. Strict mypy: three source modules passed.
Exact-base staged checker: failures empty; whitespace check clean. Independent
checker found and verified fixes for startup cleanup, directory-chain protection,
client-certificate discovery and native-prompt block separation; independently
ran44 source tests (one Linux-syntax skip) and10 runtime-source pin tests. These
are source/synthetic checks, NOT native/private acceptance or final-SHA hosted CI.
An additional `mypy --strict --platform linux` check is **NOT GREEN**: seven
errors remain in the unchanged pinned `archive_preservation_inventory.py`
Windows-FFI annotations (WinDLL, msvcrt descriptor APIs, O_BINARY/Any return).
New modules report no errors under that target, but the dependency-wide result
is still a failure, not a Linux typing pass. No suppression/import skipping was
added and the A/B helper's bytes were not changed. A separate reviewed portability
repair must reconcile its historical pins before changing that helper. This does
not establish native Linux or Windows acceptance; those gates remain required.

Adopted: native PostgreSQL tools already installed, Ed25519 continuity already
built, bounded binary pipes and same-handle destination identity. Adapted: official
hidden-console prompting instead of password URI/env/passfile. Deferred: restic/
Borg (extra repositories/keys, not a substitute for current recovery proof), full
local Supabase stack until matching extensions are reviewed, and automated agent
executors. Rejected: paid backups/services, host5433 restore, silent RLS/schema
exclusions, plaintext secret files and global environment credentials. No new
install is required. Additional native tooling cannot manufacture trading edge.

Official sources consulted21Oct2026:
- [Supabase backups](https://supabase.com/docs/guides/platform/backups) and
  [CLI migration/backup](https://supabase.com/docs/guides/platform/migrating-within-supabase/backup-restore):
  free exports/off-site copies, session pooler; do NOT follow the generic password
  reset example here because a working owner credential already exists.
- [pg_dump17](https://www.postgresql.org/docs/17/app-pgdump.html) and
  [pg_dumpall17](https://www.postgresql.org/docs/17/app-pg-dumpall.html): single-DB
  consistency, global scope distinction, roles without passwords, lock timeout.
- [Native prompt source](https://github.com/postgres/postgres/blob/REL_17_STABLE/src/common/sprompt.c):
  Windows console handles and no-echo prompting; unsupported fallbacks are blocked.
- [libpq environment](https://www.postgresql.org/docs/17/libpq-envars.html) and
  [client certificate modes](https://www.postgresql.org/docs/17/libpq-connect.html#LIBPQ-CONNECT-SSLCERTMODE):
  avoid ambient credentials; server TLS verification and client certs are separate.
- [pg_restore17](https://www.postgresql.org/docs/17/app-pgrestore.html): source SQL
  can execute code even with partial restores; no blind private restore.
- Official Docker registry manifest resolved21Oct: postgres17.11-bookworm index
  sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826;
  LinuxAMD64 image digest is pinned in source/workflow, never a mutable latest tag.
- [Supabase changelog](https://supabase.com/changelog) checked for current context.

Highest-leverage next step after first protected live export: the native
destination-bound collector that freezes A/B plus the new encrypted backup
generation into separately anchored evidence, then a source-compatible isolated
restore rehearsal—not another compaction or an autonomous trading/model loop.
