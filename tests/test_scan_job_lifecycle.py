"""Storage failures release coordinator ownership without hiding the error."""
import sqlite3

import pytest

import scan_jobs
from scan_jobs import ScanBusy, ScanJobs


class DeferredThread:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def start(self):
        pass


def worker(item):
    return None, {'category': 'Trend', 'reason': 'fixture'}


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(scan_jobs.threading, 'Thread', DeferredThread)
    return ScanJobs(str(tmp_path / 'jobs.sqlite'))


def assert_reusable(jobs, monkeypatch, persist):
    assert jobs._busy is False
    monkeypatch.setattr(jobs, '_persist', persist)
    assert jobs.start('owner', 'next', [], worker)
    job = jobs._jobs[('owner', 'next')]
    jobs._run(job, (), worker, 1, 1)
    assert not jobs._busy


@pytest.mark.parametrize('stage', ['initial', 'checkpoint-error-report'])
def test_start_storage_failure_releases_reservation(jobs, monkeypatch, stage):
    persist = jobs._persist
    failure = sqlite3.OperationalError('disk unavailable')

    def failing(owner, signature, job, status=None):
        if stage == 'initial' or status == 'INTERRUPTED':
            raise failure
        return persist(owner, signature, job, status)

    if stage != 'initial':
        def bad_checkpoints(*args):
            raise OSError('checkpoint failure')
        monkeypatch.setattr(jobs, '_create_checkpoints', bad_checkpoints)
    with monkeypatch.context() as patch:
        patch.setattr(jobs, '_persist', failing)
        with pytest.raises(sqlite3.OperationalError) as caught:
            jobs.start('owner', 'sig', ['ABC'], worker)
        assert caught.value is failure
        assert jobs.snapshot('owner', 'sig') is None
    monkeypatch.setattr(jobs, '_create_checkpoints', lambda *args: None)
    assert_reusable(jobs, monkeypatch, persist)


def test_recovery_storage_failure_releases_reservation(jobs, monkeypatch):
    jobs.start('owner', 'sig', ['ABC'], worker)
    jobs._busy = False  # Simulate the stopped controller of an interrupted run.
    persist = jobs._persist
    failure = sqlite3.OperationalError('recovery disk failure')

    def failing(*args, **kwargs):
        raise failure

    monkeypatch.setattr(jobs, '_persist', failing)
    with pytest.raises(sqlite3.OperationalError) as caught:
        jobs.recover('owner', 'sig', worker)
    assert caught.value is failure
    assert jobs.snapshot('owner', 'sig') is None
    assert_reusable(jobs, monkeypatch, persist)


@pytest.mark.parametrize('stage', ['RUNNING', 'COMPLETE'])
def test_run_persistence_failure_shuts_down_and_releases(jobs, monkeypatch, stage):
    jobs.start('owner', 'sig', ['ABC'], worker)
    job = jobs._jobs[('owner', 'sig')]
    persist = jobs._persist
    failure = sqlite3.OperationalError('run disk failure')
    shutdowns = []

    class Executor:
        def __init__(self, **kwargs):
            pass

        def submit(self, *args):
            future = scan_jobs.futures.Future()
            future.set_result(worker('ABC'))
            return future

        def shutdown(self, **kwargs):
            shutdowns.append(kwargs)
            assert jobs._busy  # Slot remains reserved through worker cleanup.
            with pytest.raises(ScanBusy):
                jobs.start('owner', 'overlap', [], worker)

    def failing(owner, signature, job, status=None):
        if status == stage:
            raise failure
        return persist(owner, signature, job, status)

    with monkeypatch.context() as patch:
        patch.setattr(scan_jobs.futures, 'ThreadPoolExecutor', Executor)
        patch.setattr(jobs, '_persist', failing)
        with pytest.raises(sqlite3.OperationalError) as caught:
            jobs._run(job, ('ABC',), worker, 1, 1)
    assert caught.value is failure
    assert shutdowns == [{'wait': True, 'cancel_futures': True}]
    assert job['draining'] is False
    assert_reusable(jobs, monkeypatch, persist)


@pytest.mark.parametrize('recovering', [False, True])
def test_thread_start_failure_cleanup_survives_storage_error(jobs, monkeypatch, recovering):
    if recovering:
        jobs.start('owner', 'sig', ['ABC'], worker)
        jobs._busy = False
    persist = jobs._persist

    class BadThread(DeferredThread):
        def start(self):
            raise RuntimeError('cannot start thread')

    def failing(owner, signature, job, status=None):
        if status == 'INTERRUPTED':
            raise sqlite3.OperationalError('error reporting failed')
        return persist(owner, signature, job, status)

    with monkeypatch.context() as patch:
        patch.setattr(scan_jobs.threading, 'Thread', BadThread)
        patch.setattr(jobs, '_persist', failing)
        with pytest.raises((RuntimeError, sqlite3.OperationalError)):
            if recovering:
                jobs.recover('owner', 'sig', worker)
            else:
                jobs.start('owner', 'sig', ['ABC'], worker)
    assert jobs.snapshot('owner', 'sig') is None
    assert_reusable(jobs, monkeypatch, persist)
