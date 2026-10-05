"""Offline archive-to-observation self-check; no collection or approval power."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from archived_directional_replay import ReplayReference, restore_and_replay
from automated_development_checks import write_once
from research_input_archive import InputArchive
from research_integrity import IntegrityError, hash_value
from research_replay_comparison import Observation, ObservationJournal, compare_session


def check(*, archive: InputArchive, manifest_sha256: str, journal_path: Path,
          source_root: Path, computed_at: str) -> dict[str, Any]:
    """Compare every accepted regular session; absent journal never becomes healthy.

    The historical development archive is reconstructed, not captured. Its source
    environment and hashes must still match. No journal is created when absent.
    Excluded sessions stay visible; a partial calendar cannot claim full coverage.
    """
    if journal_path.resolve().is_relative_to(Path(__file__).resolve().parent):
        raise IntegrityError('PRIVATE_OBSERVATIONS_OUTSIDE_REPOSITORY_REQUIRED')
    if journal_path.is_symlink():
        raise IntegrityError('OBSERVATION_SYMLINK_FORBIDDEN')
    recovered = restore_and_replay(archive, manifest_sha256, source_root)
    report = recovered['report']
    journal = ObservationJournal(journal_path, read_only=True) if journal_path.is_file() else None
    grouped: dict[str, list[Observation]] = {}
    for payload in recovered['references']:
        reference = ReplayReference(payload).for_comparison(computed_at)
        grouped.setdefault(reference.session_open, []).append(reference)
    sessions = []
    for opening, references in grouped.items():
        observed = journal.read(recovered['comparison_spec_hash'], opening) if journal is not None else []
        sessions.append(compare_session(spec_hash=recovered['comparison_spec_hash'],
                                        session_open=opening, session_close=references[0].session_close,
                                        observed=observed, replayed=references))
    exclusions = report['excluded_sessions']
    complete = bool(sessions) and not exclusions and all(row['status'] == 'MATCH' for row in sessions)
    return {'version': 'offline-replay-check-v1',
            'status': 'CHECKS_PASS' if complete else 'ATTENTION_REQUIRED',
            'journal_present': journal is not None, 'manifest_sha256': manifest_sha256,
            'comparison_spec_hash': recovered['comparison_spec_hash'],
            'accepted_sessions': len(sessions), 'excluded_sessions': exclusions, 'sessions': sessions,
            'available_decision_matches': sum(row['available_decision_matches'] for row in sessions),
            'unavailable_decision_matches': sum(row['unavailable_decision_matches'] for row in sessions),
            'approval_authority': False, 'fill_evidence': False,
            'live_capture_verified': False, 'automatic_actions': []}


def main(argv: list[str] | None = None) -> int:
    """Write a private diagnostic; exit 1 for incomplete checks, 2 for failed checks."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--journal', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        root = Path(__file__).resolve().parent
        if any(path.resolve().is_relative_to(root) for path in (args.archive, args.journal, args.output)):
            raise IntegrityError('PRIVATE_STATE_OUTSIDE_REPOSITORY_REQUIRED')
        if args.output.exists():
            raise IntegrityError('NEW_OUTPUT_REQUIRED')
        result = check(archive=InputArchive(args.archive), manifest_sha256=args.manifest_sha256,
                       journal_path=args.journal, source_root=root,
                       computed_at=datetime.now(timezone.utc).isoformat())
        write_once(args.output, result)
        print(json.dumps({'status': result['status'], 'result_hash': hash_value(result),
                          'accepted_sessions': result['accepted_sessions'],
                          'approval_authority': False, 'fill_evidence': False}))
        return 0 if result['status'] == 'CHECKS_PASS' else 1
    except (ValueError, OSError, KeyError, TypeError, AttributeError, sqlite3.Error):
        print(json.dumps({'status': 'BLOCKED', 'code': 'OFFLINE_REPLAY_CHECK_FAILED',
                          'approval_authority': False, 'fill_evidence': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
