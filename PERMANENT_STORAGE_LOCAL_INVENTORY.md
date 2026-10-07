# Local storage work inventory — pinned to main 62508fd

Workspace: C:\Users\banga\Desktop\kiran_share_market.
Public main baseline: 62508fd50f6d1e363afabc8961857c98afcd5c05, confirmed through the read-only GitHub
connector on Oct 7. The complete public tree was not truncated. All 18 expected
files from the previous source package are present. A PR's 17 changed-file count
is not a missing-file diagnosis.

The executable inventory inspects root Python/configuration files, tests/test_*.py,
sql/*.sql and supabase/migrations/*.sql only. It compares actual Git blob bytes,
separates CRLF/LF-only differences, and does not import the inspected modules.
The baseline stores only public source paths/blob hashes: no market files or
credentials. This is NOT a recursive inventory of the PC or every project file.
Documents, workflows, scripts, generated caches and other folders need separate
explicit review. No private research dataset, signing material or hosted row was
read by this inventory. No file was deleted or moved.

Initial source scan found 51 differing/new artifacts, including the new
inventory tool/test. Matching-main files are omitted, not declared obsolete.
The exact current hashes/statuses can be reproduced with:

```powershell
.venv/Scripts/python.exe storage_package_inventory.py
```

The baseline is deliberately pinned, not automatically refreshed. After a merge,
review a new public exact-SHA tree snapshot before reclassifying files; never
rewrite the baseline to make omitted companions appear safe. Hashes establish
source identity, not operational approval or external market truth.

Stages below describe intended development work, not automatic upload groups.
Use PERMANENT_STORAGE_PACKAGES.md for the actual first package and gate order.
Only the eight pure P1 source/test files listed there join the first upload;
P1's SQL test remains held with its migration dependencies.

## P0_INVENTORY (2)

- [storage_package_inventory.py](C:/Users/banga/Desktop/kiran_share_market/storage_package_inventory.py) — LOCAL_ONLY.
- [tests/test_storage_package_inventory.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_storage_package_inventory.py) — LOCAL_ONLY.

## P1_ORIGINALS_CATALOG (9)

- [catalog_receipts.py](C:/Users/banga/Desktop/kiran_share_market/catalog_receipts.py) — LOCAL_ONLY.
- [cold_catalog.py](C:/Users/banga/Desktop/kiran_share_market/cold_catalog.py) — LOCAL_ONLY.
- [ledger_cold_store.py](C:/Users/banga/Desktop/kiran_share_market/ledger_cold_store.py) — LOCAL_ONLY.
- [ledger_segments.py](C:/Users/banga/Desktop/kiran_share_market/ledger_segments.py) — LOCAL_ONLY.
- [tests/test_catalog_receipts.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_catalog_receipts.py) — LOCAL_ONLY.
- [tests/test_cold_catalog.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_cold_catalog.py) — LOCAL_ONLY.
- [tests/test_ledger_cold_store.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_ledger_cold_store.py) — LOCAL_ONLY.
- [tests/test_ledger_segments.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_ledger_segments.py) — LOCAL_ONLY.
- [tests/test_ledger_segments_sql.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_ledger_segments_sql.py) — LOCAL_ONLY.

## P2_RECOVERY (5)

- [ledger_recovery.py](C:/Users/banga/Desktop/kiran_share_market/ledger_recovery.py) — LOCAL_ONLY.
- [local_ledger_recovery.py](C:/Users/banga/Desktop/kiran_share_market/local_ledger_recovery.py) — LOCAL_ONLY.
- [recovery_drill.py](C:/Users/banga/Desktop/kiran_share_market/recovery_drill.py) — MODIFIED_FROM_MAIN.
- [tests/test_ledger_recovery_sql.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_ledger_recovery_sql.py) — LOCAL_ONLY.
- [tests/test_local_ledger_recovery.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_local_ledger_recovery.py) — LOCAL_ONLY.

## P3_READERS_WRITERS (7)

- [equity_runtime_health.py](C:/Users/banga/Desktop/kiran_share_market/equity_runtime_health.py) — MODIFIED_FROM_MAIN.
- [ledger_runtime_reader.py](C:/Users/banga/Desktop/kiran_share_market/ledger_runtime_reader.py) — LOCAL_ONLY.
- [ledger_storage_access.py](C:/Users/banga/Desktop/kiran_share_market/ledger_storage_access.py) — LOCAL_ONLY.
- [production_repository.py](C:/Users/banga/Desktop/kiran_share_market/production_repository.py) — MODIFIED_FROM_MAIN.
- [tests/test_equity_delivery_repository.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_equity_delivery_repository.py) — MODIFIED_FROM_MAIN.
- [tests/test_ledger_runtime_reader_sql.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_ledger_runtime_reader_sql.py) — LOCAL_ONLY.
- [tests/test_ledger_storage_access_sql.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_ledger_storage_access_sql.py) — LOCAL_ONLY.

## P4_ARCHIVE_COMMISSIONING (10)

- [cold_drive_objects.py](C:/Users/banga/Desktop/kiran_share_market/cold_drive_objects.py) — LOCAL_ONLY.
- [ledger_archive_publication.py](C:/Users/banga/Desktop/kiran_share_market/ledger_archive_publication.py) — LOCAL_ONLY.
- [ledger_archive_repository.py](C:/Users/banga/Desktop/kiran_share_market/ledger_archive_repository.py) — LOCAL_ONLY.
- [tests/test_catalog_roots_sql.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_catalog_roots_sql.py) — LOCAL_ONLY.
- [tests/test_cold_drive_objects.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_cold_drive_objects.py) — LOCAL_ONLY.
- [tests/test_ledger_archive_guards_sql.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_ledger_archive_guards_sql.py) — LOCAL_ONLY.
- [tests/test_ledger_archive_publication.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_ledger_archive_publication.py) — LOCAL_ONLY.
- [tests/test_ledger_archive_repository_sql.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_ledger_archive_repository_sql.py) — LOCAL_ONLY.
- [tests/test_ledger_hot_heads_sql.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_ledger_hot_heads_sql.py) — LOCAL_ONLY.
- [tests/test_storage_legacy_migration.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_storage_legacy_migration.py) — LOCAL_ONLY.

## P4_REVIEW_SQL_HOLD (3)

- [supabase/migrations/20261005194922_permanent_storage_control_review_only.sql](C:/Users/banga/Desktop/kiran_share_market/supabase/migrations/20261005194922_permanent_storage_control_review_only.sql) — LOCAL_ONLY.
- [supabase/migrations/20261005200414_permanent_storage_ledger_review_only.sql](C:/Users/banga/Desktop/kiran_share_market/supabase/migrations/20261005200414_permanent_storage_ledger_review_only.sql) — LOCAL_ONLY.
- [supabase/migrations/20261005210149_permanent_storage_heads_review_only.sql](C:/Users/banga/Desktop/kiran_share_market/supabase/migrations/20261005210149_permanent_storage_heads_review_only.sql) — LOCAL_ONLY.

## P5_UNIVERSE_NONLEDGER (1)

- [tests/test_archive_maintenance_sql.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_archive_maintenance_sql.py) — MODIFIED_FROM_MAIN.

## PACKAGING_SUPPORT (3)

- [mypy-automation.ini](C:/Users/banga/Desktop/kiran_share_market/mypy-automation.ini) — MODIFIED_FROM_MAIN.
- [release_verification.py](C:/Users/banga/Desktop/kiran_share_market/release_verification.py) — MODIFIED_FROM_MAIN.
- [tests/test_release_packaging.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_release_packaging.py) — MODIFIED_FROM_MAIN.

## SEPARATE_RESEARCH_REVIEW (4)

- [equity_research_observations.py](C:/Users/banga/Desktop/kiran_share_market/equity_research_observations.py) — MODIFIED_FROM_MAIN.
- [tests/test_equity_research_isolation.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_equity_research_isolation.py) — LOCAL_ONLY.
- [tests/test_equity_research_observations.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_equity_research_observations.py) — MODIFIED_FROM_MAIN.
- [tests/test_equity_research_outcomes.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_equity_research_outcomes.py) — LOCAL_ONLY.

## HISTORICAL_CAPTURE_HELPER (2)

- [prepare_capture_repair.py](C:/Users/banga/Desktop/kiran_share_market/prepare_capture_repair.py) — LOCAL_ONLY.
- [tests/test_prepare_capture_repair.py](C:/Users/banga/Desktop/kiran_share_market/tests/test_prepare_capture_repair.py) — LOCAL_ONLY.

## HISTORICAL_READONLY_DIAGNOSTICS (5)

- [sql/collector_trial_acceptance_read_only.sql](C:/Users/banga/Desktop/kiran_share_market/sql/collector_trial_acceptance_read_only.sql) — LOCAL_ONLY.
- [sql/nav_compaction_review_read_only.sql](C:/Users/banga/Desktop/kiran_share_market/sql/nav_compaction_review_read_only.sql) — LOCAL_ONLY.
- [sql/positions_storage_audit_readonly.sql](C:/Users/banga/Desktop/kiran_share_market/sql/positions_storage_audit_readonly.sql) — LOCAL_ONLY.
- [sql/post_nav_restart_read_only.sql](C:/Users/banga/Desktop/kiran_share_market/sql/post_nav_restart_read_only.sql) — LOCAL_ONLY.
- [sql/storage_capture_restart_read_only.sql](C:/Users/banga/Desktop/kiran_share_market/sql/storage_capture_restart_read_only.sql) — LOCAL_ONLY.

## Preserve but do not use as the current upload authority

- STORAGE_UPLOAD_MANIFEST.md: historical interim 46-file inventory. Its old
  local/live hashes and "upload group" count are superseded. Preserve as history;
  do not sweep its list into main.
- STORAGE_SOURCE_UPLOAD_2026-10-07.md: the previous 18-file group is now installed
  on main. It is not a manifest for the unfinished ledger package.
- prepare_capture_repair.py and its test: helper pinned to old 092b181 and earlier
  replacement hashes. Superseded for the current 62508fd capture installation;
  do NOT run it against main or the installed capture folder.
- staged_capture_repair/: optional historical/parity companion, not a runtime
  module folder to upload or install. Current installed root files are owner-confirmed.
- Three *_review_only.sql migrations: retained design/test fixtures, not obsolete,
  not ready to apply and not part of the first PR.
- PERMANENT_STORAGE_DESIGN.md remains component-design history; current gate order
  is PERMANENT_STORAGE_ROLLOUT.md and PERMANENT_STORAGE_PACKAGES.md.

No automatic obsolescence decision is made for local-only research changes,
modified release packaging/type configuration, or read-only SQL from earlier
incidents. Review them separately. Do not discard test coverage to make a package
pass; avoid including tests whose required code/SQL is not in the reviewed package.

Hidden .test-*, .tmp-*, caches, .venv, public verification checkouts, SQL harness
node_modules, .streamlit and nifty-quality-* folders are excluded from the scan.
They may contain private artifacts or old test output: no cleanup/removal is
recommended here. Documents\TradingResearch is outside scope and stays private.

