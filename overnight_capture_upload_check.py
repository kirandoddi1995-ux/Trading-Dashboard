"""Exact reviewed capture upload; capture base before copying, no Git writes."""
from overnight_upload_check import main

FILES = (
    'overnight_capture_audit.py',
    'overnight_capture_calendar.py',
    'overnight_capture_planning.py',
    'tests/test_overnight_capture_audit.py',
    'tests/test_overnight_capture_planning.py',
    'OVERNIGHT_CAPTURE_2026-10-13.md',
    'overnight_capture_upload_check.py',
    'OVERNIGHT_CAPTURE_UPLOAD_2026-10-13.json',
    'overnight_upload_check.py',
    'tests/test_overnight_upload_check.py',
    'OVERNIGHT_PROGRAMME_2026-10-13.md',
    'OVERNIGHT_UPLOAD_ORDER_2026-10-13.md',
)

if __name__ == '__main__':
    raise SystemExit(main('capture', FILES))
