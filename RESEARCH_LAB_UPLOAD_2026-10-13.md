# One reviewed upload: read-only application Research Lab

Baseline: `0223f0033672e072e522017f2cdfe7cab0478e18` (merged Group 4).
One coherent PR; no installation into the capture folder and no new workflow.
Safe to upload during Tuesday capture because its installed code/state/tasks are
separate and unchanged. The release hold and expectations stay unchanged.

## Exact source → destination manifest

All sources are under `C:\Users\banga\Desktop\kiran_share_market\`.
Destinations below are relative to the clean public upload clone's root. Only
these seventeen files belong to this package; do not upload the workspace or the
local-only AUTOMATION_PROGRESS.md.

- `app.py` → `app.py` (modified)
- `reviewed_stage\research_lab\equity_runtime_health.py` → `equity_runtime_health.py` (modified released source; do NOT copy the held root draft)
- `reviewed_stage\research_lab\package_release.py` → `package_release.py` (modified released packager; do NOT copy the held root draft)
- `research_lab.py` → `research_lab.py`
- `research_lab_ui.py` → `research_lab_ui.py`
- `research_lab_grounding.py` → `research_lab_grounding.py`
- `research_lab_statistics.py` → `research_lab_statistics.py`
- `research_lab_upload_check.py` → `research_lab_upload_check.py`
- `tests\test_research_lab.py` → `tests/test_research_lab.py`
- `tests\test_research_lab_grounding.py` → `tests/test_research_lab_grounding.py`
- `tests\test_research_lab_statistics.py` → `tests/test_research_lab_statistics.py`
- `tests\test_research_lab_upload_check.py` → `tests/test_research_lab_upload_check.py`
- `tests\test_streamlit_boot.py` → `tests/test_streamlit_boot.py` (modified)
- `RESEARCH_LAB_DESIGN_2026-10-13.md` → `RESEARCH_LAB_DESIGN_2026-10-13.md`
- `PROGRAMME_RECONCILIATION_2026-10-13.md` → `PROGRAMME_RECONCILIATION_2026-10-13.md`
- `RESEARCH_LAB_UPLOAD_2026-10-13.md` → `RESEARCH_LAB_UPLOAD_2026-10-13.md`
- `RESEARCH_LAB_UPLOAD_2026-10-13.json` → `RESEARCH_LAB_UPLOAD_2026-10-13.json`

## Clean-clone check and focused test lines

Use the existing clean-clone PR routine, with `core.autocrlf=false` **before
checkout** so approved policy bytes stay LF. Start from exact newest green main;
if main advanced, check pins rather than assuming compatibility. Copy the seventeen
listed files preserving folders, stage them, then:

```powershell
python research_lab_upload_check.py --base <full-current-green-main-SHA>
python -m pytest -q tests/test_research_lab.py tests/test_research_lab_grounding.py tests/test_research_lab_statistics.py tests/test_research_lab_upload_check.py tests/test_streamlit_boot.py tests/test_historical_repository_bridge.py tests/test_release_packaging.py
python -m mypy --strict --explicit-package-bases --follow-imports=silent research_lab.py research_lab_ui.py research_lab_grounding.py research_lab_statistics.py research_lab_upload_check.py tests/test_research_lab.py tests/test_research_lab_grounding.py tests/test_research_lab_statistics.py tests/test_research_lab_upload_check.py
```

The checker requires exact HEAD/index/worktree and all public prerequisite hashes;
blocked output identifies path and expected/actual hash without raw error text.
It does not weaken any historical control manifest. Run full CI on the exact PR
and merge SHA; do not enable either existing research/storage workflow.

## Verification and fingerprint

Corrected focused suite: **112 passed**, including authenticated AppTest navigation
and the actual synthetic button, historical-reader bridge and extracted artifact.
Strict typing passes on nine new files and the existing nineteen-file profile.
All candidate root/test Python lint passes; five new root modules import with
network access denied. Exact staged seventeen-file checker passes all 128 public
prerequisite pins, and the Git whitespace check is clean.

Self-review fixed explicit recipe/diagnostic source dependencies in both the
fingerprint and release packager. The first full run exposed these two artifact
failures (3960 passed, 4 existing skips, 2 subtests); it is NOT counted as a pass.
Separate sandbox temporary-directory permission failures were isolated by using
a dedicated disposable test directory; no application gate was relaxed.
Final corrected full suite: **3962 passed, 4 unchanged skips, 2 subtests passed**
in 823.13 seconds. No test-count drop: 71 added cases over the 3891-case public
baseline. The same corrected source tree passed all 112 focused cases.

Reviewed candidate fingerprint:
`d472b7767c102d98058fa4e23f9fdf6c16f0d2489a854bf45f3a6e6da975f71c`.
No expectation value is changed by any tool or script. A future separately
commissioned app release must use that exact reviewed release's fingerprint,
never infer approval from the runtime display. No new native SQL proof is claimed:
this package changes no SQL or writer implementation.

## Minimum owner steps, in order

1. Continue today's installed capture unchanged. Upload this one seventeen-file PR
   using the above routine; verify all exact-commit CI checks before merging.
2. Leave release promotion, expectations, workflows and hosted resources held.
   Research Lab becomes visible only on a later explicitly commissioned release.
3. No new plugin, API key or account is needed. Existing GitHub/Drive/Supabase
   connections suffice. Do not connect a paid LLM under the zero-cost constraint.
4. Next operational prerequisites remain private encrypted key custody, independent
   encrypted-disk restore and Drive quota/retention review; use already reviewed
   custody runbooks, including OWNER_KEYS_AND_BACKUP_RUNBOOK.md. Share only safe
   status/counts, never secrets or backup contents. The reported exposed runtime
   password also needs the separate planned owner maintenance sequence in
   RUNTIME_PASSWORD_ROTATION_OWNER.md before admitting new storage writers;
   do not reset the postgres password or ledger signing keys for this purpose.
5. Before real research, resolve source rights and contract/quote/outcome admission,
   freeze the session-level study, and gather enough prospective evidence. Local
   LLM hardware/model choice can wait; no research or trade gate depends on it.
