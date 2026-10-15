"""Pure daily-owner gates; no file, clock, credential, task or network access.

This wrapper never changes the reviewed producer's eligibility or clock rules.
Calendar and receipt inputs are observations from that exact capsule, not proofs
created by this module. It cannot commission capture or turn on training.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
import re
from typing import Any

IST = timezone(timedelta(hours=5, minutes=30))
BASE = '1251530731cce5b75fad8601567b9320d07b710d'
CODES = frozenset({'SESSION_DATE_INVALID', 'AWARE_TIME_REQUIRED', 'DAILY_INPUT_INVALID',
    'NORMAL_NON_ADMIN_WINDOW_REQUIRED', 'REVIEWED_REGULAR_SESSION_REQUIRED',
    'SETUP_DATE_OUTSIDE_REVIEW_WINDOW', 'PREOPEN_DEADLINE_MISSED',
    'SESSION_DATE_MISMATCH', 'POSTSESSION_AUDIT_ONLY',
    'FIRST_START_DEADLINE_MISSED_NO_RETRY', 'ACTUAL_DOWNLOAD_TIMESTAMP_REQUIRED',
    'FRESH_SESSION_MORNING_DOWNLOAD_REQUIRED'})


def session(value: str) -> date:
    """Require a canonical explicit date, never infer today's session."""
    if type(value) is not str or re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) is None:
        raise ValueError('SESSION_DATE_INVALID')
    return date.fromisoformat(value)


def aware(value: str) -> datetime:
    """Parse an explicit timestamp with timezone; naive clocks are unusable."""
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError('AWARE_TIME_REQUIRED')
    return result.astimezone(IST)


def plan(day: date) -> dict[str, Any]:
    """Date-derived identities only; no calendar/host readiness inferred."""
    stamp = day.strftime('%Y%m%d')
    return dict(status='PREVIEW', session_date=day.isoformat(), reviewed_commit=BASE,
        capsule_name='kiran_forward_' + stamp,
        poll_task='KiranTrading-Versioned-' + stamp + '-poll',
        audit_task='KiranTrading-Versioned-' + stamp + '-audit',
        preparation_deadline=day.isoformat() + 'T09:15:00+05:30',
        first_poll=day.isoformat() + 'T09:20:30+05:30',
        second_poll=day.isoformat() + 'T09:25:30+05:30',
        enable_deadline=day.isoformat() + 'T09:30:00+05:30',
        calendar_verified=False, writes=0, network_calls=0, credential_reads=0,
        approval_authority=False, training_eligible=False)


def gate(day: date, now: datetime, action: str, *, calendar_kind: str,
         elevated: bool, downloaded: datetime | None = None) -> None:
    """Fail closed on owner context and missed deadlines, including DST/IST dates."""
    if (type(day) is not date or type(now) is not datetime or now.utcoffset() is None
            or type(elevated) is not bool or action not in {'Setup', 'Prepare', 'Start', 'Audit'}):
        raise ValueError('DAILY_INPUT_INVALID')
    local = now.astimezone(IST)
    if elevated:
        raise ValueError('NORMAL_NON_ADMIN_WINDOW_REQUIRED')
    if calendar_kind != 'REGULAR':
        raise ValueError('REVIEWED_REGULAR_SESSION_REQUIRED')
    if action == 'Setup':
        if not timedelta(0) <= day - local.date() <= timedelta(days=7):
            raise ValueError('SETUP_DATE_OUTSIDE_REVIEW_WINDOW')
        if local.date() == day and local.time() >= time(9, 15):
            raise ValueError('PREOPEN_DEADLINE_MISSED')
        return
    if local.date() != day:
        if not (action == 'Audit' and local.date() > day):
            raise ValueError('SESSION_DATE_MISMATCH')
    if action == 'Audit':
        if local < datetime.combine(day, time(15, 40), IST):
            raise ValueError('POSTSESSION_AUDIT_ONLY')
        return
    if action == 'Start':
        if local >= datetime.combine(day, time(9, 20, 30), IST):
            raise ValueError('FIRST_START_DEADLINE_MISSED_NO_RETRY')
        return
    if local.time() >= time(9, 15):
        raise ValueError('PREOPEN_DEADLINE_MISSED')
    if downloaded is None or downloaded.utcoffset() is None:
        raise ValueError('ACTUAL_DOWNLOAD_TIMESTAMP_REQUIRED')
    observed = downloaded.astimezone(IST)
    if observed.date() != day or observed > local:
        raise ValueError('FRESH_SESSION_MORNING_DOWNLOAD_REQUIRED')


def accepted_poll(report: object, expected: int) -> bool:
    """Require the existing success contract, exact fresh-session counts, no defaults."""
    if type(report) is not dict or type(expected) is not int or expected not in (1, 2):
        return False
    return (report.get('status') == 'POLL_REMOTE_VERIFIED'
        and report.get('exit_code') == 0 and type(report.get('exit_code')) is int
        and report.get('code') == 'REMOTE_VERIFICATION_COMPLETE'
        and report.get('capture_status') == 'VERSIONED_OBSERVATION_RECORDED'
        and report.get('decision_recorded_this_poll') is True
        and all(report.get(key) is True for key in
                ('local_poll_committed', 'remote_verified', 'receipt_written'))
        and type(report.get('recorded_decisions')) is int
        and report['recorded_decisions'] == expected
        and type(report.get('missing_decisions')) is int
        and report['missing_decisions'] == 75 - expected
        and report.get('clock_problem') == 'PASS'
        and report.get('retries') == 0 and type(report.get('retries')) is int
        and report.get('approval_authority') is False
        and report.get('training_eligible') is False)


def accepted_admission_health(report: object, poll: str, audit: str,
                              minimum_bytes: int) -> bool:
    """Require literal fresh health facts while both reviewed tasks are disabled."""
    if (type(report) is not dict or type(minimum_bytes) is not int
            or minimum_bytes < 1024**3 or type(poll) is not str or type(audit) is not str
            or re.fullmatch(r'KiranTrading-Versioned-[0-9]{8}-poll', poll) is None
            or audit != poll[:-4] + 'audit'
            or report.get('status') != 'PREOPEN_HOST_CHECK_PASSED'
            or type(report.get('blockers')) is not list or report['blockers'] != []
            or type(report.get('repairs_performed')) is not int or report['repairs_performed'] != 0
            or report.get('credentials_checked') is not False
            or report.get('provider_and_drive_health') != 'NOT_CHECKED'
            or report.get('approval_authority') is not False
            or report.get('training_eligible') is not False):
        return False
    facts = report.get('facts')
    if (type(facts) is not dict or facts.get('time_service_running') is not True
            or facts.get('time_service_automatic') is not True
            or facts.get('clock_check') != 'PASS'):
        return False
    for field in ('free_bytes', 'capture_volume_free_bytes'):
        if type(facts.get(field)) is not int or facts[field] < minimum_bytes:
            return False
    for name in (poll, audit):
        task = facts.get(name)
        if (type(task) is not dict or task.get('exists') is not True
                or task.get('action_matches') is not True
                or task.get('enabled') is not False or task.get('disabled') is not True
                or task.get('running') is not False or task.get('state') != 'Disabled'):
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    """Preview by default; explicit pure input evaluation uses no OS adapters."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session-date', required=True)
    parser.add_argument('--evaluate', choices=('Setup', 'Prepare', 'Start', 'Audit'))
    parser.add_argument('--at', default='')
    parser.add_argument('--calendar-kind', default='UNVERIFIED')
    parser.add_argument('--elevated', action='store_true')
    parser.add_argument('--download-at', default='')
    args = parser.parse_args(argv)
    try:
        day = session(args.session_date)
        result = plan(day)
        if args.evaluate:
            gate(day, aware(args.at), args.evaluate, calendar_kind=args.calendar_kind,
                 elevated=args.elevated,
                 downloaded=aware(args.download_at) if args.download_at else None)
            result['status'] = 'PURE_INPUT_GATE_PASSED_NOT_HOST_ACCEPTANCE'
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        code = str(error) if isinstance(error, ValueError) and str(error) in CODES else 'DAILY_INPUT_REVIEW_REQUIRED'
        print(json.dumps(dict(status='BLOCKED', code=code,
            approval_authority=False, raw_error_printed=False)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
