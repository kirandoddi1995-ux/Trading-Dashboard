"""Exact reviewed storage upload; capture base before copying, no Git writes."""
from overnight_upload_check import main

FILES = (
    'overnight_upload_check.py',
    'tests/test_overnight_upload_check.py',
    'OVERNIGHT_PIN_REPAIR_2026-10-13.md',
    'overnight_storage_cold_methods.py',
    'overnight_storage_contracts.py',
    'overnight_storage_factory_adapter.py',
    'overnight_storage_harness.py',
    'overnight_storage_journal.py',
    'overnight_storage_materialization.py',
    'overnight_storage_native_acceptance.py',
    'overnight_storage_repository_routes.py',
    'overnight_storage_sources.py',
    'overnight_storage_staged_factories.py',
    'overnight_storage_switching.py',
    'tests/test_overnight_storage_cold_methods.py',
    'tests/test_overnight_storage_contracts.py',
    'tests/test_overnight_storage_custody_binding.py',
    'tests/test_overnight_storage_journal.py',
    'tests/test_overnight_storage_materialization.py',
    'tests/test_overnight_storage_native_acceptance.py',
    'tests/test_overnight_storage_repository_routes.py',
    'tests/test_overnight_storage_sources.py',
    'tests/test_overnight_storage_staged_factories.py',
    'tests/test_overnight_storage_switching.py',
    'overnight_storage_universe.py',
    'tests/test_overnight_storage_universe.py',
    'OVERNIGHT_STORAGE_2026-10-13.md',
    'overnight_storage_upload_check.py',
    'OVERNIGHT_STORAGE_UPLOAD_2026-10-13.json',
    'overnight_storage_native_fixture.sql',
    '.github/workflows/overnight-storage-native.yml',
)

if __name__ == '__main__':
    raise SystemExit(main('storage', FILES))
