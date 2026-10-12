# Inactive recovery join — one complete PR group

This successor package joins the existing bounded SQLite exporter to the signed
six-table binding. It does not back up installed capture, run an application
restore, enable cold readers, alter a database, activate SQL or prove independent
cold custody. Five-table contracts remain supported unchanged. Six-table contracts
must contain exactly primary_state/sqlite-image-v1 and
six_table_witness/derived-state-v1 with the same source ID. Other files/sources
need their own consistent adapter and are rejected, not silently omitted.

## What changed

The revised group also includes recovery_materialization.py and its synthetic
tests. This inactive library authenticates the independently supplied checkpoint
before copying a six-table generation into a NEW absolute destination, then
remeasures source and destination. It never overwrites installed state, advances
custody, acknowledges requests, retries sends, or removes partial copies.
Its remote-contract review requires injected original-request/fence lookups;
unknown COMMIT stays pending even when remote presence is proved. Lookup
authentication, independent-device encryption and full application recovery
remain unverified. Caller-controlled ACLs and mutation exclusion are required.

The distinction follows the [SQLite backup API](https://www.sqlite.org/backup.html):
a completed database snapshot is not proof that an external file copy survives
a crash. Separately, [Supabase's backup documentation](https://supabase.com/docs/guides/platform/backups)
notes that database backups exclude Storage object bytes and custom-role
passwords. Neither the SQLite rehearsal nor a SQL dump alone proves whole-app
recovery. No actual private backup, password or Storage object was inspected here.

The same inactive-foundation group includes research_claim_projection.py. It
addresses a confirmed default-reader hazard without changing any live factory:
unknown/ambiguous outcomes are not losses, raw forward return is not benchmark
excess, features cannot overwrite reserved labels/provenance, and payload claims
cannot grant training or production eligibility. Even TARGET/STOP remain candidate
labels only until original ledger and referenced market evidence are verified.
This is an integration building block, NOT a fix already deployed to the hot
reader or permission to train. R01 in the backlog remains open for actual hot/cold
adapter parity. All its tests use synthetic payloads, not development/holdout data.

The exporter pins one source read transaction, uses SQLite backup, closes the
source, derives both witnesses from the completed detached image, and signs the
image plus the sixth witness in one root. It writes a NEW generation, never
overwrites an old one, and retains partial files after failure. Missing sixth
tables fail; absence is not an empty journal. WAL sources are supported without
copying live side files. Existing size/deadline limits are unchanged.

Restore verification authenticates the signed checkpoint/contract and full image
digest BEFORE opening it in SQLite. It then performs full-image integrity and
both witness checks, and remeasures the image. Extra files, sidecars, wrong keys,
swapped sixth metadata, unsupported contracts and changed images block checkpoint
advance. The caller must protect generation files from concurrent replacement;
this is not an adversarial filesystem custody implementation. Remote original
ACK proof checks and actual independent encrypted-device custody remain separate.

## Exact source → destination paths

Source prefix: C:\Users\banga\Desktop\kiran_share_market\.
Destination prefix: the ROOT of the owner's fresh clean main clone.
Every source equals its destination below; preserve tests/.

| Source relative path | Destination relative path |
|---|---|
| recovery_export.py | recovery_export.py |
| recovery_materialization.py | recovery_materialization.py |
| tests/test_recovery_materialization.py | tests/test_recovery_materialization.py |
| reviewed_upload_check.py | reviewed_upload_check.py |
| research_claim_projection.py | research_claim_projection.py |
| tests/test_research_claim_projection.py | tests/test_research_claim_projection.py |
| tests/test_recovery_six_export.py | tests/test_recovery_six_export.py |
| tests/test_storage_six_export_upload.py | tests/test_storage_six_export_upload.py |
| tests/test_storage_overnight_upload.py | tests/test_storage_overnight_upload.py |
| tests/test_storage_native_ledger_upload.py | tests/test_storage_native_ledger_upload.py |
| PROJECT_COMPLETE_BACKLOG_2026-10-12.md | PROJECT_COMPLETE_BACKLOG_2026-10-12.md |
| PROJECT_BACKLOG_INTAKE_2026-10-12.md | PROJECT_BACKLOG_INTAKE_2026-10-12.md |
| STORAGE_SIX_EXPORT_PACKAGE_2026-10-12.md | STORAGE_SIX_EXPORT_PACKAGE_2026-10-12.md |
| AUTOMATION_PROGRESS.md | AUTOMATION_PROGRESS.md |
| STORAGE_SIX_EXPORT_UPLOAD_2026-10-12.json | STORAGE_SIX_EXPORT_UPLOAD_2026-10-12.json |

Fifteen paths. This replaces the earlier thirteen-path proposal for this group;
use this version. If the earlier version is already on main, use the same updated
manifest against a fresh main clone; unchanged paths are permitted. The JSON
manifest pins hashes and prerequisite modules; old manifests
are not rewritten. Historical manifest tests verify their unchanged entries and
the exact successor bytes for superseded paths, not blanket skip changed files.
Local intake-state JSON, .offline-test-runs/, temporary clones and private files
are NOT upload paths. This group needs the previously merged six-binding and
terminal-intent snapshot prerequisites; missing/mismatched prerequisites block.

## Owner rehearsal and morning steps

1. Start a fresh branch in a clean clone of actual current main. Save its full SHA
   as $sixExportBase BEFORE copying. Do not assume an abbreviated reported SHA is
   the exact base or copy other held workspace files.
2. Copy all fifteen paths in one group, then run:

```powershell
python reviewed_upload_check.py --group six_export --manifest STORAGE_SIX_EXPORT_UPLOAD_2026-10-12.json --base $sixExportBase
python -m pytest -q tests/test_recovery_materialization.py tests/test_recovery_six_export.py tests/test_recovery_proposal.py -p no:cacheprovider --basetemp "$env:TEMP/materialization-$([guid]::NewGuid().ToString('N'))"
python -m pytest -q tests/test_research_claim_projection.py tests/test_recovery_six_export.py tests/test_recovery_export.py tests/test_recovery_six_binding.py tests/test_terminal_intent_snapshot.py tests/test_recovery_replica_audit.py tests/test_recovery_proposal.py tests/test_storage_six_export_upload.py tests/test_reviewed_upload_check.py tests/test_storage_overnight_upload.py tests/test_storage_native_ledger_upload.py -p no:cacheprovider --basetemp "$env:TEMP/six-export-$([guid]::NewGuid().ToString('N'))" --tb=short
python -m mypy --strict --follow-imports=silent research_claim_projection.py recovery_export.py reviewed_upload_check.py tests/test_research_claim_projection.py tests/test_recovery_six_export.py tests/test_storage_six_export_upload.py
python -m pyflakes research_claim_projection.py recovery_export.py reviewed_upload_check.py tests/test_research_claim_projection.py tests/test_recovery_six_export.py tests/test_storage_six_export_upload.py
python -m mypy --strict --follow-imports=silent recovery_materialization.py tests/test_recovery_materialization.py
python -m pyflakes recovery_materialization.py tests/test_recovery_materialization.py
```

3. Require full quality/resilience/CodeQL checks on this exact PR tree and merge
   SHA. No migration, workflow dispatch or hosted change belongs to this package.
4. Leave capture tasks/folder, Streamlit expectations and release hold unchanged.
   No live decision fingerprint input is intentionally changed.
5. Privately finish the historical-key/password-manager and encrypted dummy disk
   restore steps. Do not send key values. Exposed runtime credential rotation is
   still the urgent separately reviewed owner operation, not executed here.
   Use RUNTIME_PASSWORD_ROTATION_OWNER.md and OWNER_KEYS_AND_BACKUP_RUNBOOK.md,
   already in the reviewed tree. Do not improvise a postgres password reset or
   rotate the ledger key. Plan a short same-role interruption, update only confirmed
   consumers, retire old pooler sessions, prove old login fails, then admit one
   supervised scan before restoring only the previously active scan recurrence.

## Validation and review record

Continuation: materialization focused suite 49 passed; its 22 new cases also
passed separately after self-review changed the joint-identity check to use
freshly measured restored bytes, rather than declared artifact metadata.
Both new inputs pass strict typing. The revised public tree passed 3,132 tests,
four skipped, two subtests passed in 330.71s, including offline app boot/import
and disposable SQL. Combined focused checks: 221 passed in 19.06s. Strict typing
eight changed/new inputs and nineteen automation inputs, whole public root lint,
new test lint and inactive imports pass. The following results
describe the prior thirteen-path tree, not the revised fifteen-path tree.

Recovery-only public candidate: 3,061 passed, four skipped, two subtests passed.
Combined focused recovery/packaging/claim suite: 199 passed. Strict typing of all
six changed/new Python/test inputs, whole-public-tree pyflakes, and offline imports
pass. Final combined public suite: 3,110 passed, four skipped, two subtests passed
in 332.49s, including app import and offline Streamlit boot cases. Existing
automation typing also passes (19 files). After self-review, final edits are
documentation/manifest only; exact-file/focused checks are rerun. No native
fixture/workflow changed or ran.
The candidate was built from the previously verified public tree plus only this
manifest, not the dirty project or any private/installed capture directory.
It is not the owner's fresh actual-main Git rehearsal: that check remains required.

Self-review checked source snapshot/WAL consistency, digest-before-SQLite order,
both witness/replica/proposal identities, bounded reads, no checkpoint advance on
failed proofs, and no truth claims from payload flags. The categorical market_regime
field has an explicit projection rather than a numeric feature override. Missing,
boolean, non-finite and malformed values stay missing or block; they are never a
zero loss. Research integration stays pending, so no live factory changed.

Measured public candidate fingerprint remains
03ad7baa68ebaad1f64b1cd3c356455e1c18cb8f23f027652de303b64b4f8478.
These offline modules are not in RELEASE_FILES. Do not copy this measurement into
Streamlit: preserve the owner's expectations and held release exactly as requested.

## Remaining engineering, not grounds to claim commissioning

Read PROJECT_COMPLETE_BACKLOG_2026-10-12.md. Next: actual independent encrypted
replica/export integration and full application/Supabase restore, then all
writer/factory and bounded cold-reader coverage, structural retention/dedup and
independent alert delivery. New market-session evidence also needs review before
F&O risk/calendar commissioning. Neither a passing local suite nor native fixture
evidence establishes these real-source gates. Work continues; this PR is one
verified component, not a shortened replacement for the full goal.
