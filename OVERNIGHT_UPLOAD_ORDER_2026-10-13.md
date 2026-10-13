# Overnight upload order — 13 October 2026

All four groups are inactive additions. Uploading reviewed files to main is safe during Tuesday’s capture **only if the installed capture folder, tasks and state stay unchanged, release stays held, and neither new workflow is enabled**. Do not install these new tools into Tuesday’s capture. No settings change, SQL execution, data deletion or secret update is part of upload.

## Clean-clone routine, once per group

Final offline verification: 538 focused tests; 3876 full-suite tests, 4 existing
skips and 2 subtests; strict types on 56 new files; whole-root lint; import-all and
real app boot pass. Native local acceptance: 27 cases, of which 4 are newly added.
Group focused counts: capture46 → operations98 → storage285 → research109.
The standalone programme ledger contains the exact fingerprint and limitations.

1. Start from a clean clone of the newest green merged main, after the previous group merged. Save its full HEAD as `$overnightBase`. Create your review branch using your usual owner procedure.
2. Copy ONLY the files in that group from the source paths below to the listed clone destinations. Create nested destination folders as needed. Never copy the whole workspace, `.streamlit`, private data or `client_secret.json`.
3. Stage exactly the listed paths using your usual Git interface. Run the package checker **after staging**: it rejects staged/worktree disagreement, wrong prerequisites and extra files. Record the base SHA and redacted checker result.
4. Run the focused line in the clone’s reviewed Python environment; then let the PR run the full quality, resilience and CodeQL checks. Re-run the checker after any edit/re-stage. Do not merge a red check. Check the post-merge exact main SHA before starting the next group.
5. Manifests normalize CRLF to LF. Their self-entry intentionally has no self-hash; the fixed wrapper lists all paths independently. They are reviewed integrity controls, not signatures. A prerequisite mismatch blocks: do not remove the pin to make it pass.

The source root is `C:/Users/banga/Desktop/kiran_share_market`. Destination paths below are relative to your clean clone. No old staged G/I replacement or special E installation applies: these are new `overnight_*` files only. Existing Uploads 8–11 stay unchanged.

## Group 1: capture (12 files)

- `C:/Users/banga/Desktop/kiran_share_market/overnight_capture_audit.py` → `overnight_capture_audit.py`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_capture_calendar.py` → `overnight_capture_calendar.py`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_capture_planning.py` → `overnight_capture_planning.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_capture_audit.py` → `tests/test_overnight_capture_audit.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_capture_planning.py` → `tests/test_overnight_capture_planning.py`
- `C:/Users/banga/Desktop/kiran_share_market/OVERNIGHT_CAPTURE_2026-10-13.md` → `OVERNIGHT_CAPTURE_2026-10-13.md`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_capture_upload_check.py` → `overnight_capture_upload_check.py`
- `C:/Users/banga/Desktop/kiran_share_market/OVERNIGHT_CAPTURE_UPLOAD_2026-10-13.json` → `OVERNIGHT_CAPTURE_UPLOAD_2026-10-13.json`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_upload_check.py` → `overnight_upload_check.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_upload_check.py` → `tests/test_overnight_upload_check.py`
- `C:/Users/banga/Desktop/kiran_share_market/OVERNIGHT_PROGRAMME_2026-10-13.md` → `OVERNIGHT_PROGRAMME_2026-10-13.md`
- `C:/Users/banga/Desktop/kiran_share_market/OVERNIGHT_UPLOAD_ORDER_2026-10-13.md` → `OVERNIGHT_UPLOAD_ORDER_2026-10-13.md`

Package check (after staging):

```powershell
python overnight_capture_upload_check.py --base $overnightBase
```

Focused check:

```powershell
python -m pytest -q tests/test_overnight_capture_audit.py tests/test_overnight_capture_planning.py tests/test_overnight_upload_check.py
```

## Group 2: operations (11 files)

- `C:/Users/banga/Desktop/kiran_share_market/overnight_operations_alerts.py` → `overnight_operations_alerts.py`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_operations_inputs.py` → `overnight_operations_inputs.py`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_operations_watch.py` → `overnight_operations_watch.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_operations_alerts.py` → `tests/test_overnight_operations_alerts.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_operations_inputs.py` → `tests/test_overnight_operations_inputs.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_operations_watch.py` → `tests/test_overnight_operations_watch.py`
- `C:/Users/banga/Desktop/kiran_share_market/OVERNIGHT_OPERATIONS_2026-10-13.md` → `OVERNIGHT_OPERATIONS_2026-10-13.md`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_operations_upload_check.py` → `overnight_operations_upload_check.py`
- `C:/Users/banga/Desktop/kiran_share_market/OVERNIGHT_OPERATIONS_UPLOAD_2026-10-13.json` → `OVERNIGHT_OPERATIONS_UPLOAD_2026-10-13.json`
- `C:/Users/banga/Desktop/kiran_share_market/overnight_history_admission.py` → `overnight_history_admission.py`
- `C:/Users/banga/Desktop/kiran_share_market/tests/test_overnight_history_admission.py` → `tests/test_overnight_history_admission.py`

Package check (after staging):

```powershell
python overnight_operations_upload_check.py --base $overnightBase
```

Focused check:

```powershell
python -m pytest -q tests/test_overnight_operations_alerts.py tests/test_overnight_operations_inputs.py tests/test_overnight_operations_watch.py tests/test_overnight_history_admission.py
```

## Group 3: storage (28 files)

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

Package check (after staging):

```powershell
python overnight_storage_upload_check.py --base $overnightBase
```

Focused check:

```powershell
python -m pytest -q tests/test_overnight_storage_cold_methods.py tests/test_overnight_storage_contracts.py tests/test_overnight_storage_custody_binding.py tests/test_overnight_storage_journal.py tests/test_overnight_storage_materialization.py tests/test_overnight_storage_native_acceptance.py tests/test_overnight_storage_repository_routes.py tests/test_overnight_storage_sources.py tests/test_overnight_storage_staged_factories.py tests/test_overnight_storage_switching.py tests/test_overnight_storage_universe.py
```

## Group 4: research (19 files)

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

Package check (after staging):

```powershell
python overnight_research_upload_check.py --base $overnightBase
```

Focused check:

```powershell
python -m pytest -q tests/test_overnight_research_dataset.py tests/test_overnight_research_evidence.py tests/test_overnight_research_execution.py tests/test_overnight_research_ml.py tests/test_overnight_research_paper.py tests/test_overnight_research_runner.py tests/test_overnight_research_trials.py
```

## Minimum owner steps; separate from upload

- Tuesday: use only the already installed reviewed version-aware routine. Preserve the original raw-only task export/folder and all Monday evidence. New planning tools are advisory; cleanup means disable obsolete recurrence after proof, **not delete history**. Check supervised poll, later automatic receipt and 15:40 audit; missing custody flags remain missing.
- Save current and available historical signing keys in an encrypted password-manager note outside the repository. Do not paste them into chat. Perform the existing harmless 7-Zip AES-256 external-disk rehearsal, then the reviewed independent-copy/readback/restore procedure. Hashes alone do not establish encryption or independent custody.
- Check Drive’s actual account-wide quota (including Gmail/Photos/trash), available capacity and retention obligations. Unlimited-looking or absent quota is UNKNOWN, not infinite.
- Keep alerts off until you choose an independent owner-controlled sender, privately provide credentials, and verify one delivery plus a dead-man failure. Provider acceptance is not owner acknowledgement.
- Optional after Group 3: manually run **Inactive overnight staged storage acceptance**, tick its disposable confirmation, and verify the exact merged SHA. This touches only synthetic container fixtures, never Supabase. A failure is diagnostic, not permission to retry or apply fixture SQL to Supabase.
- Group 4’s GitHub-hosted workflow remains off unless the explicit variable is enabled; do **not** enable it as part of this upload. Its manual command is synthetic-only. A real-data scheduled pipeline is not commissioned.
- No new equity fingerprint expectation is required by these inactive additions. Confirm the public-tree fingerprint in the verification ledger before any eventual release. Never copy a runtime hash into expectations as a substitute for reviewed release identity.

## What remains before permanent storage commissioning

AUTOMATION_PROGRESS.md has a local-only continuity pointer. **Do not upload it**:
the historical packages authenticate its old bytes. The new standalone programme
ledger and this ordered runbook are uploaded instead; historical manifests stay
immutable. A future reviewed successor can explicitly migrate that continuity
contract, rather than invalidating old recovery-package verification.

Production factory/cold-reader migration is still partial engineering. Synthetic routes do not enforce every live writer. Finish dynamic/multi-transaction methods, measured allocation bounds, same-generation full-reader parity, source-specific archive locks and exact retained lookup, and native acceptance before enabling retention. Real custody, restore and independent alerts are owner commissioning steps. No code in these packages grants deletion authority.

Analysis/ML has executable synthetic plumbing, not admitted real return labels or a proved edge. Licensing, executable derivative quotes, dated contract/cost/margin histories and enough independent prospective sessions are required. Historical 2025/2026 remain sealed; no automatic re-tuning.

