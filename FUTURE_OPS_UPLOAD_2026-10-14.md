# Upload 1 — future operations (inactive)

Start from the newest green merged main. Rehearsed baseline:
`da4a9be7d5b3e805c76cc7c677795d6eebd33a36`. Supply current HEAD exactly;
every unchanged import/requirements prerequisite remains hash-pinned. Stop on
mismatch: no pin is removed or loosened for a later merge.

Source root: `C:/Users/banga/Desktop/kiran_share_market/`.
Copy ONLY these ten paths to the same paths in a clean main clone:

| Source relative to root | Destination relative to clone |
| --- | --- |
| future_ops_diagnostics.py | future_ops_diagnostics.py |
| future_ops_task.ps1 | future_ops_task.ps1 |
| requirements-forward-operations.txt | requirements-forward-operations.txt |
| tests/test_future_ops_diagnostics.py | tests/test_future_ops_diagnostics.py |
| FUTURE_OPERATIONS_REPAIR.md | FUTURE_OPERATIONS_REPAIR.md |
| MORNING_CARD_2026-10-14.md | MORNING_CARD_2026-10-14.md |
| overnight_programme_upload_check.py | overnight_programme_upload_check.py |
| tests/test_overnight_programme_upload_check.py | tests/test_overnight_programme_upload_check.py |
| FUTURE_OPS_UPLOAD_2026-10-14.md | FUTURE_OPS_UPLOAD_2026-10-14.md |
| FUTURE_OPS_UPLOAD_2026-10-14.json | FUTURE_OPS_UPLOAD_2026-10-14.json |

Use the existing clean-clone PR routine. Set `core.autocrlf false` BEFORE cloning
or checkout; approved policy bytes must retain LF. Never copy private state,
credentials, installed capture or the unfinished workspace. Stage all ten paths
and nothing unrelated; no untracked or unstaged files. From the clone root:

```powershell
$reviewBase = (git rev-parse HEAD).Trim()
python overnight_programme_upload_check.py --group future_ops --base $reviewBase
if ($LASTEXITCODE -ne 0) { throw 'STOP: exact package review failed' }
python -m pytest -q tests/test_future_ops_diagnostics.py tests/test_overnight_programme_upload_check.py
if ($LASTEXITCODE -ne 0) { throw 'STOP: focused tests failed' }
```

Use the approved test environment; these commands install nothing. A passing
checker is byte/closure acceptance, not commissioning. Require all PR checks
and exact post-merge main checks green before Upload 2. Separate control files
mean Upload 2 cannot rewrite this plan. Safe to upload during capture: yes;
never install during that session. Future owner acceptance is in the runbook
and morning card. No task/service change occurs. Keep the release hold.
