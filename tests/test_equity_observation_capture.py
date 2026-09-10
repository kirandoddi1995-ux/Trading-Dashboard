import datetime as dt
import json
from types import SimpleNamespace

from equity_observation_capture import EquityCapture, replay
from prediction_validation import scanner_composite_score

NOW = dt.datetime(2026, 9, 10, 5, tzinfo=dt.timezone.utc)


def test_complete_snapshot_replays_without_fetching_features():
    capture = EquityCapture(identity={'ticker': 'FIXTURE'}, settings={'minimum_net_rr': 1.3})
    components = dict.fromkeys(['trend', 'momentum', 'volume', 'relative_strength',
                               'risk_reward', 'adx', 'volatility', 'historical_edge', 'momentum_beta'], 70.)
    capture.observe(dict(price=100, sl=95, tgt=107, scanner_components=components,
                         score=scanner_composite_score(components),
                         raw_quote={'last_trade_time': NOW.isoformat(), '_received_at': NOW.isoformat(),
                                    'bid_price': 99.9, 'ask_price': 100.1},
                         cost_estimate=SimpleNamespace(round_trip_bps=14, spread_bps=0)), now=NOW)
    frozen = json.loads(json.dumps(capture.snapshot(), allow_nan=False))
    assert replay(frozen)['scanner_composite_score'] == 70
    assert replay(frozen)['trade_math']['passes_gate'] is True
    assert frozen['quote']['observed_at'] == NOW.isoformat()
    assert frozen['costs']['measured_spread_available'] is True


def test_missing_sources_never_drop_known_score_or_invent_timestamps():
    capture = EquityCapture(identity={}, settings={'minimum_net_rr': 1.3})
    capture.observe({'score': 71, 'rs_vs_nifty': float('nan'), 'raw_quote': {}}, now=NOW)
    frozen = capture.snapshot()
    assert frozen['scanner_composite_score'] == 71
    assert frozen['inputs']['rs_vs_nifty'] is None
    assert frozen['quote']['observed_at'] is None
    assert frozen['quote']['received_at'] is None
    assert frozen['quote']['bid_used'] is None
    assert frozen['source_feature_available_at'] is None
    assert replay(frozen)['trade_math'] is None
    json.dumps(frozen, allow_nan=False)


def test_snapshot_is_detached_and_early_rejection_is_uncomputed():
    capture = EquityCapture(identity={}, settings={})
    capture.observe({'price': 100}, now=NOW)
    first = capture.snapshot()
    capture.observe({'price': 101}, now=NOW)
    assert first['inputs']['price'] == 100
    assert first['scanner_composite_score'] is None
    assert 'sl' in first['missing_or_uncomputed_inputs']
