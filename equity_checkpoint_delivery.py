"""SQLite-owned checkpoint delivery; no remote I/O on the scan controller.

The local checkpoint and queue insertion share the controller's transaction.
Only wakeups are volatile. Receipts, failures and retries survive process restart
when the SQLite file survives. This does not make hosted local storage durable.
"""
from contextlib import contextmanager, ExitStack
from contextvars import Context
import json
import logging
from pathlib import Path
import sqlite3
import threading
import time

from equity_evidence_delivery import delivery_owner
from equity_scan_repository import CheckpointOutcome

_registry = {}
_registry_lock = threading.Lock()


@contextmanager
def local_connection(path):
    conn = sqlite3.connect(str(path), timeout=30)
    try:
        conn.execute('PRAGMA busy_timeout=30000')
        yield conn
    finally:
        conn.close()


def ensure_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS checkpoint_outbox (
        scan_id TEXT NOT NULL, candidate TEXT NOT NULL, fencing_token TEXT NOT NULL,
        checkpoint_json TEXT NOT NULL, created_at REAL NOT NULL, delivered_at REAL,
        attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at REAL NOT NULL DEFAULT 0,
        last_error TEXT, PRIMARY KEY(scan_id,candidate,fencing_token))''')
    conn.execute('''CREATE INDEX IF NOT EXISTS checkpoint_outbox_pending
        ON checkpoint_outbox(next_attempt_at,created_at) WHERE delivered_at IS NULL''')
    if 'remote_finalized_token' not in {r[1] for r in conn.execute('PRAGMA table_info(durable_scan_jobs)')}:
        conn.execute('ALTER TABLE durable_scan_jobs ADD COLUMN remote_finalized_token INTEGER')


def enqueue(conn, payload):
    """Caller owns transaction. Same identity may never acquire another payload."""
    key = (payload['run_id'], payload['instrument'], str(payload['fencing_token']))
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False)
    prior = conn.execute('''SELECT checkpoint_json FROM checkpoint_outbox
        WHERE scan_id=? AND candidate=? AND fencing_token=?''', key).fetchone()
    if prior:
        if prior[0] != encoded:
            raise ValueError('Conflicting checkpoint delivery identity')
        return
    conn.execute('''INSERT INTO checkpoint_outbox
        (scan_id,candidate,fencing_token,checkpoint_json,created_at) VALUES(?,?,?,?,?)''',
        (*key, encoded, time.time()))


def has_pending(path, scan_id):
    with local_connection(path) as conn:
        return conn.execute('SELECT 1 FROM checkpoint_outbox WHERE scan_id=? AND delivered_at IS NULL LIMIT 1',
                            (scan_id,)).fetchone() is not None


class CheckpointSender:
    def __init__(self, path, repository, *, poll_seconds=1, batch_size=50):
        self.path = str(Path(path).resolve())
        self.repository = repository
        self.poll_seconds = poll_seconds
        self.batch_size = max(1, min(int(batch_size), 50))
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._thread = None

    def notify(self):
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._stop.clear()
                self._thread = threading.Thread(target=Context().run, args=(self._run,),
                                                daemon=True, name='equity-checkpoint-sender')
                self._thread.start()
        self._wake.set()

    def stop(self, timeout=2):
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout)

    def _run(self):
        while not self._stop.is_set():
            self._wake.clear()
            try:
                self.drain_once()
            except Exception as exc:
                logging.getLogger(__name__).error('CHECKPOINT_DELIVERY_ERROR %s', type(exc).__name__)
            self._wake.wait(self.poll_seconds)

    def _acknowledge(self, key):
        with local_connection(self.path) as conn:
            conn.execute('''UPDATE checkpoint_outbox SET delivered_at=?,last_error=NULL
                WHERE scan_id=? AND candidate=? AND fencing_token=? AND delivered_at IS NULL''',
                (time.time(), *key))
            conn.commit()

    def drain_once(self):
        stats = dict(selected=0, delivered=0, failed=0)
        with delivery_owner(self.path + '.checkpoint-sender.lock') as owned:
            if not owned:
                return stats
            with local_connection(self.path) as conn:
                rows = conn.execute('''SELECT scan_id,candidate,fencing_token,checkpoint_json,attempts
                    FROM checkpoint_outbox WHERE delivered_at IS NULL AND next_attempt_at<=?
                      AND (last_error IS NULL OR last_error<>'CONFLICT')
                    ORDER BY created_at,scan_id,candidate LIMIT ?''', (time.time(), self.batch_size)).fetchall()
            stats['selected'] = len(rows)
            with ExitStack() as stack:
                deliver = None
                for scan_id, candidate, token, encoded, attempts in rows:
                    key = (scan_id, candidate, token)
                    try:
                        if deliver is None:
                            deliver = stack.enter_context(self.repository.checkpoint_delivery_session())
                        outcome = deliver(**json.loads(encoded))
                        if outcome not in (CheckpointOutcome.NEW, CheckpointOutcome.IDEMPOTENT_SUCCESS):
                            error = 'CONFLICT'
                        else:
                            # A crash here leaves the row queued. Remote retry must
                            # explicitly acknowledge the identical committed receipt.
                            self._acknowledge(key)
                            stats['delivered'] += 1
                            continue
                    except Exception as exc:
                        error = type(exc).__name__
                        stack.close()
                        deliver = None
                    stats['failed'] += 1
                    with local_connection(self.path) as conn:
                        conn.execute('''UPDATE checkpoint_outbox SET attempts=attempts+1,
                            next_attempt_at=?,last_error=?
                            WHERE scan_id=? AND candidate=? AND fencing_token=? AND delivered_at IS NULL''',
                            (time.time() + min(60, 2 ** min(attempts, 6)), error, *key))
                        conn.commit()
            if stats['selected']:
                logging.getLogger(__name__).info('CHECKPOINT_DELIVERY %s', json.dumps(stats, sort_keys=True))
            self._finalize_runs()
        return stats

    def _finalize_runs(self):
        with local_connection(self.path) as conn:
            runs = conn.execute('''SELECT j.job_id,j.fencing_token,j.status,j.finished_at,j.summary_json
                FROM durable_scan_jobs j WHERE j.status IN ('COMPLETE','INTERRUPTED','CANCELLED')
                AND (j.remote_finalized_token IS NULL OR j.remote_finalized_token<>j.fencing_token)
                AND NOT EXISTS (SELECT 1 FROM checkpoint_outbox o
                    WHERE o.scan_id=j.job_id AND o.fencing_token=CAST(j.fencing_token AS TEXT)
                      AND o.delivered_at IS NULL)''').fetchall()
        for run_id, token, status, finished, summary in runs:
            if self.repository.heartbeat(run_id, token, status=status, finished_at=finished,
                                         error_kind=json.loads(summary).get('error')):
                with local_connection(self.path) as conn:
                    conn.execute('''UPDATE durable_scan_jobs SET remote_finalized_token=?
                        WHERE job_id=? AND fencing_token=? AND status=?''', (token, run_id, token, status))
                    conn.commit()


def get_sender(path, repository):
    key = str(Path(path).resolve())
    with _registry_lock:
        if key not in _registry:
            _registry[key] = CheckpointSender(key, repository)
        return _registry[key]
