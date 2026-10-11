# Disposable native guard runner repair — 11 October 2026

## What failed and what is fixed

Two independently reproduced defects explain an early failure before race cases:

1. `service=''` makes libpq look up an empty named connection service. A local
   synthetic loopback probe of the original factory returned OperationalError
   with that condition before any connection. The repaired factory omits that
   argument and refuses PGSERVICE, PGSERVICEFILE or PGSYSCONFDIR by name presence
   before importing the driver. No environment value is displayed or copied.
   Explicit loopback host/hostaddr, sandbox database, fixture role/password,
   null passfile, disabled SSL/GSS and bounded timeout remain unchanged.
2. The database safety comment is a shared-object comment. The runner used
   obj_description, not shobj_description. In an isolated offline SQL engine,
   the old query returned null and the corrected query returned the marker.
   The regression executes the actual corrected PROFILE_SQL. This tests catalog
   semantics, not native backends/advisory-lock races.

The old workflow output cannot establish which failing stage was reached.
The empty-service defect is the strongest explanation for the one-second stop;
the marker defect would block a successful connection next. Both are fixed.
The provisioned fixture and workflow need no changes or privilege widening.
No Supabase SQL, hosted setting or installed capture change is needed.

Documentation: [PostgreSQL comment functions](https://www.postgresql.org/docs/17/functions-info.html#FUNCTIONS-INFO-COMMENT-TABLE),
[libpq connection parameters](https://www.postgresql.org/docs/17/libpq-connect.html#LIBPQ-PARAMKEYWORDS).

## Safe diagnostics

Blocked receipts retain exit 2 and code NATIVE_CONFORMANCE_FAILED, and add:

- stage: one of CONNECT_FIRST/SECOND, VERIFY_FIRST/SECOND_PROFILE,
  VERIFY_EMPTY_FIXTURE, COMMITTED_APPEND, CONCURRENT_WRITER, BODY_ROLLBACK,
  CALLER_COMMIT, CONSTRAINT_ROLLBACK, CLOSE_FIRST/SECOND or UNEXPECTED.
- error_category: a fixed allowlisted category (for example AUTHENTICATION,
  PERMISSION, SERVICE_ENVIRONMENT, IDENTITY_MISMATCH, CONNECTION_TIMEOUT,
  GUARD_BLOCK or REDACTED_EXCEPTION), not raw exception text/class/SQLSTATE.
- passed_cases: only known cases completed before the failure. This is NOT a
  successful-run receipt; cleanup failure still blocks, even after six cases.

No driver message, query text, DSN, connection value or traceback is logged.
Unknown or malformed exception metadata stays redacted. There are no retries.
Preview still imports no driver and performs zero connections/writes.

## One consolidated upload — seven complete files

Source root: `C:\Users\banga\Desktop\kiran_share_market`.
Destination root: the owner's clean clone on the latest exact main commit.
Every source/destination below is relative to those roots; no staged substitution.

| Source | Destination | Change |
| --- | --- | --- |
| storage_native_conformance.py | storage_native_conformance.py | Fix service and marker lookups; bounded safe diagnostics and cleanup reporting |
| reviewed_upload_check.py | reviewed_upload_check.py | Allow only the new repair manifest/group in addition to existing groups |
| tests/test_storage_native_conformance.py | tests/test_storage_native_conformance.py | Connection configuration, real offline catalog regression, every failure stage and redaction/cleanup |
| tests/test_reviewed_upload_check.py | tests/test_reviewed_upload_check.py | Explicit repair-group selection and wrong-group rejection |
| STORAGE_NATIVE_REPAIR_2026-10-11.md | STORAGE_NATIVE_REPAIR_2026-10-11.md | Diagnosis, upload manifest and owner rerun instructions |
| STORAGE_NATIVE_REPAIR_UPLOAD_2026-10-11.json | STORAGE_NATIVE_REPAIR_UPLOAD_2026-10-11.json | LF-normalized file hashes and unchanged fixture/workflow/guard prerequisites |
| AUTOMATION_PROGRESS.md | AUTOMATION_PROGRESS.md | Current repair checkpoint and validation record |

Do not copy any other held drafts, secrets, fixture SQL or workflow. Existing
STORAGE_FOUNDATION_UPLOAD_2026-10-11.json remains the historical upload record;
it is not rewritten to make old hashes appear current.

## Clean-clone rehearsal and upload

1. Start from current main, create the owner's PR branch, and before copying set
   `$nativeRepairBase = (git rev-parse HEAD).Trim()` in that clean clone.
2. Copy the seven files above to their exact destinations. Use the same installed
   test environment as the prior clean-clone rehearsal. Do not copy private state.
3. Package-check line (before committing; no Git writes):

```powershell
python reviewed_upload_check.py --group native_repair --manifest STORAGE_NATIVE_REPAIR_UPLOAD_2026-10-11.json --base $nativeRepairBase
```

Expected UPLOAD_FILES_VERIFIED_REQUIRES_TESTS_AND_CI, blockers []. This checks
the actual HEAD, paths, source hashes and unchanged prerequisites, not CI results.
If a prerequisite changed on main, stop and review it rather than bypassing hashes.

4. Focused-test line (configure the existing local PGlite harness first as in the
   prior SQL rehearsal; otherwise the catalog test is explicitly skipped):

With the already installed clean-clone harness, set its module path first:

```powershell
$env:EQUITY_TEST_PGLITE_MODULE = "$((Get-Location).Path)/tests/sql-harness/node_modules/@electric-sql/pglite"
```

```powershell
python -m pytest -q tests/test_storage_native_conformance.py tests/test_storage_write_guard.py tests/test_reviewed_upload_check.py
```

Expected 140 passed when the SQL harness is configured. Tests are offline and
use synthetic fixtures only. CI must run the full suite, with its existing harness.

5. Upload/commit just this group through one reviewed PR. Merge only after all
   required checks are green; verify checks on the exact merged main SHA too.
   No Streamlit fingerprint update or release-enable change is part of this repair.

## One owner-controlled native rerun

1. GitHub → Actions → **Disposable native storage guard conformance** → Run workflow.
2. Select **main** after the repair merge/checks. Tick the disposable confirmation.
   Do not supply project credentials or change any workflow settings.
3. Run once. A new job provisions its own empty PostgreSQL 17 service; do not
   attempt to reuse a partly populated fixture or run this SQL on Supabase.
4. Expect NATIVE_GUARD_CASES_PASSED, native_cases_executed 6, all six listed
   checks, ledger_archive_races_verified false, global_enforcement_commissioned
   false and approval_authority false. Success proves only these native cases.
5. If blocked, stop. Share the safe receipt's stage, error_category, passed_cases
   and workflow commit/run number. No blind rerun and no copied connection logs.

## Verification scope

Local focused tests: 140 passed; strict type checking on four changed Python files
and recursive public-tree lint pass. Full credential-free public candidate:
2,945 passed, 4 unchanged skips, 2 subtests passed; synthetic app boot included.
Final test-only service-environment isolation also passed the focused run.
Import/preview and final self-review pass. Both early defects were
reproduced without project credentials; the catalog regression is offline.
Native PostgreSQL tools were not found on local PATH, so a successful native
race result is still pending the single owner-run disposable workflow.
Full public-tree suite and final review results are recorded in AUTOMATION_PROGRESS.md.
This repair does not commission storage, widen a safety gate or inspect research data.
