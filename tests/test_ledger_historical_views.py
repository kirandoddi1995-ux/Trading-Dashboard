"""Synthetic originals and detached research views; no market files or network."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any, cast

import pytest

from evidence_ledger import ImmutableEvidenceLedger
from ledger_history_consumers import ConsumerReadError, LedgerHistoryConsumers
from ledger_history_stream import VerifiedHistory, stage
import ledger_historical_views as views

NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)
KEY = b'synthetic-view-original-key-only'


class Source:
    def __init__(self, rows: list[dict[str, Any]], keys: dict[str, bytes]) -> None:
        self.rows = rows
        self.keys = keys
        self.calls = 0
        self.fail = False
        self.heads = {str(row['aggregate_id']): (int(row['sequence_no']), str(row['event_hash'])) for row in rows}

    @contextmanager
    def staged_history(self, private_parent: Path) -> Iterator[VerifiedHistory]:
        self.calls += 1
        def fence() -> None:
            if self.fail:
                raise ValueError('private endpoint must not escape')
        with stage(self.rows, expected_heads=self.heads, keyring=self.keys,
                   private_parent=private_parent, end_fence=fence) as history:
            yield history


@pytest.fixture
def make(tmp_path: Path, monkeypatch: Any) -> Any:
    monkeypatch.setattr('evidence_ledger._utcnow', lambda: NOW)
    counter = 0

    def factory(*, decision_change: dict[str, object] | None = None,
                outcome_change: dict[str, object] | None = None,
                outcomes: int = 1, signed: bool = True) -> tuple[views.LedgerHistoricalViews, Source]:
        nonlocal counter
        counter += 1
        ledger = ImmutableEvidenceLedger(sqlite3.connect, str(tmp_path / f'synthetic-{counter}.sqlite'), KEY if signed else b'')
        decision: dict[str, object] = {
            'decision_id': 'synthetic-decision', 'decision_at': '2024-01-02T09:20:00+05:30',
            'identifiers': {'asset_class': 'NIFTY_RESEARCH', 'strategy_id': 'frozen',
                            'target_version': 'synthetic-v1', 'horizon_sessions': 1},
            'features': {'status': 'AVAILABLE', 'values': {'rsi': {'value': 55}, 'market_regime': {'value': 'NORMAL'}}},
            'universe': {'status': 'VERIFIED'}, 'feature_quality': {'status': 'PASS'},
            'quote': {'status': 'AVAILABLE', 'bid': 100, 'ask': 101},
            'costs': {'breakdown_complete': True}, 'action': 'LONG'}
        decision.update(decision_change or {})
        ledger.append(aggregate_id='one', event_type='DECISION_EVALUATED', payload=decision,
                      idempotency_key='synthetic-decision')
        for index in range(outcomes):
            outcome: dict[str, object] = {'outcome': 'TARGET' if index == 0 else 'STOP',
                                         'outcome_at': '2024-01-02T10:20:00+05:30',
                                         'actual_forward_return': .1, 'actual_costs': {'total': 20},
                                         'decision_id': 'synthetic-decision', 'target_version': 'synthetic-v1',
                                         'horizon_sessions': 1, 'source_observation_ids': ['synthetic-source'],
                                         'completed_session_closes': ['2024-01-02T15:30:00+05:30']}
            outcome.update(outcome_change or {})
            ledger.append(aggregate_id='one', event_type='OUTCOME_MATURED', payload=outcome,
                          idempotency_key=f'synthetic-outcome-{index}')
        rows = ledger.events('one')
        keys = {str(rows[0]['key_id']): KEY} if signed else {}
        source = Source(rows, keys)
        return views.LedgerHistoricalViews(LedgerHistoryConsumers(source, tmp_path)), source
    return factory


def dataset(view: views.LedgerHistoricalViews) -> views.DatasetRows:
    return view.matured_decision_rows(strategy_id='frozen', target_version='synthetic-v1', horizon_sessions=1)


def test_same_cut_frozen_features_original_hashes_and_no_production_authority(make: Any) -> None:
    view, source = make()
    result = dataset(view)
    assert source.calls == 1  # NOT a second live audit after constructing the dataset.
    row = result.rows[0]
    assert row['rsi'] == 55 and row['market_regime'] == 'NORMAL'
    assert row['actual_forward_return'] == .1 and row['excess_return'] is None
    assert row['target_before_stop'] == 1 and row['row_structure_eligible'] is True
    assert row['training_eligible'] is False and row['reference_material_verified'] is False
    assert row['decision_event_hash'] == source.rows[0]['event_hash']
    assert row['outcome_event_hash'] == source.rows[1]['event_hash']
    audit = cast(dict[str, object], result.attributes['ledger_audit'])
    assert audit['events'] == 2
    assert audit['history_sha256'] == result.attributes['history_sha256']
    assert result.attributes['production_evidence'] is False
    assert result.attributes['production_tier_commissioned'] is False
    assert result.attributes['synthetic_fixture'] is None  # source origin is not asserted by this projection
    assert result.attributes['approval_authority'] is False
    for name in ('pit_verified', 'costs_applied', 'executable_quotes_verified'):
        assert result.attributes[name] is False
    for name in ('original_pit_claims_complete', 'original_cost_claims_complete', 'original_quote_claims_complete'):
        assert result.attributes[name] is True


def test_readiness_first_outcome_and_dataset_all_outcomes_preserve_join_semantics(make: Any) -> None:
    view, _ = make(outcomes=2)
    readiness = view.decision_outcome_records()
    assert len(readiness) == 1 and readiness[0]['outcome'] == 'TARGET'
    result = dataset(view)
    assert [row['target_before_stop'] for row in result.rows] == [1, 0]


def test_unmatured_decisions_stay_visible_without_a_fabricated_outcome(make: Any) -> None:
    view, _ = make(outcomes=0)
    row = view.decision_outcome_records()[0]
    assert row['matured'] is False and row['training_eligible'] is False
    assert row['outcome'] is None and row['outcome_at'] is None and row['outcome_event_hash'] is None
    result = dataset(view)
    assert result.rows == () and result.attributes['target_stop_labels_complete'] is False


@pytest.mark.parametrize('label', [None, 'UNKNOWN', 'NO_TOUCH', 'COVERAGE_UNKNOWN', 'target', False])
def test_unknown_target_stop_is_retained_unlabelled_not_as_zero(label: object, make: Any) -> None:
    view, _ = make(outcome_change={'outcome': label})
    result = dataset(view)
    assert len(result.rows) == 1 and result.rows[0]['target_before_stop'] is None
    assert result.rows[0]['training_eligible'] is False
    assert result.attributes['unknown_target_stop_labels'] == 1
    assert result.attributes['target_stop_labels_complete'] is False


@pytest.mark.parametrize('change,reason', [
    ({'feature_quality': None}, 'feature quality unverified'),
    ({'features': {'status': 'AVAILABLE', 'values': {}}}, 'PIT features unavailable'),
    ({'features': {'status': 'AVAILABLE', 'values': {'rsi': None}}}, 'numeric feature values unavailable'),
    ({'universe': None}, 'PIT universe unverified'),
    ({'costs': {'breakdown_complete': 'true'}}, 'transaction costs incomplete'),
    ({'quote': {'status': 'AVAILABLE', 'bid': 101, 'ask': 100}}, 'executable bid/ask invalid'),
    ({'quote': {'status': 'AVAILABLE', 'bid': True, 'ask': 100}}, 'executable bid/ask unavailable'),
    ({'decision_id': None}, 'decision identity unavailable')])
def test_missing_evidence_never_becomes_a_default_pass(change: dict[str, object], reason: str, make: Any) -> None:
    view, _ = make(decision_change=change)
    row = dataset(view).rows[0]
    assert row['row_structure_eligible'] is False and reason in cast(list[str], row['eligibility_failures'])


@pytest.mark.parametrize('stamp', ['2024-01-02T03:49:00+00:00', '2024-01-02T10:20:00',
                                  'not-a-time', '2030-01-02T10:20:00+05:30'])
def test_equal_earlier_naive_bad_or_future_outcome_time_blocks(stamp: str, make: Any) -> None:
    view, _ = make(outcome_change={'outcome_at': stamp})
    row = dataset(view).rows[0]
    assert row['row_structure_eligible'] is False
    assert 'decision/outcome chronology unverified' in cast(list[str], row['eligibility_failures'])


def test_unsigned_originals_not_upgraded_to_complete_signature_evidence(make: Any) -> None:
    view, _ = make(signed=False)
    result = dataset(view)
    assert result.rows[0]['row_structure_eligible'] is False
    assert view.audit()['signature_coverage_complete'] is False


def test_missing_key_and_late_fence_never_fall_back_to_hot_or_empty(make: Any) -> None:
    view, source = make()
    source.keys.clear()
    with pytest.raises(ConsumerReadError):
        dataset(view)
    view, source = make()
    source.fail = True
    with pytest.raises(ConsumerReadError) as caught:
        view.decision_outcome_records()
    assert 'private' not in str(caught.value)


@pytest.mark.parametrize('field', ['target_before_stop', 'decision_event_hash', 'training_eligible', 'decision_id'])
def test_feature_name_cannot_overwrite_quality_identity_target_or_provenance(field: str, make: Any) -> None:
    view, _ = make(decision_change={'features': {'status': 'AVAILABLE', 'values': {field: 1}}})
    with pytest.raises(views.ViewError, match='FEATURE_NAME_COLLISION'):
        dataset(view)


@pytest.mark.parametrize('cap', ['MAX_RESULT_ROWS', 'MAX_RESULT_BYTES'])
def test_result_bound_fails_entire_view_not_a_shorter_sample(cap: str, make: Any, monkeypatch: Any) -> None:
    view, _ = make(outcomes=2)
    monkeypatch.setattr(views, cap, 1)
    with pytest.raises(views.ViewError, match='REQUIRES_STREAMING'):
        dataset(view)


@pytest.mark.parametrize('change', [{'strategy_id': ''}, {'target_version': None}, {'horizon_sessions': True},
                                  {'horizon_sessions': 0}, {'horizon_sessions': '1'}])
def test_scope_not_coerced_from_booleans_or_missing_values(change: dict[str, Any], make: Any) -> None:
    view, _ = make()
    scope = {'strategy_id': 'frozen', 'target_version': 'synthetic-v1', 'horizon_sessions': 1}
    scope.update(change)
    with pytest.raises(views.ViewError, match='DATASET_SCOPE_INVALID'):
        view.matured_decision_rows(**scope)


def test_detached_output_cannot_mutate_signed_source_and_mismatches_are_counted(make: Any) -> None:
    view, source = make()
    row = dataset(view).rows[0]
    row['rsi'] = 0
    assert dataset(view).rows[0]['rsi'] == 55
    result = view.matured_decision_rows(strategy_id='other', target_version='synthetic-v1', horizon_sessions=1)
    assert result.rows == () and result.attributes['unmatched_identifier_pairs'] == 1
    assert source.rows[0]['payload']['features']['values']['rsi']['value'] == 55


@pytest.mark.parametrize('change,reason', [
    ({'decision_id': 'another'}, 'outcome scope proof unavailable'),
    ({'horizon_sessions': True}, 'outcome scope proof unavailable'),
    ({'target_version': 'another'}, 'outcome scope proof unavailable'),
    ({'source_observation_ids': []}, 'outcome source proof unavailable'),
    ({'completed_session_closes': []}, 'completed-session proof unavailable'),
    ({'completed_session_closes': ['2024-01-01T15:30:00+05:30']}, 'completed-session proof unavailable'),
    ({'completed_session_closes': ['2030-01-01T15:30:00+05:30']}, 'completed-session proof unavailable'),
    ({'completed_session_closes': ['2024-01-02T15:30:00']}, 'completed-session proof unavailable'),
    ({'coverage_complete': False}, 'outcome coverage/first-touch incomplete'),
    ({'first_touch_known': False}, 'outcome coverage/first-touch incomplete')])
def test_missing_mismatched_horizon_source_or_coverage_proof_stays_unusable(
        change: dict[str, object], reason: str, make: Any) -> None:
    view, _ = make(outcome_change=change)
    row = dataset(view).rows[0]
    assert row['row_structure_eligible'] is False
    assert reason in cast(list[str], row['eligibility_failures'])
    assert row['target_before_stop'] is None
