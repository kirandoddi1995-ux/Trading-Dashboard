"""Pure complete-family composition of dataset, paper replay and loss inference.

One frozen directional prediction/reference decision per trial/session. Loss is
squared direction error, not paper profit. No IO, model fit, admission or selection.
The three imported project modules are themselves pure stdlib APIs.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import re

import quote_faithful_futures_replay as paper
import research_dataset_boundary as boundary
import research_session_inference as inference

MAX_CELLS = 4096
MAX_CELL_VERSIONS = 128
MAX_CELL_QUOTES = 256
MAX_TOTAL_RECORDS = 65536
MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
IST = timezone(timedelta(hours=5, minutes=30))


@dataclass(frozen=True)
class TrialDefinition:
    trial_id: str
    strategy_sha256: str


@dataclass(frozen=True)
class CohortPlan:
    study_sha256: str
    source_sha256: str
    baseline_strategy_sha256: str
    frozen_at: str
    trials: tuple[TrialDefinition, ...]
    session_ids: tuple[str, ...]
    partition: str
    input_kind: str


@dataclass(frozen=True)
class SessionEvidence:
    strategy_sha256: str
    baseline_strategy_sha256: str
    baseline_direction: int
    candidate_direction: int
    forecast_at: str
    frozen_decision_sha256: str
    dataset_plan: boundary.DatasetPlan
    versions: tuple[boundary.SourceVersion, ...]
    decision: boundary.DecisionInput
    label: boundary.ReferenceLabel | None
    replay_plan: paper.ReplayPlan
    contract: paper.Contract
    costs: paper.DatedCosts
    quotes: tuple[paper.Quote, ...]


@dataclass(frozen=True)
class TrialSession:
    trial_id: str
    session_id: str
    state: str  # RUN, UNRUN or FAILED; missing cells are generated, never omitted.
    evidence: SessionEvidence | None


@dataclass(frozen=True)
class CellResult:
    session_id: str
    status: str
    reason: str
    input_sha256: str | None
    dataset_status: str | None = None
    dataset_manifest_sha256: str | None = None
    replay_status: str | None = None
    replay_manifest_sha256: str | None = None


@dataclass(frozen=True)
class TrialResult:
    trial_id: str
    complete: bool
    sessions: tuple[CellResult, ...]


@dataclass(frozen=True)
class CohortResult:
    status: str
    trials: tuple[TrialResult, ...]
    inference_json: bytes
    plan_sha256: str
    manifest: bytes
    manifest_sha256: str
    training_eligible: bool = False
    promotable: bool = False
    approval_authority: bool = False
    authenticated_admission: bool = False
    selection_performed: bool = False
    successful_subset_performance_reported: bool = False


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _pin(value: str) -> None:
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('INVALID_SHA256')


def _id(value: str) -> None:
    if type(value) is not str or re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', value) is None:
        raise ValueError('INVALID_TRIAL_ID')


def _at(value: str) -> datetime:
    if type(value) is not str or not 1 <= len(value) <= 40:
        raise ValueError('AWARE_TIME_REQUIRED')
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError('AWARE_TIME_REQUIRED') from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('AWARE_TIME_REQUIRED')
    return result.astimezone(timezone.utc)


def _day(value: str) -> date:
    if type(value) is not str or re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) is None:
        raise ValueError('EXACT_SESSION_DAY_REQUIRED')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError('EXACT_SESSION_DAY_REQUIRED') from None


def _plan(plan: CohortPlan) -> dict[str, object]:
    for pin in (plan.study_sha256, plan.source_sha256, plan.baseline_strategy_sha256):
        _pin(pin)
    if (type(plan.trials) is not tuple or not 1 <= len(plan.trials) <= inference.MAX_TRIALS
            or type(plan.session_ids) is not tuple or not 1 <= len(plan.session_ids) <= inference.MAX_SESSIONS
            or len(plan.trials)*len(plan.session_ids) > MAX_CELLS):
        raise ValueError('COHORT_BOUND')
    seen: set[str] = set()
    for trial in plan.trials:
        _id(trial.trial_id)
        _pin(trial.strategy_sha256)
        if trial.trial_id in seen:
            raise ValueError('DUPLICATE_PLANNED_TRIAL')
        seen.add(trial.trial_id)
    if plan.partition not in ('DEVELOPMENT_2022_2024', 'PROSPECTIVE_VERSIONED_2026'):
        raise ValueError('SEALED_OR_UNSUPPORTED_PARTITION')
    if plan.input_kind not in ('SYNTHETIC', 'CALLER_UNAUTHENTICATED'):
        raise ValueError('UNAUTHENTICATED_INPUT_KIND_REQUIRED')
    frozen = _at(plan.frozen_at)
    prior = ''
    for session in plan.session_ids:
        day = _day(session)
        if session <= prior:
            raise ValueError('UNIQUE_CHRONOLOGICAL_SESSIONS_REQUIRED')
        allowed = 2022 <= day.year <= 2024 if plan.partition == 'DEVELOPMENT_2022_2024' else day.year == 2026
        if not allowed:
            raise ValueError('SEALED_OR_UNSUPPORTED_SESSION')
        if frozen.astimezone(IST).date() >= day:
            raise ValueError('COHORT_MUST_BE_FROZEN_BEFORE_FIRST_SESSION_DAY')
        prior = session
    return dict(format='frozen-research-cohort-v1', plan={**asdict(plan), 'frozen_at': frozen.isoformat()},
        loss='SQUARED_REFERENCE_DIRECTION_ERROR_ONE_DECISION_PER_SESSION',
        weighting='EQUAL_SESSION_COMPLETE_FAMILY_ONLY', min_sessions=inference.MIN_SESSIONS,
        block_size=inference.BLOCK_SIZE, draws=inference.DRAWS, seed=inference.SEED,
        correction='HOLM_COMPLETE_FROZEN_FAMILY')


def plan_sha256(plan: CohortPlan) -> str:
    """Caller must preserve this pin before submitting outcomes; not a signature."""
    return _sha(_plan(plan))


def decision_sha256(evidence: SessionEvidence) -> str:
    """Frozen forecast envelope; future labels/quote outcomes are NOT frozen here.

    Decision input hash binds the declared full prefix via the dataset API. Code,
    contract and cost hashes are caller claims, not verified implementation pins.
    """
    return _sha(dict(strategy_sha256=evidence.strategy_sha256,
        baseline_strategy_sha256=evidence.baseline_strategy_sha256,
        baseline_direction=evidence.baseline_direction, candidate_direction=evidence.candidate_direction,
        forecast_at=evidence.forecast_at, dataset_plan=asdict(evidence.dataset_plan),
        decision=asdict(evidence.decision), replay_plan=asdict(evidence.replay_plan),
        contract=asdict(evidence.contract), costs=asdict(evidence.costs)))


def _tree_bound(value: object) -> tuple[object, bool]:
    """Validate EVERY scalar and return a strict-JSON size-accounting tree.

    Nonfinite floats are tagged only for resource accounting, never identity.
    Finding one must not skip validation of later siblings or byte accounting.
    """
    if isinstance(value, dict):
        safe_dict: dict[str, object] = {}
        nonfinite = False
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError('UNSUPPORTED_INPUT_TYPE')
            _tree_bound(key)
            safe_item, invalid = _tree_bound(item)
            safe_dict[key] = safe_item
            nonfinite = nonfinite or invalid
        return safe_dict, nonfinite
    elif isinstance(value, (list, tuple)):
        safe_items: list[object] = []
        nonfinite = False
        for item in value:
            safe_item, invalid = _tree_bound(item)
            safe_items.append(safe_item)
            nonfinite = nonfinite or invalid
        return safe_items, nonfinite
    elif type(value) is str:
        if len(value) > 128:
            raise ValueError('SCALAR_BOUND')
    elif type(value) is int:
        if abs(value) > 10**15:
            raise ValueError('SCALAR_BOUND')
    elif type(value) is float:
        if not math.isfinite(value):
            tag = 'NAN' if math.isnan(value) else 'POS_INF' if value > 0 else 'NEG_INF'
            return {'invalid_float': tag}, True
    elif value is not None and type(value) is not bool:
        raise ValueError('UNSUPPORTED_INPUT_TYPE')
    return value, False


def _bindings(plan: CohortPlan, trial: TrialDefinition, day: str, e: SessionEvidence) -> None:
    d, r, p = e.decision, e.replay_plan, e.dataset_plan
    if (e.strategy_sha256 != trial.strategy_sha256
            or e.baseline_strategy_sha256 != plan.baseline_strategy_sha256
            or p.study_sha256 != plan.study_sha256 or r.study_sha256 != plan.study_sha256
            or p.source_sha256 != plan.source_sha256 or p.partition != plan.partition
            or p.input_kind != plan.input_kind or r.input_kind != plan.input_kind
            or p.decision_ids != (d.decision_id,) or d.input_sha256 != r.decision_input_sha256):
        raise ValueError('CELL_IDENTITY_BINDING_MISMATCH')
    if (type(e.baseline_direction) is not int or e.baseline_direction not in (-1, 0, 1)
            or type(e.candidate_direction) is not int or e.candidate_direction not in (-1, 1)
            or e.candidate_direction != r.direction):
        raise ValueError('FROZEN_DIRECTION_MISMATCH')
    forecast, decision_at = _at(e.forecast_at), _at(d.decision_at)
    if (not _at(plan.frozen_at) <= _at(p.preregistered_at) <= forecast
            or forecast != decision_at
            or forecast != _at(r.frozen_at) or decision_at != _at(r.entry_decision_at)
            or _at(e.contract.known_at) > forecast or _at(e.costs.known_at) > forecast):
        raise ValueError('CELL_FREEZE_OR_DECISION_TIME_MISMATCH')
    if any(_at(t).astimezone(IST).date().isoformat() != day for t in (
            d.decision_at, r.session_open, r.session_close, r.exit_decision_at)):
        raise ValueError('CELL_SESSION_DATE_MISMATCH')
    if e.label is not None and _at(e.label.horizon_end) != _at(r.exit_decision_at):
        raise ValueError('REFERENCE_HORIZON_MISMATCH')
    _pin(e.frozen_decision_sha256)
    if e.frozen_decision_sha256 != decision_sha256(e):
        raise ValueError('FROZEN_DECISION_HASH_MISMATCH')


def evaluate(plan: CohortPlan, submissions: tuple[TrialSession, ...], *,
             frozen_plan_sha256: str, evaluated_at: str) -> CohortResult:
    """Retain the complete declared Cartesian cohort, never select successes.

    Global ambiguous/out-of-family identities and resource violations raise;
    per-cell child validation failures become retained REJECTED cells. A malformed
    nonfinite cell has no input digest, explicitly not a fabricated content hash.
    """
    frozen = _plan(plan)
    _pin(frozen_plan_sha256)
    if _sha(frozen) != frozen_plan_sha256:
        raise ValueError('FROZEN_COHORT_HASH_MISMATCH')
    cutoff = _at(evaluated_at)
    if type(submissions) is not tuple or len(submissions) > MAX_CELLS:
        raise ValueError('SUBMISSION_BOUND')
    supplied: dict[tuple[str, str], tuple[TrialSession, str | None]] = {}
    input_bytes = 0
    records = 0
    for submission in submissions:
        key = (submission.trial_id, submission.session_id)
        if (submission.trial_id not in {t.trial_id for t in plan.trials}
                or submission.session_id not in plan.session_ids):
            raise ValueError('OUTSIDE_FROZEN_COHORT')
        if key in supplied:
            raise ValueError('DUPLICATE_TRIAL_SESSION')
        if submission.state not in ('RUN', 'UNRUN', 'FAILED'):
            raise ValueError('INVALID_SUBMISSION_STATE')
        e = submission.evidence
        if e is not None:
            if (type(e.versions) is not tuple or len(e.versions) > MAX_CELL_VERSIONS
                    or type(e.quotes) is not tuple or len(e.quotes) > MAX_CELL_QUOTES
                    or type(e.decision.event_ids) is not tuple
                    or len(e.decision.event_ids) > boundary.MAX_INPUT_EVENTS
                    or type(e.dataset_plan.decision_ids) is not tuple
                    or len(e.dataset_plan.decision_ids) != 1):
                raise ValueError('CELL_RESOURCE_BOUND')
            records += len(e.versions)+len(e.quotes)
        if records > MAX_TOTAL_RECORDS:
            raise ValueError('TOTAL_RECORD_BOUND')
        raw = asdict(submission)
        accounting_tree, nonfinite = _tree_bound(raw)
        encoded = _canonical(accounting_tree)
        input_bytes += len(encoded)
        if input_bytes > MAX_INPUT_BYTES:
            raise ValueError('TOTAL_INPUT_BYTE_BOUND')
        supplied[key] = (submission, None if nonfinite else hashlib.sha256(encoded).hexdigest())

    cells: dict[tuple[str, str], CellResult] = {}
    losses: dict[tuple[str, str], tuple[float, float]] = {}
    common: dict[str, dict[str, list[str]]] = {}
    for trial in plan.trials:
        for day in plan.session_ids:
            key = (trial.trial_id, day)
            item = supplied.get(key)
            if item is None:
                cells[key] = CellResult(day, 'NOT_REPORTED', 'EXPECTED_CELL_ABSENT', None)
                continue
            submission, input_pin = item
            if input_pin is None:
                cells[key] = CellResult(day, 'REJECTED', 'UNHASHABLE_NONFINITE_INPUT', None)
                continue
            if submission.state != 'RUN':
                cells[key] = CellResult(day, submission.state, 'DECLARED_'+submission.state, input_pin)
                continue
            e = submission.evidence
            if e is None:
                cells[key] = CellResult(day, 'MISSING_EVIDENCE', 'RUN_WITHOUT_EVIDENCE', input_pin)
                continue
            try:
                _bindings(plan, trial, day, e)
            except ValueError:
                cells[key] = CellResult(day, 'REJECTED', 'CELL_BINDING_OR_TIME_REJECTED', input_pin)
                continue
            try:
                dataset = boundary.evaluate(e.dataset_plan, e.versions, (e.decision,),
                    () if e.label is None else (e.label,), evaluated_at=evaluated_at)
            except ValueError:
                cells[key] = CellResult(day, 'REJECTED', 'DATASET_INPUT_REJECTED', input_pin)
                continue
            try:
                # The batch hash binds all supplied quotes, but replay must not
                # inspect future prices/depth/revisions as if already received.
                known_quotes = tuple(q for q in e.quotes if _at(q.available_at) <= cutoff)
                replay = paper.replay(e.replay_plan, e.contract, e.costs, known_quotes)
            except ValueError:
                cells[key] = CellResult(day, 'REJECTED', 'REPLAY_INPUT_REJECTED', input_pin,
                                       dataset.status, dataset.manifest_sha256)
                continue
            result = CellResult(day, 'COMPLETE', 'REFERENCE_AND_PAPER_SUPPORTED', input_pin,
                dataset.status, dataset.manifest_sha256, replay.status, replay.manifest_sha256)
            if dataset.status != 'STRUCTURAL_REFERENCE_OUTPUT_UNADMITTED':
                result = CellResult(day, 'DATASET_WITHHELD', 'REFERENCE_DATASET_NOT_COMPLETE', input_pin,
                    dataset.status, dataset.manifest_sha256, replay.status, replay.manifest_sha256)
            elif (replay.status != 'PAPER_ROUND_TRIP_UNADMITTED' or len(replay.fills) != 2
                    or not replay.paper_flat or any(_at(fill.filled_at) > cutoff for fill in replay.fills)):
                result = CellResult(day, 'NO_FILLS', 'PAPER_PAIR_WITHHELD', input_pin,
                    dataset.status, dataset.manifest_sha256, replay.status, replay.manifest_sha256)
            cells[key] = result
            if result.status == 'COMPLETE':
                direction = dataset.rows[0].direction
                losses[key] = (float((e.baseline_direction-direction)**2),
                               float((e.candidate_direction-direction)**2))
                shared = _sha(dict(dataset_manifest=dataset.manifest_sha256,
                    baseline=e.baseline_direction, forecast_at=_at(e.forecast_at).isoformat()))
                common.setdefault(day, {}).setdefault(shared, []).append(trial.trial_id)
    # All trials must score the SAME reference problem and baseline per session.
    for day, groups in common.items():
        if len(groups) > 1:
            for trial_ids in groups.values():
                for trial_id in trial_ids:
                    old = cells[(trial_id, day)]
                    cells[(trial_id, day)] = CellResult(day, 'REJECTED', 'COMMON_SESSION_EVIDENCE_CONFLICT',
                        old.input_sha256, old.dataset_status, old.dataset_manifest_sha256,
                        old.replay_status, old.replay_manifest_sha256)

    trials: list[TrialResult] = []
    outcomes: list[inference.TrialOutcome] = []
    for trial in plan.trials:
        session_results = tuple(cells[(trial.trial_id, day)] for day in plan.session_ids)
        complete = all(cell.status == 'COMPLETE' for cell in session_results)
        trials.append(TrialResult(trial.trial_id, complete, session_results))
        paired = [losses[(trial.trial_id, day)] for day in plan.session_ids] if complete else []
        outcomes.append(inference.TrialOutcome(trial.trial_id, plan.session_ids if complete else (),
            tuple(pair[0] for pair in paired), tuple(pair[1] for pair in paired), completed=complete))
    method = inference.infer(inference.StudyPlan(tuple(t.trial_id for t in plan.trials)), outcomes)
    status = 'COHORT_METHOD_OUTPUT_UNADMITTED' if method['status'] == 'METHOD_OUTPUT_UNADMITTED' else 'INSUFFICIENT_EVIDENCE'
    method_json = _canonical(method)
    manifest = _canonical(dict(format='frozen-cohort-evaluation-v1', frozen=frozen,
        plan_sha256=frozen_plan_sha256, evaluated_at=_at(evaluated_at).isoformat(), status=status,
        trials=[asdict(t) for t in trials], inference=method,
        input_binding='PER_CELL_CANONICAL_INPUT_HASH_UNHASHABLE_INPUT_EXPLICITLY_UNBOUND',
        quote_replay_scope='AVAILABLE_AT_OR_BEFORE_EVALUATED_AT',
        input_byte_accounting='STRICT_JSON_NONFINITE_TAGS_FOR_SIZE_ONLY_NOT_CONTENT_HASH',
        training_eligible=False, promotable=False, approval_authority=False,
        authenticated_admission=False, selection_performed=False,
        successful_subset_performance_reported=False, pnl_performance_reported=False,
        provenance='CALLER_INPUTS_NOT_AUTHENTICATED', source_code_authenticated=False))
    if len(manifest) > MAX_MANIFEST_BYTES:
        raise ValueError('RESULT_MANIFEST_BOUND')
    return CohortResult(status, tuple(trials), method_json, frozen_plan_sha256,
                        manifest, hashlib.sha256(manifest).hexdigest())
