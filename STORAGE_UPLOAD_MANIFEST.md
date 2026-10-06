# Permanent storage working manifest — NOT READY FOR UPLOAD OR COMMISSIONING

This is an interim review inventory, not the final consistent upload package.
Separate Oct 6 capture repair (not part of the permanent-storage commissioning
package): complete replacements are staged_capture_repair/forward_nifty_schedule.py
and staged_capture_repair/nifty_previous_close.py; owner installs/uploads them at
repository ROOT after active tasks stop. Also tests/test_staged_capture_repair.py,
CAPTURE_MORNING_REPAIR_2026-10-06.md and sql/capture_morning_storage_read_only.sql.
The regression test falls back to uploaded root files when staging is absent.
See the repair runbook for offline checks and the no-after-open-preparation rule.
Do not upload/apply this as if it solves storage: production readers/writers,
atomic archive/source deletion, transaction admission/alerts and daily reporting
are not integrated. Keep the derivative pilot held. No hosted writes were made.

Workspace root: `C:\Users\banga\Desktop\kiran_share_market`.

## Root files (same folder as app.py)

- `ledger_segments.py` — original-event signature/chain verification, bounded sealed segments.
- `cold_catalog.py` — immutable paged lookup, verified absence, content-addressed roots.
- `ledger_cold_store.py` — segment preparation, cold identity lookup, cold/hot reconstruction.
- `catalog_receipts.py` — signed generations, predecessor receipt/root binding, explicit rotation.
- `ledger_archive_publication.py` — injected private-object upload/readback, original-row/locator verification.
- `ledger_archive_repository.py` — bounded exact-source deletion and root CAS in one transaction.
- `cold_drive_objects.py` — private content-addressed Drive transport; separate GET-only reader, bounded verified creation.
- `production_repository.py` — legacy DDL protection; optional verified cold-aware append, events, audit, training/readiness and pending-outcome readers.
- `ledger_runtime_reader.py` — consistent snapshots, original cold/hot history, append preparation and protected locked proof checking.
- `ledger_storage_access.py` — bounded legacy snapshots; archived generations require a cold reader, never hot-only fallback.
- `ledger_recovery.py` — trusted original-source witnesses and hot/cold original recovery comparison.
- `local_ledger_recovery.py` — unreferenced bounded SELECT-only local original/outbox recovery check; independent remote request receipts, no envelope splicing.
- `recovery_drill.py` — explicit target-bound original verification; rejects missing expectations, unsafe roles and source aliases.
- `equity_runtime_health.py` — release fingerprint covers the reader and its imported storage verification modules.
- `storage_policy.py` — 45 relation budgets, including protected hot heads, and fresh allocation admission policy.
- `release_verification.py` — bounded Windows cleanup retries, preserving hard timeout failure.
- `mypy-automation.ini` — strict type checking includes eleven new storage core modules.
- `PERMANENT_STORAGE_DESIGN.md` — sourced decisions, evidence and unfinished acceptance order.
- `AUTOMATION_PROGRESS.md` — continuity, exact test results and remaining work.
- `STORAGE_UPLOAD_MANIFEST.md` — this working inventory.
- `STORAGE_FIRST_RELIEF.md` — owner-only existing NAV archive relief and capture-hour source freeze; no runtime upload required.

## tests/ (NOT repository root)

- `tests/test_ledger_segments.py`
- `tests/test_ledger_segments_sql.py`
- `tests/test_cold_catalog.py`
- `tests/test_ledger_cold_store.py`
- `tests/test_catalog_receipts.py`
- `tests/test_storage_policy.py`
- `tests/test_release_packaging.py`
- `tests/test_catalog_roots_sql.py`
- `tests/test_ledger_archive_guards_sql.py`
- `tests/test_ledger_archive_publication.py`
- `tests/test_ledger_archive_repository_sql.py`
- `tests/test_cold_drive_objects.py`
- `tests/test_storage_legacy_migration.py`
- `tests/test_ledger_hot_heads_sql.py`
- `tests/test_ledger_runtime_reader_sql.py`
- `tests/test_archive_maintenance_sql.py` — positional SQL harness rows and lossless PostgreSQL timestamp transport.
- `tests/test_ledger_storage_access_sql.py`
- `tests/test_ledger_recovery_sql.py`
- `tests/test_local_ledger_recovery.py`
- `tests/test_equity_delivery_repository.py` — legacy sender fixture includes protected-storage admission metadata.

## SQL folders (review only)

- `sql/permanent_storage_inventory_read_only.sql` — exact read-only hosted diagnostic queries.
- `sql/storage_first_relief_read_only.sql` — separate owner-run size, latest NAV fingerprint and one-time eligibility checks.
- `supabase/migrations/20261005194922_permanent_storage_control_review_only.sql` —
  CLI-generated bounded root metadata draft; no bootstrap or ledger DELETE grant.
- `supabase/migrations/20261005200414_permanent_storage_ledger_review_only.sql` —
  CLI-generated disabled ledger-pruning draft, exact-row guards and deferred atomic commit checks.
- `supabase/migrations/20261005210149_permanent_storage_heads_review_only.sql` —
  CLI-generated protected hot terminals, disabled tracking, primitive temporary-stage guards and atomic retirement.

46 files so far. No app.py, workflows or secret settings changed in this interim
group. ProductionRepository imports the cold reader and can route events through
an injected commissioned reader; the live factory is NOT configured for it yet.
Cold-aware append is integrated for an explicitly injected reader/fingerprint;
Global audit, training/readiness and pending-observation joins can now use verified
cold originals through the injected reader. Live factories and recovery remain
unfinished. Large-history bounded spooling/streaming is not commissioned.
Current LOCAL decision fingerprint:
`6a234dc090b83614a31d1b08227802b23f845f68e6c82df1e590b92be9c42263`.
Do not change the live expected fingerprint for this unfinished group. The last
reviewed live expectation remains f7ff707c...30ae until a complete package is ready.

Exclude CLI `supabase/.temp/`, Python caches, all private market/research files,
credentials, .venv and temporary SQL harness output. Existing previously released
emergency fixes are not duplicated in this new manifest.

The final package and numbered owner steps will replace this interim status only
after local integration/restore/guard/reader tests pass. Hosted acceptance and
measured steady state remain separate owner commissioning evidence.

Current milestone:2102 passed,4 unchanged skips,2 subtests passed in453.74s;
full offline app boot included. Scoped local originals/equity-outbox recovery
checks are locally verified; private factory/remote verified-lookup wiring and
whole-application recovery remain unfinished. New local module is not imported
by live app/capture; local fingerprint is unchanged.
Root/direct-test pyflakes clean; strict30 storage/automation core modules clean.
Original-ledger DR verification is not whole-application recovery. CLI --verify
now fails closed without a trusted witness and configured target reader; owner
factory/credential wiring is still unfinished, not a commissioning request.

Exception to the no-upload/no-commissioning instruction:STORAGE_FIRST_RELIEF.md
and sql/storage_first_relief_read_only.sql are a standalone owner-use guide for
the ALREADY RELEASED NAV archive workflow. They require no runtime upload or new
migration. Do not upload the other44 files to perform the owner NAV relief.
