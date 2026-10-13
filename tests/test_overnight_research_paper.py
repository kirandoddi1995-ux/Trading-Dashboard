"""Typed synthetic forward observable quote outcome tests."""
from dataclasses import asdict, replace
from typing import Any

import pytest

from overnight_research_dataset import ResearchError, fingerprint
from overnight_research_execution import InstrumentContract, Quote
from overnight_research_paper import PaperIntent, observe_forward_quotes
from tests.test_overnight_research_execution import contract, policy, quote


def arguments() -> dict[str, Any]:
    instrument = contract()
    intent = PaperIntent('a'*64, 'b'*64, 'c'*64, '2022-01-03T09:00:00+05:30',
        '2022-01-03T10:00:00+05:30', '2022-01-03T10:05:00+05:30',
        fingerprint(asdict(instrument)), 50, 'BUY', 1, 5)
    return {'intent': intent, 'contract': instrument,
        'entry': quote('2022-01-03T10:00:01+05:30', '100', '101'),
        'exit': quote('2022-01-03T10:05:00+05:30', '110', '111'),
        'cost_policy': policy(), 'observed_at': '2022-01-03T10:05:01+05:30'}


def test_forward_quote_outcome_is_not_label_or_trade_evidence() -> None:
    result = observe_forward_quotes(**arguments())
    assert result['status'] == 'FORWARD_QUOTE_OUTCOME_CANDIDATE'
    assert result['known_at'] > result['label_end']
    assert result['label'] is None and result['target_before_stop'] is None
    assert not result['paper_run_authorized'] and not result['authenticity_verified']


def test_missing_quote_does_not_become_loss() -> None:
    args = arguments()
    args['exit'] = None
    result = observe_forward_quotes(**args)
    assert result['status'] == 'INSUFFICIENT_FORWARD_OBSERVATIONS'
    assert result['actual_forward_return'] is None


@pytest.mark.parametrize('damage', ['posthoc_protocol', 'predecision_entry', 'early_exit', 'future_receipt', 'wrong_contract'])
def test_forward_chronology_cannot_be_backdated(damage: str) -> None:
    args = arguments()
    intent: PaperIntent = args['intent']
    entry: Quote = args['entry']
    exit_quote: Quote = args['exit']
    instrument: InstrumentContract = args['contract']
    if damage == 'posthoc_protocol':
        args['intent'] = replace(intent, protocol_frozen_at='2022-01-03T10:01:00+05:30')
    elif damage == 'predecision_entry':
        args['entry'] = replace(entry, exchange_at='2022-01-03T10:00:00+05:30')
    elif damage == 'early_exit':
        args['exit'] = replace(exit_quote, exchange_at='2022-01-03T10:04:59+05:30')
    elif damage == 'future_receipt':
        args['exit'] = replace(exit_quote, received_at='2022-01-03T10:05:02+05:30')
    else:
        args['contract'] = replace(instrument, contract_key='other')
    with pytest.raises(ResearchError):
        observe_forward_quotes(**args)
