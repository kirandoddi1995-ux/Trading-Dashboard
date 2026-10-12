"""Explicit pre-open empty journal for raw-only capture; never creates decisions.

No credentials or network. Existing state is never repaired, reset or removed.
Partial initialization stays present for owner review and prevents a retry.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from forward_local_diagnostic import inspect_session, local_category
from forward_nifty_producer import ROOT, Producer, validate_config
from research_input_archive import InputArchive
from research_integrity import IntegrityError
from research_replay_comparison import instant


def prepare(root: Path, day: date, clock: Callable[[], datetime]) -> dict[str, Any]:
    """Create only a new empty schema before open, using a validated frozen config."""
    config_path = root / day.isoformat() / 'config.json'
    state = config_path.parent / 'state'
    for path in (root, config_path, state):
        if (not path.is_absolute() or path.resolve().is_relative_to(ROOT)
                or any(p.is_symlink() or p.is_junction() for p in (path, *path.parents))):
            raise IntegrityError('LOCAL_STATE_PRIVATE_PATH_REQUIRED')
    def read_config() -> bytes:
        with config_path.open('rb') as handle:
            value = handle.read(1024 * 1024 + 1)
        if not 0 < len(value) <= 1024 * 1024:
            raise IntegrityError('LOCAL_STATE_SIZE_BOUND')
        return value

    raw = read_config()
    config = json.loads(raw)
    validate_config(config, ROOT)
    opening = instant(config['session_open'])

    def preopen() -> None:
        current = clock()
        if (current.tzinfo is None or current.utcoffset() is None
                or current.astimezone(ZoneInfo('Asia/Kolkata')).date() != day
                or opening.astimezone(ZoneInfo('Asia/Kolkata')).date() != day
                or not instant(config['frozen_at']) <= current < opening):
            raise IntegrityError('EMPTY_JOURNAL_PREOPEN_REQUIRED')

    preopen()
    # Exclusive ownership of this entirely new directory; no existing-state edits.
    state.mkdir()
    Producer(config, state / 'observations.sqlite', InputArchive(state / 'inputs'))
    result = inspect_session(root, day)
    if (result['counts']['observations'] != 0 or result['counts']['forward_context'] != 0
            or result['producer_lock_exists']):
        raise IntegrityError('EMPTY_JOURNAL_VERIFICATION_FAILED')
    if read_config() != raw:
        raise IntegrityError('FORWARD_CONFIG_MISMATCH')
    preopen()
    return {'status': 'EMPTY_QUARANTINE_JOURNAL_PREPARED', 'session_date': day.isoformat(),
            'recorded_decisions': 0, 'missing_decisions': 75, 'network_calls': 0,
            'credential_reads': 0, 'state_created': True, 'decision_capture_enabled': False,
            'training_eligible': False, 'approval_authority': False, 'fill_evidence': False}


def main(argv: list[str] | None = None) -> int:
    """Inert preview by default; safe categories, never exception text or prices."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--session-date', type=date.fromisoformat)
    parser.add_argument('--confirm-prepare-empty-journal', action='store_true')
    args = parser.parse_args(argv)
    if not args.confirm_prepare_empty_journal:
        print(json.dumps({'status': 'PREVIEW', 'network_calls': 0, 'credential_reads': 0,
                          'writes': 0, 'approval_authority': False}))
        return 0
    try:
        if args.session_date is None:
            raise IntegrityError('EMPTY_JOURNAL_PREOPEN_REQUIRED')
        from forward_nifty_schedule import now
        print(json.dumps(prepare(args.root, args.session_date, now)))
        return 0
    except Exception as error:
        category = local_category(error)
        if isinstance(error, IntegrityError) and str(error) in {
                'EMPTY_JOURNAL_PREOPEN_REQUIRED', 'EMPTY_JOURNAL_VERIFICATION_FAILED'}:
            category = str(error)
        print(json.dumps({'status': 'BLOCKED', 'code': 'EMPTY_JOURNAL_PREPARATION_FAILED',
                          'category': category or 'UNCLASSIFIED_FAILURE',
                          'partial_state_action': 'RETAIN_AND_REVIEW_DO_NOT_RETRY',
                          'approval_authority': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
