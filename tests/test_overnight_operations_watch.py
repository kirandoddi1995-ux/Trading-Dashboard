"""Integrated fake measurement -> watch -> durable envelope -> fake provider."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import overnight_operations_watch as operations
from overnight_operations_alerts import AlertJournal
from overnight_operations_inputs import Connection
import storage_alert_delivery as delivery
from storage_capacity_watch import Observation
from tests.test_overnight_operations_inputs import FakeConnection

NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)


def test_preview_zero_callbacks(tmp_path: Path) -> None:
    instance = AlertJournal(tmp_path / 'alert.sqlite', create=True)

    def connect() -> Connection:
        raise AssertionError('preview callback')

    result = operations.cycle(connect=connect, clock=lambda: NOW, previous=None, runs=[],
        schedule_sha256=None, monitor_id='b' * 64, journal=instance,
        sender=lambda a: delivery.Acceptance(a.alert_id, NOW))
    assert result.status == 'PREVIEW' and result.network_calls_attempted == 0


def test_unknown_measurement_persisted_before_fake_send(tmp_path: Path) -> None:
    instance = AlertJournal(tmp_path / 'alert.sqlite', create=True)

    def connect() -> Connection:
        raise OSError('secret')

    def send(alert: delivery.Alert) -> delivery.Acceptance:
        assert instance.state(alert.alert_id).status == 'INTENT'
        return delivery.Acceptance(alert.alert_id, NOW)

    result = operations.cycle(execute=True, connect=connect, clock=lambda: NOW,
        previous=None, runs=[], schedule_sha256='a' * 64, monitor_id='b' * 64,
        journal=instance, sender=send, send_commissioned=True)
    assert result.delivery_state == 'ACCEPTED' and result.network_calls_attempted == 2
    assert not result.approval_authority and not result.independent_delivery_commissioned


def test_default_execute_only_prepares_unknown_warning(tmp_path: Path) -> None:
    instance = AlertJournal(tmp_path / 'alert.sqlite', create=True)
    result = operations.cycle(execute=True, connect=FakeConnection, clock=lambda: NOW,
        previous=None, runs=[], schedule_sha256='a' * 64, monitor_id='b' * 64,
        journal=instance, sender=lambda a: delivery.Acceptance(a.alert_id, NOW))
    assert result.status == 'ALERT_DURABLE_NOT_SENT' and result.delivery_state == 'PENDING'


def test_healthy_no_alert_but_no_commissioned_badge(tmp_path: Path) -> None:
    result = operations.cycle(execute=True, connect=FakeConnection, clock=lambda: NOW,
        previous=Observation(NOW - timedelta(hours=1), 394_000_000), runs=[],
        schedule_sha256='a' * 64, monitor_id='b' * 64,
        journal=AlertJournal(tmp_path / 'alert.sqlite', create=True),
        sender=lambda a: delivery.Acceptance(a.alert_id, NOW))
    assert result.status == 'OBSERVED_OK_NOT_COMMISSIONED' and result.alert_id is None


def test_reconciled_prior_acceptance_does_not_claim_another_send(tmp_path: Path) -> None:
    instance = AlertJournal(tmp_path / 'alert.sqlite', create=True)
    sends = 0
    def connect() -> Connection:
        raise OSError('synthetic missing measurement')
    def send(alert: delivery.Alert) -> delivery.Acceptance:
        nonlocal sends
        sends += 1
        return delivery.Acceptance(alert.alert_id, NOW)
    for iteration in (0, 1):
        result = operations.cycle(execute=True, connect=connect, clock=lambda: NOW,
            previous=None, runs=[], schedule_sha256='a' * 64, monitor_id='b' * 64,
            journal=instance, sender=send, send_commissioned=True)
        assert result.network_calls_attempted == (2 if iteration == 0 else 1)
        assert result.delivery_state == 'ACCEPTED'
    assert sends == 1 and result.status == 'ALERT_EXISTING_STATE_NO_SEND'
