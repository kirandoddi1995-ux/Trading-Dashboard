"""Inactive, pure morning deadline routing; never prepares, polls or enables tasks.

Explicit aware time and observed milestones are inputs, not acceptance proofs.
Without --review-plan the CLI previews before calendar/time parsing or any I/O.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import json
from typing import Any, Callable, cast

from nifty_session_calendar import cash_session

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass(frozen=True)
class MorningFacts:
    """Owner observations only; booleans cannot commission or prove capture."""

    prepared: bool = False
    policy_frozen: bool = False
    first_poll_verified: bool = False
    second_poll_verified: bool = False
    tasks_ready: bool = False


@dataclass(frozen=True)
class Route:
    status: str
    next_step: str
    reason: str
    target_at: str | None = None
    catchup_allowed: bool = False
    writes: int = 0
    task_changes: int = 0
    network_calls: int = 0
    credential_reads: int = 0
    approval_authority: bool = False


def route(day: date, now: datetime, facts: MorningFacts) -> Route:
    """Reject missed milestones rather than treating late flags as earlier proof.

    At/after 09:15 no new preparation. Supervised starts belong to exactly the
    09:20:30 and 09:25:30 instants; once passed, the planner never proposes that
    poll. A running/unknown poll must be reconciled, not repeated. No late-day
    commissioning path is supplied by this plan.
    """
    if (type(day) is not date or type(now) is not datetime or now.utcoffset() is None
            or type(facts) is not MorningFacts
            or any(type(v) is not bool for v in asdict(facts).values())):
        raise ValueError('MORNING_ROUTE_INPUT_INVALID')
    local = now.astimezone(IST)
    if local.date() != day:
        return Route('BLOCKED', 'SELECT_REVIEWED_FUTURE_SESSION', 'SESSION_DATE_MISMATCH')
    if cast(Callable[[date], dict[str, Any]], cash_session)(day)['kind'] != 'REGULAR':
        return Route('BLOCKED', 'NO_REGULAR_SESSION_CAPTURE', 'REVIEWED_REGULAR_SESSION_REQUIRED')
    if ((facts.policy_frozen and not facts.prepared)
            or (facts.first_poll_verified and not facts.policy_frozen)
            or (facts.second_poll_verified and not facts.first_poll_verified)
            or (facts.tasks_ready and not facts.second_poll_verified)):
        return Route('BLOCKED', 'RECONCILE_OBSERVATIONS_READ_ONLY', 'MILESTONES_INCONSISTENT')
    def at(hour: int, minute: int, second: int = 0) -> datetime:
        return datetime.combine(day, datetime.min.time(), IST).replace(
            hour=hour, minute=minute, second=second)
    if ((facts.first_poll_verified and local < at(9, 20, 30))
            or (facts.second_poll_verified and local < at(9, 25, 30))):
        return Route('BLOCKED', 'RECONCILE_OBSERVATIONS_READ_ONLY', 'MILESTONE_TIME_CONFLICT')
    if local >= at(15, 40):
        return Route('POSTSESSION', 'READ_ONLY_AUDIT', 'GAPS_REMAIN_MISSING')
    if not facts.prepared or not facts.policy_frozen:
        if local >= at(9, 15):
            return Route('BLOCKED', 'KEEP_TASKS_DISABLED_NEXT_SESSION', 'PREOPEN_DEADLINE_MISSED')
        return Route('OWNER_ACTION_REQUIRED', 'PREPARE_AND_FREEZE_BEFORE_OPEN',
                     'NO_AFTER_OPEN_PREPARATION', at(9, 15).isoformat())
    if not facts.first_poll_verified:
        if local > at(9, 20, 30):
            return Route('PARTIAL_REHEARSAL', 'KEEP_TASKS_DISABLED_RECONCILE_OR_AUDIT',
                         'FIRST_SUPERVISED_START_MISSED_OR_UNKNOWN')
        return Route('OWNER_ACTION_REQUIRED', 'ONE_SUPERVISED_POLL_AT_TARGET',
                     'WAIT_IS_OWNER_CONTROLLED_NOT_CAPTURE_AUTHORITY', at(9, 20, 30).isoformat())
    if not facts.second_poll_verified:
        if local > at(9, 25, 30):
            return Route('PARTIAL_REHEARSAL', 'KEEP_TASKS_DISABLED_RECONCILE_OR_AUDIT',
                         'SECOND_SUPERVISED_START_MISSED_OR_UNKNOWN')
        return Route('OWNER_ACTION_REQUIRED', 'ONE_SUPERVISED_POLL_AT_TARGET',
                     'WAIT_IS_OWNER_CONTROLLED_NOT_CAPTURE_AUTHORITY', at(9, 25, 30).isoformat())
    if local >= at(9, 30):
        return Route('READ_ONLY_REVIEW', 'INSPECT_EXISTING_TASKS_AND_RECEIPTS_ONLY',
                     'EARLIER_ENABLE_AND_TRIGGER_NOT_PROVEN_BY_FLAGS')
    return Route('OWNER_ACTION_REQUIRED', 'AUDIT_ENABLE_FIRST_POLL_LAST_THEN_READINESS',
                 'EXACT_BINDINGS_RECEIPTS_AND_VISIBLE_NOTIFICATION_REQUIRED', at(9, 30).isoformat())


def main(argv: list[str] | None = None) -> int:
    """Print a pure proposal. Dates and facts are explicit; never read wall clock."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review-plan', action='store_true')
    parser.add_argument('--session-date', default='')
    parser.add_argument('--at', default='')
    for name in ('prepared', 'policy-frozen', 'first-poll-verified', 'second-poll-verified', 'tasks-ready'):
        parser.add_argument('--' + name, action='store_true')
    args = parser.parse_args(argv)
    if not args.review_plan:
        result = Route('PREVIEW', 'NO_ACTION', 'ZERO_IO_NO_FACTS_CHECKED')
    else:
        try:
            result = route(date.fromisoformat(args.session_date), datetime.fromisoformat(args.at),
                MorningFacts(args.prepared, args.policy_frozen, args.first_poll_verified,
                             args.second_poll_verified, args.tasks_ready))
        except Exception:
            result = Route('BLOCKED', 'REVIEW_INPUTS', 'MORNING_ROUTE_INPUT_INVALID')
    print(json.dumps(asdict(result), sort_keys=True))
    return 2 if result.status in {'BLOCKED', 'PARTIAL_REHEARSAL'} else 0


if __name__ == '__main__':
    raise SystemExit(main())
