"""Cross-platform deadline routing without OS, credentials or private data."""
from datetime import date, datetime
import json

import pytest

import forward_morning_route as module

DAY = date(2026, 10, 15)


def at(value: str) -> datetime:
    return datetime.fromisoformat('2026-10-15T' + value + '+05:30')


@pytest.mark.parametrize('value,status,reason', [
    ('08:30:00', 'OWNER_ACTION_REQUIRED', 'NO_AFTER_OPEN_PREPARATION'),
    ('09:14:59', 'OWNER_ACTION_REQUIRED', 'NO_AFTER_OPEN_PREPARATION'),
    ('09:15:00', 'BLOCKED', 'PREOPEN_DEADLINE_MISSED'),
    ('09:29:59', 'BLOCKED', 'PREOPEN_DEADLINE_MISSED'),
    ('15:39:59', 'BLOCKED', 'PREOPEN_DEADLINE_MISSED'),
    ('15:40:00', 'POSTSESSION', 'GAPS_REMAIN_MISSING'),
])
def test_preparation_boundaries(value: str, status: str, reason: str) -> None:
    result = module.route(DAY, at(value), module.MorningFacts())
    assert (result.status, result.reason) == (status, reason)
    assert not result.catchup_allowed and result.writes == result.task_changes == 0


@pytest.mark.parametrize('value,first,second,step', [
    ('09:19:59', False, False, 'ONE_SUPERVISED_POLL_AT_TARGET'),
    ('09:20:30', False, False, 'ONE_SUPERVISED_POLL_AT_TARGET'),
    ('09:20:31', False, False, 'KEEP_TASKS_DISABLED_RECONCILE_OR_AUDIT'),
    ('09:25:30', True, False, 'ONE_SUPERVISED_POLL_AT_TARGET'),
    ('09:25:31', True, False, 'KEEP_TASKS_DISABLED_RECONCILE_OR_AUDIT'),
    ('09:26:00', True, True, 'AUDIT_ENABLE_FIRST_POLL_LAST_THEN_READINESS'),
    ('09:30:00', True, True, 'INSPECT_EXISTING_TASKS_AND_RECEIPTS_ONLY'),
    ('12:00:00', True, True, 'INSPECT_EXISTING_TASKS_AND_RECEIPTS_ONLY'),
])
def test_supervised_and_enable_boundaries(value: str, first: bool, second: bool, step: str) -> None:
    result = module.route(DAY, at(value), module.MorningFacts(True, True, first, second))
    assert result.next_step == step
    assert result.approval_authority is False


@pytest.mark.parametrize('facts', [module.MorningFacts(False, True),
    module.MorningFacts(True, False, True), module.MorningFacts(True, True, False, True),
    module.MorningFacts(True, True, True, False, True)])
def test_inconsistent_flags(facts: module.MorningFacts) -> None:
    assert module.route(DAY, at('08:00:00'), facts).reason == 'MILESTONES_INCONSISTENT'


@pytest.mark.parametrize('value,facts', [
    ('08:00:00', module.MorningFacts(True, True, True, True, True)),
    ('09:20:29', module.MorningFacts(True, True, True)),
    ('09:21:00', module.MorningFacts(True, True, True, True)),
])
def test_future_milestones_are_not_accepted(value: str, facts: module.MorningFacts) -> None:
    assert module.route(DAY, at(value), facts).reason == 'MILESTONE_TIME_CONFLICT'


@pytest.mark.parametrize('day', [date(2026, 10, 17), date(2026, 10, 18), date(2026, 10, 20)])
def test_holidays_and_weekend(day: date) -> None:
    now = datetime.fromisoformat(str(day) + 'T08:00:00+05:30')
    assert module.route(day, now, module.MorningFacts()).reason == 'REVIEWED_REGULAR_SESSION_REQUIRED'


def test_timezone_and_wrong_date() -> None:
    assert module.route(DAY, datetime.fromisoformat('2026-10-15T03:00:00Z'),
                        module.MorningFacts()).next_step == 'PREPARE_AND_FREEZE_BEFORE_OPEN'
    assert module.route(DAY, datetime.fromisoformat('2026-10-14T08:00:00+05:30'),
                        module.MorningFacts()).reason == 'SESSION_DATE_MISMATCH'
    with pytest.raises(ValueError, match='MORNING_ROUTE_INPUT_INVALID'):
        module.route(DAY, datetime(2026, 10, 15), module.MorningFacts())


def test_preview_does_not_parse_or_query(monkeypatch: pytest.MonkeyPatch,
                                        capsys: pytest.CaptureFixture[str]) -> None:
    def deny(*args: object) -> None:
        raise AssertionError('No calendar/IO in preview')
    monkeypatch.setattr(module, 'cash_session', deny)
    assert module.main(['--at', 'invalid', '--session-date', 'invalid']) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'PREVIEW'


def test_cli_redacts_invalid(capsys: pytest.CaptureFixture[str]) -> None:
    assert module.main(['--review-plan', '--at', 'private-invalid', '--session-date', str(DAY)]) == 2
    output = capsys.readouterr().out
    assert 'private-invalid' not in output
    assert json.loads(output)['reason'] == 'MORNING_ROUTE_INPUT_INVALID'
