"""Equity-only durable outbox sender, independent of scan workers and Streamlit.

Only the wake-up is in memory. Committed SQLite outbox rows are the work queue.
One OS-locked owner drains a local outbox, reusing a connection per bounded batch.
No prices, payloads, connection strings or raw exception text enter diagnostics.
"""
from contextlib import contextmanager, ExitStack
from contextvars import Context, ContextVar
from functools import wraps
import json
import logging
import os
from pathlib import Path
import threading
import time

_equity_worker = ContextVar("equity_evidence_worker", default=False)
_registry_lock = threading.Lock()
_senders = {}


def in_equity_worker():
    return _equity_worker.get()


def equity_evidence_worker(worker):
    @wraps(worker)
    def wrapped(*args, **kwargs):
        token = _equity_worker.set(True)
        try:
            return worker(*args, **kwargs)
        finally:
            _equity_worker.reset(token)
    return wrapped


@contextmanager
def delivery_owner(path):
    """Nonblocking, crash-released ownership, also across local processes.

    Never unlink this sidecar: replacing its inode would defeat ownership.
    This lock is NOT the SQLite transaction/write lock.
    """
    with open(path, "a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            acquire = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            release = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            acquire = lambda: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            release = lambda: fcntl.flock(handle, fcntl.LOCK_UN)
        try:
            acquire()
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            handle.seek(0)
            release()


class EquityEvidenceSender:
    def __init__(self, ledger, repository, *, batch_size=50, poll_seconds=5):
        self.ledger = ledger
        self.repository = repository
        self.batch_size = max(1, min(int(batch_size), 50))
        self.poll_seconds = float(poll_seconds)
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._lifecycle_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self._stats = {"scope": "process_cumulative", "attempts": 0,
                       "delivered": 0, "duplicate_acknowledgments": 0,
                       "failed": 0, "network_seconds": 0.0, "last_error_type": None}

    def notify(self):
        # No SQLite reads or remote calls on the producer's thread.
        with self._lifecycle_lock:
            if self._thread is None or not self._thread.is_alive():
                self._stop.clear()
                self._thread = threading.Thread(target=Context().run, args=(self._run,), daemon=True,
                                                name="equity-evidence-sender")
                self._thread.start()
        self._wake.set()

    def stop(self, timeout=2):
        """Testing/shutdown aid, never called from a candidate or scan finalizer."""
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def snapshot(self):
        with self._stats_lock:
            return {**self._stats, "running": bool(self._thread and self._thread.is_alive())}

    def _error(self, exc):
        with self._stats_lock:
            self._stats["last_error_type"] = type(exc).__name__

    def drain_once(self):
        summary = {"selected": 0, "delivered": 0, "failed": 0}
        if not self.repository.configured:
            return summary
        with delivery_owner(self.ledger.delivery_owner_path) as owned:
            if not owned:
                return summary
            events = self.ledger.pending_deliveries(self.batch_size, delivery_lane="equity")
            summary["selected"] = len(events)
            blocked_aggregates = set()
            with ExitStack() as sessions:
                send = None
                for event in events:
                    if self._stop.is_set():
                        break
                    aggregate = event["aggregate_id"]
                    if aggregate in blocked_aggregates:
                        continue
                    last_error = None
                    for attempt in range(3):
                        started = time.perf_counter()
                        try:
                            if send is None:
                                send = sessions.enter_context(self.repository.evidence_delivery_session())
                            result = send(**event)
                        except Exception as exc:
                            last_error = exc
                            self._error(exc)
                            # Failed/uncertain connection is never reused.
                            try:
                                sessions.close()
                            except Exception:
                                pass
                            send = None
                        else:
                            last_error = None
                            break
                        finally:
                            with self._stats_lock:
                                self._stats["attempts"] += 1
                                self._stats["network_seconds"] += time.perf_counter() - started
                        if attempt < 2 and self._stop.wait(.25 * (3 ** attempt)):
                            break
                    if last_error is not None:
                        self.ledger.queue_delivery(event, type(last_error).__name__)
                        blocked_aggregates.add(aggregate)
                        summary["failed"] += 1
                        with self._stats_lock:
                            self._stats["failed"] += 1
                        continue
                    # Remote commit precedes ACK. If ACK raises, stop the batch:
                    # leave the row pending and retry the SAME identity later.
                    self.ledger.mark_delivered(event["idempotency_key"])
                    summary["delivered"] += 1
                    with self._stats_lock:
                        self._stats["delivered"] += 1
                        self._stats["duplicate_acknowledgments"] += int(bool(result.get("duplicate")))
                        self._stats["last_error_type"] = None
        if summary["selected"]:
            logging.getLogger(__name__).info("EQUITY_EVIDENCE_DELIVERY %s", json.dumps(summary))
        return summary

    def _run(self):
        while not self._stop.is_set():
            self._wake.wait(self.poll_seconds)
            self._wake.clear()
            if self._stop.is_set():
                break
            try:
                while not self._stop.is_set():
                    summary = self.drain_once()
                    if summary["selected"] < self.batch_size or summary["delivered"] == 0:
                        break
            except Exception as exc:
                self._error(exc)
                logging.getLogger(__name__).warning("Equity evidence sender deferred: %s", type(exc).__name__)


def get_equity_sender(ledger, repository):
    """One process-local service across Streamlit reruns; OS lock adds fencing."""
    path = str(Path(ledger.delivery_owner_path).resolve())
    with _registry_lock:
        sender = _senders.get(path)
        if sender is None:
            sender = EquityEvidenceSender(ledger, repository)
            _senders[path] = sender
        return sender
