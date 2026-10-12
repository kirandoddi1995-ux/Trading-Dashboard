"""Owner opt-in launcher. Default preview is inert; no task or hosted changes.

Prepare a separate pre-open recipe, then date-pinned supervised polls through the
UNCHANGED scheduler's licence/auth/calendar/clock gates. Existing state is not
converted. Research observations are not approved suggestions or training labels.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
from pathlib import Path
from typing import Any, Callable, cast

from automated_development_checks import write_once
from forward_revision_evidence import private_read
from forward_versioned_producer import Producer, publish, recipe, validate_recipe
from research_integrity import IntegrityError, canonical
from research_replay_comparison import instant


def paths(root: Path, day: date) -> tuple[Path, Path, Path]:
    """Separate recipe, database and receipts, never replace old capture files."""
    import forward_nifty_schedule as schedule
    config, state = schedule.session_paths(root, day)
    namespace = state / 'versioned-v1'
    for path in (config, namespace):
        if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
            raise IntegrityError('VERSION_POLICY_PRIVATE_NAMESPACE_REQUIRED')
    return config, namespace / 'recipe.json', namespace / 'journal.sqlite'


def prepare(root: Path, day: date) -> dict[str, Any]:
    """Existing owner-file config first; NEW interpretation before open only."""
    import forward_nifty_schedule as schedule
    config_path, target, _ = paths(root, day)
    now = schedule.now()
    if now.astimezone(schedule.IST).date() != day:
        raise IntegrityError('VERSION_POLICY_DATE_MISMATCH')
    config = json.loads(private_read(config_path))
    frozen = recipe(config, now.isoformat())
    probe = cast(Callable[[], dict[str, Any]], getattr(schedule, 'measure_clock'))()
    if cast(Callable[..., str | None], getattr(schedule, 'clock_error'))(probe, now=schedule.now(), maximum_offset=1.0):
        raise IntegrityError('CLOCK_UNVERIFIED')
    # Re-measure after clock check; no freeze crossing the open.
    frozen = recipe(config, schedule.now().isoformat())
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise IntegrityError('VERSION_POLICY_RECIPE_ALREADY_PREPARED')
    write_once(target, frozen)
    return {'status': 'VERSION_POLICY_PREPARED', 'decisions_added': 0,
            'training_eligible': False, 'approval_authority': False}


def run(root: Path, day: date, mode: str) -> int:
    """Explicit process-scoped replacement; always restore original job bindings."""
    import forward_nifty_job as job
    import forward_nifty_schedule as schedule
    if mode not in ('poll', 'audit'):
        raise IntegrityError('VERSION_POLICY_MODE_INVALID')
    config_path, recipe_path, journal = paths(root, day)
    config = json.loads(private_read(config_path))
    frozen = json.loads(private_read(recipe_path))
    validate_recipe(config, frozen)
    if schedule.now().astimezone(schedule.IST).date() != day:
        raise IntegrityError('VERSION_POLICY_DATE_MISMATCH')
    if mode == 'audit':
        if schedule.now() < instant(config['session_close']) + timedelta(minutes=5):
            raise IntegrityError('VERSION_POLICY_POSTCLOSE_AUDIT_REQUIRED')
        if not journal.is_file():
            raise IntegrityError('VERSION_POLICY_JOURNAL_MISSING')
        producer = Producer(config, frozen, journal)
        bundle = producer.bundle()
        print(json.dumps({'status': 'VERSIONED_LOCAL_AUDIT_PASSED',
            'raw_polls': len(bundle['polls']), 'recorded_decisions': bundle['recorded_decisions'],
            'missing_decisions': bundle['missing_decisions'],
            'remote_custody_verified': False, 'training_eligible': False, 'approval_authority': False}))
        return 0
    originals = {name: getattr(job, name) for name in ('Producer', 'publish', 'write_once', 'failure_category')}
    def build(received_config: dict[str, Any], old_journal: Path, unused_archive: Any) -> Producer:
        if canonical(received_config) != canonical(config) or old_journal.parent != journal.parent.parent:
            raise IntegrityError('VERSION_POLICY_RECIPE_MISMATCH')
        return Producer(config, frozen, journal)
    def receipt(path: Path, record: dict[str, Any]) -> None:
        if path.parent != journal.parent.parent or not path.name.startswith(('receipt-', 'failure-')):
            raise IntegrityError('VERSION_POLICY_PRIVATE_NAMESPACE_REQUIRED')
        directory = journal.parent / 'receipts'
        if any(p.is_symlink() or p.is_junction() for p in (directory, *directory.parents)):
            raise IntegrityError('VERSION_POLICY_PRIVATE_NAMESPACE_REQUIRED')
        directory.mkdir(exist_ok=True)
        originals['write_once'](directory / path.name, record)
    def classify(error: Exception) -> str:
        if isinstance(error, IntegrityError) and str(error).startswith('VERSION_POLICY_'):
            return 'VERSION_POLICY_VALIDATION_FAILED'
        return str(originals['failure_category'](error))
    try:
        for name, replacement in {'Producer': build, 'publish': publish,
                                  'write_once': receipt, 'failure_category': classify}.items():
            setattr(job, name, replacement)
        return schedule.main(['--root', str(root), '--mode', 'poll', '--confirm-run'])
    finally:
        for name, value in originals.items():
            setattr(job, name, value)


def main(argv: list[str] | None = None) -> int:
    """Preview never reads config, state, credentials or clocks."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--session-date', type=date.fromisoformat, required=True)
    parser.add_argument('--mode', choices=('prepare-policy', 'poll', 'audit'), default='poll')
    parser.add_argument('--confirm-versioned-research', action='store_true')
    args = parser.parse_args(argv)
    if not args.confirm_versioned_research:
        print(json.dumps({'status': 'PREVIEW', 'network_calls': 0, 'credential_reads': 0,
                          'writes': 0, 'approval_authority': False}))
        return 0
    try:
        if args.mode == 'prepare-policy':
            print(json.dumps(prepare(args.root, args.session_date)))
            return 0
        return run(args.root, args.session_date, args.mode)
    except Exception as error:
        category = 'VERSION_POLICY_VALIDATION_FAILED' if isinstance(error, IntegrityError) else 'LOCAL_LAUNCHER_FAILURE'
        print(json.dumps({'status': 'BLOCKED', 'code': 'VERSIONED_CAPTURE_LAUNCHER_BLOCKED',
                          'stage': 'VERSIONED_LAUNCHER', 'category': category,
                          'training_eligible': False, 'approval_authority': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
