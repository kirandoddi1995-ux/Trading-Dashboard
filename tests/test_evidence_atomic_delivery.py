"""Real SQLite transaction and process-exit tests for equity delivery."""
import multiprocessing
import os
import sqlite3

import pytest

from evidence_ledger import ImmutableEvidenceLedger


def connect(path):
    return sqlite3.connect(path, timeout=10)


def request():
    return dict(aggregate_id="equity:test", event_type="DECISION_EVALUATED",
                payload={"identifiers": {"asset_class": "equity"}, "entry": 123},
                effective_at="2026-09-12T04:00:00+00:00",
                idempotency_key="decision:test")


def ledger(path):
    return ImmutableEvidenceLedger(connect, str(path))


def crash_worker(path, boundary):
    store = ledger(path)
    if boundary == "before_commit":
        original = store._queue_committed_event

        def crash(conn, event):
            original(conn, event)
            os._exit(73)

        store._queue_committed_event = crash
    store.append(**request(), queue_remote_delivery=True)
    os._exit(73)


@pytest.mark.parametrize("boundary,expected", [("before_commit", 0), ("after_commit", 1)])
def test_process_exit_keeps_event_and_delivery_atomic(tmp_path, boundary, expected):
    path = tmp_path / "ledger.sqlite"
    process = multiprocessing.get_context("spawn").Process(
        target=crash_worker, args=(str(path), boundary))
    process.start()
    process.join(20)
    if process.is_alive():
        process.terminate()
        process.join()
        pytest.fail("Crash-test child did not exit")
    assert process.exitcode == 73
    reopened = ledger(path)
    assert len(reopened.events("equity:test")) == expected
    assert len(reopened.pending_deliveries()) == expected
    assert reopened.verify()["valid"]


def test_queue_failure_rolls_back_local_event(tmp_path, monkeypatch):
    store = ledger(tmp_path / "ledger.sqlite")

    def fail(*args):
        raise sqlite3.OperationalError("Injected failure")

    monkeypatch.setattr(store, "_queue_committed_event", fail)
    with pytest.raises(sqlite3.OperationalError):
        store.append(**request(), queue_remote_delivery=True)
    assert store.events("equity:test") == []
    assert store.pending_deliveries() == []


def test_remote_acceptance_before_ack_retries_same_identity(tmp_path):
    path = tmp_path / "ledger.sqlite"
    store = ledger(path)
    event = store.append(**request(), queue_remote_delivery=True)
    remote = ledger(tmp_path / "remote-simulation.sqlite")
    delivered = remote.append(**store.pending_deliveries()[0])
    # Simulate restart before local acknowledgment; remote deduplication survives.
    reopened = ledger(path)
    retried = remote.append(**reopened.pending_deliveries()[0])
    assert delivered["event_id"] == retried["event_id"]
    assert retried["duplicate"]
    reopened.mark_delivered(event["idempotency_key"])
    duplicate = reopened.append(**request(), queue_remote_delivery=True)
    assert duplicate["event_id"] == event["event_id"]
    assert reopened.pending_deliveries() == []


def test_duplicate_queue_uses_original_effective_time(tmp_path):
    store = ledger(tmp_path / "ledger.sqlite")
    args = request()
    args.pop("effective_at")
    first = store.append(**args, queue_remote_delivery=True)
    second = store.append(**args, queue_remote_delivery=True)
    assert second["event_id"] == first["event_id"]
    assert store.pending_deliveries()[0]["effective_at"] == first["effective_at"]


def test_tampered_duplicate_fails_without_overwriting_queue(tmp_path):
    store = ledger(tmp_path / "ledger.sqlite")
    store.append(**request(), queue_remote_delivery=True)
    before = store.pending_deliveries()
    tampered = request()
    tampered["payload"]["entry"] = 124
    with pytest.raises(ValueError, match="different evidence"):
        store.append(**tampered, queue_remote_delivery=True)
    assert store.pending_deliveries() == before
    assert len(store.events("equity:test")) == 1


def test_default_and_non_equity_append_behavior_unchanged(tmp_path):
    store = ledger(tmp_path / "ledger.sqlite")
    args = request()
    args["payload"]["identifiers"]["asset_class"] = "options"
    event = store.append(**args)
    assert event["payload"] == args["payload"]
    assert store.pending_deliveries() == []
    with pytest.raises(ValueError, match="restricted to explicit equity"):
        store.append(**args, queue_remote_delivery=True)
    assert len(store.events("equity:test")) == 1
