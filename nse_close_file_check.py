"""Offline structure check of an owner-selected official CSV; never prepare capture."""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path

from nifty_previous_close import LIMIT, parse_close, previous_session
from research_integrity import IntegrityError


def check_file(path: Path, session_date: date) -> dict[str, object]:
    """Read one bounded private file and validate its exact prior-session close.

    File bytes/date/schema checks cannot establish the file's origin or original
    retrieval time. The returned hash is not a production provenance record.
    """
    if str(path).startswith(('\\\\', '//')):
        raise IntegrityError('LOCAL_PRIVATE_FILE_REQUIRED')
    resolved = path.resolve()
    if resolved.is_relative_to(Path(__file__).resolve().parent):
        raise IntegrityError('SOURCE_OUTSIDE_CODE_FOLDER_REQUIRED')
    expected = previous_session(session_date)
    with resolved.open('rb') as source:
        raw = source.read(LIMIT + 1)
    parse_close(raw, expected)
    return {
        'status': 'FILE_STRUCTURE_CHECK_PASSED',
        'session_date': session_date.isoformat(), 'expected_close_date': expected.isoformat(),
        'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
        'source_authenticity': 'NOT_ESTABLISHED_BY_TOOL',
        'retrieval_time': 'NOT_ESTABLISHED_BY_TOOL',
        'network_calls': 0, 'writes': 0, 'session_prepared': False,
        'approval_authority': False, 'fill_evidence': False,
    }


def main(argv: list[str] | None = None) -> int:
    """Preview without file access unless --check; redact all paths and values."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session-date', required=True, help='Target session YYYY-MM-DD')
    parser.add_argument('--file', required=True, type=Path, help='One private local CSV')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    try:
        selected = date.fromisoformat(args.session_date)
        if selected.isoformat() != args.session_date:
            raise ValueError('Invalid date format')
    except ValueError:
        print(json.dumps({'status': 'BLOCKED', 'code': 'SESSION_DATE_INVALID',
                          'network_calls': 0, 'writes': 0, 'file_reads': 0}))
        return 2
    if not args.check:
        print(json.dumps({'status': 'PREVIEW', 'session_date': selected.isoformat(),
                          'network_calls': 0, 'writes': 0, 'file_reads': 0,
                          'session_prepared': False}))
        return 0
    try:
        result = check_file(args.file, selected)
    except Exception as error:
        allowed = {
            'LOCAL_PRIVATE_FILE_REQUIRED', 'SOURCE_OUTSIDE_CODE_FOLDER_REQUIRED',
            'REGULAR_SESSION_REQUIRED', 'PREVIOUS_SESSION_UNVERIFIED',
            'NSE_CLOSE_SIZE_INVALID', 'NSE_CLOSE_SCHEMA_INVALID', 'NSE_CLOSE_ROW_INVALID',
            'NSE_CLOSE_DATE_MISMATCH', 'NSE_CLOSE_PRICE_INVALID',
            'NSE_CLOSE_UNIQUE_INDEX_REQUIRED', 'NSE_CLOSE_INVALID',
        }
        code = (str(error) if isinstance(error, IntegrityError) and str(error) in allowed
                else 'FILE_CHECK_UNAVAILABLE')
        result = {'status': 'BLOCKED', 'code': code, 'network_calls': 0, 'writes': 0,
                  'session_prepared': False, 'approval_authority': False, 'fill_evidence': False}
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'FILE_STRUCTURE_CHECK_PASSED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
