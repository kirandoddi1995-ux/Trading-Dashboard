# One reviewed upload — Friday readiness and project conductor

PR description: **Add reusable date-driven owner coordination, deterministic
conductor contracts and permanent scouting/verification rules; preserve frozen
producer, clock/source gates and inactive storage/research foundations.**

## Choose exactly one layout

Recommended while public main remains1251530731cce5b75fad8601567b9320d07b710d:
ONE33-file PR. Copy the unchanged20files in CONTINUITY_UPLOAD_2026-10-15.md AND
the13files below. Do not run the old20-file checker on33staged files: the NEW
combined checker pins all20 unchanged bytes and all13 new files together. No
existing manifest/source is edited or pin removed to make this pass.

Alternative ONLY if the20already merged green: ONE13-file follow-up PR. Actual
HEAD must be the complete125tree plus EXACTLYthose20 additions with exactpins.
No production file, workflow or unrelated edit may have landed in between.
If main differs, stop and request a reviewed reconciliation; never edit a pin.
The future merge SHA is recorded from actual Git, never guessed in advance.

## Complete combined33 source -> destination list

Source root C:/Users/banga/Desktop/kiran_share_market/, destination your NEW
clean public PR clone, never any installed capture folder or private state root.
Combined layout uses ALL33 below. Follow-up layout uses ONLY the last13, starting
at forward_daily_contract.py. The first20are unchanged; no other changed path.

```text
C:/Users/banga/Desktop/kiran_share_market/forward_morning_route.py -> forward_morning_route.py
C:/Users/banga/Desktop/kiran_share_market/tests/test_forward_morning_route.py -> tests/test_forward_morning_route.py
C:/Users/banga/Desktop/kiran_share_market/forward_evidence_preserve.py -> forward_evidence_preserve.py
C:/Users/banga/Desktop/kiran_share_market/tests/test_forward_evidence_preserve.py -> tests/test_forward_evidence_preserve.py
C:/Users/banga/Desktop/kiran_share_market/storage_consistent_cut_export.py -> storage_consistent_cut_export.py
C:/Users/banga/Desktop/kiran_share_market/tests/test_storage_consistent_cut_export.py -> tests/test_storage_consistent_cut_export.py
C:/Users/banga/Desktop/kiran_share_market/storage_cut_native_check.py -> storage_cut_native_check.py
C:/Users/banga/Desktop/kiran_share_market/tests/test_storage_cut_native_check.py -> tests/test_storage_cut_native_check.py
C:/Users/banga/Desktop/kiran_share_market/research_forward_cohort.py -> research_forward_cohort.py
C:/Users/banga/Desktop/kiran_share_market/tests/test_research_forward_cohort.py -> tests/test_research_forward_cohort.py
C:/Users/banga/Desktop/kiran_share_market/programme_agent_team.py -> programme_agent_team.py
C:/Users/banga/Desktop/kiran_share_market/tests/test_programme_agent_team.py -> tests/test_programme_agent_team.py
C:/Users/banga/Desktop/kiran_share_market/MORNING_2026-10-15.md -> MORNING_2026-10-15.md
C:/Users/banga/Desktop/kiran_share_market/OWNER_CAPTURE_2026-10-15.md -> OWNER_CAPTURE_2026-10-15.md
C:/Users/banga/Desktop/kiran_share_market/OVERNIGHT_CONTINUITY_2026-10-15.md -> OVERNIGHT_CONTINUITY_2026-10-15.md
C:/Users/banga/Desktop/kiran_share_market/AGENT_TEAM_2026-10-15.md -> AGENT_TEAM_2026-10-15.md
C:/Users/banga/Desktop/kiran_share_market/continuity_upload_check.py -> continuity_upload_check.py
C:/Users/banga/Desktop/kiran_share_market/tests/test_continuity_upload_check.py -> tests/test_continuity_upload_check.py
C:/Users/banga/Desktop/kiran_share_market/CONTINUITY_UPLOAD_2026-10-15.md -> CONTINUITY_UPLOAD_2026-10-15.md
C:/Users/banga/Desktop/kiran_share_market/CONTINUITY_UPLOAD_2026-10-15.json -> CONTINUITY_UPLOAD_2026-10-15.json
C:/Users/banga/Desktop/kiran_share_market/forward_daily_contract.py -> forward_daily_contract.py
C:/Users/banga/Desktop/kiran_share_market/forward_daily_owner.ps1 -> forward_daily_owner.ps1
C:/Users/banga/Desktop/kiran_share_market/tests/test_forward_daily_contract.py -> tests/test_forward_daily_contract.py
C:/Users/banga/Desktop/kiran_share_market/tests/test_forward_daily_owner.py -> tests/test_forward_daily_owner.py
C:/Users/banga/Desktop/kiran_share_market/project_conductor.py -> project_conductor.py
C:/Users/banga/Desktop/kiran_share_market/tests/test_project_conductor.py -> tests/test_project_conductor.py
C:/Users/banga/Desktop/kiran_share_market/PROJECT_WORKING_AGREEMENT.md -> PROJECT_WORKING_AGREEMENT.md
C:/Users/banga/Desktop/kiran_share_market/TECHNOLOGY_RADAR_2026-10-15.md -> TECHNOLOGY_RADAR_2026-10-15.md
C:/Users/banga/Desktop/kiran_share_market/FRIDAY_CAPTURE_2026-10-16.md -> FRIDAY_CAPTURE_2026-10-16.md
C:/Users/banga/Desktop/kiran_share_market/daily_owner_upload_check.py -> daily_owner_upload_check.py
C:/Users/banga/Desktop/kiran_share_market/tests/test_daily_owner_upload_check.py -> tests/test_daily_owner_upload_check.py
C:/Users/banga/Desktop/kiran_share_market/DAILY_OWNER_UPLOAD_2026-10-15.md -> DAILY_OWNER_UPLOAD_2026-10-15.md
C:/Users/banga/Desktop/kiran_share_market/DAILY_OWNER_UPLOAD_2026-10-15.json -> DAILY_OWNER_UPLOAD_2026-10-15.json
```

No .venv, caches, evidence, secret files, local Docker recipes, installed capsule,
held storage drafts, progress record or private paths/keys in the PR. Script
definitions cannot register a task or run capture during upload/import/tests.
Controller actions require explicit owner confirmation after review/greenCI.

## Rehearse the exact public tree

Use the usual NEW clean public clone, `git clone --config core.autocrlf=false`.
The approved resilience-policy RAW bytes must match its unchanged sidecar. Never
repair a converted checkout by replacing that approved checksum. Record the base
BEFORE copying. Stage only the exact manifest paths, not `git add --all` over a
dirty project. Choose your reviewed pinned test interpreter as `$testPython`.

Combined layout, on exact anchor125:

```powershell
$dailyBase = (git rev-parse HEAD).Trim()
if ($dailyBase -cne '1251530731cce5b75fad8601567b9320d07b710d') { throw 'STOP: wrong combined baseline' }
# Copy and stage EXACTLY the old20 plus new13 listed paths, then:
& $testPython -B daily_owner_upload_check.py --base $dailyBase --combined
if ($LASTEXITCODE -ne 0) { throw 'STOP: exact33file check failed' }
```

Follow-up layout, only after exact20merged green:

```powershell
$dailyBase = (git rev-parse HEAD).Trim()
# Copy and stage EXACTLY the13 new paths, then:
& $testPython -B daily_owner_upload_check.py --base $dailyBase
if ($LASTEXITCODE -ne 0) { throw 'STOP: exact13file check or prerequisite tree failed' }
```

Focused test line, BOTH layouts (fresh synthetic temporary directory per run):

```powershell
$dailyTemp = Join-Path $env:LOCALAPPDATA ('Temp\daily-focus-' + [guid]::NewGuid().ToString('N'))
& $testPython -B -m pytest -q -p no:cacheprovider --basetemp $dailyTemp tests/test_forward_daily_contract.py tests/test_forward_daily_owner.py tests/test_project_conductor.py tests/test_daily_owner_upload_check.py tests/test_forward_morning_readiness.py tests/test_forward_session_ops.py tests/test_nse_owner_close.py
if ($LASTEXITCODE -ne 0) { throw 'STOP: focused regression failed' }
```

Full suite and lint, on the exact staged candidate:

```powershell
$dailyFull = Join-Path $env:LOCALAPPDATA ('Temp\daily-full-' + [guid]::NewGuid().ToString('N'))
& $testPython -B -m pytest -q -p no:cacheprovider --basetemp $dailyFull
if ($LASTEXITCODE -ne 0) { throw 'STOP: full suite failed' }
& $testPython -B -m pyflakes forward_daily_contract.py project_conductor.py daily_owner_upload_check.py tests/test_forward_daily_contract.py tests/test_forward_daily_owner.py tests/test_project_conductor.py tests/test_daily_owner_upload_check.py
if ($LASTEXITCODE -ne 0) { throw 'STOP: lint failed' }
& $testPython -B -m mypy --strict --follow-imports=silent forward_daily_contract.py project_conductor.py daily_owner_upload_check.py tests/test_forward_daily_contract.py tests/test_forward_daily_owner.py tests/test_project_conductor.py tests/test_daily_owner_upload_check.py
if ($LASTEXITCODE -ne 0) { throw 'STOP: strict typing failed' }
git diff --cached --check
```

Run the same full candidate in the existing disposable offline Linux recipe;
local Debian is NOT hosted Ubuntu CI. WindowsPowerShell5.1 and PowerShell7 tests
use actual parsers and synthetic mocked commands only; they do not register tasks,
open private folders or repair Windows. Linux skips unavailable PowerShell runtimes
explicitly; portable contract checks still run. Never present skipped acceptance
as a pass. Native operations and notification delivery remain owner acceptance.
The source/task/clock gates are not changed if tests fail. Hosted quality,
resilience and CodeQL must pass for the EXACT final PR commit before owner merge.

## What to do after merge

Use a NEW clean reviewed tools checkout for the controller. Follow
FRIDAY_CAPTURE_2026-10-16.md: Setup ahead of time, fresh Friday owner-file Prepare,
then one Start before09:20:30, with explicit conditional-enable confirmation.
All slow admission checks precede poll enablement. A local precommit witness is
not an enabled-state/custody proof. Positive output is acknowledgement-only;
missing/late acknowledgement needs owner reconciliation, with no retry or promise
of automatic disarming. First actual scheduled execution remains owner acceptance.
It creates a separate exact125 capsule; no new helper is installed into it.
All old tasks remain disabled. No same-slot retries, catch-up, permission/service
repair or producer-window change. Existing14Oct preservation is not repeated.

Conductor is pure contract code and memory, not an installed agent/LLM or a
sandbox. Its future proof policy requests hosted Windows/Ubuntu evidence; it is
not a new active dependency of the Friday controller. No runtime agent has action
authority. No model/APIkey/account/notification subscription is activated.
Storage/custody/restore and real-data licences/paper study remain gates; no delete,
factory switch, real fitting or decision approval. Production fingerprint remains
unchanged; do not change Streamlit expectations or release hold.

Final test counts, independent review and unverified owner items are recorded in
the handoff/progress record after terminal checks. A local synthetic prerequisite
commit is rehearsal evidence only, never claimed as a public merge or hostedCI.
