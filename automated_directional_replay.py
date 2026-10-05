"""Frozen development replay of parked rules; no broker, tuning or fills."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, cast
from zoneinfo import ZoneInfo

import pandas as pd  # type: ignore[import-untyped]

from automated_development_checks import environment, write_once
from intraday_directional_replay import run as replay
from release_verification import release_members
from research_integrity import DevelopmentManifest, IntegrityError, TrialLedger, digest, hash_value, recorded_trial, require_hash

VERSION = 'frozen-directional-replay-v1'
PURPOSE = 'PARKED_DEVELOPMENT_REPLAY'
REQUIRED_COLUMNS = {'timestamp', 'Open', 'High', 'Low', 'Close', 'available_at'}


def replay_environment(root: Path) -> dict[str, Any]:
    """Freeze transitive local implementation, dependency locks and runtime."""
    result = environment(root)
    names = cast(Callable[[Path, tuple[str, ...]], list[str]], release_members)(
        root, ('automated_directional_replay.py',))
    result['sources'].update({name: digest((root / name).read_bytes().replace(b'\r\n', b'\n')) for name in names})
    return result


def check_timestamp(value: Any, manifest: dict[str, str]) -> None:
    """All bar availability/session dates use IST and the declared development partition."""
    if not isinstance(value, str):
        raise IntegrityError('TIMESTAMP_STRING_REQUIRED')
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None:
        raise IntegrityError('AWARE_TIMESTAMP_REQUIRED')
    day = instant.astimezone(ZoneInfo('Asia/Kolkata')).date().isoformat()
    if not manifest['start'] <= day <= manifest['end']:
        raise IntegrityError('SEALED_OR_OUTSIDE_DECLARED_PERIOD')


def validate_spec(spec: dict[str, Any], root: Path) -> str:
    """Exact schema: no strategy, confirmation, bootstrap or session overrides."""
    if (set(spec) != {'version', 'purpose', 'manifests', 'environment'} or spec['version'] != VERSION
            or spec['purpose'] != PURPOSE or spec['environment'] != replay_environment(root)):
        raise IntegrityError('FROZEN_REPLAY_SPEC_MISMATCH')
    manifests = spec['manifests']
    if not isinstance(manifests, dict) or set(manifests) != {'bars', 'sessions'}:
        raise IntegrityError('BARS_AND_CALENDAR_REQUIRED')
    for manifest in manifests.values():
        if (not isinstance(manifest, dict) or set(manifest) != {'relative_path', 'sha256', 'start', 'end'}
                or any(not isinstance(v, str) for v in manifest.values())):
            raise IntegrityError('MANIFEST_SCHEMA_INVALID')
        require_hash(manifest['sha256'])
        # A frozen first recipe, not a period-search interface.
        if manifest['start'] != '2022-01-01' or manifest['end'] != '2024-12-31':
            raise IntegrityError('DEVELOPMENT_PARTITION_REQUIRED')
    return hash_value(spec)


def parse_inputs(raw_bars: bytes, raw_sessions: bytes,
                 manifests: dict[str, Any]) -> tuple[Any, list[dict[str, Any]]]:
    """One shared decoder for source and archived bytes; same date/calendar guards."""
    reader = csv.DictReader(io.StringIO(raw_bars.decode('utf-8-sig')))
    if (reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames))
            or not REQUIRED_COLUMNS.issubset(reader.fieldnames)):
        raise IntegrityError('BAR_COLUMNS_REQUIRED')
    records: list[dict[str, str]] = []
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise IntegrityError('MALFORMED_CSV_ROW')
        for key in ('timestamp', 'available_at'):
            check_timestamp(row[key], manifests['bars'])
        records.append({key: row[key] for key in REQUIRED_COLUMNS})
    if not records:
        raise IntegrityError('EMPTY_BARS')
    sessions = json.loads(raw_sessions.decode('utf-8-sig'))
    if not isinstance(sessions, list) or not sessions or any(not isinstance(row, dict) for row in sessions):
        raise IntegrityError('EXPLICIT_SESSION_CALENDAR_REQUIRED')
    for session in sessions:
        for key in ('open', 'close'):
            check_timestamp(session[key], manifests['sessions'])
        if datetime.fromisoformat(session['close']) <= datetime.fromisoformat(session['open']):
            raise IntegrityError('INVALID_SESSION_BOUNDARY')
        if 'replay_eligible' in session and type(session['replay_eligible']) is not bool:
            raise IntegrityError('BOOLEAN_ELIGIBILITY_REQUIRED')
        if 'reset_warmup' in session and type(session['reset_warmup']) is not bool:
            raise IntegrityError('BOOLEAN_WARMUP_RESET_REQUIRED')
        for value in session.get('out_of_session_bars', []):
            check_timestamp(value, manifests['sessions'])
        if session.get('replay_eligible') is True and session.get('exclusion_reason') is not None:
            raise IntegrityError('CONTRADICTORY_SESSION_ELIGIBILITY')
        if session.get('replay_eligible') is True and session.get('kind', 'REGULAR') != 'REGULAR':
            raise IntegrityError('SPECIAL_SESSION_NOT_ELIGIBLE')
    frame = pd.DataFrame(records)
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop('timestamp'), utc=True))
    return frame, sessions


def run(spec: dict[str, Any], *, source_root: Path, data_root: Path,
        ledger: TrialLedger) -> dict[str, Any]:
    """Read only hash-verified development-only files inside a recorded trial."""
    spec_hash = validate_spec(spec, source_root)

    def compute() -> dict[str, Any]:
        manifests = spec['manifests']
        frame, sessions = parse_inputs(DevelopmentManifest(**manifests['bars']).read_bytes(data_root),
                                      DevelopmentManifest(**manifests['sessions']).read_bytes(data_root), manifests)
        invoke = cast(Callable[[Any, list[dict[str, Any]]], dict[str, Any]], replay)
        result = invoke(frame, sessions)
        result['automation'] = {'version': VERSION, 'spec_hash': spec_hash,
                                'input_hashes': {key: value['sha256'] for key, value in manifests.items()}}
        # Diagnostics remain a separate frozen operation: no cost/edge inference here.
        return result

    return recorded_trial(ledger, spec_hash, compute)


def main(argv: list[str] | None = None) -> int:
    """Prepare/review/register separately; explicit output and private state only."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', required=True, type=Path)
    parser.add_argument('--data-root', required=True, type=Path)
    parser.add_argument('--ledger', required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--register', action='store_true')
    parser.add_argument('--bars-relative')
    parser.add_argument('--bars-sha256')
    parser.add_argument('--sessions-relative')
    parser.add_argument('--sessions-sha256')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        root = Path(__file__).resolve().parent
        if any(path.resolve().is_relative_to(root) for path in
               (args.spec, args.data_root, args.ledger, args.output) if path is not None):
            raise IntegrityError('PRIVATE_STATE_OUTSIDE_REPOSITORY_REQUIRED')
        if args.prepare:
            if args.output is not None or not args.bars_relative or not args.sessions_relative:
                raise IntegrityError('PREPARATION_ARGUMENTS_REQUIRED')
            spec = {'version': VERSION, 'purpose': PURPOSE, 'environment': replay_environment(root),
                    'manifests': {name: {'relative_path': relative, 'sha256': require_hash(sha),
                                       'start': '2022-01-01', 'end': '2024-12-31'}
                                  for name, relative, sha in (
                                      ('bars', args.bars_relative, args.bars_sha256),
                                      ('sessions', args.sessions_relative, args.sessions_sha256))}}
            write_once(args.spec, spec)
            status = 'SPEC_PREPARED'
        else:
            spec = json.loads(args.spec.read_text(encoding='utf-8-sig'))
            if not isinstance(spec, dict):
                raise IntegrityError('SPEC_OBJECT_REQUIRED')
            fingerprint = validate_spec(spec, root)
            ledger = TrialLedger(args.ledger)
            if args.register:
                if args.output is not None:
                    raise IntegrityError('REGISTRATION_HAS_NO_OUTPUT')
                ledger.append({'kind': 'REGISTERED', 'identity': fingerprint, 'spec_hash': fingerprint,
                               'at': datetime.now(timezone.utc).isoformat()})
                status = 'REGISTERED'
            else:
                if args.output is None or args.output.exists():
                    raise IntegrityError('NEW_OUTPUT_REQUIRED')
                result = run(spec, source_root=root, data_root=args.data_root, ledger=ledger)
                write_once(args.output, result)
                print(json.dumps({'status': 'REPLAY_COMPLETE', 'result_hash': hash_value(result),
                                  'spec_hash': fingerprint, 'approval_authority': False}))
                return 0
        print(json.dumps({'status': status, 'spec_hash': hash_value(spec), 'approval_authority': False}))
        return 0
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error, csv.Error):
        print(json.dumps({'status': 'BLOCKED', 'code': 'FROZEN_REPLAY_FAILED', 'approval_authority': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
