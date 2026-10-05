"""Exact prior NSE session close, retained official CSV provenance; no fallback."""
from __future__ import annotations

import base64
import csv
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import io
from typing import Any, Callable, cast
from zoneinfo import ZoneInfo

from nifty_session_calendar import cash_session
from research_integrity import IntegrityError, digest
from research_replay_comparison import instant

LIMIT = 256 * 1024
BASE = 'https://nsearchives.nseindia.com/content/indices/ind_close_all_'


def previous_session(day: date) -> date:
    """Include genuine special sessions as previous closes, skip only closed dates."""
    if cast(Callable[[date], dict[str, Any]], cash_session)(day)['kind'] != 'REGULAR':
        raise IntegrityError('REGULAR_SESSION_REQUIRED')
    for offset in range(1, 16):
        candidate = day - timedelta(days=offset)
        if cast(Callable[[date], dict[str, Any]], cash_session)(candidate)['kind'] != 'CLOSED':
            return candidate
    raise IntegrityError('PREVIOUS_SESSION_UNVERIFIED')


def source_url(day: date) -> str:
    """Fixed official origin and exact filename; caller cannot inject a URL."""
    return BASE + day.strftime('%d%m%Y') + '.csv'


def parse_close(raw: bytes, expected: date) -> Decimal:
    """Require dated, unique NIFTY 50 price-index row, not TRI or a futures close."""
    if not raw or len(raw) > LIMIT:
        raise IntegrityError('NSE_CLOSE_SIZE_INVALID')
    try:
        reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')), strict=True)
        headers = reader.fieldnames
        required = {'Index Name', 'Index Date', 'Closing Index Value'}
        if headers is None:
            raise IntegrityError('NSE_CLOSE_SCHEMA_INVALID')
        normalized = [key.strip() for key in headers]
        if len(set(normalized)) != len(normalized) or not required.issubset(normalized):
            raise IntegrityError('NSE_CLOSE_SCHEMA_INVALID')
        matches: list[Decimal] = []
        for raw_row in reader:
            if None in raw_row or any(value is None for value in raw_row.values()):
                raise IntegrityError('NSE_CLOSE_ROW_INVALID')
            row = {key.strip(): value.strip() for key, value in raw_row.items()}
            if datetime.strptime(row['Index Date'], '%d-%m-%Y').date() != expected:
                raise IntegrityError('NSE_CLOSE_DATE_MISMATCH')
            if row['Index Name'].upper() == 'NIFTY 50':
                value = Decimal(row['Closing Index Value'])
                if not value.is_finite() or value <= 0:
                    raise IntegrityError('NSE_CLOSE_PRICE_INVALID')
                matches.append(value)
        if len(matches) != 1:
            raise IntegrityError('NSE_CLOSE_UNIQUE_INDEX_REQUIRED')
        return matches[0]
    except IntegrityError:
        raise
    except (UnicodeError, csv.Error, ValueError, InvalidOperation):
        raise IntegrityError('NSE_CLOSE_INVALID') from None


def fetch(session: Any, day: date, *, received_clock: Callable[[], datetime]) -> dict[str, Any]:
    """Bounded verified HTTPS GET; provenance is observed retrieval, not publication time."""
    previous = previous_session(day)
    with session.get(source_url(previous), timeout=(5, 20), verify=True,
                     allow_redirects=False, stream=True) as response:
        if response.status_code != 200:
            raise IntegrityError('NSE_CLOSE_UNAVAILABLE')
        raw = bytearray()
        for block in response.iter_content(65536):
            raw.extend(block)
            if len(raw) > LIMIT:
                raise IntegrityError('NSE_CLOSE_SIZE_INVALID')
    value = parse_close(bytes(raw), previous)
    received = received_clock()
    if received.tzinfo is None:
        raise IntegrityError('AWARE_TIMESTAMP_REQUIRED')
    return {'version': 'nse-previous-close-v1', 'source_url': source_url(previous),
            'close_date': previous.isoformat(), 'close_decimal': str(value),
            'sha256': digest(bytes(raw)), 'csv_base64': base64.b64encode(raw).decode('ascii'),
            'retrieved_at': received.isoformat(), 'publication_time': None}


def validate(provenance: dict[str, Any], day: date, frozen_at: str) -> float:
    """Validate retained bytes/calendar/date before trusting the numeric adapter."""
    expected = previous_session(day)
    if (set(provenance) != {'version', 'source_url', 'close_date', 'close_decimal', 'sha256',
                            'csv_base64', 'retrieved_at', 'publication_time'}
            or provenance['version'] != 'nse-previous-close-v1'
            or provenance['close_date'] != expected.isoformat()
            or provenance['source_url'] != source_url(expected)
            or provenance['publication_time'] is not None
            or instant(provenance['retrieved_at']) > instant(frozen_at)
            or instant(provenance['retrieved_at']).astimezone(ZoneInfo('Asia/Kolkata')).date() != day
            or len(provenance['csv_base64']) > 4 * ((LIMIT+2)//3)):
        raise IntegrityError('NSE_CLOSE_PROVENANCE_INVALID')
    raw = base64.b64decode(provenance['csv_base64'], validate=True)
    value = parse_close(raw, expected)
    if digest(raw) != provenance['sha256'] or value != Decimal(provenance['close_decimal']):
        raise IntegrityError('NSE_CLOSE_PROVENANCE_MISMATCH')
    numeric = float(value)
    if Decimal(str(numeric)) != value:
        raise IntegrityError('NSE_CLOSE_NUMERIC_PRECISION_INVALID')
    return numeric
