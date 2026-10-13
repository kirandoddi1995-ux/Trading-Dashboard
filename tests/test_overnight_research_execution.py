"""Typed synthetic quote/cost stress tests; all rates are explicit fixture inputs."""
from dataclasses import asdict, replace
from decimal import Decimal
from typing import Any

import pytest

from overnight_research_dataset import fingerprint
from overnight_research_execution import InstrumentContract, Quote, RiskBudget, RiskReference, margin_risk_gate, round_trip_scenario, summarize_scenarios


def contract(kind: str = 'FUTURE') -> InstrumentContract:
    return InstrumentContract('SYNTHETIC_NIFTY_CONTRACT', kind, 50, '.05',
        '2022-01-01T00:00:00+05:30', '2022-01-27T15:30:00+05:30',
        '2022-01-02T00:00:00+05:30', '2022-01-03T09:15:00+05:30',
        '2022-01-03T15:00:00+05:30', 'https://example.test/SYNTHETIC_DEADLINE',
        'd'*64, '25000' if kind == 'OPTION' else None, 'CE' if kind == 'OPTION' else None)


def policy() -> dict[str, Any]:
    names = ('brokerage_cap', 'brokerage_rate', 'stt_sell', 'stamp_buy', 'exchange', 'ipft', 'sebi', 'gst')
    rates = dict(zip(names, ['20', '.0005', '.0005', '.00002', '.000018299', '.000000001', '.000001', '.18']))
    return {'exchange': 'NSE', 'reviewed': True, 'effective_from': '2022-01-01',
        'effective_to': '2022-01-31', 'reviewed_at': '2021-12-31T00:00:00+05:30',
        'rounding': 'PER_SIDE_PAISE_HALF_UP', 'gst_components': ['brokerage', 'exchange', 'ipft', 'sebi'],
        'sources': dict.fromkeys(names, 'https://example.test/SYNTHETIC_NOT_OFFICIAL'),
        'rates': {'FUTURE': rates, 'OPTION': rates.copy()}}


def quote(at: str, bid: str, ask: str) -> Quote:
    return Quote('SYNTHETIC_NIFTY_CONTRACT', at, at, bid, ask, 100, 100, 'e'*64)


def arguments() -> dict[str, Any]:
    return {'contract': contract(), 'decision_at': '2022-01-03T10:00:00+05:30',
        'entered_at': '2022-01-03T10:00:02+05:30', 'exited_at': '2022-01-03T10:05:00+05:30',
        'entry': quote('2022-01-03T10:00:01+05:30', '100', '101'),
        'exit': quote('2022-01-03T10:04:59+05:30', '110', '111'),
        'quantity': 50, 'side': 'BUY', 'cost_policy': policy(), 'adverse_ticks': 1,
        'max_quote_age_seconds': 5}


def test_bid_ask_stress_and_native_costs() -> None:
    result = round_trip_scenario(**arguments())
    assert result['status'] == 'RESEARCH_QUOTE_SCENARIO'
    assert Decimal(result['entry_price']) == Decimal('101.05')
    assert Decimal(result['exit_price']) == Decimal('109.95')
    assert Decimal(result['gross_pnl']) == Decimal('445')
    assert Decimal(result['net_pnl']) == Decimal('445') - Decimal(result['charges'])
    assert not result['fill_evidence'] and not result['training_eligible']


def test_short_futures_uses_opposite_sides_and_taxes() -> None:
    args = arguments()
    args['side'] = 'SELL'
    result = round_trip_scenario(**args)
    assert result['status'] == 'RESEARCH_QUOTE_SCENARIO'
    assert Decimal(result['entry_price']) == Decimal('99.95')
    assert Decimal(result['exit_price']) == Decimal('111.05')
    assert Decimal(result['cost_details']['entry_charges']['stt']) > 0
    assert Decimal(result['cost_details']['exit_charges']['stamp']) > 0


@pytest.mark.parametrize('missing', ['contract', 'entry', 'exit', 'cost_policy'])
def test_missing_evidence_has_no_fabricated_pnl(missing: str) -> None:
    args = arguments()
    args[missing] = None
    result = round_trip_scenario(**args)
    assert result['status'] == 'INSUFFICIENT_DATA' and result['net_pnl'] is None


@pytest.mark.parametrize('damage', ['depth', 'stale', 'future', 'predecision', 'crossed', 'offtick',
    'wrong_instrument', 'wrong_lot', 'late_exit', 'future_listing', 'index', 'missing_policy',
    'short_option', 'sealed', 'float_tick', 'boolean_quantity'])
def test_bad_execution_inputs_are_not_fills(damage: str) -> None:
    args = arguments()
    entry: Quote = args['entry']
    instrument: InstrumentContract = args['contract']
    if damage == 'depth':
        args['entry'] = replace(entry, ask_quantity=49)
    elif damage == 'stale':
        args['entered_at'] = '2022-01-03T10:00:10+05:30'
    elif damage == 'future':
        args['entry'] = replace(entry, received_at='2022-01-03T10:01:00+05:30')
    elif damage == 'predecision':
        args['entry'] = replace(entry, exchange_at=args['decision_at'])
    elif damage == 'crossed':
        args['entry'] = replace(entry, bid='102')
    elif damage == 'offtick':
        args['entry'] = replace(entry, ask='101.01')
    elif damage == 'wrong_instrument':
        args['entry'] = replace(entry, contract_key='OTHER')
    elif damage == 'wrong_lot':
        args['quantity'] = 49
    elif damage == 'late_exit':
        args['exited_at'] = '2022-01-03T15:01:00+05:30'
    elif damage == 'future_listing':
        args['contract'] = replace(instrument, known_at='2022-01-03T10:01:00+05:30')
    elif damage == 'index':
        args['contract'] = replace(instrument, contract_key='NSE_INDEX|Nifty 50')
    elif damage == 'missing_policy':
        args['cost_policy'] = {}
    elif damage == 'short_option':
        args.update(contract=contract('OPTION'), side='SELL')
    elif damage == 'sealed':
        args['decision_at'] = '2026-01-03T10:00:00+05:30'
    elif damage == 'float_tick':
        args['contract'] = replace(instrument, tick_size=0.05)  # type: ignore[arg-type]
    else:
        args['quantity'] = True
    result = round_trip_scenario(**args)
    assert result['status'] == 'INSUFFICIENT_DATA' and result['net_pnl'] is None and result['reasons']


def test_long_option_identity_and_unknown_denominator() -> None:
    args = arguments()
    args['contract'] = contract('OPTION')
    good = round_trip_scenario(**args)
    args['entry'] = None
    unknown = round_trip_scenario(**args)
    summary = summarize_scenarios([good, unknown])
    assert summary['opportunities'] == 2 and summary['priced_scenarios'] == 1
    assert summary['insufficient_data'] == 1
    assert summarize_scenarios([unknown])['scenario_net_pnl'] is None


def test_prospective_scenario_requires_explicit_scope_and_keeps_risk_missing() -> None:
    args = arguments()
    original: InstrumentContract = args['contract']
    args['contract'] = replace(original,
        session_open='2026-10-13T09:15:00+05:30', exit_deadline='2026-10-13T15:00:00+05:30',
        expires_at='2026-10-29T15:30:00+05:30', data_scope='PROSPECTIVE_VERSIONED')
    for name in ('decision_at', 'entered_at', 'exited_at'):
        args[name] = args[name].replace('2022-01-03', '2026-10-13')
    for name in ('entry', 'exit'):
        original_quote: Quote = args[name]
        args[name] = replace(original_quote,
            exchange_at=original_quote.exchange_at.replace('2022-01-03', '2026-10-13'),
            received_at=original_quote.received_at.replace('2022-01-03', '2026-10-13'))
    args['cost_policy'].update(effective_from='2026-10-01', effective_to='2026-10-31')
    result = round_trip_scenario(**args)
    assert result['status'] == 'RESEARCH_QUOTE_SCENARIO'
    assert result['risk_status'] == 'INSUFFICIENT_DATA' and not result['margin_is_maximum_loss']
    assert not result['full_execution_engine']
    args['contract'] = replace(args['contract'], data_scope='DEVELOPMENT_ONLY')
    assert round_trip_scenario(**args)['status'] == 'INSUFFICIENT_DATA'


def test_cost_policy_must_be_known_before_decision_and_no_expiry_entries() -> None:
    args = arguments()
    args['cost_policy']['reviewed_at'] = '2022-01-03T10:00:01+05:30'
    result = round_trip_scenario(**args)
    assert result['reasons'] == ['COST_POLICY_NOT_AVAILABLE_AT_DECISION']
    args = arguments()
    args['contract'] = replace(args['contract'], expires_at='2022-01-03T15:30:00+05:30')
    assert round_trip_scenario(**args)['reasons'] == ['EXPIRY_DAY_ENTRY_UNSUPPORTED']


def risk_arguments() -> dict[str, Any]:
    instrument = contract()
    reference = RiskReference(fingerprint(asdict(instrument)), 'a'*64, 'b'*64,
        '2022-01-03T09:59:00+05:30', '2022-01-03T09:15:00+05:30',
        '2022-01-03T15:00:00+05:30', '5000', 50, '2000',
        'https://example.test/SYNTHETIC_MARGIN_STRESS', True)
    budget = RiskBudget('10000', '1000', '5000', '1000', '500', '2500',
                        '2022-01-03T09:00:00+05:30', 'c'*64)
    return {'contract': instrument, 'quote': quote('2022-01-03T09:59:59+05:30', '100', '101'),
        'reference': reference, 'budget': budget, 'decision_at': '2022-01-03T10:00:00+05:30',
        'quantity': 50, 'basket_sha256': 'a'*64}


def test_pure_risk_checks_cash_daily_loss_and_margin_is_not_max_loss() -> None:
    result = margin_risk_gate(**risk_arguments())
    assert result['status'] == 'DECLARED_RISK_REFERENCE_CHECK_PASSED'
    assert result['cash_after_margin_and_buffer'] == '4000'
    assert result['daily_loss_capacity_after_stress'] == '1500'
    assert not result['margin_is_maximum_loss'] and not result['approval_authority']
    assert not result['risk_capacity_verified'] and result['declared_capacity_satisfies_inputs']


@pytest.mark.parametrize('damage', ['missing', 'unverified', 'cash', 'daily_loss', 'trade_loss',
    'zero_price', 'wrong_quantity', 'future_reference', 'stale_reference', 'intraday_roll', 'wrong_basket'])
def test_risk_missing_or_invalid_evidence_blocks(damage: str) -> None:
    args = risk_arguments()
    reference: RiskReference = args['reference']
    budget: RiskBudget = args['budget']
    if damage == 'missing':
        args['reference'] = None
    elif damage == 'unverified':
        args['reference'] = replace(reference, independently_verified=False)
    elif damage == 'cash':
        args['budget'] = replace(budget, available_cash='5500')
    elif damage == 'daily_loss':
        args['budget'] = replace(budget, realized_loss_today='3000')
    elif damage == 'trade_loss':
        args['budget'] = replace(budget, maximum_trade_stress_loss='1000')
    elif damage == 'zero_price':
        args['quote'] = replace(args['quote'], bid='0')
    elif damage == 'wrong_quantity':
        args['quantity'] = 49
    elif damage == 'future_reference':
        args['reference'] = replace(reference, known_at='2022-01-03T10:01:00+05:30')
    elif damage == 'stale_reference':
        args['reference'] = replace(reference, effective_to='2022-01-03T09:59:00+05:30')
    elif damage == 'intraday_roll':
        args['planned_roll_at'] = '2022-01-03T12:00:00+05:30'
    else:
        args['basket_sha256'] = 'd'*64
    result = margin_risk_gate(**args)
    assert result['status'] == 'BLOCKED' and result['reasons']


def test_risk_rejects_expiry_day_and_any_roll_plan() -> None:
    args = risk_arguments()
    args['planned_roll_at'] = args['contract'].session_open
    assert margin_risk_gate(**args)['reasons'] == ['INTRADAY_ROLL_UNSUPPORTED']
    args = risk_arguments()
    args['contract'] = replace(args['contract'], expires_at='2022-01-03T15:30:00+05:30')
    args['reference'] = replace(args['reference'], contract_sha256=fingerprint(asdict(args['contract'])))
    assert margin_risk_gate(**args)['reasons'] == ['EXPIRY_DAY_ENTRY_UNSUPPORTED']
