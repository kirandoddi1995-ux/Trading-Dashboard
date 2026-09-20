from contextlib import contextmanager
from decimal import Decimal
import ast
import os
from pathlib import Path
import subprocess
import uuid

import pytest

from equity_positions import PositionRepository, PositionError, owner_identity, portfolio_heat, validate_position
from test_equity_scan_repository import Connection


OWNER = owner_identity('subject', 'issuer')
ID = '00000000-0000-4000-8000-000000000001'
VALUES = dict(ticker='ABC', sector='Unclassified', entry=100, stop=90, target=120, quantity=10)


class Backend:
    configured = True
    def __init__(self, conn):
        self.conn = conn
        self.closed = False
    @contextmanager
    def connect(self):
        try:
            yield self.conn
        finally:
            self.closed = True


def repo(*rows):
    conn = Connection(fetchone=[('quant_app_runtime', False, False), *rows])
    backend = Backend(conn)
    return PositionRepository(backend), conn, backend


@pytest.mark.parametrize('field,value', [('entry', float('nan')), ('stop', -1), ('quantity', 1.5),
    ('quantity', True), ('quantity', 0), ('target', float('inf')), ('entry', '0.00001'), ('ticker', "ABC';--"),
    ('stop', 100), ('target', 99)])
def test_invalid_position_rejected(field, value):
    with pytest.raises(PositionError):
        validate_position(**{**VALUES, field: value})


def test_owner_is_stable_provider_scoped_and_missing_identity_fails():
    assert OWNER == owner_identity('subject', 'issuer')
    assert OWNER != owner_identity('subject', 'another issuer')
    with pytest.raises(PositionError):
        owner_identity(None, 'issuer')


def test_heat_uses_exact_entry_cost_and_does_not_hide_overallocation():
    rows = [dict(ticker='ABC', sector='Unclassified', entry_price='100.10', stop_price='90.05',
                 target_price=120, quantity=10, closed_at=None)]
    result = portfolio_heat(rows, 500, 25)
    assert result['deployed'] == Decimal('1001.00')
    assert result['unallocated'] == Decimal('-501.00')
    assert result['planned_risk'] == Decimal('100.50')
    assert result['heat_pct'] == Decimal('20.100')
    assert result['sectors'][0]['overweight'] is True
    assert portfolio_heat(rows, 0, 25)['heat_pct'] is None
    rows[0]['closed_at'] = 'closed'
    assert portfolio_heat(rows, 500, 25)['deployed'] == 0


def test_record_parameterized_and_connections_close():
    journal, conn, backend = repo(None, None)
    assert journal.record(OWNER, ID, **VALUES, confirmed=True) == (ID, True)
    assert conn.commits == 1 and backend.closed
    assert any("set_config('app.position_owner',%s,true)" in sql for sql, _ in conn.calls)
    assert not any(OWNER in sql for sql, _ in conn.calls)
    assert conn.calls[-1][1][:2] == (ID, OWNER)


def test_duplicate_same_request_is_idempotent_and_conflict_fails():
    stored = validate_position(**VALUES)
    journal, conn, _ = repo(stored)
    assert journal.record(OWNER, ID, **VALUES, confirmed=True) == (ID, False)
    assert not any(sql.startswith('INSERT') for sql, _ in conn.calls)
    journal, conn, _ = repo(stored)
    with pytest.raises(PositionError, match='different values'):
        journal.record(OWNER, ID, **{**VALUES, 'quantity': 20}, confirmed=True)
    assert conn.rollbacks == 1
    journal, _, _ = repo(None, (1,))
    with pytest.raises(PositionError, match='already exists'):
        journal.record(OWNER, str(uuid.uuid4()), **VALUES, confirmed=True)


def test_close_full_position_only_idempotent_and_owner_scoped():
    journal, conn, _ = repo((None, None))
    assert journal.close(OWNER, ID, confirmed=True)
    assert 'owner_id=%s' in conn.calls[-1][0]
    assert conn.calls[-1][1] == (None, OWNER, ID)
    journal, _, _ = repo(('closed', None))
    assert journal.close(OWNER, ID, confirmed=True) is False
    journal, _, _ = repo(('closed', Decimal(110)))
    with pytest.raises(PositionError, match='different exit'):
        journal.close(OWNER, ID, exit_price=111, confirmed=True)
    journal, _, _ = repo(None)
    with pytest.raises(PositionError, match='not found'):
        journal.close(OWNER, ID, confirmed=True)


def test_manual_confirmation_cannot_be_omitted_and_admin_rejected():
    journal, conn, _ = repo()
    with pytest.raises(PositionError):
        journal.record(OWNER, ID, **VALUES, confirmed=False)
    assert conn.calls == []
    backend = Backend(Connection(fetchone=[('postgres', True, True)]))
    with pytest.raises(PositionError, match='restricted'):
        PositionRepository(backend).list_open(OWNER)
    assert backend.closed and backend.conn.rollbacks == 1


@pytest.mark.skipif(not os.environ.get('EQUITY_TEST_PGLITE_MODULE'), reason='Local SQL harness not configured')
def test_sql_constraints_owner_rls_and_research_isolation():
    migration = (Path(__file__).resolve().parents[1] / 'sql/equity_positions_draft.sql').read_text()
    script = r"""
const {PGlite}=require(process.argv[1]);let input='';
process.stdin.on('data',c=>input+=c);process.stdin.on('end',async()=>{
const db=new PGlite();try{
 await db.exec(`CREATE ROLE quant_app_runtime LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS;
 CREATE ROLE equity_research_collector;CREATE ROLE anon;CREATE ROLE authenticated;CREATE ROLE service_role;
 CREATE SCHEMA equity_operations;REVOKE ALL ON SCHEMA equity_operations FROM PUBLIC;
 GRANT USAGE ON SCHEMA equity_operations TO quant_app_runtime;`);
 await db.exec(input);
 await db.exec('SET ROLE quant_app_runtime');
 const owner='a'.repeat(64),other='b'.repeat(64);
 const insert=`INSERT INTO equity_operations.positions(position_id,owner_id,ticker,sector,entry_price,stop_price,target_price,quantity)
 VALUES($1,$2,'ABC','Unclassified',$3,$4,$5,$6)`;
 async function denied(fn){let fail=false;try{await fn();}catch(e){fail=true;}if(!fail)throw Error('Expected database rejection');}
 await denied(()=>db.query(insert,['00000000-0000-4000-8000-000000000001',owner,100,90,120,10]));
 await db.query("SELECT set_config('app.position_owner',$1,false)",[owner]);
 await denied(()=>db.query(insert,['00000000-0000-4000-8000-000000000001',other,100,90,120,10]));
 for(const values of [[100,100,120,10],[100,90,99,10],[100,90,120,0],['NaN',90,120,10]])
   await denied(()=>db.query(insert,['00000000-0000-4000-8000-000000000001',owner,...values]));
 await db.query(insert,['00000000-0000-4000-8000-000000000001',owner,100,90,120,10]);
 await denied(()=>db.query(insert,['00000000-0000-4000-8000-000000000002',owner,100,90,120,10]));
 await denied(()=>db.exec('DELETE FROM equity_operations.positions'));
 await denied(()=>db.exec('UPDATE equity_operations.positions SET quantity=20'));
 await db.query("SELECT set_config('app.position_owner',$1,false)",[other]);
 if((await db.query('SELECT * FROM equity_operations.positions')).rows.length)throw Error('Owner leak');
 if((await db.query('UPDATE equity_operations.positions SET closed_at=clock_timestamp()')).affectedRows)throw Error('Cross-owner close');
 await db.query("SELECT set_config('app.position_owner',$1,false)",[owner]);
 const size=(await db.query('SELECT pg_column_size(p) AS bytes FROM equity_operations.positions p')).rows[0].bytes;
 if(size>1024)throw Error('Unexpectedly large compact row');
 await db.exec('UPDATE equity_operations.positions SET closed_at=clock_timestamp()');
 if((await db.query('UPDATE equity_operations.positions SET closed_at=clock_timestamp()')).affectedRows)throw Error('Closed record rewritten');
 await db.query(insert,['00000000-0000-4000-8000-000000000002',owner,100,90,120,10]);
 await db.exec('RESET ROLE;SET ROLE equity_research_collector');
 await denied(()=>db.exec('SELECT * FROM equity_operations.positions'));
 console.log('POSITIONS_SQL_PASS row_bytes='+size);
}catch(e){console.error(e.message);process.exitCode=1;}finally{await db.close();}});
"""
    result = subprocess.run(['node', '-e', script, os.environ['EQUITY_TEST_PGLITE_MODULE']],
                            input=migration, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    print(result.stdout.strip())
    assert 'POSITIONS_SQL_PASS' in result.stdout


def test_ui_wiring_is_equity_journal_only():
    root = Path(__file__).resolve().parents[1]
    app = (root / 'app.py').read_text(encoding='utf-8')
    assert 'render_portfolio_heat_panel()' in app
    assert 'render_persistent_positions_sidebar()' in app
    assert "if sizing_available and real_qty > 0 and investment_capital > 0:" in app
    assert "st.secrets.get('positions', {}).get('owner_key')" in app
    source = (root / 'equity_positions.py').read_text()
    for forbidden in ('equity_research.', 'DECISION_EVALUATED', 'execution_evidence', 'order_results'):
        assert forbidden not in source


@pytest.mark.parametrize('secrets,valid', [
    ({'positions': {'owner_key': 'kiran-quant-positions-v1'}}, True),
    ({'positions': {'owner_key': '  kiran-quant-positions-v1  '}}, True),
    ({}, False), ({'positions': {}}, False), ({'positions': None}, False),
    ({'positions': {'owner_key': ''}}, False),
    ({'positions': {'owner_key': '   '}}, False),
    ({'positions': {'owner_key': 123}}, False),
])
def test_configured_owner_without_oidc(secrets, valid):
    import hashlib
    from types import SimpleNamespace
    source = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
    function = next(n for n in ast.parse(source).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'persistent_position_owner')
    namespace = dict(st=SimpleNamespace(secrets=secrets), hashlib=hashlib, PositionError=PositionError)
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<owner-test>', 'exec'), namespace)
    owner = namespace['persistent_position_owner']
    if valid:
        expected = hashlib.sha256(b'kiran-quant-positions-v1').hexdigest()
        assert owner() == owner() == expected
        assert len(expected) == 64 and set(expected) <= set('0123456789abcdef')
    else:
        with pytest.raises(PositionError, match=r'\[positions\]'):
            owner()
    class MissingSecrets:
        def get(self, *args):
            raise FileNotFoundError('no local secrets file')
    namespace['st'].secrets = MissingSecrets()
    with pytest.raises(PositionError, match='owner_key'):
        owner()


def test_streamlit_position_form_and_heat_panel():
    from streamlit.testing.v1 import AppTest
    source = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
    names = {'_position_error', 'render_position_entry_form', 'render_portfolio_heat_panel',
             'render_persistent_positions_sidebar'}
    functions = '\n\n'.join(ast.unparse(n) for n in ast.parse(source).body
                            if isinstance(n, ast.FunctionDef) and n.name in names)
    script = '''
import streamlit as st
import pandas as pd
import uuid, logging
from types import SimpleNamespace
from equity_positions import PositionError, portfolio_heat, validate_position
LOGGER=logging.getLogger('ui-test')
DURABLE_REPOSITORY=SimpleNamespace(configured=True)
investment_capital=1000
max_sector_exposure_pct=25
CURRENT_USER_ID='legacy-session'
persistent_position_owner=lambda: 'a'*64
get_sector_bucket=lambda ticker:'Unclassified'
get_positions_df=lambda owner:pd.DataFrame()
_rerun_with_metrics=st.rerun
def load_persistent_positions(owner):
    return st.session_state.setdefault('rows', [])
def record_persistent_position(owner, request_id, **values):
    if not values.pop('confirmed'):
        raise PositionError('Confirmation required')
    ticker,sector,entry,stop,target,qty=validate_position(**values)
    st.session_state.rows.append(dict(position_id=request_id,ticker=ticker,sector=sector,
        entry_price=entry,stop_price=stop,target_price=target,quantity=qty,
        recorded_at='2026-09-20',closed_at=None))
    return request_id,True
def close_persistent_position(owner, selected, **values):
    if not values.get('confirmed'):raise PositionError('Confirmation required')
    st.session_state.rows=[r for r in st.session_state.rows if r['position_id']!=selected]
'''+functions+'''
with st.sidebar:
    render_persistent_positions_sidebar()
render_portfolio_heat_panel()
'''
    at = AppTest.from_string(script).run()
    assert not at.exception
    at.text_input[0].set_value('ABC')
    for label, value in [('Actual average entry (₹)',100),('Planned stop (₹)',90),('Planned target (₹)',120)]:
        next(w for w in at.number_input if w.label == label).set_value(value)
    at.checkbox[0].check()
    next(b for b in at.button if b.label == 'Track Position').click().run()
    assert not at.exception
    assert at.metric[0].value == '₹100.00'
    next(w for w in at.checkbox if 'exited ALL' in w.label).check()
    next(b for b in at.button if b.label == 'Mark fully closed').click().run()
    assert not at.exception
    assert at.metric[0].value == '₹0.00'
