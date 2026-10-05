"""Pure synthetic observation/comparison failure paths, not live evidence."""
from dataclasses import replace
from datetime import datetime, timedelta
import sqlite3
from pathlib import Path

import pytest

from research_integrity import IntegrityError
from research_replay_comparison import Observation, ObservationJournal, compare_session

OPEN = '2022-01-03T09:15:00+05:30'
CLOSE = '2022-01-03T15:30:00+05:30'
SPEC = 'a' * 64


def observations():
    opening = datetime.fromisoformat(OPEN)
    return [Observation(SPEC, OPEN, CLOSE, (opening + timedelta(minutes=5 * n)).isoformat(),
                        (opening + timedelta(minutes=5 * n)).isoformat(),
                        (opening + timedelta(minutes=5 * n, seconds=1)).isoformat(),
                        'b' * 64, 1, True, 'c' * 64, 'recorded_bar_end', 'OBSERVED') for n in range(1, 76)]


def compare(left, right):
    return compare_session(spec_hash=SPEC, session_open=OPEN, session_close=CLOSE,
                           observed=left, replayed=[replace(row, origin='REPLAY') for row in right])


def test_full_session_matches_without_claiming_approval():
    record = observations()[0].normalized()
    assert record['record_type'] == 'RESEARCH_OBSERVATION'
    assert record['approval_authority'] is False and record['fill_evidence'] is False
    result = compare(observations(), observations())
    assert result['status'] == 'MATCH' and result['counts']['MATCH'] == 75
    assert result['match_fraction_of_expected'] == 1
    assert result['available_decision_matches'] == 75 and result['unavailable_decision_matches'] == 0
    assert result['approval_authority'] is False and result['fill_evidence'] is False
    assert all(row['capture_lag_seconds'] == 1 for row in result['checks'])


def test_empty_and_selected_subset_cannot_claim_full_match():
    result = compare([], [])
    assert result['match_fraction_of_expected'] is None and result['counts']['MISSING_BOTH'] == 75
    rows = observations()
    result = compare(rows[:1], rows)
    assert result['status'] == 'INCOMPLETE_OR_DIFFERENT'
    assert result['match_fraction_of_expected'] == 1 / 75
    assert result['counts']['MISSING_OBSERVATION'] == 74
    assert compare(rows, [])['counts']['MISSING_REPLAY'] == 75
    unavailable = [replace(row, available=False, direction=0) for row in rows]
    result = compare(unavailable, unavailable)
    assert result['available_decision_matches'] == 0 and result['unavailable_decision_matches'] == 75


@pytest.mark.parametrize('change,status', [
    ({'input_hash': 'd' * 64}, 'INPUT_OR_BASIS_MISMATCH'),
    ({'basis': 'historical_final_assumed_bar_end'}, 'INPUT_OR_BASIS_MISMATCH'),
    ({'direction': -1}, 'DECISION_MISMATCH'),
    ({'detail_hash': 'd' * 64}, 'DECISION_MISMATCH'),
    ({'direction': 0, 'available': False}, 'DECISION_MISMATCH'),
    ({'available_at': '2022-01-03T09:20:01+05:30'}, 'DELAYED_AVAILABILITY')])
def test_differences_are_not_averaged_or_hidden(change, status):
    left, right = observations(), observations()
    left[0] = replace(left[0], **change)
    result = compare(left, right)
    assert result['counts'][status] == 1 and result['counts']['MATCH'] == 74


@pytest.mark.parametrize('change', [
    {'decision_at': '2022-01-03T09:20:00'}, {'decision_at': OPEN},
    {'decision_at': '2022-01-03T09:21:00+05:30'},
    {'decision_at': '2022-01-03T15:35:00+05:30'},
    {'received_at': OPEN}, {'available_at': OPEN},
    {'input_hash': ''}, {'direction': True}, {'available': 'false'},
    {'available': False}, {'basis': 'unknown'}, {'session_close': OPEN}])
def test_invalid_observations_never_enter_journal(tmp_path, change):
    journal = ObservationJournal(tmp_path / 'observations.sqlite')
    with pytest.raises(ValueError):
        journal.record(replace(observations()[0], **change))
    assert journal.read(SPEC, OPEN) == []


def test_duplicate_identity_and_foreign_spec_fail():
    rows = observations()
    with pytest.raises(IntegrityError, match='DUPLICATE_DECISION'):
        compare(rows + rows[:1], rows)
    rows[0] = replace(rows[0], spec_hash='d' * 64)
    with pytest.raises(IntegrityError, match='COMPARISON_IDENTITY_MISMATCH'):
        compare(rows, observations())


def test_journal_idempotency_conflict_restart_and_append_only(tmp_path):
    path = tmp_path / 'observations.sqlite'
    journal = ObservationJournal(path)
    row = observations()[0]
    assert journal.record(row) == 'NEW'
    assert journal.record(row) == 'IDEMPOTENT_SUCCESS'
    # Equivalent UTC identity must not create a second row.
    utc = replace(row, **{key: row.normalized()[key] for key in
                         ('session_open', 'session_close', 'decision_at', 'available_at', 'received_at')})
    assert journal.record(utc) == 'IDEMPOTENT_SUCCESS'
    with pytest.raises(IntegrityError, match='OBSERVATION_CONFLICT'):
        journal.record(replace(row, direction=-1))
    assert len(ObservationJournal(path).read(SPEC, OPEN)) == 1
    with journal.connect() as connection:
        for statement in ('DELETE FROM observations', "UPDATE observations SET record_json='{}'"):
            with pytest.raises(sqlite3.IntegrityError, match='APPEND_ONLY'):
                connection.execute(statement)


def test_tamper_detection(tmp_path):
    journal = ObservationJournal(tmp_path / 'observations.sqlite')
    journal.record(observations()[0])
    with journal.connect() as connection:
        connection.execute('DROP TRIGGER observations_no_update')
        connection.execute("UPDATE observations SET record_json='{}'")
    with pytest.raises(IntegrityError, match='OBSERVATION_STORE_CORRUPT'):
        journal.read(SPEC, OPEN)


def test_invalid_empty_session_does_not_pass():
    with pytest.raises(IntegrityError, match='REGULAR_SESSION_BOUNDARY_REQUIRED'):
        compare_session(spec_hash=SPEC, session_open=OPEN, session_close=OPEN, observed=[], replayed=[])


def test_parallel_retries_acknowledge_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    journal = ObservationJournal(tmp_path / 'observations.sqlite')
    with ThreadPoolExecutor(max_workers=4) as executor:
        outcomes = list(executor.map(journal.record, [observations()[0]] * 8))
    assert outcomes.count('NEW') == 1 and outcomes.count('IDEMPOTENT_SUCCESS') == 7


def test_private_journal_cannot_be_created_in_repository():
    target = Path(__file__).resolve().parents[1] / 'never-created-observations.sqlite'
    with pytest.raises(IntegrityError, match='PRIVATE_OBSERVATIONS_OUTSIDE_REPOSITORY_REQUIRED'):
        ObservationJournal(target)
    assert not target.exists()
