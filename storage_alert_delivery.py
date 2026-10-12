"""Inactive capacity-alert transport boundary; no provider, scheduler or secrets.

Pure preparation plus ONE caller-injected send. Provider acceptance is not owner
receipt. Exceptions/ambiguous replies remain unknown, without automatic retry.
The caller must persist the exact envelope before sending and reconcile by ID.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import TypedDict

import storage_capacity_watch as watch

MAX_ENVELOPE_BYTES = 256 * 1024


class AlertError(ValueError):
    """Stable redacted failures; never provider text or destination identifiers."""


@dataclass(frozen=True, repr=False)
class Alert:
    """Canonical diagnostic bytes with content identity; not authenticated inputs."""
    data: bytes = field(repr=False)
    alert_id: str


@dataclass(frozen=True)
class Acceptance:
    """Exact request identity returned by an injected provider adapter."""
    alert_id: str
    accepted_at: datetime


class Attempt(TypedDict):
    """Safe result. No result authorises deletion, approvals or live writes."""
    status: str
    alert_id: str
    code: str
    attempts: int
    provider_acceptance_observed: bool
    owner_receipt_verified: bool
    independent_delivery_commissioned: bool
    approval_authority: bool


def _time(value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise AlertError('ALERT_CLOCK_INVALID')
    return value.astimezone(timezone.utc)


def _hash(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise AlertError('ALERT_IDENTITY_INVALID')
    return value


def prepare(current: watch.Observation | None, previous: watch.Observation | None,
            runs: Sequence[watch.ExpectedRun], *, schedule_sha256: str | None,
            monitor_id: str, now: datetime) -> Alert | None:
    """Evaluate original structured inputs; UNKNOWN alarms are not suppressed.

    The monitor identity must denote the independent watcher, not a producer.
    This function validates its form, not its deployment or authentication.
    Empty holiday schedules still need their reviewed schedule hash.
    No alert for OBSERVED_OK; heartbeat monitoring needs separate commissioning.
    """
    _hash(monitor_id)
    at = _time(now)
    try:
        report = watch.evaluate(current, previous, runs, schedule_sha256=schedule_sha256, now=at)
    except watch.WatchError:
        raise AlertError('ALERT_WATCH_INPUT_INVALID') from None
    if not report['alert_required']:
        return None
    body = {'version': 'storage-alert-envelope-v1', 'monitor_id': monitor_id,
            'evaluated_at': at.isoformat(), 'schedule_sha256': schedule_sha256,
            'report': report}
    data = json.dumps(body, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode()
    if not 0 < len(data) <= MAX_ENVELOPE_BYTES:
        raise AlertError('ALERT_ENVELOPE_SIZE_BOUND')
    return Alert(data, hashlib.sha256(data).hexdigest())


def attempt(alert: Alert, sender: Callable[[Alert], Acceptance], *,
            clock: Callable[[], datetime]) -> Attempt:
    """One explicit send of a previously persisted envelope; no retries or ACKs.

    Adapter acceptance must echo this exact ID and be no older than evaluation,
    and no later than the measured post-send clock. Ambiguity is never success.
    Stale envelopes require reevaluation, not resending yesterday's alarm.
    """
    try:
        start = _time(clock())
    except Exception:
        raise AlertError('ALERT_CLOCK_UNAVAILABLE') from None
    if (type(alert) is not Alert or type(alert.data) is not bytes
            or not 0 < len(alert.data) <= MAX_ENVELOPE_BYTES
            or hashlib.sha256(alert.data).hexdigest() != _hash(alert.alert_id)
            or not callable(sender)):
        raise AlertError('ALERT_ENVELOPE_INVALID')
    try:
        body = json.loads(alert.data)
        started = _time(datetime.fromisoformat(body['evaluated_at']))
        if (body['version'] != 'storage-alert-envelope-v1'
                or body['report']['alert_required'] is not True
                or not 0 <= (start - started).total_seconds() <= watch.MAX_AGE_SECONDS):
            raise ValueError
    except Exception:
        raise AlertError('ALERT_ENVELOPE_INVALID') from None
    result: Attempt = {'status': 'DELIVERY_UNKNOWN_RECONCILE_NO_BLIND_RETRY',
        'alert_id': alert.alert_id, 'code': 'ALERT_PROVIDER_UNAVAILABLE', 'attempts': 1,
        'provider_acceptance_observed': False, 'owner_receipt_verified': False,
        'independent_delivery_commissioned': False, 'approval_authority': False}
    try:
        accepted = sender(alert)
        end = _time(clock())
    except Exception:
        return result  # Driver/HTTP text can contain private URLs and credentials.
    if type(accepted) is not Acceptance:
        result['code'] = 'ALERT_ACCEPTANCE_UNVERIFIED'
        return result
    try:
        received = _time(accepted.accepted_at)
        if accepted.alert_id != alert.alert_id or end < start or not start <= received <= end:
            raise AlertError('ALERT_ACCEPTANCE_UNVERIFIED')
    except AlertError:
        result['code'] = 'ALERT_ACCEPTANCE_UNVERIFIED'
        return result
    result['status'] = 'PROVIDER_ACCEPTED_NOT_COMMISSIONED'
    result['code'] = 'ALERT_ACCEPTED'
    result['provider_acceptance_observed'] = True
    return result
