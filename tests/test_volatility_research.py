"""Synthetic numerical tests are software evidence, never market validation."""
import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from volatility_research import (
    Valuation, ResearchError, analyze_bundle, constant_tenor, event_scenario,
    greek_consistency, history_statistics, realized_volatility, strike_feasibility,
)

NOW = datetime(2026, 9, 29, 6, tzinfo=timezone.utc)
CONVENTIONS = dict(model='BSM_SPOT', iv='DECIMAL', theta='CALENDAR_DAY',
                   vega='VOL_POINT', quantity='PER_UNIT', day_count='ACT365F')


def bundle():
    data = dict(schema_version=1, underlying='SYNTHETIC', source='TEST_ONLY', snapshot_id='fixture',
                convention_version='fixture-v1', as_of=NOW.isoformat(), max_age_seconds=5,
                max_skew_seconds=2, provider_conventions=CONVENTIONS,
                tolerances={k: [1e-8, 1e-6] for k in ('delta', 'gamma', 'theta', 'vega')}, slices=[])
    for days in (20, 40):
        sl = dict(expiry_at=(NOW+timedelta(days=days)).isoformat(), exercise='EUROPEAN',
                  spot=100, rate=.04, dividend_yield=.01, reference_at=NOW.isoformat(),
                  carry_source='SYNTHETIC', adjustment_version='fixture-v1', contracts=[])
        for strike in np.linspace(85, 115, 13):
            for kind in ('CE', 'PE'):
                v = Valuation(100, float(strike), days/365, .04, .01, kind)
                price = v.price(.3)
                sl['contracts'].append(dict(instrument_key=f'{days}|{strike}|{kind}',
                    contract_version='fixture-v1', strike=float(strike), kind=kind,
                    source_at=NOW.isoformat(), available_at=NOW.isoformat(),
                    bid=price*.999, ask=price*1.001, bid_size=100, ask_size=100,
                    provider=dict(iv=.3, **v.greeks(.3))))
        data['slices'].append(sl)
    return data


@pytest.fixture(scope='module')
def report():
    return analyze_bundle(bundle())


@pytest.mark.parametrize('kind', ['CE', 'PE'])
def test_higher_greeks_match_independent_finite_differences(kind):
    v = Valuation(102, 100, .2, .04, .015, kind)
    sigma, h, ds, dt = .27, 1e-4, .001, 1e-5
    g = v.greeks(sigma)
    assert v.solve(v.price(sigma)) == pytest.approx(sigma, abs=1e-10)
    assert g['volga'] == pytest.approx((v.price(sigma+h)-2*v.price(sigma)+v.price(sigma-h))/h**2/10000, abs=1e-7)
    hi = Valuation(102+ds, 100, .2, .04, .015, kind)
    lo = Valuation(102-ds, 100, .2, .04, .015, kind)
    cross = (hi.price(sigma+h)-hi.price(sigma-h)-lo.price(sigma+h)+lo.price(sigma-h))/(4*ds*h)/100
    assert g['vanna'] == pytest.approx(cross, abs=1e-8)
    earlier = Valuation(102, 100, .2+dt, .04, .015, kind)
    later = Valuation(102, 100, .2-dt, .04, .015, kind)
    assert g['charm'] == pytest.approx((later.greeks(sigma)['delta']-earlier.greeks(sigma)['delta'])/(2*dt*365), rel=1e-6)


def test_flat_smile_term_delta_and_non_authorization(report):
    assert report['mode'] == 'RESEARCH_ONLY' and report['approval_eligible'] is False
    for sl in report['slices']:
        assert sl['smile']['status'] == 'RESEARCH_FIT'
        assert sl['books'] == 'FEASIBLE_OBSERVED_BOOKS'
        assert max(abs(x['iv']-.3) for x in sl['smile']['grid']) < .002
        for value in sl['same_delta'].values():
            assert value['status'] == 'RESEARCH_ESTIMATE'
            assert value['iv'] == pytest.approx(.3, abs=.002)
        assert all(r['consistency']['status'] == 'CONSISTENT' for r in sl['contracts'])
    assert report['calendar_diagnostics'][0]['status'] == 'NO_SAMPLED_DECREASE'
    assert constant_tenor(report['slices'], 30)['iv'] == pytest.approx(.3, abs=.002)
    assert constant_tenor(report['slices'], 60)['status'] == 'INSUFFICIENT_EXPIRY_COVERAGE'


@pytest.mark.parametrize('mutation', ['unit', 'missing', 'mismatch', 'missing_tolerance'])
def test_comparator_never_approves_or_fills_missing(mutation):
    v = Valuation(100, 100, .1, .04, .01, 'CE')
    provider, conventions = dict(iv=.3, **v.greeks(.3)), dict(CONVENTIONS)
    tolerance = {k: [1e-8, 1e-6] for k in ('delta', 'gamma', 'theta', 'vega')}
    if mutation == 'unit':
        conventions['iv'] = 'PERCENT'
    if mutation == 'missing':
        provider['gamma'] = None
    if mutation == 'mismatch':
        provider['delta'] += .2
    if mutation == 'missing_tolerance':
        tolerance = {}
    result = greek_consistency(v, v.price(.29), v.price(.31), provider, conventions, tolerance)
    assert result['status'] != 'CONSISTENT'
    assert result['approval_eligible'] is False


@pytest.mark.parametrize('field,value', [('rate', None), ('dividend_yield', None), ('spot', float('nan')),
                                       ('years', 0), ('kind', 'FUT')])
def test_no_pricing_defaults(field, value):
    spec = dict(spot=100, strike=100, years=.1, rate=.04, dividend_yield=0, kind='CE')
    spec[field] = value
    with pytest.raises(ResearchError):
        Valuation(**spec)


@pytest.mark.parametrize('mutation', ['stale', 'crossed', 'duplicate', 'adjustment', 'future', 'unaware'])
def test_bad_bundles_fail_closed(mutation):
    data = bundle()
    row = data['slices'][0]['contracts'][0]
    if mutation == 'stale':
        row['source_at'] = (NOW-timedelta(seconds=20)).isoformat()
    elif mutation == 'crossed':
        row['bid'] = row['ask']+1
    elif mutation == 'duplicate':
        data['slices'][0]['contracts'].append(deepcopy(row))
    elif mutation == 'adjustment':
        data['slices'][0]['adjustment_version'] = ''
    elif mutation == 'future':
        row['available_at'] = (NOW+timedelta(seconds=1)).isoformat()
    else:
        row['source_at'] = '2026-09-29T06:00:00'
    with pytest.raises(ValueError):
        analyze_bundle(data)


def test_book_parity_and_convexity_reject_conflicts():
    v = Valuation(100, 100, .1, 0, 0, 'CE')
    rows = [dict(strike=100, kind='CE', bid=10, ask=11), dict(strike=100, kind='PE', bid=1, ask=2)]
    assert strike_feasibility(rows, v) == 'INFEASIBLE_BOOKS'
    rows = [dict(strike=k, kind='CE', bid=p, ask=p+.01) for k, p in [(90, 15), (100, 14), (110, 1)]]
    assert strike_feasibility(rows, v) == 'INFEASIBLE_OR_SOLVER_FAILED'


def test_sparse_smile_is_not_filled():
    data = bundle()
    data['slices'][0]['contracts'] = data['slices'][0]['contracts'][10:16]
    result = analyze_bundle(data)
    assert result['slices'][0]['smile']['status'] == 'INSUFFICIENT_STRIKES'
    assert result['calendar_diagnostics'][0]['status'] == 'UNAVAILABLE'


def test_impossible_price_not_replaced():
    v = Valuation(100, 100, .1, 0, 0, 'CE')
    with pytest.raises(ResearchError):
        v.solve(110)


def test_negative_calendar_is_diagnostic_not_suppressed(report):
    slices = deepcopy(report['slices'])
    slices[1]['smile']['parameters'] = [1e-5, 0, 0, 0, .1]
    assert constant_tenor(slices, 30)['status'] == 'NEGATIVE_FORWARD_VARIANCE'


def historical_rows(n):
    return [dict(series_key='series', session_date=(NOW-timedelta(days=n-i)).date().isoformat(),
                 observed_at=(NOW-timedelta(days=n-i)).isoformat(),
                 available_at=(NOW-timedelta(days=n-i)).isoformat(), iv=.2+i*.001) for i in range(n)]


def test_history_no_lookahead_or_cross_series():
    rows = historical_rows(4)
    rows += [dict(rows[0], series_key='other', iv=9),
             dict(rows[0], available_at=(NOW+timedelta(days=1)).isoformat(), iv=8)]
    stat = history_statistics(rows, current_iv=.2015, series_key='series', as_of=NOW, lookback=4)
    assert stat['iv_rank'] == pytest.approx(50)
    assert stat['iv_percentile'] == 50
    assert history_statistics(rows, current_iv=.2, series_key='series', as_of=NOW)['status'] == 'INSUFFICIENT_HISTORY'
    with pytest.raises(ResearchError):
        history_statistics(rows+[rows[0]], current_iv=.2, series_key='series', as_of=NOW)


def test_flat_history_rank_unavailable():
    rows = [dict(r, iv=.2) for r in historical_rows(4)]
    result = history_statistics(rows, current_iv=.2, series_key='series', as_of=NOW, lookback=4)
    assert result['iv_rank'] is None and result['iv_percentile'] == 0


def test_realized_requires_complete_adjusted_history():
    sessions = ['2026-09-23', '2026-09-24', '2026-09-25']
    rows = [dict(session_date=d, close=c, available_at=d+'T16:00:00+05:30', adjustment_version='v1')
            for d, c in zip(sessions, [100, 102, 101])]
    args = dict(sessions=sessions, as_of=NOW, adjustment_version='v1')
    assert realized_volatility(rows, **args)['realized_iv'] == pytest.approx(np.std(np.diff(np.log([100, 102, 101])), ddof=1)*np.sqrt(252))
    assert realized_volatility(rows[:-1], **args)['status'] == 'INSUFFICIENT_HISTORY'
    with pytest.raises(ResearchError):
        realized_volatility([dict(rows[0], adjustment_version='old'), *rows[1:]], **args)


def test_event_scenarios_are_not_predictions_or_fills():
    v = Valuation(100, 100, .1, 0, 0, 'CE')
    args = dict(spot_return=0, iv_change_points=-5, elapsed_days=1, signed_units=10)
    result = event_scenario(v, .3, **args)
    assert result['status'] == 'HYPOTHETICAL' and result['gross_pnl'] < 0
    assert 'fills' in result['excludes']
    with pytest.raises(ResearchError):
        event_scenario(v, .3, **dict(args, iv_change_points=-40))


def test_research_has_no_authorization_or_persistence_wiring():
    root = Path(__file__).resolve().parents[1]
    for file in ('volatility_research.py', 'volatility_research_ui.py'):
        tree = ast.parse((root/file).read_text(encoding='utf-8'))
        imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not imports.intersection({'derivative_preflight', 'model_registry', 'production_repository', 'live_governance'})
        assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in {'open', 'eval', 'exec'} for n in ast.walk(tree))
    app = (root/'app.py').read_text(encoding='utf-8')
    tree = ast.parse(app)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'render_volatility_research']
    assert len(calls) == 1
    assert any(isinstance(n, ast.Expr) and n.value is calls[0] for n in ast.walk(tree))
    assert '_call_validation' not in app and '_put_validation' not in app
    assert '"valid": bool(surface_row["production_valid"])' not in app
    preflight = (root/'derivative_preflight.py').read_text()
    assert 'OPTION_COMPARISON_HOLD' in preflight
    assert 'volatility_research' not in (root/'derivative_preflight.py').read_text()


def test_ui_does_not_return_report_or_render_input_errors():
    from volatility_research_ui import render_volatility_research

    class UI:
        def expander(self, *args):
            return self
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def caption(self, *args):
            pass
        def file_uploader(self, *args, **kwargs):
            return type('Upload', (), {'size': 10, 'getvalue': lambda self: b'{secret-credential'})()
        def button(self, *args, **kwargs):
            return True
        def error(self, message):
            assert 'secret-credential' not in message

    assert render_volatility_research(UI()) is None
