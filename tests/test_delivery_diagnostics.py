import sqlite3
import time

from evidence_ledger import ImmutableEvidenceLedger
from equity_checkpoint_delivery import enqueue
from resilience_control_plane import ResilienceControlPlane, SafetyState
from scan_jobs import ScanJobs


def test_evidence_lane_breakdown_and_failure_counter(tmp_path):
    path = str(tmp_path / "evidence.sqlite")
    ledger = ImmutableEvidenceLedger(lambda p: sqlite3.connect(p), path)
    event = dict(aggregate_id="equity:test", event_type="DECISION_EVALUATED",
                 payload={"asset_class": "equity"}, effective_at="2026-10-04T00:00:00+00:00",
                 idempotency_key="equity-event")
    ledger.append(**event, queue_remote_delivery=True)
    legacy = {**event, "aggregate_id": "legacy:test", "idempotency_key": "legacy-event"}
    ledger.queue_delivery(legacy, "ConnectionError")
    stats = ledger.outbox_stats()
    assert stats["pending"] == sum(lane["pending"] for lane in stats["by_lane"].values()) == 2
    assert stats["by_lane"]["equity"]["maximum_recorded_failures"] == 0
    assert stats["by_lane"]["legacy"]["maximum_recorded_failures"] == 1
    ledger.mark_delivered("equity-event")
    assert set(ledger.outbox_stats()["by_lane"]) == {"legacy"}
    ledger.mark_delivered("legacy-event")
    assert ledger.outbox_stats()["pending"] == 0
    assert ledger.outbox_stats()["by_lane"] == {}


def test_recovery_diagnostics_distinguish_completed_analysis_from_pending_delivery(tmp_path):
    jobs = ScanJobs(str(tmp_path / "jobs.sqlite"))
    conn = jobs._connect()
    conn.execute("""INSERT INTO durable_scan_jobs
        (job_id,owner,signature,started_at,status,processed,total,summary_json,updated_at)
        VALUES ('run','owner','sig',?,'COMPLETE',95,95,'{}',?)""", (time.time(), time.time()))
    enqueue(conn, dict(run_id="run", instrument="ONE", fencing_token=1,
                       result=None, rejection={"category": "Trend"}, item="ONE",
                       quote_observed_at=None, governance_decision_at=None))
    conn.commit()
    source = {"id": "run", "status": "RUNNING", "unfinished": ["ONE"]}
    report = jobs.recovery_diagnostics("owner", "sig", source)
    assert report["local_completed"] == report["local_total"] == 95
    assert report["delivery_pending"] is True
    assert report["checkpoint_pending"] == 1
    conn.execute("UPDATE checkpoint_outbox SET last_error='CONFLICT'")
    conn.commit()
    assert jobs.recovery_diagnostics("owner", "sig", source)["checkpoint_conflicts"] == 1
    conn.execute("UPDATE checkpoint_outbox SET delivered_at=?", (time.time(),))
    conn.commit()
    assert jobs.recovery_diagnostics("owner", "sig", source)["delivery_pending"] is False
    assert jobs.recovery_diagnostics("other", "sig", source)["local_status"] is None
    conn.close()


def test_161_pending_still_blocks_after_diagnostic_changes():
    control = ResilienceControlPlane()
    finding = control.operations.outbox({"pending": 161, "oldest_pending_seconds": 37.8,
                                        "by_lane": {"equity": {"pending": 161}}})
    assert finding[0].state == SafetyState.READ_ONLY
    assert control.operations.outbox({"pending": 0, "oldest_pending_seconds": 0}) == []
