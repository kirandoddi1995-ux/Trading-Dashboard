"""Inactive, durable one-attempt alerts and explicit free Telegram transport.

No credential discovery, scheduled activation or real sends at import. A durable
INTENT is committed before a transport call: crashes and lost replies require
reconciliation, never automatic resend. Acceptance is not proof the owner saw it.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import http.client
import json
from pathlib import Path
import re
import sqlite3
import ssl
from typing import Protocol

import storage_alert_delivery as delivery

MAX_JOURNAL_BYTES = 64 * 1024 * 1024
MAX_ALERTS = 1024
TRIGGERS = {
    'immutable_event_update': "CREATE TRIGGER immutable_event_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVENT'); END",
    'immutable_event_delete': "CREATE TRIGGER immutable_event_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVENT'); END",
    'immutable_alert_payload': "CREATE TRIGGER immutable_alert_payload BEFORE UPDATE OF id,envelope ON alerts BEGIN SELECT RAISE(ABORT,'IMMUTABLE_ENVELOPE'); END",
    'immutable_alert_delete': "CREATE TRIGGER immutable_alert_delete BEFORE DELETE ON alerts BEGIN SELECT RAISE(ABORT,'IMMUTABLE_ENVELOPE'); END",
}


class OperationError(ValueError):
    """Redacted operational failure: never include a driver exception or URL."""


def instant(value: datetime) -> datetime:
    """Reject naive clocks instead of silently assuming the PC's timezone."""
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise OperationError('OPERATIONS_CLOCK_INVALID')
    return value.astimezone(timezone.utc)


def validate_alert(alert: delivery.Alert) -> None:
    """Check bounded content identity and the canonical envelope before persistence."""
    if (type(alert) is not delivery.Alert or type(alert.data) is not bytes
            or not 0 < len(alert.data) <= delivery.MAX_ENVELOPE_BYTES
            or hashlib.sha256(alert.data).hexdigest() != alert.alert_id):
        raise OperationError('ALERT_IDENTITY_INVALID')
    try:
        body = json.loads(alert.data)
        canonical = json.dumps(body, sort_keys=True, separators=(',', ':'),
                               ensure_ascii=True, allow_nan=False).encode()
        if (canonical != alert.data or body['version'] != 'storage-alert-envelope-v1'
                or body['report']['alert_required'] is not True):
            raise ValueError
        if (set(body) != {'version', 'monitor_id', 'evaluated_at', 'schedule_sha256', 'report'}
                or type(body['monitor_id']) is not str
                or re.fullmatch('[0-9a-f]{64}', body['monitor_id']) is None
                or (body['schedule_sha256'] is not None and (type(body['schedule_sha256']) is not str
                    or re.fullmatch('[0-9a-f]{64}', body['schedule_sha256']) is None))):
            raise ValueError
        report = body['report']
        if (set(report) != {'status', 'reasons', 'unhealthy_runs', 'pending_runs',
                'nominal_headroom_bytes', 'observed_delta_bytes', 'positive_growth_bytes_per_day_ceiling',
                'diagnostic_seconds_to_floor', 'alert_required', 'alert_delivery_verified',
                'authenticated_inputs_verified', 'all_writers_enforced', 'approval_authority'}
                or report['status'] not in ('UNKNOWN', 'ALARM')
                or any(report[key] is not False for key in ('alert_delivery_verified',
                    'authenticated_inputs_verified', 'all_writers_enforced', 'approval_authority'))
                or type(report['pending_runs']) is not int or not 0 <= report['pending_runs'] <= 1440
                or any(type(report[key]) is not list or len(report[key]) > 1440
                    or any(type(item) is not str or not 0 < len(item) <= 256 for item in report[key])
                    for key in ('reasons', 'unhealthy_runs'))
                or not report['reasons']
                or any(report[key] is not None and (type(report[key]) is not int or abs(report[key]) > (1 << 127))
                    for key in ('nominal_headroom_bytes', 'observed_delta_bytes',
                        'positive_growth_bytes_per_day_ceiling', 'diagnostic_seconds_to_floor'))):
            raise ValueError
        instant(datetime.fromisoformat(body['evaluated_at']))
    except Exception:
        raise OperationError('ALERT_ENVELOPE_INVALID') from None


@dataclass(frozen=True)
class JournalState:
    """Safe metadata; private diagnostic envelopes are never included in repr."""
    alert_id: str
    status: str
    events: int
    owner_receipt_verified: bool = False
    approval_authority: bool = False


class AlertJournal:
    """Explicit private SQLite journal with immutable events and restart reconciliation.

    The caller selects a private location outside the repository. Creating the
    parent, setting its ACL/encryption and independent custody remain owner steps.
    This local journal does not enforce the hosted database's capacity policy.
    """

    def __init__(self, path: Path, *, create: bool = False) -> None:
        if not path.is_absolute() or path.suffix != '.sqlite':
            raise OperationError('ALERT_JOURNAL_PATH_INVALID')
        for part in (path, *path.parents):
            if part.is_symlink() or part.is_junction():
                raise OperationError('ALERT_JOURNAL_LINK_REJECTED')
        if not path.parent.is_dir() or (not create and not path.is_file()):
            raise OperationError('ALERT_JOURNAL_MISSING')
        self.path = path
        exists = path.exists()
        if create and exists:
            raise OperationError('ALERT_JOURNAL_ALREADY_EXISTS')
        try:
            connection = sqlite3.connect(path.as_uri() + ('?mode=rwc' if create else '?mode=rw'),
                                         uri=True, timeout=2)
            try:
                if create:
                    connection.executescript('''
                        PRAGMA synchronous=FULL;
                        CREATE TABLE metadata(version TEXT NOT NULL);
                        INSERT INTO metadata VALUES ('overnight-alert-journal-v1');
                        CREATE TABLE alerts(id TEXT PRIMARY KEY, envelope BLOB NOT NULL,
                            state TEXT NOT NULL CHECK(state IN ('PENDING','INTENT','UNKNOWN','ACCEPTED')));
                        CREATE TABLE events(seq INTEGER PRIMARY KEY, id TEXT NOT NULL,
                            state TEXT NOT NULL, at TEXT NOT NULL);
                        CREATE TRIGGER immutable_event_update BEFORE UPDATE ON events
                            BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVENT'); END;
                        CREATE TRIGGER immutable_event_delete BEFORE DELETE ON events
                            BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVENT'); END;
                        CREATE TRIGGER immutable_alert_payload BEFORE UPDATE OF id,envelope ON alerts
                            BEGIN SELECT RAISE(ABORT,'IMMUTABLE_ENVELOPE'); END;
                        CREATE TRIGGER immutable_alert_delete BEFORE DELETE ON alerts
                            BEGIN SELECT RAISE(ABORT,'IMMUTABLE_ENVELOPE'); END;
                    ''')
                self._schema(connection)
            finally:
                connection.close()
        except OperationError:
            raise
        except Exception:
            raise OperationError('ALERT_JOURNAL_UNAVAILABLE') from None

    def _connect(self) -> sqlite3.Connection:
        try:
            if not self.path.is_file() or self.path.stat().st_size > MAX_JOURNAL_BYTES:
                raise OperationError('ALERT_JOURNAL_CAPACITY_OR_FILE_UNAVAILABLE')
            connection = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=2)
            connection.execute('PRAGMA synchronous=FULL')
            try:
                self._schema(connection)
            except Exception:
                connection.close()
                raise
            return connection
        except Exception:
            raise OperationError('ALERT_JOURNAL_UNAVAILABLE') from None

    @staticmethod
    def _schema(connection: sqlite3.Connection) -> None:
        """Check guard definitions, not just names; this is corruption detection, not custody."""
        def normalize(text: str) -> str:
            return ''.join(text.split()).lower().rstrip(';')
        found = dict(connection.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'").fetchall())
        if (connection.execute('SELECT version FROM metadata').fetchall() != [('overnight-alert-journal-v1',)]
                or set(found) != set(TRIGGERS)
                or any(normalize(found[name]) != normalize(sql) for name, sql in TRIGGERS.items())):
            raise OperationError('ALERT_JOURNAL_SCHEMA_INVALID')

    @staticmethod
    def _record(connection: sqlite3.Connection, alert_id: str) -> tuple[bytes, str, int]:
        row = connection.execute('SELECT envelope,state FROM alerts WHERE id=?', (alert_id,)).fetchone()
        events = connection.execute('SELECT state,at FROM events WHERE id=? ORDER BY seq', (alert_id,)).fetchall()
        if row is None:
            raise OperationError('ALERT_JOURNAL_RECORD_MISSING')
        states = [event[0] for event in events]
        if (states not in (['PENDING'], ['PENDING', 'INTENT'], ['PENDING', 'INTENT', 'UNKNOWN'],
                           ['PENDING', 'INTENT', 'ACCEPTED']) or row[1] != states[-1]):
            raise OperationError('ALERT_JOURNAL_HISTORY_CONFLICT_NO_RESEND')
        previous: datetime | None = None
        for event in events:
            at = instant(datetime.fromisoformat(event[1]))
            if previous is not None and at < previous:
                raise OperationError('ALERT_JOURNAL_HISTORY_CONFLICT_NO_RESEND')
            previous = at
        validate_alert(delivery.Alert(row[0], alert_id))
        return bytes(row[0]), str(row[1]), len(events)

    def persist(self, alert: delivery.Alert, *, at: datetime) -> JournalState:
        """Idempotently persist identical bytes; never overwrite a former envelope."""
        validate_alert(alert)
        stamp = instant(at).isoformat()
        if instant(at) < datetime.fromisoformat(json.loads(alert.data)['evaluated_at']):
            raise OperationError('ALERT_PERSIST_CLOCK_REGRESSION')
        connection = self._connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT envelope FROM alerts WHERE id=?', (alert.alert_id,)).fetchone()
            if row is None:
                count = connection.execute('SELECT count(*) FROM alerts').fetchone()
                pages = connection.execute('PRAGMA page_count').fetchone()
                page_size = connection.execute('PRAGMA page_size').fetchone()
                if (count is None or pages is None or page_size is None or count[0] >= MAX_ALERTS
                        or pages[0] * page_size[0] + len(alert.data) * 2 + 65_536 > MAX_JOURNAL_BYTES):
                    raise OperationError('ALERT_JOURNAL_CAPACITY_REVIEW_REQUIRED')
                connection.execute('INSERT INTO alerts VALUES (?,?,?)', (alert.alert_id, alert.data, 'PENDING'))
                connection.execute('INSERT INTO events(id,state,at) VALUES (?,?,?)',
                                   (alert.alert_id, 'PENDING', stamp))
            elif row[0] != alert.data:
                raise OperationError('ALERT_JOURNAL_IDENTITY_CONFLICT')
            self._record(connection, alert.alert_id)
            connection.commit()
        except OperationError:
            connection.rollback()
            raise
        except Exception:
            connection.rollback()
            raise OperationError('ALERT_JOURNAL_COMMIT_UNKNOWN_READ_ONLY_RECONCILE') from None
        finally:
            connection.close()
        return self.state(alert.alert_id)

    def state(self, alert_id: str) -> JournalState:
        """Read only: INTENT after a restart means do not resend."""
        if re.fullmatch('[0-9a-f]{64}', alert_id) is None:
            raise OperationError('ALERT_IDENTITY_INVALID')
        connection = self._connect()
        try:
            connection.execute('BEGIN')
            _, status, count = self._record(connection, alert_id)
            return JournalState(alert_id, status, count)
        except OperationError:
            raise
        except Exception:
            raise OperationError('ALERT_JOURNAL_READ_UNAVAILABLE') from None
        finally:
            connection.close()

    def send_once(self, alert: delivery.Alert, sender: Callable[[delivery.Alert], delivery.Acceptance],
                  *, clock: Callable[[], datetime], commissioned: bool = False) -> JournalState:
        """Commissioned callers only; persist INTENT before exactly one transport call.

        Any exception after the claim leaves an immutable INTENT/UNKNOWN witness.
        Concurrent callers and restarts cannot send that ID again. A new warning
        needs a freshly evaluated, independently persisted envelope, not a retry.
        """
        if commissioned is not True:
            raise OperationError('ALERT_DELIVERY_NOT_COMMISSIONED')
        validate_alert(alert)
        connection = self._connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT envelope,state FROM alerts WHERE id=?', (alert.alert_id,)).fetchone()
            if row is None or row[0] != alert.data:
                raise OperationError('ALERT_NOT_DURABLY_PERSISTED')
            self._record(connection, alert.alert_id)
            if row[1] != 'PENDING':
                raise OperationError('ALERT_ALREADY_ATTEMPTED_RECONCILE')
            stamp = self._transition_stamp(connection, alert.alert_id, clock())
            connection.execute('UPDATE alerts SET state=? WHERE id=?', ('INTENT', alert.alert_id))
            connection.execute('INSERT INTO events(id,state,at) VALUES (?,?,?)',
                               (alert.alert_id, 'INTENT', stamp))
            connection.commit()
        except OperationError:
            connection.rollback()
            raise
        except Exception:
            connection.rollback()
            raise OperationError('ALERT_CLAIM_COMMIT_UNKNOWN_DO_NOT_SEND') from None
        finally:
            connection.close()
        try:
            result = delivery.attempt(alert, sender, clock=clock)
            status = 'ACCEPTED' if result['provider_acceptance_observed'] else 'UNKNOWN'
        except Exception:
            status = 'UNKNOWN'
        connection = self._connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            stamp = self._transition_stamp(connection, alert.alert_id, clock())
            updated = connection.execute('UPDATE alerts SET state=? WHERE id=? AND state=?',
                                         (status, alert.alert_id, 'INTENT'))
            if updated.rowcount != 1:
                raise OperationError('ALERT_COMPLETION_CONFLICT')
            connection.execute('INSERT INTO events(id,state,at) VALUES (?,?,?)',
                               (alert.alert_id, status, stamp))
            connection.commit()
        except Exception:
            connection.rollback()
            raise OperationError('ALERT_RESULT_COMMIT_UNKNOWN_DO_NOT_RESEND') from None
        finally:
            connection.close()
        return self.state(alert.alert_id)

    @staticmethod
    def _transition_stamp(connection: sqlite3.Connection, alert_id: str, at: datetime) -> str:
        previous = connection.execute('SELECT at FROM events WHERE id=? ORDER BY seq DESC LIMIT 1',
                                      (alert_id,)).fetchone()
        stamp = instant(at)
        if previous is None or stamp < instant(datetime.fromisoformat(previous[0])):
            raise OperationError('ALERT_TRANSITION_CLOCK_REGRESSION_NO_SEND')
        return stamp.isoformat()


class HTTPSPost(Protocol):
    """Injected transport: implementations must not log paths or bodies."""
    def __call__(self, path: str, body: bytes, /) -> tuple[int, bytes]: ...


def telegram_https_post(path: str, body: bytes) -> tuple[int, bytes]:
    """Fixed-host TLS, no redirects/retries, bounded response and explicit timeout."""
    connection = http.client.HTTPSConnection('api.telegram.org', timeout=10,
                                            context=ssl.create_default_context())
    try:
        connection.request('POST', path, body, {'Content-Type': 'application/json'})
        response = connection.getresponse()
        data = response.read(16_385)
        if len(data) > 16_384:
            raise OperationError('ALERT_RESPONSE_SIZE_BOUND')
        return response.status, data
    except Exception:
        raise OperationError('ALERT_TRANSPORT_UNAVAILABLE') from None
    finally:
        connection.close()


@dataclass(frozen=True, repr=False)
class TelegramSender:
    """Explicit credentials only, never environment reads; paid broadcasts disabled."""
    token: str = field(repr=False)
    chat_id: str = field(repr=False)
    post: HTTPSPost = field(repr=False)
    clock: Callable[[], datetime] = field(repr=False)
    commissioned: bool = False

    def __call__(self, alert: delivery.Alert) -> delivery.Acceptance:
        if self.commissioned is not True:
            raise OperationError('ALERT_DELIVERY_NOT_COMMISSIONED')
        validate_alert(alert)
        if (re.fullmatch('[0-9]{5,20}:[A-Za-z0-9_-]{20,100}', self.token) is None
                or re.fullmatch('-?[0-9]{1,20}', self.chat_id) is None):
            raise OperationError('ALERT_DESTINATION_INVALID')
        # Send a constant redacted notice, not arbitrary source/provider payloads.
        data = json.dumps({'chat_id': self.chat_id,
                           'text': 'Storage/capture health requires review. Alert ID: ' + alert.alert_id,
                           'allow_paid_broadcast': False}, separators=(',', ':')).encode()
        try:
            status, raw = self.post('/bot' + self.token + '/sendMessage', data)
            if status != 200 or not 0 < len(raw) <= 16_384:
                raise ValueError
            reply = json.loads(raw)
            message = reply['result']
            now = instant(self.clock())
            if (reply['ok'] is not True or message.get('text') != json.loads(data)['text']
                    or type(message['message_id']) is not int
                    or message['message_id'] <= 0 or type(message['chat']['id']) is not int
                    or str(message['chat']['id']) != self.chat_id or type(message['date']) is not int
                    or not 0 <= now.timestamp() - message['date'] <= 60):
                raise ValueError
            return delivery.Acceptance(alert.alert_id, now)
        except Exception:
            raise OperationError('ALERT_PROVIDER_REPLY_UNVERIFIED') from None
