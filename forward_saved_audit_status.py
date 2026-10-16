"""Inert-by-default, bounded saved-audit claim reader. No capture or task access."""
from __future__ import annotations

import argparse
import hashlib
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any

from forward_live_status import DAY_JSON, IST, StatusError, _directory, _path


def project(report: dict[str, Any], day: date) -> dict[str, Any]:
    """Validate internal consistency, NOT authenticity, journal bytes or task origin."""
    stamp = datetime.fromisoformat(report['observed_at'])
    close = datetime.combine(day, time(15, 40), IST)
    if (stamp.utcoffset() is None or stamp < close
            or report.get('session_date') != day.isoformat()):
        raise ValueError('INVALID_AUDIT_TIME')
    counts: list[Any] = [report.get(k) for k in ('raw_polls', 'recorded_decisions', 'missing_decisions')]
    if any(type(n) is not int or not 0 <= n <= 75 for n in counts):
        raise ValueError('INVALID_COUNTS')
    raw, recorded, missing = counts
    if (recorded + missing != 75 or recorded > raw
            or type(report.get('expected_decisions')) is not int
            or report['expected_decisions'] != 75):
        raise ValueError('INCONSISTENT_COUNTS')
    if any(report.get(k) is not False for k in (
            'full_session_cohort_eligible', 'training_eligible', 'approval_authority',
            'remote_custody_verified', 'backfill_allowed')):
        raise ValueError('AUTHORITY_NOT_SUPPORTED')
    if type(report.get('capture_writes')) is not int or report['capture_writes'] != 0:
        raise ValueError('READ_ONLY_CLAIM_REQUIRED')
    generation = report.get('generation_sha256')
    if type(generation) is not str or not re.fullmatch('[a-f0-9]{64}', generation):
        raise ValueError('INVALID_GENERATION')
    slots = report.get('slots')
    if type(slots) is not list or len(slots) != 75:
        raise ValueError('INVALID_SLOTS')
    start = datetime.combine(day, time(9, 20), IST)
    expected = {(start + timedelta(minutes=5*i)).astimezone(timezone.utc) for i in range(75)}
    seen: set[datetime] = set()
    identities: list[tuple[str, str]] = []
    totals = {'MISSING_NOT_OBSERVED': 0, 'RAW_ONLY_NO_DECISION': 0, 'OBSERVED_DECISION': 0}
    for slot in slots:
        if type(slot) is not dict or slot.get('status') not in totals:
            raise ValueError('INVALID_SLOT_STATUS')
        at = datetime.fromisoformat(slot['slot'])
        if at.utcoffset() is None or at not in expected or at in seen:
            raise ValueError('INVALID_SLOT_IDENTITY')
        seen.add(at)
        identities.append((at.astimezone(timezone.utc).isoformat(), slot['status']))
        totals[slot['status']] += 1
    if (totals['OBSERVED_DECISION'] != recorded
            or totals['OBSERVED_DECISION'] + totals['RAW_ONLY_NO_DECISION'] != raw):
        raise ValueError('SLOT_COUNT_MISMATCH')
    complete = recorded == 75
    status = 'VERSIONED_COVERAGE_COMPLETE' if complete else 'VERSIONED_COVERAGE_INCOMPLETE'
    if (report.get('status') != status or report.get('coverage_requirement_met') is not complete
            or report.get('operational_cause_per_slot') != 'NOT_ESTABLISHED'):
        raise ValueError('COVERAGE_CLAIM_MISMATCH')
    return dict(status=status, raw_polls=raw, recorded_decisions=recorded,
                missing_decisions=missing, generation_sha256=generation,
                observed_at=stamp.isoformat(), internal_consistency_verified=True,
                slot_status_sha256=hashlib.sha256(json.dumps(sorted(identities)).encode('ascii')).hexdigest())


def inspect(ops: Path, day: date) -> dict[str, Any]:
    source = Path(__file__).resolve().parent
    target = _path(ops)
    if target == target.parent or target.is_relative_to(source) or source.is_relative_to(target):
        raise StatusError('SEPARATE_PRIVATE_OPERATIONS_ROOT_REQUIRED')
    reports, unreadable = _directory(target, DAY_JSON, day.isoformat() + '-')
    valid: list[dict[str, Any]] = []
    invalid = 0
    for report in reports:
        if report.get('status') not in {'VERSIONED_COVERAGE_COMPLETE', 'VERSIONED_COVERAGE_INCOMPLETE'}:
            continue
        try:
            valid.append(project(report, day))
        except (KeyError, TypeError, ValueError):
            invalid += 1
    valid.sort(key=lambda r: (r['observed_at'], r['generation_sha256']))
    identities = {(r['generation_sha256'], r['raw_polls'], r['recorded_decisions'],
                   r['slot_status_sha256']) for r in valid}
    status = ('SAVED_AUDIT_REPORT_REVIEW_REQUIRED' if invalid or unreadable or len(identities) > 1
              else 'SAVED_AUDIT_REPORT_CLAIMS_VALIDATED' if valid else 'SAVED_AUDIT_REPORT_NOT_FOUND')
    return dict(status=status, session_date=day.isoformat(), candidates=valid,
                invalid_candidates=invalid, unreadable_or_inflight=unreadable,
                multiple_candidates=len(valid) > 1, conflicting_claims=len(identities) > 1,
                proof_basis='UNSIGNED_SAVED_REPORT_CLAIMS_ONLY',
                scheduled_task_origin_verified=False, journal_independently_verified=False,
                remote_custody_verified=False, training_eligible=False, approval_authority=False,
                task_queries=0, capture_reads=0, writes=0, credential_reads=0, network_calls=0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ops-root', type=Path, required=True)
    parser.add_argument('--session-date', type=date.fromisoformat, required=True)
    parser.add_argument('--confirm-read-only', action='store_true')
    args = parser.parse_args(argv)
    if not args.confirm_read_only:
        print(json.dumps(dict(status='PREVIEW', reads=0, writes=0, task_queries=0, credential_reads=0)))
        return 0
    try:
        result = inspect(args.ops_root, args.session_date)
    except Exception:
        result = dict(status='BLOCKED', code='SAVED_AUDIT_METADATA_REVIEW_REQUIRED',
                      raw_error_printed=False, approval_authority=False, writes=0)
    print(json.dumps(result))
    return 0 if result['status'] == 'SAVED_AUDIT_REPORT_CLAIMS_VALIDATED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
