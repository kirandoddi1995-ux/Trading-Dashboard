"""Pure allow-listed next-session operations plan, NOT an execution capability.

No arbitrary commands, credentials, date rollover, automatic attestation or trade.
Existing pinned daily owner coordinator remains the only execution authority.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import json
from typing import Any

ACTIONS = ('Setup', 'Prepare', 'Start', 'Audit', 'Status', 'AlertDrill')


def plan(day: date, action: str, now: datetime, calendar_kind: str,
         token_expires_at: datetime | None = None) -> dict[str, Any]:
    if action not in ACTIONS or now.utcoffset() is None:
        raise ValueError('RUNNER_INPUT_INVALID')
    if token_expires_at is not None and token_expires_at.utcoffset() is None:
        raise ValueError('TOKEN_EXPIRY_TIMEZONE_REQUIRED')
    from datetime import timezone
    local = now.astimezone(timezone(timedelta(hours=5, minutes=30)))
    blockers = []
    if calendar_kind != 'REGULAR':
        blockers.append('REVIEWED_REGULAR_CALENDAR_REQUIRED')
    if not timedelta(0) <= day-local.date() <= timedelta(days=7):
        blockers.append('DATE_OUTSIDE_REVIEW_WINDOW')
    seconds = (token_expires_at-now).total_seconds() if token_expires_at else None
    warning = 'EXPIRY_NOT_RECORDED'
    if seconds is not None:
        warning = 'EXPIRED' if seconds <= 0 else 'RENEWAL_DUE_WITHIN_30_DAYS' if seconds <= 30*86400 else 'NOT_DUE'
    return dict(status='BLOCKED' if blockers else 'PLAN_ONLY_NOT_OPERATIONAL_GO',
        session_date=day.isoformat(), action=action, blockers=blockers,
        reviewed_entrypoint='forward_daily_owner.ps1' if action in ACTIONS[:4] else 'SEPARATE_OBSERVER',
        required_attestations={'Prepare': ['ACTUAL_FRESH_DOWNLOAD', 'ATTEST_NSE_SOURCE'],
            'Start': ['OWNER_SAW_NOTIFICATION', 'ENABLE_ONLY_AFTER_TWO_VERIFIED_POLLS'],
            'AlertDrill': ['AFTER_SESSION', 'NO_CAPTURE_RUNNING']}.get(action, []),
        token_expiry_status=warning, token_expiry_source='OWNER_DATE_NOT_TOKEN_CONTENT',
        future_setup_allowed_only_disabled=True, command_execution=False,
        automatic_attestation=False, task_enable_operations=0, actual_task_state='NOT_OBSERVED', clock_gate_bypassed=False,
        session_calendar_commissioned=False, approval_authority=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session-date', required=True, type=date.fromisoformat)
    parser.add_argument('--action', required=True, choices=ACTIONS)
    parser.add_argument('--calendar-kind', choices=('REGULAR', 'CLOSED', 'UNKNOWN'), default='UNKNOWN')
    parser.add_argument('--token-expires-at', type=datetime.fromisoformat)
    args = parser.parse_args(argv)
    try:
        from datetime import timezone
        result = plan(args.session_date, args.action, datetime.now(timezone.utc),
                      args.calendar_kind, args.token_expires_at)
    except ValueError:
        result = dict(status='BLOCKED', code='RUNNER_INPUT_INVALID', command_execution=False)
    print(json.dumps(result))
    return 2 if result['status'] == 'BLOCKED' else 0


if __name__ == '__main__':
    raise SystemExit(main())
