"""Recoverable frozen development inputs and honest replay-only references."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, cast
import argparse
import csv
import json
import sqlite3
import zlib

from automated_development_checks import write_once
from automated_directional_replay import parse_inputs, replay_environment, validate_spec as validate_replay_spec
from intraday_directional_replay import run as replay, validate
from release_verification import release_members
from research_input_archive import InputArchive
from research_integrity import DevelopmentManifest, IntegrityError, TrialLedger, canonical, digest, hash_value, recorded_trial
from research_replay_comparison import Observation, instant


def prepare_spec(replay_spec: dict[str, Any], source_root: Path) -> dict[str, Any]:
    """Freeze the adapter too; preparation opens source/metadata, never data files."""
    validate_replay_spec(replay_spec, source_root)
    environment = replay_environment(source_root)
    names = cast(Callable[[Path, tuple[str, ...]], list[str]], release_members)(
        source_root, ('archived_directional_replay.py',))
    environment['sources'].update({name: digest((source_root / name).read_bytes().replace(b'\r\n', b'\n'))
                                   for name in names})
    return {'version': 'archived-development-v1', 'purpose': 'RECOVERABLE_PARKED_REPLAY',
            'replay_spec': replay_spec, 'environment': environment, 'zlib': zlib.ZLIB_RUNTIME_VERSION}


def comparison_identity(spec: dict[str, Any]) -> str:
    """Math/source identity excludes future dataset bytes and capture timestamps.

    Trial recipe identity still binds every input file. Comparison identity binds
    the single NIFTY raw-bias recipe, NOT entry/exit rules or a trading instrument.
    """
    return hash_value({'version': 'nifty-raw-bias-v1', 'environment': spec['environment'],
                       'instrument': 'NIFTY_INDEX_REFERENCE', 'policy': 'intraday-directional-v1'})


@dataclass(frozen=True)
class ReplayReference:
    """Computed reference without fabricated historical receipt time."""

    payload: dict[str, Any]

    def for_comparison(self, computed_at: str) -> Observation:
        """Caller supplies actual computation time; origin stays REPLAY."""
        result = Observation(**self.payload, received_at=computed_at, origin='REPLAY')
        result.normalized()
        return result


def references(frame: Any, sessions: list[dict[str, Any]], report: dict[str, Any],
               identity: str) -> list[dict[str, Any]]:
    """Linear rolling consumed-prefix hashes; future prices never enter a prefix."""
    accepted, _ = cast(Callable[[Any, list[dict[str, Any]]], tuple[list[Any], Any]], validate)(frame, sessions)
    by_open = {instant(row['session_open']).isoformat(): row['rows'] for row in report['decisions']}
    result = []
    chain = hash_value({'schema': 'consumed-prefix-v1', 'comparison_spec_hash': identity})
    for session, clean in accepted:
        if session['reset_warmup']:
            chain = hash_value({'schema': 'consumed-prefix-v1', 'comparison_spec_hash': identity})
        context = {key: session[key] for key in ('open', 'close', 'source', 'availability_basis', 'reset_warmup')}
        context['open'], context['close'] = instant(context['open']).isoformat(), instant(context['close']).isoformat()
        context['previous_close'] = float(session['previous_close'])
        chain = hash_value({'previous': chain, 'session': context})
        rows = by_open[context['open']]
        if len(rows) != len(clean):
            raise IntegrityError('REPLAY_REFERENCE_COUNT_MISMATCH')
        for (start, bar), decision in zip(clean.iterrows(), rows):
            consumed = {key: float(bar[key]) for key in ('Open', 'High', 'Low', 'Close')}
            consumed.update(start=start.isoformat(), available_at=bar.available_at.isoformat())
            chain = hash_value({'previous': chain, 'bar': consumed})
            if decision['at'] != bar.end.isoformat():
                raise IntegrityError('REPLAY_REFERENCE_BOUNDARY_MISMATCH')
            result.append({'spec_hash': identity, 'session_open': context['open'],
                           'session_close': context['close'], 'decision_at': decision['at'],
                           'available_at': bar.available_at.isoformat(), 'input_hash': chain,
                           'direction': decision['direction'], 'available': decision['available'],
                           'detail_hash': hash_value(decision['detail']), 'basis': session['availability_basis']})
    return result


def run(spec: dict[str, Any], *, source_root: Path, data_root: Path,
        archive: InputArchive, ledger: TrialLedger) -> dict[str, Any]:
    """Record before access, retain verified inputs, compute references, persist manifest.

    Does not store references in the observation journal or call any provider.
    Source copies may disappear later; restore_and_replay uses only archived bytes.
    """
    if (set(spec) != {'version', 'purpose', 'replay_spec', 'environment', 'zlib'}
            or spec != prepare_spec(spec['replay_spec'], source_root)):
        raise IntegrityError('ARCHIVED_REPLAY_SPEC_MISMATCH')
    spec_hash = hash_value(spec)

    def compute() -> dict[str, Any]:
        manifests = spec['replay_spec']['manifests']
        raw = {key: DevelopmentManifest(**value).read_bytes(data_root) for key, value in manifests.items()}
        frame, sessions = parse_inputs(raw['bars'], raw['sessions'], manifests)
        cast(Callable[[Any, list[dict[str, Any]]], Any], validate)(frame, sessions)
        blobs = {key: archive.put(value) for key, value in raw.items()}
        report = cast(Callable[[Any, list[dict[str, Any]]], dict[str, Any]], replay)(frame, sessions)
        rows = references(frame, sessions, report, comparison_identity(spec))
        manifest = {'version': 'recoverable-replay-v1', 'spec': spec, 'inputs': blobs,
                    'report_hash': hash_value(report), 'references_hash': hash_value(rows),
                    'approval_authority': False, 'fill_evidence': False}
        stored = archive.put(canonical(manifest))
        return {'version': 'archived-replay-result-v1', 'spec_hash': spec_hash,
                'manifest_sha256': stored['sha256'], 'comparison_spec_hash': comparison_identity(spec),
                'references_origin': 'REPLAY', 'references': rows, 'report': report,
                'approval_authority': False, 'fill_evidence': False}

    return recorded_trial(ledger, spec_hash, compute)


def restore_and_replay(archive: InputArchive, manifest_sha256: str,
                       source_root: Path) -> dict[str, Any]:
    """Reproduce from archive only; environment drift blocks before data decode."""
    manifest = json.loads(archive.get(manifest_sha256))
    if (not isinstance(manifest, dict) or set(manifest) != {'version', 'spec', 'inputs', 'report_hash',
            'references_hash', 'approval_authority', 'fill_evidence'}
            or manifest['version'] != 'recoverable-replay-v1'
            or manifest['approval_authority'] is not False or manifest['fill_evidence'] is not False):
        raise IntegrityError('RECOVERY_MANIFEST_INVALID')
    spec = manifest['spec']
    if not isinstance(spec, dict) or 'replay_spec' not in spec:
        raise IntegrityError('RECOVERY_MANIFEST_INVALID')
    if spec != prepare_spec(spec['replay_spec'], source_root):
        raise IntegrityError('RECOVERY_ENVIRONMENT_MISMATCH')
    if not isinstance(manifest['inputs'], dict) or set(manifest['inputs']) != {'bars', 'sessions'}:
        raise IntegrityError('RECOVERY_INPUT_INVENTORY_INVALID')
    if any(not isinstance(value, dict) or set(value) != {'sha256', 'size', 'compressed_size'}
           or type(value['size']) is not int or type(value['compressed_size']) is not int
           or value['size'] < 0 or value['compressed_size'] < 0
           for value in manifest['inputs'].values()):
        raise IntegrityError('RECOVERY_INPUT_INVENTORY_INVALID')
    raw = {key: archive.get(value['sha256']) for key, value in manifest['inputs'].items()}
    if any(digest(raw[key]) != spec['replay_spec']['manifests'][key]['sha256']
           or len(raw[key]) != manifest['inputs'][key]['size'] for key in raw):
        raise IntegrityError('RECOVERY_INPUT_IDENTITY_MISMATCH')
    frame, sessions = parse_inputs(raw['bars'], raw['sessions'], spec['replay_spec']['manifests'])
    report = cast(Callable[[Any, list[dict[str, Any]]], dict[str, Any]], replay)(frame, sessions)
    rows = references(frame, sessions, report, comparison_identity(spec))
    if hash_value(report) != manifest['report_hash'] or hash_value(rows) != manifest['references_hash']:
        raise IntegrityError('RECOVERY_RESULT_MISMATCH')
    return {'report': report, 'references': rows, 'references_origin': 'REPLAY',
            'comparison_spec_hash': comparison_identity(spec), 'approval_authority': False, 'fill_evidence': False}


def main(argv: list[str] | None = None) -> int:
    """Explicit private prepare/register/run/restore; no automatic registration."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'register', 'run', 'restore'))
    parser.add_argument('--spec', type=Path)
    parser.add_argument('--replay-spec', type=Path)
    parser.add_argument('--ledger', type=Path)
    parser.add_argument('--data-root', type=Path)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--manifest-sha256')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        root = Path(__file__).resolve().parent
        for path in (args.spec, args.replay_spec, args.ledger, args.data_root, args.archive, args.output):
            if path is not None and path.resolve().is_relative_to(root):
                raise IntegrityError('PRIVATE_STATE_OUTSIDE_REPOSITORY_REQUIRED')
        if args.mode == 'prepare':
            if args.spec is None or args.replay_spec is None:
                raise IntegrityError('PREPARATION_ARGUMENTS_REQUIRED')
            spec = prepare_spec(json.loads(args.replay_spec.read_text(encoding='utf-8-sig')), root)
            write_once(args.spec, spec)
            summary = {'status': 'SPEC_PREPARED', 'spec_hash': hash_value(spec)}
        elif args.mode == 'register':
            if args.spec is None or args.ledger is None:
                raise IntegrityError('REGISTRATION_ARGUMENTS_REQUIRED')
            spec = json.loads(args.spec.read_text(encoding='utf-8-sig'))
            if spec != prepare_spec(spec['replay_spec'], root):
                raise IntegrityError('ARCHIVED_REPLAY_SPEC_MISMATCH')
            fingerprint = hash_value(spec)
            TrialLedger(args.ledger).append({'kind': 'REGISTERED', 'identity': fingerprint,
                                             'spec_hash': fingerprint})
            summary = {'status': 'REGISTERED', 'spec_hash': fingerprint}
        else:
            if args.archive is None or args.output is None or args.output.exists():
                raise IntegrityError('NEW_PRIVATE_OUTPUT_AND_ARCHIVE_REQUIRED')
            archive = InputArchive(args.archive)
            if args.mode == 'restore':
                if args.manifest_sha256 is None:
                    raise IntegrityError('MANIFEST_REQUIRED')
                result = restore_and_replay(archive, args.manifest_sha256, root)
            else:
                if args.spec is None or args.ledger is None or args.data_root is None:
                    raise IntegrityError('RUN_ARGUMENTS_REQUIRED')
                spec = json.loads(args.spec.read_text(encoding='utf-8-sig'))
                result = run(spec, source_root=root, data_root=args.data_root,
                             archive=archive, ledger=TrialLedger(args.ledger))
            write_once(args.output, result)
            summary = {'status': 'REPLAY_COMPLETE', 'result_hash': hash_value(result)}
        print(json.dumps({**summary, 'approval_authority': False, 'fill_evidence': False}))
        return 0
    except (ValueError, OSError, KeyError, TypeError, AttributeError, sqlite3.Error, csv.Error):
        print(json.dumps({'status': 'BLOCKED', 'code': 'ARCHIVED_REPLAY_FAILED',
                          'approval_authority': False, 'fill_evidence': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
