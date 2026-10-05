"""Frozen offline diagnostics of parked benchmarks; no strategy search or unsealing."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sqlite3
import tempfile
from typing import Any, Callable, cast
from zoneinfo import ZoneInfo

from development_cost_hurdles import screen
from research_integrity import DevelopmentManifest, IntegrityError, TrialLedger, canonical, digest, hash_value, require_hash, recorded_trial
from release_verification import release_members

VERSION = 'automated-development-v1'
SOURCES = ('automated_development_checks.py', 'research_integrity.py',
           'development_cost_hurdles.py', 'directional_replay_diagnostics.py')
VARIANTS = {'C_single_bar_no_volume', 'C_persistent_no_volume'}


def environment(root: Path) -> dict[str, Any]:
    """Bind actual source, lockfiles and numeric runtime; no git/secret dependence."""
    closure = cast(Callable[[Path, tuple[str, ...]], list[str]], release_members)(root, SOURCES)
    return {'sources': {name: digest((root / name).read_bytes().replace(b'\r\n', b'\n')) for name in closure},
            'locks': {name: digest((root / name).read_bytes().replace(b'\r\n', b'\n'))
                      for name in ('requirements.txt', 'constraints.txt')},
            'python': platform.python_version(),
            'packages': {name: importlib.metadata.version(name) for name in ('numpy', 'pandas')}}


def validate_spec(spec: dict[str, Any], root: Path) -> str:
    """No tunable parameters; exact frozen implementation/data identity required."""
    if (set(spec) != {'version', 'purpose', 'manifest', 'environment'} or spec['version'] != VERSION
            or spec['purpose'] != 'PARKED_BENCHMARK_DIAGNOSTICS'
            or spec['environment'] != environment(root)):
        raise IntegrityError('FROZEN_SPEC_OR_ENVIRONMENT_MISMATCH')
    manifest = spec['manifest']
    if not isinstance(manifest, dict) or set(manifest) != {'relative_path', 'sha256', 'start', 'end'}:
        raise IntegrityError('DATA_MANIFEST_REQUIRED')
    if any(not isinstance(v, str) for v in manifest.values()):
        raise IntegrityError('MANIFEST_STRING_FIELDS_REQUIRED')
    require_hash(manifest['sha256'])
    return hash_value(spec)


def run(spec: dict[str, Any], *, source_root: Path, data_root: Path, ledger: TrialLedger) -> dict[str, Any]:
    """Record an attempt before loading data; failed/incomplete trials stay visible."""
    spec_hash = validate_spec(spec, source_root)

    def compute() -> dict[str, Any]:
        raw = DevelopmentManifest(**spec['manifest']).load(data_root)
        if not isinstance(raw.get('variants'), dict) or set(raw['variants']) != VARIANTS:
            raise IntegrityError('PARKED_BENCHMARKS_ONLY')
        timestamps = [item['session_open'] for item in raw['decisions']]
        timestamps.extend(item['open'] for item in raw['excluded_sessions'])
        timestamps.extend(trade[field] for variant in raw['variants'].values()
                          for trade in variant['trades'] for field in ('entry_at', 'exit_at'))
        for value in timestamps:
            instant = datetime.fromisoformat(value)
            if instant.tzinfo is None:
                raise IntegrityError('AWARE_REPORT_TIMESTAMP_REQUIRED')
            day = instant.astimezone(ZoneInfo('Asia/Kolkata')).date().isoformat()
            if not spec['manifest']['start'] <= day <= spec['manifest']['end']:
                raise IntegrityError('REPORT_OUTSIDE_DECLARED_PERIOD')
        # The existing adapter verifies actual session/trade dates, including
        # excluded sessions. Type boundary only; no numeric or policy rewrite.
        result = cast(Callable[[dict[str, Any]], dict[str, Any]], screen)(raw)
        result['automation'] = {'version': VERSION, 'spec_hash': spec_hash,
                                'result_fingerprint': hash_value({'spec': spec_hash, 'mode': VERSION})}
        return result

    return recorded_trial(ledger, spec_hash, compute)


def write_once(path: Path, value: dict[str, Any]) -> None:
    """Publish complete fsynced content atomically, without replacing any file."""
    data = canonical(value)
    descriptor, temporary = tempfile.mkstemp(prefix='.research-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    """Register explicitly or run an already registered frozen development spec."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--register', action='store_true', help='Explicit local spec registration, never automatic')
    parser.add_argument('--prepare', action='store_true', help='Write a frozen spec without opening data')
    parser.add_argument('--report-relative', help='Relative development report path for preparation')
    parser.add_argument('--report-sha256', help='Previously verified exact report SHA-256')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        root = Path(__file__).resolve().parent
        for path in (args.spec, args.data_root, args.ledger, args.output):
            if path is not None and path.resolve().is_relative_to(root):
                raise IntegrityError('PRIVATE_RESEARCH_STATE_MUST_BE_OUTSIDE_REPOSITORY')
        if args.prepare:
            if args.register or args.output is not None or not args.report_relative:
                raise IntegrityError('PREPARATION_ARGUMENTS_INVALID')
            spec = {'version': VERSION, 'purpose': 'PARKED_BENCHMARK_DIAGNOSTICS',
                    'manifest': {'relative_path': args.report_relative,
                                 'sha256': require_hash(args.report_sha256),
                                 'start': '2022-01-01', 'end': '2024-12-31'},
                    'environment': environment(root)}
            write_once(args.spec, spec)
            print(json.dumps({'status': 'SPEC_PREPARED', 'spec_hash': hash_value(spec),
                              'approval_authority': False}))
            return 0
        spec = json.loads(args.spec.read_text(encoding='utf-8-sig'))
        if not isinstance(spec, dict):
            raise IntegrityError('SPEC_OBJECT_REQUIRED')
        spec_hash = validate_spec(spec, root)
        ledger = TrialLedger(args.ledger)
        if args.register:
            ledger.append({'kind': 'REGISTERED', 'identity': spec_hash, 'spec_hash': spec_hash,
                           'at': datetime.now(timezone.utc).isoformat()})
            print(json.dumps({'status': 'REGISTERED', 'spec_hash': spec_hash, 'approval_authority': False}))
        else:
            if args.output is None:
                raise IntegrityError('PRIVATE_OUTPUT_REQUIRED')
            if args.output.exists():
                raise IntegrityError('OUTPUT_EXISTS_NO_OVERWRITE')
            result = run(spec, source_root=root, data_root=args.data_root, ledger=ledger)
            write_once(args.output, result)
            print(json.dumps({'status': 'RESEARCH_CHECK_COMPLETE', 'spec_hash': spec_hash,
                              'result_hash': hash_value(result), 'approval_authority': False}))
        return 0
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error):
        # No raw path, report, token or exception text can appear in CLI output.
        print(json.dumps({'status': 'BLOCKED', 'code': 'LOCAL_RESEARCH_CHECK_FAILED', 'approval_authority': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
