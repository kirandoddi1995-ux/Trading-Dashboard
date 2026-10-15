"""Offline daily gates: synthetic clocks and receipts, never host acceptance."""
import ast
import builtins
from datetime import date, datetime, timedelta
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
from typing import Any

import pytest

import forward_daily_contract as daily


DAY = date(2026, 10, 15)
ACTIONS = ('Setup', 'Prepare', 'Start', 'Audit')


def health_report() -> dict[str, Any]:
    task = dict(exists=True, action_matches=True, enabled=False, disabled=True,
                running=False, state='Disabled')
    return dict(status='PREOPEN_HOST_CHECK_PASSED', blockers=[], repairs_performed=0,
        credentials_checked=False, provider_and_drive_health='NOT_CHECKED',
        approval_authority=False, training_eligible=False,
        facts=dict(time_service_running=True, time_service_automatic=True, clock_check='PASS',
                   free_bytes=1024**3, capture_volume_free_bytes=1024**3,
                   **{'KiranTrading-Versioned-20261015-poll': dict(task),
                      'KiranTrading-Versioned-20261015-audit': dict(task)}))


@pytest.mark.parametrize('path,value', [
    ((), None), (('status',), 'BLOCKED'), (('blockers',), ['CLOCK_UNVERIFIED']),
    (('blockers',), ()), (('repairs_performed',), True), (('repairs_performed',), 1),
    (('credentials_checked',), True), (('provider_and_drive_health',), 'VERIFIED'),
    (('approval_authority',), True), (('training_eligible',), True),
    (('facts',), None), (('facts', 'time_service_running'), False),
    (('facts', 'time_service_automatic'), 1), (('facts', 'clock_check'), 'UNVERIFIED'),
    (('facts', 'free_bytes'), True), (('facts', 'capture_volume_free_bytes'), 1024**3-1),
    (('facts', 'KiranTrading-Versioned-20261015-poll'), None),
    (('facts', 'KiranTrading-Versioned-20261015-poll', 'action_matches'), False),
    (('facts', 'KiranTrading-Versioned-20261015-poll', 'exists'), 1),
    (('facts', 'KiranTrading-Versioned-20261015-poll', 'enabled'), True),
    (('facts', 'KiranTrading-Versioned-20261015-audit', 'disabled'), False),
    (('facts', 'KiranTrading-Versioned-20261015-audit', 'running'), True),
    (('facts', 'KiranTrading-Versioned-20261015-audit', 'state'), 'Ready')])
def test_admission_health_fails_closed(path: tuple[str, ...], value: Any) -> None:
    report: Any = health_report()
    if not path:
        report = value
    else:
        target = report
        for name in path[:-1]:
            target = target[name]
        target[path[-1]] = value
    assert not daily.accepted_admission_health(report,
        'KiranTrading-Versioned-20261015-poll', 'KiranTrading-Versioned-20261015-audit', 1024**3)


def test_admission_health_literal_complete_and_no_floor_reduction() -> None:
    report = health_report()
    poll, audit = 'KiranTrading-Versioned-20261015-poll', 'KiranTrading-Versioned-20261015-audit'
    assert daily.accepted_admission_health(report, poll, audit, 1024**3)
    for minimum in (0, 1024**3-1, True, 1024**3+1):
        assert not daily.accepted_admission_health(report, poll, audit, minimum)
    assert not daily.accepted_admission_health(report, audit, poll, 1024**3)
    for field in report:
        damaged = dict(report)
        del damaged[field]
        assert not daily.accepted_admission_health(damaged, poll, audit, 1024**3)
    for field in report['facts']:
        damaged = health_report()
        del damaged['facts'][field]
        assert not daily.accepted_admission_health(damaged, poll, audit, 1024**3)
    for name in (poll, audit):
        for field in report['facts'][name]:
            damaged = health_report()
            del damaged['facts'][name][field]
            assert not daily.accepted_admission_health(damaged, poll, audit, 1024**3)


def at(clock: str = '08:30:00', day: date = DAY) -> datetime:
    return datetime.fromisoformat(f'{day}T{clock}+05:30')


def gate(action: str, now: datetime | None = None, **kwargs: Any) -> None:
    options: dict[str, Any] = dict(calendar_kind='REGULAR', elevated=False)
    options.update(kwargs)
    return daily.gate(DAY, now or at(), action, **options)


@pytest.mark.parametrize('value', ['2026-10-15', '2024-02-29', '2000-01-01'])
def test_canonical_session_date(value: str) -> None:
    assert daily.session(value) == date.fromisoformat(value)


@pytest.mark.parametrize('value', [None, True, 20261015, date(2026, 10, 15), '',
    '20261015', '2026-1-15', '2026-10-5', ' 2026-10-15', '2026-10-15\n',
    '2026-10-15T00:00:00', '2026-02-29', '2026-13-01', '2026-00-01',
    '2026-10-00', '0000-01-01', '２０２６-１０-１５'])
def test_session_rejects_noncanonical_or_impossible(value: Any) -> None:
    with pytest.raises(ValueError):
        daily.session(value)


@pytest.mark.parametrize('value', ['2026-10-15T08:30:00+05:30',
    '2026-10-15T03:00:00Z', '2026-10-14T23:00:00-04:00'])
def test_aware_normalizes_equivalent_instants(value: str) -> None:
    assert daily.aware(value) == at()
    assert daily.aware(value).tzinfo == daily.IST


@pytest.mark.parametrize('value', ['', 'private-invalid', '2026-10-15',
    '2026-10-15T08:30:00', '2026-10-15T08:30:00+25:00', None, True, 123])
def test_aware_rejects_naive_or_invalid(value: Any) -> None:
    with pytest.raises((ValueError, TypeError)):
        daily.aware(value)


@pytest.mark.parametrize('action', ACTIONS)
@pytest.mark.parametrize('kind', ['CLOSED', 'SPECIAL', 'UNVERIFIED', '', None,
                                  True, 'regular', 'REGULAR '])
def test_only_reviewed_regular_calendar_admitted(action: str, kind: Any) -> None:
    with pytest.raises(ValueError, match='^REVIEWED_REGULAR_SESSION_REQUIRED$'):
        gate(action, at('16:00:00') if action == 'Audit' else at(), calendar_kind=kind)


@pytest.mark.parametrize('action', ACTIONS)
def test_elevated_blocks_every_action_before_other_gates(action: str) -> None:
    with pytest.raises(ValueError, match='^NORMAL_NON_ADMIN_WINDOW_REQUIRED$'):
        gate(action, elevated=True, calendar_kind='UNVERIFIED')


@pytest.mark.parametrize('days,clock,reason', [
    (7, '20:00:00', None), (1, '23:59:59', None),
    (0, '00:00:00', None), (0, '09:14:59.999999', None),
    (0, '09:15:00', 'PREOPEN_DEADLINE_MISSED'),
    (0, '20:00:00', 'PREOPEN_DEADLINE_MISSED'),
    (8, '20:00:00', 'SETUP_DATE_OUTSIDE_REVIEW_WINDOW'),
    (-1, '08:00:00', 'SETUP_DATE_OUTSIDE_REVIEW_WINDOW'),
])
def test_setup_evening_review_window_and_same_day_preopen(days: int, clock: str, reason: str | None) -> None:
    now = at(clock, DAY - timedelta(days=days))
    if reason:
        with pytest.raises(ValueError, match=f'^{reason}$'):
            gate('Setup', now)
    else:
        gate('Setup', now)


@pytest.mark.parametrize('action', ['Prepare', 'Start'])
@pytest.mark.parametrize('delta', [-1, 1])
def test_prepare_and_start_require_exact_session_day(action: str, delta: int) -> None:
    with pytest.raises(ValueError, match='^SESSION_DATE_MISMATCH$'):
        gate(action, at(day=DAY + timedelta(days=delta)), downloaded=at())


@pytest.mark.parametrize('download', [None, datetime(2026, 10, 15, 8)])
def test_prepare_requires_actual_aware_download(download: datetime | None) -> None:
    with pytest.raises(ValueError, match='^ACTUAL_DOWNLOAD_TIMESTAMP_REQUIRED$'):
        gate('Prepare', downloaded=download)


@pytest.mark.parametrize('download', [at('20:00:00', DAY - timedelta(days=1)),
    at('23:59:59', DAY - timedelta(days=1)), at('08:30:00.000001'),
    at('08:00:00', DAY + timedelta(days=1))])
def test_prepare_rejects_previous_evening_and_future_downloads(download: datetime) -> None:
    # Reviewed nse_owner_close requires the download's IST date to equal session day.
    with pytest.raises(ValueError, match='^FRESH_SESSION_MORNING_DOWNLOAD_REQUIRED$'):
        gate('Prepare', downloaded=download)


@pytest.mark.parametrize('download', [at('00:00:00'), at('08:29:59'), at(),
    datetime.fromisoformat('2026-10-14T18:30:00Z')])
def test_prepare_accepts_only_same_ist_morning_not_later_than_now(download: datetime) -> None:
    gate('Prepare', downloaded=download)


@pytest.mark.parametrize('clock', ['09:15:00', '09:20:29', '20:00:00'])
def test_prepare_preopen_deadline_is_exclusive(clock: str) -> None:
    with pytest.raises(ValueError, match='^PREOPEN_DEADLINE_MISSED$'):
        gate('Prepare', at(clock), downloaded=at('08:00:00'))


def test_prepare_last_microsecond_before_open() -> None:
    gate('Prepare', at('09:14:59.999999'), downloaded=at())


@pytest.mark.parametrize('clock', ['00:00:00', '09:20:29', '09:20:29.999999'])
def test_start_admission_before_first_poll(clock: str) -> None:
    gate('Start', at(clock))


@pytest.mark.parametrize('clock', ['09:20:30', '09:20:30.000001', '09:25:30',
                                  '09:29:59', '09:30:00', '16:00:00'])
def test_start_deadline_no_retry_or_second_poll_admission(clock: str) -> None:
    for _ in range(2):
        with pytest.raises(ValueError, match='^FIRST_START_DEADLINE_MISSED_NO_RETRY$'):
            gate('Start', at(clock))


@pytest.mark.parametrize('clock', ['00:00:00', '15:39:59.999999'])
def test_audit_waits_for_postsession_boundary(clock: str) -> None:
    with pytest.raises(ValueError, match='^POSTSESSION_AUDIT_ONLY$'):
        gate('Audit', at(clock))


@pytest.mark.parametrize('now', [at('15:40:00'), at('23:59:59'),
    at('00:00:00', DAY + timedelta(days=1)), at(day=DAY + timedelta(days=365))])
def test_audit_allows_postsession_and_historical(now: datetime) -> None:
    gate('Audit', now)


def test_audit_never_allows_future_session() -> None:
    with pytest.raises(ValueError, match='^SESSION_DATE_MISMATCH$'):
        gate('Audit', at('23:59:59', DAY - timedelta(days=1)))


def test_gates_use_ist_date_and_instant_not_input_timezone_date() -> None:
    gate('Prepare', datetime.fromisoformat('2026-10-14T23:00:00-04:00'),
         downloaded=datetime.fromisoformat('2026-10-14T18:30:00Z'))
    with pytest.raises(ValueError, match='FIRST_START_DEADLINE_MISSED_NO_RETRY'):
        gate('Start', datetime.fromisoformat('2026-10-15T03:50:30Z'))
    gate('Audit', datetime.fromisoformat('2026-10-15T10:10:00Z'))


@pytest.mark.parametrize('changes', [dict(day=str(DAY)), dict(day=at()),
    dict(now=datetime(2026, 10, 15, 8)), dict(now='private-invalid'),
    dict(elevated=0), dict(elevated=1), dict(elevated='false'),
    dict(action='Preview'), dict(action='start'), dict(action=None)])
def test_gate_input_types_fail_closed(changes: dict[str, Any]) -> None:
    args: dict[str, Any] = dict(day=DAY, now=at(), action='Setup', calendar_kind='REGULAR', elevated=False)
    args.update(changes)
    with pytest.raises(ValueError, match='^DAILY_INPUT_INVALID$'):
        daily.gate(**args)


def receipt(expected: int = 1) -> dict[str, Any]:
    return dict(status='POLL_REMOTE_VERIFIED', exit_code=0,
        code='REMOTE_VERIFICATION_COMPLETE', capture_status='VERSIONED_OBSERVATION_RECORDED',
        decision_recorded_this_poll=True, local_poll_committed=True, remote_verified=True,
        receipt_written=True, recorded_decisions=expected, missing_decisions=75 - expected,
        clock_problem='PASS', retries=0, approval_authority=False, training_eligible=False)


@pytest.mark.parametrize('expected', [1, 2])
def test_exact_public_poll_contract(expected: int) -> None:
    report = receipt(expected)
    before = dict(report)
    assert daily.accepted_poll(report, expected) is True
    assert report == before
    assert daily.accepted_poll(report, 3 - expected) is False


@pytest.mark.parametrize('field', list(receipt()))
@pytest.mark.parametrize('expected', [1, 2])
def test_every_poll_contract_field_required(field: str, expected: int) -> None:
    report = receipt(expected)
    del report[field]
    assert daily.accepted_poll(report, expected) is False


@pytest.mark.parametrize('field', ['decision_recorded_this_poll', 'local_poll_committed',
    'remote_verified', 'receipt_written', 'approval_authority', 'training_eligible'])
@pytest.mark.parametrize('value', [None, 0, 1, 'true', 'false', [], {}])
def test_poll_flags_require_literal_boolean(field: str, value: Any) -> None:
    report = receipt()
    report[field] = value
    assert daily.accepted_poll(report, 1) is False


@pytest.mark.parametrize('field', ['exit_code', 'retries', 'recorded_decisions', 'missing_decisions'])
@pytest.mark.parametrize('value', [True, False, None, '0', '1', 0.0, 1.0, [], {}])
def test_poll_numeric_fields_require_exact_integer_not_bool(field: str, value: Any) -> None:
    report = receipt()
    report[field] = value
    assert daily.accepted_poll(report, 1) is False


@pytest.mark.parametrize('field,value', [
    ('status', 'BLOCKED'), ('status', 'RAW_INPUT_BLOCKED'),
    ('status', 'POLL_LOCAL_COMMITTED'), ('exit_code', 1),
    ('code', 'RAW_INPUT_BLOCKED'), ('code', 'REMOTE_VERIFICATION_FAILED'),
    ('capture_status', 'RAW_INPUT_BLOCKED'), ('capture_status', 'RAW_ONLY_NO_DECISION'),
    ('decision_recorded_this_poll', False), ('local_poll_committed', False),
    ('remote_verified', False), ('receipt_written', False),
    ('recorded_decisions', 0), ('recorded_decisions', 2),
    ('missing_decisions', 75), ('missing_decisions', 73),
    ('clock_problem', 'FAIL'), ('clock_problem', True), ('retries', 1),
    ('approval_authority', True), ('training_eligible', True)])
def test_poll_failures_and_raw_only_are_never_success(field: str, value: Any) -> None:
    report = receipt()
    report[field] = value
    assert daily.accepted_poll(report, 1) is False


def test_clock_check_is_not_public_clock_problem() -> None:
    report = receipt()
    del report['clock_problem']
    report['clock_check'] = 'PASS'
    assert daily.accepted_poll(report, 1) is False


@pytest.mark.parametrize('field', ['status', 'code', 'capture_status', 'clock_problem'])
@pytest.mark.parametrize('value', [None, True, 1, [], {}])
def test_poll_string_fields_reject_invalid_types(field: str, value: Any) -> None:
    report = receipt()
    report[field] = value
    assert daily.accepted_poll(report, 1) is False


@pytest.mark.parametrize('report', [None, [], (), 'private-invalid', True, 1])
def test_poll_invalid_report_types(report: object) -> None:
    assert daily.accepted_poll(report, 1) is False


@pytest.mark.parametrize('expected', [None, True, False, 0, 3, -1, 1.0, '1', [], {}])
def test_poll_invalid_expected_count(expected: Any) -> None:
    assert daily.accepted_poll(receipt(), expected) is False


def test_preview_exact_date_derived_plan() -> None:
    result = daily.plan(DAY)
    assert result == dict(status='PREVIEW', session_date='2026-10-15',
        reviewed_commit='1251530731cce5b75fad8601567b9320d07b710d',
        capsule_name='kiran_forward_20261015', poll_task='KiranTrading-Versioned-20261015-poll',
        audit_task='KiranTrading-Versioned-20261015-audit',
        preparation_deadline='2026-10-15T09:15:00+05:30',
        first_poll='2026-10-15T09:20:30+05:30', second_poll='2026-10-15T09:25:30+05:30',
        enable_deadline='2026-10-15T09:30:00+05:30', calendar_verified=False,
        writes=0, network_calls=0, credential_reads=0, approval_authority=False,
        training_eligible=False)


def test_imports_stdlib_only_and_no_import_time_execution() -> None:
    tree = ast.parse(Path(daily.__file__).read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(item.name.split('.')[0] in sys.stdlib_module_names for item in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            assert node.level == 0 and node.module.split('.')[0] in sys.stdlib_module_names
    # Definitions/constants/imports and the guarded CLI are the only top-level forms.
    assert all(isinstance(node, (ast.Expr, ast.Import, ast.ImportFrom,
        ast.Assign, ast.AnnAssign, ast.FunctionDef, ast.If)) for node in tree.body)


def test_cli_preview_zero_io(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    # Initialize argparse's lazy imports before closing every IO seam.
    assert daily.main(['--session-date', str(DAY)]) == 0
    capsys.readouterr()
    def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError('preview attempted IO')
    with monkeypatch.context() as patch:
        for obj, name in [(builtins, 'open'), (io, 'open'), (socket, 'socket'),
                          (socket, 'create_connection'), (subprocess, 'Popen')]:
            patch.setattr(obj, name, denied)
        patch.setattr(daily, 'gate', denied)
        assert daily.main(['--session-date', str(DAY), '--at', 'private-invalid',
                           '--download-at', 'private-invalid']) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == daily.plan(DAY)
    assert captured.err == ''


@pytest.mark.parametrize('action,clock,download', [
    ('Setup', '08:30:00', None), ('Prepare', '08:30:00', '08:00:00'),
    ('Start', '09:20:29', None), ('Audit', '15:40:00', None)])
def test_cli_pure_gate_success_is_never_host_acceptance(action: str, clock: str, download: str | None,
                                                       capsys: pytest.CaptureFixture[str]) -> None:
    argv = ['--session-date', str(DAY), '--evaluate', action, '--at', at(clock).isoformat(),
            '--calendar-kind', 'REGULAR']
    if download:
        argv += ['--download-at', at(download).isoformat()]
    assert daily.main(argv) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'PURE_INPUT_GATE_PASSED_NOT_HOST_ACCEPTANCE'
    assert result['calendar_verified'] is result['approval_authority'] is False
    assert result['writes'] == result['network_calls'] == result['credential_reads'] == 0


@pytest.mark.parametrize('argv', [
    ['--session-date', 'private-secret-invalid'],
    ['--session-date', str(DAY), '--evaluate', 'Start', '--at', 'private-secret-invalid'],
    ['--session-date', str(DAY), '--evaluate', 'Prepare', '--at', at().isoformat(),
     '--calendar-kind', 'REGULAR', '--download-at', 'private-secret-invalid'],
    ['--session-date', str(DAY), '--evaluate', 'Start', '--at', at().isoformat()],
    ['--session-date', str(DAY), '--evaluate', 'Start', '--at', at().isoformat(),
     '--calendar-kind', 'REGULAR', '--elevated']])
def test_cli_invalid_inputs_emit_only_safe_class(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert daily.main(argv) == 2
    captured = capsys.readouterr()
    assert captured.err == '' and 'private-secret' not in captured.out
    expected_code = ('SESSION_DATE_INVALID' if argv[1] == 'private-secret-invalid' else
        'NORMAL_NON_ADMIN_WINDOW_REQUIRED' if '--elevated' in argv else
        'REVIEWED_REGULAR_SESSION_REQUIRED' if '--calendar-kind' not in argv and '--evaluate' in argv
        and 'private-secret-invalid' not in argv else 'DAILY_INPUT_REVIEW_REQUIRED')
    assert json.loads(captured.out) == dict(status='BLOCKED',
        code=expected_code, approval_authority=False, raw_error_printed=False)


@pytest.mark.parametrize('error', [ValueError('private-path-secret'), RuntimeError('private-token-secret')])
def test_cli_unclassified_exception_never_leaks_raw(monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str], error: Exception) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise error
    monkeypatch.setattr(daily, 'gate', fail)
    assert daily.main(['--session-date', str(DAY), '--evaluate', 'Start',
                       '--at', at().isoformat()]) == 2
    captured = capsys.readouterr()
    assert 'private-' not in captured.out + captured.err
    assert json.loads(captured.out)['code'] == 'DAILY_INPUT_REVIEW_REQUIRED'
