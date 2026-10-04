"""Supervised development-only expired NIFTY futures probe; no import-time I/O."""
import argparse
from datetime import date, datetime, timezone
import getpass
import gzip
import json
from pathlib import Path
import re
import time
from urllib.parse import quote

import requests

from download_nifty_history import (HistoryError, candles, check_session, encoded,
                                    immutable, sha)

BASE = 'https://api.upstox.com/v2/expired-instruments'
KEY = 'NSE_INDEX|Nifty 50'
MAX_RESPONSE = 8 * 1024 * 1024


def development_range(start, end, expiry):
    if not (date(2022, 1, 1) <= start <= end <= expiry <= date(2024, 12, 31)):
        raise HistoryError('DEVELOPMENT_ONLY_2025_2026_FROZEN')
    if start.year != end.year or start.month != end.month:
        raise HistoryError('SINGLE_MONTH_REQUEST_REQUIRED')


class Reader:
    def __init__(self, token, session, sleep=time.sleep):
        if not isinstance(token, str) or not token or any(c.isspace() for c in token):
            raise HistoryError('AUTH_REQUIRED')
        self.token, self.session, self.sleep = token, session, sleep

    def _get(self, path, params=None):
        for attempt in range(3):
            try:
                with self.session.get(BASE + path, params=params,
                        headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/json'},
                        verify=True, allow_redirects=False, timeout=(5, 30), stream=True) as response:
                    if response.status_code in (401, 403):
                        raise HistoryError('AUTH_OR_PLUS_ENTITLEMENT_REQUIRED')
                    if response.status_code == 429 or 500 <= response.status_code < 600:
                        if attempt == 2:
                            raise HistoryError('RETRIES_EXHAUSTED')
                        self.sleep(2 ** attempt)
                        continue
                    if response.status_code != 200:
                        raise HistoryError('HTTP_REJECTED_CHECK_ENTITLEMENT_OR_HISTORY')
                    raw = bytearray()
                    for chunk in response.iter_content(65536):
                        raw.extend(chunk)
                        if len(raw) > MAX_RESPONSE:
                            raise HistoryError('RESPONSE_TOO_LARGE')
                    try:
                        body = json.loads(raw)
                    except (TypeError, ValueError):
                        raise HistoryError('INVALID_JSON') from None
                    if not isinstance(body, dict) or body.get('status') != 'success':
                        raise HistoryError('PROVIDER_REJECTED_CHECK_ENTITLEMENT_OR_HISTORY')
                    return body
            except requests.RequestException:
                if attempt == 2:
                    raise HistoryError('TRANSPORT_FAILED') from None
                self.sleep(2 ** attempt)
        raise HistoryError('RETRIES_EXHAUSTED')

    def probe(self, start, end, expiry):
        development_range(start, end, expiry)
        body = self._get('/future/contract', {'instrument_key': KEY, 'expiry_date': str(expiry)})
        data = body.get('data')
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
            raise HistoryError('CONTRACT_MISSING_OR_AMBIGUOUS')
        contract = data[0]
        key = contract.get('instrument_key')
        if (contract.get('underlying_key') != KEY or contract.get('instrument_type') != 'FUT'
                or contract.get('exchange') != 'NSE' or contract.get('segment') != 'NSE_FO'
                or contract.get('expiry') != str(expiry) or not isinstance(key, str)
                or not re.fullmatch(r'NSE_FO\|[A-Za-z0-9]+\|\d{2}-\d{2}-\d{4}', key)
                or key.rsplit('|', 1)[1] != expiry.strftime('%d-%m-%Y')
                or type(contract.get('lot_size')) is not int or contract['lot_size'] <= 0):
            raise HistoryError('CONTRACT_IDENTITY_UNVERIFIED')
        # Never construct expired keys from symbols or a presumed expiry weekday.
        history = self._get(f'/historical-candle/{quote(key, safe="")}/5minute/{end}/{start}')
        rows = candles(history, start, end)
        if not rows:
            raise HistoryError('EMPTY_HISTORY_NOT_VERIFIED_COVERAGE')
        return {'version': 'nifty-futures-probe-v1', 'provider_contract': contract,
                'retrieved_at': datetime.now(timezone.utc).isoformat(),
                'provider_source': BASE,
                'contract_sha256': sha(encoded(contract)), 'candles': rows,
                'rows_sha256': sha(encoded(rows)), 'row_count': len(rows),
                'start': str(start), 'end': str(end), 'interval': '5minute',
                'timestamp_basis': 'BAR_START_DOCUMENTED_NOT_INDEPENDENTLY_VERIFIED',
                'lot_size_authority': 'PROVIDER_METADATA_REQUIRES_DATED_NSE_RECONCILIATION',
                'replay_ready': False, 'fill_evidence': False, 'approval_authority': False,
                'session_check': check_session(rows, start) if start == end else None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', required=True, type=date.fromisoformat)
    parser.add_argument('--end', required=True, type=date.fromisoformat)
    parser.add_argument('--expiry', required=True, type=date.fromisoformat)
    parser.add_argument('--output', required=True, type=Path, help='Private directory OUTSIDE the repository')
    parser.add_argument('--confirm-network', action='store_true', help='Otherwise offline preview; no token prompt')
    args = parser.parse_args(argv)
    try:
        development_range(args.start, args.end, args.expiry)
        root = args.output.resolve()
        if root.is_relative_to(Path(__file__).resolve().parent):
            raise HistoryError('PRIVATE_OUTPUT_MUST_BE_OUTSIDE_REPOSITORY')
        if not args.confirm_network:
            print(json.dumps({'status': 'PREVIEW', 'network_calls': 0, 'interval': '5minute',
                              'start': str(args.start), 'end': str(args.end), 'expiry': str(args.expiry),
                              'approval_authority': False}))
            return 0
        path = root / f'nifty-future-{args.expiry}-{args.start}-{args.end}.json.gz'
        if path.exists():
            raise HistoryError('ARTIFACT_ALREADY_EXISTS_REVIEW_BEFORE_REPROBE')
        token = getpass.getpass('Upstox token (hidden; never saved): ')
        with requests.Session() as session:
            result = Reader(token, session).probe(args.start, args.end, args.expiry)
        immutable(path, gzip.compress(encoded(result), mtime=0))
        restored = json.loads(gzip.decompress(path.read_bytes()))
        if (restored != result or sha(encoded(restored['candles'])) != restored['rows_sha256']):
            raise HistoryError('LOCAL_VERIFICATION_FAILED')
        print(json.dumps({'status': 'PROBE_SAVED_NOT_REPLAY_READY', 'rows': result['row_count'],
                          'rows_sha256': result['rows_sha256'], 'session_check': result['session_check'],
                          'approval_authority': False}))
        return 0
    except HistoryError as error:
        print(json.dumps({'status': 'BLOCKED', 'code': str(error)}))
        return 2
    except (OSError, EOFError):
        print(json.dumps({'status': 'BLOCKED', 'code': 'LOCAL_IO_OR_INPUT_FAILED'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
