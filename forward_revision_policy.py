"""Inactive as-of source policy foundation; no signals, IO or live admission.

Every numeric revision is retained and annotated, never called trivial. Selected
inputs and source hashes are frozen per cutoff; later corrections cannot rewrite
that projection. This does not commission decision capture or training.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from typing import Any

from forward_revision_evidence import versions_as_of
from forward_revision_quarantine import verify
from research_integrity import IntegrityError, canonical, hash_value
from research_replay_comparison import instant


def specification() -> dict[str, Any]:
    """Fixed candidate semantics, with no tunable tolerance or finality delay."""
    return {'version': 'nifty-received-version-policy-v1-review-only',
            'selection': 'LATEST_ACTUALLY_RECEIVED_AT_OR_BEFORE_CUTOFF',
            'numeric_revision': 'EXACT_CHANGE_RETAIN_AND_ANNOTATE',
            'trivial_revision': 'NUMERIC_EQUALITY_ONLY',
            'missing_prefix': 'BLOCK_CANDIDATE', 'source_age_limit_seconds': 120,
            'session': 'ORIGINAL_FROZEN_INDEX_WINDOW_NOT_DERIVATIVE_HOURS',
            'finality': 'NOT_ESTABLISHED', 'decision_eligible': False,
            'training_eligible': False, 'approval_authority': False}


def project(records: list[dict[str, Any]], cutoff: str) -> dict[str, Any]:
    """Build hash-bound candidate inputs; no future receipts or silent corrections.

Input consists of verified raw snapshots, not fabricated earlier availability.
An empty input is missing evidence. Values are returned only to the caller;
there is deliberately no CLI that prints private prices or writes a journal.
"""
    end = instant(cutoff)
    if len(records) > 75:
        raise IntegrityError('REVISION_POLICY_SIZE_BOUND')
    available = []
    for record in records:
        # Validate the envelope before accessing timestamps. Never trust a claimed
        # eligibility flag or malformed supplied source, even outside the cutoff.
        verify(canonical(record))
        if instant(record['received_at']) <= end:
            available.append(record)
    available.sort(key=lambda row: instant(row['received_at']))
    selected = deepcopy(versions_as_of(available, end.isoformat())['bars'])
    missing: list[str] = []
    annotations: list[dict[str, Any]] = []
    blockers = []
    if not available:
        blockers.append('NO_RECEIVED_SOURCE_AT_CUTOFF')
    else:
        config = available[0]['config']
        opening, closing = instant(config['session_open']), instant(config['session_close'])
        if not opening < end <= closing + timedelta(seconds=120):
            raise IntegrityError('REVISION_POLICY_OUTSIDE_FROZEN_WINDOW')
        count = min(75, int((end - opening).total_seconds() // 300))
        actual = {row['bar_start'] for row in selected}
        missing = [(opening + timedelta(minutes=5 * index)).isoformat()
                   for index in range(count)
                   if (opening + timedelta(minutes=5 * index)).isoformat() not in actual]
        if not count or missing:
            blockers.append('MISSING_COMPLETED_PREFIX')
        if end - instant(available[-1]['received_at']) > timedelta(seconds=120):
            blockers.append('STALE_RECEIVED_SOURCE')
        seen: dict[str, list[Any]] = {}
        versions: dict[tuple[str, str], list[Any]] = {}
        for record in available:
            rows = [(row['start'], row['values'], row['available_at']) for row in record['accepted_baseline']]
            rows += [(row['start'], row['values'], row['received_at']) for row in record['closed_bars']]
            for start, values, known in rows:
                versions[(instant(known).isoformat(), instant(start).isoformat())] = values
        for (known, key), values in sorted(versions.items()):
            if key in seen and seen[key] != values:
                fields = [field for field, old, new in zip(
                    ('open', 'high', 'low', 'close', 'volume', 'open_interest'), seen[key], values)
                    if old != new]
                annotations.append({'bar_start': key, 'known_at': known,
                                    'changed_fields': fields, 'classification': 'SOURCE_REVISION_REVIEW'})
            seen[key] = values
    result = {'format': 'nifty-version-input-projection-v1', 'policy_sha256': hash_value(specification()),
              'cutoff': end.isoformat(), 'source_sha256s': [hash_value(row) for row in available],
              'bars': selected, 'missing_bar_starts': missing, 'revision_annotations': annotations,
              'status': 'BLOCKED' if blockers else 'INPUT_CANDIDATE_ONLY', 'blockers': blockers,
              'finality': 'NOT_ESTABLISHED', 'decision_eligible': False,
              'training_eligible': False, 'approval_authority': False, 'fill_evidence': False}
    return {**result, 'projection_sha256': hash_value(result)}
