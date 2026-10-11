"""Offline independent-watch evaluation; never write admission or alert delivery.

Inputs must come from independently commissioned, authenticated transports and a
reviewed session-aware run schedule. This module never invents exchange sessions,
producer success, archive custody or physical disk availability. No credentials,
network, storage writes, database connection discovery or notification side effects.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import TypedDict

from collector_storage_preflight import QUOTA_BYTES, RESERVE_BYTES, RUN_ALLOWANCE_BYTES

FLOOR_BYTES = RESERVE_BYTES + RUN_ALLOWANCE_BYTES
MAX_RUNS = 1440
MAX_AGE_SECONDS = 60
MAX_TREND_SECONDS = 86_400


class WatchError(ValueError):
    """Invalid inputs are UNAVAILABLE to a caller, never a healthy observation."""


@dataclass(frozen=True)
class Observation:
    """Actual cluster allocation and source measurement time, not dashboard cache."""

    at: datetime
    cluster_bytes: int


@dataclass(frozen=True)
class ExpectedRun:
    """Explicit session-calendar deadline plus independently read terminal receipt.

    run_id binds this specific run; a previous day's receipt cannot satisfy it.
    Both receipt fields absent means not observed, not failure or success. A
    timestamp with successful=False is observed failure and immediately alerts.
    A successful receipt is merely transport evidence here, not signed custody.
    """

    producer: str
    run_id: str
    starts_at: datetime
    deadline: datetime
    receipt_at: datetime | None
    successful: bool | None


class WatchReport(TypedDict):
    """Redacted deterministic diagnostics; a caller must deliver UNKNOWN alarms."""

    status: str
    reasons: list[str]
    unhealthy_runs: list[str]
    pending_runs: int
    nominal_headroom_bytes: int | None
    observed_delta_bytes: int | None
    positive_growth_bytes_per_day_ceiling: int | None
    diagnostic_seconds_to_floor: int | None
    alert_required: bool
    alert_delivery_verified: bool
    authenticated_inputs_verified: bool
    all_writers_enforced: bool
    approval_authority: bool


def _instant(value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise WatchError('STORAGE_WATCH_CLOCK_INVALID')
    return value.astimezone(timezone.utc)


def _size(value: int) -> int:
    if type(value) is not int or not 0 < value <= (1 << 63) - 1:
        raise WatchError('STORAGE_WATCH_SIZE_INVALID')
    return value


def _micros(delta_seconds: float) -> int:
    # datetime resolution is one microsecond; round prevents float representation
    # of, e.g., .000001 from truncating it to zero. No float size arithmetic.
    return round(delta_seconds * 1_000_000)


def evaluate(current: Observation | None, previous: Observation | None,
             runs: Sequence[ExpectedRun], *, schedule_sha256: str | None,
             now: datetime, warning_horizon_seconds: int = 172_800) -> WatchReport:
    """Capacity/missed-run diagnostics without a false global-safety badge.

    No schedule hash or no measurement => UNKNOWN alarm. Empty runs is legitimate
    only with an explicit reviewed schedule identity (e.g. holiday/no enabled job).
    Run deadlines come from that calendar, not a Mon-Fri guess in this evaluator.
    At exactly a deadline an unobserved run is still due; it is late AFTER it.

    A positive two-point slope is diagnostic, not a guaranteed future growth bound.
    Negative growth never earns capacity credit. Seconds-to-floor remains None
    for non-positive growth or unusable trend; None NEVER means infinite runway.
    No notifications are sent; delivery/transport authenticity remain unverified.
    """
    current_time = _instant(now)
    if (type(warning_horizon_seconds) is not int
            or not 0 < warning_horizon_seconds <= 30 * 86_400):
        raise WatchError('STORAGE_WATCH_HORIZON_INVALID')
    if not isinstance(runs, (tuple, list)) or len(runs) > MAX_RUNS:
        raise WatchError('STORAGE_WATCH_RUN_INVENTORY_INVALID')
    if ((current is not None and not isinstance(current, Observation))
            or (previous is not None and not isinstance(previous, Observation))):
        raise WatchError('STORAGE_WATCH_OBSERVATION_INVALID')
    reasons: list[str] = []
    unknown = False
    if schedule_sha256 is None:
        reasons.append('SCHEDULE_INVENTORY_UNAVAILABLE')
        unknown = True
    elif not isinstance(schedule_sha256, str) or re.fullmatch('[0-9a-f]{64}', schedule_sha256) is None:
        raise WatchError('STORAGE_WATCH_SCHEDULE_IDENTITY_INVALID')
    identities: set[tuple[str, str]] = set()
    unhealthy: list[str] = []
    pending = 0
    for run in runs:
        if (not isinstance(run, ExpectedRun) or not isinstance(run.producer, str)
                or re.fullmatch('[a-z][a-z0-9_]{0,62}', run.producer) is None
                or not isinstance(run.run_id, str) or re.fullmatch('[0-9a-f]{64}', run.run_id) is None):
            raise WatchError('STORAGE_WATCH_RUN_IDENTITY_INVALID')
        identity = (run.producer, run.run_id)
        if identity in identities:
            raise WatchError('STORAGE_WATCH_DUPLICATE_RUN')
        identities.add(identity)
        start, deadline = _instant(run.starts_at), _instant(run.deadline)
        if start > deadline:
            raise WatchError('STORAGE_WATCH_DEADLINE_INVALID')
        label = run.producer + ':' + run.run_id
        if run.receipt_at is None and run.successful is None:
            if current_time > deadline:
                unhealthy.append(label)
                if 'EXPECTED_RUN_RECEIPT_MISSING' not in reasons:
                    reasons.append('EXPECTED_RUN_RECEIPT_MISSING')
            else:
                pending += 1
        elif run.receipt_at is None or type(run.successful) is not bool:
            raise WatchError('STORAGE_WATCH_RECEIPT_INVALID')
        else:
            received = _instant(run.receipt_at)
            if received < start or received > current_time:
                raise WatchError('STORAGE_WATCH_RECEIPT_TIME_INVALID')
            if run.successful is False or received > deadline:
                unhealthy.append(label)
                code = 'EXPECTED_RUN_FAILED' if run.successful is False else 'EXPECTED_RUN_RECEIPT_LATE'
                if code not in reasons:
                    reasons.append(code)
    headroom: int | None = None
    delta: int | None = None
    daily: int | None = None
    runway: int | None = None
    if current is None:
        reasons.append('CAPACITY_MEASUREMENT_UNAVAILABLE')
        unknown = True
    else:
        measured_at, size = _instant(current.at), _size(current.cluster_bytes)
        age = (current_time - measured_at).total_seconds()
        if not 0 <= age <= MAX_AGE_SECONDS:
            reasons.append('CAPACITY_MEASUREMENT_STALE_OR_FUTURE')
            unknown = True
        headroom = QUOTA_BYTES - size
        if headroom < FLOOR_BYTES:
            reasons.append('CURRENT_ADMISSION_FLOOR_BREACHED')
        elif headroom < FLOOR_BYTES + RUN_ALLOWANCE_BYTES:
            reasons.append('BOUNDED_APPEND_RUNWAY_NOT_MET')
        if previous is None:
            reasons.append('CAPACITY_TREND_UNAVAILABLE')
            unknown = True
        else:
            earlier, before = _instant(previous.at), _size(previous.cluster_bytes)
            interval_us = _micros((measured_at - earlier).total_seconds())
            if not 0 < interval_us <= MAX_TREND_SECONDS * 1_000_000:
                reasons.append('CAPACITY_TREND_WINDOW_UNUSABLE')
                unknown = True
            else:
                delta = size - before
                positive = max(delta, 0)
                daily = (positive * 86_400_000_000 + interval_us - 1) // interval_us
                if positive:
                    remaining = max(headroom - FLOOR_BYTES, 0)
                    runway = (remaining * interval_us) // (positive * 1_000_000)
                    if runway < warning_horizon_seconds:
                        reasons.append('DIAGNOSTIC_GROWTH_APPROACHES_ADMISSION_FLOOR')
    status = 'UNKNOWN' if unknown else 'ALARM' if reasons else 'OBSERVED_OK'
    return {'status': status, 'reasons': sorted(reasons), 'unhealthy_runs': sorted(unhealthy),
            'pending_runs': pending, 'nominal_headroom_bytes': headroom,
            'observed_delta_bytes': delta, 'positive_growth_bytes_per_day_ceiling': daily,
            'diagnostic_seconds_to_floor': runway, 'alert_required': bool(reasons),
            'alert_delivery_verified': False, 'authenticated_inputs_verified': False,
            'all_writers_enforced': False, 'approval_authority': False}
