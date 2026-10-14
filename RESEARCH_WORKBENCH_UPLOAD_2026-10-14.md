# Upload 2 — inactive application workbench

Prerequisite: Upload 1 merged with green exact-main checks. Branch from that
newest green main, not its older source branch. Review baseline before Upload 1:
`da4a9be7d5b3e805c76cc7c677795d6eebd33a36`. The shared checker from Upload 1
is an exact pinned prerequisite; do not re-copy it or the Upload 1 control file.

Source root: `C:/Users/banga/Desktop/kiran_share_market/`.
ONLY these seventeen destinations change. Three runtime files come from the
reviewed stage, NEVER the held workspace-root versions:

| Source relative to root | Destination relative to clone |
| --- | --- |
| reviewed_stage/overnight_workbench/app.py | app.py |
| reviewed_stage/overnight_workbench/equity_runtime_health.py | equity_runtime_health.py |
| reviewed_stage/overnight_workbench/package_release.py | package_release.py |
| research_workbench.py | research_workbench.py |
| research_workbench_ui.py | research_workbench_ui.py |
| research_assistant.py | research_assistant.py |
| tests/test_research_workbench.py | tests/test_research_workbench.py |
| tests/test_research_workbench_ui.py | tests/test_research_workbench_ui.py |
| tests/test_research_assistant.py | tests/test_research_assistant.py |
| tests/test_streamlit_boot.py | tests/test_streamlit_boot.py |
| RESEARCH_WORKBENCH_METHODS.md | RESEARCH_WORKBENCH_METHODS.md |
| LLM_PROVIDER_DECISION_2026-10-14.md | LLM_PROVIDER_DECISION_2026-10-14.md |
| RESEARCH_BACKFILL_RIGHTS_2026-10-14.md | RESEARCH_BACKFILL_RIGHTS_2026-10-14.md |
| OVERNIGHT_DECISIONS_2026-10-14.md | OVERNIGHT_DECISIONS_2026-10-14.md |
| OVERNIGHT_ACCEPTANCE_2026-10-14.md | OVERNIGHT_ACCEPTANCE_2026-10-14.md |
| RESEARCH_WORKBENCH_UPLOAD_2026-10-14.md | RESEARCH_WORKBENCH_UPLOAD_2026-10-14.md |
| RESEARCH_WORKBENCH_UPLOAD_2026-10-14.json | RESEARCH_WORKBENCH_UPLOAD_2026-10-14.json |

Use the clean-clone PR routine, `core.autocrlf false` before checkout. Stage
exactly these paths with no unrelated/unstaged/untracked files. From clone root:

```powershell
$reviewBase = (git rev-parse HEAD).Trim()
python overnight_programme_upload_check.py --group application --base $reviewBase
if ($LASTEXITCODE -ne 0) { throw 'STOP: exact application package failed' }
python -m pytest -q tests/test_research_workbench.py tests/test_research_workbench_ui.py tests/test_research_assistant.py tests/test_streamlit_boot.py
if ($LASTEXITCODE -ne 0) { throw 'STOP: focused application tests failed' }
```

Require every PR check and exact post-merge main green. No workflow is enabled,
no capture file installed. Safe to upload during separately frozen capture: yes.
Do not promote release or change Streamlit expectations in this step. The new
candidate fingerprint is in the acceptance note for a separate owner release
review, never taken from a live display.

Safe first later: pages, deterministic cited fallback and explicit synthetic
reports outside 09:15–15:40 IST. Real training, schedules, model calls, private
retrieval and trading authority stay disabled. Rollback: preserve release hold;
withdraw before merge or revert the complete group in a new checked owner PR,
never a partial runtime revert.
