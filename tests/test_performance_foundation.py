import sqlite3
import threading
import time

import numpy as np
import pandas as pd

from feature_store import FEATURE_COLUMNS, TechnicalFeatureStore, compute_feature_frame
from market_data_gateway import MarketDataGateway
from observability import MetricsRegistry, safe_endpoint
import smc_analysis as smc
import technical_indicators as ta


def test_observability_drops_query_strings_and_credentials():
    assert safe_endpoint('https://api.test/path?token=secret&x=1') == 'api.test/path'
    registry = MetricsRegistry()
    registry.record('api', 'GET api.test/path', .01, status=200)
    row = registry.summary()[0]
    assert row['Calls'] == 1 and row['Avg ms'] == 10.0


def test_gateway_coalesces_identical_concurrent_requests():
    gateway = MarketDataGateway()
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def loader():
        calls.append(1)
        entered.set()
        release.wait(2)
        return {'value': 7}

    results = []
    first = threading.Thread(target=lambda: results.append(gateway.get_or_load('x', ('same',), loader, ttl=1)))
    second = threading.Thread(target=lambda: results.append(gateway.get_or_load('x', ('same',), loader, ttl=1)))
    first.start()
    entered.wait(1)
    second.start()
    time.sleep(.03)
    release.set()
    first.join(2)
    second.join(2)
    assert calls == [1]
    assert results == [{'value': 7}, {'value': 7}]


def test_large_quote_snapshot_does_not_expand_websocket():
    class Buffer:
        def __init__(self):
            self.reconciled = []
            self.released = []
        def reconcile(self, scope, keys):
            self.reconciled.append((scope, keys))
        def release_scope(self, scope):
            self.released.append(scope)
        def snapshot(self, keys):
            return {}

    buffer = Buffer()
    keys = [f'K{i}' for i in range(250)]
    gateway = MarketDataGateway()
    result = gateway.quotes(
        keys, rest_loader=lambda missing: {
            key: {'last_price': 100.0, '_ts': time.time(), '_source': 'rest'} for key in missing
        }, buffer=buffer, market_open=True, scope='scan', websocket_limit=200,
    )
    assert not buffer.reconciled
    assert buffer.released == ['scan']
    assert len(result) == 250


def test_gateway_replaces_invalid_websocket_quote_with_rest_snapshot():
    class Buffer:
        def reconcile(self, scope, keys):
            self.scope = (scope, keys)

        def snapshot(self, keys):
            return {keys[0]: {'last_price': 90.0, '_ts': 1.0, '_source': 'websocket'}}

    rest_calls = []
    gateway = MarketDataGateway()
    result = gateway.quotes(
        ['K'],
        rest_loader=lambda missing: rest_calls.append(missing) or {
            'K': {'last_price': 101.0, '_ts': time.time(), '_source': 'rest'}
        },
        buffer=Buffer(),
        market_open=True,
        quote_validator=lambda quote: quote.get('_ts', 0) > time.time() - 5,
    )
    assert rest_calls == [['K']]
    assert result['K']['last_price'] == 101.0
    assert result['K']['_source'] == 'rest'


def test_app_defers_settings_master_and_non_market_live_feed():
    source = open('app.py', encoding='utf-8').read()
    assert 'primary_section == "Settings" and st.session_state.get("settings_symbols_requested", False)' in source
    assert 'Load NSE Watchlist Symbols' in source
    assert 'Live market feed deferred on this page' in source
    assert 'def reconcile(self, scope, keys)' in source
    assert 'self.streamer.unsubscribe' in source


def _connect(path):
    conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def _prices(rows=280):
    index = pd.bdate_range('2025-01-01', periods=rows)
    close = pd.Series(np.linspace(100, 180, rows) + np.sin(np.arange(rows) / 7), index=index)
    return pd.DataFrame({
        'Open': close - .2, 'High': close + 1.0, 'Low': close - 1.0,
        'Close': close, 'Volume': np.linspace(100_000, 180_000, rows), 'OI': np.nan,
    }, index=index)


def test_feature_store_hits_and_updates_only_latest_or_appended_rows(tmp_path):
    path = str(tmp_path / 'features.sqlite3')
    store = TechnicalFeatureStore(_connect, path)
    source = _prices()
    first, mode = store.enrich('K', source, lambda frame: compute_feature_frame(frame, ta))
    assert mode == 'full_rebuild'
    second, mode = store.enrich('K', source, lambda frame: (_ for _ in ()).throw(AssertionError('cache miss')))
    assert mode == 'hit'
    pd.testing.assert_series_equal(first['EMA_200'], second['EMA_200'])

    changed = source.copy()
    changed.iloc[-1, changed.columns.get_loc('Close')] += 1.0
    latest, mode = store.enrich('K', changed, lambda frame: compute_feature_frame(frame, ta))
    assert mode == 'latest_bar_update'
    expected = compute_feature_frame(changed, ta)
    for column in FEATURE_COLUMNS:
        np.testing.assert_allclose(latest[column], expected[column], rtol=1e-12, atol=1e-12, equal_nan=True)

    appended = pd.concat([changed, _prices(len(changed) + 1).iloc[[-1]]])
    appended_result, mode = store.enrich('K', appended, lambda frame: compute_feature_frame(frame, ta))
    assert mode == 'append'
    expected_appended = compute_feature_frame(appended, ta)
    for column in FEATURE_COLUMNS:
        np.testing.assert_allclose(
            appended_result[column], expected_appended[column], rtol=1e-12, atol=1e-12, equal_nan=True,
        )


def _slow_supertrend(high, low, close, length=10, multiplier=3.0):
    atr_values = ta.atr(high, low, close, length)
    midpoint = (high + low) / 2.0
    upper = (midpoint + multiplier * atr_values).copy()
    lower = (midpoint - multiplier * atr_values).copy()
    direction = pd.Series(np.nan, index=close.index, dtype=float)
    trend = pd.Series(np.nan, index=close.index, dtype=float)
    first = atr_values.first_valid_index()
    if first is None:
        return direction, trend
    start = close.index.get_loc(first)
    direction.iloc[start] = 1.0
    trend.iloc[start] = lower.iloc[start]
    for i in range(start + 1, len(close)):
        if pd.isna(upper.iloc[i]) or pd.isna(lower.iloc[i]):
            continue
        if upper.iloc[i] >= upper.iloc[i - 1] and close.iloc[i - 1] <= upper.iloc[i - 1]:
            upper.iloc[i] = upper.iloc[i - 1]
        if lower.iloc[i] <= lower.iloc[i - 1] and close.iloc[i - 1] >= lower.iloc[i - 1]:
            lower.iloc[i] = lower.iloc[i - 1]
        previous = direction.iloc[i - 1] if pd.notna(direction.iloc[i - 1]) else 1.0
        if close.iloc[i] > upper.iloc[i - 1]:
            current = 1.0
        elif close.iloc[i] < lower.iloc[i - 1]:
            current = -1.0
        else:
            current = previous
            if current > 0 and lower.iloc[i] < lower.iloc[i - 1]:
                lower.iloc[i] = lower.iloc[i - 1]
            elif current < 0 and upper.iloc[i] > upper.iloc[i - 1]:
                upper.iloc[i] = upper.iloc[i - 1]
        direction.iloc[i] = current
        trend.iloc[i] = lower.iloc[i] if current > 0 else upper.iloc[i]
    return direction, trend


def test_numpy_supertrend_is_numerically_identical_to_previous_algorithm():
    frame = _prices(600)
    expected_direction, expected_trend = _slow_supertrend(frame.High, frame.Low, frame.Close)
    result = ta.supertrend(frame.High, frame.Low, frame.Close)
    direction = result[[c for c in result if 'SUPERTd' in c][0]]
    trend = result[[c for c in result if c.startswith('SUPERT_')][0]]
    np.testing.assert_allclose(direction, expected_direction, equal_nan=True)
    np.testing.assert_allclose(trend, expected_trend, equal_nan=True)


def test_vectorized_smc_detects_structure_and_order_block():
    frame = _prices(80)
    trend, event = smc.detect_market_structure(frame)
    assert trend in {'Neutral / Ranging', 'Bullish (HH-HL)', 'Bearish (LH-LL)'}
    assert isinstance(event, str)
    atr = ta.atr(frame.High, frame.Low, frame.Close)
    assert isinstance(smc.detect_order_block(frame, atr, float(atr.dropna().iloc[-1])), str)
