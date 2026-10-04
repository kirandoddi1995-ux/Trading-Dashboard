from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from intraday_fo_costs import CostEvidenceError, fresh_margin, margin_response, round_trip


def policy():
    names = ('brokerage_cap', 'brokerage_rate', 'stt_sell', 'stamp_buy', 'exchange', 'ipft', 'sebi', 'gst')
    return {'exchange': 'NSE', 'reviewed': True, 'effective_from': '2026-10-01',
        'effective_to': '2026-10-31', 'reviewed_at': '2026-09-30T00:00:00+05:30',
        'rounding': 'PER_SIDE_PAISE_HALF_UP', 'gst_components': ['brokerage', 'exchange', 'ipft', 'sebi'],
        'sources': dict.fromkeys(names, 'https://example.test/SYNTHETIC_NOT_OFFICIAL'),
        'rates': {'OPTION': dict(zip(names, ['20', '0', '.0015', '.00003', '.000355299', '.000000001', '.000001', '.18'])),
                  'FUTURE': dict(zip(names, ['20', '.0005', '.0005', '.00002', '.000018299', '.000000001', '.000001', '.18']))}}


def scenario(**changes):
    args = dict(entry='100', exit='110', quantity=50, lot_size=50, kind='OPTION', policy=policy(),
        entered_at=datetime.fromisoformat('2026-10-01T10:00:00+05:30'),
        exited_at=datetime.fromisoformat('2026-10-01T14:00:00+05:30'),
        exit_deadline=datetime.fromisoformat('2026-10-01T15:00:00+05:30'),
        deadline_source='https://example.test/SYNTHETIC_BROKER_DEADLINE')
    args.update(changes)
    return round_trip(**args)


def test_exact_cost_components_and_no_authority():
    result = scenario()
    assert result['gross_pnl'] == Decimal('500')
    assert result['charges'] == Decimal('60.02')
    assert result['net_pnl'] == Decimal('439.98')
    assert result['entry_charges']['stt'] == 0
    assert result['exit_charges']['stamp'] == 0
    assert result['approval_authority'] is False
    assert isinstance(result['net_pnl'], Decimal)


@pytest.mark.parametrize('changes', [{'entry': 100.0}, {'quantity': 49}, {'entry_orders': True},
    {'exit_deadline': datetime.fromisoformat('2026-10-01T12:00:00+05:30')},
    {'kind': 'STOCK'}, {'policy': {}}, {'deadline_source': ''}])
def test_invalid_or_uncommissioned_blocks(changes):
    with pytest.raises(CostEvidenceError):
        scenario(**changes)


def test_historical_policy_not_backapplied():
    p = policy()
    p['effective_from'] = '2026-10-02'
    with pytest.raises(CostEvidenceError):
        scenario(policy=p)


def test_multiple_option_orders_cost_more_not_partial_fill_count():
    assert scenario(entry_orders=2)['charges'] > scenario()['charges']
    with pytest.raises(CostEvidenceError):
        scenario(kind='FUTURE', entry_orders=2)


def test_short_futures_sell_tax_on_entry_buy_stamp_on_exit():
    result = scenario(kind='FUTURE', entry_side='SELL')
    assert result['gross_pnl'] == Decimal('-500')
    assert result['entry_charges']['stt'] > 0
    assert result['entry_charges']['stamp'] == 0
    assert result['exit_charges']['stt'] == 0
    assert result['exit_charges']['stamp'] > 0
    with pytest.raises(CostEvidenceError):
        scenario(entry_side='SELL')  # short options intentionally unsupported


def test_futures_card_requires_tariff_and_discards_generic_fee_components():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
    gate = next(line for line in source.splitlines() if 'if not futures_foundation.eligible or fut_bias' in line)
    assert 'or futures_tariff is None' in gate
    assert 'statutory_bps=float(futures_tariff["charges"] - tariff_brokerage)' in source
    assert 'brokerage_bps=float(tariff_brokerage)' in source


def test_required_not_final_margin_and_zero_is_preserved():
    body = {'status': 'success', 'data': {'required_margin': 100, 'final_margin': 0, 'margins': [{}]}}
    assert margin_response(body)['required_margin'] == Decimal('100')
    assert margin_response(body)['final_margin'] == 0
    now = datetime.fromisoformat('2026-10-01T10:00:00+05:30')
    assert fresh_margin(body, requested_at=now, now=now, request_basket=['a'], response_basket=['a'])
    with pytest.raises(CostEvidenceError):
        fresh_margin(body, requested_at=now, now=now + timedelta(seconds=31), request_basket=['a'], response_basket=['a'])
    with pytest.raises(CostEvidenceError):
        fresh_margin(body, requested_at=now, now=now, request_basket=['a'], response_basket=['b'])


@pytest.mark.parametrize('value', [None, True, -1, 'NaN', 'Infinity'])
def test_margin_missing_invalid_never_defaults(value):
    with pytest.raises(CostEvidenceError):
        margin_response({'status': 'success', 'data': {'required_margin': value, 'final_margin': 1, 'margins': [{}]}})


@pytest.mark.parametrize('segment', [None, [], 'invalid', 123, True])
def test_malformed_tariff_segment_rejects_without_unhandled_attribute_error(segment):
    p = policy()
    p['rates']['OPTION'] = segment
    with pytest.raises(CostEvidenceError, match='DATED_COST_POLICY_MISSING'):
        scenario(policy=p)


@pytest.mark.parametrize('changes', [
    {'requested_at': None}, {'now': 'not a timestamp'},
    {'max_age_seconds': True}, {'max_age_seconds': float('nan')},
    {'max_age_seconds': float('inf')}, {'max_age_seconds': '30'},
])
def test_invalid_margin_freshness_arguments_fail_closed(changes):
    now = datetime.fromisoformat('2026-10-01T10:00:00+05:30')
    args = dict(requested_at=now, now=now, request_basket=['a'], response_basket=['a'])
    args.update(changes)
    with pytest.raises(CostEvidenceError, match='MARGIN_REQUEST_UNVERIFIED'):
        fresh_margin({}, **args)
