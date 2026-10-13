"""Inactive independent capacity-watch cycle with durable alert delivery boundary."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from overnight_operations_alerts import AlertJournal, instant
from overnight_operations_inputs import Connection, measure_capacity
import storage_alert_delivery as delivery
from storage_capacity_watch import ExpectedRun, Observation


@dataclass(frozen=True)
class CycleResult:
    """No result establishes independently authenticated custody or writer safety."""
    status: str
    measurement: Observation | None
    alert_id: str | None
    delivery_state: str | None
    network_calls_attempted: int
    approval_authority: bool = False
    all_writers_enforced: bool = False
    independent_delivery_commissioned: bool = False


def cycle(*, execute: bool = False, connect: Callable[[], Connection],
          clock: Callable[[], datetime], previous: Observation | None,
          runs: Sequence[ExpectedRun], schedule_sha256: str | None,
          monitor_id: str, journal: AlertJournal,
          sender: Callable[[delivery.Alert], delivery.Acceptance],
          send_commissioned: bool = False) -> CycleResult:
    """Preview performs zero callbacks/IO; explicit execution reads then persists.

    Missing SQL data becomes a durable UNKNOWN warning. Real sending requires a
    separate owner commissioning choice and occurs only after local persistence.
    An accepted provider reply is not a human ACK or independently running host.
    Caller retains measured observations/schedule roots in its commissioned tier.
    """
    if execute is not True:
        return CycleResult('PREVIEW', None, None, None, 0)
    attempts = 0
    def measured_connect() -> Connection:
        nonlocal attempts
        attempts += 1
        return connect()
    def counted_sender(alert: delivery.Alert) -> delivery.Acceptance:
        nonlocal attempts
        attempts += 1
        return sender(alert)
    current: Observation | None
    try:
        current = measure_capacity(measured_connect, clock=clock)
    except Exception:
        current = None
    now = instant(clock())
    alert = delivery.prepare(current, previous, runs, schedule_sha256=schedule_sha256,
                             monitor_id=monitor_id, now=now)
    if alert is None:
        return CycleResult('OBSERVED_OK_NOT_COMMISSIONED', current, None, None, attempts)
    state = journal.persist(alert, at=now)
    if state.status != 'PENDING':
        return CycleResult('ALERT_EXISTING_STATE_NO_SEND', current,
                           alert.alert_id, state.status, attempts)
    if send_commissioned is not True:
        return CycleResult('ALERT_DURABLE_NOT_SENT', current, alert.alert_id, state.status, attempts)
    before_send = attempts
    state = journal.send_once(alert, counted_sender, clock=clock, commissioned=True)
    status = ('ALERT_ATTEMPT_REQUIRES_OWNER_RECONCILIATION' if attempts > before_send
              else 'ALERT_EXISTING_STATE_NO_SEND')
    return CycleResult(status, current, alert.alert_id, state.status, attempts)
