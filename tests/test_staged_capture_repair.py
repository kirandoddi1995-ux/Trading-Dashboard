"""Offline checks of complete replacement files without editing active task sources."""
from datetime import date, datetime
import importlib.util
import json
from pathlib import Path

import pytest
from requests.exceptions import ConnectionError, ReadTimeout, SSLError

from research_integrity import IntegrityError


def staged(name, root=None):
    """Load a replacement under a distinct name; never replace active imports."""
    root = Path(__file__).resolve().parents[1] if root is None else root
    path = root / 'staged_capture_repair' / (name + '.py')
    if not path.exists():
        path = root / (name + '.py')
    spec = importlib.util.spec_from_file_location('repair_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_uploaded_root_files_are_used_when_staging_is_absent(tmp_path):
    (tmp_path / 'nifty_previous_close.py').write_text('marker = 1\n')
    assert staged('nifty_previous_close', tmp_path).marker == 1


@pytest.fixture
def schedule(monkeypatch):
    module = staged('forward_nifty_schedule')
    close = staged('nifty_previous_close')
    monkeypatch.setattr(module, 'fetch', close.fetch)
    monkeypatch.setattr(module, 'now', lambda: datetime.fromisoformat('2026-10-06T09:25:30+05:30'))
    return module


def test_missing_recipe_blocks_before_vault_or_capture(schedule, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(schedule, 'load', lambda: pytest.fail('Vault read'))
    monkeypatch.setattr(schedule, 'capture', lambda *args: pytest.fail('Capture'))
    assert schedule.main(['--root', str(tmp_path), '--mode', 'poll', '--confirm-run']) == 2
    result = json.loads(capsys.readouterr().out)
    assert result['code'] == 'SESSION_NOT_PREPARED' and result['stage'] == 'poll'
    assert not (tmp_path / '2026-10-06').exists()


@pytest.mark.parametrize('error_type', [ReadTimeout, ConnectionError, SSLError])
@pytest.mark.parametrize('stream_failure', [False, True])
def test_transport_failure_redacted_including_stream(error_type, stream_failure):
    close = staged('nifty_previous_close')
    class Response:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_content(self, size):
            raise error_type('PRIVATE_TOKEN_CONNECTION_STRING')
    class Session:
        def get(self, url, **kwargs):
            assert kwargs == dict(timeout=(5, 20), verify=True, allow_redirects=False, stream=True)
            if not stream_failure:
                raise error_type('PRIVATE_TOKEN_CONNECTION_STRING')
            return Response()
    with pytest.raises(IntegrityError) as failure:
        close.fetch(Session(), date(2026, 10, 6), received_clock=lambda: pytest.fail('Clock'))
    assert str(failure.value) == 'NSE_CLOSE_TRANSPORT_UNAVAILABLE'
    assert failure.value.__suppress_context__


def test_prepare_receipt_identifies_transport_without_raw_exception(schedule, tmp_path, monkeypatch, capsys):
    import requests
    monkeypatch.setattr(schedule, 'now', lambda: datetime.fromisoformat('2026-10-06T09:00:00+05:30'))
    monkeypatch.setattr(schedule, 'read_secret', lambda *args: 'true')
    monkeypatch.setattr(schedule, 'measure_clock', lambda: {})
    monkeypatch.setattr(schedule, 'clock_error', lambda *args, **kwargs: None)
    class Session:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, *args, **kwargs): raise ReadTimeout('PRIVATE_TOKEN')
    monkeypatch.setattr(requests, 'Session', Session)
    assert schedule.main(['--root', str(tmp_path), '--mode', 'prepare', '--confirm-run']) == 2
    output = capsys.readouterr().out
    assert 'PRIVATE_TOKEN' not in output
    assert json.loads(output)['code'] == 'NSE_CLOSE_TRANSPORT_UNAVAILABLE'
    assert json.loads(output)['stage'] == 'prepare'
    assert not (tmp_path / '2026-10-06' / 'config.json').exists()
    stored = next((tmp_path / 'scheduler-receipts').glob('*.json')).read_text()
    assert 'PRIVATE_TOKEN' not in stored and 'NSE_CLOSE_TRANSPORT_UNAVAILABLE' in stored


def test_missing_recipe_postsession_audit_records_all_missed_without_creating_state(schedule, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(schedule, 'now', lambda: datetime.fromisoformat('2026-10-06T15:40:00+05:30'))
    monkeypatch.setattr(schedule, 'load', lambda: pytest.fail('Vault read'))
    monkeypatch.setattr(schedule, 'ObservationJournal', lambda *args, **kwargs: pytest.fail('Journal creation'))
    assert schedule.main(['--root', str(tmp_path), '--mode', 'audit', '--confirm-run']) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'SESSION_CAPTURE_INCOMPLETE'
    assert result['code'] == 'SESSION_NOT_PREPARED'
    assert result['recorded_decisions'] == 0 and result['missing_decisions'] == 75
    assert result['remote_acknowledged_decisions'] == 0
    assert not (tmp_path / '2026-10-06').exists()


def test_missing_recipe_audit_cannot_claim_zero_if_state_exists(schedule, tmp_path, monkeypatch):
    monkeypatch.setattr(schedule, 'now', lambda: datetime.fromisoformat('2026-10-06T15:40:00+05:30'))
    state = tmp_path / '2026-10-06' / 'state'
    state.mkdir(parents=True)
    with pytest.raises(IntegrityError, match='SESSION_STATE_WITHOUT_CONFIG'):
        schedule.audit(tmp_path)
    assert state.exists()


def test_missing_recipe_audit_before_close_is_blocked(schedule, tmp_path):
    with pytest.raises(IntegrityError, match='POSTSESSION_AUDIT_REQUIRED'):
        schedule.audit(tmp_path)


def test_staged_preview_is_offline(schedule, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(schedule, 'read_secret', lambda *args: pytest.fail('Vault read'))
    assert schedule.main(['--root', str(tmp_path), '--mode', 'prepare']) == 0
    assert json.loads(capsys.readouterr().out)['network_calls'] == 0
    assert not list(tmp_path.iterdir())
