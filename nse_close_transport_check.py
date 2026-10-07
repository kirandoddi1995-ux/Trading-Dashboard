"""Owner-run transport diagnosis only: no credentials, files or capture state."""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from typing import Any

import requests

from nifty_previous_close import LIMIT, source_url


def probe(session: Any, close_date: date) -> dict[str, object]:
    """Mirror the capture's HTTPS GET; report fixed failure codes, never raw errors.

    A successful GET does not validate the CSV or prepare a trading session.
    No retry, alternate source, TLS override or redirect following is permitted.
    """
    result: dict[str, object] = {
        'status': 'BLOCKED', 'close_date': close_date.isoformat(),
        'network_calls': 1, 'writes': 0, 'approval_authority': False,
        'fill_evidence': False, 'session_prepared': False,
    }
    try:
        with session.get(source_url(close_date), timeout=(5, 20), verify=True,
                         allow_redirects=False, stream=True) as response:
            result['http_status'] = response.status_code
            if response.status_code != 200:
                return dict(result, code='NSE_CLOSE_HTTP_NON_200')
            raw = bytearray()
            for block in response.iter_content(65536):
                raw.extend(block)
                if len(raw) > LIMIT:
                    return dict(result, code='NSE_CLOSE_SIZE_LIMIT_EXCEEDED')
            if not raw:
                return dict(result, code='NSE_CLOSE_EMPTY_BODY')
            return dict(result, status='TRANSPORT_CHECK_COMPLETE',
                        bytes_received=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                        payload_validated=False)
    except requests.exceptions.ProxyError:
        code = 'NSE_CLOSE_PROXY_ERROR'
    except requests.exceptions.SSLError:
        code = 'NSE_CLOSE_TLS_ERROR'
    except requests.exceptions.ConnectTimeout:
        code = 'NSE_CLOSE_CONNECT_TIMEOUT'
    except requests.exceptions.ReadTimeout:
        code = 'NSE_CLOSE_READ_TIMEOUT'
    except requests.exceptions.Timeout:
        code = 'NSE_CLOSE_TIMEOUT'
    except requests.exceptions.ConnectionError:
        code = 'NSE_CLOSE_CONNECTION_ERROR'
    except requests.exceptions.RequestException:
        code = 'NSE_CLOSE_REQUEST_ERROR'
    return dict(result, code=code)


def main(argv: list[str] | None = None) -> int:
    """Offline preview by default; --check performs exactly one public-file GET."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--close-date', required=True, help='Exact prior session YYYY-MM-DD')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    try:
        selected = date.fromisoformat(args.close_date)
        if selected.isoformat() != args.close_date:
            raise ValueError('Invalid date format')
    except ValueError:
        print(json.dumps({'status': 'BLOCKED', 'code': 'CLOSE_DATE_INVALID',
                          'network_calls': 0, 'writes': 0}))
        return 2
    if not args.check:
        print(json.dumps({'status': 'PREVIEW', 'close_date': selected.isoformat(),
                          'network_calls': 0, 'writes': 0, 'session_prepared': False}))
        return 0
    try:
        with requests.Session() as session:
            result = probe(session, selected)
    except Exception:
        result = {'status': 'BLOCKED', 'code': 'TRANSPORT_DIAGNOSTIC_UNAVAILABLE',
                  'writes': 0, 'session_prepared': False, 'approval_authority': False,
                  'fill_evidence': False}
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'TRANSPORT_CHECK_COMPLETE' else 2


if __name__ == '__main__':
    raise SystemExit(main())
