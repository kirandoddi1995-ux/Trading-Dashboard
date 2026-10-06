# Restore main without commissioning unfinished storage

## Decision

Keep release at `b23323ffaed67129a1e03d87247bfdec789c44f9` until the repair is reviewed
and all required checks pass for its exact SHA. First turn
`DASHBOARD_RELEASE_ENABLED` off yourself; a green commit must not automatically
promote the accidentally uploaded permanent-storage implementation.

The read-only GitHub comparison confirms main `0d78993d28d46db023d83eb29381bec252f8a33e`
is six commits ahead of release. This is not only a tests upload problem:

- `c616decc972149b0152e24e0c77493084e930b86` uploaded unfinished root storage modules
  and changed `production_repository.py`, recovery and the release fingerprint.
- `7f4aefe8cb86ca89dbbdfb89523f220c4f5b64f5` uploaded their tests and the capture
  repair test, without the three draft migrations or the repaired capture sources.
- Subsequent collector safety code, workflow, read-only diagnostics and documents
  can stay. They do not require the unfinished ledger package.

Do NOT add draft migrations to silence errors, skip missing-file tests, disable the
SQL harness, weaken assertions, or enable storage pruning. Main must regain the
released runtime and its original tests, not merely become green by dropping tests.
The withdrawn tests and implementation remain intact in the local source workspace
and recoverable in Git history. No evidence or history is deleted.

## Why this repair is separate

The source workspace is intentionally ahead of production and includes unfinished
work. Running its full suite is not proof that a partial upload is complete. This
repair is tested against a separate checkout of the exact failing main commit.
The helper refuses the active source workspace, changed HEAD, dirty checkout,
missing paths, unsafe paths and unexpected postconditions. Default is preview.
It never commits, pushes, connects to hosted services or changes settings.

It restores eight modified files exactly from the released commit, withdraws
12 unfinished root modules and 18 new unreleased tests, and removes the IV cache
from Git tracking while preserving the cache file on disk. The original released
test files are restored, not removed. Existing released tests remain mandatory.

## Owner sequence — one consistent repair commit

1. GitHub repository → Settings → Secrets and variables → Actions → Variables:
   set `DASHBOARD_RELEASE_ENABLED=false`. Confirm no publish job is running and
   release is still `b23323f`. Leave the live Streamlit expectations unchanged.
   No new database migrations, task edits or capture deployment are part of this.
2. Keep the emergency collector safety gate on main. At low headroom, visible
   `COLLECTOR_STORAGE_BLOCKED` is expected, not a reason to remove the check.
   The missing `tests/test_collector_storage_preflight.py` must be included below.
   Leave verified Drive archival enabled. Main's failing quality gate does not
   itself stop independently dispatched collector workflows.
3. Open PowerShell. Make a NEW empty folder, outside `kiran_share_market` and outside
   private TradingResearch. Example: `C:\Users\banga\Desktop\main_ci_repair_2026_10_06`.
   Clone the public repository into it; do not put credentials in commands:

   ```powershell
   git -c core.autocrlf=false clone --branch main --single-branch https://github.com/kirandoddi1995-ux/Trading-Dashboard.git C:/Users/banga/Desktop/main_ci_repair_2026_10_06
   git -C C:/Users/banga/Desktop/main_ci_repair_2026_10_06 config core.autocrlf false
   ```

   If Git's Windows TLS backend reports `SEC_E_NO_CREDENTIALS`, retry in another
   NEW empty folder with `git -c core.autocrlf=false -c http.sslBackend=openssl clone ...` using the same
   arguments. Do not disable certificate verification or add a token to the URL.
   The second command changes only this clone's line-ending setting, not global
   Git settings or hosted resources. Do not upload the helper/test files to main
   before preparing this repair: that advances main and intentionally invalidates
   the helper's exact-SHA check. Copy them into the repair checkout at step 5.
4. From the SOURCE workspace run the following, replacing the checkout path if
   different. The first command must report `REPAIR_PREVIEW` with the exact main
   and released SHAs above. If main changed, STOP for a new comparison; do not edit
   the helper constants or check out the old main and overwrite later work.
   `POLICY_CHECKOUT_BYTES_INVALID_RECLONE_LF` means Git converted policy bytes;
   re-clone into a new empty folder with the line-ending option above. Do not
   change the policy checksum, normalize the live policy, or weaken verification.

   ```powershell
   .venv/Scripts/python.exe prepare_main_ci_repair.py --checkout C:/Users/banga/Desktop/main_ci_repair_2026_10_06
   .venv/Scripts/python.exe prepare_main_ci_repair.py --checkout C:/Users/banga/Desktop/main_ci_repair_2026_10_06 --apply-local
   ```

   Expected second result: `LOCAL_REPAIR_STAGED_NOT_COMMITTED`. The helper staged
   39 paths: eight restorations, 30 withdrawn code/test paths, one cache untracking.
   The cache remains on disk and must not be uploaded. A partial failure leaves
   only this separate clone changed; do not commit it. Keep it for diagnosis and
   prepare a new clean clone after review. No active task sources are overwritten.
5. In the NEW checkout create a repair branch yourself, then copy ONLY these
   complete files from the source workspace to matching paths in that checkout:

   - ROOT: `prepare_main_ci_repair.py`
   - `tests/test_prepare_main_ci_repair.py`
   - `tests/test_collector_storage_preflight.py`
   - ROOT: `MAIN_CI_REPAIR_2026-10-06.md`

   ```powershell
   git -C C:/Users/banga/Desktop/main_ci_repair_2026_10_06 switch -c repair-main-ci-2026-10-06
   ```

   Do not copy the whole source folder, staged capture directory, private files,
   draft migrations, runtime readers or the source workspace fingerprint.
   Capture repair remains a later maintenance-window package with both sources.
6. Review `git diff --cached --stat` and the eight restored files. Add only the four
   copied paths. The retained helper/workflow/read-only diagnostics should not be
   reverted. Confirm `.iv_history_cache.json` is absent from `git ls-files` but still
   present on disk. `.gitignore` already excludes it; ignore rules do not untrack
   existing files or prevent GitHub web uploads. Its older versions remain public
   in history; this step does NOT erase past exposure or establish a licence right.

   ```powershell
   git -C C:/Users/banga/Desktop/main_ci_repair_2026_10_06 add -- prepare_main_ci_repair.py tests/test_prepare_main_ci_repair.py tests/test_collector_storage_preflight.py MAIN_CI_REPAIR_2026-10-06.md
   ```

7. Run the final checkout tests, not the ahead-of-production source tree. Use the
   existing source virtual environment and locked disposable SQL engine:

   ```powershell
   Set-Location C:/Users/banga/Desktop/main_ci_repair_2026_10_06
   $env:EQUITY_TEST_PGLITE_MODULE='C:/Users/banga/Desktop/kiran_share_market/tests/sql-harness/node_modules/@electric-sql/pglite'
   & C:/Users/banga/Desktop/kiran_share_market/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp "$env:TEMP/repaired-main-$([guid]::NewGuid().ToString('N'))"
   $repairSources=Get-ChildItem -LiteralPath . -File -Filter '*.py' | ForEach-Object { $_.Name }
   & C:/Users/banga/Desktop/kiran_share_market/.venv/Scripts/python.exe -m pyflakes $repairSources tests
   & C:/Users/banga/Desktop/kiran_share_market/.venv/Scripts/python.exe -m mypy --config-file mypy-automation.ini
   & C:/Users/banga/Desktop/kiran_share_market/.venv/Scripts/python.exe -m mypy --strict prepare_main_ci_repair.py collector_storage_preflight.py
   ```

   Compare test counts to the released baseline plus the new collector/repair
   tests, NOT the unfinished workspace's 2,143. Withdrawing unreleased feature
   tests together with their implementation is not a test skip or gate relaxation.
8. Owner creates ONE repair commit, pushes this repair branch and opens a pull
   request to main, or uses GitHub Desktop to publish the branch and create the PR.
   This is explicitly an owner action: the agent has not committed or pushed.
   Wait for quality, resilience and CodeQL on the final repair SHA before merging.
   If main advanced in the meantime, re-review the diff and re-run checks; do not
   force-push or reset main/release. Do not hand-delete 31 files through separate
   web commits: the isolated repair checkout provides one atomic consistent change.
9. After merge, keep promotion disabled until all required checks pass for the
   newest exact main SHA and the release preview is ready. Verify the expected
   decision fingerprint equals the current reviewed release fingerprint, since
   the eight runtime/test files were restored. No Streamlit secret change is
   needed for this collector/repair-only release. Review remaining read-only docs
   as proposals, not commissioned code. Then restore promotion only when intended;
   a restart can auto-scan and create evidence, so assess database capacity first.

## Local verification

The independently repaired main checkout passed the full suite: **1,769 passed,
four skipped, two subtests passed**, in 438.32 seconds. Final focused checks passed
**54 tests**, including two policy-symlink regressions added after full-suite
collection. These two were also verified in the repaired checkout. No original
released test was skipped or weakened; the full-run count is released baseline
1,727 + 28 collector tests + 14 repair tests. The final repair test file has 16
tests; fresh CI must include all of them.

Root/test lint, 19-module automation type checks and strict checks for both new
helpers passed. Repository readiness, deployment canaries and resilience game-day
checks passed. The full suite includes app import, real offline login/settings
boot, disposable SQL and packaged-artifact import checks. The first clone run's
checksum failures were traced to Windows checkout line-ending conversion, not a
committed policy change; verification was rerun with original approved LF bytes.

Self-review checked the exact-SHA/clean-clone restriction, preservation of active
workspace and cache/history, original-test restoration, fixed error-code redaction,
bounded local Git calls, policy byte/symlink checks and expected 39-path staged diff.
No commit, push, workflow dispatch, setting, migration or hosted write was made.

Repaired decision fingerprint, equal to the released baseline:
`f7ff707c03609986b56276cc1a724d27b71e7ec6b977fccf0d43533e0feb30ae`.
Do not replace it with the ahead-of-production workspace fingerprint. These
results verify the repaired checkout and helper locally, not hosted quota safety,
network availability, a fresh dependency install/audit or hosted CI. No 2025/2026
research data is inspected. Owner must still obtain all exact-SHA hosted checks.
