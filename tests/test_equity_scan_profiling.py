import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
import streamlit as st

import equity_scan_profiling as p


def in_scan(function, scan_id="profile-test"):
    @p.profile_controller
    def controller(self, job):
        return function()
    return controller(None, {"id": scan_id})


def test_no_context_is_noop_and_context_preserves_values_and_errors():
    sentinel = object()
    assert p.call("outside", lambda: sentinel) is sentinel
    error = ValueError("secret raw error must never appear")

    def body():
        assert p.call("success", lambda: sentinel) is sentinel
        with pytest.raises(ValueError) as caught:
            with p.span("failure"):
                raise error
        assert caught.value is error
    in_scan(body)
    report = p.snapshot("profile-test")
    assert [e["state"] for e in report["events"]] == ["complete", "raised"]
    assert "secret" not in json.dumps(report)
    assert p._context.get() is None


def test_bounded_events_and_scans(monkeypatch):
    monkeypatch.setattr(p, "MAX_EVENTS", 2)
    monkeypatch.setattr(p, "MAX_SCANS", 2)
    def body():
        for _ in range(5):
            p.call("stage", lambda: None)
    in_scan(body, "bound-1")
    assert p.snapshot("bound-1")["dropped_events"] == 3
    in_scan(body, "bound-2")
    in_scan(body, "bound-3")
    assert p.snapshot("bound-1") is None


def test_recorder_failure_does_not_change_worker(monkeypatch):
    class Broken:
        def get(self, key):
            raise RuntimeError("diagnostics failed")
    monkeypatch.setattr(p, "_profiles", Broken())
    with p.candidate_context("id", "stock"):
        assert p.call("stage", lambda: 42) == 42


def test_streamlit_cache_refresh_hit_clear_and_lock_wait():
    entered = threading.Event()
    release = threading.Event()
    attempts = threading.Event()
    refreshes = []

    @p.observe_health_cache
    @st.cache_data(ttl=30, show_spinner=False)
    @p.timed("health_cache_refresh")
    def health():
        refreshes.append(1)
        entered.set()
        assert release.wait(5)
        return {"status": "PASS"}

    health.clear()
    def worker(item):
        if item == "B":
            attempts.set()
        return health()

    def body():
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(p.run_candidate, "cache-test", "A", time.perf_counter(), worker, "A")
            assert entered.wait(5)
            second = pool.submit(p.run_candidate, "cache-test", "B", time.perf_counter(), worker, "B")
            assert attempts.wait(5)
            # Ensure a real contended miss before allowing the first refresh out.
            limit = time.monotonic() + 5
            while time.monotonic() < limit:
                events = p.snapshot("cache-test")["events"]
                if any(e["candidate"] == "B" and e["stage"] == "health_cache_call" for e in events):
                    break
                time.sleep(.001)
            time.sleep(.03)
            release.set()
            assert first.result(5) == second.result(5) == {"status": "PASS"}
        assert health() == {"status": "PASS"}  # Hit: no refresh or lock.
    try:
        in_scan(body, "cache-test")
        report = p.snapshot("cache-test")
        assert len(refreshes) == 1
        assert report["totals"]["health_cache_refresh"]["count"] == 1
        assert report["totals"]["health_cache_call"]["count"] == 3
        waits = [e for e in report["events"] if e["stage"] == "health_cache_lock_wait"]
        assert len(waits) == 2
        assert next(e for e in waits if e["candidate"] == "B")["seconds"] > .01
        health.clear()
        assert health() == {"status": "PASS"}
        assert len(refreshes) == 2
    finally:
        release.set()
        health.clear()


def test_cache_exception_not_swallowed_or_cached():
    error = RuntimeError("private error")
    @p.observe_health_cache
    @st.cache_data(show_spinner=False)
    @p.timed("health_cache_refresh")
    def fail():
        raise error
    def body():
        for _ in range(2):
            with pytest.raises(RuntimeError) as caught:
                fail()
            assert caught.value is error
    in_scan(body, "cache-error")
    assert p.snapshot("cache-error")["totals"]["health_cache_refresh"]["count"] == 2


def test_unsupported_cache_explicit_not_false_zero():
    wrapped = p.observe_health_cache(lambda: 7)
    assert in_scan(wrapped, "unsupported") == 7
    report = p.snapshot("unsupported")
    assert "health_cache_lock_instrumentation_unavailable" in report["totals"]
    assert "health_cache_lock_wait" not in report["totals"]
