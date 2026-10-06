"""Offline emergency collector admission; never touch production or credentials."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

import collector_storage_preflight as guard

NOW = datetime(2026, 10, 6, 5, 2, tzinfo=timezone.utc)


@pytest.mark.parametrize('size,allowed', [(495180597, False), (500000000, False),
    (500000001, False), (476000000, True), (476000001, False), (475999999, True)])
def test_headroom_boundary(size, allowed):
    result = guard.assess((NOW, size, False, False), NOW)
    assert result['allowed'] is allowed and result['transaction_enforced'] is False
    assert result['approval_authority'] is False


@pytest.mark.parametrize('row', [None, (), (NOW, 1, False),
    (NOW, True, False, False), (NOW, '1', False, False), (NOW, 0, False, False),
    (NOW.replace(tzinfo=None), 1, False, False), (NOW, 1, 0, False),
    (NOW, 1, False, 'false')])
def test_invalid_measurement(row):
    with pytest.raises(ValueError, match='STORAGE_MEASUREMENT_INVALID'):
        guard.assess(row, NOW)


@pytest.mark.parametrize('offset,allowed', [(0, True), (-60, True), (-61, False), (1, False)])
def test_freshness(offset, allowed):
    row = (NOW + timedelta(seconds=offset), 400000000, False, False)
    if allowed:
        assert guard.assess(row, NOW)['allowed'] is True
    else:
        with pytest.raises(ValueError, match='STALE_OR_FUTURE'): guard.assess(row, NOW)


@pytest.mark.parametrize('superuser,bypass', [(True, False), (False, True), (True, True)])
def test_owner_role_not_an_admission_shortcut(superuser, bypass):
    with pytest.raises(ValueError, match='RESTRICTED_ROLE_REQUIRED'):
        guard.assess((NOW, 1, superuser, bypass), NOW)


def test_preview_never_reads_connection_or_network(monkeypatch, capsys):
    monkeypatch.setattr(guard, 'measure', lambda *args: pytest.fail('Network'))
    monkeypatch.delenv('DATABASE_URL', raising=False)
    assert guard.main([]) == 0
    assert json.loads(capsys.readouterr().out)['network_calls'] == 0


def test_missing_connection_and_transport_failure_are_sanitized(monkeypatch, capsys):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    assert guard.main(['--check']) == 2
    assert 'DATABASE_CONNECTION_REQUIRED' in capsys.readouterr().out
    monkeypatch.setenv('DATABASE_URL', 'PRIVATE_CONNECTION')
    monkeypatch.setattr(guard, 'measure', lambda *args: (_ for _ in ()).throw(RuntimeError('PRIVATE_PASSWORD')))
    assert guard.main(['--check']) == 2
    result = capsys.readouterr().out
    assert 'STORAGE_CHECK_UNAVAILABLE' in result and 'PRIVATE_' not in result


@pytest.mark.parametrize('size,code', [(400000000, 0), (495180597, 2)])
def test_main_preserves_boolean_admission(monkeypatch, capsys, size, code):
    monkeypatch.setenv('DATABASE_URL', 'PRIVATE_CONNECTION')
    monkeypatch.setattr(guard, 'measure', lambda *args: (datetime.now(timezone.utc), size, False, False))
    assert guard.main(['--check']) == code
    assert json.loads(capsys.readouterr().out)['allowed'] is (code == 0)


def test_measure_uses_read_only_timeouts_and_all_cluster_databases(monkeypatch):
    import psycopg
    queries = []
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql): queries.append(sql)
        def fetchone(self): return (NOW, 495180597, False, False)
    class Connection:
        read_only = False
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def cursor(self):
            assert self.read_only is True
            return Cursor()
    def connect(url, **kwargs):
        assert kwargs == {'connect_timeout': 5, 'sslmode': 'require'}
        return Connection()
    monkeypatch.setattr(psycopg, 'connect', connect)
    assert guard.measure('PRIVATE_CONNECTION')[1] == 495180597
    assert queries[:2] == ["SET LOCAL statement_timeout='10s'", "SET LOCAL lock_timeout='2s'"]
    assert 'FROM pg_database' in queries[2] and 'datallowconn' not in queries[2]


def test_workflow_cannot_write_before_or_after_failed_admission():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / '.github/workflows/scheduled-collector.yml').read_text()
    assert workflow.index('run: python collector_storage_preflight.py --check') < workflow.index('--migrate')
    assert 'continue-on-error' not in workflow and 'always()' not in workflow
    assert 'permissions:\n  contents: read\n' in workflow
    assert workflow.count('run: python collector_storage_preflight.py --check') == 2
    recheck = workflow.index('- name: Recheck storage immediately before collection')
    assert workflow.index('run: python scheduled_collector.py --check') < recheck
    assert recheck < workflow.index('run: python scheduled_collector.py --mode')
