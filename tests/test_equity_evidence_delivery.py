import ast
from contextlib import contextmanager
import datetime as dt
import json
import logging
import multiprocessing
import os
from pathlib import Path
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from equity_evidence_delivery import (
    EquityEvidenceSender, delivery_owner, equity_evidence_worker, in_equity_worker,
)
from evidence_ledger import ImmutableEvidenceLedger
from resilience_control_plane import ResilienceControlPlane, SafetyState

ROOT = Path(__file__).resolve().parents[1]


def connect(path):
    return sqlite3.connect(path, timeout=10)


def ledger(path):
    return ImmutableEvidenceLedger(connect, str(path))


def event(key="one", aggregate="equity:test", asset="equity"):
    payload = {"identifiers": {"asset_class": asset}, "entry": 123}
    return dict(aggregate_id=aggregate, event_type="DECISION_EVALUATED", payload=payload,
                effective_at="2026-09-12T04:00:00+00:00", idempotency_key=key)


def wait_for(predicate):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("sender did not reach expected state")


class Remote:
    configured = True
    def __init__(self, path):
        self.store = ledger(path)
        self.connections = 0
        self.attempts = []
        self.hook = None

    @contextmanager
    def evidence_delivery_session(self):
        self.connections += 1
        def send(**request):
            self.attempts.append(request["idempotency_key"])
            if self.hook:
                self.hook(request)
            return self.store.append(**request)
        yield send


def app_recording(store, remote, sender):
    source = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    wanted = {"_record_trade_evidence", "_flush_evidence_outbox", "_append_durable_with_retry"}
    nodes = [n for n in source.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    namespace = {"EVIDENCE_LEDGER": store, "DURABLE_REPOSITORY": remote,
                 "LOGGER": logging.getLogger("delivery-test"), "time": time,
                 "in_equity_worker": in_equity_worker,
                 "get_equity_sender": lambda *args: sender,
                 "profile_timed": lambda name: lambda function: function,
                 "profile_call": lambda name, function, *args, **kwargs: function(*args, **kwargs)}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), namespace)
    return namespace


def test_blocked_network_does_not_block_equity_producer_or_ancillary_events(tmp_path):
    store, remote = ledger(tmp_path / "local"), Remote(tmp_path / "remote")
    entered, release = threading.Event(), threading.Event()
    def block(request):
        entered.set()
        assert release.wait(10)
    remote.hook = block
    sender = EquityEvidenceSender(store, remote, poll_seconds=.02)
    namespace = app_recording(store, remote, sender)
    record = namespace["_record_trade_evidence"]
    try:
        first = record(**event())
        assert first and entered.wait(5)
        # Sender is still blocked. These commits must finish without its release.
        for number in range(10):
            assert record(**event(str(number)))
        @equity_evidence_worker
        def ancillary():
            return record(aggregate_id="feature:test", event_type="FEATURE_QUALITY_OBSERVED",
                          payload={"feature_count": 3}, effective_at="2026-09-12T04:00:00+00:00",
                          idempotency_key="ancillary")
        assert ancillary()["payload"] == {"feature_count": 3}
        assert not in_equity_worker()
        assert store.outbox_stats()["pending"] == 12
        assert store.pending_deliveries(delivery_lane="legacy") == []
        assert len(store.pending_deliveries(delivery_lane="equity")) == 12
        assert remote.attempts == ["one"]
    finally:
        release.set()
        sender.stop()


def test_one_owner_even_for_two_senders_and_producers_can_commit(tmp_path):
    store, remote = ledger(tmp_path / "local"), Remote(tmp_path / "remote")
    store.append(**event(), queue_remote_delivery=True)
    entered, release = threading.Event(), threading.Event()
    remote.hook = lambda request: (entered.set(), release.wait(5))
    first, second = EquityEvidenceSender(store, remote), EquityEvidenceSender(store, remote)
    thread = threading.Thread(target=first.drain_once)
    thread.start()
    try:
        assert entered.wait(5)
        assert second.drain_once()["selected"] == 0
        store.append(**event("two"), queue_remote_delivery=True)
        assert len(store.pending_deliveries()) == 2
    finally:
        release.set()
        thread.join(5)
    second.drain_once()
    assert remote.attempts == ["one", "two"]


def own_until_crash(path, ready):
    with delivery_owner(path) as owned:
        assert owned
        ready.set()
        time.sleep(60)


def test_os_ownership_is_cross_process_and_released_on_crash(tmp_path):
    path = str(tmp_path / "owner.lock")
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Event()
    process = ctx.Process(target=own_until_crash, args=(path, ready))
    process.start()
    try:
        assert ready.wait(10)
        with delivery_owner(path) as owned:
            assert owned is False
    finally:
        process.terminate()
        process.join(10)
    with delivery_owner(path) as owned:
        assert owned is True


def test_ack_failure_retries_same_identity_and_payload(tmp_path, monkeypatch):
    store, remote = ledger(tmp_path / "local"), Remote(tmp_path / "remote")
    original = store.append(**event(), queue_remote_delivery=True)
    sender = EquityEvidenceSender(store, remote)
    real_ack = store.mark_delivered
    def fail_ack(key):
        raise sqlite3.OperationalError("injected ACK failure")
    monkeypatch.setattr(store, "mark_delivered", fail_ack)
    with pytest.raises(sqlite3.OperationalError):
        sender.drain_once()
    assert len(store.pending_deliveries()) == 1
    monkeypatch.setattr(store, "mark_delivered", real_ack)
    restarted = EquityEvidenceSender(ledger(tmp_path / "local"), remote)
    assert restarted.drain_once()["delivered"] == 1
    assert restarted.snapshot()["duplicate_acknowledgments"] == 1
    assert len(remote.store.events(original["aggregate_id"])) == 1
    assert remote.store.events(original["aggregate_id"])[0]["payload"] == original["payload"]
    assert store.pending_deliveries() == []
    assert store.verify()["valid"]


def test_failed_predecessor_blocks_same_aggregate_not_other_aggregates(tmp_path):
    store, remote = ledger(tmp_path / "local"), Remote(tmp_path / "remote")
    for key, aggregate in (("one", "A"), ("two", "A"), ("three", "B")):
        store.append(**event(key, aggregate), queue_remote_delivery=True)
    def fail(request):
        if request["idempotency_key"] == "one":
            raise OSError("synthetic private connection text")
    remote.hook = fail
    sender = EquityEvidenceSender(store, remote)
    result = sender.drain_once()
    assert result == {"selected": 3, "delivered": 1, "failed": 1}
    assert remote.attempts == ["one", "one", "one", "three"]
    assert store.pending_deliveries(delivery_lane="equity") == []
    assert "synthetic private" not in json.dumps(sender.snapshot())
    # Test clock/backoff boundary without fabricating production observations.
    conn = connect(tmp_path / "local")
    conn.execute("UPDATE evidence_delivery_outbox SET next_attempt_at='2000-01-01T00:00:00+00:00'")
    conn.commit()
    conn.close()
    remote.hook = None
    assert sender.drain_once()["delivered"] == 2
    assert [e["idempotency_key"] for e in remote.store.events("A")] == ["one", "two"]


def test_background_startup_drains_existing_queue_without_new_candidate(tmp_path):
    path = tmp_path / "local"
    ledger(path).append(**event(), queue_remote_delivery=True)
    store, remote = ledger(path), Remote(tmp_path / "remote")
    sender = EquityEvidenceSender(store, remote, poll_seconds=.02)
    try:
        sender.notify()
        wait_for(lambda: not store.pending_deliveries())
        # Periodic retry also operates without another notification.
        store.append(**event("later"), queue_remote_delivery=True)
        wait_for(lambda: not store.pending_deliveries())
        assert remote.attempts == ["one", "later"]
    finally:
        sender.stop()


def test_ancillary_queue_is_atomic_and_explicit_non_equity_cannot_opt_in(tmp_path, monkeypatch):
    store = ledger(tmp_path / "local")
    request = dict(aggregate_id="feature:test", event_type="FEATURE_DEFINITION_REGISTERED",
                   payload={"definition": 1}, idempotency_key="feature")
    original = store._queue_committed_event
    def fail(*args):
        raise sqlite3.OperationalError("injected")
    monkeypatch.setattr(store, "_queue_committed_event", fail)
    with pytest.raises(sqlite3.OperationalError):
        store.append(**request, queue_remote_delivery=True, equity_scan_context=True)
    assert store.events("feature:test") == []
    monkeypatch.setattr(store, "_queue_committed_event", original)
    with pytest.raises(ValueError):
        store.append(**event(asset="options"), queue_remote_delivery=True, equity_scan_context=True)
    assert store.append(**request, queue_remote_delivery=True, equity_scan_context=True)["payload"] == request["payload"]


def test_legacy_non_equity_still_delivers_synchronously_and_cannot_flush_equity(tmp_path):
    store = ledger(tmp_path / "local")
    store.append(**event("background"), queue_remote_delivery=True)
    calls = []
    remote = SimpleNamespace(configured=True, append_evidence_event=lambda **request: calls.append(request))
    class ForbiddenSender:
        def notify(self):
            raise AssertionError("non-equity used sender")
    record = app_recording(store, remote, ForbiddenSender())["_record_trade_evidence"]
    request = event("options", asset="options")
    assert record(**request)
    assert [row["idempotency_key"] for row in calls] == ["options"]
    assert store.outbox_stats()["pending"] == 1


def test_existing_100_pending_900_seconds_gate_still_trips(tmp_path):
    store = ledger(tmp_path / "local")
    for number in range(101):
        store.append(**event(str(number)), queue_remote_delivery=True)
    control = ResilienceControlPlane()
    assert control.policy.section("outbox") == {
        "maximum_pending_events": 100, "maximum_oldest_pending_seconds": 900}
    assert control.operations.outbox(store.outbox_stats())[0].state == SafetyState.READ_ONLY
    for number in range(1, 101):
        store.mark_delivered(str(number))
    future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=901)
    assert control.operations.outbox(store.outbox_stats(now=future))[0].state == SafetyState.READ_ONLY
    assert control.operations.outbox({"pending": 100, "oldest_pending_seconds": 900}) == []


def test_preexisting_outbox_metadata_upgrade_does_not_change_evidence(tmp_path):
    path = tmp_path / "local"
    store = ledger(path)
    saved = store.append(**event(), queue_remote_delivery=True)
    conn = connect(path)
    conn.execute("ALTER TABLE evidence_delivery_outbox DROP COLUMN delivery_lane")
    conn.commit()
    conn.close()
    reopened = ledger(path)
    assert reopened.events(saved["aggregate_id"])[0]["event_hash"] == saved["event_hash"]
    assert len(reopened.pending_deliveries(delivery_lane="equity")) == 1
    assert reopened.pending_deliveries(delivery_lane="legacy") == []


def test_scope_reset_even_when_worker_raises():
    @equity_evidence_worker
    def fail():
        assert in_equity_worker()
        raise ValueError("fixture")
    with pytest.raises(ValueError):
        fail()
    assert not in_equity_worker()


def test_fresh_and_recovered_scan_wiring_keep_limits_and_equity_context():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    recovered = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                     and n.name == "_evaluate_recovered_stock")
    assert any(isinstance(n, ast.Name) and n.id == "equity_evidence_worker" for n in recovered.decorator_list)
    assert "stage1_shortlist, equity_evidence_worker(evaluate_stock)," in source
    assert source.count('workers=scan_workers, timeout=180 if scan_mode.startswith("Full") else 90') == 2


def crash_after_remote_acceptance(local_path, remote_path):
    store, remote = ledger(local_path), Remote(remote_path)
    store.mark_delivered = lambda key: os._exit(74)
    EquityEvidenceSender(store, remote).drain_once()


def test_process_crash_after_remote_commit_replays_without_duplicate(tmp_path):
    local_path, remote_path = str(tmp_path / "local"), str(tmp_path / "remote")
    ledger(local_path).append(**event(), queue_remote_delivery=True)
    process = multiprocessing.get_context("spawn").Process(
        target=crash_after_remote_acceptance, args=(local_path, remote_path))
    process.start()
    process.join(15)
    if process.is_alive():
        process.terminate()
        process.join()
        pytest.fail("crash-test process did not exit")
    assert process.exitcode == 74
    remote = Remote(remote_path)
    assert EquityEvidenceSender(ledger(local_path), remote).drain_once()["delivered"] == 1
    assert len(remote.store.events("equity:test")) == 1
