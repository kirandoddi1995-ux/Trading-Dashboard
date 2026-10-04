from datetime import date, datetime
from decimal import Decimal

import pytest

from intraday_fo_costs import CostEvidenceError
from nifty_futures_research_contract import POLICY, adverse_reference_price, select_contract

DATES = ['2024-01-22', '2024-01-23', '2024-01-24', '2024-01-25',
         '2024-02-26', '2024-02-27', '2024-02-28', '2024-02-29']
CONTRACTS = [{'contract_key': key, 'expiry': expiry, 'listed_at': '2023-12-01T00:00:00+05:30'}
             for key, expiry in [('JAN', '2024-01-25'), ('FEB', '2024-02-29')]]


def select(day, contracts=CONTRACTS, dates=DATES):
    return select_contract(date.fromisoformat(day), contracts, dates,
                           decision_at=datetime.fromisoformat(day + 'T09:15:00+05:30'))


def test_roll_two_actual_sessions_before_expiry_not_calendar_days():
    assert select('2024-01-22')['contract_key'] == 'JAN'
    assert select('2024-01-23')['contract_key'] == 'FEB'
    assert select('2024-01-25')['contract_key'] == 'FEB'
    assert POLICY['approval_authority'] is False and POLICY['fill_evidence'] is False


def test_missing_next_contract_has_no_fallback_to_expiring_contract():
    with pytest.raises(CostEvidenceError, match='NO_FALLBACK'):
        select('2024-01-23', CONTRACTS[:1])


def test_future_listing_cannot_be_selected_and_missing_calendar_blocks():
    contracts = [dict(CONTRACTS[1], listed_at='2024-02-01T00:00:00+05:30')]
    with pytest.raises(CostEvidenceError):
        select('2024-01-23', contracts)
    with pytest.raises(CostEvidenceError, match='CALENDAR'):
        select('2024-01-23', dates=DATES[:-1])


def test_adverse_ticks_direction_grid_and_no_unregistered_sweeps():
    assert adverse_reference_price('100.01', '.05', side='BUY', ticks=1) == Decimal('100.10')
    assert adverse_reference_price('100.01', '.05', side='SELL', ticks=1) == Decimal('99.95')
    with pytest.raises(CostEvidenceError):
        adverse_reference_price('100', '.05', side='BUY', ticks=3)
    with pytest.raises(CostEvidenceError):
        adverse_reference_price('100', '.05', side='BUY', ticks=True)


def test_invalid_calendar_inventory_and_ambiguous_contract_block():
    with pytest.raises(CostEvidenceError):
        select('2024-01-23', dates=['not-a-date'])
    with pytest.raises(CostEvidenceError):
        select('2024-01-23', contracts=[None])
    with pytest.raises(CostEvidenceError, match='AMBIGUOUS'):
        select('2024-01-22', contracts=CONTRACTS + [dict(CONTRACTS[0], contract_key='OTHERJAN')])
