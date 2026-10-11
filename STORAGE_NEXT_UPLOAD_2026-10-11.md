# One consolidated upload: inactive storage acceptance foundation

Uploads 1 and 2 from Oct 8 are reported merged/green by the owner. Do NOT upload
those old groups again. This is ONE new PR from the owner's current clean main.
No staged source exceptions: all source paths below map to the SAME relative
destination. Root means C:\Users\banga\Desktop\kiran_share_market on the source
side and the clean clone's repository root on the destination side.

| Complete source -> destination | Purpose |
| --- | --- |
| local_state_recovery.py -> local_state_recovery.py | Opt-in eager sixth-table capture; original five-table behavior unchanged |
| terminal_intent_snapshot.py -> terminal_intent_snapshot.py | Same-cut bounded terminal witness and exact historical proof verification |
| storage_native_conformance.py -> storage_native_conformance.py | Preview-first disposable native guard runner |
| reviewed_upload_check.py -> reviewed_upload_check.py | Explicit new manifest/group, narrowly allowlisted workflow path |
| tests/test_terminal_intent_snapshot.py -> tests/test_terminal_intent_snapshot.py | Same-cut, restore, bounds, corruption, old ACK and callback regressions |
| tests/test_storage_native_conformance.py -> tests/test_storage_native_conformance.py | Offline sandbox/confirmation/redaction/control-flow tests |
| tests/test_reviewed_upload_check.py -> tests/test_reviewed_upload_check.py | Old groups preserved; new exact-manifest tests |
| sql/storage_native_fixture_disposable_only.sql -> sql/storage_native_fixture_disposable_only.sql | Disposable-only restricted RLS fixture; NOT a migration |
| .github/workflows/storage-native-conformance.yml -> .github/workflows/storage-native-conformance.yml | Manual-only isolated native service; no project secrets |
| RUNTIME_PASSWORD_ROTATION_OWNER.md -> RUNTIME_PASSWORD_ROTATION_OWNER.md | Quiesce/rotate/update/revoke/test/resume owner procedure |
| STORAGE_FOUNDATION_2026-10-11.md -> STORAGE_FOUNDATION_2026-10-11.md | Permanent design, engineering gates and owner native/custody steps |
| STORAGE_NEXT_UPLOAD_2026-10-11.md -> STORAGE_NEXT_UPLOAD_2026-10-11.md | This complete upload list |
| STORAGE_FOUNDATION_UPLOAD_2026-10-11.json -> STORAGE_FOUNDATION_UPLOAD_2026-10-11.json | Normalized source hashes and unchanged dependency prerequisites |
| AUTOMATION_PROGRESS.md -> AUTOMATION_PROGRESS.md | Current owner state, completed step and remaining engineering |

14 paths total, including the control manifest. No entire-folder upload. Do not
copy root production_repository.py, equity_runtime_health.py or package_release.py
from the working folder: unrelated held drafts remain there. This package does not
change their public counterparts. No client_secret.json, secrets.toml, data files,
receipts, caches or private archive material are in this upload.

Final checks: focused 246 passed; credential-free reviewed public candidate full
suite 2913 passed, 4 unchanged skips, 2 subtests passed (332.94s), including app
boot. Seven changed Python paths strict typing PASS; full candidate lint PASS.
New imports/zero-network preview and source/dependency hashes PASS. Native service
execution NOT performed; owner exact-main/PR CI remains required.

## Clean-clone rehearsal

In a clean clone of current main, BEFORE copying these files:

```powershell
$storageUploadBase = git rev-parse HEAD
git status --short
```

Status must be empty. Create your PR branch using the usual owner routine, copy
only the 14 complete files to their mapped locations, then run this ONE package
check line from the clean clone root:

```powershell
python reviewed_upload_check.py --group foundation --manifest STORAGE_FOUNDATION_UPLOAD_2026-10-11.json --base $storageUploadBase
```

It must return UPLOAD_FILES_VERIFIED_REQUIRES_TESTS_AND_CI, blockers [], exit 0.
It checks exact current HEAD, named files/hashes, no extra changed/untracked paths
and unchanged foundation dependencies. Do not alter the baseline or manifest to
silence a mismatch. The manifest is reviewed control metadata, not signed release
authority. It cannot hash itself; source/dependency files are hashed.

ONE focused-test line (offline; no native service/credential required):

```powershell
python -m pytest -q tests/test_terminal_intent_snapshot.py tests/test_local_state_recovery.py tests/test_finalization_intents.py tests/test_storage_native_conformance.py tests/test_storage_write_guard.py tests/test_reviewed_upload_check.py
```

New strict type/lint lines:

```powershell
python -m mypy --strict --follow-imports=silent terminal_intent_snapshot.py storage_native_conformance.py reviewed_upload_check.py tests/test_terminal_intent_snapshot.py tests/test_storage_native_conformance.py tests/test_reviewed_upload_check.py
python -m pyflakes local_state_recovery.py terminal_intent_snapshot.py storage_native_conformance.py reviewed_upload_check.py tests/test_terminal_intent_snapshot.py tests/test_storage_native_conformance.py tests/test_reviewed_upload_check.py
```

Full quality/resilience/CodeQL and app boot checks on the EXACT PR/main commit
remain required. No production workflow gates are weakened; no tests removed.
Do not treat the manual native workflow as green just because it exists/skips.

## After merge

1. Confirm post-merge quality, resilience and CodeQL on the exact merge SHA.
2. Owner may run the manual disposable native workflow as described in the
   foundation runbook. This is not a collector dispatch or Supabase migration.
3. Password rotation can happen independently before merge; prioritize it.
4. Complete the private key note/dummy encrypted external-disk rehearsal.
5. Keep capture installation, release hold, Streamlit expectations and other held
   collector modes unchanged. No new EXPECTED_EQUITY_CODE_SHA256 is required by
   this inactive package: no file in the current decision fingerprint changes.
6. Next engineering: signed six-table bundle custody, immutable remote receipt
   writer/native ledger races, live factory/all-writer guard integration, universe
   shadow SQL/readers, source retention and independently delivered alerts.

There is NO apply-migration, archive-delete, retention activation, dashboard
promotion or new F&O-ingestion instruction in this package.
