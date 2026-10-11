# Native ledger/archive acceptance — one complete upload

## Decision and boundary

The owner reports the original six native capacity-guard cases passed on main
`affeb07`. This package adds the next coherent proof: native archive transactions
against the **actual three reviewed migrations**, original archive repository,
signed synthetic segment/catalog publication, and cold-aware runtime reader.
It does not install anything on Supabase or commission any live writer.

No existing production migration, ledger implementation, installed capture, secrets,
research input, release hold or expectation is changed. The shared disposable
connector now accepts only three fixed restricted fixture identities; its default
capacity-guard identity is unchanged. PostgreSQL must be version 17, genuinely
native (positive backend PID), on fixed loopback, in the correctly named/marked
database, without privileged roles or inherited membership. Service environment
discovery is refused. Public synthetic passwords are not project credentials.

## What the eight new cases prove

1. Restricted native identities, distinct backends, fresh empty fixture and
   read-only protected-head/source-update privileges.
2. Deleting a staged prefix without advancing its root fails deferred checks;
   source, protected head and root survive rollback.
3. Two `relations` root compare-and-swap transactions serialize; only one advances.
4. An append holding the shared root fence blocks archival until commit; archival
   preserves the new hot tail and the reader reconstructs all signed originals.
5. Archival holding the root update fence blocks an append prepared against the
   old root; that stale proof is rejected. A newly prepared cold-frontier append
   succeeds without resetting sequence or predecessor hash.
6. Two archivers proposing the same captured source/root serialize: one commits,
   the other independently reconciles as `ALREADY_COMMITTED`, not another deletion.
7. Injecting a lost reply **after an actual database COMMIT** returns an unknown
   result, not success. A fresh read verifies root/source; reconciliation performs
   no second deletion and original cold history remains readable.
8. Injecting failure **before COMMIT** leaves source/root unchanged; a separately
   verified transaction can then commit normally.

Concurrent cases observe `pg_blocking_pids` for the exact holder and waiter before
releasing the holder. Sleeping briefly is only polling; elapsed time is not proof.
The actual archive/append lock timeout is unchanged. Missing blocking evidence
fails the run; holder rollback and waiter cancellation precede worker cleanup.
No retries hide failures. Cleanup failures also fail closed.

In-memory immutable objects exercise the real signed codecs and readback, **not
Drive custody**. COMMIT fault injection is not arbitrary TCP/network chaos. The
`relations` CAS case does not claim to test a source-specific retention policy.
Immutable operational receipt writes, fencing takeover and native full recovery
are still unverified. Therefore even a successful run deliberately retains
`ledger_archive_races_verified: false`, `global_enforcement_commissioned: false`,
and `approval_authority: false`; it adds only
`tested_archive_transactions_verified: true` for the eight named cases.

## Consolidated source → destination list

Source root: `C:\Users\banga\Desktop\kiran_share_market`.
Every source below maps to the **same relative destination** in the clean clone.
No staged files, private files or special installation steps are included.
The archive repository and three SQL drafts were not present in the frozen public
candidate, so they are explicitly included rather than assumed to be on main.
They stay inactive/review-only; adding them is not permission to migrate Supabase.

| Source relative to source root | Destination in clean clone | Change |
| --- | --- | --- |
| storage_native_conformance.py | storage_native_conformance.py | Fixed restricted-role connector/profile extension |
| storage_native_ledger_conformance.py | storage_native_ledger_conformance.py | Eight real native transaction cases; safe diagnostics |
| ledger_archive_repository.py | ledger_archive_repository.py | Existing local archive adapter, now included for isolated acceptance; no live wiring |
| supabase/migrations/20261005194922_permanent_storage_control_review_only.sql | supabase/migrations/20261005194922_permanent_storage_control_review_only.sql | Existing review-only root controls; disposable execution only |
| supabase/migrations/20261005200414_permanent_storage_ledger_review_only.sql | supabase/migrations/20261005200414_permanent_storage_ledger_review_only.sql | Existing review-only deletion/root atomicity; disposable execution only |
| supabase/migrations/20261005210149_permanent_storage_heads_review_only.sql | supabase/migrations/20261005210149_permanent_storage_heads_review_only.sql | Existing review-only protected-head/root fencing; disposable execution only |
| reviewed_upload_check.py | reviewed_upload_check.py | Exact new manifest/group allowlist |
| .github/workflows/storage-native-conformance.yml | .github/workflows/storage-native-conformance.yml | Adds isolated ledger fixture/case steps after existing guard cases |
| sql/storage_native_ledger_fixture_disposable_only.sql | sql/storage_native_ledger_fixture_disposable_only.sql | Fresh synthetic schema, actual migration includes, fixture-only commissioning |
| tests/test_storage_native_ledger_conformance.py | tests/test_storage_native_ledger_conformance.py | Offline boundaries, cleanup, signatures and real serial SQL |
| tests/test_storage_native_ledger_upload.py | tests/test_storage_native_ledger_upload.py | Exact package/prerequisite checks |
| tests/test_reviewed_upload_check.py | tests/test_reviewed_upload_check.py | New manifest path regression |
| STORAGE_NATIVE_LEDGER_2026-10-11.md | STORAGE_NATIVE_LEDGER_2026-10-11.md | This runbook and proof limits |
| STORAGE_NATIVE_LEDGER_UPLOAD_2026-10-11.json | STORAGE_NATIVE_LEDGER_UPLOAD_2026-10-11.json | LF-normalized hashes and unchanged source dependencies |
| AUTOMATION_PROGRESS.md | AUTOMATION_PROGRESS.md | Owner result and continuity checkpoint |

Historical manifests remain historical. Do not copy their stale file hashes into
the new package. The new manifest hashes the supplied migrations and pins existing runtime
dependencies as prerequisites; a mismatch means STOP and review the exact main
tree, never edit a hash merely to make the checker pass.

## Owner upload and verification

1. Start the usual clean clone on current green `main`. Before copying, capture
   its actual full SHA with `$ledgerBase=(git rev-parse HEAD).Trim()`. Create the
   review branch by your normal routine. Do not assume an abbreviated SHA.
2. Copy only the fifteen paths in the table, keeping `tests/`, `sql/`, `supabase/migrations/` and
   `.github/workflows/` destinations intact. Do not copy the whole source folder.
3. From the clean clone root, run the package check:

```powershell
python reviewed_upload_check.py --group native_ledger --manifest STORAGE_NATIVE_LEDGER_UPLOAD_2026-10-11.json --base $ledgerBase
```

Expected: `UPLOAD_FILES_VERIFIED_REQUIRES_TESTS_AND_CI`, blockers empty. This is a
file/tree check, not a native test result or commissioning authority.

4. Configure the existing offline PGlite harness by your established routine (it
   must be configured so the SQL tests below actually run), then focused tests:

```powershell
python -m pytest -q tests/test_storage_native_ledger_conformance.py tests/test_storage_native_ledger_upload.py tests/test_storage_native_conformance.py tests/test_reviewed_upload_check.py tests/test_ledger_archive_publication.py tests/test_ledger_cold_store.py
```

No SQL skips are an acceptance result. Tests without PGlite still test offline
boundaries, but explicitly skip serial SQL; report that rather than claiming proof.

5. Upload/review the **one complete group** through a PR. Wait for quality,
   resilience and CodeQL on the exact merged main SHA. Leave release hold,
   expectations, collectors and installed capture unchanged.
6. GitHub → Actions → **Disposable native storage guard conformance** → Run
   workflow → select `main` → tick `confirm_disposable` → Run workflow once.
   The original guard step must pass six cases, then the new ledger step must
   report `NATIVE_LEDGER_CASES_PASSED`, eight cases, hosted changes 0 and the
   uncommissioned flags listed above. Record the exact run SHA and JSON output.
7. If either step fails, stop. Share the failing case/stage, safe category and
   completed-case names only. Do not retry blindly, run either fixture on
   Supabase, reuse live credentials, or turn any gate off.

This workflow has only explicit manual dispatch, contents-read permission,
unchanged concurrency, no project secrets/artifacts, and a disposable PostgreSQL
service. It never dispatches collection or releases the app.

## Local verification and remaining chain

Focused suite: **127 passed**. Full credential-free public candidate:
**2,971 passed, four unchanged skips, two subtests passed** in 291.37 seconds;
26 tests added, none removed. Synthetic app boot, recursive pyflakes, strict mypy
on seven Python files, imports and zero-I/O preview passed. Final self-review fixed
the four missing public-package dependencies and the test adapter's dependence
on held local harness methods. No further actionable issue found. Package and
prerequisite hashes verified; the owner's actual Git-base/merged-SHA checks remain
separate. Historical held workspace tests are not claimed as public acceptance.

Public candidate equity fingerprint unchanged:
`03ad7baa68ebaad1f64b1cd3c356455e1c18cb8f23f027652de303b64b4f8478`.
Do not change Streamlit expectations or release hold for this package.

Docker is installed
but its Linux engine is not running; no native PostgreSQL binaries are on PATH.
Native concurrency acceptance therefore remains the single owner workflow above.
Serial SQL in PGlite is deliberately not reported as native race acceptance.
Do not run `supabase db push` or apply the new review-only migration files to a
hosted database. Their only execution authorized by this package is inside the
fresh disposable workflow service.

Next: immutable operational receipt/fencing transactions with native acceptance;
authenticated six-table/full-image independent custody; then complete guarded
writer/cold-recovery factory wiring. Only after those proofs should source-specific
normalization/retention and deletion be commissioned. Independent capacity-alert
delivery remains an owner gate. Key note/encrypted external-disk rehearsal and
the previously prepared runtime-password rotation are still pending; this package
does not perform them or reduce their importance.

Design references: PostgreSQL [explicit locking](https://www.postgresql.org/docs/17/explicit-locking.html)
and [transaction isolation](https://www.postgresql.org/docs/17/transaction-iso.html).
Root-before-aggregate locks and stale-proof rechecks test the existing design;
they do not introduce a weaker live policy.
