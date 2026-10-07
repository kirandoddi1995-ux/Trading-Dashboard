# Package 2B1 — exact effective-time retry identity

## Scope and decision

Package 2A is owner-reported merged at 56c5508 with green status checks. This
next small group fixes one live local-ledger retry defect before larger recovery
integration. It does NOT finish Package 2B or commission permanent storage.

An explicit effective_at is part of immutable request identity. A retry with a
different instant now fails before adding/resetting delivery intent. Equivalent
UTC/IST representations still reuse the original. Omitting the timestamp or
passing None retains the original time, including after restart; it does not
replace it with the retry's clock. Explicit empty/false/zero inputs are malformed,
not omissions. Existing naive-time-as-UTC and date normalization are unchanged.

Original hashes/signatures, schema, queue transaction boundaries, acknowledged
rows and local-only defaults remain unchanged. No originals are rewritten,
deleted or re-signed. Real SQLite process-exit/queue rollback tests remain in the
focused command. Remote Postgres retry semantics, legacy missing-intent policy,
trusted witness export/restore and every-reader integration remain separate work.
Do not upload the unfinished production_repository.py to fix this local issue.

## Complete upload group — exactly seven files

Paths are relative to C:\Users\banga\Desktop\kiran_share_market. One reviewed PR,
preserving folders; no whole-folder selection. Package 2A need not be uploaded again.

ROOT:

- evidence_ledger.py — explicit-time identity check; omitted-time compatibility.
- LOCAL_LEDGER_RETRY_PACKAGE.md — new review/upload/verification instructions.
- OWNER_KEYS_AND_BACKUP_RUNBOOK.md — current encrypted backup, historical copies,
  project credential exclusions and USB inspection steps.
- PERMANENT_STORAGE_PACKAGES.md — 2A merged/2B1 split and remaining recovery work.
- AUTOMATION_PROGRESS.md — current decisions, scope and test record.

tests/:

- tests/test_ledger_retry_time.py — new offline timestamp/queue/ACK regressions.
- tests/test_storage_package_inventory.py — keep pinned-baseline inventory and
  require explicit inclusion of changed companions, rather than freezing the
  ledger forever; isolated import still excludes unfinished runtime modules.

Exclude credential files, private data, capture folders, old recovery drafts,
local equity_runtime_health.py/production_repository.py replacements, migrations,
workflows and unrelated tests. No new hosted prerequisites or migration needed.

## Owner rehearsal and upload

In a clean checkout of exact main 56c5508566a5ff700c2411d68617d8f0566193c4, copy
only these seven reviewed files. If main advanced, rebase/review and recompute the
fingerprint from the complete candidate checkout; do not assume the value below.
Review changed paths before running any upload. Run from the CLEAN CLONE folder,
using the existing reviewed project environment without copying it into the clone:

```powershell
$storageReviewPython='C:\Users\banga\Desktop\kiran_share_market\.venv\Scripts\python.exe'
```

The inventory CLI's on-disk baseline deliberately remains the historical 62508fd
snapshot. Using it for this seven-file group flags already-merged Package 1
companions as "new": do NOT re-upload those files or rewrite the old baseline.
In the CLEAN GIT CLONE, check dependencies against public Git tree metadata of
the exact current base instead (reads names/hashes only, no network or writes):

```powershell
& $storageReviewPython -c "import json,subprocess; from pathlib import Path; from storage_package_inventory import Baseline,check_package; sha='56c5508566a5ff700c2411d68617d8f0566193c4'; rows=subprocess.check_output(['git','ls-tree','-r','--full-tree',sha],text=True).splitlines(); files={row.split('\t',1)[1]:row.split('\t',1)[0].split()[2] for row in rows}; members=['evidence_ledger.py','LOCAL_LEDGER_RETRY_PACKAGE.md','OWNER_KEYS_AND_BACKUP_RUNBOOK.md','PERMANENT_STORAGE_PACKAGES.md','AUTOMATION_PROGRESS.md','tests/test_ledger_retry_time.py','tests/test_storage_package_inventory.py']; result=check_package(Path.cwd(),Baseline(sha,files),members); print(json.dumps(result)); raise SystemExit(2 if result['blockers'] else 0)"
```

Require PACKAGE_CHECK_PASSED_REQUIRES_REHEARSAL with blockers empty and that
56c5508 base, then run the tests. An advanced main requires a fresh reviewed base;
do not delete blockers or substitute the mixed local inventory. The agent's
equivalent exact-public-tree check passed; the pinned baseline remains unchanged.

```powershell
& $storageReviewPython -m pytest -q -p no:cacheprovider --basetemp "$env:TEMP/ledger-retry-focused-$([guid]::NewGuid().ToString('N'))" tests/test_ledger_retry_time.py tests/test_evidence_atomic_delivery.py tests/test_local_state_recovery.py tests/test_ledger_key_availability.py tests/test_storage_package_inventory.py
& $storageReviewPython -m pyflakes evidence_ledger.py tests/test_ledger_retry_time.py tests/test_storage_package_inventory.py
& $storageReviewPython -m mypy --strict --follow-imports=silent tests/test_ledger_retry_time.py
```

Full suite uses the same configured SQL harness as prior owner rehearsals/CI:

```powershell
$env:EQUITY_TEST_PGLITE_MODULE='C:\Users\banga\Desktop\kiran_share_market\tests\sql-harness\node_modules\@electric-sql\pglite'
& $storageReviewPython -m pytest -q -p no:cacheprovider --basetemp "$env:TEMP/ledger-retry-full-$([guid]::NewGuid().ToString('N'))" --tb=short
```

Unique temporary roots avoid the inaccessible stale pytest-current directory
observed locally. Do not remove the old directory or count a teardown-error run
as a successful suite. Type checking above covers new typed tests; the legacy
ledger module is not claimed to be newly strict-typed in full.

Merge only after exact-candidate quality/resilience/CodeQL pass. Keep release
promotion held, installed capture untouched and scan-only recurrence unchanged.
Collectors run main after merge; this change is schema-compatible and no cold
reader/factory is activated. No hosted write is requested in this package.

## Fingerprint — reviewed candidate, NOT the unfinished local working set

The explicit 53-file manifest from exact main was used. Main-matching local
files were Git-blob checked; public main copies supplied the two unrelated local
drafts (runtime health and production repository). Only evidence_ledger.py is
replaced by this package. Normalized LF source bytes give:

- Exact-main baseline: f7ff707c03609986b56276cc1a724d27b71e7ec6b977fccf0d43533e0feb30ae.
- Candidate EXPECTED_EQUITY_CODE_SHA256:
  c6b33f7db02346303cbea4ea83f0a38debc825cafcb0fa272622ab4b11504c95.

Recompute independently in the clean candidate checkout before use. This is
not the fingerprint of the current release branch; do not change Streamlit's
expectation while its old release is serving. This package does not authorize
promotion. At a later reviewed promotion, mismatched expectations must block
entries until the owner configures the reviewed running release hash. Update
any main-consuming fingerprint expectation only with its reviewed code upload;
do not substitute a displayed runtime value for the reviewed candidate. A source
inspection of current workflow environment definitions found no use of
EXPECTED_EQUITY_CODE_SHA256, so this package requests no GitHub variable/secret
change. EVIDENCE_LEDGER_SIGNING_KEY is a different control and stays unchanged.

## Remaining sequence

Next: authenticated consistent source backup/witness custody, cross-file restore
identity, then legacy intent and remote retries without broad draft uploads.
Package 3 connects complete historical readers/key/root adapters only after
their prerequisite review. Package 4 commissions archive publication/deletion
only after original-key verification, licence permission, independent encrypted
replicas and whole-application restore. Missing keys/evidence protect history;
they are never replaced with a guessed key or fabricated delivery intent.

Validation: final expanded focused suite 160 passed; final full suite 2,517 passed,
4 unchanged skips, 2 subtests passed (538.68s). Full root/tests pyflakes clean.
Main's actual 19-module strict type-check configuration passes; seven-module
core/recovery/new-test strict check with followed import types passes. Actual
synthetic/offline app boot (login/Settings) passes. A stale baseline-equality
test caught by the first full run was corrected without changing the baseline
or permitting omitted companions; that run is not reported as passing. Final
full suite/self-review and the unuploaded expanded-config type-boundary issue are
recorded in AUTOMATION_PROGRESS.md. That draft configuration is not in this group.
No actual keys, historical datasets,
installed capture state or hosted resource were opened or changed for these tests.
