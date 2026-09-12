import datetime as dt
import multiprocessing
import sqlite3
import time
from pathlib import Path

from evidence_ledger import ImmutableEvidenceLedger
from scan_jobs import ScanJobs


def _wait_complete(jobs, owner="owner", signature="signature", seconds=10):
    deadline = time.time() + seconds
    while time.time() < deadline:
        result = jobs.snapshot(owner, signature)
        if result and result["complete"]:
            return result
        time.sleep(0.02)
    raise AssertionError("scan did not complete")


def _crashable_scan(path, ready):
    jobs = ScanJobs(path)

    def worker(item):
        if item == "DONE":
            return None, {"category": "Trend", "reason": "completed before crash"}
        time.sleep(60)
        return None, {"category": "Data", "reason": "late"}

    jobs.start("owner", "signature", ["DONE", "PENDING"], worker,
               workers=2, timeout=120, metadata={"scan_mode": "Quick", "horizon_sessions": 15})
    deadline = time.time() + 10
    while time.time() < deadline:
        conn = sqlite3.connect(path)
        status = conn.execute(
            "SELECT status FROM durable_scan_candidates WHERE instrument='DONE'"
        ).fetchone()
        conn.close()
        if status and status[0] == "COMPLETE":
            ready.set()
            break
        time.sleep(0.02)
    time.sleep(60)


def _fresh_result(item):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    return ({"Ticker": item, "Action": "Buy", "_quote_observed_at": now,
             "_governance": {"allow_trade": True, "decision_at": now}}, None)


def test_process_kill_preserves_completed_and_recovers_only_unfinished(tmp_path):
    path = str(tmp_path / "jobs.sqlite")
    ready = multiprocessing.get_context("spawn").Event()
    process = multiprocessing.get_context("spawn").Process(target=_crashable_scan, args=(path, ready))
    process.start()
    assert ready.wait(15)
    process.terminate()
    process.join(10)
    reopened = ScanJobs(path)
    recoverable = reopened.recoverable("owner", "signature")
    assert recoverable["unfinished"] == ["PENDING"]
    assert recoverable["archived_completed"] == 1
    reopened.recover("owner", "signature", _fresh_result, metadata={
        "funnel": {}, "timing": {}, "quote_at": time.time(),
        "scan_mode": "Quick", "horizon_sessions": 15,
    })
    result = _wait_complete(reopened)
    assert [row["Ticker"] for row in result["signals"]] == ["PENDING"]
    assert result["metadata"]["archived_completed"] == 1


def test_recovery_rejects_reused_stale_result(tmp_path):
    path = str(tmp_path / "jobs.sqlite")
    first = ScanJobs(path)
    first.start("owner", "signature", ["LATE"], lambda item: (None, {
        "category": "Cancelled", "reason": "fixture"}), metadata={
            "scan_mode": "Quick", "horizon_sessions": 15})
    _wait_complete(first)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE durable_scan_jobs SET status='INTERRUPTED'")
    conn.execute("UPDATE durable_scan_candidates SET status='PENDING',result_json=NULL,rejection_json=NULL")
    conn.commit(); conn.close()
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)).isoformat()
    reopened = ScanJobs(path)
    reopened.recover("owner", "signature", lambda item: ({
        "Ticker": item, "Action": "Buy", "_quote_observed_at": old,
        "_governance": {"allow_trade": True, "decision_at": old}}, None),
        metadata={"funnel": {}, "timing": {}, "quote_at": time.time()})
    result = _wait_complete(reopened)
    assert result["signals"] == []
    assert result["rejections"] == {"Recovery": 1}
    conn = sqlite3.connect(path)
    stored = conn.execute(
        "SELECT result_json,rejection_json FROM durable_scan_candidates WHERE instrument='LATE'"
    ).fetchone()
    conn.close()
    assert stored[0] is None
    assert '"category":"Recovery"' in stored[1]


def test_old_fencing_token_cannot_overwrite_recovered_candidate(tmp_path):
    path = str(tmp_path / "jobs.sqlite")
    jobs = ScanJobs(path)
    job = {"id": "run", "owner": "owner", "signature": "sig", "fencing_token": 1}
    conn = jobs._connect()
    conn.execute("""INSERT INTO durable_scan_jobs(
      job_id,owner,signature,started_at,status,processed,total,summary_json,updated_at,
      fencing_token,metadata_json,recovered) VALUES ('run','owner','sig',1,'RECOVERING',0,1,'{}',1,2,'{}',1)""")
    conn.execute("""INSERT INTO durable_scan_candidates
      (job_id,instrument,item_json,status,fencing_token,updated_at)
      VALUES ('run','ABC','\"ABC\"','PENDING',2,1)""")
    conn.commit(); conn.close()
    assert not jobs._checkpoint_candidate(job, "ABC", {"Ticker": "STALE"}, None)
    conn = sqlite3.connect(path)
    row = conn.execute("SELECT status,result_json FROM durable_scan_candidates").fetchone()
    conn.close()
    assert row == ("PENDING", None)


def test_recovery_retry_does_not_duplicate_existing_evidence(tmp_path):
    path = str(tmp_path / "jobs.sqlite")
    jobs = ScanJobs(path)
    jobs.start("owner", "signature", ["ABC"], lambda item: (
        None, {"category": "Data", "reason": "fixture"}),
        metadata={"scan_mode": "Quick", "horizon_sessions": 15})
    _wait_complete(jobs)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE durable_scan_jobs SET status='INTERRUPTED'")
    conn.execute("UPDATE durable_scan_candidates SET status='PENDING',result_json=NULL,rejection_json=NULL")
    conn.commit(); conn.close()

    ledger_path = str(tmp_path / "ledger.sqlite")
    ledger = ImmutableEvidenceLedger(sqlite3.connect, ledger_path)
    request = dict(
        aggregate_id="equity:ABC", event_type="DECISION_EVALUATED",
        payload={"identifiers": {"asset_class": "equity"}},
        effective_at="2026-09-13T04:00:00+00:00", idempotency_key="ABC:decision",
    )
    first = ledger.append(**request)

    def worker(item):
        retried = ledger.append(**request)
        assert retried["event_id"] == first["event_id"] and retried["duplicate"]
        return _fresh_result(item)

    reopened = ScanJobs(path)
    reopened.recover("owner", "signature", worker,
                     metadata={"funnel": {}, "timing": {}, "quote_at": time.time()})
    assert len(_wait_complete(reopened)["signals"]) == 1
    assert len(ledger.events("equity:ABC")) == 1


def test_dashboard_recovery_requires_refreshed_stage1_before_stage2():
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    assert "_fresh_stage1_candidates = set(stage1_shortlist)" in source
    assert "if ticker not in _fresh_stage1_candidates:" in source
    assert '"reason": "Candidate did not pass the refreshed Stage-1 evaluation"' in source
    assert "CURRENT_USER_ID, _signature, _evaluate_recovered_stock," in source
