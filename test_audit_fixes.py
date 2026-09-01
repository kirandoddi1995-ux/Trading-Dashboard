"""Regression coverage for concrete defects found in the live-market audit."""
import ast
from contextlib import nullcontext
import datetime
import logging
import math
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import urllib.parse

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest
from streamlit.testing.v1 import AppTest

import app_runtime as runtime
import technical_indicators as ta
from reliable_charts import chart_png
from scan_jobs import ScanBusy, ScanJobs
from risk_engine import RiskEngine

SOURCE = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')


def app_functions(*names, **context):
    tree = ast.parse(SOURCE)
    nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    for node in nodes:
        node.decorator_list = []
    namespace = dict(pd=pd, np=np, math=math, time=time, datetime=datetime,
                     threading=threading, runtime=runtime, ta=ta, LOGGER=logging.getLogger('tests'))
    namespace.update(context)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'app.py', 'exec'), namespace)
    return namespace


def test_settings_survive_real_widget_cleanup():
    app = AppTest.from_string('''
import streamlit as st
import app_runtime as runtime
runtime.retain_preferences(st.session_state)
section = st.radio('Section', ['Settings', 'Research'], key='section')
if section == 'Settings':
    st.number_input('Capital', value=1000000.0, key='sb_investment_capital')
    st.slider('Risk', .5, 10., 2., key='sb_max_risk_pct')
    st.button('Add Position', key='sb_add_position')
st.write(st.session_state.get('sb_investment_capital'))
''').run()
    app.number_input[0].set_value(500000.).run()
    app.slider[0].set_value(1.5).run()
    app.radio[0].set_value('Research').run()
    app.run()  # a further rerun with no settings widgets
    app.radio[0].set_value('Settings').run()
    assert not app.exception
    assert app.number_input[0].value == 500000.
    assert app.slider[0].value == 1.5
    app.button[0].click().run()
    assert not app.exception


def test_anonymous_owners_are_stable_and_isolated():
    one, two = {}, {}
    first = runtime.session_identity(one)
    assert runtime.session_identity(one) == first
    assert runtime.session_identity(two) != first
    assert len(first) == 64


@pytest.mark.parametrize('quote,expected', [
    ({'last_price': 100, '_ts': 999}, True),
    ({'last_price': 100, '_ts': 1}, False),
    ({'last_price': 100, '_ts': 1001}, False),
    ({'last_price': float('nan'), '_ts': 999}, False),
    ({'last_price': 100}, False),
])
def test_quote_receipt_freshness(quote, expected):
    assert runtime.quote_is_fresh(quote, now=1000) is expected


def test_option_direction_blocks_green_session_mild_pe_conflict():
    result = runtime.score_option_direction(
        price=100.30, previous_close=100.0, ema20=102.0, rsi=44.0,
        macd_hist=-1.0, pcr=.70, oi_change_bias="Bearish",
        trend_15m="Bearish", trend_1h="Bullish", market_open=True,
    )
    assert result["bias"] == "Neutral"
    assert result["day_change_pct"] > 0


def test_option_direction_blocks_red_session_mild_ce_conflict():
    result = runtime.score_option_direction(
        price=99.70, previous_close=100.0, ema20=98.0, rsi=56.0,
        macd_hist=1.0, pcr=1.20, oi_change_bias="Bullish",
        trend_15m="Bullish", trend_1h="Bearish", market_open=True,
    )
    assert result["bias"] == "Neutral"
    assert result["day_change_pct"] < 0


def test_option_direction_never_allows_one_factor_or_missing_intraday():
    one_factor = runtime.score_option_direction(
        price=100.0, previous_close=100.0, ema20=90.0,
        market_open=False, minimum_score=5,
    )
    assert one_factor["bias"] == "Neutral"
    assert one_factor["threshold"] == 25.0

    missing_intraday = runtime.score_option_direction(
        price=105.0, previous_close=100.0, ema20=95.0, vwap=100.0,
        rsi=70.0, macd_hist=2.0, pcr=1.2, oi_change_bias="Bullish",
        trend_15m=None, trend_1h="Bullish", market_open=True,
    )
    assert missing_intraday["bias"] == "Neutral"
    assert "15-minute" in missing_intraday["decision_reason"]


def test_option_direction_allows_aligned_signal_and_strong_confirmed_reversal():
    aligned = runtime.score_option_direction(
        price=101.0, previous_close=100.0, ema20=99.0, vwap=100.0,
        rsi=60.0, macd_hist=1.0, pcr=1.2, oi_change_bias="Bullish",
        trend_15m="Bullish", trend_1h="Bullish", market_open=True,
    )
    assert aligned["bias"] == "Bullish"

    reversal = runtime.score_option_direction(
        price=100.30, previous_close=100.0, ema20=103.0, vwap=102.0,
        rsi=35.0, macd_hist=-2.0, pcr=.65, oi_change_bias="Bearish",
        trend_15m="Bearish", trend_1h="Bearish", volume_confirmed=True,
        market_open=True,
    )
    assert reversal["bias"] == "Bearish"


def test_near_atm_oi_change_uses_previous_oi_not_total_oi():
    chain = []
    for strike in (90, 95, 100, 105, 110):
        chain.append({
            "strike_price": strike,
            "call_options": {"market_data": {"oi": 2000, "prev_oi": 1000}},
            "put_options": {"market_data": {"oi": 10000, "prev_oi": 9900}},
        })
    result = runtime.option_oi_change_bias(chain, 100, strikes_each_side=2)
    # Total put OI is much larger, but fresh call additions dominate.
    assert result["bias"] == "Bearish"
    assert result["call_add"] > result["put_add"]


def test_current_intraday_route_is_merged_with_prior_history():
    calls = []

    def request(method, url, **kwargs):
        calls.append(url)
        return SimpleNamespace(status_code=200, text="", json=lambda: {"data": {"candles": []}})

    fn = app_functions(
        "fetch_upstox_intraday_series",
        IST=datetime.timezone(datetime.timedelta(hours=5, minutes=30)),
        urllib=SimpleNamespace(parse=urllib.parse),
        get_robust_session=lambda **kwargs: nullcontext(SimpleNamespace()),
        upstox_request=request,
        _history_to_dataframe=lambda candles: pd.DataFrame(),
    )["fetch_upstox_intraday_series"]
    fn("NSE_INDEX|SENSEX", "test-only", "minutes", 15, days_back=10)
    assert len(calls) == 2
    assert "/v3/historical-candle/intraday/NSE_INDEX%7CSENSEX/minutes/15" in calls[1]


def test_mild_bias_is_not_exempt_from_multitimeframe_confirmation():
    marker_15m, marker_1h = object(), object()
    fn = app_functions(
        "get_multi_timeframe_confirmation",
        fetch_upstox_intraday_series=lambda *args, **kwargs: marker_15m if args[2] == "minutes" else marker_1h,
        get_timeframe_trend_label=lambda frame: "Bearish",
    )["get_multi_timeframe_confirmation"]
    status, detail = fn("K", "token", "Mildly Bearish")
    assert status == "Aligned Bearish"
    assert detail["Daily"] == "Mildly Bearish"


def test_retry_after_not_shortened():
    assert runtime.retry_delay('120') == 120
    assert runtime.retry_delay('Thu, 01 Jan 1970 00:02:00 GMT', now=0) == 120
    assert runtime.retry_delay('nonsense') == 1


def test_counts_exclude_bad_data_and_use_actual_display_count():
    counts = runtime.scan_counts([{}]*92, {'Trend': 100, 'Data': 58},
                                 {'futures_submitted': 250, 'completed': 250}, 10)
    assert counts['valid_data'] == 192
    assert counts['data_failures'] == 58
    assert counts['displayed'] == 10
    assert counts['passed'] == 92
    assert runtime.scan_counts([], {'Error': 1, 'Timeout': 2},
                               {'worker_exceptions': 1, 'completed': 1})['data_failures'] == 3


def test_wide_stop_and_low_score_cannot_be_buy():
    assert runtime.equity_action(77, 111.31, 66.31, 174.31, 5, 15)[0] == 'Watch'
    assert runtime.equity_action(67, 100, 95, 108, 3, 15)[0] == 'Watch'
    assert runtime.equity_action(75, 100, 95, 108, 3, 15)[0] == 'Buy'
    assert runtime.equity_action(75, 100, 105, 108, 3, 15)[0] == 'Unavailable'


@pytest.mark.parametrize('bars,stop,target,reason,net', [
    ([(100, 100.2, 99.8, 100.1)], 99., 100.1, 'TARGET', -.2),
    ([(100, 100.1, 99.8, 100.1)], 99., 101., 'TIME', -.2),
    ([(100, 101., 99., 100.)], 99., 101., 'BOTH_STOP', -1.3),
    ([(95., 100., 94., 99.)], 99., 101., 'GAP_STOP', -5.3),
])
def test_costs_every_exit_and_conservative_barriers(bars, stop, target, reason, net):
    result = runtime.trade_outcome(bars, 100., stop, target, .3)
    assert result['reason'] == reason
    assert result['net_return_pct'] == pytest.approx(net)
    assert result['win'] == 0


def test_probability_does_not_count_gross_only_wins():
    ctx = app_functions('compute_historical_setup_probability')
    ctx['derive_long_trade_levels'] = lambda d, p, a, h: (p*.99, p*1.001, .1, {})
    idx = pd.bdate_range('2020-01-01', periods=700)
    price = np.linspace(100., 110., len(idx))
    frame = pd.DataFrame({'Open': price, 'High': price*1.002, 'Low': price*.999, 'Close': price}, index=idx)
    result = ctx['compute_historical_setup_probability'](frame, horizon_days=5)
    assert result['samples'] >= 20
    assert result['wins'] == 0


def test_diversification_does_not_relax_limits():
    select = app_functions('select_diversified_top_n')['select_diversified_top_n']
    returns = pd.Series(np.random.default_rng(2).normal(size=120))
    signals = [dict(Ticker=f'T{i}', score=90-i, _returns=returns,
                    _sector='Unclassified', _risk_amt=1) for i in range(10)]
    assert len(select(signals)) == 1  # all perfectly correlated
    for i, signal in enumerate(signals):
        signal['_returns'] = pd.Series(np.random.default_rng(i).normal(size=120))
    assert len(select(signals)) <= 3  # common unknown-sector bucket cap


def wait_complete(jobs, owner='a', signature='quick', seconds=3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        snapshot = jobs.snapshot(owner, signature)
        if snapshot and snapshot['complete']:
            return snapshot
        time.sleep(.01)
    raise AssertionError('Job did not finish')


def test_job_survives_new_observers_and_isolates_sessions():
    jobs = ScanJobs()
    release = threading.Event()
    def work(ticker):
        release.wait(2)
        return {'Ticker': ticker}, None
    jobs.start('a', 'quick', ['X','Y'], work, timeout=2)
    assert jobs.snapshot('b', 'quick') is None
    assert jobs.snapshot('a', 'full') is None
    with pytest.raises(ScanBusy):
        jobs.start('a', 'full', [], work)
    release.set()
    result = wait_complete(jobs)
    assert len(result['signals']) == 2
    assert result['processed'] == 2
    result['signals'].clear()
    assert len(jobs.snapshot('a', 'quick')['signals']) == 2


def test_deadline_releases_ui_but_keeps_guard_until_workers_drain():
    jobs, release = ScanJobs(), threading.Event()
    def slow(_):
        release.wait(2)
        return {'Ticker':'LATE'}, None
    jobs.start('a', 'quick', ['X'], slow, timeout=.03)
    result = wait_complete(jobs)
    assert result['timeouts'] == 1 and result['draining']
    assert not result['signals']
    with pytest.raises(ScanBusy):
        jobs.start('b', 'full', [], slow)
    release.set()
    deadline = time.monotonic()+2
    while jobs.snapshot('a','quick')['draining'] and time.monotonic()<deadline:
        time.sleep(.01)
    assert not jobs.snapshot('a','quick')['signals']
    jobs.start('b', 'full', [], slow)
    assert wait_complete(jobs,'b','full')['complete']


def test_job_errors_and_examples_are_per_category():
    jobs = ScanJobs()
    def work(i):
        if i == 49:
            raise RuntimeError('private response must not be printed')
        return None, {'category': 'Trend' if i<40 else 'Data', 'reason': 'test'}
    jobs.start('a','quick',range(50),work)
    result = wait_complete(jobs)
    assert result['rejections'] == {'Trend':40,'Data':9,'Error':1}
    assert {x['Category'] for x in result['examples']} == {'Trend','Data','Error'}
    assert len(result['issues']) == 50
    assert 'private response' not in str(result)


@pytest.mark.parametrize('kind', ['nav', 'commodity', 'technical'])
def test_chart_renders_without_streamlit_plotly_javascript(kind):
    dates = pd.date_range('2026-01-01', periods=60)
    fig = go.Figure()
    if kind != 'nav':
        fig.add_trace(go.Candlestick(x=dates,open=[100]*60,high=[110]*60,low=[90]*60,close=[105]*60))
    fig.add_trace(go.Scatter(x=dates,y=np.arange(60)+100,line=dict(color='#ff9800'),name='Value'))
    if kind == 'technical':
        fig.add_hline(y=110,line_color='#4caf50')
    data = chart_png(fig)
    assert data.startswith(b'\x89PNG\r\n\x1a\n')
    assert len(data) > 5000


def test_exchange_status_requires_bearer_and_uppercase_exchange():
    calls = []
    def request(*args, **kwargs):
        calls.append((args,kwargs))
        return SimpleNamespace(raise_for_status=lambda:None,
                               json=lambda:{'data':{'exchange':'NSE','status':'NORMAL_OPEN'}})
    fn=app_functions('fetch_exchange_market_status',upstox_request=request)['fetch_exchange_market_status']
    result=fn('nse','test-only-token')
    assert result['status']=='NORMAL_OPEN'
    assert calls[0][0][1].endswith('/NSE')
    assert calls[0][1]['headers']['Authorization']=='Bearer test-only-token'


def test_stale_quotes_trigger_rest_in_actual_quote_function():
    calls=[]
    old={'K':{'last_price':100.,'_ts':1}}
    buffer=SimpleNamespace(ensure=lambda keys:None, snapshot=lambda keys:old)
    def rest(keys,token):
        calls.append(keys)
        return {'K':{'last_price':105.,'_ts':time.time()}}
    fn=app_functions('get_live_market_quotes',UPSTOX_SDK_AVAILABLE=True,MARKET_OPEN=True,
                     get_market_data_buffer=lambda token:buffer,_rest_market_quotes=rest)['get_live_market_quotes']
    assert fn(['K'],'test-only')['K']['last_price']==105.
    assert calls==[['K']]


def test_option_costs_depth_and_capital_use_one_execution_model():
    ctx=app_functions('build_option_recommendation',lot_size=65,dte=1,
                      iv_percentile_proxy=20,IST=datetime.timezone(datetime.timedelta(hours=5,minutes=30)))
    ctx['risk_engine']=RiskEngine(investment_capital=1000000,max_risk_pct=2,max_position_pct=20)
    row={'Strike':'24000','Put LTP':'38.80','_put_bid':38.75,'_put_ask':38.85,
         '_put_ask_qty':100000,'_put_bid_qty':100000,'_put_volume':1000000}
    result=ctx['build_option_recommendation']('Bearish',best_row=row)
    assert result is not None
    cost=result['premium']*.007
    net_risk=(result['premium']-result['stop_premium']+cost)*result['lots']*65
    assert result['total_risk']==pytest.approx(round(net_risk,2))
    assert result['total_risk']<=20000 and result['required_capital']<=200000
    rr=(result['target_premium']-result['premium']-cost)/(result['premium']-result['stop_premium']+cost)
    assert result['reward_risk']==round(rr,2)
    row['_put_ask_qty']=65
    assert ctx['build_option_recommendation']('Bearish',best_row=row)['lots']==1
    row['_put_bid']=40
    assert ctx['build_option_recommendation']('Bearish',best_row=row) is None


def test_revalidation_does_not_rewrite_original_signal():
    previous=dict(signal_id='old',status='NEW',strike=100,direction='CE',entry=10,target=14,stop=8)
    calls=[]
    fn=app_functions('evaluate_signal_lifecycle',DEFAULT_DB_PATH='unused',ACTIVE_LIKE_STATUSES={'NEW','REVALIDATED'},
        get_active_signal=lambda *args:dict(previous),
        update_signal_status=lambda *args,**kwargs:calls.append((args,kwargs)))['evaluate_signal_lifecycle']
    status,result=fn('NIFTY','2026-09-01','2026-08-31',1,
                     {'strike':100,'side':'CE','premium':12,'target_premium':16,'stop_premium':11},
                     lambda *args:12,'owner')
    assert status=='REVALIDATED' and result['entry']==10 and result['target']==14
    assert calls[0][1]=={'dte':1}


def test_log_redaction_includes_provider_urls():
    record=logging.LogRecord('test',logging.ERROR,'',1,
         'failed %s Bearer abc https://provider.test/path?token=xyz',('secret-example',),None)
    runtime.SecretRedactor(['secret-example']).filter(record)
    assert all(secret not in record.getMessage() for secret in ('secret-example','abc','xyz'))


def test_candles_allow_optional_oi_reject_bad_prices_and_deduplicate():
    fn=app_functions('_history_to_dataframe',normalize_market_timestamp_series=lambda s:s)['_history_to_dataframe']
    candles=[['2026-08-28',100,110,90,105,10],
             ['2026-08-28',100,110,90,106,20,5],
             ['2026-08-27',100,95,90,105,10,5],
             ['2026-08-26',100,110,90,float('inf'),10,5]]
    frame=fn(candles)
    assert len(frame)==1
    assert frame.iloc[0]['Volume']==20 and frame.iloc[0]['Close']==106


def test_csv_export_cannot_activate_external_formula_strings():
    exported=runtime.csv_bytes(pd.DataFrame({'label':['=1+1',' @formula','normal'],'return':[-2.,1.,3.]})).decode('utf-8-sig')
    assert "'=1+1" in exported and "' @formula" in exported
    assert 'normal,3.0' in exported and ',-2.0' in exported


def test_scan_quotes_count_instruments_not_provider_aliases():
    fn=app_functions('get_live_scan_market_data',
        get_live_market_quotes=lambda keys,token:{'K':{'last_price':100.,'ohlc':{}}},
        _rest_ohlc_v3=lambda *args,**kwargs:{'K':{'last_price':100.,'ohlc':{'high':102.,'low':99.,'close':100.},'volume':4},
                                          'EXCHANGE:ALIAS':{'last_price':100.}})['get_live_scan_market_data']
    quotes=fn(['K'],'test')
    assert list(quotes)==['K']
    assert quotes['K']['ohlc']['high']==102.


@pytest.mark.parametrize('age,market_open,has_price', [(1, True, True), (120, True, False), (1, False, False)])
def test_header_never_presents_stale_ticks_as_live(age, market_open, has_price):
    shown, captions = [], []
    ui = SimpleNamespace(columns=lambda count:[nullcontext() for _ in range(count)],
                         markdown=shown.append, caption=captions.append)
    buffer = SimpleNamespace(ensure=lambda keys:None, snapshot=lambda keys:{
        'NSE_INDEX|Nifty 50':{'last_price':100., '_ts':time.time()-age, 'ohlc':{'close':99.}}})
    fn = app_functions('_render_ticker_tape', st=ui, selected_indices=['NIFTY 50'],
                        access_token='test-only', UPSTOX_SDK_AVAILABLE=True, MARKET_OPEN=market_open,
                        get_market_data_buffer=lambda token:buffer)['_render_ticker_tape']
    fn()
    assert bool(shown) is has_price
    unavailable = any('unavailable' in str(caption).lower() for caption in captions)
    assert unavailable is not has_price
    if unavailable:
        unavailable_caption = next(c for c in captions if 'unavailable' in c.lower())
        assert 'waiting' not in unavailable_caption
