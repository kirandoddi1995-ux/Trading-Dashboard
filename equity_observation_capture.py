"""Equity-only audit snapshots. These never authorize trades or certify PIT data."""
import datetime as dt
import math
from collections.abc import Mapping

from live_evidence import quote_evidence_times


INPUTS = (
    'price', 'live_price', 'sl', 'tgt', 'atr_val', 'levels', 'trade_math',
    'average_daily_value', 'cost_per_share', 'risk_per_share', 'qty_to_buy',
    'scanner_components', 'score', 'weekly_trend', 'rs_vs_nifty',
    'supertrend_bullish', 'adx_val', 'rsi_val', 'ema_trend', 'macd_status',
    'ema20_now', 'ema20_prev', 'ema20_slope_pct', 'current_day_volume',
    'avg_vol20', 'elapsed_fraction', 'raw_volume_ratio', 'volume_pace_ratio',
    'probability_result', 'stock_beta', 'mom_factor', 'momentum_20d',
    'trend_quality', 'volume_quality', 'breakout_quality', 'feature_cache_mode',
    'action', 'action_reason', 'timing', 'current_vol', 'is_choppy_adx',
    'is_low_volume', 'timeframes_mixed',
)


def clean(value):
    """JSON-safe copy; unknown/nonfinite data is null, never a guessed value."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dt.datetime):
        return value.isoformat() if value.tzinfo is not None else None
    if isinstance(value, Mapping):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if hasattr(value, 'item'):
        return clean(value.item())
    return None


class EquityCapture:
    def __init__(self, *, identity, settings):
        self.identity = clean(identity)
        self.settings = clean(settings)
        self.inputs = {}
        self.captured_at = {}
        self.quote = {}
        self.costs = None

    def observe(self, values, *, now):
        if now.tzinfo is None:
            raise ValueError('Capture clock must be timezone aware')
        for name in INPUTS:
            if name in values:
                self.inputs[name] = clean(values[name])
                self.captured_at.setdefault(name, now.isoformat())
        if 'latest' in values:
            self.inputs['latest_indicators'] = clean(values['latest'].to_dict())
            self.captured_at.setdefault('latest_indicators', now.isoformat())
        if 'raw_quote' in values:
            self.quote = clean(values['raw_quote'])
        if 'cost_estimate' in values:
            cost = values['cost_estimate']
            self.costs = clean({**vars(cost), 'round_trip_bps': cost.round_trip_bps})

    def snapshot(self):
        observed, received = quote_evidence_times(self.quote)
        market = self.quote.get('market_data') or self.quote
        return clean({
            'schema': 'equity-observation-capture-v1',
            'purpose': 'AUDIT_ONLY_NOT_TRADE_AUTHORIZATION',
            'identity': self.identity, 'settings': self.settings,
            'inputs': self.inputs, 'scanner_composite_score': self.inputs.get('score'),
            'captured_at': self.captured_at,
            'timestamp_semantics': 'Application capture times, not source availability certification',
            'source_feature_available_at': None,
            'source_feature_availability_reason': 'Not independently established by this capture',
            'quote': {'raw': self.quote, 'observed_at': observed, 'received_at': received,
                      'bid_used': market.get('bid_price'), 'ask_used': market.get('ask_price')},
            'costs': {'estimates': self.costs, 'measured_spread_available':
                      market.get('bid_price') is not None and market.get('ask_price') is not None,
                      'note': 'Model estimates; zero estimated spread does not establish zero executable spread'},
            'missing_or_uncomputed_inputs': [k for k in INPUTS if self.inputs.get(k) is None],
            'calculation_defaults': 'Existing scorer defaults may occur in derived inputs; raw missing values are retained separately. No defaults are added by capture.',
        })


def replay(snapshot):
    """Reproduce captured composite and net R:R only, with no provider access."""
    from prediction_validation import scanner_composite_score
    from trade_contracts import calculate_trade_math
    data = snapshot['inputs']
    result = {'scanner_composite_score': None, 'trade_math': None}
    if data.get('scanner_components') is not None:
        result['scanner_composite_score'] = scanner_composite_score(data['scanner_components'])
    costs = snapshot['costs']['estimates']
    if all(data.get(k) is not None for k in ('price', 'sl', 'tgt')) and costs is not None:
        result['trade_math'] = calculate_trade_math(
            data['price'], data['sl'], data['tgt'], round_trip_cost_bps=costs['round_trip_bps'],
            minimum_ratio=snapshot['settings']['minimum_net_rr'])
    return result
