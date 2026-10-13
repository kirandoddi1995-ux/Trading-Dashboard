"""Synthetic future operations only; no owner state, clock, service or notification IO."""
from datetime import date, datetime, timedelta, timezone
import json
import importlib
import shutil
from pathlib import Path
from typing import Any

import pytest

import forward_session_ops as ops
import forward_ops_host as host

DAY = date(2026, 10, 14)


def test_preview_zero_io(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def denied(*args: Any, **kwargs: Any) -> None:
        pytest.fail('preview performed IO')
    monkeypatch.setattr(ops, 'separate', denied)
    monkeypatch.setattr(ops, 'preflight', denied)
    assert ops.main(['--root', 'unused', '--ops-root', 'unused', '--session-date', str(DAY), '--mode', 'preflight']) == 0
    assert json.loads(capsys.readouterr().out)['writes'] == 0


def test_gap_counts_and_no_fabricated_decision() -> None:
    opening = datetime(2026, 10, 14, 3, 45, tzinfo=timezone.utc)
    bundle = {'config': {'session_open': opening.isoformat()}, 'polls': [
        {'source': {'slot': (opening + timedelta(minutes=5*i)).isoformat()}, 'decision': {}}
        for i in range(1, 42)], 'recorded_decisions': 41, 'missing_decisions': 34}
    report = ops.coverage(bundle)
    assert report['status'] == 'VERSIONED_COVERAGE_INCOMPLETE'
    assert len(report['slots']) == 75
    assert sum(row['status'] == 'MISSING_NOT_OBSERVED' for row in report['slots']) == 34
    assert report['operational_cause_per_slot'] == 'NOT_ESTABLISHED'
    assert report['training_eligible'] is report['remote_custody_verified'] is report['backfill_allowed'] is False


def test_raw_only_is_not_a_decision() -> None:
    report = ops.coverage({'config': {'session_open': '2026-10-14T09:15:00+05:30'},
        'polls': [{'source': {'slot': '2026-10-14T09:20:00+05:30'}, 'decision': None}],
        'recorded_decisions': 0, 'missing_decisions': 75})
    assert report['slots'][0]['status'] == 'RAW_ONLY_NO_DECISION'


def test_namespace_alias_and_overlap_fail(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        ops.separate(tmp_path, tmp_path / 'ops')
    with pytest.raises(ValueError):
        ops.separate(Path('relative'), tmp_path)


def test_report_append_and_alert_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    alerts: list[str] = []
    monkeypatch.setattr(ops, 'notify', lambda code: alerts.append(code))
    for _ in range(3):
        ops.save(tmp_path, DAY, {'status': 'BLOCKED', 'code': 'CLOCK_UNVERIFIED'}, visible=True)
    assert len(list(tmp_path.glob('*.json'))) == 3
    assert alerts == ['CLOCK_REVIEW_REQUIRED']
    assert len(list(tmp_path.glob('*.alert'))) == 1


@pytest.mark.parametrize('reason', ['CLOCK_PROBE_TIMEOUT', 'CLOCK_PROBE_BUSY', 'CLOCK_PROBE_FAILED'])
def test_clock_detail_restore_and_no_retry(reason: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import forward_nifty_job as job
    import forward_versioned_capture as capture
    calls: list[int] = []
    def measure() -> dict[str, Any]:
        calls.append(1)
        return {'status': 'UNAVAILABLE', 'reason': reason}
    monkeypatch.setattr(job, 'measure_clock', measure)
    monkeypatch.setattr(job, 'clock_error', lambda *a, **k: 'CLOCK_MEASUREMENT_UNAVAILABLE')
    def run(*args: Any) -> int:
        getattr(job, 'measure_clock')()
        print(json.dumps({'status': 'BLOCKED', 'code': 'CLOCK_UNVERIFIED', 'local_poll_committed': False}))
        return 2
    monkeypatch.setattr(capture, 'run', run)
    result = ops.poll(tmp_path, DAY)
    assert result['probe_reason'] == reason and result['clock_problem'] == 'CLOCK_MEASUREMENT_UNAVAILABLE'
    assert result['local_poll_committed'] is False and result['retries'] == 0
    assert getattr(job, 'measure_clock') is measure and calls == [1]


def test_restore_after_interruption(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import forward_nifty_job as job
    import forward_versioned_capture as capture
    original = getattr(job, 'measure_clock')
    def interrupted(*args: Any) -> int:
        raise KeyboardInterrupt()
    monkeypatch.setattr(capture, 'run', interrupted)
    with pytest.raises(KeyboardInterrupt):
        ops.poll(tmp_path, DAY)
    assert getattr(job, 'measure_clock') is original


def test_poll_unknown_exit_never_promoted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import forward_versioned_capture as capture
    monkeypatch.setattr(capture, 'run', lambda *args: 0)
    assert ops.poll(tmp_path, DAY)['status'] == 'BLOCKED'


def test_preflight_stopped_service_does_not_imply_ntp_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, 'inspect_tasks', lambda *args: {'time_service_running': False,
        'poll': {'exists': True, 'action_matches': True}, 'audit': {'exists': True, 'action_matches': True}})
    monkeypatch.setattr(host, 'measure_clock', lambda: {'status': 'MEASURED'})
    monkeypatch.setattr(host, 'clock_error', lambda *args, **kwargs: None)
    monkeypatch.setattr(shutil, 'disk_usage', lambda path: type('Disk', (), {'free': host.MIN_FREE_BYTES})())
    result = host.preflight(DAY, 'poll', 'audit', tmp_path)
    assert result['blockers'] == ['WINDOWS_TIME_SERVICE_NOT_RUNNING']
    assert result['facts']['clock_check'] == 'PASS' and result['repairs_performed'] == 0


@pytest.mark.parametrize('value', ["bad'", 'a;exit', 'a b', '', '../task'])
def test_bad_task_name(value: str) -> None:
    with pytest.raises(ValueError):
        host.task_name(value)


def test_audit_is_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixtures = importlib.import_module('test_overnight_capture_audit')
    import forward_versioned_capture as capture
    producer = fixtures.make(tmp_path)
    fixtures.poll(producer, 1)
    config, frozen = tmp_path / 'config.json', tmp_path / 'recipe.json'
    config.write_text(json.dumps(producer.config))
    frozen.write_text(json.dumps(producer.frozen))
    monkeypatch.setattr(capture, 'paths', lambda *args: (config, frozen, producer.path))
    before = producer.path.read_bytes()
    result = ops.audit(tmp_path, date(2022, 1, 3), datetime.fromisoformat('2022-01-03T15:40:00+05:30'))
    assert result['missing_decisions'] == 74 and result['capture_writes'] == 0
    assert producer.path.read_bytes() == before
    with pytest.raises(ValueError, match='1540'):
        ops.audit(tmp_path, date(2022, 1, 3), datetime.fromisoformat('2022-01-03T15:39:59+05:30'))


def test_naive_audit_blocked(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='AWARE_AUDIT_TIME_REQUIRED'):
        ops.audit(tmp_path, DAY, datetime(2026, 10, 14, 15, 40))


def test_foreign_date_and_redaction(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    assert ops.main(['--root', 'unused', '--ops-root', 'unused', '--session-date', '2001-01-01',
                     '--mode', 'audit', '--confirm-ops']) == 2
    assert 'unused' not in capsys.readouterr().out


@pytest.mark.parametrize('issue', ['disk', 'tasks', 'clock', 'os'])
def test_preflight_failure_paths(issue: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, 'inspect_tasks', lambda *args: {'time_service_running': True,
        'poll': {'exists': True, 'action_matches': True}, 'audit': {'exists': True, 'action_matches': True}})
    monkeypatch.setattr(host, 'measure_clock', lambda: {'status': 'UNAVAILABLE'})
    monkeypatch.setattr(host, 'clock_error', lambda *a, **k: None)
    monkeypatch.setattr(shutil, 'disk_usage', lambda p: type('Disk', (), {'free': host.MIN_FREE_BYTES})())
    if issue == 'disk':
        monkeypatch.setattr(shutil, 'disk_usage', lambda p: type('Disk', (), {'free': 0})())
    elif issue == 'tasks':
        monkeypatch.setattr(host, 'inspect_tasks', lambda *a: {'time_service_running': True})
    elif issue == 'clock':
        monkeypatch.setattr(host, 'clock_error', lambda *a, **k: 'CLOCK_OFFSET_OR_UNCERTAINTY_EXCESSIVE')
    else:
        def failed(*args: Any) -> dict[str, Any]:
            raise OSError('private data not printed')
        monkeypatch.setattr(host, 'inspect_tasks', failed)
    result = host.preflight(DAY, 'poll', 'audit', tmp_path)
    assert result['status'] == 'BLOCKED' and result['blockers']
    assert 'private data' not in json.dumps(result)


def test_no_alert_on_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ops, 'notify', lambda c: pytest.fail('success notified'))
    ops.save(tmp_path, DAY, {'status': 'POLL_REMOTE_VERIFIED'}, visible=True)
    assert not list(tmp_path.glob('*.alert'))


def test_complete_does_not_claim_custody_or_training() -> None:
    opening = datetime(2026, 10, 14, 3, 45, tzinfo=timezone.utc)
    value = ops.coverage({'config': {'session_open': opening.isoformat()}, 'polls': [
        {'source': {'slot': (opening+timedelta(minutes=5*i)).isoformat()}, 'decision': {}}
        for i in range(1,76)], 'recorded_decisions': 75, 'missing_decisions': 0})
    assert value['coverage_requirement_met'] is True
    assert value['full_session_cohort_eligible'] is value['remote_custody_verified'] is False


def test_safe_stage_category_and_private_text_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import forward_versioned_capture as capture
    def blocked(*args: Any) -> int:
        print(json.dumps({'status':'BLOCKED','code':'FORWARD_CAPTURE_FAILED',
            'stage':'LOCAL_RECORD_POLL','category':'CLOSED_BAR_REVISION_REVIEW_REQUIRED',
            'error':'private connection string', 'local_poll_committed': 'untrusted string'}))
        return 2
    monkeypatch.setattr(capture, 'run', blocked)
    value = ops.poll(tmp_path, DAY)
    assert value['stage'] == 'LOCAL_RECORD_POLL'
    assert value['category'] == 'CLOSED_BAR_REVISION_REVIEW_REQUIRED'
    assert value['local_poll_committed'] is None and 'private connection string' not in json.dumps(value)


def test_preopen_warning_cannot_suppress_poll_or_coverage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    alerts: list[str] = []
    monkeypatch.setattr(ops, 'notify', lambda code: alerts.append(code))
    for result in ({'status':'BLOCKED', 'blockers':['POLL_TASK_ACTION_MISMATCH']},
                   {'status':'BLOCKED', 'code':'CLOCK_UNVERIFIED'},
                   {'status':'VERSIONED_COVERAGE_INCOMPLETE'}):
        ops.save(tmp_path, DAY, result, visible=True)
    assert alerts == ['PREOPEN_REVIEW_REQUIRED', 'CLOCK_REVIEW_REQUIRED', 'COVERAGE_REVIEW_REQUIRED']


def test_task_inspection_script_checks_binding_without_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    scripts: list[str] = []
    def capture(script: str) -> dict[str, Any]:
        scripts.append(script)
        return {}
    monkeypatch.setattr(host, 'powershell', capture)
    assert host.inspect_tasks(DAY, 'SyntheticPoll', 'SyntheticAudit', Path('C:/SyntheticState'), Path('C:/SyntheticOps')) == {}
    text = scripts[0]
    for value in ('Get-CimInstance', 'w32time', 'OrdinalIgnoreCase', 'SyntheticState', 'SyntheticOps', '-SessionDate', '-Mode'):
        assert value in text
    assert 'Set-Service' not in text and 'Enable-ScheduledTask' not in text


@pytest.mark.parametrize('verified', [True, False])
def test_cleanup_failure_preserves_known_receipt_without_promoting(verified: bool, tmp_path: Path,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    import forward_versioned_capture as capture
    def blocked(*args: Any) -> int:
        print(json.dumps({'status':'BLOCKED','code':'FORWARD_CAPTURE_FAILED','stage':'DRIVE_CLOSE',
                          'local_poll_committed':True,'remote_verified':verified,'receipt_written':verified}))
        return 2
    monkeypatch.setattr(capture, 'run', blocked)
    value = ops.poll(tmp_path, DAY)
    assert value['status'] == 'BLOCKED' and value['local_poll_committed'] is True
    assert value['remote_verified'] is value['receipt_written'] is verified
