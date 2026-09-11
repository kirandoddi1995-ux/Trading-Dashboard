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


@pytest.mark.parametrize('ordinary_privileged_function', [False, True])
def test_event_trigger_excluded_but_ordinary_privileged_function_blocks(ordinary_privileged_function):
    class FunctionConnection(Connection):
        def execute(self, sql, params=None):
            if 'FROM pg_proc' in sql:
                assert "p.prorettype <> 'pg_catalog.event_trigger'::regtype" in sql
                assert 'p.prosecdef' in sql
                assert 'has_schema_privilege' in sql
                assert 'has_function_privilege' in sql
                return SimpleNamespace(fetchall=lambda: [('dangerous',)] if ordinary_privileged_function else [])
            return super().execute(sql, params)
    if ordinary_privileged_function:
        with pytest.raises(PermissionError, match='privileged function access'):
            ResearchRepository(FunctionConnection())
    else:
        ResearchRepository(FunctionConnection())


def test_function_filter_on_real_postgres():
    import json
    import os
    import subprocess
    module = os.environ.get('EQUITY_TEST_PGLITE_MODULE')
    if not module:
        pytest.skip('PostgreSQL-engine test harness not configured')
    queries = []
    class CaptureConnection(Connection):
        def execute(self, sql, params=None):
            if 'FROM pg_proc' in sql:
                queries.append(sql)
            return super().execute(sql, params)
    ResearchRepository(CaptureConnection())
    script = r'''
const {PGlite} = require(process.argv[1]);
const fs = require('fs');
(async () => {
  const db = new PGlite();
  await db.exec(`CREATE ROLE equity_research_collector;
    CREATE FUNCTION public.test_event_helper() RETURNS event_trigger
      LANGUAGE plpgsql SECURITY DEFINER AS $$ BEGIN RETURN; END $$;
    CREATE FUNCTION public.test_privileged_helper() RETURNS integer
      LANGUAGE sql SECURITY DEFINER AS $$ SELECT 1 $$;
    GRANT USAGE ON SCHEMA public TO equity_research_collector;
    GRANT EXECUTE ON FUNCTION public.test_event_helper(), public.test_privileged_helper()
      TO equity_research_collector;
    SET ROLE equity_research_collector;`);
  const result = await db.query(fs.readFileSync(0, 'utf8'));
  console.log(JSON.stringify(result.rows));
  await db.close();
})().catch(() => {process.exitCode = 1;});
'''
    result = subprocess.run(['node', '-e', script, module], input=queries[0],
                            text=True, capture_output=True, timeout=60, check=True)
    names = {row['proname'] for row in json.loads(result.stdout)}
    assert 'test_event_helper' not in names
    assert 'test_privileged_helper' in names


def test_workflow_check_job_has_no_collection_secrets_or_enable_gate():
    workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/equity-research-observations.yml').read_text()
    check_job = workflow.split('  check:\n')[1].split('  research:\n')[0]
    assert 'EQUITY_RESEARCH_ENABLED' not in check_job
    assert 'UPSTOX_ANALYTICS_TOKEN' not in check_job
    assert 'EQUITY_RESEARCH_SESSIONS_JSON' not in check_job
    assert 'run: python equity_research_collector.py --check' in check_job
    assert "inputs.mode == 'collect'" in workflow.split('  research:\n')[1]


@pytest.mark.parametrize('message,category', [
    ('password authentication failed', 'authentication_failure'),
    ('SASL authentication failed', 'authentication_failure'),
    ('could not translate host name', 'dns_failure'),
    ('Temporary failure in name resolution', 'dns_failure'),
    ('getaddrinfo failed', 'dns_failure'),
    ('connection timeout expired', 'timeout'),
    ('connection timed out', 'timeout'),
    ('Tenant or user not found', 'invalid_pooler_address_or_routing'),
    ('invalid port number', 'invalid_pooler_address_or_routing'),
    ('connection refused', 'unclassified_operational_error'),
    ('SSL connection has been closed unexpectedly', 'unclassified_operational_error'),
])
def test_cli_diagnostics_never_emit_raw_error_or_credentials(monkeypatch, capsys, message, category):
    import json
    import psycopg
    import equity_research_collector as collector
    secret = 'postgresql://private-user:private-password@private-host/postgres'
    def fail():
        raise psycopg.OperationalError(message + ' ' + secret)
    monkeypatch.setattr(collector, 'main', fail)
    with pytest.raises(SystemExit) as error:
        collector.cli()
    assert error.value.code == 1
    captured = capsys.readouterr()
    assert captured.err == ''
    assert json.loads(captured.out) == {
        'status': 'FAILED', 'error_type': 'OperationalError', 'error_category': category}
    assert secret not in captured.out
    assert message not in captured.out


def test_diagnostics_use_sqlstate_and_do_not_misclassify_other_errors():
    import psycopg
    from equity_research_collector import error_category
    assert error_category(psycopg.errors.InvalidPassword('private detail')) == 'authentication_failure'
    assert error_category(PermissionError('authentication failed')) == 'unclassified_error'
    assert error_category(ValueError('timeout expired')) == 'unclassified_error'
