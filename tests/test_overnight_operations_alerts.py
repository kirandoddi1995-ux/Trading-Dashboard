"""Deterministic offline alert transport, restart and concurrency tests."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import hashlib
from pathlib import Path
import sqlite3

import pytest

import overnight_operations_alerts as operations
import storage_alert_delivery as delivery

NOW = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)


def alert() -> delivery.Alert:
    value = delivery.prepare(None, None, [], schedule_sha256='a' * 64,
                             monitor_id='b' * 64, now=NOW)
    assert value is not None
    return value


def journal(tmp_path: Path) -> operations.AlertJournal:
    return operations.AlertJournal(tmp_path / 'alerts.sqlite', create=True)


def test_persist_restart_and_single_send(tmp_path: Path) -> None:
    instance, value = journal(tmp_path), alert()
    assert instance.persist(value, at=NOW).events == 1
    assert instance.persist(value, at=NOW).events == 1
    instance = operations.AlertJournal(tmp_path / 'alerts.sqlite')
    calls: list[str] = []

    def send(envelope: delivery.Alert) -> delivery.Acceptance:
        calls.append(envelope.alert_id)
        return delivery.Acceptance(envelope.alert_id, NOW)

    state = instance.send_once(value, send, clock=lambda: NOW, commissioned=True)
    assert state.status == 'ACCEPTED' and state.events == 3
    assert not state.owner_receipt_verified and not state.approval_authority
    with pytest.raises(operations.OperationError, match='ALREADY_ATTEMPTED'):
        instance.send_once(value, send, clock=lambda: NOW, commissioned=True)
    assert calls == [value.alert_id]


def test_lost_reply_is_unknown_no_retry(tmp_path: Path) -> None:
    instance, value = journal(tmp_path), alert()
    instance.persist(value, at=NOW)

    def fail(_: delivery.Alert) -> delivery.Acceptance:
        raise RuntimeError('SECRET must never escape')

    assert instance.send_once(value, fail, clock=lambda: NOW, commissioned=True).status == 'UNKNOWN'
    assert operations.AlertJournal(tmp_path / 'alerts.sqlite').state(value.alert_id).status == 'UNKNOWN'
    with pytest.raises(operations.OperationError, match='ALREADY_ATTEMPTED'):
        instance.send_once(value, fail, clock=lambda: NOW, commissioned=True)


def test_default_inactive_and_unpersisted(tmp_path: Path) -> None:
    instance, value = journal(tmp_path), alert()
    sender = lambda a: delivery.Acceptance(a.alert_id, NOW)
    with pytest.raises(operations.OperationError, match='NOT_COMMISSIONED'):
        instance.send_once(value, sender, clock=lambda: NOW)
    with pytest.raises(operations.OperationError, match='NOT_DURABLY_PERSISTED'):
        instance.send_once(value, sender, clock=lambda: NOW, commissioned=True)


def test_concurrent_claim_one_sender(tmp_path: Path) -> None:
    instance, value = journal(tmp_path), alert()
    instance.persist(value, at=NOW)
    calls: list[str] = []

    def send(value: delivery.Alert) -> delivery.Acceptance:
        calls.append(value.alert_id)
        return delivery.Acceptance(value.alert_id, NOW)

    def run(_: int) -> str:
        try:
            return instance.send_once(value, send, clock=lambda: NOW, commissioned=True).status
        except operations.OperationError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, [1, 2]))
    assert sorted(results) == ['ACCEPTED', 'ALERT_ALREADY_ATTEMPTED_RECONCILE']
    assert len(calls) == 1


def test_crash_after_intent_never_retries(tmp_path: Path) -> None:
    instance, value = journal(tmp_path), alert()
    instance.persist(value, at=NOW)
    with sqlite3.connect(instance.path) as connection:
        connection.execute("UPDATE alerts SET state='INTENT'")
        connection.execute('INSERT INTO events(id,state,at) VALUES (?,?,?)',
                           (value.alert_id, 'INTENT', NOW.isoformat()))
    with pytest.raises(operations.OperationError, match='ALREADY_ATTEMPTED'):
        operations.AlertJournal(instance.path).send_once(value, lambda a: delivery.Acceptance(a.alert_id, NOW),
                                                       clock=lambda: NOW, commissioned=True)


@pytest.mark.parametrize('query', ["DELETE FROM events", "UPDATE events SET state='ACCEPTED'",
                                 "DELETE FROM alerts", "UPDATE alerts SET envelope=x'00'"])
def test_immutable_records(tmp_path: Path, query: str) -> None:
    instance = journal(tmp_path)
    instance.persist(alert(), at=NOW)
    with sqlite3.connect(instance.path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(query)


@pytest.mark.parametrize('bad', [delivery.Alert(b'{}', 'a' * 64),
                               delivery.Alert(b'', 'a' * 64)])
def test_bad_envelope_rejected(tmp_path: Path, bad: delivery.Alert) -> None:
    with pytest.raises(operations.OperationError):
        journal(tmp_path).persist(bad, at=NOW)


def test_stale_does_not_call_sender(tmp_path: Path) -> None:
    instance, value = journal(tmp_path), alert()
    instance.persist(value, at=NOW)
    calls: list[str] = []

    def send(envelope: delivery.Alert) -> delivery.Acceptance:
        calls.append(envelope.alert_id)
        return delivery.Acceptance(envelope.alert_id, NOW)

    state = instance.send_once(value, send, clock=lambda: NOW + timedelta(seconds=61), commissioned=True)
    assert state.status == 'UNKNOWN' and calls == []


def test_missing_schema_and_recreation_rejected(tmp_path: Path) -> None:
    path = tmp_path / 'alerts.sqlite'
    with pytest.raises(operations.OperationError, match='MISSING'):
        operations.AlertJournal(path)
    instance = journal(tmp_path)
    with pytest.raises(operations.OperationError, match='ALREADY_EXISTS'):
        operations.AlertJournal(instance.path, create=True)
    with sqlite3.connect(instance.path) as connection:
        connection.execute("UPDATE metadata SET version='invalid'")
    with pytest.raises(operations.OperationError, match='SCHEMA_INVALID'):
        operations.AlertJournal(instance.path)


def telegram(post: operations.HTTPSPost, *, commissioned: bool = True) -> operations.TelegramSender:
    return operations.TelegramSender('123456:' + 'x' * 30, '123', post, lambda: NOW, commissioned)


def test_telegram_redacted_payload_no_paid_broadcast() -> None:
    seen: list[bytes] = []

    def post(path: str, data: bytes) -> tuple[int, bytes]:
        assert path.endswith('/sendMessage')
        seen.append(data)
        return 200, json.dumps({'ok': True, 'result': {'message_id': 1,
            'chat': {'id': 123}, 'date': int(NOW.timestamp()), 'text': json.loads(data)['text']}}).encode()

    sender = telegram(post)
    accepted = sender(alert())
    body = json.loads(seen[0])
    assert accepted.alert_id == alert().alert_id
    assert body['allow_paid_broadcast'] is False
    assert body['text'].endswith(alert().alert_id)
    assert sender.token not in repr(sender) and sender.chat_id not in repr(sender)


@pytest.mark.parametrize('status,reply', [(302, b'{}'), (500, b'SECRET'), (200, b'{}'),
                                        (200, b'x' * 16_385), (200, b'{invalid')])
def test_telegram_bad_reply_redacted(status: int, reply: bytes) -> None:
    with pytest.raises(operations.OperationError, match='REPLY_UNVERIFIED') as caught:
        telegram(lambda _p, _d: (status, reply))(alert())
    assert 'SECRET' not in str(caught.value)


@pytest.mark.parametrize('field,value', [('message_id', True), ('message_id', 0),
                                       ('date', 0), ('date', int(NOW.timestamp()) + 1),
                                       ('chat', {'id': 456}), ('chat', {'id': True})])
def test_telegram_wrong_receipt(field: str, value: object) -> None:
    message: dict[str, object] = {'message_id': 1, 'chat': {'id': 123}, 'date': int(NOW.timestamp())}
    message[field] = value
    with pytest.raises(operations.OperationError):
        telegram(lambda _p, _d: (200, json.dumps({'ok': True, 'result': message}).encode()))(alert())


def test_telegram_inactive_does_not_use_transport() -> None:
    def post(_path: str, _data: bytes) -> tuple[int, bytes]:
        raise AssertionError('must not call')

    with pytest.raises(operations.OperationError, match='NOT_COMMISSIONED'):
        telegram(post, commissioned=False)(alert())
    with pytest.raises(operations.OperationError, match='DESTINATION_INVALID'):
        replace(telegram(post), token='bad')(alert())


def test_journal_bound_before_another_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    instance = journal(tmp_path)
    monkeypatch.setattr(operations, 'MAX_ALERTS', 0)
    with pytest.raises(operations.OperationError, match='CAPACITY_REVIEW'):
        instance.persist(alert(), at=NOW)


def test_missing_journal_does_not_recreate(tmp_path: Path) -> None:
    instance = journal(tmp_path)
    instance.path.unlink()  # synthetic fixture only, not owner data
    with pytest.raises(operations.OperationError):
        instance.persist(alert(), at=NOW)
    assert not instance.path.exists()


def test_mutated_state_cannot_resend(tmp_path: Path) -> None:
    instance, value = journal(tmp_path), alert()
    instance.persist(value, at=NOW)
    instance.send_once(value, lambda a: delivery.Acceptance(a.alert_id, NOW), clock=lambda: NOW, commissioned=True)
    with sqlite3.connect(instance.path) as connection:
        connection.execute("UPDATE alerts SET state='PENDING'")
    with pytest.raises(operations.OperationError, match='HISTORY_CONFLICT'):
        operations.AlertJournal(instance.path).send_once(value,
            lambda _: pytest.fail('duplicate send'), clock=lambda: NOW, commissioned=True)


def test_removed_guard_blocks_reopen(tmp_path: Path) -> None:
    instance = journal(tmp_path)
    with sqlite3.connect(instance.path) as connection:
        connection.execute('DROP TRIGGER immutable_event_delete')
    with pytest.raises(operations.OperationError, match='SCHEMA_INVALID'):
        operations.AlertJournal(instance.path)


@pytest.mark.parametrize('field,value', [('monitor_id', 'invalid'), ('schedule_sha256', 'invalid'),
                                       ('report', {'alert_required': True, 'approval_authority': True})])
def test_canonical_but_malformed_envelope(tmp_path: Path, field: str, value: object) -> None:
    body = json.loads(alert().data)
    body[field] = value
    raw = json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
    with pytest.raises(operations.OperationError, match='ENVELOPE_INVALID'):
        journal(tmp_path).persist(delivery.Alert(raw, hashlib.sha256(raw).hexdigest()), at=NOW)


def test_telegram_unrelated_text_not_acceptance() -> None:
    raw = json.dumps({'ok': True, 'result': {'message_id': 1, 'chat': {'id': 123},
        'date': int(NOW.timestamp()), 'text': 'different alert'}}).encode()
    with pytest.raises(operations.OperationError, match='REPLY_UNVERIFIED'):
        telegram(lambda _p, _d: (200, raw))(alert())


class AcceptedCommitLostReply(sqlite3.Connection):
    """Commit reached synthetic disk; caller receives an ambiguous error."""
    def commit(self) -> None:
        super().commit()
        raise OSError('synthetic private driver detail')


def test_claim_commit_then_raise_never_sends(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    instance, value = journal(tmp_path), alert()
    instance.persist(value, at=NOW)
    monkeypatch.setattr(instance, '_connect', lambda: sqlite3.connect(instance.path, factory=AcceptedCommitLostReply))
    with pytest.raises(operations.OperationError, match='CLAIM_COMMIT_UNKNOWN'):
        instance.send_once(value, lambda _: pytest.fail('ambiguous claim must not send'),
                           clock=lambda: NOW, commissioned=True)
    reopened = operations.AlertJournal(instance.path)
    assert reopened.state(value.alert_id).status == 'INTENT'
    with pytest.raises(operations.OperationError, match='ALREADY_ATTEMPTED'):
        reopened.send_once(value, lambda _: pytest.fail('must not resend'), clock=lambda: NOW, commissioned=True)


def test_completion_commit_then_raise_stays_nonretryable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    instance, value = journal(tmp_path), alert()
    instance.persist(value, at=NOW)
    connect = instance._connect
    connections = 0

    def injected() -> sqlite3.Connection:
        nonlocal connections
        connections += 1
        return sqlite3.connect(instance.path, factory=AcceptedCommitLostReply) if connections == 2 else connect()

    monkeypatch.setattr(instance, '_connect', injected)
    with pytest.raises(operations.OperationError, match='RESULT_COMMIT_UNKNOWN'):
        instance.send_once(value, lambda a: delivery.Acceptance(a.alert_id, NOW), clock=lambda: NOW, commissioned=True)
    reopened = operations.AlertJournal(instance.path)
    assert reopened.state(value.alert_id).status == 'ACCEPTED'
    with pytest.raises(operations.OperationError, match='ALREADY_ATTEMPTED'):
        reopened.send_once(value, lambda _: pytest.fail('must not resend'), clock=lambda: NOW, commissioned=True)


def test_clock_regression_before_claim_never_calls_sender(tmp_path: Path) -> None:
    instance, value = journal(tmp_path), alert()
    instance.persist(value, at=NOW + timedelta(seconds=30))
    with pytest.raises(operations.OperationError, match='CLOCK_REGRESSION'):
        instance.send_once(value, lambda _: pytest.fail('regressed clock must not send'),
                           clock=lambda: NOW, commissioned=True)
    assert instance.state(value.alert_id).status == 'PENDING'
