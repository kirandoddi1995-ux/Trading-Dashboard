from pathlib import Path
from types import SimpleNamespace

import pytest

from equity_research_repository import ResearchRepository, ROLE


class Connection:
    def __init__(self, role=ROLE, unsafe=False):
        self.role, self.unsafe = role, unsafe

    def execute(self, sql, params=None):
        if 'FROM pg_roles' in sql:
            return SimpleNamespace(fetchone=lambda: (self.role,self.role,False,False,False,False,False,False,False))
        if 'FROM pg_class' in sql:
            return SimpleNamespace(fetchall=lambda: [('forbidden',)] if self.unsafe else [])
        if 'FROM pg_proc' in sql:
            return SimpleNamespace(fetchall=lambda: [])
        if 'has_table_privilege' in sql:
            return SimpleNamespace(fetchone=lambda: (True,'source_decisions' not in params[0],False,False,False,False))
        raise AssertionError(sql)


def test_requires_real_restricted_login():
    ResearchRepository(Connection())
    with pytest.raises(PermissionError):
        ResearchRepository(Connection(role='postgres'))
    with pytest.raises(PermissionError):
        ResearchRepository(Connection(unsafe=True))


def test_no_production_credentials_or_migration_runner():
    source = (Path(__file__).resolve().parents[1] / 'equity_research_collector.py').read_text()
    assert "os.environ.get('DATABASE_URL')" not in source
    assert 'DATABASE_MIGRATION_URL' not in source
    assert 'ProductionRepository' not in source
    workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/equity-research-observations.yml').read_text()
    assert "vars.EQUITY_RESEARCH_ENABLED == 'true'" in workflow
    assert 'secrets.DATABASE_URL' not in workflow


def test_market_fetch_is_get_only_and_preserves_raw(monkeypatch):
    from equity_research_collector import fetch_minutes
    import datetime as dt
    monkeypatch.setattr('equity_research_collector.time.sleep', lambda _: None)
    candle = ['2026-09-10T10:00:00+05:30',100,101,99,100]
    calls = []
    class Client:
        def get(self, url, **kwargs):
            calls.append(url)
            return SimpleNamespace(status_code=200,json=lambda: {'status':'success','data':{'candles':[candle]}})
    result = fetch_minutes(Client(),'TEST','NSE_EQ|FIXTURE',dt.date(2026,9,10),dt.date(2026,9,10))
    assert result == [candle]
    assert '/historical-candle/' in calls[0]


def test_outside_cohort_never_registered():
    repo = ResearchRepository(Connection())
    with pytest.raises(ValueError):
        repo.register({'decision_id':'outside','policy':'bad','purpose':'bad'})


def test_check_main_is_read_only_and_never_collects(monkeypatch, capsys):
    import sys
    import equity_research_collector as collector
    calls = []
    class CheckConnection:
        read_only = False
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def rollback(self):
            calls.append('rollback')
    connection = CheckConnection()
    class Repo:
        def __init__(self, conn):
            assert conn.read_only is True
            calls.append('permissions')
        def sources(self):
            calls.append('select_sources')
            return [{}] * 89
    monkeypatch.setitem(sys.modules, 'psycopg', SimpleNamespace(connect=lambda *a,**k: connection))
    monkeypatch.setattr(collector, 'ResearchRepository', Repo)
    monkeypatch.setattr(collector, 'enroll', lambda *a,**k: calls.append('validate_in_memory'))
    def forbidden(*args, **kwargs):
        raise AssertionError('Check must not collect or contact market data')
    monkeypatch.setattr(collector, 'collect', forbidden)
    monkeypatch.setattr('requests.Session', forbidden)
    monkeypatch.setenv('EQUITY_RESEARCH_DATABASE_URL', 'test-only')
    monkeypatch.delenv('UPSTOX_ANALYTICS_TOKEN', raising=False)
    monkeypatch.delenv('EQUITY_RESEARCH_SESSIONS_JSON', raising=False)
    monkeypatch.setattr(sys, 'argv', ['collector', '--check'])
    collector.main()
    assert calls == ['permissions', 'select_sources'] + ['validate_in_memory'] * 89 + ['rollback']
    assert '"read_only": true' in capsys.readouterr().out


def test_permission_verifier_issues_only_selects():
    class ReadOnlyConnection(Connection):
        def execute(self, sql, params=None):
            assert sql.strip().upper().startswith('SELECT ')
            return super().execute(sql, params)
    ResearchRepository(ReadOnlyConnection())


def test_workflow_check_job_has_no_collection_secrets_or_enable_gate():
    workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/equity-research-observations.yml').read_text()
    check_job = workflow.split('  check:\n')[1].split('  research:\n')[0]
    assert 'EQUITY_RESEARCH_ENABLED' not in check_job
    assert 'UPSTOX_ANALYTICS_TOKEN' not in check_job
    assert 'EQUITY_RESEARCH_SESSIONS_JSON' not in check_job
    assert 'run: python equity_research_collector.py --check' in check_job
    assert "inputs.mode == 'collect'" in workflow.split('  research:\n')[1]
