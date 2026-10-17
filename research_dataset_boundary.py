"""Pure bounded PIT/reference-label boundary, not authenticated admission.

No adapters, IO, fitting, historical unseal or real-data assertion. Attestations
and hashes supplied by a caller do not authenticate provenance or a study.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re

MAX_VERSIONS = 4096
MAX_DECISIONS = 512
MAX_INPUT_EVENTS = 64
MAX_PRICE = 1e12
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
IST = timezone(timedelta(hours=5, minutes=30))


@dataclass(frozen=True)
class DatasetPlan:
    study_sha256: str
    source_sha256: str
    partition: str
    preregistered_at: str
    decision_ids: tuple[str, ...]
    licence_sha256: str | None
    provenance_sha256: str | None
    licence_attested: bool
    provenance_attested: bool
    preregistration_attested: bool
    prospective_attested: bool
    input_kind: str  # SYNTHETIC or CALLER_UNAUTHENTICATED, never inferred REAL.


@dataclass(frozen=True)
class SourceVersion:
    event_id: str
    version: int
    event_at: str
    observed_at: str
    reference_price: float | None
    quote_count: int
    source_sha256: str
    payload_sha256: str


@dataclass(frozen=True)
class DecisionInput:
    decision_id: str
    decision_at: str
    event_ids: tuple[str, ...]
    entry_event_id: str
    input_sha256: str  # Full consumed prefix, not just the entry price.


@dataclass(frozen=True)
class ReferenceLabel:
    decision_id: str
    horizon_end: str
    observed_at: str
    target_event_id: str
    target_version_sha256: str


@dataclass(frozen=True)
class EvidenceIssue:
    identity: str
    code: str


@dataclass(frozen=True)
class ReferenceRow:
    decision_id: str
    input_sha256: str
    target_version_sha256: str
    direction: int
    label_kind: str = 'REFERENCE_DIRECTION_NOT_EXECUTABLE_PNL'


@dataclass(frozen=True)
class BoundaryReport:
    status: str
    rows: tuple[ReferenceRow, ...]
    missing: tuple[EvidenceIssue, ...]
    rejected: tuple[EvidenceIssue, ...]
    plan_sha256: str
    manifest: bytes
    manifest_sha256: str
    training_eligible: bool = False
    promotable: bool = False
    approval_authority: bool = False
    authenticated_admission: bool = False
    executable_pnl: bool = False


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _hash(value: str) -> None:
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('INVALID_SHA256')


def _id(value: str) -> None:
    if type(value) is not str or re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', value) is None:
        raise ValueError('INVALID_IDENTITY')


def _at(value: str) -> datetime:
    if type(value) is not str or not 1 <= len(value) <= 40:
        raise ValueError('AWARE_TIMESTAMP_REQUIRED')
    try:
        at = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError('AWARE_TIMESTAMP_REQUIRED') from None
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError('AWARE_TIMESTAMP_REQUIRED')
    return at.astimezone(timezone.utc)


def _version(value: SourceVersion) -> dict[str, object]:
    _id(value.event_id)
    _hash(value.source_sha256)
    _hash(value.payload_sha256)
    if type(value.version) is not int or not 1 <= value.version <= MAX_VERSIONS:
        raise ValueError('INVALID_VERSION')
    if type(value.quote_count) is not int or not 0 <= value.quote_count <= 1_000_000:
        raise ValueError('INVALID_QUOTE_COUNT')
    price = value.reference_price
    if price is not None and (type(price) not in (int, float)
                             or not 0 < price <= MAX_PRICE or not math.isfinite(price)):
        raise ValueError('INVALID_REFERENCE_PRICE')
    event, observed = _at(value.event_at), _at(value.observed_at)
    if observed < event:
        raise ValueError('OBSERVED_BEFORE_EVENT')
    return dict(event_id=value.event_id, version=value.version, event_at=event.isoformat(),
                observed_at=observed.isoformat(), reference_price=None if price is None else float(price),
                quote_count=value.quote_count, source_sha256=value.source_sha256,
                payload_sha256=value.payload_sha256)


def version_sha256(value: SourceVersion) -> str:
    """Fingerprint metadata plus caller's raw-payload hash; not verification."""
    return _sha(_version(value))


def input_sha256(versions: tuple[SourceVersion, ...]) -> str:
    """Hash the entire caller-declared input prefix; one version per event."""
    if type(versions) is not tuple or not 1 <= len(versions) <= MAX_INPUT_EVENTS:
        raise ValueError('INPUT_PREFIX_BOUND')
    if len({v.event_id for v in versions}) != len(versions):
        raise ValueError('DUPLICATE_INPUT_EVENT')
    return _sha([_version(v) for v in sorted(versions, key=lambda v: v.event_id)])


def evaluate(plan: DatasetPlan, versions: tuple[SourceVersion, ...],
             decisions: tuple[DecisionInput, ...], labels: tuple[ReferenceLabel, ...],
             *, evaluated_at: str) -> BoundaryReport:
    """Validate complete declared scope and return unadmitted reference rows.

    Malformed/ambiguous structures raise fixed ValueError codes. Absent evidence,
    policy rejection and immature labels are classified in the frozen manifest.
    No clock/calendar is queried; evaluated_at is a caller claim, not fresh time.
    """
    for collection, bound in ((versions, MAX_VERSIONS), (decisions, MAX_DECISIONS),
                              (labels, MAX_DECISIONS), (plan.decision_ids, MAX_DECISIONS)):
        if type(collection) is not tuple or len(collection) > bound:
            raise ValueError('COLLECTION_BOUND')
    if not plan.decision_ids:
        raise ValueError('EMPTY_FROZEN_DECISION_SCOPE')
    for identity in plan.decision_ids:
        _id(identity)
    if len(set(plan.decision_ids)) != len(plan.decision_ids):
        raise ValueError('DUPLICATE_PLANNED_DECISION')
    _hash(plan.study_sha256)
    _hash(plan.source_sha256)
    for optional in (plan.licence_sha256, plan.provenance_sha256):
        if optional is not None:
            _hash(optional)
    for flag in (plan.licence_attested, plan.provenance_attested,
                 plan.preregistration_attested, plan.prospective_attested):
        if type(flag) is not bool:
            raise ValueError('LITERAL_ATTESTATION_REQUIRED')
    if plan.input_kind not in ('SYNTHETIC', 'CALLER_UNAUTHENTICATED'):
        raise ValueError('UNAUTHENTICATED_INPUT_KIND_REQUIRED')
    if plan.partition not in ('DEVELOPMENT_2022_2024', 'PROSPECTIVE_VERSIONED_2026'):
        raise ValueError('SEALED_OR_UNSUPPORTED_PARTITION')
    prereg, cutoff = _at(plan.preregistered_at), _at(evaluated_at)
    missing: list[EvidenceIssue] = []
    rejected: list[EvidenceIssue] = []
    for name, pin, attested in (('LICENCE', plan.licence_sha256, plan.licence_attested),
                                 ('PROVENANCE', plan.provenance_sha256, plan.provenance_attested)):
        if pin is None or not attested:
            missing.append(EvidenceIssue('PLAN', name+'_EVIDENCE_REQUIRED'))
    if not plan.preregistration_attested:
        missing.append(EvidenceIssue('PLAN', 'PREREGISTRATION_ATTESTATION_REQUIRED'))
    if plan.partition == 'PROSPECTIVE_VERSIONED_2026' and not plan.prospective_attested:
        missing.append(EvidenceIssue('PLAN', 'SEPARATE_PROSPECTIVE_ATTESTATION_REQUIRED'))

    groups: dict[str, list[SourceVersion]] = {}
    for value in versions:
        _version(value)
        if value.source_sha256 != plan.source_sha256:
            raise ValueError('SOURCE_IDENTITY_MISMATCH')
        groups.setdefault(value.event_id, []).append(value)
    for group in groups.values():
        group.sort(key=lambda v: v.version)
        for previous, current in zip(group, group[1:]):
            if (current.version <= previous.version
                    or _at(current.observed_at) <= _at(previous.observed_at)
                    or _at(current.event_at) != _at(previous.event_at)):
                raise ValueError('AMBIGUOUS_OR_NONMONOTONIC_REVISION')

    def partition_ok(at: datetime) -> bool:
        year = at.astimezone(IST).year
        return (2022 <= year <= 2024 if plan.partition == 'DEVELOPMENT_2022_2024'
                else year == 2026 and prereg <= at)

    # Entire supplied scope, including unused/late versions, is hash-bound and
    # checked: a future historical revision cannot smuggle a sealed year in.
    for value in versions:
        if not partition_ok(_at(value.event_at)) or not partition_ok(_at(value.observed_at)):
            rejected.append(EvidenceIssue(value.event_id, 'SEALED_OR_OUTSIDE_DECLARED_PARTITION'))
    decision_map: dict[str, DecisionInput] = {}
    for decision in decisions:
        _id(decision.decision_id)
        _id(decision.entry_event_id)
        _hash(decision.input_sha256)
        if decision.decision_id not in plan.decision_ids:
            raise ValueError('UNDECLARED_DECISION')
        if decision.decision_id in decision_map:
            raise ValueError('DUPLICATE_DECISION')
        if (type(decision.event_ids) is not tuple or not 1 <= len(decision.event_ids) <= MAX_INPUT_EVENTS
                or len(set(decision.event_ids)) != len(decision.event_ids)):
            raise ValueError('AMBIGUOUS_INPUT_PREFIX')
        for event in decision.event_ids:
            _id(event)
        if decision.entry_event_id not in decision.event_ids:
            raise ValueError('ENTRY_OUTSIDE_INPUT_PREFIX')
        _at(decision.decision_at)
        decision_map[decision.decision_id] = decision
    label_map: dict[str, ReferenceLabel] = {}
    for label in labels:
        _id(label.decision_id)
        _id(label.target_event_id)
        _hash(label.target_version_sha256)
        _at(label.horizon_end)
        _at(label.observed_at)
        if label.decision_id not in plan.decision_ids:
            raise ValueError('UNDECLARED_LABEL')
        if label.decision_id in label_map:
            raise ValueError('AMBIGUOUS_DUPLICATE_LABEL')
        label_map[label.decision_id] = label

    rows: list[ReferenceRow] = []
    for identity in plan.decision_ids:
        found_decision = decision_map.get(identity)
        if found_decision is None:
            missing.append(EvidenceIssue(identity, 'DECISION_NOT_REPORTED'))
            continue
        decision = found_decision
        at = _at(decision.decision_at)
        if not partition_ok(at) or prereg > at or at > cutoff:
            rejected.append(EvidenceIssue(identity, 'DECISION_PARTITION_OR_PREREGISTRATION_TIME'))
            continue
        selected: list[SourceVersion] = []
        for event in decision.event_ids:
            available = [v for v in groups.get(event, ())
                         if _at(v.observed_at) <= at and _at(v.event_at) <= at]
            if not available:
                missing.append(EvidenceIssue(identity, 'INPUT_NOT_OBSERVED_AT_DECISION'))
                break
            selected.append(available[-1])
        if len(selected) != len(decision.event_ids):
            continue
        if input_sha256(tuple(selected)) != decision.input_sha256:
            rejected.append(EvidenceIssue(identity, 'FROZEN_INPUT_PREFIX_MISMATCH'))
            continue
        entry = next(v for v in selected if v.event_id == decision.entry_event_id)
        found_label = label_map.get(identity)
        if found_label is None:
            missing.append(EvidenceIssue(identity, 'LABEL_NOT_REPORTED'))
            continue
        label = found_label
        end, known = _at(label.horizon_end), _at(label.observed_at)
        if end <= at or known < end:
            rejected.append(EvidenceIssue(identity, 'LABEL_TIMING_INVALID'))
            continue
        if end > cutoff or known > cutoff:
            missing.append(EvidenceIssue(identity, 'LABEL_NOT_MATURED_OR_OBSERVED'))
            continue
        targets = [v for v in groups.get(label.target_event_id, ())
                   if version_sha256(v) == label.target_version_sha256]
        if not targets:
            missing.append(EvidenceIssue(identity, 'LABEL_VERSION_NOT_REPORTED'))
            continue
        target = targets[0]
        if _at(target.event_at) != end or _at(target.observed_at) > known:
            rejected.append(EvidenceIssue(identity, 'LABEL_VERSION_TIMING_MISMATCH'))
            continue
        if (entry.reference_price is None or target.reference_price is None
                or entry.quote_count < 1 or target.quote_count < 1):
            missing.append(EvidenceIssue(identity, 'INSUFFICIENT_REFERENCE_QUOTE'))
            continue
        direction = int(target.reference_price > entry.reference_price)-int(target.reference_price < entry.reference_price)
        rows.append(ReferenceRow(identity, decision.input_sha256, label.target_version_sha256, direction))

    # Any absent/rejected member or plan evidence withholds the entire dataset.
    missing.sort(key=lambda issue: (issue.identity, issue.code))
    rejected.sort(key=lambda issue: (issue.identity, issue.code))
    if rejected or missing:
        rows = []
    status = 'REJECTED_EVIDENCE' if rejected else 'INSUFFICIENT_EVIDENCE' if missing else 'STRUCTURAL_REFERENCE_OUTPUT_UNADMITTED'
    normalized_plan = asdict(plan)
    normalized_plan['preregistered_at'] = prereg.isoformat()
    plan_hash = _sha(normalized_plan)
    manifest_value = dict(format='research-dataset-boundary-v1', plan=normalized_plan,
        plan_sha256=plan_hash, evaluated_at=cutoff.isoformat(),
        versions=[_version(v) for v in sorted(versions, key=lambda v: (v.event_id, v.version))],
        decisions=[{**asdict(d), 'decision_at': _at(d.decision_at).isoformat()}
                   for d in sorted(decisions, key=lambda d: d.decision_id)],
        labels=[{**asdict(l), 'horizon_end': _at(l.horizon_end).isoformat(),
                 'observed_at': _at(l.observed_at).isoformat()}
                for l in sorted(labels, key=lambda l: l.decision_id)],
        status=status, rows=[asdict(r) for r in rows], missing=[asdict(i) for i in missing],
        rejected=[asdict(i) for i in rejected], training_eligible=False, promotable=False,
        approval_authority=False, authenticated_admission=False, executable_pnl=False,
        input_kind=plan.input_kind, provenance='CALLER_CLAIMS_NOT_AUTHENTICATED',
        input_scope='DECLARED_PREFIX_COMPLETENESS_NOT_INDEPENDENTLY_VERIFIED',
        label_kind='REFERENCE_DIRECTION_NOT_EXECUTABLE_PNL')
    manifest = _canonical(manifest_value)
    if len(manifest) > MAX_MANIFEST_BYTES:
        raise ValueError('MANIFEST_SIZE_BOUND')
    return BoundaryReport(status, tuple(rows), tuple(missing), tuple(rejected), plan_hash,
                          manifest, hashlib.sha256(manifest).hexdigest())
