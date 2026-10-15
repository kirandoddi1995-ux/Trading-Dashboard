# One inactive upload group — 15 October 2026

PR description: **Add offline morning routing, quiescent evidence preservation,
consistent-cut export/native rehearsal, prospective cohort checks and report-only
agent-team contracts; no production wiring or hosted changes.**

## Order and safety

ONE PR, all20files together, from exact green base
1251530731cce5b75fad8601567b9320d07b710d. Do not split root/test/control uploads.
Morning owner procedure uses that already-merged baseline and a fresh detached
capsule; new source is not installed as a capture producer. All new tools inactive.
Safe to review/upload during capture because the installed capsule is separate
and unchanged and no production source/workflow/configuration is replaced.
Do not enable workflows, alerts, models, retention or factory switches.

Create the clean public rehearsal clone with `git clone --config core.autocrlf=false`
so approved resilience-policy bytes remain EXACT Git bytes. The checker pins both
existing policy/sidecar files and verifies their raw-byte checksum in addition to
LF-normalized source pins. Do NOT upload replacements or recompute the approved
policy checksum to make a converted checkout pass. A mismatch means rebuild the
disposable checkout correctly, not change production policy.

If main advances before this rehearsal, STOP. Review its exact source closure
and rebuild a package against that public tree; do not edit the --base argument,
remove a pin, use workspace draft bytes or call a historical checker with a new
base just to pass. Green CI must belong to the final uploaded SHA before merge.

## Exact source → destination paths

Every source is under C:/Users/banga/Desktop/kiran_share_market/.
Destination prefix is YOUR CLEAN PUBLIC PR CLONE, not an installed capsule or
TradingResearch. The identical suffix on the right is the exact repo destination.
Only these paths; no private data, held storage drafts, .venv, progress file,
Docker fixture volume, local test caches or secret files.

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
```

## Rehearsal, one block at a time

Use existing reviewed external $testPython and public $publicPgliteModule.
No dependency upgrades, private credential reads or installed-task test runs.
Fresh interpreter/capsule installation belongs only to the morning owner guide.

```powershell
$ErrorActionPreference = 'Stop'
if ((git rev-parse HEAD).Trim() -ne '1251530731cce5b75fad8601567b9320d07b710d') { throw 'STOP: wrong baseline' }
$env:EQUITY_TEST_PGLITE_MODULE = $publicPgliteModule
git add -- forward_morning_route.py tests/test_forward_morning_route.py forward_evidence_preserve.py tests/test_forward_evidence_preserve.py storage_consistent_cut_export.py tests/test_storage_consistent_cut_export.py storage_cut_native_check.py tests/test_storage_cut_native_check.py research_forward_cohort.py tests/test_research_forward_cohort.py programme_agent_team.py tests/test_programme_agent_team.py MORNING_2026-10-15.md OWNER_CAPTURE_2026-10-15.md OVERNIGHT_CONTINUITY_2026-10-15.md AGENT_TEAM_2026-10-15.md continuity_upload_check.py tests/test_continuity_upload_check.py CONTINUITY_UPLOAD_2026-10-15.md CONTINUITY_UPLOAD_2026-10-15.json
if ($LASTEXITCODE -ne 0) { throw 'STOP: staging failed' }
& $testPython -B continuity_upload_check.py --base 1251530731cce5b75fad8601567b9320d07b710d
if ($LASTEXITCODE -ne 0) { throw 'STOP: package or prerequisite pins differ' }
```

Focused line (use a NEW temporary path each run, never reuse/delete evidence):

```powershell
$testTemp = Join-Path $env:LOCALAPPDATA ('Temp\continuity-focus-' + [guid]::NewGuid().ToString('N'))
& $testPython -B -m pytest -q -p no:cacheprovider --basetemp $testTemp tests/test_forward_morning_route.py tests/test_forward_evidence_preserve.py tests/test_storage_consistent_cut_export.py tests/test_storage_cut_native_check.py tests/test_research_forward_cohort.py tests/test_programme_agent_team.py tests/test_continuity_upload_check.py tests/test_forward_session_ops.py tests/test_forward_morning_readiness.py tests/test_overnight_capture_audit.py tests/test_storage_daily_volume_reader.py
if ($LASTEXITCODE -ne 0) { throw 'STOP: focused check failed' }
```

Strict typing/lint on ALL fourteen source/test paths and existing public strict
profile; full Windows and Linux suites are required, counts/skips explicitly
labelled. Local Debian is not hosted Ubuntu. The existing local-only Docker
recipe/runner from the PR33 repair can run the clean staged public clone with
network none and no private mounts; it copies only tracked public sources into
writable disposable /tmp for synthetic caches. Do not mount the dirty workspace,
capture/state/ops/TradingResearch. Record final exact byte hashes and interpreter
versions. Do not infer pass from a container merely starting or a skipped case.

## Disposable native check — not Supabase SQL

The native harness has NO host, URL, password or database argument. It can only
connect to loopback55436, fixed kiran_cut_disposable and public synthetic fixture
credentials. It rejects inherited libpq PG* variables by NAME. Preview zeroIO.
Requires a FRESH disposable Postgres17.6; rejects an existing quant_app schema.
Never point the fixture at Supabase or run its CREATE statements there.

Owner can wait; no new workflow or hosted dispatch is required. After review:

```powershell
# Local disposable test only. Choose a NEW container name; never overwrite/reuse.
docker run --name kiran-cut-owner-NEW --publish 127.0.0.1:55436:5432 --memory 512m --cpus 1 -e POSTGRES_DB=kiran_cut_disposable -e POSTGRES_PASSWORD=synthetic-disposable-only -d postgres:17.6-bookworm
if ($LASTEXITCODE -ne 0) { throw 'STOP: fixture start failed' }
# Wait for Docker's synthetic server readiness, NOT a blind fixture retry.
& $testPython -B storage_cut_native_check.py
& $testPython -B storage_cut_native_check.py --execute --confirm-disposable
if ($LASTEXITCODE -ne 0) { throw 'STOP: native case blocked; preserve redacted stage/cases' }
```

No fixture same-database retry after failure; first identify the redacted failing
stage. Stop ONLY your exact disposable container afterward, retain for inspection.
Do not delete volumes or operate any other containers. Capture unaffected.
Native success proves this bounded daily-volume SQL window only, not all-source
export, physical allocation, signed object publication, custody or global writers.

## Owner items and honest acceptance

Read morning card FIRST. Evidence copy/audit needs real owner checks, original
environment, quiescence and an ALREADY private destination parent. No permission
repair, key read, source rewrite or timestamp invention. Notify rehearsal needs
human observation. Actual daily capture/tasks remain owner commissioning.

Later: encrypted key note/history coverage, harmless7Zip/disk restore rehearsal,
Drive capacity/retention review, exact object-set publication and real restore
proofs. Nothing deleted before verified custody and restore. Real-data licences,
contract quotes/labels and prospective registration block real training; model
and LLM backends stay disabled. Role templates are strings, not installed agents.

## Verification record

Final focused/full platform counts and native receipt are recorded after terminal
verification in the final handoff and local AUTOMATION_PROGRESS.md; no unfinished
run is counted as a pass. Source bytes and pins are frozen before each full run.
Existing app/production code is unchanged, so no new EXPECTED_EQUITY_CODE_SHA256
is requested. Preserve release hold and installed capture expectations unchanged.
