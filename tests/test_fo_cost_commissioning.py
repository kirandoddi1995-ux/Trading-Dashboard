from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
import json

import pytest

from fo_cost_commissioning import COMPONENTS, commissioned_scenario, main, select
from intraday_fo_costs import CostEvidenceError

NOW = datetime.fromisoformat('2026-10-05T10:00:00+05:30')


def record(value='0', **changes):
    result = {'effective_from': '2022-01-01', 'effective_to': '2024-12-31',
              'published_on': '2021-12-01', 'reviewed_at': NOW.isoformat(), 'status': 'VERIFIED',
              'source_url': 'https://example.test/SYNTHETIC_NOT_OFFICIAL',
              'evidence_sha256': 'a' * 64, 'basis': 'FRACTION_OF_TURNOVER', 'value': value}
    result.update(changes)
    return result


def arguments():
    fees = {name: [record()] for name in COMPONENTS}
    fees['brokerage'] = [record('20', basis='FLAT_PER_ORDER', status='ASSUMED',
                                assumption='Unconfirmed personal broker plan')]
    fees['stt_sell'] = [record('.0001')]
    fees['gst'] = [record('.18', basis='FRACTION_OF_TAXABLE_FEES',
                           taxable_components=['brokerage', 'exchange', 'ipft', 'sebi'])]
    return {'ledger': {'exchange': 'NSE', 'segment': 'FUTURE',
                       'rounding': 'PER_SIDE_PAISE_HALF_UP',
                       'gst_components': ['brokerage', 'exchange', 'ipft', 'sebi'], 'components': fees},
            'terms': [record(contract_key='NSE_FO|TEST|27-01-2022', lot_size=50,
                             exchange='NSE', segment='FUTURE', underlying_key='NSE_INDEX|Nifty 50',
                             expiry='2022-01-27')], 'contract_key': 'NSE_FO|TEST|27-01-2022',
            'entry': '100', 'exit': '110', 'lots': 1, 'entry_side': 'BUY',
            'entered_at': datetime.fromisoformat('2022-01-03T10:00:00+05:30'),
            'exited_at': datetime.fromisoformat('2022-01-03T14:00:00+05:30'), 'review_as_of': NOW}


def test_assumed_brokerage_decimal_cost_and_retrospective_review_not_backdated():
    args = arguments()
    original = deepcopy(args)
    result = commissioned_scenario(**args)
    assert args == original
    assert result['status'] == 'ASSUMPTION_ONLY'
    assert not result['cost_policy_commissioned'] and not result['approval_authority']
    assert not result['fill_evidence']
    assert result['charges'] == Decimal('47.75')
    assert result['gross_scenario_pnl'] == Decimal('500')
    assert result['net_scenario_pnl'] == Decimal('452.25')
    assert result['assumed_components'] == ['brokerage']
    assert len(result['provenance_sha256']) == 64


def test_short_taxes_use_entry_sell_turnover_and_stamps_exit_buy():
    args = arguments()
    args['entry_side'] = 'SELL'
    args['ledger']['components']['stamp_buy'][0]['value'] = '.00002'
    result = commissioned_scenario(**args)
    assert result['entry_charges']['stt'] == Decimal('.50')
    assert result['exit_charges']['stt'] == 0
    assert result['exit_charges']['stamp'] == Decimal('.11')
    assert result['gross_scenario_pnl'] == Decimal('-500')


def test_lot_change_changes_quantity_and_fixed_brokerage_percentage():
    args = arguments()
    first = commissioned_scenario(**args)
    args['terms'][0]['lot_size'] = 25
    second = commissioned_scenario(**args)
    assert first['quantity'] == 50 and second['quantity'] == 25
    assert first['entry_charges']['brokerage'] == second['entry_charges']['brokerage'] == Decimal('20')
    assert first['provenance_sha256'] != second['provenance_sha256']


def test_independent_component_effective_dates_and_overlap_fail_closed():
    assert select([record('1', effective_to='2023-03-31'),
                   record('2', effective_from='2023-04-01')], date(2023, 4, 1), NOW)['value'] == '2'
    with pytest.raises(CostEvidenceError, match='OVERLAPPING'):
        select([record(), record()], date(2022, 1, 3), NOW)
    with pytest.raises(CostEvidenceError, match='DATED_EVIDENCE_MISSING'):
        select([], date(2022, 1, 3), NOW)


@pytest.mark.parametrize('problem', ['missing_fee', 'missing_lot', 'float', 'publication',
                                   'future_review', 'source', 'unreviewed', 'expiry', 'gst', 'wrong_contract'])
def test_missing_or_inconsistent_commissioning_blocks(problem):
    args = arguments()
    records = args['ledger']['components']
    if problem == 'missing_fee':
        del records['exchange']
    elif problem == 'missing_lot':
        del args['terms'][0]['lot_size']
    elif problem == 'float':
        args['entry'] = 100.0
    elif problem == 'publication':
        records['stt_sell'][0]['published_on'] = '2026-01-01'
    elif problem == 'future_review':
        records['stt_sell'][0]['reviewed_at'] = '2027-01-01T00:00:00+00:00'
    elif problem == 'source':
        records['stt_sell'][0]['evidence_sha256'] = None
    elif problem == 'unreviewed':
        records['stt_sell'][0]['status'] = 'UNREVIEWED'
    elif problem == 'expiry':
        args['terms'][0]['expiry'] = '2022-01-03'
    elif problem == 'gst':
        args['ledger']['components']['gst'][0]['taxable_components'] = ['unknown_fee']
    else:
        args['contract_key'] = 'unknown'
    with pytest.raises(CostEvidenceError):
        commissioned_scenario(**args)


def test_cap_and_turnover_brokerage_exactly_and_verified_still_not_live():
    args = arguments()
    args['ledger']['components']['brokerage'] = [record('20', basis='MIN_CAP_TURNOVER', turnover_rate='.0005')]
    result = commissioned_scenario(**args)
    assert result['entry_charges']['brokerage'] == Decimal('2.50')
    assert result['status'] == 'REVIEWED_RESEARCH_ONLY'
    assert result['cost_policy_commissioned'] and not result['approval_authority']


def test_cli_scenario_outputs_exact_money_and_safe_missing_input(tmp_path, capsys):
    args = arguments()
    trade = {key: args[key] for key in ('contract_key', 'entry', 'exit', 'lots', 'entry_side')}
    trade.update(entered_at=args['entered_at'].isoformat(), exited_at=args['exited_at'].isoformat())
    paths = []
    for name, body in [('ledger', args['ledger']), ('terms', args['terms']), ('trade', trade)]:
        path = tmp_path / (name + '.json')
        path.write_text(json.dumps(body), encoding='utf-8')
        paths.extend(['--' + name, str(path)])
    assert main(paths + ['--review-as-of', NOW.isoformat()]) == 0
    output = capsys.readouterr().out
    assert str(tmp_path) not in output
    assert json.loads(output)['charges'] == '47.75'
    (tmp_path / 'ledger.json').unlink()
    assert main(paths + ['--review-as-of', NOW.isoformat()]) == 2
    assert json.loads(capsys.readouterr().out)['code'] == 'INVALID_LOCAL_INPUT'


def test_unreviewed_other_period_does_not_block_selected_verified_period():
    current = record(effective_to='2023-03-31')
    future = record(effective_from='2023-04-01', status='UNREVIEWED')
    assert select([current, future], date(2022, 1, 3), NOW) == current
    with pytest.raises(CostEvidenceError, match='UNVERIFIED'):
        select([current, future], date(2023, 4, 1), NOW)


def test_committed_template_does_not_silently_commission_known_or_missing_values():
    from pathlib import Path
    template = json.loads((Path(__file__).resolve().parents[1] / 'fo_costs_review_template.json').read_text())
    args = arguments()
    args['ledger'] = template
    with pytest.raises(CostEvidenceError, match='UNVERIFIED'):
        commissioned_scenario(**args)


def test_dated_gst_base_changes_without_changing_other_component_rates():
    args = arguments()
    args['ledger']['components']['sebi'] = [record('.0001')]
    with_sebi = commissioned_scenario(**args)
    args['ledger']['components']['gst'][0]['taxable_components'] = ['brokerage', 'exchange', 'ipft']
    without_sebi = commissioned_scenario(**args)
    assert with_sebi['provenance_sha256'] != without_sebi['provenance_sha256']
    assert with_sebi['charges'] > without_sebi['charges']


def test_percentage_units_cannot_be_supplied_as_fractional_gst_rate():
    args = arguments()
    args['ledger']['components']['gst'][0]['value'] = '18'
    with pytest.raises(CostEvidenceError, match='FRACTIONAL_RATE'):
        commissioned_scenario(**args)
