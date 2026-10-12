"""Inactive payload projection: signed claims are not verified training evidence.

No repository, pandas, credential, network, model fitting or market-data reads.
Factory integration and referenced-source verification are separate pending work.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import math
from typing import cast


class ProjectionError(ValueError):
    """Stable errors without payload values or identifiers."""


RESERVED = frozenset({
    'decision_id', 'as_of_date', 'label_end_date', 'target_before_stop',
    'candidate_target_before_stop', 'excess_return', 'actual_forward_return',
    'market_regime', 'action', 'quote_available', 'decision_event_hash',
    'outcome_event_hash', 'training_eligible', 'row_structure_eligible',
    'reference_material_verified', 'eligibility_failures', 'production_evidence',
    'pit_verified', 'costs_applied', 'executable_quotes_verified', 'ledger_verified',
    'synthetic_fixture', 'calendar_proof_verified', 'production_tier_commissioned',
})


def _map(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(k) is not str for k in value):
        raise ProjectionError('PROJECTION_MAPPING_INVALID')
    return value


def _number(value: object) -> float | None:
    # Boolean flags are not numeric features; never coerce arbitrary objects.
    if type(value) not in (int, float):
        return None
    try:
        result = float(cast(int | float, value))
    except (ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _stamp(value: object) -> datetime | None:
    if type(value) is not str:
        return None
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None or result.utcoffset() is None:
            return None
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def project_claims(decision: Mapping[str, object], outcome: Mapping[str, object]) -> dict[str, object]:
    """Keep candidates separate from usable labels; no claim grants eligibility.

    Even TARGET/STOP and apparently complete coverage remain only candidate labels
    until a separate adapter verifies original ledger and referenced market proof.
    A finite forward return is retained on its own basis, never renamed excess/net.
    Invalid chronology cannot erase the row or turn its outcome into a loss.
    """
    decision, outcome = _map(decision), _map(outcome)
    features = _map(decision.get('features', {}))
    values = _map(features.get('values', {}))
    if len(values) > 1024 or any(len(name.encode('utf-8')) > 128 for name in values):
        raise ProjectionError('PROJECTION_FEATURE_BOUND')
    if (set(values) - {'market_regime'}).intersection(RESERVED):
        raise ProjectionError('PROJECTION_RESERVED_FEATURE_COLLISION')
    failures = ['original_ledger_not_verified', 'referenced_market_evidence_not_verified']
    start, end = _stamp(decision.get('decision_at')), _stamp(outcome.get('outcome_at'))
    if start is None or end is None or end < start:
        failures.append('chronology_unverified')
    candidate = 1 if outcome.get('outcome') == 'TARGET' else 0 if outcome.get('outcome') == 'STOP' else None
    if candidate is None:
        failures.append('target_stop_unknown')
    row: dict[str, object] = {
        'decision_id': decision.get('decision_id'), 'as_of_date': decision.get('decision_at'),
        'label_end_date': outcome.get('outcome_at'), 'action': decision.get('action'),
        'candidate_target_before_stop': candidate, 'target_before_stop': None,
        'actual_forward_return': _number(outcome.get('actual_forward_return')),
        'excess_return': None, 'training_eligible': False, 'reference_material_verified': False,
        'production_evidence': False, 'pit_verified': False, 'costs_applied': False,
        'executable_quotes_verified': False, 'ledger_verified': False,
        'calendar_proof_verified': False, 'production_tier_commissioned': False,
        'synthetic_fixture': None, 'eligibility_failures': failures,
    }
    regime = values.get('market_regime')
    if isinstance(regime, Mapping):
        regime = _map(regime).get('value')
    row['market_regime'] = regime if isinstance(regime, str) else None
    for name, value in values.items():
        if name == 'market_regime':
            continue
        if isinstance(value, Mapping):
            value = _map(value).get('value')
        number = _number(value)
        if number is not None:
            row[name] = number
    return row
