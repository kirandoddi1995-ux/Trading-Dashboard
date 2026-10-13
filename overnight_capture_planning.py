"""Pure owner planning and prospective research gates; no task installation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import re

from overnight_capture_audit import Generation


def _aware(at: datetime) -> None:
    if at.utcoffset() is None:
        raise ValueError('OVERNIGHT_AWARE_TIME_REQUIRED')


@dataclass(frozen=True)
class TaskAction:
    name: str
    mode: str
    at: datetime
    executable: str
    arguments: tuple[str, ...]
    working_directory: str
    last_at: datetime
    repeat_interval_minutes: int | None = None
    repeat_count: int = 1
    enabled: bool = False
    logon: str = 'InteractiveToken'
    privilege: str = 'LeastPrivilege'
    action: str = 'REVIEW_ONLY'
    overlap_policy: str = 'IgnoreNew'
    catch_up: bool = False
    execution_limit_seconds: int = 120


@dataclass(frozen=True)
class TaskPlan:
    tasks: tuple[TaskAction, ...]
    blockers: tuple[str, ...]
    owner_steps: tuple[str, ...]
    installation_performed: bool = False
    deletion_performed: bool = False
    approval_authority: bool = False


def plan_tasks(opening: datetime, closing: datetime, *, owner_sid: str,
               namespace: str, existing_names: frozenset[str],
               python_executable: Path, working_directory: Path, private_root: Path,
               calendar_reviewed: bool = False, license_reviewed: bool = False,
               private_namespace_reviewed: bool = False) -> TaskPlan:
    """Disabled date-pinned proposals; case-insensitive collision blocks all tasks."""
    _aware(opening)
    _aware(closing)
    if (closing <= opening or closing.date() != opening.date()
            or re.fullmatch(r'S-1-5-(?:\d+-)*\d+', owner_sid) is None
            or re.fullmatch(r'overnight_capture_[A-Za-z0-9_]{1,64}', namespace) is None):
        raise ValueError('OVERNIGHT_PLAN_IDENTITY_INVALID')
    if (opening.utcoffset() != timedelta(hours=5, minutes=30)
            or closing.utcoffset() != opening.utcoffset()
            or opening.strftime('%H:%M:%S') != '09:15:00'
            or closing.strftime('%H:%M:%S') != '15:30:00'
            or opening.microsecond or closing.microsecond):
        raise ValueError('OVERNIGHT_REVIEWED_INDEX_WINDOW_REQUIRED')
    if (any(not p.is_absolute() or '..' in p.parts
            for p in (python_executable, working_directory, private_root))
            or not python_executable.is_relative_to(working_directory)
            or private_root.is_relative_to(working_directory)):
        raise ValueError('OVERNIGHT_REVIEWED_SEPARATE_PATHS_REQUIRED')
    names = tuple(f'{namespace}_{opening.date().isoformat()}_{mode}'
                  for mode in ('prepare', 'poll', 'audit'))
    blockers = []
    if any(n.casefold() in {old.casefold() for old in existing_names} for n in names):
        blockers.append('TASK_NAME_COLLISION')
    for verified, code in ((calendar_reviewed, 'CALENDAR_UNREVIEWED'),
                           (license_reviewed, 'LICENSE_UNREVIEWED'),
                           (private_namespace_reviewed, 'PRIVATE_NAMESPACE_UNREVIEWED')):
        if verified is not True:
            blockers.append(code)
    first_poll = opening + timedelta(minutes=5, seconds=30)
    last_poll = closing + timedelta(seconds=30)
    audit_at = closing.replace(hour=15, minute=40)
    tasks = () if blockers else tuple(TaskAction(
        name, mode, at, str(python_executable),
        (str(working_directory / 'forward_versioned_capture.py'), '--root', str(private_root),
         '--session-date', opening.date().isoformat(), '--mode', mode, '--confirm-versioned-research'),
        str(working_directory), last_poll if mode == 'poll' else at,
        5 if mode == 'poll' else None, 75 if mode == 'poll' else 1)
        for name, mode, at in zip(names, ('prepare-policy', 'poll', 'audit'),
                                 (opening - timedelta(minutes=15), first_poll, audit_at)))
    return TaskPlan(tasks, tuple(blockers), (
        f'Confirm owner {owner_sid} and separate versioned namespace before any future registration.',
        'Review date-specific calendar, licence, clock, authentication and source pins.',
        'Keep proposals disabled; supervise prepare and one poll before considering scheduling.',
        'Resolve existing-name collisions with a new namespace; retain all old tasks and folders.',
        'Base owner-file preparation must succeed before the separate prepare-policy action.',
        'After two supervised future-slot polls, review date-pinned five-minute recurrence only.',
        'Last index poll is 15:30:30; owner audit is 15:40, not the 15:35 verifier minimum.'))


@dataclass(frozen=True)
class Preregistration:
    policy_sha256: str
    registered_at: datetime
    first_session_open: datetime
    minimum_sessions: int
    hypothesis: str
    outcome_definition: str
    missing_data_policy: str
    split_policy: str


@dataclass(frozen=True)
class EligibilityInputs:
    generations: tuple[Generation, ...] = ()
    license_evidence_sha256: str | None = None
    calendar_evidence_sha256: str | None = None
    independent_review_sha256: str | None = None
    outcome_evidence_sha256: str | None = None


@dataclass(frozen=True)
class Eligibility:
    status: str
    blockers: tuple[str, ...]
    qualifying_sessions: int
    research_review_ready: bool
    training_eligible: bool = False
    approval_authority: bool = False
    retrospective_relabeling_allowed: bool = False


def research_gate(registration: Preregistration, inputs: EligibilityInputs) -> Eligibility:
    """Assess review readiness only. Evidence references require later human validation."""
    _aware(registration.registered_at)
    _aware(registration.first_session_open)
    blockers = []
    if registration.registered_at >= registration.first_session_open:
        blockers.append('PREREGISTRATION_NOT_PROSPECTIVE')
    if (type(registration.minimum_sessions) is not int or registration.minimum_sessions < 2
            or any(not s.strip() for s in (registration.hypothesis, registration.outcome_definition,
                                          registration.missing_data_policy, registration.split_policy))
            or re.fullmatch(r'[0-9a-f]{64}', registration.policy_sha256) is None):
        blockers.append('PREREGISTRATION_INCOMPLETE')
    for name, reference in (('LICENSE', inputs.license_evidence_sha256),
                            ('CALENDAR', inputs.calendar_evidence_sha256),
                            ('INDEPENDENT_REVIEW', inputs.independent_review_sha256),
                            ('OUTCOMES', inputs.outcome_evidence_sha256)):
        if reference is None or re.fullmatch(r'[0-9a-f]{64}', reference) is None:
            blockers.append(name + '_EVIDENCE_MISSING')
    sessions: set[str] = set()
    generations: set[str] = set()
    for generation in inputs.generations:
        start = datetime.fromisoformat(generation.session_open)
        _aware(start)
        if (start < registration.first_session_open
                or generation.policy_sha256 != registration.policy_sha256):
            blockers.append('SESSION_OUTSIDE_PREREGISTRATION')
            continue
        if generation.sha256 in generations or start.date().isoformat() in sessions:
            blockers.append('DUPLICATE_SESSION_OR_GENERATION')
            continue
        generations.add(generation.sha256)
        if (generation.scope not in ('LOCAL_BYTES_REPLAYED', 'INJECTED_TRANSPORT_BYTES_REPLAYED')
                or generation.expected_decisions != 75 or generation.raw_polls != 75
                or generation.recorded_decisions != 75 or generation.missing_decisions != 0
                or generation.training_eligible is not False or generation.approval_authority is not False):
            blockers.append('SESSION_EVIDENCE_INSUFFICIENT')
            continue
        sessions.add(start.date().isoformat())
    if len(sessions) < registration.minimum_sessions:
        blockers.append('INSUFFICIENT_PROSPECTIVE_SESSIONS')
    unique = tuple(dict.fromkeys(blockers))
    return Eligibility('BLOCKED' if unique else 'RESEARCH_REVIEW_READY', unique, len(sessions), not unique)
