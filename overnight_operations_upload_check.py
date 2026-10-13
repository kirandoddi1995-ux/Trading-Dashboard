"""Exact reviewed operations upload; capture base before copying, no Git writes."""
from overnight_upload_check import main

FILES = (
    'overnight_operations_alerts.py',
    'overnight_operations_inputs.py',
    'overnight_operations_watch.py',
    'tests/test_overnight_operations_alerts.py',
    'tests/test_overnight_operations_inputs.py',
    'tests/test_overnight_operations_watch.py',
    'OVERNIGHT_OPERATIONS_2026-10-13.md',
    'overnight_operations_upload_check.py',
    'OVERNIGHT_OPERATIONS_UPLOAD_2026-10-13.json',
    'overnight_history_admission.py',
    'tests/test_overnight_history_admission.py',
)

if __name__ == '__main__':
    raise SystemExit(main('operations', FILES))
