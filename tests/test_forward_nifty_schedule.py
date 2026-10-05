"""Deterministic scheduler/installer policies; never register tasks or touch secrets."""
from datetime import date, datetime
import json
import os
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

import forward_nifty_schedule as schedule
from nifty_previous_close import parse_close
from research_integrity import IntegrityError, canonical, hash_value
from research_replay_comparison import ObservationJournal
from test_nifty_previous_close import v2_config, provenance, report


def clock(monkeypatch, value):
    monkeypatch.setattr(schedule, 'now', lambda: datetime.fromisoformat(value))


def config_file(tmp_path):
    path, state = schedule.session_paths(tmp_path, date(2026, 10, 5))
    path.parent.mkdir(parents=True)
    path.write_bytes(canonical(v2_config()))
    return path, state


def test_preview_has_no_network_vault_or_state(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(schedule, 'load', lambda: pytest.fail('Vault read'))
    monkeypatch.setattr(schedule, 'fetch', lambda *args, **kwargs: pytest.fail('Network'))
    assert schedule.main(['--root', str(tmp_path / 'new'), '--mode', 'poll']) == 0
    assert 'PREVIEW' in capsys.readouterr().out and not (tmp_path / 'new').exists()


@pytest.mark.parametrize('day,status', [('2026-10-02', 'CLOSED'), ('2026-10-04', 'CLOSED'), ('2024-03-02', 'SPECIAL')])
def test_nonregular_days_skip_without_network_or_vault(tmp_path, monkeypatch, capsys, day, status):
    clock(monkeypatch, day+'T09:00:00+05:30')
    monkeypatch.setattr(schedule, 'load', lambda: pytest.fail('Vault read'))
    monkeypatch.setattr(schedule, 'read_secret', lambda *args: pytest.fail('Vault read'))
    monkeypatch.setattr(schedule, 'fetch', lambda *args, **kwargs: pytest.fail('Network'))
    assert schedule.main(['--root', str(tmp_path), '--mode', 'prepare', '--confirm-run']) == 0
    assert 'SKIPPED_'+status in capsys.readouterr().out


def test_prepare_requires_explicit_licence_ack_before_source_fetch(tmp_path, monkeypatch, capsys):
    clock(monkeypatch, '2026-10-05T09:00:00+05:30')
    monkeypatch.setattr(schedule, 'read_secret', lambda *args: 'false')
    monkeypatch.setattr(schedule, 'fetch', lambda *args, **kwargs: pytest.fail('Network'))
    assert schedule.main(['--root', str(tmp_path), '--mode', 'prepare', '--confirm-run']) == 2
    assert 'LICENSE_ACK_REQUIRED' in capsys.readouterr().out


def test_automatic_preparation_retains_official_source_and_never_overwrites(tmp_path, monkeypatch):
    import requests
    class Session:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    clock(monkeypatch, '2026-10-05T09:00:00+05:30')
    monkeypatch.setattr(requests, 'Session', Session)
    monkeypatch.setattr(schedule, 'measure_clock', lambda: {})
    monkeypatch.setattr(schedule, 'clock_error', lambda *args, **kwargs: None)
    reads = []
    monkeypatch.setattr(schedule, 'fetch', lambda *args, **kwargs: reads.append(1) or provenance())
    result = schedule.prepare(tmp_path)
    assert result['status'] == 'CONFIG_PREPARED' and result['previous_close_date'] == '2026-10-01'
    path, _ = schedule.session_paths(tmp_path, date(2026, 10, 5))
    frozen = path.read_bytes()
    assert json.loads(frozen)['version'] == 'nifty-forward-v2'
    assert schedule.prepare(tmp_path)['status'] == 'CONFIG_ALREADY_PREPARED'
    assert reads == [1] and path.read_bytes() == frozen


def test_preopen_and_clock_checks_block_before_fetch(tmp_path, monkeypatch):
    monkeypatch.setattr(schedule, 'fetch', lambda *args, **kwargs: pytest.fail('Network'))
    clock(monkeypatch, '2026-10-05T09:15:00+05:30')
    with pytest.raises(IntegrityError, match='PREOPEN'): schedule.prepare(tmp_path)
    clock(monkeypatch, '2026-10-05T09:00:00+05:30')
    monkeypatch.setattr(schedule, 'measure_clock', lambda: {})
    monkeypatch.setattr(schedule, 'clock_error', lambda *args, **kwargs: 'MISSING')
    with pytest.raises(IntegrityError, match='CLOCK'): schedule.prepare(tmp_path)


def test_prepare_crossing_open_does_not_publish(tmp_path, monkeypatch):
    import requests
    class Session:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    clock(monkeypatch, '2026-10-05T09:14:59+05:30')
    monkeypatch.setattr(requests, 'Session', Session)
    monkeypatch.setattr(schedule, 'measure_clock', lambda: {})
    monkeypatch.setattr(schedule, 'clock_error', lambda *args, **kwargs: None)
    def fetched(*args, **kwargs):
        clock(monkeypatch, '2026-10-05T09:15:01+05:30')
        return provenance()
    monkeypatch.setattr(schedule, 'fetch', fetched)
    with pytest.raises(IntegrityError, match='PREOPEN'): schedule.prepare(tmp_path)
    assert not (tmp_path / '2026-10-05' / 'config.json').exists()


@pytest.mark.parametrize('stamp,allowed', [('09:19:59', False), ('09:20:30', True), ('09:22:00', True),
    ('09:22:01', False), ('15:30:30', True), ('15:35:30', False)])
def test_five_minute_slot_lateness_bounds_and_environment_cleanup(tmp_path, monkeypatch, stamp, allowed):
    config_file(tmp_path)
    clock(monkeypatch, '2026-10-05T'+stamp+'+05:30')
    monkeypatch.setenv('UPSTOX_ANALYTICS_TOKEN', 'ORIGINAL')
    monkeypatch.setattr(schedule, 'load', lambda: {'UPSTOX_ANALYTICS_TOKEN': 'PRIVATE', 'FORWARD_CAPTURE_LICENSE_ACK': 'true'})
    calls = []
    def capture(args):
        assert os.environ['UPSTOX_ANALYTICS_TOKEN'] == 'PRIVATE'
        assert '--confirm-run' in args
        calls.append(args)
        return 0
    monkeypatch.setattr(schedule, 'capture', capture)
    if allowed:
        assert schedule.poll(tmp_path) == 0 and len(calls) == 1
    else:
        with pytest.raises(IntegrityError, match='MISSED'): schedule.poll(tmp_path)
        assert not calls
    assert os.environ['UPSTOX_ANALYTICS_TOKEN'] == 'ORIGINAL'


def test_environment_restored_on_capture_exception(tmp_path, monkeypatch):
    config_file(tmp_path)
    clock(monkeypatch, '2026-10-05T09:20:30+05:30')
    monkeypatch.delenv('UPSTOX_ANALYTICS_TOKEN', raising=False)
    monkeypatch.setattr(schedule, 'load', lambda: {'UPSTOX_ANALYTICS_TOKEN': 'PRIVATE'})
    monkeypatch.setattr(schedule, 'capture', lambda *args: (_ for _ in ()).throw(RuntimeError('PRIVATE')))
    assert schedule.main(['--root', str(tmp_path), '--mode', 'poll', '--confirm-run']) == 2
    assert 'UPSTOX_ANALYTICS_TOKEN' not in os.environ
    assert len(list((tmp_path / 'scheduler-receipts').glob('*.json'))) == 1


def test_missing_vault_fails_sanitized_and_records_failure(tmp_path, monkeypatch, capsys):
    config_file(tmp_path)
    clock(monkeypatch, '2026-10-05T09:20:30+05:30')
    monkeypatch.setattr(schedule, 'load', lambda: (_ for _ in ()).throw(IntegrityError('PRIVATE_CREDENTIAL_REQUIRED')))
    assert schedule.main(['--root', str(tmp_path), '--mode', 'poll', '--confirm-run']) == 2
    assert 'PRIVATE_CREDENTIAL_REQUIRED' in capsys.readouterr().out


def test_audit_keeps_missing_decisions_visible_readonly(tmp_path, monkeypatch):
    path, state = config_file(tmp_path)
    ObservationJournal(state / 'observations.sqlite')
    before = (state / 'observations.sqlite').read_bytes()
    clock(monkeypatch, '2026-10-05T15:40:00+05:30')
    result = schedule.audit(tmp_path)
    assert result['status'] == 'SESSION_CAPTURE_INCOMPLETE' and result['missing_decisions'] == 75
    assert result['remote_acknowledged_decisions'] == 0
    assert (state / 'observations.sqlite').read_bytes() == before
    assert parse_close(report(), date(2026, 10, 1)) > 0 and path.exists()


def test_audit_requires_all_slots_and_complete_remote_acknowledgment(tmp_path, monkeypatch):
    path, state = config_file(tmp_path)
    state.mkdir(parents=True)
    clock(monkeypatch, '2026-10-05T15:40:00+05:30')
    class Journal:
        def __init__(self, file, *, read_only): assert read_only is True
        def read(self, *args): return [SimpleNamespace(available=False)]*75
    monkeypatch.setattr(schedule, 'ObservationJournal', Journal)
    assert schedule.audit(tmp_path)['status'] == 'SESSION_CAPTURE_INCOMPLETE'
    record = {'status': 'REMOTE_VERIFIED', 'spec_hash': hash_value(json.loads(path.read_bytes())),
              'format': 'forward-backup-manifest-v1', 'sha256': 'a'*64,
              'recorded_decisions': 74, 'data_file_id': 'DATA', 'manifest_file_id': 'MANIFEST',
              'approval_authority': False, 'fill_evidence': False}
    receipt = state / 'receipt-test.json'
    receipt.write_bytes(canonical(record))
    assert schedule.audit(tmp_path)['status'] == 'SESSION_CAPTURE_INCOMPLETE'
    record['recorded_decisions'] = 75
    receipt.write_bytes(canonical(record))
    result = schedule.audit(tmp_path)
    assert result['status'] == 'SESSION_CAPTURE_COMPLETE' and result['unavailable_decisions'] == 75
    record.pop('manifest_file_id')
    receipt.write_bytes(canonical(record))
    assert schedule.audit(tmp_path)['status'] == 'SESSION_CAPTURE_INCOMPLETE'


def test_audit_rejects_config_copied_under_the_wrong_session_day(tmp_path, monkeypatch):
    path, state = config_file(tmp_path)
    other_path, _ = schedule.session_paths(tmp_path, date(2026, 10, 6))
    other_path.parent.mkdir(parents=True)
    other_path.write_bytes(path.read_bytes())
    clock(monkeypatch, '2026-10-06T15:40:00+05:30')
    with pytest.raises(IntegrityError, match='CURRENT_AUTOMATIC'):
        schedule.audit(tmp_path)
    assert not state.exists()


def test_task_xml_is_disabled_normal_user_no_password_or_catchup(tmp_path):
    ns = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}
    for mode, at in [('prepare', '09:00:00'), ('poll', '09:20:30'), ('audit', '15:40:00')]:
        xml = schedule.task_xml(mode, tmp_path / 'private & space', date(2026, 10, 6), 'S-1-5-21-1001')
        tree = ET.fromstring(xml)
        assert tree.find('t:Settings/t:Enabled', ns).text == 'false'
        assert tree.find('t:Settings/t:StartWhenAvailable', ns).text == 'false'
        assert tree.find('t:Settings/t:MultipleInstancesPolicy', ns).text == 'IgnoreNew'
        assert tree.find('t:Principals/t:Principal/t:LogonType', ns).text == 'InteractiveToken'
        assert tree.find('t:Principals/t:Principal/t:RunLevel', ns).text == 'LeastPrivilege'
        assert tree.find('t:Triggers/t:CalendarTrigger/t:StartBoundary', ns).text.endswith(at+'+05:30')
        assert 'SECRET' not in xml and 'Password' not in xml
        if mode == 'poll':
            assert tree.find('t:Triggers/t:CalendarTrigger/t:Repetition/t:Interval', ns).text == 'PT5M'
            assert tree.find('t:Triggers/t:CalendarTrigger/t:Repetition/t:Duration', ns).text == 'PT6H11M'


def test_task_plans_write_verify_and_detect_tampering(tmp_path):
    args = ['--root', str(tmp_path), '--start-date', '2026-10-06', '--owner-sid', 'S-1-5-21-1001']
    assert schedule.main(args+['--write-task-plans']) == 0
    assert schedule.main(args+['--verify-task-plans']) == 0
    assert schedule.main(args+['--write-task-plans']) == 2
    (tmp_path / 'task-plans' / 'poll.xml').write_text('bad')
    assert schedule.main(args+['--verify-task-plans']) == 2


def test_repository_root_and_bad_task_identity_rejected():
    with pytest.raises(IntegrityError): schedule.task_xml(schedule.ROOT, schedule.ROOT, date(2026, 10, 6), 'bad')
    script = (Path(__file__).resolve().parents[1] / 'scripts' / 'install_forward_tasks.ps1').read_text()
    assert 'Enable-ScheduledTask' not in script and '-Force' not in script
    assert '--verify-task-plans' in script and 'RegisterTasks' in script
