"""Pure commissioning-aware self-checks. No polling, credentials or remediation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from research_integrity import IntegrityError, require_hash
from research_replay_comparison import instant

LANES = {'OFFLINE_SELF_CHECK', 'ARCHIVE', 'OPTION_CAPTURE', 'SETTLEMENT_MONITOR'}


@dataclass(frozen=True)
class Heartbeat:
    """Owner-reviewed expected deadline, not a guess from a market weekday.

    due_at must reflect the actual calendar/schedule plus explicitly reviewed
    scheduler allowance. Delayed GitHub cron is not an exchange session clock.
    last_success_at is an independently observed completion receipt, not a start,
    HTTP ping or an app page load. No receipt means no successful run is assumed.
    """

    lane: str
    commissioned: bool
    due_at: str
    last_success_at: str | None
    expected_run_at: str
    success_for: str | None

    def assess(self, now: datetime) -> dict[str, Any]:
        """No missing→zero substitution; uncommissioned work cannot report healthy."""
        if self.lane not in LANES or type(self.commissioned) is not bool or now.tzinfo is None:
            raise IntegrityError('INVALID_HEARTBEAT_POLICY')
        due = instant(self.due_at)
        run = instant(self.expected_run_at)
        if due < run:
            raise IntegrityError('DEADLINE_BEFORE_EXPECTED_RUN')
        success = instant(self.last_success_at) if self.last_success_at is not None else None
        receipt_for = instant(self.success_for) if self.success_for is not None else None
        if (success is None) != (receipt_for is None):
            raise IntegrityError('COMPLETE_RECEIPT_IDENTITY_REQUIRED')
        if success is not None and success > now:
            raise IntegrityError('FUTURE_HEARTBEAT_RECEIPT')
        if not self.commissioned:
            state = 'NOT_COMMISSIONED'
        elif success is not None and receipt_for == run and success >= run:
            state = 'COMPLETE'
        elif now <= due:
            state = 'AWAITING_DEADLINE'
        else:
            state = 'MISSED_COMPLETION'
        return {'lane': self.lane, 'state': state, 'attention_required': state == 'MISSED_COMPLETION'}


def assess(*, now: datetime, expected_hash: str | None, actual_hash: str | None,
           clock_state: str | None, heartbeats: list[Heartbeat],
           required_lanes: tuple[str, ...]) -> dict[str, Any]:
    """Build a sanitized operator report, never trading approval or auto-repair."""
    if now.tzinfo is None:
        raise IntegrityError('AWARE_CHECK_TIME_REQUIRED')
    if (not required_lanes or len(set(required_lanes)) != len(required_lanes)
            or any(lane not in LANES for lane in required_lanes)):
        raise IntegrityError('EXPLICIT_HEARTBEAT_SCOPE_REQUIRED')
    checks = []
    if expected_hash is None:
        release = 'EXPECTATION_MISSING'
    elif actual_hash is None:
        require_hash(expected_hash)
        release = 'OBSERVATION_MISSING'
    else:
        release = 'MATCH' if require_hash(expected_hash) == require_hash(actual_hash) else 'MISMATCH'
    checks.append({'check': 'RELEASE', 'state': release, 'attention_required': release != 'MATCH'})
    if clock_state not in (None, 'PASS', 'MISSING', 'STALE', 'FAILED'):
        raise IntegrityError('CLOCK_STATE_UNRECOGNIZED')
    checks.append({'check': 'CLOCK', 'state': clock_state or 'MISSING', 'attention_required': clock_state != 'PASS'})
    if len({heartbeat.lane for heartbeat in heartbeats}) != len(heartbeats):
        raise IntegrityError('DUPLICATE_HEARTBEAT_LANE')
    receipts = [heartbeat.assess(now) for heartbeat in heartbeats]
    supplied = {heartbeat.lane for heartbeat in heartbeats}
    if supplied - set(required_lanes):
        raise IntegrityError('HEARTBEAT_OUTSIDE_REVIEWED_SCOPE')
    receipts.extend({'lane': lane, 'state': 'MISSING_POLICY', 'attention_required': True}
                    for lane in required_lanes if lane not in supplied)
    incomplete = not receipts or any(receipt['state'] != 'COMPLETE' for receipt in receipts)
    attention = any(check['attention_required'] for check in checks) or any(
        receipt['attention_required'] for receipt in receipts)
    return {'version': 'automation-health-v1', 'required_lanes': list(required_lanes),
            'status': 'ATTENTION_REQUIRED' if attention else 'NOT_FULLY_VERIFIED' if incomplete else 'CHECKS_PASS',
            'checks': checks, 'heartbeats': receipts, 'approval_authority': False,
            'automatic_actions': [], 'live_broker_validation': False}
