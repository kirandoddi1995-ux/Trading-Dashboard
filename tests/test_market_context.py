import ast
import base64
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import gzip
import io
import json
from pathlib import Path

import pytest

import market_context as m
from market_context_sources import import_manual, parse_participant_oi, OI_COLUMNS, collect_quotes, collect_participant_oi
from market_context_archive import archive_context, unpack, validate
from market_context_job import main

NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def value(kind='VIX', price='18', at=NOW, **payload):
    return m.record(dict(kind=kind, series=kind, source_at=at.isoformat(),
                        source_url='https://'+m.DOMAINS[kind][0]+'/source',
                        unit=m.UNITS[kind], payload=dict(value=price, **payload)), received_at=NOW)


def event(**payload):
    return m.record(dict(kind='EVENT', series='RBI:STANCE', source_at=(NOW-timedelta(days=1)).isoformat(),
        published_at=(NOW-timedelta(days=1)).isoformat(), source_url='https://rbi.org.in/source',
        payload=dict(category='RBI', component='STANCE', window_start=(NOW-timedelta(hours=1)).isoformat(),
                     window_end=(NOW-timedelta(minutes=45)).isoformat(), **payload)), received_at=NOW)


@pytest.mark.parametrize('bad', [None, True, 'NaN', 'Infinity', 'abc'])
def test_missing_numbers_never_become_zero(bad):
    with pytest.raises(m.ContextError):
        value(price=bad)


def test_first_known_is_ingestion_not_claimed_history():
    row = value(at=NOW-timedelta(days=2))
    assert not m.known([row], NOW-timedelta(seconds=1))
    uploaded = dict(row, available_at='2000-01-01T00:00:00+00:00')
    loaded = import_manual(json.dumps({'records': [uploaded]}).encode(), NOW)
    assert loaded['records'][0]['available_at'] == NOW.isoformat()
    assert loaded['approval_eligible'] is False


def test_units_naive_future_and_untrusted_hosts_rejected():
    row = value()
    for changes in [dict(unit='FRACTION'), dict(source_at=NOW.replace(tzinfo=None).isoformat()),
                    dict(source_at=(NOW+timedelta(seconds=1)).isoformat()),
                    dict(source_url='https://upstox.com.attacker.test/x'),
                    dict(source_url='https://upstox.com:bad/x')]:
        with pytest.raises(m.ContextError):
            m.record(dict(row, **changes), received_at=NOW)
    assert m.freshness(value(at=NOW-timedelta(days=1)), NOW) == 'STALE'


def test_gift_requires_same_explicit_contract_and_anchors():
    args = dict(contract_id='NIFTY-FUT-SEP', contract_source_url='https://nseix.com/contract')
    prior = value('GIFT', '25000', NOW-timedelta(days=1), anchor='INDIA_CLOSE', session_date='2026-09-29', **args)
    current = value('GIFT', '25250', previous_session_date='2026-09-29', anchor='PREOPEN', **args)
    assert m.gift_overnight(current, prior, NOW) == Decimal('1.00')
    for field, bad in [('contract_id', None), ('contract_id', 'OCT'), ('previous_session_date', '2026-09-28'),
                       ('anchor', 'LTP'), ('contract_source_url', None)]:
        changed = dict(current, payload=dict(current['payload'], **{field: bad}))
        assert m.gift_overnight(changed, prior, NOW) is None


def test_vix_percentile_distinct_prior_sessions_and_point_in_time():
    current = value()
    rows = [value('VIX_CLOSE', '17', NOW-timedelta(days=i), session_date=str((NOW-timedelta(days=i)).date()))
            for i in range(1, 253)]
    assert m.vix_percentile(current, rows, NOW) == Decimal(100)
    assert m.vix_percentile(current, rows[:-1]+[rows[0]], NOW) is None
    assert m.vix_percentile(current, rows, NOW-timedelta(seconds=1)) is None


def test_yield_basis_points_cannot_cross_benchmark_roll():
    prior = value('GSEC10Y', '6.50', NOW-timedelta(days=1), benchmark_id='bond-A')
    assert m.yield_change_bp(value('GSEC10Y', '6.55', benchmark_id='bond-A'), prior, NOW) == Decimal('5.00')
    assert m.yield_change_bp(value('GSEC10Y', '6.55', benchmark_id='bond-B'), prior, NOW) is None


def test_events_never_automatically_clear_or_authorize():
    assert m.event_state(event(), NOW+timedelta(days=10)) == 'UNRESOLVED_REVIEW_REQUIRED'
    assert m.event_state(event(review_completed_at=NOW.isoformat()), NOW) == 'REVIEW_RECORDED_NOT_AUTHORIZATION'
    assert m.event_state(event(), NOW-timedelta(days=2)) == 'NOT_YET_AVAILABLE'
    assert event()['approval_eligible'] is False


def test_rebalance_publication_separate_from_effective_date():
    raw = dict(kind='REBALANCE', series='MSCI', source_at=NOW.isoformat(), published_at=NOW.isoformat(),
               source_url='https://msci.com/review', payload={'effective_at': (NOW+timedelta(days=30)).isoformat()})
    row = m.record(raw, received_at=NOW)
    assert m.known([row], NOW)
    with pytest.raises(m.ContextError):
        m.record(dict(raw, published_at=(NOW+timedelta(days=1)).isoformat()), received_at=NOW)


def oi_file():
    stream = io.StringIO()
    w = csv.writer(stream)
    w.writerow(['Participant wise Open Interest on Sep 30, 2026'])
    w.writerow(['Client Type', *OI_COLUMNS])
    for p in ('Client', 'DII', 'FII', 'Pro'):
        w.writerow([p, *([1]*12), 6, 6])
    w.writerow(['TOTAL', *([4]*12), 24, 24])
    return stream.getvalue().encode()


def test_oi_totals_publication_and_raw_bytes_retained():
    raw = b'\xef\xbb\xbf'+oi_file()
    packet = parse_participant_oi(raw, NOW.date(), NOW)
    assert len(packet['records']) == 4
    assert all(r['published_at'] is None and r['available_at'] == NOW.isoformat() for r in packet['records'])
    assert base64.b64decode(packet['source_files'][0]['bytes_base64']) == raw
    validate(packet)
    assert not m.known(packet['records'], NOW-timedelta(seconds=1))


@pytest.mark.parametrize('mutation', ['date', 'total', 'schema', 'missing'])
def test_oi_failure_never_becomes_empty_valid_data(mutation):
    raw = oi_file()
    if mutation == 'date':
        raw = raw.replace(b'Sep 30', b'Sep 29')
    elif mutation == 'total':
        raw = raw.replace(b',24,24', b',25,24')
    elif mutation == 'schema':
        raw = raw.replace(b'Future Index Long', b'Changed Column')
    else:
        raw = b'\n'.join(l for l in raw.splitlines() if not l.startswith(b'Pro,'))
    with pytest.raises(m.ContextError):
        parse_participant_oi(raw, NOW.date(), NOW)


def test_official_missing_file_fails_without_empty_payload():
    class Response:
        status_code = 404
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    class Client:
        def get(self, url, **kwargs):
            assert kwargs['allow_redirects'] is False
            assert url.endswith('30092026.csv')
            return Response()
    with pytest.raises(m.ContextError, match='OFFICIAL_OI_UNAVAILABLE'):
        collect_participant_oi(Client(), NOW.date())


def test_quotes_reuse_read_adapters_and_do_not_invent_trade_timestamps(monkeypatch):
    import prospective_collection as p
    import market_context_sources as s
    monkeypatch.setattr(s, 'now', lambda: NOW)
    def master(client, url):
        if url == p.GLOBAL_INSTRUMENTS:
            return [dict(segment='GLOBAL_INDEX', name='GIFT NIFTY', instrument_key='GLOBAL_INDEX|SGX NIFTY')]
        return [dict(segment='NCD_FO', instrument_type='FUT', underlying_symbol='USDINR',
                     instrument_key='NCD_FO|test', expiry='2026-10-28')]
    monkeypatch.setattr(p, '_fetch_instrument_master', master)
    def quotes(client, token, keys):
        return {'quotes': {k: dict(last_price=18, timestamp=int(NOW.timestamp()*1000),
                                   last_trade_time=int(NOW.timestamp()*1000), _received_at=NOW.isoformat()) for k in keys}}
    monkeypatch.setattr(p, 'fetch_global_quotes', quotes)
    packet = collect_quotes(None, 'not-a-real-token')
    assert len(packet['records']) == 3
    gift = m.latest(packet['records'], 'GIFT', NOW)
    assert gift['payload']['contract_id'] is None
    assert m.latest(packet['records'], 'USDINR', NOW)['payload']['proxy'] is True
    monkeypatch.setattr(p, 'fetch_global_quotes', lambda *a: {'quotes': {'NSE_INDEX|India VIX': {'last_price': 18}}})
    assert not collect_quotes(None, 'not-a-real-token')['records']


class Drive:
    def __init__(self, corrupt=None):
        self.files = {}
        self.corrupt = corrupt
    def check_folder(self):
        pass
    def put(self, name, data, batch, kind, mime):
        self.files.setdefault(kind, data)
        return kind
    def download(self, key):
        return b'bad' if self.corrupt == key else self.files[key]


def test_archive_roundtrip_retry_and_checksum():
    packet = parse_participant_oi(oi_file(), NOW.date(), NOW)
    drive = Drive()
    first = archive_context(drive, packet)
    assert first == archive_context(drive, packet)
    assert unpack(drive.files['data']) == packet
    assert json.loads(drive.files['manifest'])['row_count'] == 4


@pytest.mark.parametrize('kind', ['data', 'manifest'])
def test_archive_corruption_fails(kind):
    with pytest.raises(m.ContextError):
        archive_context(Drive(kind), m.bundle([value()], NOW))


def test_archive_bombs_and_tampering_rejected():
    with pytest.raises(m.ContextError):
        unpack(gzip.compress(b'x'*(m.MAX_BYTES+1)))
    packet = m.bundle([value()], NOW)
    packet['records'][0]['approval_eligible'] = True
    with pytest.raises(m.ContextError):
        validate(packet)


def test_preview_offline_and_disabled_job_sanitized(monkeypatch, capsys):
    monkeypatch.setenv('DRIVE_OAUTH_TOKEN_JSON', 'TOP-SECRET-TOKEN')
    monkeypatch.delenv('MARKET_CONTEXT_ARCHIVE_ENABLED', raising=False)
    assert main(['--preview']) == 0
    assert main([]) == 1
    output = capsys.readouterr()
    assert 'TOP-SECRET-TOKEN' not in output.out+output.err


def test_ui_integration_is_statement_not_decision_and_no_database_imports():
    tree = ast.parse((ROOT/'app.py').read_text(encoding='utf-8'))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
             and isinstance(n.value.func, ast.Name) and n.value.func.id == 'render_market_context']
    assert len(calls) == 1
    for name in ('market_context.py', 'market_context_sources.py', 'market_context_ui.py',
                 'market_context_archive.py', 'market_context_job.py'):
        tree = ast.parse((ROOT/name).read_text(encoding='utf-8'))
        imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not imports & {'production_repository', 'live_governance', 'derivative_preflight', 'model_registry'}
    workflow = (ROOT/'.github/workflows/market-context.yml').read_text()
    assert 'DATABASE_URL' not in workflow and 'UPSTOX' not in workflow
    assert 'contents: read' in workflow
    assert 'MARKET_CONTEXT_ARCHIVE_ENABLED' in workflow


def test_vix_uses_prior_ist_session_and_exposes_exact_baseline(monkeypatch):
    import pandas as pd
    import prospective_collection as p
    import market_context_sources as s
    monkeypatch.setattr(s, 'now', lambda: NOW)
    monkeypatch.setattr(p, '_fetch_instrument_master', lambda *a: [])
    monkeypatch.setattr(p, 'fetch_global_quotes', lambda *a: {'quotes': {s.VIX: dict(
        last_price='13.42', timestamp=NOW.isoformat(), last_trade_time=int(NOW.timestamp()*1000),
        _received_at=NOW.isoformat())}})
    # UTC midnight boundary: the second candle belongs to TODAY in India.
    history = pd.DataFrame({'Close': ['13.41', '999']}, index=pd.to_datetime(
        ['2026-09-28T18:30:00Z', '2026-09-29T18:30:00Z']))
    packet = s.collect_quotes(None, 'fake-token', vix_history=lambda: history)
    current = m.latest(packet['records'], 'VIX', NOW)
    comparison = m.vix_close_comparison(current, packet['records'], NOW)
    assert comparison['change'] == Decimal('0.01')
    assert comparison['close'] == Decimal('13.41')
    assert comparison['session_date'] == '2026-09-29'
    assert comparison['calendar_days'] == 1


def test_vix_comparison_excludes_current_session_other_series_and_future_availability():
    current = value()
    def close(day, series='VIX', received=NOW):
        raw = value('VIX_CLOSE', '17', NOW-timedelta(days=1), session_date=day)
        return m.record(dict(raw, series=series), received_at=received)
    assert m.vix_close_comparison(current, [close('2026-09-30')], NOW) is None
    assert m.vix_close_comparison(current, [close('2026-09-29', 'OTHER')], NOW) is None
    assert m.vix_close_comparison(current, [close('2026-09-29', received=NOW+timedelta(seconds=1))], NOW) is None


@pytest.mark.parametrize('input_value,code', [(None, 'MISSING'), ('credential-secret', 'INVALID'),
    (0, 'INVALID'), (True, 'INVALID'), (int((NOW+timedelta(seconds=1)).timestamp()*1000), 'IN_FUTURE')])
def test_quote_time_specific_sanitized_diagnostics(input_value, code):
    from market_context_sources import quote_time
    with pytest.raises(m.ContextError) as error:
        quote_time({'last_trade_time': input_value}, 'last_trade_time', NOW)
    assert str(error.value) == 'LAST_TRADE_TIME_'+code
    assert 'credential-secret' not in str(error.value)


def test_quote_missing_time_remains_unavailable_with_field_reason(monkeypatch):
    import prospective_collection as p
    import market_context_sources as s
    monkeypatch.setattr(p, '_fetch_instrument_master', lambda *a: [])
    monkeypatch.setattr(p, 'fetch_global_quotes', lambda *a: {'quotes': {s.VIX: dict(
        last_price=13.42, timestamp=NOW.isoformat(), _received_at=NOW.isoformat())}})
    result = s.collect_quotes(None, 'fake-token')
    assert not result['records']
    assert 'VIX_LAST_TRADE_TIME_MISSING' in result['issues']


def app_function(name, namespace):
    """Exercise the actual function without importing the network-capable dashboard."""
    import copy
    tree = ast.parse((ROOT/'app.py').read_text(encoding='utf-8'))
    node = copy.deepcopy(next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name))
    decorators = node.decorator_list
    node.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), 'app.py', 'exec'), namespace)
    return namespace[name], decorators


def test_websocket_fragment_rereads_live_memory_without_api_calls():
    from types import SimpleNamespace
    from unittest.mock import Mock
    status = dict(connected=False, subscribed=2, quotes=2, auth_failed=False)
    st = Mock()
    render, decorators = app_function('render_websocket_status', dict(st=st, MARKET_OPEN=True,
        UPSTOX_API_HEALTH=SimpleNamespace(snapshot=lambda: {'status': 200}),
        get_market_data_buffer=lambda token: SimpleNamespace(status=lambda: dict(status))))
    assert decorators[0].func.attr == 'fragment'
    assert decorators[0].keywords[0].value.value == '2s'
    render('fake-token')
    assert 'CONNECTING' in st.info.call_args.args[0]
    status['connected'] = True
    render('fake-token')
    assert 'LIVE' in st.success.call_args.args[0]
    status['auth_failed'] = True
    render('fake-token')
    assert 'TOKEN REJECTED' in st.error.call_args.args[0]


def test_missing_derivative_schema_every_check_blocks_but_logs_throttled():
    import datetime as dt
    from types import SimpleNamespace
    from unittest.mock import Mock
    from psycopg.errors import UndefinedTable
    from derivative_preflight import PreflightResult
    repo = Mock()
    repo.load.side_effect = UndefinedTable('private SQL and credentials must not appear')
    logger = Mock()
    state = {}
    clock = Mock(side_effect=[0, 1, 2, 61])
    check, _ = app_function('derivative_entry_preflight', dict(
        datetime=dt, IST=timezone.utc, DURABLE_REPOSITORY=SimpleNamespace(configured=True, connect=Mock()),
        DerivativeRepository=lambda *a: repo, PreflightResult=PreflightResult, LOGGER=logger,
        time=SimpleNamespace(monotonic=clock), st=SimpleNamespace(session_state=state)))
    for _ in range(4):
        result = check('NSE_FO|test', 'fake-token')
        assert not result.eligible and 'tables are missing' in result.reasons[0]
    assert repo.load.call_count == 4  # Never cache the failure or skip a safety check.
    assert logger.warning.call_count == 2
    assert 'private SQL' not in str(logger.warning.call_args_list)


def test_pyarrow_runtime_and_all_pins_match_cloud():
    import pyarrow
    assert pyarrow.__version__ == '24.0.0'
    for name in ('requirements.txt', 'requirements-archive.txt', 'constraints.txt'):
        assert 'pyarrow==24.0.0' in (ROOT/name).read_text(encoding='utf-8')


@pytest.mark.parametrize('quote,code', [({}, 'MISSING'), ({'last_price': None}, 'NULL'),
    ({'last_price': 0}, 'ZERO'), ({'last_price': -1}, 'NEGATIVE'),
    ({'last_price': True}, 'INVALID_NUMBER'), ({'last_price': 'secret-value'}, 'INVALID_NUMBER'),
    ({'last_price': 'NaN'}, 'INVALID_NUMBER')])
def test_quote_price_fixed_codes_no_substitution_or_raw_output(quote, code):
    from market_context_sources import quote_price
    with pytest.raises(m.ContextError) as error:
        quote_price(quote)
    assert str(error.value) == 'LAST_PRICE_'+code


def test_quote_price_preserves_decimal():
    from market_context_sources import quote_price
    assert quote_price({'last_price': '83.125'}) == Decimal('83.125')


@pytest.mark.parametrize('error_type,expected', [
    ('UndefinedTable', 'NOT COMMISSIONED'), ('InsufficientPrivilege', 'access denied'),
    ('generic', 'monitor unavailable')])
def test_monitor_panel_explains_own_failure_without_raw_error(error_type, expected):
    from types import SimpleNamespace
    from unittest.mock import Mock
    import psycopg.errors
    repo, st = Mock(), Mock()
    exception = getattr(psycopg.errors, error_type, RuntimeError)
    repo.monitor_state.side_effect = exception('PRIVATE SQL CREDENTIAL')
    render, _ = app_function('render_derivative_monitor_panel', dict(st=st,
        DURABLE_REPOSITORY=SimpleNamespace(configured=True, connect=Mock()),
        DerivativeRepository=lambda *a: repo))
    render('test')
    assert expected in st.error.call_args.args[0]
    assert 'PRIVATE SQL CREDENTIAL' not in str(st.mock_calls)
    repo.positions.assert_not_called()
    if error_type == 'UndefinedTable':
        assert 'derivative_monitor_review_only.sql' in str(st.caption.call_args_list)


def test_monitor_unconfigured_never_queries_or_claims_empty_portfolio():
    from types import SimpleNamespace
    from unittest.mock import Mock
    st, factory = Mock(), Mock()
    render, _ = app_function('render_derivative_monitor_panel', dict(st=st,
        DURABLE_REPOSITORY=SimpleNamespace(configured=False), DerivativeRepository=factory))
    render('test')
    factory.assert_not_called()
    assert 'UNKNOWN' in st.error.call_args.args[0]
