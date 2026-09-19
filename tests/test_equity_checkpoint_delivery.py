from contextlib import contextmanager
import json
import multiprocessing
import sqlite3
import threading
import time

import pytest

import equity_checkpoint_delivery as delivery
from equity_scan_repository import CheckpointOutcome
from scan_jobs import ScanJobs, CheckpointUnavailable


class Store:
    configured = True

    def __init__(self, outcome=CheckpointOutcome.NEW):
        self.outcome = outcome
        self.calls = []
        self.sessions = 0
        self.finished = []

    def create_run(self, *args):
        pass

    @contextmanager
    def checkpoint_delivery_session(self):
        self.sessions += 1
        def send(**payload):
            self.calls.append(payload)
            return self.outcome
        yield send

    def heartbeat(self, *args, **kwargs):
        self.finished.append((args, kwargs))
        return True


def fixture(tmp_path):
    path = str(tmp_path / 'checkpoints.sqlite')
    jobs = ScanJobs(path)
    job = dict(id='run', owner='owner', signature='sig', fencing_token=1,
               started_at=time.time(), processed=0, total=2)
    jobs._persist('owner', 'sig', job, 'RUNNING')
    jobs._create_checkpoints(job, ['A', 'B'])
    return path, jobs, job


def queue(path, candidate='A', token=1, score=1):
    payload = dict(run_id='run', instrument=candidate, fencing_token=token,
                   result={'score': score}, rejection=None, item=candidate,
                   quote_observed_at=None, governance_decision_at=None)
    with delivery.local_connection(path) as conn:
        delivery.enqueue(conn, payload)
        conn.commit()
    return payload


def wait(predicate):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('background task did not finish')


@pytest.mark.parametrize('outcome', [CheckpointOutcome.NEW, CheckpointOutcome.IDEMPOTENT_SUCCESS])
def test_batch_reuses_connection_and_accepts_only_explicit_success(tmp_path, outcome):
    path, _, _ = fixture(tmp_path)
    queue(path, 'A')
    queue(path, 'B')
    store = Store(outcome)
    sender = delivery.CheckpointSender(path, store)
    assert sender.drain_once() == dict(selected=2, delivered=2, failed=0)
    assert store.sessions == 1
    assert not delivery.has_pending(path, 'run')
    assert sender.drain_once()['selected'] == 0


def test_remote_commit_then_local_ack_crash_retries_idempotently(tmp_path, monkeypatch):
    path, _, _ = fixture(tmp_path)
    queue(path)
    store = Store()
    sender = delivery.CheckpointSender(path, store)
    def crash(key):
        raise RuntimeError('simulated local acknowledgment failure')
    monkeypatch.setattr(sender, '_acknowledge', crash)
    assert sender.drain_once() == dict(selected=1, delivered=0, failed=1)
    assert delivery.has_pending(path, 'run')
    with delivery.local_connection(path) as conn:
        conn.execute('UPDATE checkpoint_outbox SET next_attempt_at=0')
        conn.commit()
    store.outcome = CheckpointOutcome.IDEMPOTENT_SUCCESS
    reopened = delivery.CheckpointSender(path, store)
    assert reopened.drain_once()['delivered'] == 1
    assert store.calls[0] == store.calls[1]


@pytest.mark.parametrize('outcome', [CheckpointOutcome.CONFLICT, False, True, None])
def test_no_false_ack_or_retry_churn_for_conflicts(tmp_path, outcome, caplog):
    path, _, _ = fixture(tmp_path)
    queue(path)
    sender = delivery.CheckpointSender(path, Store(outcome))
    with caplog.at_level('INFO'):
        assert sender.drain_once() == dict(selected=1, delivered=0, failed=1)
    assert delivery.has_pending(path, 'run')
    assert sender.drain_once()['selected'] == 0
    assert 'CHECKPOINT_DELIVERY' in caplog.text
    assert 'score' not in caplog.text


def test_local_identity_includes_fence_and_rejects_payload_change(tmp_path):
    path, _, _ = fixture(tmp_path)
    queue(path)
    queue(path)
    with pytest.raises(ValueError, match='Conflicting'):
        queue(path, score=2)
    queue(path, token=2, score=2)
    with delivery.local_connection(path) as conn:
        assert conn.execute('SELECT count(*) FROM checkpoint_outbox').fetchone()[0] == 2


def test_local_candidate_and_outbox_commit_are_atomic(tmp_path, monkeypatch):
    path, jobs, job = fixture(tmp_path)
    jobs._checkpoint_sender = delivery.CheckpointSender(path, Store())
    monkeypatch.setattr(jobs._checkpoint_sender, 'notify', lambda: None)
    import scan_jobs
    def fail(conn, payload):
        delivery.enqueue(conn, payload)
        raise sqlite3.OperationalError('simulated write failure')
    monkeypatch.setattr(scan_jobs, 'enqueue', fail)
    with pytest.raises(sqlite3.OperationalError):
        jobs._checkpoint_candidate(job, 'A', {'score': 1}, None)
    with delivery.local_connection(path) as conn:
        assert conn.execute("SELECT status FROM durable_scan_candidates WHERE instrument='A'").fetchone()[0] == 'PENDING'
        assert conn.execute('SELECT count(*) FROM checkpoint_outbox').fetchone()[0] == 0
    monkeypatch.setattr(scan_jobs, 'enqueue', delivery.enqueue)
    assert jobs._checkpoint_candidate(job, 'A', {'score': 1}, None)
    # Re-opened connection sees both durable records, not just an in-memory wakeup.
    with delivery.local_connection(path) as conn:
        assert conn.execute("SELECT status FROM durable_scan_candidates WHERE instrument='A'").fetchone()[0] == 'COMPLETE'
        assert conn.execute('SELECT count(*) FROM checkpoint_outbox').fetchone()[0] == 1


def test_slow_remote_does_not_block_controller_or_workers(tmp_path):
    entered, release = threading.Event(), threading.Event()
    class Slow(Store):
        @contextmanager
        def checkpoint_delivery_session(self):
            def send(**payload):
                entered.set()
                assert release.wait(5)
                return CheckpointOutcome.NEW
            yield send
    jobs = ScanJobs(str(tmp_path / 'slow.sqlite'), Slow())
    try:
        jobs.start('owner', 'sig', list(range(20)),
                   lambda item: (None, {'category': 'Trend', 'reason': 'fixture'}), timeout=2)
        assert entered.wait(5)
        wait(lambda: jobs.snapshot('owner', 'sig')['complete'])
        result = jobs.snapshot('owner', 'sig')
        assert result['processed'] == 20 and result['timeouts'] == 0
        assert jobs._checkpoint_store.finished == []
    finally:
        release.set()
        jobs._checkpoint_sender.stop(5)


def test_no_remote_complete_until_pending_acknowledged(tmp_path):
    path, jobs, job = fixture(tmp_path)
    queue(path)
    jobs._persist('owner', 'sig', job, 'COMPLETE')
    store = Store(CheckpointOutcome.CONFLICT)
    sender = delivery.CheckpointSender(path, store)
    sender.drain_once()
    assert store.finished == []
    with delivery.local_connection(path) as conn:
        conn.execute('UPDATE checkpoint_outbox SET next_attempt_at=0,last_error=NULL')
        conn.commit()
    store.outcome = CheckpointOutcome.IDEMPOTENT_SUCCESS
    sender.drain_once()
    assert len(store.finished) == 1
    sender.drain_once()
    assert len(store.finished) == 1


def test_recovery_waits_for_local_pending_delivery(tmp_path):
    path, jobs, _ = fixture(tmp_path)
    queue(path)
    class Recovery(Store):
        def latest_recoverable(self, *args):
            return {'id': 'run'}
        def claim_recovery(self, *args):
            pytest.fail('must not advance fencing token with a pending local receipt')
    jobs._checkpoint_store = Recovery()
    class Wake:
        def notify(self):
            pass
    jobs._checkpoint_sender = Wake()
    with pytest.raises(CheckpointUnavailable, match='pending'):
        jobs.recover('owner', 'sig', lambda item: None)


def test_sender_ownership_excludes_duplicate_delivery(tmp_path):
    path, _, _ = fixture(tmp_path)
    queue(path)
    store = Store()
    sender = delivery.CheckpointSender(path, store)
    with delivery.delivery_owner(path + '.checkpoint-sender.lock') as owned:
        assert owned
        assert sender.drain_once()['selected'] == 0
    assert store.calls == []
    assert sender.drain_once()['delivered'] == 1


def test_transient_failure_reopens_connection_and_preserves_payload(tmp_path):
    path, _, _ = fixture(tmp_path)
    expected = queue(path)
    class Broken(Store):
        @contextmanager
        def checkpoint_delivery_session(self):
            self.sessions += 1
            if self.sessions == 1:
                raise ConnectionError('secret must not enter logs')
            yield lambda **payload: CheckpointOutcome.NEW
    store = Broken()
    sender = delivery.CheckpointSender(path, store)
    assert sender.drain_once()['failed'] == 1
    assert sender.drain_once()['selected'] == 0
    with delivery.local_connection(path) as conn:
        encoded, error = conn.execute('SELECT checkpoint_json,last_error FROM checkpoint_outbox').fetchone()
        assert json.loads(encoded) == expected and error == 'ConnectionError'
        conn.execute('UPDATE checkpoint_outbox SET next_attempt_at=0')
        conn.commit()
    assert sender.drain_once()['delivered'] == 1
    assert store.sessions == 2


def _commit_then_wait(path, ready):
    jobs = ScanJobs(path)
    class NoWake:
        def notify(self):
            pass
    jobs._checkpoint_sender = NoWake()
    job = dict(id='run', owner='owner', signature='sig', fencing_token=1,
               started_at=time.time(), processed=0, total=1)
    jobs._persist('owner', 'sig', job, 'RUNNING')
    jobs._create_checkpoints(job, ['A'])
    assert jobs._checkpoint_candidate(job, 'A', {'score': 1}, None)
    ready.set()
    time.sleep(60)


def test_process_termination_preserves_checkpoint_and_queue(tmp_path):
    path = str(tmp_path / 'crash.sqlite')
    ctx = multiprocessing.get_context('spawn')
    ready = ctx.Event()
    process = ctx.Process(target=_commit_then_wait, args=(path, ready))
    process.start()
    try:
        assert ready.wait(15)
    finally:
        process.terminate()
        process.join(10)
    ScanJobs(path)  # restart changes RUNNING to INTERRUPTED, never drops the outbox
    with delivery.local_connection(path) as conn:
        assert conn.execute('SELECT status FROM durable_scan_candidates').fetchone()[0] == 'COMPLETE'
    assert delivery.has_pending(path, 'run')
    assert delivery.CheckpointSender(path, Store()).drain_once()['delivered'] == 1


def test_recovery_on_replacement_host_recreates_only_pending_local_items(tmp_path):
    class Recovery(Store):
        def latest_recoverable(self, *args):
            return dict(id='remote-run', archived_completed=1)
        def claim_recovery(self, *args):
            return dict(fencing_token=2, items=['ABC'], metadata={})
    jobs = ScanJobs(str(tmp_path / 'replacement.sqlite'), Recovery())
    try:
        jobs.recover('owner', 'sig', lambda item: (None, {'category': 'Trend', 'reason': 'fresh evaluation'}))
        wait(lambda: jobs.snapshot('owner', 'sig')['complete'])
        result = jobs.snapshot('owner', 'sig')
        assert result['processed'] == 1 and result['checkpoint_conflicts'] == 0
        with delivery.local_connection(jobs._db_path) as conn:
            rows = conn.execute('SELECT instrument,fencing_token,status FROM durable_scan_candidates').fetchall()
            assert rows == [('ABC', 2, 'COMPLETE')]
            assert conn.execute('SELECT fencing_token FROM checkpoint_outbox').fetchone()[0] == '2'
    finally:
        jobs._checkpoint_sender.stop(5)


def test_late_old_fence_delivery_is_a_visible_failure(tmp_path):
    from test_equity_scan_repository import Connection, repository
    path, _, _ = fixture(tmp_path)
    queue(path, token=1)
    # Active remote fence is already 2. No candidate UPDATE may execute.
    conn = Connection(fetchone=[(2,)])
    repo = repository(conn)
    sender = delivery.CheckpointSender(path, repo)
    assert sender.drain_once() == dict(selected=1, delivered=0, failed=1)
    assert delivery.has_pending(path, 'run')
    assert not any(sql.startswith('UPDATE') for sql, _ in conn.calls)
