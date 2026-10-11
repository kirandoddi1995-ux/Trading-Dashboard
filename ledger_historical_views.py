"""Bounded read-only research/readiness views over one verified original cut.

No SQL writes, runtime factory activation, credential discovery or model fitting.
Original decision features and outcome facts only: no current-price reconstruction,
unknown-as-loss labelling, HMAC upgrade, production permission or holdout access.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import cast

from evidence_ledger import canonical_json
from ledger_history_consumers import LedgerHistoryConsumers, audit_history
from ledger_history_stream import HistoryWitness

MAX_RESULT_ROWS = 20_000
MAX_RESULT_BYTES = 32 * 1024 * 1024


class ViewError(ValueError):
    """Unusable view is not an empty or apparently successful research dataset."""


@dataclass(frozen=True)
class DatasetRows:
    """Detached rows plus same-cut provenance; caller may construct a DataFrame."""

    rows: tuple[dict[str, object], ...]
    attributes: Mapping[str, object]


def _map(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ViewError('HISTORICAL_PAYLOAD_SHAPE_INVALID')
    return dict(value)


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(cast(str | int | float, value))
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _instant(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if instant.utcoffset() is None:
            return None
        return instant.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _readiness(decision_event: dict[str, object], outcome_event: dict[str, object] | None,
               witness: HistoryWitness) -> dict[str, object]:
    """Derive quality facts, never authorization, from exact original event rows."""
    decision = _map(decision_event['payload'])
    outcome = {} if outcome_event is None else _map(outcome_event['payload'])
    identifiers = _map(decision.get('identifiers'))
    features = _map(decision.get('features'))
    feature_values = _map(features.get('values'))
    universe = _map(decision.get('universe'))
    quote = _map(decision.get('quote'))
    costs = _map(decision.get('costs'))
    quality = _map(decision.get('feature_quality'))
    failures: list[str] = []
    if features.get('status') != 'AVAILABLE' or not feature_values:
        failures.append('PIT features unavailable')
    if not isinstance(decision.get('decision_id'), str) or not decision['decision_id']:
        failures.append('decision identity unavailable')
    if (any(not isinstance(identifiers.get(name), str) or not identifiers[name]
            for name in ('strategy_id', 'target_version'))
            or type(identifiers.get('horizon_sessions')) is not int
            or cast(int, identifiers.get('horizon_sessions')) <= 0):
        failures.append('decision scope unverified')
    if any(_number(value.get('value') if isinstance(value, Mapping) else value) is None
           for name, value in feature_values.items() if name != 'market_regime'):
        failures.append('numeric feature values unavailable')
    if universe.get('status') != 'VERIFIED':
        failures.append('PIT universe unverified')
    # Missing feature quality is not an implicit PASS in this original-only view.
    if quality.get('status') != 'PASS':
        failures.append('feature quality unverified')
    if costs.get('breakdown_complete') is not True:
        failures.append('transaction costs incomplete')
    if (quote.get('status') != 'AVAILABLE' or _number(quote.get('bid')) is None
            or _number(quote.get('ask')) is None):
        failures.append('executable bid/ask unavailable')
    else:
        bid, ask = _number(quote['bid']), _number(quote['ask'])
        if bid is None or ask is None or not 0 < bid <= ask:
            failures.append('executable bid/ask invalid')
    if witness.unsigned_events or witness.hmac_events == 0:
        failures.append('complete original signature coverage unavailable')
    start, end = _instant(decision.get('decision_at')), _instant(outcome.get('outcome_at'))
    recorded = _instant(decision_event['recorded_at'])
    outcome_recorded = None if outcome_event is None else _instant(outcome_event['recorded_at'])
    if (start is None or recorded is None or start > recorded
            or (outcome_event is not None and (end is None or end <= start
                or outcome_recorded is None or end > outcome_recorded))):
        failures.append('decision/outcome chronology unverified')
    label = outcome.get('outcome')
    # Binary target-before-stop labels require an explicit known target/stop fact.
    # Other terminal outcomes remain visible and unlabelled, never coerced to 0.
    known_label = label in ('TARGET', 'STOP')
    if outcome_event is not None and not known_label:
        failures.append('target/stop outcome unknown')
    realized = _number(outcome.get('actual_forward_return'))
    if outcome_event is not None and realized is None:
        failures.append('realized return unavailable')
    if outcome_event is not None:
        horizon = identifiers.get('horizon_sessions')
        if (outcome.get('decision_id') != decision.get('decision_id')
                or outcome.get('target_version') != identifiers.get('target_version')
                or type(outcome.get('horizon_sessions')) is not int
                or outcome.get('horizon_sessions') != horizon):
            failures.append('outcome scope proof unavailable')
        proof = outcome.get('source_observation_ids')
        if (not isinstance(proof, list) or not proof
                or any(not isinstance(item, str) or not item for item in proof)):
            failures.append('outcome source proof unavailable')
        closes = outcome.get('completed_session_closes')
        if not isinstance(closes, list) or len(closes) > 2048:
            failures.append('completed-session proof unavailable')
        else:
            instants = [_instant(item) for item in closes]
            valid = {item for item in instants if item is not None}
            if (len(valid) != len(instants) or start is None or outcome_recorded is None
                    or any(item <= start or item > outcome_recorded for item in valid)
                    or type(horizon) is not int or len(valid) < horizon):
                failures.append('completed-session proof unavailable')
        if outcome.get('coverage_complete') is False or outcome.get('first_touch_known') is False:
            failures.append('outcome coverage/first-touch incomplete')
    return {'decision_id': decision.get('decision_id'), 'decision_at': decision.get('decision_at'),
            'decision_recorded_at': decision_event['recorded_at'],
            'asset_class': identifiers.get('asset_class'), 'strategy_id': identifiers.get('strategy_id'),
            'target_version': identifiers.get('target_version'), 'horizon_sessions': identifiers.get('horizon_sessions'),
            'action': decision.get('action'), 'feature_names': sorted(feature_values),
            'matured': outcome_event is not None, 'outcome_at': outcome.get('outcome_at'),
            'matured_at': outcome.get('matured_at') or (None if outcome_event is None else outcome_event['recorded_at']),
            'outcome': label, 'actual_forward_return': realized,
            'actual_costs': _map(outcome.get('actual_costs')),
            'row_structure_eligible': outcome_event is not None and not failures,
            # The ledger verifies signed REFERENCES, not every referenced quote,
            # session calendar, cost source or retained scanner record. No training
            # promotion until source-specific readers/provenance are commissioned.
            'training_eligible': False, 'reference_material_verified': False,
            'eligibility_failures': failures,
            'decision_event_hash': decision_event['event_hash'],
            'outcome_event_hash': None if outcome_event is None else outcome_event['event_hash'],
            'approval_authority': False}


def _append(rows: list[dict[str, object]], row: dict[str, object], size: int) -> int:
    size += len(canonical_json(row).encode())
    if len(rows) >= MAX_RESULT_ROWS or size > MAX_RESULT_BYTES:
        raise ViewError('HISTORICAL_RESULT_REQUIRES_STREAMING')
    rows.append(row)
    return size


class LedgerHistoricalViews:
    """Repository-shaped read APIs; every dataset/readiness view pins ONE cut."""

    def __init__(self, history: LedgerHistoryConsumers):
        if not isinstance(history, LedgerHistoryConsumers):
            raise ViewError('HISTORICAL_CONSUMER_REQUIRED')
        self._history = history

    def events(self, aggregate: str) -> list[dict[str, object]]:
        """Original, detached compatibility rows, not an append interface."""
        return [{**row, 'duplicate': False} for row in self._history.events(aggregate)]

    def audit(self) -> dict[str, object]:
        """Continuity and original signature coverage remain separate facts."""
        return self._history.audit()

    def decision_outcome_records(self) -> list[dict[str, object]]:
        """Include unmatured decisions; first outcome by original sequence only."""
        rows: list[dict[str, object]] = []
        size = 0
        with self._history.history() as history:
            for decision, outcome in history.decision_pairs(include_unmatured=True, first_outcome=True):
                size = _append(rows, _readiness(decision, outcome, history.witness), size)
        return rows

    def matured_decision_rows(self, *, strategy_id: str, target_version: str,
                              horizon_sessions: int) -> DatasetRows:
        """Frozen features and all original outcomes, with unknown labels intact.

        No model fitting, costs reconstruction, data download or permission to use
        sealed periods. Projection does not establish calibration/production tier.
        Hash/continuity/signature facts come from the SAME staged witness as rows,
        not a second live audit that could race the dataset read.
        """
        if (not isinstance(strategy_id, str) or not 1 <= len(strategy_id.encode()) <= 128
                or not isinstance(target_version, str) or not 1 <= len(target_version.encode()) <= 128
                or type(horizon_sessions) is not int or not 1 <= horizon_sessions <= (1 << 31)-1):
            raise ViewError('HISTORICAL_DATASET_SCOPE_INVALID')
        rows: list[dict[str, object]] = []
        size = 0
        unmatched = 0
        unknown_labels = 0
        pit_ok, costs_ok, quotes_ok = True, True, True
        with self._history.history() as history:
            for decision_event, outcome_event in history.decision_pairs():
                if outcome_event is None:
                    raise ViewError('HISTORICAL_MATURED_PAIR_INVALID')
                decision, outcome = _map(decision_event['payload']), _map(outcome_event['payload'])
                identifiers = _map(decision.get('identifiers'))
                if (identifiers.get('strategy_id') != strategy_id
                        or identifiers.get('target_version') != target_version
                        or type(identifiers.get('horizon_sessions')) is not int
                        or identifiers.get('horizon_sessions') != horizon_sessions):
                    unmatched += 1
                    continue
                quality = _readiness(decision_event, outcome_event, history.witness)
                features = _map(decision.get('features'))
                values = _map(features.get('values'))
                regime = values.get('market_regime')
                if isinstance(regime, Mapping):
                    regime = regime.get('value')
                flattened: dict[str, object] = {}
                for name, value in values.items():
                    if name == 'market_regime':
                        continue  # explicit categorical projection, not a numeric override
                    candidate = value.get('value') if isinstance(value, Mapping) else value
                    numeric = _number(candidate)
                    if numeric is not None:
                        flattened[name] = numeric
                failures = cast(list[str], quality['eligibility_failures'])
                pit_ok = pit_ok and not any(reason in failures for reason in
                    ('PIT features unavailable', 'PIT universe unverified', 'feature quality unverified',
                     'numeric feature values unavailable'))
                costs_ok = costs_ok and 'transaction costs incomplete' not in failures
                quotes_ok = quotes_ok and not any(reason in failures for reason in
                    ('executable bid/ask unavailable', 'executable bid/ask invalid'))
                label = 1 if outcome.get('outcome') == 'TARGET' else 0 if outcome.get('outcome') == 'STOP' else None
                if any(reason in failures for reason in ('outcome scope proof unavailable',
                        'outcome source proof unavailable', 'completed-session proof unavailable',
                        'outcome coverage/first-touch incomplete', 'decision/outcome chronology unverified')):
                    label = None
                unknown_labels += int(label is None)
                row: dict[str, object] = {'decision_id': decision.get('decision_id'), 'as_of_date': decision.get('decision_at'),
                       'label_end_date': outcome.get('outcome_at'), 'target_before_stop': label,
                       # Forward return is not automatically benchmark excess,
                       # net P&L or an executable derivative return.
                       'excess_return': None, 'actual_forward_return': quality['actual_forward_return'],
                       'market_regime': None if regime is None else str(regime),
                       'action': decision.get('action'), 'quote_available': not any(reason in failures for reason in
                           ('executable bid/ask unavailable', 'executable bid/ask invalid')),
                       'decision_event_hash': decision_event['event_hash'],
                       'outcome_event_hash': outcome_event['event_hash'],
                       'training_eligible': quality['training_eligible'],
                       'row_structure_eligible': quality['row_structure_eligible'],
                       'reference_material_verified': False,
                       'eligibility_failures': failures}
                # Features may NOT overwrite identity, target, quality or provenance.
                if (set(values) - {'market_regime'}).intersection(row):
                    raise ViewError('HISTORICAL_FEATURE_NAME_COLLISION')
                row.update(flattened)
                size = _append(rows, row, size)
            audit = audit_history(history)
            attributes: dict[str, object] = {
                'evidence_source': 'immutable-decision-spine',
                # These original payload fields are claims, not verification of
                # the external referenced material. Never satisfy a training
                # consumer's proof flags just because the claim was signed.
                'pit_verified': False, 'costs_applied': False, 'executable_quotes_verified': False,
                'original_pit_claims_complete': bool(rows) and pit_ok,
                'original_cost_claims_complete': bool(rows) and costs_ok,
                'original_quote_claims_complete': bool(rows) and quotes_ok,
                'ledger_verified': True, 'ledger_audit': audit,
                'production_evidence': False, 'production_tier_commissioned': False,
                'reference_material_verified': False, 'calendar_proof_verified': False,
                'synthetic_fixture': None, 'strategy_version': strategy_id, 'target_version': target_version,
                'horizon_sessions': horizon_sessions, 'unknown_target_stop_labels': unknown_labels,
                'target_stop_labels_complete': bool(rows) and unknown_labels == 0,
                'unmatched_identifier_pairs': unmatched, 'history_sha256': history.witness.sha256,
                'approval_authority': False}
        return DatasetRows(tuple(rows), attributes)
