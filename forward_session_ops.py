"""Additive future-session operations. Preview has zero IO; frozen capture unchanged."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta, timezone
import io
import json
from pathlib import Path
from typing import Any, Callable, cast
import uuid

from automated_development_checks import write_once
from forward_ops_host import notify, preflight, task_name
from forward_revision_evidence import private_read
from research_integrity import digest
from research_replay_comparison import instant


def separate(root: Path, ops: Path) -> None:
    """Operations reports must not mutate or alias capture or source directories."""
    code = Path(__file__).resolve().parent
    if (not root.is_absolute() or not ops.is_absolute()
            or any(p.is_symlink() or p.is_junction() for path in (root, ops) for p in (path, *path.parents))
            or root.resolve().is_relative_to(code) or ops.resolve().is_relative_to(code)
            or ops.resolve().is_relative_to(root.resolve()) or root.resolve().is_relative_to(ops.resolve())):
        raise ValueError('SEPARATE_PRIVATE_OPERATIONS_ROOT_REQUIRED')


def coverage(bundle: dict[str, Any]) -> dict[str, Any]:
    """Projection of a VERIFIED bundle: gaps are never zeros, labels or fake decisions."""
    opening = instant(bundle['config']['session_open'])
    slots = [(opening + timedelta(minutes=5*i)).isoformat() for i in range(1, 76)]
    polls = {instant(p['source']['slot']).isoformat(): p for p in bundle['polls']}
    rows = [{'slot': slot, 'status': 'MISSING_NOT_OBSERVED' if slot not in polls else
             'RAW_ONLY_NO_DECISION' if polls[slot]['decision'] is None else 'OBSERVED_DECISION'} for slot in slots]
    return {'status': 'VERSIONED_COVERAGE_COMPLETE' if bundle['missing_decisions'] == 0 else 'VERSIONED_COVERAGE_INCOMPLETE',
            'raw_polls': len(polls), 'recorded_decisions': bundle['recorded_decisions'],
            'missing_decisions': bundle['missing_decisions'], 'expected_decisions': 75,
            'slots': rows, 'operational_cause_per_slot': 'NOT_ESTABLISHED',
            'coverage_requirement_met': bundle['missing_decisions'] == 0,
            'full_session_cohort_eligible': False,
            'training_eligible': False, 'approval_authority': False,
            'remote_custody_verified': False, 'backfill_allowed': False}


def audit(root: Path, day: date, now: datetime) -> dict[str, Any]:
    """Paused, SELECT-only replay; never invokes the writable Producer constructor."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('AWARE_AUDIT_TIME_REQUIRED')
    from forward_versioned_capture import paths
    from overnight_capture_audit import journal_bytes
    config_path, recipe_path, journal = paths(root, day)
    config = json.loads(private_read(config_path))
    from zoneinfo import ZoneInfo
    ist = ZoneInfo('Asia/Kolkata')
    if now.astimezone(ist).date() < day or instant(config['session_open']).astimezone(ist).date() != day:
        raise ValueError('AUDIT_SESSION_DATE_MISMATCH')
    if now < instant(config['session_close']) + timedelta(minutes=10):
        raise ValueError('AUDIT_1540_OR_LATER_REQUIRED')
    frozen = json.loads(private_read(recipe_path))
    raw = journal_bytes(journal, config, frozen)
    return {**coverage(json.loads(raw)), 'generation_sha256': digest(raw), 'capture_writes': 0}


def poll(root: Path, day: date) -> dict[str, Any]:
    """Run one original gated poll; preserve the exact clock evidence, never retry."""
    import forward_nifty_job as job
    import forward_versioned_capture as capture
    original = cast(Callable[[], dict[str, Any]], getattr(job, 'measure_clock'))
    check_clock = cast(Callable[..., str | None], getattr(job, 'clock_error'))
    clock: dict[str, Any] = {}
    def measured() -> Any:
        result = original()
        # Allowlisted public codes only. No host names, packet bytes or OS text.
        problem = check_clock(result, now=datetime.now(timezone.utc), maximum_offset=1.0)
        clock['clock_problem'] = problem if problem in {'CLOCK_MEASUREMENT_UNAVAILABLE', 'CLOCK_MEASUREMENT_STALE',
            'CLOCK_MEASUREMENT_INVALID', 'CLOCK_OFFSET_OR_UNCERTAINTY_EXCESSIVE'} else 'PASS' if problem is None else 'CLOCK_MEASUREMENT_INVALID'
        reason = result.get('reason')
        clock['probe_reason'] = reason if reason in {'CLOCK_PROBE_BUSY', 'CLOCK_PROBE_TIMEOUT', 'CLOCK_PROBE_FAILED'} else None
        return result
    output = io.StringIO()
    try:
        setattr(job, 'measure_clock', measured)
        with redirect_stdout(output):
            code = capture.run(root, day, 'poll')
    finally:
        setattr(job, 'measure_clock', original)
    reports: list[dict[str, Any]] = []
    for line in output.getvalue().splitlines():
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                reports.append(value)
        except ValueError:
            pass
    last: dict[str, Any] = next((r for r in reversed(reports) if r.get('status') in {'REMOTE_VERIFIED', 'BLOCKED'}), {})
    allowed = {'CLOCK_UNVERIFIED', 'AUTH_REQUIRED', 'LICENSE_ACK_REQUIRED', 'OUTSIDE_COLLECTION_SESSION',
               'FORWARD_CAPTURE_FAILED', 'MISSED_OR_OUTSIDE_POLL_SLOT', 'SESSION_NOT_PREPARED',
               'PRIVATE_CREDENTIAL_REQUIRED', 'SCHEDULER_BLOCKED', 'FORWARD_CONFIG_MISMATCH'}
    stages = {'AUTHORIZATION', 'CLOCK_CHECK', 'LOCAL_CAPTURE_OPEN', 'DRIVE_CONFIGURATION',
              'MARKET_DATA_READ', 'LOCAL_RECORD_POLL', 'DRIVE_FOLDER_CHECK',
              'DRIVE_PUBLISH_VERIFY', 'LOCAL_RECEIPT_WRITE', 'DRIVE_CLOSE', 'LOCAL_BACKUP_BUNDLE'}
    categories = {'UNCLASSIFIED_FAILURE', 'DRIVE_AUTH_REFRESH_FAILED', 'TLS_FAILED',
        'TRANSPORT_TIMEOUT', 'TRANSPORT_FAILED', 'CLOSED_BAR_REVISION_REVIEW_REQUIRED',
        'DRIVE_HTTP_401', 'DRIVE_HTTP_403', 'DRIVE_HTTP_404', 'DRIVE_HTTP_429',
        'DRIVE_HTTP_500', 'DRIVE_HTTP_502', 'DRIVE_HTTP_503', 'DRIVE_HTTP_504',
        'FORWARD_REMOTE_VERIFICATION_FAILED', 'FORWARD_MANIFEST_VERIFICATION_FAILED',
        'VERSION_POLICY_VALIDATION_FAILED'}
    # The reviewed job prints this terminal contract only after record_poll,
    # publication, receipt write and Drive close have all returned successfully.
    # It is a process report, NOT an independent custody/restore attestation.
    recorded, missing = last.get('recorded_decisions'), last.get('missing_decisions')
    verified = (type(code) is int and code == 0 and last.get('status') == 'REMOTE_VERIFIED'
                and last.get('capture_status') in {'VERSIONED_OBSERVATION_RECORDED', 'VERSIONED_INPUT_BLOCKED'}
                and type(recorded) is int and type(missing) is int
                and 0 <= recorded <= 75 and 0 <= missing <= 75 and recorded + missing == 75
                and last.get('approval_authority') is False
                and all(field not in last or last[field] is True
                        for field in ('local_poll_committed', 'remote_verified', 'receipt_written')))
    if verified:
        return {'status': 'POLL_REMOTE_VERIFIED', 'exit_code': 0,
                'code': 'REMOTE_VERIFICATION_COMPLETE', 'stage': 'LOCAL_RECEIPT_CONFIRMED',
                'category': 'NONE', 'capture_status': last['capture_status'],
                'recorded_decisions': recorded, 'missing_decisions': missing,
                'decision_recorded_this_poll': last['capture_status'] == 'VERSIONED_OBSERVATION_RECORDED',
                'local_poll_committed': True, 'remote_verified': True, 'receipt_written': True,
                'proof_basis': 'REVIEWED_PRODUCER_TERMINAL_CONTRACT', 'remote_custody_verified': False,
                **clock, 'retries': 0, 'approval_authority': False, 'training_eligible': False}
    window_block = last.get('code') == 'MISSED_OR_OUTSIDE_POLL_SLOT'
    return {'status': 'BLOCKED',
            'exit_code': code, 'code': last.get('code') if last.get('code') in allowed else 'POLL_REVIEW_REQUIRED',
            'stage': 'POLL_SLOT_GATE' if window_block else last.get('stage') if last.get('stage') in stages else 'NOT_ESTABLISHED',
            'category': 'POLL_WINDOW_REVIEW_REQUIRED' if window_block else last.get('category') if last.get('category') in categories else 'REVIEW_REQUIRED',
            'local_poll_committed': False if window_block else last.get('local_poll_committed') if isinstance(last.get('local_poll_committed'), bool) else None,
            'remote_verified': False if window_block else last.get('remote_verified') if isinstance(last.get('remote_verified'), bool) else None,
            'receipt_written': False if window_block else last.get('receipt_written') if isinstance(last.get('receipt_written'), bool) else None,
            **clock, 'retries': 0, 'approval_authority': False, 'training_eligible': False}


def save(ops: Path, day: date, result: dict[str, Any], *, visible: bool) -> None:
    """Append reports; separate causes, bounded launch retries, never claim delivery."""
    ops.mkdir(parents=True, exist_ok=True)
    report = {**result, 'session_date': day.isoformat(), 'observed_at': datetime.now(timezone.utc).isoformat()}
    write_once(ops / (day.isoformat() + '-' + uuid.uuid4().hex + '.json'), report)
    if result['status'] not in {'BLOCKED', 'VERSIONED_COVERAGE_INCOMPLETE'} or not visible:
        return
    category = ('POLL_WINDOW_REVIEW_REQUIRED' if result.get('code') == 'MISSED_OR_OUTSIDE_POLL_SLOT' else
                'CLOCK_REVIEW_REQUIRED' if result.get('code') == 'CLOCK_UNVERIFIED' else
                'PREOPEN_REVIEW_REQUIRED' if 'blockers' in result else
                'COVERAGE_REVIEW_REQUIRED' if result['status'] == 'VERSIONED_COVERAGE_INCOMPLETE' else
                'OPERATIONS_REVIEW_REQUIRED' if result.get('code') == 'OPERATIONS_REVIEW_REQUIRED' else
                'CAPTURE_REVIEW_REQUIRED')
    # New namespace does not overwrite or trust old day/category markers.
    # Hash only bounded public tokens; no raw error, credentials or path data.
    tokens = [result.get(k) for k in ('code', 'stage', 'category')]
    safe = [v if isinstance(v, str) and len(v) <= 80 and all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789' for c in v)
            else 'NOT_ESTABLISHED' for v in tokens]
    identity = digest(json.dumps(safe).encode())[:16]
    for attempt in range(1, 4):
        marker = ops / f'{day.isoformat()}-v2-{category}-{identity}-{attempt}.alert'
        completed = marker.with_suffix('.launch')
        if any(p.is_symlink() or p.is_junction() for p in (marker, completed)):
            raise ValueError('OPERATIONS_ALERT_PATH_INVALID')
        if marker.exists():
            # Unknown interrupted launch is not silently retried. A confirmed
            # launch failure can retry at most twice on later invocations.
            if not completed.is_file():
                return
            with completed.open('rb') as stream:
                if stream.read(65) not in (b'LAUNCH_FAILED\n', b'LAUNCH_FAILED\r\n'):
                    return
            continue
        try:
            with marker.open('x', encoding='utf-8') as stream:
                stream.write('LOCAL_NOTIFICATION_LAUNCH_PENDING_NOT_DELIVERY_PROOF\n')
        except FileExistsError:
            return
        try:
            launched = notify(category) is True
        except Exception:
            launched = False
        with completed.open('x', encoding='utf-8') as stream:
            stream.write('LAUNCHED_NOT_DELIVERY_PROOF\n' if launched else 'LAUNCH_FAILED\n')
        return


def main(argv: list[str] | None = None) -> int:
    """No OS/state access on preview; no task changes, catch-up or clock self-healing."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--ops-root', required=True, type=Path)
    parser.add_argument('--session-date', required=True, type=date.fromisoformat)
    parser.add_argument('--mode', choices=('preflight', 'poll', 'audit'), required=True)
    parser.add_argument('--poll-task', default='KiranTrading-Forward-poll')
    parser.add_argument('--audit-task', default='KiranTrading-Forward-audit')
    parser.add_argument('--confirm-ops', action='store_true')
    parser.add_argument('--notify-local', action='store_true')
    parser.add_argument('--read-only-audit', action='store_true')
    args = parser.parse_args(argv)
    if not args.confirm_ops:
        print(json.dumps({'status': 'PREVIEW', 'network_calls': 0, 'credential_reads': 0, 'writes': 0}))
        return 0
    result: dict[str, Any]
    paths_validated = False
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(timezone.utc)
        if args.read_only_audit and args.mode != 'audit':
            raise ValueError('READ_ONLY_AUDIT_MODE_REQUIRED')
        today = now.astimezone(ZoneInfo('Asia/Kolkata')).date()
        if args.session_date > today or (args.mode != 'audit' and today != args.session_date):
            raise ValueError('OPERATIONS_DATE_MISMATCH')
        separate(args.root, args.ops_root)
        paths_validated = True
        if args.mode == 'preflight':
            if now.astimezone(ZoneInfo('Asia/Kolkata')).time().replace(tzinfo=None) >= datetime.min.time().replace(hour=9, minute=15):
                raise ValueError('PREOPEN_CHECK_REQUIRED')
            result = preflight(args.session_date, task_name(args.poll_task), task_name(args.audit_task),
                               args.ops_root.parent, root=args.root, ops=args.ops_root)
        elif args.mode == 'poll':
            result = poll(args.root, args.session_date)
        else:
            result = audit(args.root, args.session_date, now)
        if not args.read_only_audit:
            save(args.ops_root, args.session_date, result, visible=args.notify_local)
    except Exception:
        result = {'status': 'BLOCKED', 'code': 'OPERATIONS_REVIEW_REQUIRED', 'raw_error_printed': False,
                  'approval_authority': False, 'training_eligible': False}
        # Reports only, outside the capture. Deduplicate alerts even on audit failure.
        if paths_validated and not args.read_only_audit:
            try:
                save(args.ops_root, args.session_date, result, visible=args.notify_local)
            except Exception:
                if args.notify_local:
                    # Without durable storage there is no safe deduplication proof.
                    notify('OPERATIONS_REPORT_UNAVAILABLE')
    print(json.dumps(result))
    return 2 if result['status'] == 'BLOCKED' else 1 if result['status'] == 'VERSIONED_COVERAGE_INCOMPLETE' else 0


if __name__ == '__main__':
    raise SystemExit(main())
