"""Tests for equity_stage2_collector (the scheduled collector's shadow Stage-2).

The main tests are differential. The same synthetic Upstox candles go through:
  * app.py's REAL history path - `_fetch_upstox_history_impl`, `get_cached_history`,
    `_serialize_history`, `_read_cached_history` on a cold SQLite cache, exec'd from
    app.py's source - and app.py's REAL `evaluate_stock` (the Phase 1b test runner);
  * the collector's adapter (`fetch_daily_candles`, `cold_cache_history`) and the
    parity-tested copy `evaluate_stage2`.
They must give the same frame and the same decision (reject category/reason, or the
same score/levels/features), with the same captured inputs.

Also pinned: the settings are app.py's defaults; the SQL is app.py's; history guards;
capture compaction round-trips; the code hash covers the import closure; and the
collector wiring (off = no change at all, on = complete shortlist, batch before rows,
never "Buy", failures contained, lease fencing). No network, no database, no
credentials, synthetic prices only.
"""
from __future__ import annotations

import ast
import contextlib
import datetime as dt
import hashlib
import itertools
import json
import logging
import re
import sqlite3
import time
import types
import urllib.parse
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import app_runtime
import equity_stage2_collector as s2
import scheduled_collector as collector
import test_equity_stage2_decision as decision_tests
from deployment_canary import run_canaries
from release_verification import release_members
from risk_engine import RiskEngine
from test_prospective_collection import MemoryRepository
from test_prospective_collection import quote as stage1_quote

ROOT = Path(__file__).resolve().parents[1]
APP_TREE = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
UTC = dt.timezone.utc
TICKER = decision_tests.TICKER
# EquityCapture inputs derived from datetime.now(): the app and collector runs in one
# test are seconds apart, so these are compared with a tolerance instead of exactly.
CLOCK_INPUTS = {"elapsed_fraction", "timing"}
# One evaluation instant for both sides' cache window (app.py: pd.Timestamp.now()).
# Its 1200-day cutoff, 2023-07-31, is a Monday, so an off-by-one day drops a bar.
FIXED_NOW = dt.datetime(2026, 11, 12, 10, 0, tzinfo=s2.IST)
FIXED_NAIVE = pd.Timestamp(FIXED_NOW.replace(tzinfo=None))
FIXED_CUTOFF = pd.Timestamp("2023-07-31")
APP_HISTORY_FUNCTIONS = (
    "_cache_connect", "_serialize_history", "_read_cached_history", "_cache_last_sync_date",
    "get_cached_history", "normalize_market_timestamp_series", "_history_to_dataframe",
    "_fetch_upstox_history_impl",
)


# ------------------------------------------------------------ synthetic data ---

def _last_bar() -> pd.Timestamp:
    """Fixed last bar date (weekly buckets, so outcomes, do not move with the
    calendar), or the last completed weekday if the clock is earlier than that."""
    yesterday = pd.Timestamp(dt.datetime.now(s2.IST).date()) - pd.offsets.BDay(1)
    return min(pd.Timestamp("2026-11-06"), yesterday)


def _frame(n=900, drift=0.0025, noise=0.004, seed=7, tail_days=0, tail_drift=0.0,
           start_price=100.0):
    """Valid daily OHLCV ending yesterday (High/Low bracket Open/Close)."""
    rng = np.random.default_rng(seed)
    returns = drift + rng.normal(0, noise, size=n)
    if tail_days:
        returns[-tail_days:] = tail_drift + rng.normal(0, noise, size=tail_days)
    close = start_price * np.cumprod(1 + returns)
    open_ = close * (1 + rng.normal(0, 0.002, size=n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, size=n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, size=n)))
    return pd.DataFrame({
        "Open": open_, "High": high, "Low": low, "Close": close,
        "Volume": rng.integers(500_000, 1_500_000, size=n),
    }, index=pd.bdate_range(end=_last_bar(), periods=n))


def _phase1b_frame(**kwargs):
    """A Phase 1b test history (its generator), moved to end at `_last_bar()`."""
    frame = decision_tests._ohlcv(**kwargs)
    frame.index = pd.bdate_range(end=_last_bar(), periods=len(frame))
    return frame


def _candles(frame, *, oi=True):
    """Upstox V3 candle rows, newest first, prices to the paisa."""
    rows = []
    for stamp, row in frame.iterrows():
        candle = [stamp.strftime("%Y-%m-%dT00:00:00+05:30"), round(float(row.Open), 2),
                  round(float(row.High) + 0.01, 2), round(float(row.Low) - 0.01, 2),
                  round(float(row.Close), 2), int(row.Volume)]
        rows.append(candle + [0] if oi else candle)
    return rows[::-1]


NIFTY_CANDLES = _candles(_frame(n=300, drift=0.0006, noise=0.008, seed=1, start_price=18000.0))
STOCKS = {
    "buy_signal": _candles(_phase1b_frame(drift=0.004, noise=0.008, tail_days=40, tail_drift=0.004,
                                          tail_noise=0.002, range_scale=3.0, seed=395)),
    "watch_signal": _candles(_frame(n=600, drift=0.004, noise=0.012, seed=3, tail_days=20,
                                    tail_drift=0.006)),
    "uptrend": _candles(_frame()),
    "uptrend_b": _candles(_frame(seed=13, drift=0.003)),
    "downtrend": _candles(_frame(drift=-0.002, seed=3)),
    "late_breakdown": _candles(_frame(tail_days=30, tail_drift=-0.006, seed=11)),
    "noisy_flat": _candles(_frame(drift=0.0002, noise=0.02, seed=5)),
    "short_history": _candles(_frame(n=150)),
    "no_candles": [],
    "expensive": _candles(_frame(start_price=40000.0, seed=17)),
}


def _messy(candles):
    """Rows app.py's parser must drop or keep: bad prices, short rows, duplicates, NULLs."""
    rows = [list(c) for c in candles]
    rows[5][2] = rows[5][3] - 1          # High below Low -> dropped
    rows[9][1] = 0                       # non-positive price -> dropped
    rows[12] = rows[12][:5]              # too short -> skipped
    rows[20][5] = None                   # missing volume -> kept
    rows[30][4] = None                   # missing close -> dropped
    return rows + [list(rows[40])]       # duplicate date -> last kept


class Response:
    """Minimal requests.Response stand-in."""

    def __init__(self, status_code, payload):
        """Store a status and JSON payload."""
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)[:200]

    def json(self):
        """Return the JSON payload."""
        return self._payload


class CandleClient:
    """Fake Upstox client: serves candles per instrument key, records each URL."""

    def __init__(self, by_key, *, status=None):
        """`by_key`: key -> candle rows or an int HTTP status; `status`: override all."""
        self.by_key = dict(by_key)
        self.status = status
        self.calls = []

    def get(self, url, **kwargs):
        """Return the candles for the key in a historical-candle URL."""
        self.calls.append((url, kwargs))
        if self.status is not None:
            return Response(self.status, {})
        for key, value in self.by_key.items():
            if f"/historical-candle/{urllib.parse.quote(key, safe='')}/" in url:
                if isinstance(value, int):
                    return Response(value, {"status": "error"})
                return Response(200, {"status": "success", "data": {"candles": value}})
        return Response(404, {"status": "error"})


# -------------------------------------------------------- app.py's real code ---

def _app_cache_ddl():
    """app.py's CREATE statements for the candle cache tables (from its source)."""
    fn = next(n for n in APP_TREE.body if isinstance(n, ast.FunctionDef)
              and n.name == "_ensure_cache_schema")
    statements = [node.value for node in ast.walk(fn)
                  if isinstance(node, ast.Constant) and isinstance(node.value, str)
                  and re.search(r"CREATE (TABLE|INDEX) IF NOT EXISTS (candles|sync_meta|idx_candles)",
                                node.value)]
    assert len(statements) == 3
    return statements


def _app_history(tmp_path, *, requests_seen=None, response=None):
    """Exec app.py's history functions against a fresh (cold) SQLite cache file."""
    db_path = tmp_path / "market_cache.sqlite3"
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        for statement in _app_cache_ddl():
            conn.execute(statement)
        conn.commit()

    def upstox_request(method, url, **kwargs):
        """Record the app's request; answer with the prepared response."""
        if requests_seen is not None:
            requests_seen.append((method, url, kwargs))
        return response

    ns = {
        "np": np, "pd": pd, "sqlite3": sqlite3, "time": time, "datetime": dt, "urllib": urllib,
        "runtime": app_runtime, "LOGGER": logging.getLogger("god_mode_quant"), "IST": s2.IST,
        "DEFAULT_DB_PATH": str(db_path),
        "OBSERVABILITY": types.SimpleNamespace(record=lambda *a, **k: None),
        "HISTORY_FRESHNESS": types.SimpleNamespace(record=lambda *a, **k: None),
        "_expected_latest_completed_session_date": lambda now=None, instrument_key=None: None,
        "get_robust_session": lambda total_retries=3: contextlib.nullcontext(object()),
        "upstox_request": upstox_request,
    }
    nodes = [n for n in APP_TREE.body
             if isinstance(n, ast.FunctionDef) and n.name in APP_HISTORY_FUNCTIONS]
    assert sorted(n.name for n in nodes) == sorted(APP_HISTORY_FUNCTIONS)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), ns)
    return ns


def _app_cold_history(tmp_path, candles, key="NSE_EQ|SYNTH"):
    """app.py's get_cached_history(days=1200) on a cold cache fed by these candles."""
    ns = _app_history(tmp_path)
    asked = []

    def fetch_fn(instrument_key, token, days=400):
        """app.py's fetch_upstox_history signature; parse with app.py's parser."""
        asked.append(days)
        return ns["_history_to_dataframe"](candles)

    frame = ns["get_cached_history"](key, "token", days=s2.HISTORY_DAYS, fetch_fn=fetch_fn)
    assert asked == [s2.HISTORY_DAYS]  # cold cache -> one full-window request
    return frame


def _app_decision(monkeypatch, tmp_path, *, history, nifty, quote, key):
    """app.py's real evaluate_stock with the collector's settings and inputs, and the
    real TechnicalFeatureStore on an empty database (the app's cold feature cache)."""
    from feature_store import TechnicalFeatureStore
    settings = s2.APP_DEFAULT_SETTINGS
    store_path = str(tmp_path / "app_features.sqlite3")
    monkeypatch.setattr(decision_tests, "_FeatureStore",
                        lambda: TechnicalFeatureStore(lambda path: sqlite3.connect(path), store_path))
    monkeypatch.setattr(decision_tests, "_nifty", lambda: nifty)
    monkeypatch.setattr(decision_tests, "_risk_engine", lambda: RiskEngine(
        investment_capital=settings.investment_capital, max_risk_pct=settings.max_risk_pct,
        max_position_pct=settings.max_position_pct))
    scenario = decision_tests._scenario(
        history=history, quote=quote, market_open=True, max_price=settings.max_stock_price,
        weekly=settings.require_weekly_align, advanced=settings.use_advanced_signal_filters,
        key=key, days=settings.custom_days)
    return decision_tests._run_app(scenario)


def _quote_for(candles, shape="stage1"):
    """A live quote near the last close.

    "stage1": the collector's real Stage-1 snapshot shape (depth under market_depth,
    no market_data bid/ask) = app.py's Full NSE scan path (REST LTP + OHLC).
    "quick": app.py's Quick-scan websocket shape with market_data bid/ask.
    """
    last = candles[0][4] if candles else 100.0
    price = round(last * 1.004, 2)
    if shape == "stage1":
        return stage1_quote(price, last, 1500, FIXED_NOW.astimezone(UTC))
    return {"last_price": price,
            "market_data": {"bid_price": round(last * 1.003, 2), "ask_price": round(last * 1.005, 2)}}


@pytest.fixture
def frozen_pandas_now(monkeypatch):
    """Freeze pd.Timestamp.now() (app.py's cache window clock) at FIXED_NOW, IST wall time."""
    monkeypatch.setattr(pd.Timestamp, "now", classmethod(
        lambda cls, tz=None: FIXED_NAIVE if tz is None else FIXED_NOW.astimezone(tz)))
    return FIXED_NAIVE


# ------------------------------------------------------------- settings & SQL ---

def _app_assigned_default(attr):
    """Value of `st.session_state.<attr> = <constant>` in app.py."""
    values = [node.value.value for node in ast.walk(APP_TREE)
              if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
              and any(isinstance(t, ast.Attribute) and t.attr == attr for t in node.targets)]
    assert len(values) == 1, attr
    return values[0]


def _app_checkbox_default(key):
    """`value=` of the st.checkbox(..., key=<key>) in app.py."""
    values = []
    for node in ast.walk(APP_TREE):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "checkbox":
            kw = {k.arg: k.value for k in node.keywords}
            if isinstance(kw.get("key"), ast.Constant) and kw["key"].value == key:
                values.append(kw["value"].value)
    assert len(values) == 1, key
    return values[0]


def _app_session_get_default(name):
    """Default of `st.session_state.get(<name>, <default>)` in app.py."""
    values = [node.args[1].value for node in ast.walk(APP_TREE)
              if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "get"
              and len(node.args) == 2 and isinstance(node.args[0], ast.Constant)
              and node.args[0].value == name and isinstance(node.args[1], ast.Constant)]
    assert len(values) == 1, name
    return values[0]


def test_settings_are_app_widget_defaults():
    """Kiran chose the app's defaults; pin them to app.py so drift fails here."""
    s = s2.APP_DEFAULT_SETTINGS
    assert (s.custom_days, type(s.custom_days)) == (_app_assigned_default("eq_days_input"), int)
    assert s.max_stock_price == _app_assigned_default("eq_price_filter") == 50000.0
    assert s.require_weekly_align is _app_checkbox_default("eq_weekly_filter") is False
    assert s.use_advanced_signal_filters is _app_checkbox_default("eq_advanced_filters") is False
    assert s.investment_capital == _app_session_get_default("sb_investment_capital") == 1000000.0
    assert s.max_risk_pct == _app_session_get_default("sb_max_risk_pct") == 2.0
    assert s.max_position_pct == _app_session_get_default("sb_max_position_pct") == 20.0


def _sql_words(text):
    """SQL with whitespace collapsed (layout is not behaviour)."""
    return " ".join(text.split())


def _strings_in(function_name):
    """String constants (implicit concatenation joined) inside one app.py function."""
    fn = next(n for n in APP_TREE.body if isinstance(n, ast.FunctionDef) and n.name == function_name)
    return [n.value for n in ast.walk(fn) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def test_cache_sql_is_app_sql():
    """Same CREATE/INSERT/SELECT text as app.py's candle cache."""
    assert _sql_words(s2._CANDLE_SCHEMA) == _sql_words(_app_cache_ddl()[0])
    assert _sql_words(s2._CANDLE_INSERT) in [_sql_words(t) for t in _strings_in("_serialize_history")]
    assert _sql_words(s2._CANDLE_READ) in [_sql_words(t) for t in _strings_in("_read_cached_history")]


def test_request_sizes_match_app_calls():
    """1200 days (decision core's history call) and NIFTY 50 for 400 days (app.py)."""
    decision = ast.parse((ROOT / "equity_stage2_decision.py").read_text(encoding="utf-8"))
    days = [kw.value.value for node in ast.walk(decision) if isinstance(node, ast.Call)
            for kw in node.keywords if kw.arg == "days" and any(
                isinstance(a, ast.Name) and a.id == "get_cached_history" for a in node.args)]
    assert days == [s2.HISTORY_DAYS] == [1200]
    nifty = next(node for node in APP_TREE.body if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "nifty_hist_df" for t in node.targets))
    call = next(n for n in ast.walk(nifty) if isinstance(n, ast.Call)
                and getattr(n.func, "id", None) == "fetch_upstox_history")
    assert call.args[0].value == s2.NIFTY_KEY == collector.NIFTY_KEY
    assert {kw.arg: kw.value.value for kw in call.keywords} == {"days": s2.NIFTY_HISTORY_DAYS}


# ------------------------------------------------------------ history parity ---

@pytest.mark.parametrize("name, candles", [
    ("long_window_cut", STOCKS["uptrend"]),
    ("messy_rows", _messy(STOCKS["uptrend"])),
    ("six_field_rows", _candles(_frame(seed=21), oi=False)),
    ("short_history", STOCKS["short_history"]),
    ("no_candles", []),
])
def test_cold_cache_history_is_app_get_cached_history(tmp_path, frozen_pandas_now, name, candles):
    """Same frame, dtypes and index as app.py on a cold cache, row for row."""
    app_frame = _app_cold_history(tmp_path, candles)
    mine = s2.cold_cache_history("NSE_EQ|SYNTH", s2._history_to_dataframe(candles),
                                 s2.HISTORY_DAYS, now=FIXED_NAIVE)
    if app_frame.empty:
        assert mine.empty and list(mine.columns) == list(app_frame.columns)
        return
    pd.testing.assert_frame_equal(mine, app_frame, check_exact=True)
    assert s2.history_index_problem(mine) is None
    if name == "long_window_cut":
        # The cutoff day itself is kept, the day before is not (exact window).
        assert mine.index.min() == FIXED_CUTOFF and len(mine) < len(candles)
        assert FIXED_CUTOFF - pd.offsets.BDay(1) in s2._history_to_dataframe(candles).index


def test_fetch_request_and_parse_match_app(tmp_path):
    """Same Upstox URL and the same parsed frame as app.py's _fetch_upstox_history_impl."""
    key = "NSE_EQ|INE002A01018"
    seen = []
    payload = {"status": "success", "data": {"candles": _messy(STOCKS["uptrend"])}}
    ns = _app_history(tmp_path, requests_seen=seen, response=Response(200, payload))
    app_frame = ns["_fetch_upstox_history_impl"](key, "token", days=s2.HISTORY_DAYS)
    client = CandleClient({key: payload["data"]["candles"]})
    mine = s2.fetch_daily_candles(client, "token", key, s2.HISTORY_DAYS,
                                  today=dt.datetime.now(s2.IST).date())
    assert [url for _, url, _ in seen] == [url for url, _ in client.calls]
    assert seen[0][2]["headers"]["Authorization"] == client.calls[0][1]["headers"]["Authorization"]
    pd.testing.assert_frame_equal(mine, app_frame, check_exact=True)


@pytest.mark.parametrize("status, error", [(401, PermissionError), (403, PermissionError),
                                           (500, s2.HistoryUnavailable), (404, s2.HistoryUnavailable)])
def test_fetch_failure_raises_instead_of_an_empty_frame(status, error):
    """A failed request is not 'insufficient history': it must not become a reject."""
    with pytest.raises(error):
        s2.fetch_daily_candles(CandleClient({}, status=status), "t", "NSE_EQ|X", 1200,
                               today=dt.date(2026, 11, 10))


@pytest.mark.parametrize("payload", [
    {"status": "error", "errors": [{"errorCode": "UDAPI1015"}]},
    {"status": "success", "data": None},
    {"status": "success", "data": {"candle": []}},
    {"status": "success", "data": {"candles": "none"}},
    [["2026-11-06T00:00:00+05:30", 1, 2, 0.5, 1.5, 10, 0]],
])
def test_http_200_error_or_changed_schema_is_a_fetch_failure(payload):
    """app.py reads these as 'no candles' (a Data reject); here they are NOT_EVALUATED."""
    class Client:
        """Answers 200 with the given body."""

        def get(self, url, **kwargs):
            """Return the prepared body."""
            return Response(200, payload)

    with pytest.raises(s2.HistoryUnavailable):
        s2.fetch_daily_candles(Client(), "t", "NSE_EQ|X", 1200, today=dt.date(2026, 11, 10))
    empty = s2.fetch_daily_candles(CandleClient({"NSE_EQ|X": []}), "t", "NSE_EQ|X", 1200,
                                   today=dt.date(2026, 11, 10))
    assert empty.empty  # a well-formed empty answer stays the app's "no candles"


def test_compute_only_store_matches_the_real_store_on_an_empty_cache(tmp_path):
    """Same features and same mode label as feature_store.TechnicalFeatureStore when cold."""
    from feature_store import TechnicalFeatureStore, compute_feature_frame
    import technical_indicators as ta
    source = s2.cold_cache_history("NSE_EQ|K", s2._history_to_dataframe(STOCKS["buy_signal"]),
                                   1200, now=FIXED_NAIVE)
    compute = lambda frame: compute_feature_frame(frame, ta)  # noqa: E731
    real = TechnicalFeatureStore(lambda path: sqlite3.connect(path), str(tmp_path / "features.db"))
    real_frame, real_mode = real.enrich("NSE_EQ|K", source, compute)
    mine_frame, mine_mode = s2.ComputeOnlyFeatureStore().enrich("NSE_EQ|K", source, compute)
    assert mine_mode == real_mode == "full_rebuild"
    pd.testing.assert_frame_equal(mine_frame, real_frame, check_exact=True)


def test_history_index_guard():
    """Only a sorted, unique, naive DatetimeIndex reaches completed-bar logic."""
    good = s2.cold_cache_history("K", s2._history_to_dataframe(STOCKS["uptrend"]), 1200,
                                 now=pd.Timestamp.now())
    assert s2.history_index_problem(good) is None
    assert s2.history_index_problem(pd.DataFrame(columns=s2.COLUMNS)) is None
    assert "DatetimeIndex" in s2.history_index_problem(good.reset_index())
    assert "timezone" in s2.history_index_problem(good.tz_localize("Asia/Kolkata"))
    assert "duplicate" in s2.history_index_problem(pd.concat([good, good.iloc[[-1]]]))
    assert "order" in s2.history_index_problem(good.iloc[::-1])
    broken = good.copy()
    broken.index = broken.index.where(broken.index != broken.index[3], pd.NaT)
    assert "missing" in s2.history_index_problem(broken)


def test_dates_come_from_the_ist_calendar_even_when_utc_is_a_day_behind():
    """00:30 IST is still the previous UTC day: request end and cache window use IST.

    IST date 13 Nov -> cutoff Tue 1 Aug 2023; the UTC date would keep Mon 31 Jul too.
    """
    late = dt.datetime(2026, 11, 12, 19, 0, tzinfo=UTC)  # 2026-11-13 00:30 IST
    client = CandleClient({s2.NIFTY_KEY: NIFTY_CANDLES, "K": STOCKS["uptrend"]})
    out = s2.evaluate_shortlist(client, "t", [("A", "K")], quotes={}, market_open=False,
                                identity={}, sleep=lambda s: None, now=lambda: late)
    assert all("/days/1/2026-11-13/" in url for url, _ in client.calls)
    assert out["results"][0]["history"]["first"] == "2023-08-01T00:00:00"
    short = CandleClient({"K": []})
    s2.fetch_daily_candles(short, "t", "K", 10, today=dt.date(2026, 11, 13))
    assert short.calls[0][0].endswith("/days/1/2026-11-13/2026-10-14")  # app's 30-day minimum


def test_prefetched_history_serves_only_the_agreed_request():
    """The decision core may ask for exactly its one 1200-day history, nothing else."""
    frame = pd.DataFrame({"Close": [1.0]}, index=pd.DatetimeIndex(["2026-01-02"]))
    source = s2.prefetched_history("K", frame)
    served = source("K", "token", days=1200, fetch_fn=None)
    served.loc[:, "Close"] = 9.0
    assert frame["Close"].iloc[0] == 1.0  # a copy each time
    with pytest.raises(ValueError):
        source("OTHER", "token", days=1200)
    with pytest.raises(ValueError):
        source("K", "token", days=400)


# ----------------------------------------------------------- decision parity ---

def _collector_results(stocks, shape="stage1"):
    """Collector decisions for {name: candles}, one shortlist, evaluated at FIXED_NOW."""
    keys = {name: f"NSE_EQ|SYN{i:04d}" for i, name in enumerate(stocks)}
    client = CandleClient({s2.NIFTY_KEY: NIFTY_CANDLES} | {keys[n]: c for n, c in stocks.items()})
    quotes = {keys[n]: _quote_for(c, shape) for n, c in stocks.items()}
    evaluation = s2.evaluate_shortlist(
        client, "token", [(TICKER, keys[n]) for n in stocks], quotes=quotes, market_open=True,
        identity={"strategy_id": s2.STAGE2_SHADOW_VERSION}, sleep=lambda s: None,
        now=lambda: FIXED_NOW,
    )
    by_key = {r["instrument_key"]: r for r in evaluation["results"]}
    return {name: by_key[keys[name]] for name in stocks}, keys, quotes, evaluation


QUOTE_SHAPES = ("stage1", "quick")


@pytest.fixture(scope="module")
def collector_outcomes():
    """Collector results for every synthetic stock and quote shape (computed once)."""
    return {shape: _collector_results(STOCKS, shape) for shape in QUOTE_SHAPES}


@pytest.mark.parametrize("shape", QUOTE_SHAPES)
@pytest.mark.parametrize("name", sorted(STOCKS))
def test_collector_reaches_app_decision_from_the_same_candles(
        tmp_path, monkeypatch, frozen_pandas_now, collector_outcomes, name, shape):
    """Candles -> app.py (real history + real evaluate_stock) == candles -> collector."""
    results, keys, quotes, _ = collector_outcomes[shape]
    mine = results[name]
    assert mine["status"] == s2.EVALUATED and mine["governance_evaluated"] is False
    app_history = _app_cold_history(tmp_path, STOCKS[name], key=keys[name])
    app_nifty = _app_history(tmp_path)["_history_to_dataframe"](NIFTY_CANDLES)
    (app_row, app_reject), archived = _app_decision(
        monkeypatch, tmp_path, history=app_history, nifty=app_nifty, quote=quotes[keys[name]],
        key=keys[name])
    app_capture = archived[-1]["features"]["equity_capture"]
    mine_inputs, app_inputs = mine["equity_capture"]["inputs"], app_capture["inputs"]
    # Two inputs read the wall clock (the runs are seconds apart): compare them loosely.
    assert {k: v for k, v in mine_inputs.items() if k not in CLOCK_INPUTS} == \
        {k: v for k, v in app_inputs.items() if k not in CLOCK_INPUTS}
    assert set(mine_inputs) & CLOCK_INPUTS == set(app_inputs) & CLOCK_INPUTS
    if mine_inputs.get("elapsed_fraction") is not None or app_inputs.get("elapsed_fraction") is not None:
        assert abs(mine_inputs["elapsed_fraction"] - app_inputs["elapsed_fraction"]) < 0.01
    if "timing" in mine_inputs:
        drift = (dt.datetime.fromisoformat(app_inputs["timing"]["generated_at"])
                 - dt.datetime.fromisoformat(mine_inputs["timing"]["generated_at"]))
        assert dt.timedelta(0) <= drift <= dt.timedelta(minutes=5)
        assert mine_inputs["timing"]["mandatory_exit_at"][:10] <= app_inputs["timing"]["mandatory_exit_at"][:10]
    assert mine["equity_capture"]["costs"] == {k: v for k, v in app_capture["costs"].items() if k != "note"}
    assert mine["equity_capture"]["quote"] == {k: v for k, v in app_capture["quote"].items() if k != "raw"}
    if mine["equity_capture"]["costs"]["estimates"] is not None:
        assert mine["equity_capture"]["costs"]["measured_spread_available"] is (shape == "quick")
    if app_row is None:
        assert mine["stage2_pass"] is False
        assert (mine["category"], mine["reason"]) == (app_reject["category"], app_reject["reason"])
        assert archived[-1]["rejection_reason"] == s2._rejection_text(mine)
    else:
        assert mine["stage2_pass"] is True
        app_features = {k: v for k, v in archived[-1]["features"].items()
                        if k not in decision_tests.APP_ONLY_FEATURE_KEYS}
        assert mine["features"] == app_features
        assert (mine["signal_action"], mine["signal_action_reason"]) == \
            (app_row["Action"], app_row["_action_reason"])
    for column in ("score", "entry", "stop", "target"):
        assert mine[column] == archived[-1][column], column


@pytest.mark.parametrize("shape", QUOTE_SHAPES)
def test_differential_stocks_reach_passes_and_several_reject_kinds(collector_outcomes, shape):
    """The parity above is only meaningful if it covers passes and different rejects."""
    results = collector_outcomes[shape][0]
    actions = {n: r["signal_action"] for n, r in results.items() if r["stage2_pass"]}
    rejects = {r["category"] for r in results.values() if not r["stage2_pass"]}
    assert actions.get("buy_signal") == "Buy" and "Watch" in actions.values(), actions
    assert {"Data", "Trend", "Price Filter"} <= rejects, rejects
    assert results["no_candles"]["reason"].startswith("Insufficient price history")
    assert (shape == "quick") is ("Risk:Reward" in rejects)  # measured spread costs more


# --------------------------------------------------------- capture & hashing ---

def test_compact_capture_round_trips_to_the_app_snapshot(monkeypatch):
    """Ledger keeps a compact capture; expanding it gives back the app's snapshot."""
    seen = []
    original = s2.compact_capture
    monkeypatch.setattr(s2, "compact_capture", lambda snap: seen.append(snap) or original(snap))
    hashes = ("code", "config", "policy")
    identity = {"strategy_id": s2.STAGE2_SHADOW_VERSION, "scanner_strategy_id": s2.STAGE2_SHADOW_VERSION,
                "target_version": s2.TARGET_VERSION, "code_hash": hashes[0],
                "config_hash": hashes[1], "policy_hash": hashes[2]}
    results = s2.evaluate_shortlist(
        CandleClient({s2.NIFTY_KEY: NIFTY_CANDLES, "K1": STOCKS["uptrend"], "K2": STOCKS["downtrend"],
                      "K3": STOCKS["short_history"]}),
        "token", [("A", "K1"), ("B", "K2"), ("C", "K3")],
        quotes={"K1": _quote_for(STOCKS["uptrend"])}, market_open=True, identity=identity,
        sleep=lambda s: None)["results"]
    batch = {"strategy_id": s2.STAGE2_SHADOW_VERSION, "target_version": s2.TARGET_VERSION,
             "code_hash": hashes[0], "config_hash": hashes[1], "policy_hash": hashes[2]}
    assert len(seen) == 3
    for snapshot, result in zip(seen, results):
        expected = {k: v for k, v in snapshot.items() if k != "captured_at"}
        expected["quote"] = {k: v for k, v in snapshot["quote"].items() if k != "raw"}
        assert s2.expand_capture(result["equity_capture"], batch=batch) == expected
        times = sorted(snapshot["captured_at"].values())
        assert result["equity_capture"]["captured_at_range"] == [times[0], times[-1]]


def test_code_hash_covers_the_whole_import_closure():
    """Every local module that can change a shadow decision is in the code hash."""
    closure = set(release_members(ROOT, ["equity_stage2_collector.py"]))
    assert set(s2.STAGE2_CODE_FILES) == closure | {"scheduled_collector.py", "scanner_funnel.py"}
    code, config, policy = s2.stage2_hashes(stage1_top_n=150)
    assert s2.stage2_hashes(stage1_top_n=150) == (code, config, policy)
    assert s2.stage2_hashes(s2.ScanSettings(custom_days=20), stage1_top_n=150)[1] != config
    assert s2.stage2_hashes(stage1_top_n=100)[1] != config


def test_empty_shortlist_makes_no_requests_and_no_writes():
    """Nothing shortlisted -> nothing fetched, nothing written."""
    repo, client = Repo(), CandleClient({})
    out = s2.run_shadow_stage2(
        repo, client, "token", "run-1", shortlist=[], quotes={}, quote_evidence={}, universe={},
        now=NOW, observed_at=NOW, market_open=True, environ={s2.ENABLE_ENV: "1"})
    assert out == {"status": "SKIPPED", "reason": "Empty Stage-1 shortlist"}
    assert client.calls == [] and repo.ledger == [] and repo.scanner == []


def test_switch_and_budget_parsing():
    """Off unless explicitly on; a bad budget falls back to the default."""
    assert not s2.stage2_enabled({})
    assert not s2.stage2_enabled({s2.ENABLE_ENV: "0"})
    assert not s2.stage2_enabled({s2.ENABLE_ENV: "no"})
    assert all(s2.stage2_enabled({s2.ENABLE_ENV: v}) for v in ("1", "true", "YES", " on "))
    assert s2.budget_seconds({}) == s2.DEFAULT_BUDGET_SECONDS
    assert s2.budget_seconds({s2.BUDGET_ENV: "120"}) == 120.0
    assert s2.budget_seconds({s2.BUDGET_ENV: "x"}) == s2.DEFAULT_BUDGET_SECONDS
    assert s2.budget_seconds({s2.BUDGET_ENV: "-5"}) == s2.DEFAULT_BUDGET_SECONDS


# ------------------------------------------------------- shortlist behaviour ---

def _evaluate(by_key, shortlist, **kwargs):
    """evaluate_shortlist with a fake client and no pauses."""
    kwargs.setdefault("quotes", {})
    return s2.evaluate_shortlist(CandleClient(by_key), "token", shortlist, market_open=True,
                                 identity={}, sleep=lambda s: None, **kwargs)


def test_benchmark_failure_leaves_every_ticker_not_evaluated():
    """No NIFTY -> no decision at all (the app would always have it)."""
    for nifty in ({s2.NIFTY_KEY: 500}, {s2.NIFTY_KEY: []}, {}):
        out = _evaluate(nifty | {"K1": STOCKS["uptrend"]}, [("A", "K1"), ("B", "K2")])
        assert out["status"] == "FAILED" and out["error"] == "BENCHMARK_UNAVAILABLE"
        assert [r["status"] for r in out["results"]] == [s2.NOT_EVALUATED] * 2
        assert all(not r["stage2_pass"] for r in out["results"])


def test_auth_rejection_stops_and_marks_the_rest():
    """401/403 means the token is bad: stop calling, mark remaining tickers."""
    out = _evaluate({s2.NIFTY_KEY: NIFTY_CANDLES, "K1": STOCKS["downtrend"], "K2": 401,
                     "K3": STOCKS["uptrend"]}, [("A", "K1"), ("B", "K2"), ("C", "K3")])
    assert out["status"] == "FAILED" and out["error"] == "AUTH_REJECTED"
    assert [r["status"] for r in out["results"]] == [s2.EVALUATED, s2.NOT_EVALUATED, s2.NOT_EVALUATED]
    assert "Token" in out["results"][2]["reason"]


def test_per_ticker_data_problems_are_not_strategy_rejects(monkeypatch):
    """HTTP failure, a malformed quote or a bad index -> NOT_EVALUATED, run continues."""
    original = s2.cold_cache_history

    def bad_index(key, fresh, days, *, now):
        """Return an unsorted frame for K4 only."""
        frame = original(key, fresh, days, now=now)
        return frame.iloc[::-1] if key == "K4" else frame

    monkeypatch.setattr(s2, "cold_cache_history", bad_index)
    out = _evaluate({s2.NIFTY_KEY: NIFTY_CANDLES, "K1": 503, "K2": STOCKS["uptrend"],
                     "K3": STOCKS["downtrend"], "K4": STOCKS["uptrend"]},
                    [("A", "K1"), ("B", "K2"), ("C", "K3"), ("D", "K4")],
                    quotes={"K2": "not-a-quote"})
    by = {r["instrument_key"]: r for r in out["results"]}
    assert out["status"] == "PARTIAL"
    assert (out["history_failures"], out["candidate_errors"], out["invalid_history"]) == (1, 1, 1)
    assert by["K1"]["reason"] == "Price history unavailable (HistoryUnavailable)"
    assert by["K2"]["reason"] == "Quote snapshot is malformed"
    assert by["K3"]["status"] == s2.EVALUATED and by["K3"]["category"] == "Trend"
    assert by["K4"]["reason"] == "Price history rejected: history index is not in date order"


def test_time_budget_marks_the_unreached_tail():
    """Budget exhaustion keeps rank order and records the rest explicitly."""
    ticks = itertools.chain([0.0, 0.0], itertools.repeat(50.0))
    out = _evaluate({s2.NIFTY_KEY: NIFTY_CANDLES, "K1": STOCKS["downtrend"], "K2": STOCKS["uptrend"],
                     "K3": STOCKS["uptrend"]}, [("A", "K1"), ("B", "K2"), ("C", "K3")],
                    budget=10.0, clock=lambda: next(ticks))
    assert out["status"] == "PARTIAL" and out["error"] == "TIME_BUDGET_EXHAUSTED"
    assert [r["status"] for r in out["results"]] == [s2.EVALUATED, s2.NOT_EVALUATED, s2.NOT_EVALUATED]
    assert [r["instrument_key"] for r in out["results"]] == ["K1", "K2", "K3"]


def test_lease_loss_raises_before_any_more_work():
    """A fenced worker stops: LeaseLost propagates, no further requests."""
    client = CandleClient({s2.NIFTY_KEY: NIFTY_CANDLES, "K1": STOCKS["uptrend"]})
    calls = iter([None, RuntimeError("Collector lease was lost; fenced worker stopped")])

    def check():
        """First check passes, the next one reports a lost lease."""
        value = next(calls)
        if value:
            raise value

    with pytest.raises(s2.LeaseLost):
        s2.evaluate_shortlist(client, "token", [("A", "K1")], quotes={}, market_open=True,
                              identity={}, sleep=lambda s: None, check_lease=check)
    assert len(client.calls) == 1  # NIFTY only


# --------------------------------------------------------- collector wiring ---

NOW = dt.datetime(2026, 9, 7, 10, 0, tzinfo=collector.IST)


class Repo(MemoryRepository):
    """Upserts by observation_id like the real ON CONFLICT; logs write order;
    fixed universe time; optional shadow-batch failure."""

    def __init__(self, *, fail_stage2_batch=False):
        """Start empty."""
        super().__init__()
        self.fail_stage2_batch = fail_stage2_batch
        self.rows = {}
        self.ops = []

    def archive_universe(self, rows, snapshot_date):
        """Same as the base fake but with a fixed observation time."""
        result = super().archive_universe(rows, snapshot_date)
        return {**result, "observed_at": "2026-09-07T04:00:00+00:00"}

    def append_evidence_event(self, **event):
        """Optionally fail only the shadow Stage-2 batch."""
        self.ops.append(("ledger", event["aggregate_id"]))
        if self.fail_stage2_batch and event["aggregate_id"].endswith(s2.STAGE2_RUN_SUFFIX):
            raise RuntimeError("ledger unavailable")
        return super().append_evidence_event(**event)

    def upsert_scanner_observations(self, rows):
        """Upsert by id; shadow rows require their batch to be durable first."""
        rows = list(rows)
        versions = {r["strategy_version"] for r in rows}
        if s2.STAGE2_SHADOW_VERSION in versions:
            assert any(e["aggregate_id"] == "scan:run-1" + s2.STAGE2_RUN_SUFFIX for e in self.ledger)
        self.ops.append(("rows", tuple(sorted(versions))))
        for row in rows:
            self.rows[row["observation_id"]] = dict(row)
        self.scanner = list(self.rows.values())
        return len(rows)

    def store_order_book_marker(self):
        """Record where Stage-1's order-book step ran (licence-gated)."""
        self.ops.append(("order_books", None))


UNIVERSE = [{"instrument_key": f"NSE_EQ|{s}", "trading_symbol": s}
            for s in ("UPA", "UPB", "DOWN", "SHORT", "QUIET")]
CANDLES = {"NSE_EQ|UPA": STOCKS["buy_signal"], "NSE_EQ|UPB": STOCKS["watch_signal"],
           "NSE_EQ|DOWN": STOCKS["downtrend"], "NSE_EQ|SHORT": STOCKS["short_history"],
           "NSE_EQ|QUIET": STOCKS["noisy_flat"]}


def _scan(monkeypatch, repo, *, enabled, client=None, lease=None):
    """One scheduled scan at 10:00 IST with five synthetic stocks, shortlist of four."""
    monkeypatch.delenv("PROSPECTIVE_DATA_LICENSE_ACK", raising=False)
    monkeypatch.setenv("SCHEDULED_STAGE1_TOP_N", "4")
    if enabled:
        monkeypatch.setenv(s2.ENABLE_ENV, "1")
    else:
        monkeypatch.delenv(s2.ENABLE_ENV, raising=False)
    received = NOW.astimezone(UTC)
    quotes = {}
    for i, row in enumerate(UNIVERSE):
        last = CANDLES[row["instrument_key"]][0][4]
        live = _quote_for(CANDLES[row["instrument_key"]])["last_price"]
        quotes[row["instrument_key"]] = stage1_quote(live, last, 2000 - 100 * i, received)
    monkeypatch.setattr(collector, "fetch_nse_universe", lambda c: UNIVERSE)
    monkeypatch.setattr(collector, "fetch_full_quotes", lambda c, t, keys: quotes)
    monkeypatch.setattr(collector, "fetch_nse_exchange_status",
                        lambda c, t: {"exchange": "NSE", "status": "NORMAL_OPEN"})
    repo.pauses = []
    monkeypatch.setattr(s2.time, "sleep", repo.pauses.append)
    monkeypatch.setattr(collector, "require_licence_acknowledgement", repo.store_order_book_marker)
    monkeypatch.setattr(collector, "store_order_books",
                        lambda writer, quotes, selected: {"stored": len(selected)})
    client = client or CandleClient({s2.NIFTY_KEY: NIFTY_CANDLES, **CANDLES})
    return collector._scheduled_stage1(repo, client, "token", "run-1", now=NOW, lease=lease), client


def _stage1(repo):
    """Stage-1 batch payload and scanner rows (what existed before Phase 2)."""
    batch = next(e for e in repo.ledger if e["aggregate_id"] == "scan:run-1")
    rows = [r for r in repo.scanner if r["strategy_version"] == collector.SCHEDULED_STAGE1_VERSION]
    return json.dumps(batch["payload"], sort_keys=True, default=str), \
        json.dumps(rows, sort_keys=True, default=str)


def test_switch_off_changes_nothing(monkeypatch):
    """Default: no history requests, no shadow rows, no shadow batch."""
    repo = Repo()
    result, client = _scan(monkeypatch, repo, enabled=False)
    assert result["stage2_shadow"] == {"status": "DISABLED",
                                       "reason": f"{s2.ENABLE_ENV} is not enabled"}
    assert client.calls == []
    assert [e["aggregate_id"] for e in repo.ledger] == ["scan:run-1"]
    assert {r["strategy_version"] for r in repo.scanner} == {collector.SCHEDULED_STAGE1_VERSION}


def test_switch_on_adds_complete_shadow_evidence_and_leaves_stage1_identical(monkeypatch):
    """Stage-1 evidence byte-identical; one shadow row per shortlisted ticker."""
    off, on = Repo(), Repo()
    _scan(monkeypatch, off, enabled=False)
    calls = []
    real_core = s2.evaluate_stage2

    def spy(ticker, **kwargs):
        """Record what the collector hands app.py's decision core."""
        calls.append(kwargs)
        return real_core(ticker, **kwargs)

    monkeypatch.setattr(s2, "evaluate_stage2", spy)
    result, _ = _scan(monkeypatch, on, enabled=True)
    # Wiring into the decision core: verified market status and the app's defaults.
    assert len(calls) == 4
    for kw in calls:
        assert kw["market_open"] is True and kw["custom_days"] == 15
        assert (kw["max_stock_price"], kw["require_weekly_align"], kw["use_advanced_signal_filters"]) \
            == (50000.0, False, False)
        engine = kw["risk_engine"]
        assert (engine.investment_capital, engine.max_risk_pct, engine.max_position_pct) == (1e6, 2.0, 20.0)
        assert isinstance(kw["feature_store"], s2.ComputeOnlyFeatureStore)
        assert set(kw["live_quote_data"]) == {kw["key"]}
    quote_last = {r["instrument_key"]: q["last"] for r, q in (
        (c, c["quote"]) for c in json.loads(_stage1(on)[0])["candidates"])}
    assert _stage1(on) == _stage1(off)
    summary = result["stage2_shadow"]
    shortlisted = {r["instrument_key"] for r in on.scanner
                   if r["strategy_version"] == collector.SCHEDULED_STAGE1_VERSION and r["stage1_pass"]}
    shadow = [r for r in on.scanner if r["strategy_version"] == s2.STAGE2_SHADOW_VERSION]
    assert len(shortlisted) == 4 and {r["instrument_key"] for r in shadow} == shortlisted
    assert summary["status"] == "SUCCESS" and summary["archive_status"] == "STORED"
    assert summary["shortlisted"] == summary["evaluated"] == len(shadow) == 4
    assert summary["passed"] == sum(r["stage2_pass"] for r in shadow) >= 1
    assert summary["decision_errors"] == 0
    # Order: all Stage-1 evidence (batch, rows, order books) before any shadow write.
    stage2_aggregate = "scan:run-1" + s2.STAGE2_RUN_SUFFIX
    assert on.ops == [("ledger", "scan:run-1"), ("rows", (collector.SCHEDULED_STAGE1_VERSION,)),
                      ("order_books", None), ("ledger", stage2_aggregate),
                      ("rows", (s2.STAGE2_SHADOW_VERSION,))]
    # Shadow ids never collide with Stage-1 ids (a real upsert would overwrite them).
    stage1_ids = {r["observation_id"] for r in on.scanner
                  if r["strategy_version"] == collector.SCHEDULED_STAGE1_VERSION}
    assert stage1_ids.isdisjoint({r["observation_id"] for r in shadow}) and len(stage1_ids) == 5
    # One pause before each shortlisted history request (NIFTY is fetched first, unpaused).
    assert on.pauses == [s2.REQUEST_PAUSE_SECONDS] * 4
    batch = next(e for e in on.ledger if e["aggregate_id"] == "scan:run-1" + s2.STAGE2_RUN_SUFFIX)
    payload = batch["payload"]
    assert batch["event_type"] == "DECISION_BATCH_EVALUATED"
    assert batch["idempotency_key"] == "decision-batch:run-1" + s2.STAGE2_RUN_SUFFIX
    assert payload["strategy_id"] == s2.STAGE2_SHADOW_VERSION
    assert payload["horizon_sessions"] == 15 and payload["candidate_count"] == 4
    assert payload["universe"] == json.loads(_stage1(on)[0])["universe"]
    candidates = {c["decision_id"]: c for c in payload["candidates"]}
    stage1_payload = json.loads(_stage1(on)[0])
    assert payload["observed_at"] == stage1_payload["observed_at"]
    for row in shadow:
        c = candidates[row["observation_id"]]
        used = c["inputs_used"]
        # The ledger batch is the only full copy of the shadow evidence.
        assert set(used) == {
            "parent_scan_run_id", "stage1_decision_scan", "status", "stage2_pass", "category",
            "reason", "score", "entry", "stop", "target", "signal_action", "signal_action_reason",
            "features", "governance_evaluated", "history", "evaluated_at", "equity_capture"}
        assert used["status"] == s2.EVALUATED and used["stage1_decision_scan"] == "scan:run-1"
        assert (used["features"] is not None) is row["stage2_pass"]
        assert used["equity_capture"]["schema"] == "equity-observation-capture-v1-compact"
        assert used["equity_capture"]["inputs"]["live_price"] == quote_last[row["instrument_key"]]
        assert used["history"]["days_requested"] == 1200 and used["history"]["source"] == s2.HISTORY_SOURCE
        parsed = s2._history_to_dataframe(CANDLES[row["instrument_key"]])
        assert 0 < used["history"]["rows"] <= len(parsed)  # window cut from the real clock
        assert used["history"]["last"] == parsed.index.max().isoformat()
        estimates = used["equity_capture"]["costs"]["estimates"]
        assert c["costs"] == ({"status": "NOT_EVALUATED", "reason": "Stage-2 stopped before the cost estimate"}
                              if estimates is None else
                              {"status": "MODEL_ESTIMATE", "round_trip_bps": estimates["round_trip_bps"],
                               "assumptions": "Stage-2 execution-cost model; not measured executable spread"})
        assert row["observation_id"] == hashlib.sha256(
            f"run-1|{row['instrument_key']}|equity-stage2-scheduled-shadow-v1".encode()).hexdigest()
        assert row["features"] == {"scan_run_id": "run-1" + s2.STAGE2_RUN_SUFFIX, "retention": "ledger_v1"}
        assert c["action"] == ("Watch" if row["stage2_pass"] else "No Trade")
        assert c["inputs_used"]["governance_evaluated"] is False
        assert c["inputs_used"]["parent_scan_run_id"] == "run-1"
        assert c["rejection_reason"] == row["rejection_reason"]
        if row["stage2_pass"]:
            assert row["rejection_reason"] is None
            assert row["stop"] < row["entry"] < row["target"]
            assert c["inputs_used"]["signal_action"] in {"Buy", "Watch"}
        else:
            assert re.match(r"^[A-Z][A-Za-z: -]+: ", row["rejection_reason"])
        assert c["quote"] == next(q["quote"] for q in json.loads(_stage1(on)[0])["candidates"]
                                  if q["instrument_key"] == row["instrument_key"])
    # Never an executable action anywhere in the shadow evidence, even for a Buy signal.
    assert {c["action"] for c in payload["candidates"]} <= {"Watch", "No Trade"}
    assert {c["inputs_used"]["signal_action"] for c in payload["candidates"]} >= {"Buy", "Watch"}
    assert all(not r["stage2_pass"] for r in on.scanner
               if r["strategy_version"] == collector.SCHEDULED_STAGE1_VERSION)


def test_shadow_batch_failure_is_contained_and_writes_no_rows(monkeypatch):
    """Ledger failure -> FAILED summary + quality event; no shadow rows; Stage-1 kept."""
    repo = Repo(fail_stage2_batch=True)
    result, _ = _scan(monkeypatch, repo, enabled=True)
    assert result["status"] == "SUCCESS"
    assert result["stage2_shadow"] == {"status": "FAILED", "error_type": "RuntimeError"}
    assert not any(r["strategy_version"] == s2.STAGE2_SHADOW_VERSION for r in repo.scanner)
    assert any(args[2] == "STAGE2_SHADOW_FAILED" for args, _ in repo.quality_events)
    assert _stage1(repo)[1] != "[]"


def test_partial_run_is_reported_as_a_quality_event(monkeypatch):
    """A shortlisted ticker without history -> PARTIAL, recorded, row says why."""
    probe = Repo()
    _scan(monkeypatch, probe, enabled=False)
    failing = next(r["instrument_key"] for r in probe.scanner if r["stage1_pass"])
    client = CandleClient({s2.NIFTY_KEY: NIFTY_CANDLES, **CANDLES, failing: 502})
    repo = Repo()
    result, _ = _scan(monkeypatch, repo, enabled=True, client=client)
    summary = result["stage2_shadow"]
    assert summary["status"] == "PARTIAL" and summary["not_evaluated"] == 1
    events = [args for args, _ in repo.quality_events if args[0] == "scheduled_stage2_shadow"]
    assert [(e[1], e[2]) for e in events] == [("WARNING", "STAGE2_SHADOW_PARTIAL")]
    row = next(r for r in repo.scanner if r["strategy_version"] == s2.STAGE2_SHADOW_VERSION
               and r["instrument_key"] == failing)
    assert row["rejection_reason"] == "Not Evaluated: Price history unavailable (HistoryUnavailable)"
    batch = next(e for e in repo.ledger if e["aggregate_id"].endswith(s2.STAGE2_RUN_SUFFIX))
    missing = next(c for c in batch["payload"]["candidates"] if c["instrument_key"] == failing)
    assert missing["action"] == "No Trade" and missing["inputs_used"]["status"] == s2.NOT_EVALUATED
    assert missing["inputs_used"]["governance_evaluated"] is False
    assert missing["inputs_used"]["equity_capture"] is None


def _direct_run(repo, *, check_lease=None, client=None, shortlist=None):
    """run_shadow_stage2 on three synthetic tickers, switch on, fixed clock."""
    keys = shortlist or [("UPA", "NSE_EQ|UPA"), ("DOWN", "NSE_EQ|DOWN"), ("SHORT", "NSE_EQ|SHORT")]
    client = client or CandleClient({s2.NIFTY_KEY: NIFTY_CANDLES, **CANDLES})
    quotes = {k: _quote_for(CANDLES[k]) for _, k in keys}
    return s2.run_shadow_stage2(
        repo, client, "token", "run-1", shortlist=keys, quotes=quotes,
        quote_evidence={k: {"status": "AVAILABLE"} for _, k in keys},
        universe={"status": "VERIFIED"}, now=NOW, observed_at=NOW.astimezone(UTC),
        market_open=True, stage1_top_n=3, check_lease=check_lease,
        environ={s2.ENABLE_ENV: "1"}, sleep=lambda s: None, wall_clock=lambda: FIXED_NOW,
    ), client


def test_lease_lost_after_evaluation_writes_nothing():
    """Fencing is re-checked right before the shadow batch: lost -> no writes at all."""
    calls = []

    def lease():
        """Valid for NIFTY + each ticker, lost at the pre-write check."""
        calls.append(1)
        if len(calls) > 4:
            raise RuntimeError("Collector lease was lost; fenced worker stopped")

    repo = Repo()
    with pytest.raises(s2.LeaseLost):
        _direct_run(repo, check_lease=lease)
    assert len(calls) == 5 and repo.ledger == [] and repo.scanner == []


def test_data_quality_rejection_is_never_a_pass(monkeypatch):
    """A non-finite value in a pass -> ledger 'No Trade' reject, row not passed, full features."""
    original = s2.evaluate_candidate

    def poisoned(ticker, key, **kwargs):
        """Real evaluation; then a non-finite feature on the passing ticker."""
        result = original(ticker, key, **kwargs)
        if result["stage2_pass"]:
            result["features"] = {**result["features"], "relative_strength": float("inf")}
        return result

    monkeypatch.setattr(s2, "evaluate_candidate", poisoned)
    repo = Repo()
    summary, _ = _direct_run(repo)
    assert summary["passed"] == 1 and summary["data_quality_rejected"] == 1
    batch = next(e for e in repo.ledger if e["aggregate_id"].endswith(s2.STAGE2_RUN_SUFFIX))
    bad = next(c for c in batch["payload"]["candidates"] if "data_quality" in c)
    row = repo.rows[bad["decision_id"]]
    assert bad["action"] == "No Trade" and bad["data_quality"]["original_action"] == "Watch"
    assert row["stage2_pass"] is False and row["rejection_reason"] == bad["rejection_reason"]
    assert row["features"]["shadow_action"] == "No Trade"
    assert row["features"]["features"]["relative_strength"] == float("inf")  # full evidence kept
    assert any(args[2] == "CANDIDATE_DATA_QUALITY_REJECTED" for args, _ in repo.quality_events)


def test_decision_core_errors_are_counted(monkeypatch):
    """The core's own 'Error' rejects stay EVALUATED (as in the app) but are counted."""
    monkeypatch.setattr(s2, "evaluate_stage2", lambda *a, **k: (None, {"category": "Error",
                                                                        "reason": "boom"}))
    summary, _ = _direct_run(Repo())
    assert summary["decision_errors"] == summary["evaluated"] == 3


def test_run_scan_fences_stage2_and_counts_its_rows(monkeypatch):
    """run('scan') hands its lease to Stage-2, counts shadow rows, flags a partial shadow."""
    class RunRepo(Repo):
        """Repo with the run/lease API run() needs."""

        def __init__(self):
            """Start empty."""
            super().__init__()
            self.finished = []

        def acquire_collector_lease(self, *a, **k):
            """Grant the lease."""
            return {"fencing_token": 7}

        def renew_collector_lease(self, *a, **k):
            """Keep the lease."""
            return True

        def release_collector_lease(self, *a, **k):
            """Release the lease."""
            return True

        def start_run(self, *a, **k):
            """The scan run id the shadow ids derive from."""
            return "run-1"

        def finish_run(self, run_id, **kwargs):
            """Record the final run status."""
            self.finished.append(kwargs)

    probe = Repo()
    _scan(monkeypatch, probe, enabled=False)
    failing = next(r["instrument_key"] for r in probe.scanner if r["stage1_pass"])
    repo = RunRepo()
    client = CandleClient({s2.NIFTY_KEY: NIFTY_CANDLES, **CANDLES, failing: 503})
    seen = {}
    real = collector._scheduled_stage1

    def stage1(repo_, client_, token, run_id, **kwargs):
        """Run the real scan at 10:00 IST; remember the lease it was given."""
        seen["lease"] = kwargs.get("lease")
        return real(repo_, client_, token, run_id, now=NOW, lease=kwargs.get("lease"))

    monkeypatch.setenv("UPSTOX_ANALYTICS_TOKEN", "token")
    monkeypatch.setattr(collector, "ProductionRepository", lambda *a, **k: repo)
    monkeypatch.setattr(collector, "session", lambda: client)
    monkeypatch.setattr(collector, "_scheduled_stage1", stage1)
    _scan(monkeypatch, repo, enabled=True, client=client)  # installs the same fakes
    repo.rows, repo.ops, repo.ledger, repo.quality_events = {}, [], [], []
    result = collector.run("scan")
    assert isinstance(seen["lease"], collector.CollectorLease)
    shadow = result["scheduled_stage1"]["stage2_shadow"]
    assert shadow["status"] == "PARTIAL" and shadow["scanner_observations"] == 4
    assert result["status"] == "PARTIAL" and repo.finished[-1]["status"] == "PARTIAL"
    assert repo.finished[-1]["record_count"] == 5 + 4


def test_lost_lease_propagates_out_of_the_scan(monkeypatch):
    """The run must fail (fenced) instead of writing shadow evidence."""
    lease = types.SimpleNamespace(assert_valid=lambda: (_ for _ in ()).throw(
        RuntimeError("Collector lease was lost; fenced worker stopped")))
    repo = Repo()
    with pytest.raises(s2.LeaseLost):
        _scan(monkeypatch, repo, enabled=True, lease=lease)
    assert not any(e["aggregate_id"].endswith(s2.STAGE2_RUN_SUFFIX) for e in repo.ledger)


def test_shadow_evidence_stays_small(monkeypatch):
    """Ledger never deletes: keep a shortlisted candidate's evidence compact."""
    repo = Repo()
    _scan(monkeypatch, repo, enabled=True)
    batch = next(e for e in repo.ledger if e["aggregate_id"].endswith(s2.STAGE2_RUN_SUFFIX))
    sizes = {c["instrument"]: len(json.dumps(c, separators=(",", ":")))
             for c in batch["payload"]["candidates"]}
    # Measured 10 Nov 2026: ~1.7-2.7 kB per reject, ~5.9 kB per pass (raw JSON,
    # before TOAST compression); 150 shortlisted is roughly 0.3-0.4 MB raw a run.
    assert max(sizes.values()) < 6500, sizes
    assert sum(sizes.values()) / len(sizes) < 4500, sizes


# ---------------------------------------------------------------- canary ---

def test_canary_accepts_the_shadow_stage2():
    """The deployment canary knows the shadow Stage-2 and finds it safe."""
    checks = run_canaries(ROOT)["checks"]
    assert checks["scheduled_stage2_is_shadow_only"] is True
    assert checks["scheduled_scan_is_shadow_only"] is True


@pytest.mark.parametrize("name, old, new", [
    ("equity_stage2_collector.py", 'action = "Watch" if item["stage2_pass"] else "No Trade"',
     'action = item["signal_action"] or "No Trade"'),
    ("equity_stage2_collector.py", '"governance_evaluated": False', '"governance_evaluated": True'),
    ("equity_stage2_collector.py", "def shadow_decision_id(", "def place_order(): pass\ndef shadow_decision_id("),
    ("equity_stage2_decision.py", "def evaluate_stage2(", "place_order = None\ndef evaluate_stage2("),
    ("scheduled_collector.py", "from equity_stage2_collector import run_shadow_stage2",
     "import equity_stage2_collector as live_stage2"),
])
def test_canary_rejects_an_unsafe_shadow_stage2(monkeypatch, name, old, new):
    """Any executable action, governance claim or order API turns the check off."""
    target = ROOT / name
    read_text = Path.read_text

    def altered(path, *args, **kwargs):
        """Serve the altered source for the one target file."""
        content = read_text(path, *args, **kwargs)
        if path == target:
            assert old in content
            return content.replace(old, new)
        return content

    monkeypatch.setattr(Path, "read_text", altered)
    assert run_canaries(ROOT)["checks"]["scheduled_stage2_is_shadow_only"] is False
