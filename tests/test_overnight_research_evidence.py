"""Report completeness is not licensing approval or paper activation."""
from dataclasses import replace
import hashlib
from typing import Any

import pytest

from overnight_research_dataset import ResearchError, canonical
from overnight_research_evidence import EvidenceArtifact, REQUIRED, paper_evidence_gate


def reports() -> list[EvidenceArtifact]:
    checks: dict[str, dict[str, Any]] = {'licensing': {'declared_purpose': 'RESEARCH_ML_AND_PAPER_SPECULATION',
        'ml_use_permitted': True, 'speculative_use_permitted': True,
        'redistribution_planned': False, 'agreement_sha256': 'a'*64},
        'adequacy': {'sessions': 30, 'minimum_sessions': 20, 'labelled_rows': 300,
            'minimum_labelled_rows': 200, 'oos_sessions': 10, 'minimum_oos_sessions': 5,
            'thresholds_frozen_before_selection': True},
        'pit_audit': dict.fromkeys(('actual_receipts_verified', 'revision_replay_verified', 'sealed_data_excluded'), True),
        'contract_audit': dict.fromkeys(('dated_instrument_identity_verified', 'calendar_and_expiry_verified', 'quotes_and_depth_verified'), True),
        'cost_audit': dict.fromkeys(('dated_tariffs_verified', 'side_and_quantity_verified'), True),
        'out_of_sample': dict.fromkeys(('purged_folds_verified', 'fit_transform_train_only', 'all_trials_retained'), True),
        'paper_protocol': dict.fromkeys(('no_broker_orders', 'loss_and_stop_protocol_reviewed', 'rejection_and_missing_data_logging'), True)}
    result: list[EvidenceArtifact] = []
    for kind in sorted(REQUIRED):
        result.append(artifact(kind, {'dataset_sha256': 'd'*64, 'model_sha256': 'c'*64,
            'reviewed_at': '2022-01-03T16:00:00+05:30', 'status': 'PASS', **checks[kind]}))
    return result


def artifact(kind: str, body: dict[str, Any]) -> EvidenceArtifact:
    raw = canonical(body)
    return EvidenceArtifact(kind, hashlib.sha256(raw).hexdigest(), raw)


def gate(artifacts: list[EvidenceArtifact]) -> dict[str, Any]:
    return paper_evidence_gate(artifacts=artifacts, dataset_sha256='d'*64, model_sha256='c'*64,
                              evaluated_at='2022-01-03T16:01:00+05:30')


def test_complete_claims_never_activate_paper_or_ml() -> None:
    result = gate(reports())
    assert result['status'] == 'REPORTS_COMPLETE_PENDING_INDEPENDENT_REVIEW'
    assert not result['paper_run_authorized'] and not result['independently_verified']
    assert not result['training_eligible'] and not result['approval_authority']


def test_empty_reports_block() -> None:
    result = gate([])
    assert result['status'] == 'BLOCKED'
    assert all(kind + ':missing' in result['failures'] for kind in REQUIRED)


@pytest.mark.parametrize('damage', ['free_download', 'insufficient', 'future_review', 'wrong_dataset',
    'redistribution', 'no_speculative_rights', 'missing_pit', 'no_frozen_thresholds'])
def test_relevant_evidence_failures_block(damage: str) -> None:
    items = reports()
    kind = 'licensing'
    if damage in ('insufficient', 'no_frozen_thresholds'):
        kind = 'adequacy'
    elif damage == 'missing_pit':
        kind = 'pit_audit'
    index = next(i for i, item in enumerate(items) if item.kind == kind)
    body = items[index].inspect()
    if damage == 'free_download':
        body.pop('agreement_sha256')
        body['source_url'] = 'https://www.nseindia.com/static/nse-disclaimer'
    elif damage == 'insufficient':
        body['labelled_rows'] = 0
    elif damage == 'future_review':
        body['reviewed_at'] = '2022-01-04T00:00:00+05:30'
    elif damage == 'wrong_dataset':
        body['dataset_sha256'] = 'b'*64
    elif damage == 'redistribution':
        body['redistribution_planned'] = True
    elif damage == 'no_speculative_rights':
        body['speculative_use_permitted'] = False
    elif damage == 'missing_pit':
        body['actual_receipts_verified'] = False
    else:
        body['thresholds_frozen_before_selection'] = False
    items[index] = artifact(kind, body)
    assert gate(items)['status'] == 'BLOCKED'


def test_hash_tampering_and_duplicate_reports_rejected() -> None:
    items = reports()
    with pytest.raises(ResearchError):
        gate([replace(items[0], payload=items[0].payload+b' ')])
    with pytest.raises(ResearchError):
        gate([items[0], items[0]])


def test_duplicate_licensing_fields_rejected() -> None:
    raw = b'{"speculative_use_permitted":false,"speculative_use_permitted":true}'
    item = EvidenceArtifact('licensing', hashlib.sha256(raw).hexdigest(), raw)
    with pytest.raises(ResearchError):
        item.inspect()
