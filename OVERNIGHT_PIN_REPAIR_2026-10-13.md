# Overnight upload pin repair — 13 October 2026

This document supersedes the old upload-order instructions for Groups 3 and 4 only. Groups 1 and 2 are already merged; do not upload them again. Nothing is commissioned, deleted, enabled or sent by this repair. The installed capture, release hold and expectations stay untouched.

## What failed and why

The storage manifest was generated from an isolated earlier rehearsal tree, not exact merged main `113423758598f459b8a94cf5ad4e410abb04d116`. Its two stale dependencies have exactly one extra EOF newline compared with main. LF normalization intentionally does not ignore blank lines. Independent AST comparison confirms identical executable syntax, including constants and docstrings. The held workspace versions are different and must NOT be uploaded.

The original storage audit: 120 prerequisites, 118 matched, two mismatched. The original research audit: all 112 prerequisites matched exact current main. The research helper pin will change intentionally because the shared checker is repaired in Group 3. No pin is removed to admit different code: the checker moves from prerequisite to a modified upload file, and every remaining prerequisite stays byte-pinned.

Reviewed main dependency pins:

- `equity_research_observations.py`: `a8414ecb775dc3fd031efb6f817058ef4373fba46d1b613f2c354a06fa4262fa`
- `recovery_drill.py`: `76accb2d9f7f1f0b836463b1299dd37f65cfaa0df924bc07dda7abf4b25fe528`

The refreshed storage checker tests both dependencies' reviewed executable ASTs in addition to exact manifest hashes. Source inventory parses recovery code without executing it; real repository route compilation remains tied to supplied source hashes. No legacy recovery/research runtime file changes are required.

## Upload order and clean-clone steps

1. Start a clean clone on exact green main `113423758598f459b8a94cf5ad4e410abb04d116`. Save `$overnightBase = git rev-parse HEAD` BEFORE copying. Use a new review branch.
2. Copy Group 3 below, stage its exact paths, and run its checker and tests. These are the original 28 storage files plus three checker/diagnostic files (31 paths); several original files have been refreshed, so copy ALL 31, not just the changed manifest.
3. Review the PR, require all checks on the exact commit, merge. Do not change variables, run hosted SQL or enable either workflow.
4. Start another clean clone on the newest green merged main, save a NEW `$overnightBase`, and copy Group 4 (19 paths). Stage, check, test, review and merge. Its refreshed manifest pins the shared checker from Group 3.
5. A BLOCKED result is a stop, not permission to edit a pin. It now reports an allowlisted rule and public relative path plus expected/actual SHA256 for EVERY hash mismatch. Unknown errors remain redacted; no raw exception text, private paths or Git stderr are printed.

Run checks and tests IN THE CLEAN CLONE, never against the mixed local source folder. Do not copy `equity_research_observations.py`, `recovery_drill.py`, the local-only `AUTOMATION_PROGRESS.md`, credentials or any file absent from the lists below.

For Windows offline full-suite/boot rehearsals, preserve repository bytes from the start: create a new clone with `git -c core.autocrlf=false clone https://github.com/kirandoddi1995-ux/Trading-Dashboard.git <new-upload-clone>`, then set `git config core.autocrlf false` inside it before working. Do not rewrite the approved policy or its sidecar to accommodate line-ending conversion. The package checker still deliberately supports LF-normalized source hashing; it does not ignore extra blank lines. CI uses repository LF bytes.

If other main changes land, recheck against that exact SHA. An expected dependency change requires another reviewed compatibility audit, not a hand-edited pin. Files already copied into an unmerged upload branch can be replaced from this refreshed list; do not delete or reset the owner's work.

## Group 3 — storage (31 paths)

- `C:/Users/banga/Desktop/kiran_share_market/overnight_upload_check.py` → `overnight_upload_check.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_upload_check.py` → `tests/test_overnight_upload_check.py`
- `C:/Users/banga/Desktop/kiran_share_market/OVERNIGHT_PIN_REPAIR_2026-10-13.md` → `OVERNIGHT_PIN_REPAIR_2026-10-13.md`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_storage_cold_methods.py` → `overnight_storage_cold_methods.py`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_storage_contracts.py` → `overnight_storage_contracts.py`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_storage_factory_adapter.py` → `overnight_storage_factory_adapter.py`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_storage_harness.py` → `overnight_storage_harness.py`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_storage_journal.py` → `overnight_storage_journal.py`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_storage_materialization.py` → `overnight_storage_materialization.py`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_storage_native_acceptance.py` → `overnight_storage_native_acceptance.py`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_storage_repository_routes.py` → `overnight_storage_repository_routes.py`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_storage_sources.py` → `overnight_storage_sources.py`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_storage_staged_factories.py` → `overnight_storage_staged_factories.py`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_storage_switching.py` → `overnight_storage_switching.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_storage_cold_methods.py` → `tests/test_overnight_storage_cold_methods.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_storage_contracts.py` → `tests/test_overnight_storage_contracts.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_storage_custody_binding.py` → `tests/test_overnight_storage_custody_binding.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_storage_journal.py` → `tests/test_overnight_storage_journal.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_storage_materialization.py` → `tests/test_overnight_storage_materialization.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_storage_native_acceptance.py` → `tests/test_overnight_storage_native_acceptance.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_storage_repository_routes.py` → `tests/test_overnight_storage_repository_routes.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_storage_sources.py` → `tests/test_overnight_storage_sources.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_storage_staged_factories.py` → `tests/test_overnight_storage_staged_factories.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_storage_switching.py` → `tests/test_overnight_storage_switching.py`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_storage_universe.py` → `overnight_storage_universe.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_storage_universe.py` → `tests/test_overnight_storage_universe.py`
- `C:/Users/banga/Desktop/kiran_share_market/OVERNIGHT_STORAGE_2026-10-13.md` → `OVERNIGHT_STORAGE_2026-10-13.md`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_storage_upload_check.py` → `overnight_storage_upload_check.py`
- `C:/Users/banga/Desktop/kiran_share_market/OVERNIGHT_STORAGE_UPLOAD_2026-10-13.json` → `OVERNIGHT_STORAGE_UPLOAD_2026-10-13.json`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_storage_native_fixture.sql` → `overnight_storage_native_fixture.sql`
- `C:/Users/banga/Desktop/kiran_share_market/.github/workflows/overnight-storage-native.yml` → `.github/workflows/overnight-storage-native.yml`

Checker after staging:

```powershell
python overnight_storage_upload_check.py --base $overnightBase
```

Focused offline tests:

```powershell
python -m pytest -q tests/test_overnight_upload_check.py tests/test_overnight_storage_cold_methods.py tests/test_overnight_storage_contracts.py tests/test_overnight_storage_custody_binding.py tests/test_overnight_storage_journal.py tests/test_overnight_storage_materialization.py tests/test_overnight_storage_native_acceptance.py tests/test_overnight_storage_repository_routes.py tests/test_overnight_storage_sources.py tests/test_overnight_storage_staged_factories.py tests/test_overnight_storage_switching.py tests/test_overnight_storage_universe.py
```

## Group 4 — research (19 paths)

- `C:/Users/banga/Desktop/kiran_share_market/overnight_research_dataset.py` → `overnight_research_dataset.py`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_research_evidence.py` → `overnight_research_evidence.py`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_research_execution.py` → `overnight_research_execution.py`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_research_ml.py` → `overnight_research_ml.py`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_research_paper.py` → `overnight_research_paper.py`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_research_runner.py` → `overnight_research_runner.py`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_research_trials.py` → `overnight_research_trials.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_research_dataset.py` → `tests/test_overnight_research_dataset.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_research_evidence.py` → `tests/test_overnight_research_evidence.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_research_execution.py` → `tests/test_overnight_research_execution.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_research_ml.py` → `tests/test_overnight_research_ml.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_research_paper.py` → `tests/test_overnight_research_paper.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_research_runner.py` → `tests/test_overnight_research_runner.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_research_trials.py` → `tests/test_overnight_research_trials.py`
- `C:/Users/banga/Desktop/kiran_share_market/OVERNIGHT_RESEARCH_2026-10-13.md` → `OVERNIGHT_RESEARCH_2026-10-13.md`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_research_upload_check.py` → `overnight_research_upload_check.py`
- `C:/Users/banga/Desktop/kiran_share_market/OVERNIGHT_RESEARCH_UPLOAD_2026-10-13.json` → `OVERNIGHT_RESEARCH_UPLOAD_2026-10-13.json`
- `C:/Users/banga/Desktop/kiran_share_market/requirements-overnight-research.txt` → `requirements-overnight-research.txt`
- `C:/Users/banga/Desktop/kiran_share_market/.github/workflows/overnight-research-offline.yml` → `.github/workflows/overnight-research-offline.yml`

Checker after staging:

```powershell
python overnight_research_upload_check.py --base $overnightBase
```

Focused offline tests:

```powershell
python -m pytest -q tests/test_overnight_research_dataset.py tests/test_overnight_research_evidence.py tests/test_overnight_research_execution.py tests/test_overnight_research_ml.py tests/test_overnight_research_paper.py tests/test_overnight_research_runner.py tests/test_overnight_research_trials.py
```

## Verification and owner limits

Verification against exact public main dependencies, not the held workspace drafts:

- Group 3 alone: 318 focused tests passed (31 checker, 287 storage/compatibility).
- Group 4: 109 focused tests passed.
- Full regression: 3,890 passed, four existing skips, two subtests passed, 1,778.44 seconds. The final malformed-JSON diagnostic parameter was added after this run collected its tests; the finalized checker suite independently passed all 31 cases. Require the PR quality gate to run the complete final tree before merging.
- Strict typing: all 41 package Python files and the existing 19-file automation profile passed; complete public root/tests lint passed.
- Network-blocked import-all: 22 package modules passed. Real app import and both offline Streamlit boot modes passed (three checks).
- Both exact staged upload checks passed in order (Group 4 rehearsed after an offline-only Group 3 commit). All 119 storage and 112 research prerequisites and all package file hashes passed. Original Group 4's 112 pins also matched pre-storage main; only the repaired checker prerequisite changes in its refreshed manifest.
- Final self-review checked recovered old pins, EOF-only differences, unchanged executable ASTs, exact-byte pins, fixed path lists, staging/root guards, error redaction and upload order. No runtime drafts or safety-gate changes were introduced.

The equity release fingerprint is unchanged: `03ad7baa68ebaad1f64b1cd3c356455e1c18cb8f23f027652de303b64b4f8478`. Do not change Streamlit expectations. No hosted writes, credentials, installed capture, holdout data, real alerts or archive deletion were involved. Both new workflows remain inactive, global writer enforcement and archive/deletion commissioning remain false. These uploads can be reviewed during capture because installed capture is a separate untouched folder; copying into that folder is NOT part of these steps.

