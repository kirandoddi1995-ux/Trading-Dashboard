"""Synthetic commissioning/receipt checks; no real hosted health queries."""
from datetime import datetime

import pytest

from automation_health import Heartbeat, assess
from research_integrity import IntegrityError

NOW = datetime.fromisoformat('2022-01-03T16:00:00+05:30')
DUE = '2022-01-03T15:50:00+05:30'
HASH = 'a' * 64


def beat(lane, commissioned, due_at, success_at):
    run = '2022-01-03T15:30:00+05:30'
    return Heartbeat(lane, commissioned, due_at, success_at, run, run if success_at is not None else None)


def health(**changes):
    args = {'now': NOW, 'expected_hash': HASH, 'actual_hash': HASH, 'clock_state': 'PASS',
            'heartbeats': [beat('ARCHIVE', True, DUE, '2022-01-03T15:51:00+05:30')],
            'required_lanes': ('ARCHIVE',)}
    args.update(changes)
    return assess(**args)


def test_verified_checks_are_not_trading_approval():
    result = health()
    assert result['status'] == 'CHECKS_PASS'
    assert result['approval_authority'] is False and result['live_broker_validation'] is False
    assert result['automatic_actions'] == []


@pytest.mark.parametrize('changes,state', [({'expected_hash': None}, 'EXPECTATION_MISSING'),
    ({'actual_hash': None}, 'OBSERVATION_MISSING'), ({'actual_hash': 'b' * 64}, 'MISMATCH')])
def test_missing_or_wrong_release_never_self_compares(changes, state):
    result = health(**changes)
    assert result['status'] == 'ATTENTION_REQUIRED' and result['checks'][0]['state'] == state


@pytest.mark.parametrize('clock', [None, 'MISSING', 'STALE', 'FAILED'])
def test_real_clock_status_required(clock):
    assert health(clock_state=clock)['status'] == 'ATTENTION_REQUIRED'


def test_absent_uncommissioned_and_pending_are_not_healthy():
    assert health(heartbeats=[])['status'] == 'ATTENTION_REQUIRED'
    assert health(heartbeats=[])['heartbeats'][0]['state'] == 'MISSING_POLICY'
    assert health(heartbeats=[beat('ARCHIVE', False, DUE, None)])['status'] == 'NOT_FULLY_VERIFIED'
    pending = beat('ARCHIVE', True, '2022-01-03T17:00:00+05:30', None)
    assert health(heartbeats=[pending])['heartbeats'][0]['state'] == 'AWAITING_DEADLINE'


def test_started_or_previous_completion_is_not_current_completion():
    for receipt in (None, '2022-01-02T15:55:00+05:30'):
        result = health(heartbeats=[beat('ARCHIVE', True, DUE, receipt)])
        assert result['status'] == 'ATTENTION_REQUIRED'
        assert result['heartbeats'][0]['state'] == 'MISSED_COMPLETION'


@pytest.mark.parametrize('problem', ['naive', 'future', 'lane', 'commissioned', 'clock', 'hash', 'duplicate'])
def test_invalid_health_inputs_are_explicit_errors(problem):
    changes = {'naive': {'now': NOW.replace(tzinfo=None)},
               'future': {'heartbeats': [beat('ARCHIVE', True, DUE, '2022-01-03T17:00:00+05:30')]},
               'lane': {'heartbeats': [beat('SECRET_TEXT', True, DUE, None)]},
               'commissioned': {'heartbeats': [beat('ARCHIVE', 'false', DUE, None)]},
               'clock': {'clock_state': 'secret-text'}, 'hash': {'expected_hash': 'invalid'},
               'duplicate': {'heartbeats': [beat('ARCHIVE', True, DUE, None)] * 2}}
    with pytest.raises(IntegrityError):
        health(**changes[problem])


def test_deadline_equality_and_utc_normalization():
    equal = beat('ARCHIVE', True, NOW.isoformat(), None)
    assert equal.assess(NOW)['state'] == 'AWAITING_DEADLINE'
    done = beat('ARCHIVE', True, DUE, '2022-01-03T10:20:00+00:00')
    assert done.assess(NOW)['state'] == 'COMPLETE'


def test_completion_before_deadline_and_wrong_run_identity():
    from dataclasses import replace
    done = beat('ARCHIVE', True, DUE, '2022-01-03T15:40:00+05:30')
    assert done.assess(NOW)['state'] == 'COMPLETE'
    wrong = replace(done, success_for='2022-01-02T15:30:00+05:30')
    assert wrong.assess(NOW)['state'] == 'MISSED_COMPLETION'
    with pytest.raises(IntegrityError, match='COMPLETE_RECEIPT_IDENTITY_REQUIRED'):
        replace(done, success_for=None).assess(NOW)
    with pytest.raises(IntegrityError, match='DEADLINE_BEFORE_EXPECTED_RUN'):
        replace(done, expected_run_at='2022-01-03T17:00:00+05:30').assess(NOW)


def test_expected_scope_cannot_be_silently_reduced():
    result = health(required_lanes=('ARCHIVE', 'SETTLEMENT_MONITOR'))
    assert result['status'] == 'ATTENTION_REQUIRED'
    assert result['heartbeats'][-1]['state'] == 'MISSING_POLICY'
    for scope in ((), ('ARCHIVE', 'ARCHIVE'), ('UNKNOWN',)):
        with pytest.raises(IntegrityError, match='EXPLICIT_HEARTBEAT_SCOPE_REQUIRED'):
            health(required_lanes=scope)
    with pytest.raises(IntegrityError, match='HEARTBEAT_OUTSIDE_REVIEWED_SCOPE'):
        health(required_lanes=('OFFLINE_SELF_CHECK',))
