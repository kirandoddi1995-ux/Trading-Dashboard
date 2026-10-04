import ast
import datetime as dt
import logging
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace

import pandas as pd
import pytest

import app_runtime as runtime
import nifty_session_calendar as calendar


ROOT = Path(__file__).resolve().parents[1]
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def functions(*names, **context):
    nodes = [node for node in ast.walk(ast.parse((ROOT / 'app.py').read_text(encoding='utf-8')))
             if isinstance(node, ast.FunctionDef) and node.name in names]
    for node in nodes:
        node.decorator_list = []
    scope = dict(datetime=dt, IST=IST, nse_calendar=calendar, runtime=runtime, pd=pd,
                 time=time, sqlite3=sqlite3, DEFAULT_DB_PATH='unused', LOGGER=logging.getLogger('history-test'),
                 OBSERVABILITY=SimpleNamespace(record=lambda *a, **kw: None))
    scope.update(context)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'app.py', 'exec'), scope)
    return scope


@pytest.mark.parametrize('now,expected', [
    ('2026-10-02T18:00:00+05:30', '2026-10-01'),
    ('2026-10-04T22:23:00+05:30', '2026-10-01'),
    ('2026-10-05T10:00:00+05:30', '2026-10-01'),
    ('2026-10-05T15:30:00+05:30', '2026-10-05'),
    ('2026-10-04T16:53:00+00:00', '2026-10-01'),
    ('2024-03-02T13:00:00+05:30', '2024-03-02'),
])
def test_expected_completed_nse_session(now, expected):
    fn = functions('_expected_latest_completed_session_date', '_previous_weekday')['_expected_latest_completed_session_date']
    assert fn(dt.datetime.fromisoformat(now), 'NSE_INDEX|India VIX') == dt.date.fromisoformat(expected)


def test_unknown_year_or_special_hours_never_guessed():
    fn = functions('_expected_latest_completed_session_date')['_expected_latest_completed_session_date']
    assert fn(dt.datetime(2027, 1, 4, 16, tzinfo=IST), 'NSE_EQ|TEST') is None
    assert fn(dt.datetime(2026, 11, 8, 23, tzinfo=IST), 'NSE_EQ|TEST') is None
    with pytest.raises(ValueError, match='STUDY_RANGE'):
        calendar.session(dt.date(2026, 10, 2))  # replay boundary unchanged


def test_nse_calendar_not_applied_to_other_exchanges():
    fn = functions('_expected_latest_completed_session_date', '_previous_weekday')['_expected_latest_completed_session_date']
    assert fn(dt.datetime(2026, 10, 2, 18, tzinfo=IST), 'MCX_FO|TEST') == dt.date(2026, 10, 2)


def test_widget_has_one_default_and_preserves_saved_value():
    from streamlit.testing.v1 import AppTest
    tree = ast.parse((ROOT / 'app.py').read_text(encoding='utf-8'))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and any(keyword.arg == 'key' and isinstance(keyword.value, ast.Constant)
                     and keyword.value.value == 'eq_price_filter' for keyword in node.keywords)]
    assert len(calls) == 1 and not any(keyword.arg == 'value' for keyword in calls[0].keywords)
    code = """import streamlit as st
if 'eq_price_filter' not in st.session_state:
    st.session_state.eq_price_filter = 50000.0
""" + ast.unparse(calls[0])
    app = AppTest.from_string(code).run()
    assert not app.exception and app.number_input[0].value == 50000
    assert not app.warning
    app.number_input[0].set_value(10000).run()
    assert not app.exception and app.number_input[0].value == 10000
    assert not app.warning


@pytest.mark.parametrize('now,fetches', [('2026-10-04T22:23:00+05:30', 0),
                                      ('2026-10-05T16:00:00+05:30', 1)])
def test_today_sync_does_not_hide_after_close_refresh(now, fetches):
    observed = dt.datetime.fromisoformat(now)
    class Clock(dt.datetime):
        @classmethod
        def now(cls, zone=None):
            return observed.astimezone(zone) if zone else observed.replace(tzinfo=None)
    frame = pd.DataFrame({'Close': [100] * 75}, index=pd.date_range('2026-06-19', '2026-10-01', periods=75))
    calls = []
    scope = functions('_expected_latest_completed_session_date', '_previous_weekday', 'get_cached_history',
        datetime=SimpleNamespace(datetime=Clock, timedelta=dt.timedelta, time=dt.time),
        _read_cached_history=lambda *a, **kw: frame,
        _cache_last_sync_date=lambda *a, **kw: observed.date().isoformat(),
        _serialize_history=lambda *a, **kw: 0)
    scope['get_cached_history']('NSE_EQ|TEST', 'SYNTHETIC', days=120,
        fetch_fn=lambda *a, **kw: calls.append(kw) or frame)
    assert len(calls) == fetches


@pytest.mark.parametrize('now,last,marked', [
    ('2026-10-04T22:23:00+05:30', '2026-10-01', True),
    ('2026-10-04T22:23:00+05:30', '2026-09-30', False),
    ('2027-01-04T16:00:00+05:30', '2027-01-04', False),
])
def test_persisted_freshness_marker_requires_reviewed_calendar_and_real_last_bar(tmp_path, now, last, marked):
    observed = dt.datetime.fromisoformat(now)
    class Clock(dt.datetime):
        @classmethod
        def now(cls, zone=None):
            return observed.astimezone(zone) if zone else observed.replace(tzinfo=None)
    path = tmp_path / 'cache.sqlite3'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE candles(instrument_key TEXT, dt TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, oi REAL, PRIMARY KEY(instrument_key,dt))')
        conn.execute('CREATE TABLE sync_meta(instrument_key TEXT PRIMARY KEY, last_sync_date TEXT)')
    scope = functions('_expected_latest_completed_session_date', '_previous_weekday', '_serialize_history',
        datetime=SimpleNamespace(datetime=Clock, timedelta=dt.timedelta, time=dt.time),
        _cache_connect=lambda name: sqlite3.connect(name))
    frame = pd.DataFrame({'Close': [100]}, index=pd.DatetimeIndex([last]))
    assert scope['_serialize_history']('NSE_EQ|TEST', frame, path) == 1
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM candles').fetchone()[0] == 1
        result = conn.execute('SELECT last_sync_date FROM sync_meta').fetchone()
    assert bool(result) is marked
    if marked:
        assert result[0] == observed.date().isoformat()
