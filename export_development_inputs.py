"""Verified readiness export; later numeric data is never decoded or scored."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Iterator, cast
from zoneinfo import ZoneInfo

from automated_development_checks import write_once
from automated_directional_replay import REQUIRED_COLUMNS, parse_inputs
from intraday_directional_replay import validate
from research_integrity import IntegrityError, canonical, digest, require_hash

LIMIT = 64 * 1024 * 1024
ROOT = Path(__file__).resolve().parent
COLUMNS = ('timestamp', 'Open', 'High', 'Low', 'Close', 'available_at')


def file_hash(path: Path) -> str:
    """Hash mixed source bytes without decoding prices in sealed partitions."""
    if path.is_symlink():
        raise IntegrityError('SOURCE_SYMLINK_FORBIDDEN')
    result = hashlib.sha256()
    total = 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            total += len(block)
            if total > LIMIT:
                raise IntegrityError('SOURCE_TOO_LARGE')
            result.update(block)
    return result.hexdigest()


def day(value: str) -> str:
    """Only inspect aware timestamps; never guess timezone from a date."""
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None:
        raise IntegrityError('AWARE_TIMESTAMP_REQUIRED')
    return instant.astimezone(ZoneInfo('Asia/Kolkata')).date().isoformat()


def session_prefix(path: Path) -> Iterator[dict[str, Any]]:
    """Scan JSON object bytes; inspect open before decoding any numeric fields.

    Readiness output is an array of objects. Stops at the first later session,
    without JSON-decoding its previous close or any following sessions. Timestamp
    extraction is restricted to the metadata prefix before the open field.
    """
    previous = ''
    with path.open(encoding='utf-8-sig') as stream:
        if next((char for char in iter(lambda: stream.read(1), '') if not char.isspace()), '') != '[':
            raise IntegrityError('SESSION_ARRAY_REQUIRED')
        while True:
            char = next((char for char in iter(lambda: stream.read(1), '') if not char.isspace() and char != ','), '')
            if char == ']':
                return
            if char != '{':
                raise IntegrityError('SESSION_OBJECT_REQUIRED')
            text, depth, quoted, escaped = char, 1, False, False
            while depth:
                char = stream.read(1)
                if not char or len(text) >= 256 * 1024:
                    raise IntegrityError('SESSION_OBJECT_INVALID_OR_TOO_LARGE')
                text += char
                if quoted:
                    if escaped:
                        escaped = False
                    elif char == '\\':
                        escaped = True
                    elif char == '"':
                        quoted = False
                elif char == '"':
                    quoted = True
                elif char in '{[':
                    depth += 1
                elif char in '}]':
                    depth -= 1
            # Canonical readiness keys place open before previous_close. Match
            # a top-level-looking timestamp and verify against decoded dev row.
            match = re.search(r'"open"\s*:\s*("[^"\\]+")', text)
            if match is None:
                raise IntegrityError('SESSION_OPEN_REQUIRED')
            opening = json.loads(match[1])
            current = day(opening)
            if current > '2024-12-31':
                return
            if current < '2022-01-01' or current <= previous:
                raise IntegrityError('DEVELOPMENT_SESSION_ORDER_INVALID')
            row = json.loads(text)
            if not isinstance(row, dict) or row.get('open') != opening:
                raise IntegrityError('SESSION_METADATA_INVALID')
            previous = current
            yield row


def export(*, source_csv: Path, sessions_path: Path, quality_path: Path,
           quality_sha256: str, sessions_sha256: str, output: Path) -> dict[str, Any]:
    """Never overwrite sources/outputs; publish a completion manifest last."""
    paths = (source_csv, sessions_path, quality_path, output)
    if any(path.resolve().is_relative_to(ROOT) for path in paths):
        raise IntegrityError('PRIVATE_INPUTS_OUTSIDE_REPOSITORY_REQUIRED')
    if file_hash(quality_path) != require_hash(quality_sha256) or file_hash(sessions_path) != require_hash(sessions_sha256):
        raise IntegrityError('READINESS_HASH_MISMATCH')
    quality = json.loads(quality_path.read_bytes())
    if quality.get('replay_ready') is not True or quality.get('calendar_reviewed') is not True:
        raise IntegrityError('REVIEWED_READINESS_REQUIRED')
    source_sha = file_hash(source_csv)
    if source_sha != quality.get('source_csv_sha256'):
        raise IntegrityError('SOURCE_HASH_MISMATCH')
    if output.exists():
        raise IntegrityError('NEW_EXPORT_DIRECTORY_REQUIRED')
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS)
    writer.writeheader()
    count, previous = 0, None
    with source_csv.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if (reader.fieldnames is None or len(set(reader.fieldnames)) != len(reader.fieldnames)
                or not REQUIRED_COLUMNS.issubset(reader.fieldnames)):
            raise IntegrityError('BAR_COLUMNS_REQUIRED')
        for row in reader:
            current = day(row['timestamp'])
            if current > '2024-12-31':
                break  # No numeric interpretation, no later availability read.
            stamp = datetime.fromisoformat(row['timestamp'])
            if current < '2022-01-01' or previous is not None and stamp <= previous:
                raise IntegrityError('DEVELOPMENT_BAR_ORDER_INVALID')
            if None in row or any(row.get(key) is None for key in REQUIRED_COLUMNS):
                raise IntegrityError('MALFORMED_CSV_ROW')
            writer.writerow({key: row[key] for key in COLUMNS})
            previous = stamp
            count += 1
    calendar = list(session_prefix(sessions_path))
    development_days = [row for row in quality['days'] if '2022-01-01' <= row['date'] <= '2024-12-31']
    expected_dates = [row['date'] for row in development_days if row['status'] != 'CLOSED']
    if ([day(row['open']) for row in calendar] != expected_dates
            or count != sum(row['count'] for row in development_days)):
        raise IntegrityError('DEVELOPMENT_COVERAGE_MISMATCH')
    raw_bars, raw_sessions = buffer.getvalue().encode(), canonical(calendar)
    manifests = {key: {'relative_path': filename, 'sha256': digest(raw),
                       'start': '2022-01-01', 'end': '2024-12-31'}
                 for key, filename, raw in [('bars', 'bars.csv', raw_bars),
                                            ('sessions', 'sessions.json', raw_sessions)]}
    frame, checked = parse_inputs(raw_bars, raw_sessions, manifests)
    accepted, excluded = cast(Callable[..., tuple[Any, Any]], validate)(frame, checked)
    result = {'version': 'development-export-v1', 'manifests': manifests,
              'source_csv_sha256': source_sha, 'source_quality_sha256': quality_sha256,
              'source_sessions_sha256': sessions_sha256, 'rows': count,
              'accepted_sessions': len(accepted), 'excluded_sessions': len(excluded),
              'approval_authority': False, 'fill_evidence': False}
    if (file_hash(source_csv) != source_sha or file_hash(sessions_path) != sessions_sha256
            or file_hash(quality_path) != quality_sha256):
        raise IntegrityError('SOURCE_CHANGED_DURING_EXPORT')
    output.mkdir(parents=True)
    # Exclusive writes leave an incomplete directory visible on disk failure;
    # never clean it up or replace it. Only export.json proves completion.
    for filename, raw in [('bars.csv', raw_bars), ('sessions.json', raw_sessions)]:
        with (output / filename).open('xb') as target:
            target.write(raw)
            target.flush()
            os.fsync(target.fileno())
    write_once(output / 'export.json', result)
    return result


def main(argv: list[str] | None = None) -> int:
    """No token/network input; only verified private files and sanitized status."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-csv', 'sessions', 'quality', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--quality-sha256', required=True)
    parser.add_argument('--sessions-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        result = export(source_csv=args.source_csv, sessions_path=args.sessions, quality_path=args.quality,
                        quality_sha256=args.quality_sha256, sessions_sha256=args.sessions_sha256, output=args.output)
        print(json.dumps({'status': 'DEVELOPMENT_EXPORTED', 'rows': result['rows'],
                          'accepted_sessions': result['accepted_sessions'],
                          'approval_authority': False, 'fill_evidence': False}))
        return 0
    except (ValueError, OSError, KeyError, TypeError, csv.Error):
        print(json.dumps({'status': 'BLOCKED', 'code': 'DEVELOPMENT_EXPORT_FAILED', 'approval_authority': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
