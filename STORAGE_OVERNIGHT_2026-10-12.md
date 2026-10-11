# One complete review-only upload: receipt/fence and backup identity foundation

## Outcome and limits

One PR group, based on the owner's green main 0db342b and all five prior uploads.
No hosted SQL, capture installation, release promotion or expectation change is
part of this package. Native PostgreSQL acceptance remains an owner workflow
step; local serial SQL tests are not concurrency proof.

The nine new native cases cover restricted identity, original/idempotent receipt,
conflict, rollback of operation and receipt, direct mutation denial, expired-owner
takeover, competing takeover, blocked old writer and accepted COMMIT with lost
reply. Waits require observed PostgreSQL blocking dependencies, not sleeps alone.
All diagnostics are allowlisted case/category names; raw driver text is withheld.

The SQL is a separate disabled-by-default journal, not a migration/backfill or a
replacement for live equity_operations. Missing control also fails closed. SQL
binds the request and original signature but does not validate HMAC. Historical
authenticity still requires the original key and verifier. Privileged database
owners remain a separate threat; independent anchors/custody are indispensable.
Dedicated caller-owned transactions are required. No automatic retry, invented
absence, reconstructed legacy receipt or implicit acknowledgement is added.
Lease renewal and the live scan completion policy are not implemented here.

The joint backup binding authenticates both witnesses and full-image identity
under one root, but neither exports a consistent image nor writes/verifies an
independent replica. All whole-chain commissioning/deletion flags stay false.

## Exact source → repository destination

Source root: `C:\Users\banga\Desktop\kiran_share_market`.
Every source below is relative to that root. Destination is relative to the clean
clone/repo root. **There are no staged replacements and no special migration step.**
Do not upload the whole working folder. The exact LF-normalized hashes and
unchanged prerequisites are in STORAGE_OVERNIGHT_UPLOAD_2026-10-12.json.

| Source | Destination | Change |
|---|---|---|
| operational_receipt_writer.py | operational_receipt_writer.py | New inactive transaction adapter. |
| recovery_six_binding.py | recovery_six_binding.py | New joint authenticated identity binding. |
| storage_native_operational_conformance.py | storage_native_operational_conformance.py | New nine-case disposable native runner. |
| reviewed_upload_check.py | reviewed_upload_check.py | Add this exact manifest/group, preserving older groups. |
| sql/operational_receipts_review_only.sql | sql/operational_receipts_review_only.sql | New disabled original-receipt/fence journal. Do not run on Supabase. |
| sql/storage_native_operational_fixture_disposable_only.sql | sql/storage_native_operational_fixture_disposable_only.sql | Synthetic fixture, never Supabase. |
| .github/workflows/storage-native-conformance.yml | .github/workflows/storage-native-conformance.yml | Add fixture and nine cases to manual disposable workflow. |
| tests/test_operational_receipt_writer.py | tests/test_operational_receipt_writer.py | Codec, failure, serial SQL and diagnostic tests. |
| tests/test_recovery_six_binding.py | tests/test_recovery_six_binding.py | Mixed-cut, missing-key/artifact and restore-binding tests. |
| tests/test_storage_overnight_upload.py | tests/test_storage_overnight_upload.py | Exact package/prerequisites and CLI selection tests. |
| tests/test_storage_native_ledger_upload.py | tests/test_storage_native_ledger_upload.py | Preserve prior manifest; validate superseded files through the new exact manifest. |
| PROJECT_FOUNDATION_ROADMAP_2026-10-12.md | PROJECT_FOUNDATION_ROADMAP_2026-10-12.md | Sourced storage/product/market/regulatory priorities. |
| STORAGE_OVERNIGHT_2026-10-12.md | STORAGE_OVERNIGHT_2026-10-12.md | This upload and owner runbook. |
| STORAGE_OVERNIGHT_UPLOAD_2026-10-12.json | STORAGE_OVERNIGHT_UPLOAD_2026-10-12.json | Exact-file control manifest; self-hash deliberately null. |
| AUTOMATION_PROGRESS.md | AUTOMATION_PROGRESS.md | Continuity checkpoint, no activation. |
| RUNTIME_PASSWORD_ROTATION_OWNER.md | RUNTIME_PASSWORD_ROTATION_OWNER.md | Include the reviewed local owner procedure; do not assume this held document is already on main. |

## Owner clean-clone rehearsal and upload

1. Use the usual clean **main** clone after confirming latest main checks are
   green. Record its full base SHA **before copying**. Do not use this dirty source
   folder as the upload clone. In PowerShell: `$overnightBase = git rev-parse HEAD`.
2. Copy exactly the sixteen paths above into the matching folders. Preserve
   existing `.github/workflows`, `sql` and `tests` destinations. No private files,
   cache files, data or capture state. Check `git status --short` privately: only
   this allowlist may be changed/new. Some unchanged already-identical paths may
   not appear; all listed files must still exist and match.
3. With the clone's activated Python environment, run this single package check:

   `python reviewed_upload_check.py --group overnight --manifest STORAGE_OVERNIGHT_UPLOAD_2026-10-12.json --base $overnightBase`

   Expect UPLOAD_FILES_VERIFIED_REQUIRES_TESTS_AND_CI, blockers [], hosted_changes 0.
   A prerequisite mismatch means stop and compare public source versions; do not
   bypass it or copy unrelated held drafts. This is not a signature of main.
4. Run the focused line:

   `python -m pytest -q tests/test_operational_receipt_writer.py tests/test_recovery_six_binding.py tests/test_storage_overnight_upload.py tests/test_storage_native_ledger_upload.py tests/test_reviewed_upload_check.py tests/test_operational_receipt_history.py tests/test_terminal_intent_snapshot.py tests/test_recovery_bundle.py tests/test_storage_native_conformance.py tests/test_storage_native_ledger_conformance.py`

   Configure the existing offline PGlite harness as in the prior native package
   before this line. A skipped new SQL test is **not acceptance**. Run the full
   suite/quality gate too, or require all PR CI checks before merging. No secrets
   are needed. Native races run only in the disposable workflow below.
5. Create one reviewed PR containing exactly this group, wait for all quality,
   resilience and CodeQL checks on the exact candidate, then merge. Do not change
   DASHBOARD_RELEASE_ENABLED, Streamlit expectations, tasks or cron jobs.

## Owner native acceptance after the merge

1. Confirm post-merge main checks are green for the exact SHA.
2. GitHub → Actions → **Disposable native storage guard conformance** → Run workflow.
3. Select main. Tick the explicit disposable confirmation. Run once.
4. Expect all three runners green: six capacity, eight ledger/archive and nine
   operational cases. The last result is NATIVE_OPERATIONAL_CASES_PASSED with nine
   passed_cases, hosted_changes 0, inactive_journal_cases_verified true. Global,
   immutable operational and fencing whole-chain flags intentionally remain false.
5. If blocked, retain only the case/category/completed list and exact SHA for
   diagnosis. Do not retry blindly; **never copy fixture SQL into Supabase**.

## Morning security/custody steps — separate from this PR

No credential was read tonight. Follow RUNTIME_PASSWORD_ROTATION_OWNER.md for
the click-by-click role cutover and OWNER_KEYS_AND_BACKUP_RUNBOOK.md for custody.
These reviewed procedures take precedence over the sequencing reminders below.

- Inventory all quant_app_runtime consumers by account and secret **names**:
  collector, Streamlit release app, any local tools and migration/maintenance
  consumers. Do not assume DATABASE_MIGRATION_URL uses the same role.
- Coordinate a brief writer pause with the owner. Keep archives on their separate
  role where confirmed; never change installed capture tasks for this package.
- Generate/save a new runtime password privately; rotate that role through the
  approved owner procedure, update each confirmed consumer, restart/reconnect,
  then one restricted connection check and one supervised admission-checked scan.
  Rotation is not atomic across hosted secret stores. Check for stale pooled
  sessions; old authenticated sessions can remain connected after password change.
  Do not resume recurrence until consumers and delivery checks pass. Do not reset
  postgres or change ledger signing keys as part of runtime-password rotation.
- Back up the current signing key in an encrypted password-manager note outside
  this public project; inventory older key versions without posting values.
- Complete the harmless 7-Zip encrypted external-disk rehearsal and restore/readback
  with a privately stored passphrase. 7-Zip encryption protects confidentiality;
  signed bundle/anchor checks protect identity. They are different requirements.
- Decide whether the recommended Pro budget is acceptable; no purchase/settings
  changes were made. Confirm data-retention/ML rights and broker plan separately.

## Verification record

Measured: focused 318 passed; full suite 3044 passed, 4 unchanged skips and two
subtests passed; separate actual app boot/import 3 passed. Recursive public-tree
pyflakes, strict new-code type checks, imports and offline preview passed.
No new SQL case was skipped in the configured focused run. Native races are NOT
claimed locally verified. Equity fingerprint remains
`03ad7baa68ebaad1f64b1cd3c356455e1c18cb8f23f027652de303b64b4f8478`;
no expectation update is proposed.

Further measured results are recorded in AUTOMATION_PROGRESS.md. Local verification
uses an explicit public-file candidate, without project secrets or held drafts.
The owner still performs the real clean-main Git-base check and disposable native
run. No local claim substitutes for those steps.
