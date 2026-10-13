"""Evidence completeness gate, never permission to train, paper trade, or deploy."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Sequence

from overnight_research_dataset import ResearchError, fingerprint, instant, sha, unique_pairs

REQUIRED = frozenset({'licensing', 'adequacy', 'pit_audit', 'contract_audit',
                      'cost_audit', 'out_of_sample', 'paper_protocol'})


@dataclass(frozen=True)
class EvidenceArtifact:
    """Retained bytes supplied by caller. Hash agreement proves bytes, not truth."""

    kind: str
    sha256: str
    payload: bytes

    def inspect(self) -> dict[str, Any]:
        sha(self.sha256)
        if (self.kind not in REQUIRED or type(self.payload) is not bytes
                or len(self.payload) > 1024 * 1024
                or hashlib.sha256(self.payload).hexdigest() != self.sha256):
            raise ResearchError('EVIDENCE_BYTES_INVALID')
        try:
            body = json.loads(self.payload, object_pairs_hook=unique_pairs)
            if not isinstance(body, dict):
                raise ValueError()
            fingerprint(body)
        except (ValueError, TypeError, UnicodeError):
            raise ResearchError('EVIDENCE_JSON_INVALID') from None
        return body


def paper_evidence_gate(*, artifacts: Sequence[EvidenceArtifact], dataset_sha256: str,
                        model_sha256: str, evaluated_at: str) -> dict[str, Any]:
    """Validate retained report structure/bindings, leaving independent audit pending.

    Even complete reports cannot self-commission paper trading. Free downloads,
    paid subscriptions, signed claims and profitable backtests are not licenses.
    """
    sha(dataset_sha256)
    sha(model_sha256)
    evaluated = instant(evaluated_at)
    reports: dict[str, Mapping[str, Any]] = {}
    failures: list[str] = []
    hashes: dict[str, str] = {}
    for artifact in artifacts:
        if artifact.kind in reports:
            raise ResearchError('DUPLICATE_EVIDENCE_KIND')
        body = artifact.inspect()
        reports[artifact.kind] = body
        hashes[artifact.kind] = artifact.sha256
        if (body.get('dataset_sha256') != dataset_sha256 or body.get('model_sha256') != model_sha256
                or instant(body.get('reviewed_at', '')) > evaluated or body.get('status') != 'PASS'):
            failures.append(artifact.kind + ':binding_or_review_invalid')
    failures.extend(kind + ':missing' for kind in sorted(REQUIRED - reports.keys()))
    license_report = reports.get('licensing', {})
    if (license_report.get('declared_purpose') != 'RESEARCH_ML_AND_PAPER_SPECULATION'
            or license_report.get('ml_use_permitted') is not True
            or license_report.get('speculative_use_permitted') is not True
            or license_report.get('redistribution_planned') is not False
            or not isinstance(license_report.get('agreement_sha256'), str)):
        failures.append('licensing:explicit_use_rights_required')
    else:
        sha(str(license_report['agreement_sha256']))
    adequacy = reports.get('adequacy', {})
    for actual, required in (('sessions', 'minimum_sessions'), ('labelled_rows', 'minimum_labelled_rows'),
                             ('oos_sessions', 'minimum_oos_sessions')):
        value, minimum = adequacy.get(actual), adequacy.get(required)
        if type(value) is not int or type(minimum) is not int or minimum <= 0 or value < minimum:
            failures.append('adequacy:' + actual)
    if adequacy.get('thresholds_frozen_before_selection') is not True:
        failures.append('adequacy:preregistered_thresholds_required')
    required_checks = {'pit_audit': ('actual_receipts_verified', 'revision_replay_verified', 'sealed_data_excluded'),
        'contract_audit': ('dated_instrument_identity_verified', 'calendar_and_expiry_verified', 'quotes_and_depth_verified'),
        'cost_audit': ('dated_tariffs_verified', 'side_and_quantity_verified'),
        'out_of_sample': ('purged_folds_verified', 'fit_transform_train_only', 'all_trials_retained'),
        'paper_protocol': ('no_broker_orders', 'loss_and_stop_protocol_reviewed', 'rejection_and_missing_data_logging')}
    for kind, checks in required_checks.items():
        for check in checks:
            if reports.get(kind, {}).get(check) is not True:
                failures.append(kind + ':' + check)
    return {'status': 'REPORTS_COMPLETE_PENDING_INDEPENDENT_REVIEW' if not failures else 'BLOCKED',
        'failures': sorted(set(failures)), 'artifact_sha256s': hashes,
        'dataset_sha256': dataset_sha256, 'model_sha256': model_sha256,
        'paper_run_authorized': False, 'independently_verified': False,
        'training_eligible': False, 'approval_authority': False, 'fill_evidence': False}
