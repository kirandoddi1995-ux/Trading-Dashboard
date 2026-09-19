import ast
from contextlib import contextmanager
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

import equity_scan_profiling as p
from equity_runtime_health import recovery_health, RELEASE_FILES
from scan_jobs import ScanJobs
from equity_scan_repository import CheckpointOutcome

ROOT = Path(__file__).resolve().parents[1]


def wait_for(predicate):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.01)
    raise AssertionError("background scan did not finish")


def test_actual_scan_records_checkpoint_stages_without_changing_results(tmp_path):
    calls = []
    class Store:
        configured = True
        def create_run(self, job, items):
            calls.append("create")
        @contextmanager
        def checkpoint_delivery_session(self):
            def deliver(**kwargs):
                calls.append("candidate")
                return CheckpointOutcome.NEW
            yield deliver
        def heartbeat(self, *args, **kwargs):
            calls.append("heartbeat")
            return True
    jobs = ScanJobs(str(tmp_path / "scan.sqlite"), Store())
    def worker(item):
        p.call("history_retrieval", lambda: None)
        return None, {"category": "Trend", "reason": "original rejection"}
    scan_id = jobs.start("owner", "signature", ["A", "B"], worker, timeout=5)
    wait_for(lambda: (p.snapshot(scan_id) or {}).get("milestones", {}).get("workers_drained"))
    result = jobs.snapshot("owner", "signature")
    assert result["processed"] == 2 and result["rejections"] == {"Trend": 2}
    assert result["timeouts"] == 0
    wait_for(lambda: 'heartbeat' in calls)
    jobs._checkpoint_sender.stop()
    assert calls == ["create", "candidate", "candidate", "heartbeat"]
    report = p.snapshot(scan_id)
    assert 'checkpoint_postgres_candidate' not in report['totals']
    for stage in ("history_retrieval", "candidate_total", "checkpoint_sqlite_candidate"):
        assert report["totals"][stage]["count"] == 2
    assert "checkpoint_sqlite_job_summary" in report["totals"]
    assert "original rejection" not in json.dumps(report)
    assert "owner" not in json.dumps(report)


def test_deadline_still_discards_late_workers_and_profiles_running_stages():
    release = threading.Event()
    entered = threading.Event()
    jobs = ScanJobs()
    def worker(item):
        with p.span("history_retrieval"):
            entered.set()
            assert release.wait(5)
        return {"Ticker": item}, None
    scan_id = jobs.start("owner", "signature", ["A", "B"], worker, workers=1, timeout=.05)
    try:
        assert entered.wait(5)
        wait_for(lambda: jobs.snapshot("owner", "signature")["complete"])
        report = p.snapshot(scan_id)
        assert any(e["stage"] == "history_retrieval" and e["state"] == "running" and "seconds" not in e for e in report["events"])
        assert jobs.snapshot("owner", "signature")["timeouts"] == 2
        assert "workers_drained" not in report["milestones"]
    finally:
        release.set()
    wait_for(lambda: "workers_drained" in p.snapshot(scan_id)["milestones"])
    assert jobs.snapshot("owner", "signature")["signals"] == []
    assert p.snapshot(scan_id)["totals"]["candidate_total"]["count"] == 1


def test_ledger_verify_separate_from_repository_health_and_outbox():
    calls = []
    def mark(name, result):
        calls.append(name)
        return result
    repository = SimpleNamespace(recovery_health=lambda: mark("checkpoint", {"status": "PASS"}))
    ledger = SimpleNamespace(verify=lambda: mark("verify", {"valid": True, "events_checked": 5}),
                             outbox_stats=lambda: mark("outbox", {"pending": 0}))
    @p.profile_controller
    def controller(self, job):
        return recovery_health(repository, ledger)
    result = controller(None, {"id": "health-wiring"})
    assert result["status"] == "PASS"
    assert calls == ["checkpoint", "verify", "outbox"]
    assert set(p.snapshot("health-wiring")["totals"]) == {
        "recovery_checkpoint_health", "ledger_verification", "ledger_outbox_health"}


def test_remote_retry_instrumentation_preserves_attempts_sleep_and_errors():
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_append_durable_with_retry")
    calls = []
    error = OSError("private credential error")
    def append(**kwargs):
        calls.append("attempt")
        raise error
    namespace = {"profile_timed": p.timed, "profile_call": p.call,
                 "DURABLE_REPOSITORY": SimpleNamespace(append_evidence_event=append),
                 "time": SimpleNamespace(sleep=lambda seconds: calls.append(seconds))}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "app.py", "exec"), namespace)
    @p.profile_controller
    def controller(self, job):
        with pytest.raises(OSError) as caught:
            namespace[function.name]({"secret": "must-not-log"})
        assert caught.value is error
    controller(None, {"id": "remote-retry"})
    assert calls == ["attempt", .25, "attempt", .75, "attempt"]
    report = p.snapshot("remote-retry")
    assert report["totals"]["remote_event_delivery_attempt"]["count"] == 3
    assert "must-not-log" not in json.dumps(report)
    assert "private credential" not in json.dumps(report)


def test_app_wiring_and_release_manifest():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    for stage in ("history_retrieval", "history_live_bar", "indicator_enrichment",
                  "indicator_weekly_trend", "indicator_relative_strength", "clock_measurement"):
        assert f'profile_call("{stage}"' in source
    assert '@observe_health_cache\n@st.cache_data(ttl=30, show_spinner=False)' in source
    assert 'Download scan timing diagnostics (JSON)' in source
    assert "equity_scan_profiling.py" in RELEASE_FILES
