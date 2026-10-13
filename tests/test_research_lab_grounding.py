"""Untrusted model responses cannot introduce claims, numbers or actions."""
import json
from typing import Any, cast

import pytest

from overnight_research_dataset import ResearchError
from research_lab_grounding import FACTS, SELECTOR_FORMAT, grounded_explanation


def reply(prompt: str) -> str:
    payload = json.loads(prompt)
    return json.dumps({'format': SELECTOR_FORMAT, 'catalog_sha256': payload['catalog_sha256'],
        'fact_ids': ['missing_execution', 'no_authority']})


def test_default_no_model_and_fixed_evidence() -> None:
    def denied(prompt: str) -> str:
        raise AssertionError('uncommissioned model was called')
    result = cast(dict[str, Any], grounded_explanation(selector=denied))
    assert result['status'] == 'DETERMINISTIC_EVIDENCE_SUMMARY_LLM_DISABLED'
    assert len(result['facts']) == len(FACTS)
    assert result['numeric_generation'] is False


def test_local_selector_cannot_generate_prose() -> None:
    result = cast(dict[str, Any], grounded_explanation(selector=reply, commissioned=True))
    assert result['status'] == 'LOCAL_LLM_FACT_SELECTION_VALIDATED'
    assert [f['id'] for f in result['facts']] == ['missing_execution', 'no_authority']
    assert result['approval_authority'] is False


@pytest.mark.parametrize('change', [{'format': 'wrong'}, {'catalog_sha256': 'a'*64},
    {'fact_ids': ['no_authority', 'trade_now']}, {'fact_ids': ['no_authority'] * 2},
    {'fact_ids': ['small_sample']}, {'fact_ids': []}, {'fact_ids': 'no_authority'},
    {'fact_ids': [1]}, {'profit': 'Guaranteed 90 percent'}, {'tool_call': 'place_order'}])
def test_adversarial_schema(change: dict[str, Any]) -> None:
    def malicious(prompt: str) -> str:
        body = json.loads(reply(prompt))
        body.update(change)
        return json.dumps(body)
    result = grounded_explanation(selector=malicious, commissioned=True)
    assert result['code'] == 'LLM_GROUNDING_FAILED' and result['facts'] == []


@pytest.mark.parametrize('response', ['{"format":"x","format":"y"}', 'NaN', '[]', 'not json', 'x'*4097])
def test_malformed_model_output(response: str) -> None:
    assert grounded_explanation(selector=lambda _: response, commissioned=True)['status'] == 'BLOCKED'


def test_failure_redaction_and_missing_backend() -> None:
    def failed(prompt: str) -> str:
        raise RuntimeError('SECRET_TOKEN and private source')
    result = grounded_explanation(selector=failed, commissioned=True)
    assert 'SECRET' not in json.dumps(result)
    with pytest.raises(ResearchError, match='LOCAL_LLM_BACKEND_NOT_CONFIGURED'):
        grounded_explanation(commissioned=True)
