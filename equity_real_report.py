"""Pure private cash-study payloads; no files, credentials, network, app or fitting.

build_report(decoded_by_symbol, *, manifest=None, expected_sessions=None) accepts
one decode_daily result or a list of annual results per fixed pilot symbol.
Optional manifest: {format: equity-real-inputs-v1, cohort: [...], symbols:
{symbol: {instrument_key: ..., chunks: [{start, end, source_sha256,
decoded_sha256}, ...]}}}. Without it, verified decoded hashes are an observed
input inventory, never an independently supplied manifest or provider signature.
The caller writes JSON/HTML/Parquet. All returns are descriptive price scenarios.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import html
import json
import logging
import math
import re
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from equity_eod_pilot import COHORT
from event_backtest import run_long_bracket_backtest
import technical_indicators as ta

LOGGER = logging.getLogger(__name__)
COSTS = (30, 60, 100)
HORIZON = 15
MIN_HISTORY = HORIZON + 70
APP_SHA256 = "260daa7a79462b6715229ab2f1764c4026e6cb7ac0bf43c0e01353aadfaf0d0d"
INDICATORS_SHA256 = "e91816284bf431f4c33934994509e9d6f605da8f992db1ff740bf3e344749032"
ENGINE_SHA256 = "e28c20793792428ffdf852e12da6a355c43413d44067c43ccc620272f3e0fbf2"
RULE_LABEL = "EXISTING_DAILY_TECHNICAL_SANITY_RULE_NOT_FULL_APP_SCANNER"
TradeLevels = tuple[float, float, float, dict[str, float]] | tuple[None, None, None, None]


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _fail() -> ValueError:
    return ValueError("EQUITY_REAL_REPORT_INVALID_INPUT")


def _study_design() -> dict[str, Any]:
    """Input-independent implementation choices, not authenticated preregistration."""
    return {
        'cohort_rule_map': {symbol: RULE_LABEL for symbol in COHORT},
        'horizon_sessions': HORIZON,
        'horizon_basis': 'LAB_FREEZE_FROM_DERIVE_LONG_TRADE_LEVELS_DEFAULT_NOT_CURRENT_LIVE_UI_SETTING',
        'minimum_prepared_history': MIN_HISTORY,
        'cost_scenarios_bps': list(COSTS),
        'warmup_year': 2022, 'evaluation_years': [2023, 2024],
        'capital_policy': 'TWELVE_EQUAL_INITIAL_SLEEVES_NO_REALLOCATION',
        'post_input_reoptimization': False, 'data_driven_rule_selection': False,
        'historical_preregistration_verified': False,
        'approval_authority': False, 'training_eligible': False,
        'data_admission_authorised': False, 'promotion_authorised': False,
        'performance_claim_verified': False, 'out_of_sample_claim': False,
        'full_app_reproduction': False, 'fill_evidence': False,
    }


def _day(value: object) -> date:
    if type(value) is not str:
        raise _fail()
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value or not date(2022, 1, 1) <= parsed <= date(2024, 12, 31):
        raise _fail()
    return parsed


def _hash(value: object) -> str:
    if type(value) is not str or re.fullmatch("[a-f0-9]{64}", value) is None:
        raise _fail()
    return value


# These three functions are literal copies of the pinned app's allowlisted pure
# routines with annotations only. Tests compare annotation-normalized ASTs and
# evaluate pinned references in a
# minimal test-only namespace. Production never imports or executes app.py.
def derive_long_trade_levels(df: pd.DataFrame, price: float, atr: float, horizon_days: int = 15) -> TradeLevels:
    try:
        if df.empty or price <= 0 or atr <= 0:
            return None, None, None, None

        lookback = df.tail(60)
        prior = lookback.iloc[:-1] if len(lookback) > 2 else lookback
        support20 = float(prior["Low"].tail(20).min()) if not prior.empty else float(price - atr)
        resistance20 = float(prior["High"].tail(20).max()) if not prior.empty else float(price + 2 * atr)
        resistance60 = float(prior["High"].max()) if not prior.empty else float(price + 3 * atr)

        atr_stop = price - 1.5 * atr
        structural_stop = support20 - 0.15 * atr if support20 < price else atr_stop
        stop = min(atr_stop, structural_stop)
        if stop <= 0 or stop >= price:
            stop = price - 1.5 * atr

        risk_distance = price - stop
        target_floor = price + max(2.0 * atr, risk_distance * 1.4)
        horizon_mult = 2.0 * (1.0 + horizon_days / 70.0)
        atr_target = price + horizon_mult * atr

        resistance_candidates = [
            r for r in [resistance20, resistance60]
            if r > price * 1.005
        ]
        minimum_target = price + risk_distance * 1.5
        suitable_resistance = [r for r in resistance_candidates if r >= minimum_target]
        if suitable_resistance:
            target = min(min(suitable_resistance), max(target_floor, price + 0.85 * (atr_target - price)))
            target = min(target, min(suitable_resistance))
        else:
            target = max(target_floor, atr_target)

        if target <= price:
            return None, None, None, None

        rr = (target - price) / risk_distance if risk_distance > 0 else 0.0
        return round(float(stop), 2), round(float(target), 2), round(float(rr), 2), {
            "support20": round(support20, 2),
            "resistance20": round(resistance20, 2),
            "resistance60": round(resistance60, 2),
        }
    except Exception as exc:
        LOGGER.debug("Trade-level derivation failed: %s", exc)
        return None, None, None, None


def event_signal(history: pd.DataFrame) -> bool:
    latest = history.iloc[-1]
    return bool(
        latest['Close'] > latest['EMA_50']
        and latest['EMA_20'] >= latest['EMA_50']
        and latest['ADX'] >= 20
    )


def event_levels(history: pd.DataFrame, entry: float, event_hold_days: int) -> tuple[float, float] | None:
    latest_atr = float(history.iloc[-1]['ATR'])
    sl, tgt, rr, _ = derive_long_trade_levels(
        history, entry, latest_atr, event_hold_days,
    )
    if sl is None or tgt is None or rr is None or rr < 1.2:
        return None
    return float(sl), float(tgt)


def prepare_indicators(hist_df: pd.DataFrame) -> pd.DataFrame:
    # Exact arithmetic statements from backtest_signal, excluding its live-clock
    # cutoff, UI minimum-trade filter, GARCH, and summary presentation.
    d = hist_df.copy()
    d['EMA_20'] = ta.ema(d['Close'], length=20)
    d['EMA_50'] = ta.ema(d['Close'], length=50)
    adx_df = ta.adx(d['High'], d['Low'], d['Close'], length=14)
    d['ADX'] = adx_df.iloc[:, 0] if adx_df is not None and not adx_df.empty else np.nan
    d['ATR'] = ta.atr(d['High'], d['Low'], d['Close'], length=14)
    d = d.dropna(subset=['Open', 'High', 'Low', 'Close', 'EMA_20', 'EMA_50', 'ADX', 'ATR'])
    return d


def _expected_days(values: Sequence[str] | None) -> list[str]:
    if values is not None:
        if isinstance(values, (str, bytes)) or len(values) > 1096:
            raise _fail()
        days = [_day(value).isoformat() for value in values]
        if len(set(days)) != len(days):
            raise _fail()
        return sorted(days)
    return []


def _label(value: Any) -> str:
    return pd.Timestamp(value).tz_convert('Asia/Kolkata').date().isoformat()


def _evaluation_frame(frame: pd.DataFrame) -> pd.DataFrame:
    positions = [index for index, at in enumerate(frame.index) if pd.Timestamp(at).year >= 2023]
    return frame.iloc[positions].copy()


def _rows(symbol: str, supplied: object, binding: object) -> tuple[pd.DataFrame, list[dict[str, str]], list[str]]:
    chunks = [supplied] if type(supplied) is dict else supplied
    if type(chunks) is not list or len(chunks) > 3:
        raise _fail()
    if not chunks:
        return pd.DataFrame(), [], []
    descriptors: list[dict[str, str]] = []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    keys: set[str] = set()
    periods: list[tuple[date, date]] = []
    for chunk in chunks:
        if type(chunk) is not dict or chunk.get('status') != 'UPSTOX_DAILY_STRUCTURE_ONLY_NOT_ADMISSION':
            raise _fail()
        decoded_sha = _hash(chunk.get('decoded_sha256'))
        if _digest({key: value for key, value in chunk.items() if key != 'decoded_sha256'}) != decoded_sha:
            raise _fail()
        key = chunk.get('instrument_key')
        if type(key) is not str or re.fullmatch(r'NSE_EQ\|INE[A-Z0-9]{9}', key) is None:
            raise _fail()
        keys.add(key)
        first, last = _day(chunk.get('start')), _day(chunk.get('end'))
        if first > last or any(not (last < a or first > b) for a, b in periods):
            raise _fail()
        periods.append((first, last))
        descriptors.append({'start': first.isoformat(), 'end': last.isoformat(),
                            'source_sha256': _hash(chunk.get('source_sha256')), 'decoded_sha256': decoded_sha})
        candles = chunk.get('rows')
        if type(candles) is not list or type(chunk.get('row_count')) is not int or chunk['row_count'] != len(candles):
            raise _fail()
        if len(candles) > 1200 or len(rows) + len(candles) > 1200:
            raise _fail()
        for row in candles:
            if type(row) is not dict:
                raise _fail()
            day = _day(row.get('date'))  # Reject sealed dates before interpreting any price.
            if not first <= day <= last or day.isoformat() in seen:
                raise _fail()
            seen.add(day.isoformat())
            timestamp = row.get('provider_timestamp')
            if type(timestamp) is not str:
                raise _fail()
            stamp = datetime.fromisoformat(timestamp)
            if (stamp.date() != day or stamp.utcoffset() != timedelta(hours=5, minutes=30)
                    or (stamp.hour, stamp.minute, stamp.second, stamp.microsecond) not in ((0, 0, 0, 0), (9, 15, 0, 0))):
                raise _fail()
            prices = []
            for field in ('open', 'high', 'low', 'close'):
                value = row.get(field)
                if type(value) is not str or len(value) > 64:
                    raise _fail()
                number = Decimal(value)
                if not number.is_finite() or not 0 < number <= Decimal('1000000000'):
                    raise _fail()
                converted = float(number)
                if not math.isfinite(converted) or converted <= 0:
                    raise _fail()
                prices.append(converted)
            opening, high, low, close = prices
            if high < max(opening, close) or low > min(opening, close) or high < low:
                raise _fail()
            for field in ('volume', 'open_interest'):
                if type(row.get(field)) is not int or not 0 <= row[field] <= 10**14:
                    raise _fail()
            rows.append({'date': day.isoformat(), 'Open': opening, 'High': high, 'Low': low,
                         'Close': close, 'Volume': row['volume'], 'OI': row['open_interest']})
    if len(keys) > 1:
        raise _fail()
    if binding is not None:
        if type(binding) is not dict or binding.get('instrument_key') not in keys:
            raise _fail()
        expected = binding.get('chunks')
        if type(expected) is not list or sorted(expected, key=_digest) != sorted(descriptors, key=_digest):
            raise _fail()
    rows.sort(key=lambda row: row['date'])
    if not rows:
        return pd.DataFrame(), descriptors, list(keys)
    frame = pd.DataFrame(rows)
    frame.index = pd.DatetimeIndex(frame.pop('date')).tz_localize('Asia/Kolkata') + pd.Timedelta(hours=15, minutes=30)
    return frame, sorted(descriptors, key=lambda item: item['start']), list(keys)


def _metrics(curve: list[dict[str, Any]]) -> dict[str, Any]:
    if not curve or any(row['nav'] is None for row in curve):
        return {'return': None, 'max_drawdown': None, 'valuations_complete': False,
                'drawdown_basis': 'OBSERVED_SESSION_CLOSE_MTM_AND_MODELED_EXITS_NOT_INTRADAY_OR_OFFICIAL_CALENDAR_PROOF'}
    values = [1.0, *[float(row['nav']) for row in curve]]
    peak, drawdown = 1.0, 0.0
    for value in values:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1.0)
    return {'return': values[-1] - 1.0, 'max_drawdown': drawdown, 'valuations_complete': True,
            'drawdown_basis': 'OBSERVED_SESSION_CLOSE_MTM_AND_MODELED_EXITS_NOT_INTRADAY_OR_OFFICIAL_CALENDAR_PROOF'}


def _bh(frame: pd.DataFrame, cost: int, window: tuple[str, str] | None) -> dict[str, Any]:
    if frame.empty or window is None or _label(frame.index[0]) != window[0] or _label(frame.index[-1]) != window[1]:
        return {'curve': [], 'metrics': _metrics([]), 'trade_count': 0,
                'status': 'UNAVAILABLE_COMMON_WINDOW_ENDPOINT_OR_NO_EVALUATION_ROWS'}
    entry = float(frame.iloc[0]['Open'])
    curve: list[dict[str, Any]] = [{'date': _label(at), 'nav': float(row['Close']) / entry}
                                  for at, row in frame.iterrows()]
    curve[-1]['nav'] = max(0.0, curve[-1]['nav'] - cost / 10000.0)
    return {'curve': curve, 'metrics': _metrics(curve), 'trade_count': 1,
            'entry_session': curve[0]['date'], 'exit_session': curve[-1]['date']}


def _technical_book(frame: pd.DataFrame, trades: list[dict[str, Any]], cost: int) -> dict[str, Any]:
    cash, base, index = 1.0, 1.0, 0
    curve: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    exhausted = False
    for at, row in frame.iterrows():
        day = _label(at)
        nav = cash
        if index < len(trades):
            trade = trades[index]
            entry_day = pd.Timestamp(trade['entry_at']).tz_convert('Asia/Kolkata').date().isoformat()
            exit_day = pd.Timestamp(trade['exit_at']).tz_convert('Asia/Kolkata').date().isoformat()
            if day == entry_day:
                base = cash
            if entry_day <= day <= exit_day:
                nav = base * float(row['Close']) / trade['entry_price']
            if day == exit_day:
                scenario_return = trade['gross_return'] - cost / 10000.0
                cash = max(0.0, base * (1.0 + scenario_return))
                nav = cash
                ledger.append({key: trade[key] for key in ('entry_at', 'exit_at', 'entry_price', 'exit_price', 'stop', 'target', 'outcome', 'gross_return')}
                              | {'scenario_return': scenario_return, 'capital_before': base, 'capital_after': cash,
                                 'cost_bps': cost, 'funded': base > 0})
                exhausted = exhausted or cash == 0
                index += 1
        curve.append({'date': day, 'nav': float(nav)})
    return {'curve': curve, 'metrics': _metrics(curve), 'trades': ledger,
            'trade_count': len(ledger), 'capital_exhausted': exhausted}


def _technical(frame: pd.DataFrame) -> dict[str, Any]:
    prepared = prepare_indicators(frame) if not frame.empty else frame
    evaluation = _evaluation_frame(frame)
    if prepared.empty or len(prepared) < MIN_HISTORY or evaluation.empty:
        return {'label': RULE_LABEL, 'status': 'INSUFFICIENT_HISTORY', 'trade_count': 0,
                'eligible_decisions': 0, 'scenarios': {}, 'gross': None}
    eligible = 0

    def scoped_signal(history: pd.DataFrame) -> bool:
        nonlocal eligible
        if pd.Timestamp(history.index[-1]).year < 2023 or len(history) < MIN_HISTORY:
            return False
        eligible += 1
        return event_signal(history)

    replay = run_long_bracket_backtest(prepared, signal=scoped_signal, levels=event_levels,
                                     maximum_holding_bars=HORIZON, round_trip_cost_bps=0.0)
    trades = replay['trades']
    if any(not 2023 <= pd.Timestamp(trade['entry_at']).year <= 2024 for trade in trades):
        raise _fail()
    return {'label': RULE_LABEL, 'status': 'INSUFFICIENT_EVIDENCE_LT_20_TRADES' if len(trades) < 20 else 'DESCRIPTIVE_RETROSPECTIVE_SCENARIO',
            'trade_count': len(trades), 'eligible_decisions': eligible,
            'scenarios': {str(cost): _technical_book(evaluation, trades, cost) for cost in COSTS},
            'gross': _technical_book(evaluation, trades, 0),
            'engine': replay['engine'], 'fill_evidence': False}


def _portfolio(names: dict[str, Any], days: list[str], strategy: str, cost: int) -> dict[str, Any]:
    curves: list[dict[str, float]] = []
    reserved: list[str] = []
    for symbol in COHORT:
        data = names[symbol][strategy]
        scenario = data.get('scenarios', {}).get(str(cost))
        if scenario is None or not scenario['curve']:
            reserved.append(symbol)
            curves.append({day: 1.0 for day in days})
        else:
            curves.append({row['date']: row['nav'] for row in scenario['curve']})
    rows = []
    for day in days:
        values = [curve.get(day) for curve in curves]
        nav = sum(value for value in values if value is not None) / len(COHORT) if all(value is not None for value in values) else None
        rows.append({'date': day, 'nav': nav})
    metrics = _metrics(rows)
    complete = not reserved and all(names[symbol]['quality']['evaluation_coverage_complete'] for symbol in COHORT)
    return {'curve': rows, 'modeled_metrics_with_reserved_cash': metrics,
            'full_cohort_metrics': metrics if complete else None,
            'reserved_cash_symbols': reserved, 'complete_cohort': complete,
            'starting_weight_per_name': 1.0 / len(COHORT),
            'capital_policy': 'TWELVE_FIXED_INITIAL_CAPITAL_SLEEVES_NO_CROSS_NAME_REALLOCATION_NO_RENORMALIZATION'}


def build_report(decoded_by_symbol: Mapping[str, object], *, manifest: Mapping[str, object] | None = None,
                 expected_sessions: Sequence[str] | None = None) -> dict[str, Any]:
    """Return bounded JSON-safe results; absence/short histories are warnings.

    Shape/hash/date failures raise one fixed redacted ValueError. Empty input
    yields all twelve exclusions and a hypothetical cash reference, not success.
    No source discovery, external files, credentials, fitting or requests occur.
    """
    try:
        return _build(decoded_by_symbol, manifest, expected_sessions)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, InvalidOperation, RecursionError):
        raise _fail() from None


def _build(decoded: Mapping[str, object], manifest: Mapping[str, object] | None,
           expected_sessions: Sequence[str] | None) -> dict[str, Any]:
    if type(decoded) is not dict or not set(decoded).issubset(COHORT):
        raise _fail()
    bindings: dict[str, Any] = {}
    if manifest is not None:
        if (type(manifest) is not dict or manifest.get('format') != 'equity-real-inputs-v1'
                or manifest.get('cohort') != list(COHORT) or type(manifest.get('symbols')) is not dict):
            raise _fail()
        symbols = manifest['symbols']
        if type(symbols) is not dict:
            raise _fail()
        bindings = symbols
        if not set(bindings).issubset(COHORT) or any(symbol not in bindings for symbol in decoded):
            raise _fail()
    names: dict[str, Any] = {}
    observed: dict[str, Any] = {}
    frames: dict[str, pd.DataFrame] = {}
    all_keys: set[str] = set()
    total_rows = 0
    for symbol in COHORT:
        frame, chunks, keys = _rows(symbol, decoded.get(symbol, []), bindings.get(symbol))
        if any(key in all_keys for key in keys):
            raise _fail()
        all_keys.update(keys)
        observed[symbol] = {'instrument_key': keys[0] if keys else None, 'chunks': chunks}
        frames[symbol] = frame
    expected = (_expected_days(expected_sessions) if expected_sessions is not None else
                sorted({_label(at) for frame in frames.values() for at in frame.index}))
    evaluation_days = [day for day in expected if day >= '2023-01-01']
    window = (evaluation_days[0], evaluation_days[-1]) if evaluation_days else None
    for symbol in COHORT:
        frame = frames[symbol]
        chunks = observed[symbol]['chunks']
        actual = [_label(at) for at in frame.index] if not frame.empty else []
        total_rows += len(actual)
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        absent_years = [year for year in (2022, 2023, 2024) if not any(day.startswith(str(year)) for day in actual)]
        warnings = ['CALENDAR_PRICE_BASIS_CORPORATE_ACTIONS_AND_RIGHTS_NOT_INDEPENDENTLY_VERIFIED']
        if not actual:
            warnings.append('NO_ROWS_NAME_RETAINED_AS_EXCLUDED')
        if missing:
            warnings.append('MISSING_SESSIONS_NO_PRICE_FORWARD_FILL')
        if unexpected:
            warnings.append('DATES_OUTSIDE_EXPECTED_CALENDAR')
        if absent_years:
            warnings.append('MISSING_YEAR_OR_WARMUP')
        if len(chunks) != 3:
            warnings.append('ANNUAL_RESPONSE_SET_INCOMPLETE_OR_COMBINED')
        evaluation = _evaluation_frame(frame)
        actual_eval = [_label(at) for at in evaluation.index] if not evaluation.empty else []
        quality: dict[str, Any] = {'row_count': len(actual), 'warmup_2022_rows': sum(day < '2023-01-01' for day in actual),
                   'actual_first_row': actual[0] if actual else None, 'actual_last_row': actual[-1] if actual else None,
                   'evaluation_rows': len(actual_eval), 'missing_dates': missing, 'unexpected_dates': unexpected,
                   'missing_years': absent_years, 'response_count': len(chunks),
                   'evaluation_coverage_complete': bool(actual_eval) and set(actual_eval) == set(evaluation_days),
                   'coverage_claim': 'MATCH_TO_DIAGNOSTIC_REFERENCE_ONLY_NOT_HISTORICAL_COMPLETENESS_PROOF',
                   'warnings': warnings, 'excluded': evaluation.empty}
        names[symbol] = {'quality': quality,
                         'buy_hold': {'label': 'SAME_COHORT_BUY_HOLD_PRICE_RETURN_NOT_TOTAL_RETURN',
                                      'gross': _bh(evaluation, 0, window),
                                      'scenarios': {str(cost): _bh(evaluation, cost, window) for cost in COSTS}},
                         'technical': _technical(frame)}
        quality['comparison_exclusions'] = {
            'buy_hold': None if names[symbol]['buy_hold']['gross']['curve'] else 'COMMON_WINDOW_ENDPOINT_OR_EVALUATION_ROWS_MISSING',
            'technical': None if names[symbol]['technical']['scenarios'] else 'INSUFFICIENT_HISTORY_OR_EVALUATION_ROWS',
        }
    observed_manifest = {'format': 'equity-real-inputs-v1', 'cohort': list(COHORT), 'symbols': observed}
    # Keep all known dates; missing valuations become null rather than fabricated prices.
    days = sorted(set(evaluation_days) | {row['date'] for data in names.values()
                                        for row in data['buy_hold']['gross']['curve']})
    portfolio = {str(cost): {strategy: _portfolio(names, days, strategy, cost)
                             for strategy in ('buy_hold', 'technical')} for cost in COSTS}
    report: dict[str, Any] = {
        'format': 'equity-private-real-report-v1', 'status': 'DESCRIPTIVE_PRIVATE_PRICE_SCENARIOS' if total_rows else 'NO_USABLE_DATA',
        'cohort': list(COHORT), 'cohort_basis': 'PURPOSIVE_CURRENT_SURVIVOR_SET_NOT_HISTORICAL_UNIVERSE',
        'input_period': ['2022-01-01', '2024-12-31'], 'scored_period': ['2023-01-01', '2024-12-31'],
        'warmup_period': ['2022-01-01', '2022-12-31'], 'cost_scenarios_bps': list(COSTS),
        'observed_comparison_window': list(window) if window is not None else None,
        'input_binding': {'decoded_chunk_hashes_verified': True, 'external_manifest_supplied': manifest is not None,
                          'external_manifest_binding_verified': manifest is not None and bool(bindings) and all(symbol in decoded and bool(observed[symbol]['chunks']) for symbol in bindings),
                          'manifest_sha256': _digest(manifest if manifest is not None else observed_manifest),
                          'observed_chunks': observed, 'provider_authentication_verified': False},
        'dataset_quality': {'total_rows': total_rows, 'symbols_with_rows': sum(data['quality']['row_count'] > 0 for data in names.values()),
                            'excluded_names': [symbol for symbol, data in names.items() if data['quality']['excluded']],
                            'calendar_reference': 'CALLER_EXPECTED_SESSIONS_NOT_VERIFIED_OFFICIAL_CALENDAR' if expected_sessions is not None else 'OBSERVED_UNION_DIAGNOSTIC_NOT_OFFICIAL_EXCHANGE_CALENDAR',
                            'gaps_shared_by_all_names_detectable': False,
                            'calendar_verified': False, 'corporate_actions_verified': False,
                            'historical_raw_executable_price_basis_verified': False, 'rights_verified': False},
        'rule': {'label': RULE_LABEL, 'horizon_sessions': HORIZON, 'minimum_prepared_history': MIN_HISTORY,
                 'horizon_basis': 'LAB_FREEZE_FROM_DERIVE_LONG_TRADE_LEVELS_DEFAULT_NOT_CURRENT_LIVE_UI_SETTING',
                 'app_source_sha256': APP_SHA256, 'indicators_sha256': INDICATORS_SHA256, 'engine_sha256': ENGINE_SHA256,
                 'identity': 'ALLOWLISTED_FUNCTION_COPIES_TESTED_AGAINST_PINNED_SOURCE_NOT_RUNTIME_ATTESTATION'},
        'frozen_design': _study_design(), 'frozen_design_sha256': _digest(_study_design()),
        'assumptions': [
            'RETROSPECTIVE_DEVELOPMENT_NOT_UNTOUCHED_OOS_NOT_FULL_APP_SCANNER',
            '2022_FEATURE_WARMUP_ONLY_NO_2022_ORDERS_OR_SCORED_RETURNS',
            'DAILY_BARS_LABELLED_15_30_IST_NOT_PROVIDER_PUBLICATION_OR_ACTUAL_FILL_TIMES',
            'NEXT_OBSERVED_BAR_OPEN_PRICE_ENTRY_CLOSE_LABEL_ENGINE_CLOCK_NOT_PROVEN_NEXT_EXCHANGE_SESSION',
            'INTRABAR_STOP_FIRST_ADVERSE_GAP_AT_OPEN_TARGET_CAPPED_UNCHANGED_ENGINE',
            'FORCED_LAST_OBSERVED_CLOSE_LIQUIDATION_NO_2025_OUTCOMES',
            'PRICE_RETURN_ONLY_DIVIDENDS_AND_ACTION_RECONCILIATION_UNVERIFIED',
            'FLAT_ROUNDTRIP_STRESS_DEBITED_AT_EXIT_ON_ENTRY_NOTIONAL_NOT_DATED_FEES',
            'NORMALIZED_SLEEVE_UNITS_NOT_INTEGER_SHARE_EXECUTION_OR_EXECUTABLE_PNL',
            'CASH_REFERENCE_ZERO_INTEREST_NO_TRADE_NO_FEES',
            'CAPITAL_EXHAUSTION_FLOORED_AT_ZERO_NO_LEVERAGE_OR_NEGATIVE_CAPITAL_REINVESTMENT',
            'DRAWDOWN_IS_DAILY_MARK_TO_MARKET_INCLUDING_INITIAL_CAPITAL_NOT_REALIZED_TRADE_ONLY',
            'UNAVAILABLE_SLEEVES_RESERVED_CASH_FULL_COHORT_METRICS_WITHHELD_NO_SURVIVOR_REWEIGHTING',
            'UNVERIFIED_CALENDAR_ACTIONS_OR_GAPS_MEAN_DESCRIPTIVE_SCENARIOS_NOT_EXECUTABLE_PNL',
        ],
        'cash': {'label': 'CASH_NO_TRADE_ZERO_INTEREST', 'curve': [{'date': day, 'nav': 1.0} for day in days],
                 'return': 0.0, 'max_drawdown': 0.0, 'trade_count': 0},
        'per_name': names, 'equal_initial_weight': portfolio,
        'data_admission_authorised': False, 'training_eligible': False, 'promotion_authorised': False,
        'performance_claim_verified': False, 'out_of_sample_claim': False, 'full_app_reproduction': False,
        'fill_evidence': False, 'approval_authority': False, 'network_calls': 0, 'file_reads': 0, 'writes': 0,
    }
    report['report_sha256'] = _digest(report)
    return report


def render_html(report: Mapping[str, Any]) -> str:
    """Return private, self-contained escaped HTML; never write or load assets."""
    payload = json.dumps(report, sort_keys=True, indent=2, allow_nan=False)
    rows = []
    comparison = ['<tr><td>0</td><td>Cash / no trade</td><td>0.00%</td><td>0.00%</td>'
                  '<td>Zero interest; no trades or fees</td></tr>']
    for cost, strategies in report.get('equal_initial_weight', {}).items():
        for strategy, result in strategies.items():
            metrics = result['modeled_metrics_with_reserved_cash']
            values = (cost, strategy, _percent(metrics['return']), _percent(metrics['max_drawdown']),
                      'all twelve on diagnostic reference' if result['complete_cohort'] else 'partial; unavailable sleeves reserved as cash')
            comparison.append('<tr>' + ''.join('<td>' + html.escape(str(value), quote=True) + '</td>' for value in values) + '</tr>')
    for symbol, data in report.get('per_name', {}).items():
        cells = (symbol, data['quality']['row_count'], len(data['quality']['missing_dates']),
                 data['technical']['status'], data['technical']['trade_count'])
        rows.append('<tr>' + ''.join('<td>' + html.escape(str(value), quote=True) + '</td>' for value in cells) + '</tr>')
    return ('<!doctype html><html><head><meta charset="utf-8"><title>Private cash equity study</title>'
            '<style>body{font:16px system-ui;margin:2rem;max-width:1100px}td,th{padding:.5rem;border:1px solid #aaa}table{border-collapse:collapse}pre{white-space:pre-wrap}</style>'
            '</head><body><h1>Private cash-equity study — 2022–2024 inputs</h1>'
            '<p>2023–2024 retrospective descriptive price scenarios. Not full-app, OOS, total-return, executable P&amp;L or deployment evidence.</p>'
            '<p>Study horizon: 15 observed sessions, frozen from the trade-level function default; this does not establish the current live UI setting. '
            'The twelve-name cohort, technical rule and cost stresses are fixed in this implementation; no re-optimization follows input analysis.</p>'
            '<p>Cash/no-trade reference: zero return, zero interest and zero fees. Equal initial weights mean twelve fixed capital sleeves, not daily rebalancing. '
            'Null valuations are unavailable; reported drawdown uses observed session-close mark-to-market values, not just realized trades or intraday lows.</p>'
            '<h2>Equal-initial-capital comparison</h2><table><thead><tr><th>Cost bps</th><th>Baseline</th><th>Scenario return</th><th>Observed MTM drawdown</th><th>Coverage basis</th></tr></thead><tbody>'
            + ''.join(comparison) + '</tbody></table><h2>Per-name coverage and technical evidence</h2>'
            +
            '<table><thead><tr><th>Name</th><th>Rows</th><th>Missing dates</th><th>Technical-rule status</th><th>Trades</th></tr></thead><tbody>'
            + ''.join(rows) + '</tbody></table><h2>Complete private report and trade ledgers</h2><pre>'
            + html.escape(payload, quote=True) + '</pre></body></html>')


def _percent(value: object) -> str:
    if value is None:
        return 'Unavailable'
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 'Unavailable'
    number = float(value)
    return f'{number:.2%}' if math.isfinite(number) else 'Unavailable'


def report_frames(report: Mapping[str, Any]) -> dict[str, pd.DataFrame]:
    """Optional derived frames for caller-managed private export; no writes."""
    summary: list[dict[str, Any]] = []
    curves: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    for symbol, data in report['per_name'].items():
        summary.append({'symbol': symbol, 'row_count': data['quality']['row_count'],
                        'technical_trade_count': data['technical']['trade_count'], 'technical_status': data['technical']['status']})
        for strategy in ('buy_hold', 'technical'):
            for cost, scenario in data[strategy].get('scenarios', {}).items():
                curves.extend({'symbol': symbol, 'strategy': strategy, 'cost_bps': int(cost), **row} for row in scenario['curve'])
                trades.extend({'symbol': symbol, 'strategy': strategy, **row} for row in scenario.get('trades', []))
    return {'summary': pd.DataFrame(summary), 'curves': pd.DataFrame(curves), 'trades': pd.DataFrame(trades)}
