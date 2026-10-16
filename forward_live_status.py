"""Opt-in metadata-only observer. Never opens config, journal, inputs or credentials.

Reports are unsigned process claims, not independent custody or decision evidence.
No command execution, retries, polling loop, notification or writes. Default inert.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, TypeGuard

IST = timezone(timedelta(hours=5, minutes=30))
MAX_FILES = 1024
MAX_ENTRIES = 65536
MAX_BYTES = 32768
DAY_JSON = re.compile(r'\d{4}-\d{2}-\d{2}-[a-f0-9]{32}\.json')
RECEIPT_JSON = re.compile(r'(?:receipt|failure)-[a-f0-9]{32}\.json')


class StatusError(ValueError):
    """Only fixed public errors may reach output."""


def _path(path: Path) -> Path:
    if not path.is_absolute() or str(path).startswith(('\\\\', '//')):
        raise StatusError('LOCAL_ABSOLUTE_PATH_REQUIRED')
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise StatusError('LINK_PATH_REJECTED')
    return path.resolve()


def _directory(path: Path, pattern: re.Pattern[str], prefix: str = '') -> tuple[list[dict[str, Any]], int]:
    """Bound names before opening. In-flight JSON is incomplete, never a success."""
    _path(path)
    if not path.is_dir():
        return [], 0
    names: list[Path] = []
    entries = 0
    with os.scandir(path) as scan:
        for entry in scan:
            entries += 1
            if entries > MAX_ENTRIES:
                raise StatusError('DIRECTORY_ENTRY_BOUND_EXCEEDED')
            if pattern.fullmatch(entry.name) and entry.name.startswith(prefix):
                names.append(path / entry.name)
                if len(names) > MAX_FILES:
                    raise StatusError('SELECTED_FILE_BOUND_EXCEEDED')
    values: list[dict[str, Any]] = []
    incomplete = 0
    for file in names:
        _path(file)
        if not file.is_file():
            raise StatusError('METADATA_FILE_REQUIRED')
        try:
            before = file.lstat()
            if not stat.S_ISREG(before.st_mode):
                raise StatusError('REGULAR_METADATA_REQUIRED')
            if before.st_size > MAX_BYTES:
                raise StatusError('METADATA_FILE_BOUND_EXCEEDED')
            descriptor = os.open(file, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
            try:
                opened = os.fstat(descriptor)
                if (not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino)
                        != (before.st_dev, before.st_ino)):
                    raise StatusError('METADATA_FILE_IDENTITY_CHANGED')
                _path(file)
                blocks = bytearray()
                while len(blocks) <= MAX_BYTES:
                    block = os.read(descriptor, MAX_BYTES + 1 - len(blocks))
                    if not block:
                        break
                    blocks.extend(block)
                raw = bytes(blocks)
                after = os.fstat(descriptor)
            finally:
                os.close(descriptor)
            if (len(raw) > MAX_BYTES or len(raw) != opened.st_size
                    or (opened.st_size, opened.st_mtime_ns, opened.st_ino)
                    != (after.st_size, after.st_mtime_ns, after.st_ino)):
                incomplete += 1
                continue
            value = json.loads(raw, object_pairs_hook=_unique)
            if type(value) is not dict:
                incomplete += 1
            else:
                values.append(value)
        except StatusError:
            raise
        except (OSError, ValueError):
            incomplete += 1
    return values, incomplete


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def _count(value: Any) -> TypeGuard[int]:
    return type(value) is int and 0 <= value <= 75


def observe(root: Path, ops: Path, day: date, now: datetime) -> dict[str, Any]:
    """Single bounded read; counts only, no journal interpretation or enable authority."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise StatusError('AWARE_OBSERVER_TIME_REQUIRED')
    local = now.astimezone(IST)
    if local.date() != day:
        raise StatusError('SAME_DAY_OBSERVER_REQUIRED')
    source = Path(__file__).resolve().parent
    left, right = _path(root), _path(ops)
    if (left.is_relative_to(source) or right.is_relative_to(source)
            or left.is_relative_to(right) or right.is_relative_to(left)):
        raise StatusError('SEPARATE_PRIVATE_ROOTS_REQUIRED')
    reports, incomplete = _directory(ops, DAY_JSON, day.isoformat())
    receipts, receipt_incomplete = _directory(
        left / day.isoformat() / 'state/versioned-v1/receipts', RECEIPT_JSON)
    accepted = 0
    blocked = 0
    invalid = 0
    timestamps: list[datetime] = []
    codes: dict[str, int] = {}
    counts: list[int] = []
    identities: dict[tuple[str, str], int] = {}
    for report in reports:
        try:
            stamp = datetime.fromisoformat(report['observed_at'])
            if (stamp.utcoffset() is None or stamp > now or stamp.astimezone(IST).date() != day
                    or report.get('session_date') != day.isoformat()):
                raise ValueError
            status = report.get('status')
            if status not in {'POLL_REMOTE_VERIFIED', 'BLOCKED'}:
                continue
            timestamps.append(stamp)
            if status == 'POLL_REMOTE_VERIFIED':
                n, missing = report.get('recorded_decisions'), report.get('missing_decisions')
                if (not _count(n) or not _count(missing) or n + missing != 75
                        or report.get('exit_code') != 0 or type(report.get('exit_code')) is not int
                        or report.get('clock_problem') != 'PASS' or report.get('retries') != 0
                        or type(report.get('retries')) is not int
                        or report.get('code') != 'REMOTE_VERIFICATION_COMPLETE'
                        or report.get('stage') != 'LOCAL_RECEIPT_CONFIRMED'
                        or report.get('category') != 'NONE'
                        or report.get('capture_status') not in {'VERSIONED_OBSERVATION_RECORDED', 'VERSIONED_INPUT_BLOCKED'}
                        or report.get('decision_recorded_this_poll') is not
                            (report.get('capture_status') == 'VERSIONED_OBSERVATION_RECORDED')
                        or report.get('approval_authority') is not False
                        or report.get('training_eligible') is not False
                        or any(report.get(k) is not True for k in
                               ('remote_verified', 'receipt_written', 'local_poll_committed'))):
                    raise ValueError
                accepted += 1
            else:
                blocked += 1
                code = report.get('code')
                safe = code if code in {'CLOCK_UNVERIFIED', 'AUTH_REQUIRED', 'MISSED_OR_OUTSIDE_POLL_SLOT',
                    'FORWARD_CAPTURE_FAILED', 'POLL_REVIEW_REQUIRED', 'OPERATIONS_REVIEW_REQUIRED'} else 'OTHER_REDACTED'
                codes[safe] = codes.get(safe, 0) + 1
        except (KeyError, TypeError, ValueError):
            invalid += 1
    for receipt in receipts:
        n = receipt.get('recorded_decisions')
        if (receipt.get('format') == 'forward-versioned-manifest-v1'
                and receipt.get('status') == 'REMOTE_VERIFIED' and _count(n)
                and receipt.get('training_eligible') is False and receipt.get('approval_authority') is False
                and all(type(receipt.get(k)) is str and re.fullmatch('[0-9a-f]{64}', receipt[k])
                        for k in ('sha256', 'spec_hash'))):
            key = (receipt['sha256'], receipt['spec_hash'])
            if key in identities and identities[key] != n:
                raise StatusError('CONFLICTING_RECEIPT_COUNT_CLAIMS')
            if key not in identities:
                counts.append(n)
                identities[key] = n
        elif receipt.get('status') != 'BLOCKED':
            invalid += 1
    first = datetime.combine(day, datetime.min.time(), IST).replace(hour=9, minute=20, second=30)
    elapsed = min(75, max(0, int((local - first).total_seconds() // 300) + 1))
    due = min(75, max(0, int((local - first - timedelta(seconds=90)).total_seconds() // 300) + 1))
    return dict(status='READ_ONLY_METADATA_SNAPSHOT_NOT_AUDIT', session_date=day.isoformat(),
        observer_at=now.isoformat(), observer_clock_verified=False, scheduled_slots_elapsed=elapsed,
        slots_due_after_90s_reporting_grace=due, future_slots=75-elapsed,
        unbound_distinct_manifest_claims=len(counts),
        highest_unbound_receipt_decision_count=max(counts) if counts else None,
        receipt_session_binding_verified=False, elapsed_missing_count='NOT_ESTABLISHED',
        missing_slots='NOT_ESTABLISHED_REQUIRES_FINAL_JOURNAL_AUDIT',
        successful_process_reports=accepted, blocked_process_reports=blocked, blocked_codes=codes,
        incomplete_metadata=incomplete+receipt_incomplete, invalid_metadata=invalid,
        latest_process_report_at=max(timestamps).isoformat() if timestamps else None,
        snapshot_atomic=False, task_state='NOT_QUERIED_USE_SEPARATE_READ_ONLY_TASK_VIEW',
        filesystem_locality='NOT_ATTESTED_MAPPED_DRIVES_MAY_BE_REMOTE',
        hostile_filesystem_isolation=False,
        independent_remote_verification=False, remote_custody_verified=False,
        capture_writes=0, operational_writes=0, command_executions=0,
        network_requests_issued=0, approval_authority=False, training_eligible=False,
        retry_allowed=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--ops-root', type=Path, required=True)
    parser.add_argument('--session-date', type=date.fromisoformat, required=True)
    parser.add_argument('--inspect-read-only', action='store_true')
    args = parser.parse_args(argv)
    if not args.inspect_read_only:
        print(json.dumps(dict(status='PREVIEW', filesystem_reads=0, writes=0, command_executions=0)))
        return 0
    try:
        result = observe(args.root, args.ops_root, args.session_date, datetime.now(timezone.utc))
    except Exception as error:
        result = dict(status='BLOCKED', code=str(error) if type(error) is StatusError else 'METADATA_READ_UNAVAILABLE',
                      raw_error_printed=False, capture_writes=0, operational_writes=0)
    print(json.dumps(result))
    return 2 if result['status'] == 'BLOCKED' else 0


if __name__ == '__main__':
    raise SystemExit(main())
