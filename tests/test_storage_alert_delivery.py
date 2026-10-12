"""Deterministic injected adapters; no accounts, network or real notifications."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from typing import Any, cast

import pytest

import storage_alert_delivery as delivery
import storage_capacity_watch as watch

NOW = datetime(2026, 10, 12, 20, tzinfo=timezone.utc)


def alarm() -> delivery.Alert:
    result = delivery.prepare(None, None, (), schedule_sha256=None, monitor_id='a'*64, now=NOW)
    assert result is not None
    return result


def test_unknown_is_an_alarm_with_deterministic_identity() -> None:
    item = alarm()
    assert item == alarm()
    body = json.loads(item.data)
    assert body['report']['status'] == 'UNKNOWN'
    assert body['report']['alert_required'] is True
    assert 'CAPACITY_MEASUREMENT_UNAVAILABLE' in body['report']['reasons']


def test_observed_ok_no_send_and_ist_same_identity() -> None:
    current = watch.Observation(NOW, 394_000_000)
    previous = watch.Observation(NOW-timedelta(hours=1), 394_000_000)
    assert delivery.prepare(current, previous, (), schedule_sha256='b'*64,
                            monitor_id='a'*64, now=NOW) is None
    assert delivery.prepare(None, None, (), schedule_sha256=None, monitor_id='a'*64,
        now=NOW.astimezone(timezone(timedelta(hours=5, minutes=30)))) == alarm()


def test_acceptance_is_not_owner_receipt_or_commissioning() -> None:
    item = alarm()
    calls = []
    def send(sent: delivery.Alert) -> delivery.Acceptance:
        calls.append(sent)
        return delivery.Acceptance(sent.alert_id, NOW)
    result = delivery.attempt(item, send, clock=lambda: NOW)
    assert calls == [item]
    assert result['status'] == 'PROVIDER_ACCEPTED_NOT_COMMISSIONED'
    assert result['provider_acceptance_observed'] is True
    for name in ('owner_receipt_verified', 'independent_delivery_commissioned', 'approval_authority'):
        assert result[name] is False


@pytest.mark.parametrize('kind', ['exception', 'none', 'wrong_id', 'past', 'future', 'naive', 'clock_backwards'])
def test_ambiguous_delivery_stays_unknown_once(kind: str) -> None:
    item = alarm()
    calls = []
    ticks = iter([NOW, NOW-timedelta(seconds=1) if kind == 'clock_backwards' else NOW])
    def send(sent: delivery.Alert) -> delivery.Acceptance:
        calls.append(sent)
        if kind == 'exception':
            raise RuntimeError('private webhook https://secret')
        if kind == 'none':
            return cast(delivery.Acceptance, None)
        at = NOW
        if kind == 'past':
            at -= timedelta(seconds=1)
        elif kind == 'future':
            at += timedelta(seconds=1)
        elif kind == 'naive':
            at = at.replace(tzinfo=None)
        return delivery.Acceptance('f'*64 if kind == 'wrong_id' else sent.alert_id, at)
    result = delivery.attempt(item, send, clock=lambda: next(ticks))
    assert len(calls) == 1
    assert result['status'] == 'DELIVERY_UNKNOWN_RECONCILE_NO_BLIND_RETRY'
    assert result['provider_acceptance_observed'] is False
    assert 'secret' not in json.dumps(result)


@pytest.mark.parametrize('kind', ['bytes', 'id', 'stale', 'future'])
def test_invalid_or_stale_envelope_never_sent(kind: str) -> None:
    item = alarm()
    if kind == 'bytes':
        item = replace(item, data=b'{}')
    elif kind == 'id':
        item = replace(item, alert_id='not-a-hash')
    now = NOW+timedelta(seconds=61) if kind == 'stale' else NOW-timedelta(seconds=1) if kind == 'future' else NOW
    def forbidden(_: delivery.Alert) -> delivery.Acceptance:
        pytest.fail('invalid envelope was sent')
    with pytest.raises(delivery.AlertError):
        delivery.attempt(item, forbidden, clock=lambda: now)


@pytest.mark.parametrize('changes', [{'now': NOW.replace(tzinfo=None)}, {'monitor_id': 'private-url'},
                                    {'schedule_sha256': 'bad'}, {'runs': [None]}])
def test_invalid_inputs_fail_with_redacted_code(changes: dict[str, Any]) -> None:
    args: dict[str, Any] = dict(current=None, previous=None, runs=(), schedule_sha256=None,
                              monitor_id='a'*64, now=NOW)
    args.update(changes)
    with pytest.raises(delivery.AlertError) as error:
        delivery.prepare(**args)
    assert 'private-url' not in str(error.value)
