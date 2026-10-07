"""Explicit owner-attested browser source; never impersonate automated retrieval."""
from __future__ import annotations

import base64
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from nifty_previous_close import LIMIT, parse_close, previous_session, source_url
from research_integrity import IntegrityError, digest
from research_replay_comparison import instant

IST = ZoneInfo('Asia/Kolkata')
VERSION = 'nse-previous-close-owner-file-v1'
FIELDS = {'version', 'source_url', 'source_authenticity', 'close_date', 'close_decimal',
          'sha256', 'csv_base64', 'owner_observed_download_at', 'file_read_at', 'publication_time'}


def validate(provenance: dict[str, Any], day: date, frozen_at: str) -> float:
    """Check retained bytes and attested timing; do not certify external origin."""
    expected = previous_session(day)
    if (set(provenance) != FIELDS or provenance['version'] != VERSION
            or provenance['source_authenticity'] != 'OWNER_ATTESTED_NOT_INDEPENDENTLY_VERIFIED'
            or provenance['source_url'] != source_url(expected)
            or provenance['close_date'] != expected.isoformat()
            or provenance['publication_time'] is not None
            or not isinstance(provenance['csv_base64'], str)
            or len(provenance['csv_base64']) > 4 * ((LIMIT + 2) // 3)):
        raise IntegrityError('OWNER_CLOSE_PROVENANCE_INVALID')
    observed, read, frozen = map(instant, (provenance['owner_observed_download_at'],
                                         provenance['file_read_at'], frozen_at))
    opening = datetime.combine(day, time(9, 15), IST)
    if (not observed <= read <= frozen < opening
            or observed.astimezone(IST).date() != day
            or frozen.astimezone(IST).date() != day):
        raise IntegrityError('OWNER_CLOSE_TIMING_INVALID')
    raw = base64.b64decode(provenance['csv_base64'], validate=True)
    value = parse_close(raw, expected)
    if digest(raw) != provenance['sha256'] or value != Decimal(provenance['close_decimal']):
        raise IntegrityError('OWNER_CLOSE_BYTES_MISMATCH')
    numeric = float(value)
    if Decimal(str(numeric)) != value:
        raise IntegrityError('NSE_CLOSE_NUMERIC_PRECISION_INVALID')
    return numeric


def from_file(path: Path, day: date, *, observed_download_at: str,
              read_at: str, attested: bool, code_root: Path) -> dict[str, Any]:
    """Read one private bounded CSV only after literal Boolean owner confirmation."""
    if attested is not True:
        raise IntegrityError('OWNER_CLOSE_ATTESTATION_REQUIRED')
    if str(path).startswith(('\\\\', '//')):
        raise IntegrityError('LOCAL_PRIVATE_FILE_REQUIRED')
    resolved = path.resolve()
    if str(resolved).startswith(('\\\\', '//')):
        raise IntegrityError('LOCAL_PRIVATE_FILE_REQUIRED')
    if resolved.is_relative_to(code_root.resolve()):
        raise IntegrityError('SOURCE_OUTSIDE_CODE_FOLDER_REQUIRED')
    expected = previous_session(day)
    # Reject impossible attested timestamps before reading the private file.
    observed, read = instant(observed_download_at), instant(read_at)
    if (observed > read or observed.astimezone(IST).date() != day
            or read.astimezone(IST).date() != day
            or read >= datetime.combine(day, time(9, 15), IST)):
        raise IntegrityError('OWNER_CLOSE_TIMING_INVALID')
    with resolved.open('rb') as source:
        raw = source.read(LIMIT + 1)
    value = parse_close(raw, expected)
    result = {'version': VERSION, 'source_url': source_url(expected),
              'source_authenticity': 'OWNER_ATTESTED_NOT_INDEPENDENTLY_VERIFIED',
              'close_date': expected.isoformat(), 'close_decimal': str(value),
              'sha256': digest(raw), 'csv_base64': base64.b64encode(raw).decode('ascii'),
              'owner_observed_download_at': observed_download_at,
              'file_read_at': read_at, 'publication_time': None}
    validate(result, day, read_at)
    return result
