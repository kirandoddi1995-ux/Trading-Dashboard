"""Pure commissioning checklist over reviewed receipts, never deletion authority.

File existence, green CI and low row counts are not operational storage proofs.
This gate is not wired into hosted admission; callers must verify receipt origin.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
from typing import Any, Callable, cast
from zoneinfo import ZoneInfo

from nifty_session_calendar import cash_session
from storage_policy import Measurement, WARNING_BYTES, assess

REQUIRED_PROOFS = (
    'complete_dependency_inventory', 'all_writers_bounded', 'universe_exact_pit_reads',
    'all_nonledger_sources_roundtrip', 'ledger_originals_and_legacy_keys',
    'cold_hot_reader_factory_wiring', 'local_outbox_checkpoint_recovery',
    'archived_retry_idempotency', 'archive_crash_and_concurrency',
    'independent_root_and_second_copy', 'private_ml_dataset_reproducibility',
    'independent_capacity_and_missed_job_alerts',
)
MIN_CYCLES = 10  # consecutive complete trading-session collection/archive cycles
HASH = re.compile(r'[0-9a-f]{64}')


@dataclass(frozen=True)
class Cycle:
    """One complete observed session, including pre-archive peak allocation."""

    session_date: date
    peak_bytes: int
    after_bytes: int
    collection_complete: bool
    archive_verified: bool
    backlog_growing: bool


def evaluate(measurement: Measurement, now: datetime, *,
             receipt_hashes: Mapping[str, str], cycles: Sequence[Cycle],
             steady_state_growth_bound_bytes: int) -> dict[str, object]:
    """Reject missing proof, over-budget peaks or a still-unbounded design.

    Cycles are supervised observations, not proof of infinite future capacity.
    The analytical bound must include protected dependencies and metadata growth.
    """
    if (type(steady_state_growth_bound_bytes) is not int
            or steady_state_growth_bound_bytes < 0):
        raise ValueError('STORAGE_GROWTH_BOUND_INVALID')
    if set(receipt_hashes) - set(REQUIRED_PROOFS):
        raise ValueError('STORAGE_PROOF_UNKNOWN')
    if any(not isinstance(v, str) or not HASH.fullmatch(v) for v in receipt_hashes.values()):
        raise ValueError('STORAGE_PROOF_HASH_INVALID')
    policy = assess(measurement, now)
    reasons = list(cast(list[str], policy['reasons']))
    missing = [name for name in REQUIRED_PROOFS if name not in receipt_hashes]
    if missing:
        reasons.append('STORAGE_COMMISSIONING_PROOF_MISSING')
    if len(cycles) > 260:
        raise ValueError('STORAGE_CYCLE_LIMIT_EXCEEDED')
    if len(cycles) < MIN_CYCLES:
        reasons.append('STORAGE_OBSERVATION_WINDOW_INCOMPLETE')
    for cycle in cycles:
        if (type(cycle.session_date) is not date or type(cycle.peak_bytes) is not int or type(cycle.after_bytes) is not int
                or not 0 < cycle.after_bytes <= cycle.peak_bytes
                or any(type(value) is not bool for value in
                       (cycle.collection_complete, cycle.archive_verified, cycle.backlog_growing))):
            raise ValueError('STORAGE_CYCLE_INVALID')
    dates = [c.session_date for c in cycles]
    if dates:
        if dates != sorted(set(dates)) or dates[-1] >= now.astimezone(ZoneInfo('Asia/Kolkata')).date():
            raise ValueError('STORAGE_CYCLE_DATES_INVALID')
        span = (dates[-1] - dates[0]).days
        if span > 366:
            raise ValueError('STORAGE_CYCLE_LIMIT_EXCEEDED')
        calendar = cast(Callable[[date], dict[str, Any]], cash_session)
        expected = [dates[0] + timedelta(days=i) for i in range(span + 1)
                    if calendar(dates[0] + timedelta(days=i))['kind'] == 'REGULAR']
        if dates != expected:
            reasons.append('STORAGE_CYCLE_SESSION_COVERAGE_INCOMPLETE')
    if any(c.peak_bytes >= WARNING_BYTES or not c.collection_complete
           or not c.archive_verified or c.backlog_growing for c in cycles):
        reasons.append('STORAGE_CYCLE_NOT_STEADY')
    if measurement.cluster_bytes + steady_state_growth_bound_bytes >= WARNING_BYTES:
        reasons.append('STORAGE_STEADY_STATE_BOUND_EXCEEDED')
    return {'status': 'CHECKLIST_COMPLETE_REQUIRES_RECEIPT_VERIFICATION' if not reasons else 'NOT_COMMISSIONED',
            'blockers': sorted(set(reasons)), 'missing_proofs': missing,
            'observed_cycles': len(cycles), 'approval_authority': False,
            'receipts_verified_by_tool': False, 'deletion_authorised': False, 'hosted_changes': 0}
