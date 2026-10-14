"""One bounded read-only readiness check; preview has zero I/O and no clock read.

API: ReadinessSpec, preview(), assess_readiness(spec, now, prepared_status, facts),
guided_check(spec, clock, prepared, inspect), and main(argv).
Never prepares state, polls, enables tasks, waits, retries, discovers credentials,
or measures NTP. Reports are observations, not fresh-capsule acceptance proofs.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path, PureWindowsPath
import re
from typing import cast

IST = timezone(timedelta(hours=5, minutes=30))
MAX_FUTURE_SECONDS = 86400
PREPARED_BYTES = 65536


@dataclass(frozen=True)
class ReadinessSpec:
    session_date: date
    code_directory: str
    python_executable: str
    state_root: str
    ops_root: str

    @property
    def task_names(self) -> tuple[str, str]:
        prefix = 'KiranTrading-Versioned-' + self.session_date.strftime('%Y%m%d')
        return prefix + '-poll', prefix + '-audit'

    def validate(self) -> None:
        if type(self.session_date) is not date:
            raise ValueError('READINESS_SPEC_INVALID')
        values = (self.code_directory, self.python_executable, self.state_root, self.ops_root)
        if any(type(v) is not str or not 1 <= len(v) <= 512 or any(c in v for c in '\r\n"')
               or not PureWindowsPath(v).is_absolute() or '..' in PureWindowsPath(v).parts
               or v.endswith(('\\', '/')) for v in values):
            raise ValueError('READINESS_SPEC_INVALID')
        code, python, state, ops = map(PureWindowsPath, values)
        if (not python.is_relative_to(code) or state.is_relative_to(code) or ops.is_relative_to(code)
                or code.is_relative_to(state) or code.is_relative_to(ops)
                or state.is_relative_to(ops) or ops.is_relative_to(state)):
            raise ValueError('READINESS_SPEC_INVALID')


@dataclass(frozen=True)
class ReadinessReport:
    status: str
    blockers: tuple[str, ...] = ()
    prepared_status: str = 'NOT_CHECKED'
    action_exact_binding_verified: bool = False
    both_tasks_enabled_verified: bool = False
    enable_deadline_status: str = 'NOT_CHECKED'
    enable_deadline: str | None = None
    next_future_slot: str | None = None
    next_expected_task_trigger: str | None = None
    supervised_slots: tuple[str, ...] = ()
    supervised_acceptance: str = 'NOT_CHECKED'
    fresh_capsule_acceptance: str = 'PENDING'
    scheduler_triggers_verified: bool = False
    producer_clock_verified: bool = False
    missing_capture_count: None = None
    local_receipt_verified: bool = False
    remote_receipt_verified: bool = False
    catchup_allowed: bool = False
    task_mutations: int = 0
    capture_writes: int = 0
    credential_reads: int = 0
    network_calls: int = 0
    waits: int = 0
    approval_authority: bool = False
    owner_step: str = 'Preview only; no readiness checks performed.'


def preview() -> ReadinessReport:
    return ReadinessReport('PREVIEW')


def _time(spec: ReadinessSpec, now: datetime) -> tuple[datetime, datetime, datetime | None]:
    if type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('AWARE_READINESS_CLOCK_REQUIRED')
    local = now.astimezone(IST)
    deadline = datetime.combine(spec.session_date, datetime.min.time(), IST).replace(hour=9, minute=30)
    # Only future *source slots*, not a just-passed bar with a still-future trigger.
    first = deadline
    next_slot = next((first + timedelta(minutes=5*i) for i in range(73)
        if first + timedelta(minutes=5*i) > local), None)
    if (next_slot is not None and
            (next_slot + timedelta(seconds=30) - local).total_seconds() > MAX_FUTURE_SECONDS):
        next_slot = None
    return local, deadline, next_slot


def assess_readiness(spec: ReadinessSpec, now: datetime, prepared_status: str,
                     task_facts: Mapping[str, object]) -> ReadinessReport:
    """Pure evaluation of read-only facts. Enabled now cannot prove earlier enable.

    Task facts must come from the strict forward_ops_host.inspect_tasks, not the
    older substring matcher. Trigger execution and supervised polls are NOT checked.
    LastTaskResult is intentionally ignored: exit zero is not a capture receipt.
    """
    spec.validate()
    local, deadline, slot = _time(spec, now)
    blockers: list[str] = []
    if prepared_status not in ('VERIFIED', 'NOT_CHECKED', 'BLOCKED'):
        prepared_status = 'BLOCKED'
    if prepared_status != 'VERIFIED':
        blockers.append('PREPARED_CONFIG_POLICY_NOT_VERIFIED')
    exact = True
    enabled = True
    confirmed_disabled = False
    for identity, mode in zip(spec.task_names, ('POLL', 'AUDIT')):
        entry = task_facts.get(identity)
        if not isinstance(entry, Mapping):
            exact = enabled = False
            blockers.append(mode + '_TASK_NOT_VERIFIED')
            continue
        if entry.get('exists') is not True or entry.get('action_matches') is not True:
            exact = False
            blockers.append(mode + '_EXACT_ACTION_BINDING_NOT_VERIFIED')
        if entry.get('enabled') is False or entry.get('disabled') is True:
            confirmed_disabled = True
        if (entry.get('exists') is not True or entry.get('enabled') is not True
                or entry.get('disabled') is not False):
            enabled = False
            blockers.append(mode + '_ENABLED_IDLE_STATE_NOT_VERIFIED')
        elif entry.get('running') is not False or entry.get('state') != 'Ready':
            blockers.append(mode + '_IDLE_STATE_NOT_VERIFIED')
    if local < deadline:
        deadline_status = 'BOTH_ENABLED_OBSERVED_BEFORE_DEADLINE' if exact and enabled else 'OWNER_ENABLE_PENDING'
    elif confirmed_disabled:
        deadline_status = 'MISSED_ENABLE_DEADLINE'
        blockers.append('MISSED_ENABLE_DEADLINE')
    elif not enabled:
        deadline_status = 'ENABLE_DEADLINE_STATE_NOT_VERIFIED'
        blockers.append(deadline_status)
    else:
        deadline_status = 'ENABLE_BEFORE_DEADLINE_NOT_ESTABLISHED'
        blockers.append(deadline_status)
    if slot is None:
        blockers.append('NO_FUTURE_SLOT_WITHIN_24_HOUR_BOUND')
    milestones = tuple((deadline - timedelta(minutes=minutes)).isoformat() for minutes in (10, 5))
    return ReadinessReport('BLOCKED' if blockers else 'TASK_READINESS_CHECKED_ACCEPTANCE_PENDING',
        tuple(blockers), prepared_status, exact, enabled, deadline_status, deadline.isoformat(),
        None if slot is None else slot.isoformat(),
        None if slot is None else (slot + timedelta(seconds=30)).isoformat(), milestones,
        owner_step='Supervise the 09:20 and 09:25 polls; after acceptance, manually enable BOTH reviewed '
        'date-pinned tasks before 09:30 IST. Missed slots stay missing; no catch-up. '
        'This read-only check never enables or runs capture.')


def guided_check(spec: ReadinessSpec, *, clock: Callable[[], datetime],
                 prepared: Callable[[ReadinessSpec], str],
                 inspect: Callable[[ReadinessSpec], Mapping[str, object]]) -> ReadinessReport:
    """One bounded pass; fixture seams have no implicit/default OS callbacks."""
    try:
        spec.validate()
        now = clock()
        _, _, slot = _time(spec, now)
    except Exception:
        return ReadinessReport('BLOCKED', ('READINESS_SPEC_OR_CLOCK_INVALID',))
    if slot is None:
        return ReadinessReport('BLOCKED', ('NO_FUTURE_SLOT_WITHIN_24_HOUR_BOUND',))
    issues: list[str] = []
    try:
        prepared_status = prepared(spec)
    except Exception:
        prepared_status = 'BLOCKED'
        issues.append('PREPARED_READ_ONLY_CHECK_UNAVAILABLE')
    try:
        facts = inspect(spec)
    except Exception:
        facts = {}
        issues.append('TASK_READ_ONLY_CHECK_UNAVAILABLE')
    try:
        fresh = clock()
        _time(spec, fresh)
        if fresh.astimezone(timezone.utc) < now.astimezone(timezone.utc):
            return ReadinessReport('BLOCKED', ('READINESS_CLOCK_MOVED_BACKWARDS',))
    except Exception:
        return ReadinessReport('BLOCKED', ('READINESS_CLOCK_REFRESH_UNAVAILABLE',))
    try:
        result = assess_readiness(spec, fresh, prepared_status, facts)
    except Exception:
        return ReadinessReport('BLOCKED', ('READ_ONLY_FACTS_INVALID',))
    if issues:
        from dataclasses import replace
        result = replace(result, status='BLOCKED', blockers=(*result.blockers, *issues))
    return result


def _prepared(spec: ReadinessSpec) -> str:
    """Explicit capsule only, existing bounded reader/validator; never Producer."""
    import sys
    from forward_revision_evidence import private_read
    from forward_nifty_producer import validate_config
    from forward_versioned_producer import validate_recipe
    from forward_session_ops import separate
    code = Path(spec.code_directory)
    root, ops = Path(spec.state_root), Path(spec.ops_root)
    if (Path(__file__).resolve().parent != code.resolve()
            or Path(sys.executable).resolve() != Path(spec.python_executable).resolve()):
        raise ValueError('READINESS_RUNTIME_BINDING_INVALID')
    separate(root, ops)
    base = root / spec.session_date.isoformat()
    config = json.loads(private_read(base / 'config.json', PREPARED_BYTES), object_pairs_hook=_pairs)
    policy = json.loads(private_read(base / 'state/versioned-v1/recipe.json', PREPARED_BYTES), object_pairs_hook=_pairs)
    validate_config(config, code)
    validate_recipe(config, policy, code)
    opening = datetime.fromisoformat(config['session_open']).astimezone(IST)
    if opening.date() != spec.session_date:
        raise ValueError('READINESS_PREPARED_DATE_INVALID')
    return 'VERIFIED'


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise ValueError('PREPARED_JSON_DUPLICATE_FIELD')
        result[key] = value
    return result


def _inspect(spec: ReadinessSpec) -> Mapping[str, object]:
    from forward_ops_host import inspect_tasks
    poll, audit = spec.task_names
    result = inspect_tasks(spec.session_date, poll, audit, Path(spec.state_root), Path(spec.ops_root))
    return cast(Mapping[str, object], result)


def main(argv: list[str] | None = None) -> int:
    """Single guided command; all parameters and reads require explicit opt-in.

    python forward_morning_readiness.py --allow-read-only --session-date YYYY-MM-DD
      --code-directory CODE --python-executable PYTHON --state-root STATE --ops-root OPS
    No confirmation means preview before date parsing, callbacks, imports or clock.
    No command enables tasks; callbacks have one existing 12-second host-query bound.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-read-only', action='store_true')
    for argument in ('session-date', 'code-directory', 'python-executable', 'state-root', 'ops-root'):
        parser.add_argument('--' + argument, default='')
    args = parser.parse_args(argv)
    if not args.allow_read_only:
        print(json.dumps(asdict(preview()), sort_keys=True))
        return 0
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', args.session_date) is None:
            raise ValueError('READINESS_SPEC_INVALID')
        spec = ReadinessSpec(date.fromisoformat(args.session_date), args.code_directory,
            args.python_executable, args.state_root, args.ops_root)
        report = guided_check(spec, clock=lambda: datetime.now(timezone.utc), prepared=_prepared, inspect=_inspect)
    except Exception:
        report = ReadinessReport('BLOCKED', ('READINESS_SPEC_INVALID',))
    print(json.dumps(asdict(report), sort_keys=True))
    return 2 if report.status == 'BLOCKED' else 0


if __name__ == '__main__':
    raise SystemExit(main())
