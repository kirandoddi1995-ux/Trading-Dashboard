"""Generated fixtures only; no actual prices, credentials, downloads or 2025/26 data."""
from __future__ import annotations

import ast
import builtins
import copy
import hashlib
import inspect
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from equity_daily_ingest import decode_daily
from equity_eod_pilot import COHORT
from event_backtest import run_long_bracket_backtest
import equity_real_report as report
import technical_indicators as ta

ROOT = Path(__file__).resolve().parents[1]


def complete_dump(node: ast.AST) -> str:
    options = {'include_attributes': False}
    if 'show_empty' in inspect.signature(ast.dump).parameters:
        options['show_empty'] = True
    return ast.dump(node, **options)


def source_nodes() -> dict[str, ast.FunctionDef]:
    raw = (ROOT / 'app.py').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == report.APP_SHA256
    wanted = {'derive_long_trade_levels', 'event_signal', 'event_levels', 'backtest_signal'}
    return {node.name: node for node in ast.walk(ast.parse(raw.decode('utf-8')))
            if isinstance(node, ast.FunctionDef) and node.name in wanted}


def without_annotations(node: ast.FunctionDef) -> ast.FunctionDef:
    result = copy.deepcopy(node)
    result.returns = None
    for argument in [*result.args.posonlyargs, *result.args.args, *result.args.kwonlyargs]:
        argument.annotation = None
    if result.args.vararg is not None:
        result.args.vararg.annotation = None
    if result.args.kwarg is not None:
        result.args.kwarg.annotation = None
    return result


def reference_functions() -> dict[str, Any]:
    # Static pinned file, allowlisted pure definitions only; never import app.py.
    nodes = source_nodes()
    selected = [copy.deepcopy(nodes[name]) for name in ('derive_long_trade_levels', 'event_signal', 'event_levels')]
    assert {node.name for node in selected} == {'derive_long_trade_levels', 'event_signal', 'event_levels'}
    namespace: dict[str, Any] = {'LOGGER': logging.getLogger('synthetic-reference'), 'pd': pd, 'np': np, 'ta': ta}
    exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])),
                 '<allowlisted-pinned-pure-reference>', 'exec'), namespace)
    return namespace


def mini_frame() -> pd.DataFrame:
    days = pd.to_datetime(['2023-01-02', '2023-01-03', '2023-01-04', '2024-12-30', '2024-12-31'])
    opening = np.array([100., 105., 110., 115., 120.])
    close = np.array([104., 108., 112., 118., 125.])
    return pd.DataFrame({'Open': opening, 'High': np.maximum(opening, close) + 5,
                         'Low': np.minimum(opening, close) - 5, 'Close': close,
                         'Volume': 1000, 'OI': 0}, index=days)


def long_frame() -> pd.DataFrame:
    # Synthetic 2022 rows exercise the warmup-only boundary; all values generated.
    days = pd.bdate_range('2022-01-03', periods=180).append(
        pd.bdate_range('2023-01-02', periods=90)).append(pd.bdate_range('2024-01-02', periods=90))
    close = 100. + np.arange(len(days)) * .3 + np.sin(np.arange(len(days)) / 3.) * .1
    return pd.DataFrame({'Open': close - .1, 'High': close + 1.2, 'Low': close - 1.2,
                         'Close': close, 'Volume': 1000, 'OI': 0}, index=days)


def decoded(frame: pd.DataFrame, symbols: tuple[str, ...] = (COHORT[0],)) -> dict[str, list[dict[str, Any]]]:
    result = {}
    for symbol in symbols:
        key = f'NSE_EQ|INE{COHORT.index(symbol):09d}'
        chunks = []
        for year in (2022, 2023, 2024):
            subset = frame.loc[frame.index.year == year]
            if subset.empty:
                continue
            candles = [[at.date().isoformat() + 'T00:00:00+05:30',
                        *[float(row[name]) for name in ('Open', 'High', 'Low', 'Close')],
                        int(row['Volume']), int(row['OI'])] for at, row in subset.iterrows()]
            raw = json.dumps({'status': 'success', 'data': {'candles': candles}}).encode()
            chunks.append(decode_daily(raw, instrument_key=key, start=f'{year}-01-01', end=f'{year}-12-31'))
        result[symbol] = chunks
    return result


def manifest_for(data: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {'format': 'equity-real-inputs-v1', 'cohort': list(COHORT), 'symbols': {
        symbol: {'instrument_key': chunks[0]['instrument_key'], 'chunks': [
            {key: chunk[key] for key in ('start', 'end', 'source_sha256', 'decoded_sha256')} for chunk in chunks]}
        for symbol, chunks in data.items() if chunks}}


def rehash(chunk: dict[str, Any]) -> None:
    chunk['decoded_sha256'] = report._digest({key: value for key, value in chunk.items() if key != 'decoded_sha256'})


@pytest.mark.parametrize('name', ['derive_long_trade_levels', 'event_signal', 'event_levels'])
def test_rule_copies_preserve_full_ast_except_annotations(name: str) -> None:
    copied = ast.parse(inspect.getsource(getattr(report, name))).body[0]
    assert isinstance(copied, ast.FunctionDef)
    assert complete_dump(without_annotations(copied)) == complete_dump(source_nodes()[name])


def test_indicator_preparation_is_exact_pinned_arithmetic() -> None:
    copied = ast.parse(inspect.getsource(report.prepare_indicators)).body[0]
    assert isinstance(copied, ast.FunctionDef)
    source = source_nodes()['backtest_signal'].body[0]
    assert isinstance(source, ast.Try)
    assert complete_dump(ast.Module(body=copied.body[:-1], type_ignores=[])) == complete_dump(
        ast.Module(body=[source.body[0], *source.body[2:8]], type_ignores=[]))
    frame = long_frame()
    expected = frame.copy()
    expected['EMA_20'] = ta.ema(expected.Close, length=20)
    expected['EMA_50'] = ta.ema(expected.Close, length=50)
    adx = ta.adx(expected.High, expected.Low, expected.Close, length=14)
    expected['ADX'] = adx.iloc[:, 0]
    expected['ATR'] = ta.atr(expected.High, expected.Low, expected.Close, length=14)
    expected = expected.dropna(subset=['Open', 'High', 'Low', 'Close', 'EMA_20', 'EMA_50', 'ADX', 'ATR'])
    pd.testing.assert_frame_equal(report.prepare_indicators(frame), expected)


def test_indicators_and_engine_sources_unchanged() -> None:
    assert hashlib.sha256((ROOT / 'technical_indicators.py').read_bytes()).hexdigest() == report.INDICATORS_SHA256
    assert hashlib.sha256((ROOT / 'event_backtest.py').read_bytes()).hexdigest() == report.ENGINE_SHA256


@pytest.mark.parametrize('horizon', [1, 15, 30])
def test_copied_rule_numerical_equivalence(horizon: int) -> None:
    reference = reference_functions()
    frame = report.prepare_indicators(long_frame())
    for length in (1, 30, 60, len(frame)):
        history = frame.iloc[:length]
        price, atr = float(history.iloc[-1].Close), float(history.iloc[-1].ATR)
        assert report.derive_long_trade_levels(history, price, atr, horizon) == reference['derive_long_trade_levels'](history, price, atr, horizon)
        assert report.event_signal(history) == reference['event_signal'](history)
        assert report.event_levels(history, price, horizon) == reference['event_levels'](history, price, horizon)


@pytest.mark.parametrize('change', ['predicate', 'default', 'bracket_constant', 'feature_length'])
def test_mutated_rule_source_cannot_pass_parity(change: str) -> None:
    nodes = source_nodes()
    name = {'predicate': 'event_signal', 'default': 'derive_long_trade_levels',
            'bracket_constant': 'derive_long_trade_levels', 'feature_length': 'backtest_signal'}[change]
    node = copy.deepcopy(nodes[name])
    if change == 'predicate':
        compare = next(item for item in ast.walk(node) if isinstance(item, ast.Compare))
        compare.ops[0] = ast.Lt()
    elif change == 'default':
        node.args.defaults[0] = ast.Constant(value=14)
    else:
        value = 1.5 if change == 'bracket_constant' else 20
        constant = next(item for item in ast.walk(node) if isinstance(item, ast.Constant) and item.value == value)
        constant.value = 99
    assert complete_dump(node) != complete_dump(nodes[name])


def test_empty_input_retains_twelve_names_and_cash_only_reference() -> None:
    value = report.build_report({})
    assert value['status'] == 'NO_USABLE_DATA'
    assert value['cohort'] == list(COHORT) and len(value['per_name']) == 12
    assert value['dataset_quality']['excluded_names'] == list(COHORT)
    assert value['cash']['return'] == value['cash']['max_drawdown'] == 0
    assert value['equal_initial_weight']['30']['buy_hold']['full_cohort_metrics'] is None
    json.dumps(value, allow_nan=False)


def test_all_names_short_fixture_bh_costs_and_equal_initial_capital() -> None:
    data = decoded(mini_frame(), COHORT)
    value = report.build_report(data, manifest=manifest_for(data))
    assert value['input_binding']['external_manifest_binding_verified'] is True
    for cost in report.COSTS:
        expected = .25 - cost / 10000
        for symbol in COHORT:
            row = value['per_name'][symbol]
            assert row['buy_hold']['scenarios'][str(cost)]['metrics']['return'] == pytest.approx(expected)
            assert row['technical']['status'] == 'INSUFFICIENT_HISTORY'
        aggregate = value['equal_initial_weight'][str(cost)]['buy_hold']
        assert aggregate['complete_cohort'] is True
        assert aggregate['full_cohort_metrics']['return'] == pytest.approx(expected)
        assert aggregate['reserved_cash_symbols'] == []
    assert value['dataset_quality']['calendar_verified'] is False
    assert value['dataset_quality']['calendar_reference'].startswith('OBSERVED_UNION')
    assert value['dataset_quality']['gaps_shared_by_all_names_detectable'] is False
    for flag in ('approval_authority', 'performance_claim_verified', 'out_of_sample_claim',
                 'full_app_reproduction', 'data_admission_authorised', 'training_eligible', 'fill_evidence'):
        assert value[flag] is False
    json.dumps(value, allow_nan=False)


def test_missing_names_are_reserved_cash_not_reweighted_winners() -> None:
    value = report.build_report(decoded(mini_frame()))
    aggregate = value['equal_initial_weight']['30']['buy_hold']
    assert aggregate['modeled_metrics_with_reserved_cash']['return'] == pytest.approx(.247 / 12)
    assert aggregate['full_cohort_metrics'] is None
    assert len(aggregate['reserved_cash_symbols']) == 11
    assert len(value['per_name']) == 12


def test_gap_uses_observed_union_null_valuations_and_no_price_fill() -> None:
    data = decoded(mini_frame(), COHORT[:2])
    gap = data[COHORT[0]][0]['rows'].pop(1)['date']
    data[COHORT[0]][0]['row_count'] -= 1
    rehash(data[COHORT[0]][0])
    value = report.build_report(data)
    assert value['per_name'][COHORT[0]]['quality']['missing_dates'] == [gap]
    curve = value['equal_initial_weight']['30']['buy_hold']['curve']
    assert next(row['nav'] for row in curve if row['date'] == gap) is None
    assert value['equal_initial_weight']['30']['buy_hold']['modeled_metrics_with_reserved_cash']['max_drawdown'] is None


def test_missing_common_start_does_not_silently_shift_bh_entry() -> None:
    data = decoded(mini_frame(), COHORT[:2])
    data[COHORT[0]][0]['rows'].pop(0)
    data[COHORT[0]][0]['row_count'] -= 1
    rehash(data[COHORT[0]][0])
    value = report.build_report(data)
    assert value['per_name'][COHORT[0]]['buy_hold']['gross']['curve'] == []
    assert value['per_name'][COHORT[0]]['quality']['comparison_exclusions']['buy_hold'] is not None
    assert COHORT[0] in value['equal_initial_weight']['30']['buy_hold']['reserved_cash_symbols']


def test_special_weekend_is_accepted_not_rejected_as_weekday_calendar() -> None:
    frame = mini_frame().copy()
    frame.index = pd.to_datetime(['2023-01-02', '2023-01-03', '2023-01-07', '2024-12-30', '2024-12-31'])
    value = report.build_report(decoded(frame))
    assert value['per_name'][COHORT[0]]['quality']['unexpected_dates'] == []
    assert value['dataset_quality']['calendar_verified'] is False


def test_2022_warmup_no_carryin_and_small_trade_samples_retained() -> None:
    value = report.build_report(decoded(long_frame()))
    technical = value['per_name'][COHORT[0]]['technical']
    assert 0 < technical['trade_count'] < 20
    assert technical['status'] == 'INSUFFICIENT_EVIDENCE_LT_20_TRADES'
    assert technical['eligible_decisions'] > 0
    assert min(pd.Timestamp(trade['entry_at']).tz_convert('Asia/Kolkata').date().isoformat()
               for trade in technical['scenarios']['30']['trades']) > '2023-01-02'
    for cost, scenario in technical['scenarios'].items():
        assert scenario['metrics']['return'] is not None
        assert len(scenario['trades']) == technical['trade_count']
        for trade in scenario['trades']:
            stamp = pd.Timestamp(trade['entry_at']).tz_convert('Asia/Kolkata')
            assert 2023 <= stamp.year <= 2024 and stamp.hour == 15 and stamp.minute == 30
            assert trade['scenario_return'] == pytest.approx(trade['gross_return'] - int(cost) / 10000)
        assert all(row['date'] >= '2023-01-01' for row in scenario['curve'])
    assert 'NOT_FULL_APP' in technical['label']


def test_zero_trade_rule_retains_cash_returns_and_insufficient_evidence() -> None:
    frame = long_frame()
    close = 300. - np.arange(len(frame)) * .2
    frame['Open'], frame['Close'] = close + .1, close
    frame['High'], frame['Low'] = close + 1.2, close - 1.2
    technical = report.build_report(decoded(frame))['per_name'][COHORT[0]]['technical']
    assert technical['eligible_decisions'] > 0 and technical['trade_count'] == 0
    assert technical['status'] == 'INSUFFICIENT_EVIDENCE_LT_20_TRADES'
    for scenario in technical['scenarios'].values():
        assert scenario['metrics']['return'] == scenario['metrics']['max_drawdown'] == 0
        assert scenario['trades'] == []


@pytest.mark.parametrize('cost', report.COSTS)
def test_single_engine_gross_run_scenarios_match_costed_engine_trades(cost: int) -> None:
    frame = long_frame()
    frame.index = frame.index.tz_localize('Asia/Kolkata') + pd.Timedelta(hours=15, minutes=30)
    prepared = report.prepare_indicators(frame)
    result = run_long_bracket_backtest(prepared,
        signal=lambda history: history.index[-1].year >= 2023 and len(history) >= report.MIN_HISTORY and report.event_signal(history),
        levels=report.event_levels, maximum_holding_bars=15, round_trip_cost_bps=cost)
    actual = report.build_report(decoded(frame))['per_name'][COHORT[0]]['technical']['scenarios'][str(cost)]
    assert [trade['net_return'] for trade in result['trades']] == [trade['scenario_return'] for trade in actual['trades']]


def test_drawdown_is_mark_to_market_includes_initial_capital_not_closed_trades_only() -> None:
    frame = pd.DataFrame({'Open': [100., 90.], 'Close': [90., 110.]},
                         index=pd.to_datetime(['2023-01-02', '2023-01-03']).tz_localize('Asia/Kolkata'))
    trades = [{'entry_at': frame.index[0].isoformat(), 'exit_at': frame.index[1].isoformat(),
               'entry_price': 100., 'exit_price': 110., 'stop': 80., 'target': 120., 'outcome': 'END_OF_REPLAY', 'gross_return': .1}]
    value = report._technical_book(frame, trades, 100)
    assert value['metrics']['max_drawdown'] == pytest.approx(-.1)
    assert value['metrics']['return'] == pytest.approx(.09)
    assert [row['nav'] for row in value['curve']] == pytest.approx([.9, 1.09])


def test_sequential_trades_compound_one_sleeve_without_reusing_capital_twice() -> None:
    dates = pd.date_range('2023-01-02', periods=4, tz='Asia/Kolkata')
    frame = pd.DataFrame({'Open': [100., 100., 100., 100.], 'Close': [100., 110., 100., 110.]}, index=dates)
    trades = [{'entry_at': dates[start].isoformat(), 'exit_at': dates[start + 1].isoformat(),
               'entry_price': 100., 'exit_price': 110., 'stop': 90., 'target': 120.,
               'outcome': 'TIMEOUT', 'gross_return': .1} for start in (0, 2)]
    value = report._technical_book(frame, trades, 30)
    assert value['metrics']['return'] == pytest.approx((1.1 - .003) ** 2 - 1)
    assert value['trades'][1]['capital_before'] == value['trades'][0]['capital_after']


def test_capital_exhaustion_cannot_turn_negative_capital_into_later_profit() -> None:
    dates = pd.date_range('2023-01-02', periods=4, tz='Asia/Kolkata')
    frame = pd.DataFrame({'Open': [100., 100., 100., 100.], 'Close': [100., .1, 100., 1000.]}, index=dates)
    trades = [{'entry_at': dates[start].isoformat(), 'exit_at': dates[start + 1].isoformat(),
               'entry_price': 100., 'exit_price': exit_price, 'stop': .1, 'target': 1000.,
               'outcome': 'SYNTHETIC', 'gross_return': exit_price / 100. - 1.}
              for start, exit_price in ((0, .1), (2, 1000.))]
    value = report._technical_book(frame, trades, 100)
    assert value['capital_exhausted'] is True
    assert value['metrics']['return'] == -1 and value['curve'][-1]['nav'] == 0
    assert value['trades'][1]['funded'] is False


@pytest.mark.parametrize('change', ['stale_hash', 'source_hash', 'instrument', 'duplicate', 'sealed', 'sealed_2026', 'bad_price', 'bool_volume', 'bad_timestamp'])
def test_bad_shapes_bindings_and_sealed_dates_fail_closed(change: str) -> None:
    data = decoded(mini_frame())
    manifest = manifest_for(data)
    chunk = data[COHORT[0]][0]
    if change == 'stale_hash':
        chunk['rows'][0]['close'] = '999'
    elif change == 'source_hash':
        manifest['symbols'][COHORT[0]]['chunks'][0]['source_sha256'] = 'f' * 64
    elif change == 'instrument':
        manifest['symbols'][COHORT[0]]['instrument_key'] = 'NSE_EQ|INE999999999'
    else:
        if change == 'duplicate':
            chunk['rows'].append(copy.deepcopy(chunk['rows'][0]))
            chunk['row_count'] += 1
        elif change in ('sealed', 'sealed_2026'):
            chunk['rows'][0]['date'] = '2025-01-01' if change == 'sealed' else '2026-01-01'
        elif change == 'bad_price':
            chunk['rows'][0]['open'] = 'NaN'
        elif change == 'bool_volume':
            chunk['rows'][0]['volume'] = True
        elif change == 'bad_timestamp':
            chunk['rows'][0]['provider_timestamp'] = '2023-01-02T15:30:00+05:30'
        rehash(chunk)
        manifest = manifest_for(data)
    with pytest.raises(ValueError, match='^EQUITY_REAL_REPORT_INVALID_INPUT$'):
        report.build_report(data, manifest=manifest)


def test_manifest_missing_name_is_coverage_warning_not_hidden_admission() -> None:
    data = decoded(mini_frame(), COHORT[:2])
    manifest = manifest_for(data)
    del data[COHORT[1]]
    value = report.build_report(data, manifest=manifest)
    assert value['input_binding']['external_manifest_binding_verified'] is False
    assert COHORT[1] in value['dataset_quality']['excluded_names']


def test_unknown_symbol_cannot_expand_pilot() -> None:
    data = decoded(mini_frame())
    data['UNKNOWN'] = data[COHORT[0]]
    with pytest.raises(ValueError, match='^EQUITY_REAL_REPORT_INVALID_INPUT$'):
        report.build_report(data)


def test_render_html_escapes_all_private_payload_and_frames_are_exportable() -> None:
    value = report.build_report(decoded(mini_frame()))
    value['note'] = '</pre><script>bad()</script>&"'
    rendered = report.render_html(value)
    assert '<script>' not in rendered and '&lt;script&gt;' in rendered
    assert 'https://' not in rendered
    frames = report.report_frames(value)
    assert set(frames) == {'summary', 'curves', 'trades'} and len(frames['summary']) == 12


def test_html_summary_formats_percentages_unavailable_and_explicit_cash() -> None:
    value = report.build_report(decoded(mini_frame(), COHORT))
    rendered = report.render_html(value)
    summary = rendered.split('<h2>Complete private report')[0]
    assert '<td>24.70%</td>' in summary
    assert '<td>Cash / no trade</td><td>0.00%</td><td>0.00%</td>' in summary
    assert 'current live UI setting' in summary
    empty = report.render_html(report.build_report({})).split('<h2>Complete private report')[0]
    assert '<td>Unavailable</td>' in empty and '<td>None</td>' not in empty
    assert report._percent(-.15) == '-15.00%'
    assert report._percent(float('nan')) == 'Unavailable'


def test_frozen_cohort_rule_map_and_closed_flags_are_input_independent() -> None:
    empty = report.build_report({})
    populated = report.build_report(decoded(long_frame()))
    design = empty['frozen_design']
    assert design == populated['frozen_design']
    assert empty['frozen_design_sha256'] == populated['frozen_design_sha256'] == report._digest(design)
    assert design['cohort_rule_map'] == {symbol: report.RULE_LABEL for symbol in COHORT}
    assert design['horizon_sessions'] == inspect.signature(report.derive_long_trade_levels).parameters['horizon_days'].default == 15
    assert design['horizon_basis'] == empty['rule']['horizon_basis'] == 'LAB_FREEZE_FROM_DERIVE_LONG_TRADE_LEVELS_DEFAULT_NOT_CURRENT_LIVE_UI_SETTING'
    assert design['cost_scenarios_bps'] == [30, 60, 100]
    for flag in ('post_input_reoptimization', 'data_driven_rule_selection', 'historical_preregistration_verified',
                 'approval_authority', 'training_eligible', 'data_admission_authorised', 'promotion_authorised',
                 'performance_claim_verified', 'out_of_sample_claim', 'full_app_reproduction', 'fill_evidence'):
        assert design[flag] is False
        if flag in populated:
            assert populated[flag] is False


def test_report_is_deterministic_does_not_mutate_and_performs_no_data_io(monkeypatch: pytest.MonkeyPatch) -> None:
    data = decoded(mini_frame(), COHORT)
    before = copy.deepcopy(data)
    first = report.build_report(data)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError('unexpected data I/O')

    monkeypatch.setattr(builtins, 'open', forbidden)
    monkeypatch.setattr(Path, 'open', forbidden)
    monkeypatch.setattr(pd, 'read_parquet', forbidden)
    second = report.build_report(data)
    assert data == before and second == first
    assert first['report_sha256'] == report._digest({key: value for key, value in first.items() if key != 'report_sha256'})
    assert first['network_calls'] == first['file_reads'] == first['writes'] == 0
