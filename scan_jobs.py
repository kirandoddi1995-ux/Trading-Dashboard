"""Process-local scan jobs that survive Streamlit script reruns.

Only the controller writes results. Timed-out worker results are discarded, and
the concurrency slot is retained until those workers drain (threads cannot be
forcibly killed safely). No Streamlit or account APIs are called by this module.
"""
import copy
import concurrent.futures as futures
import json
import math
import sqlite3
import threading
import time
import uuid
import datetime as dt
from equity_scan_profiling import (
    call as profile_call, timed as profile_timed, profile_controller,
    run_candidate, milestone, candidate_context, span,
)


class ScanBusy(RuntimeError):
    pass


class CheckpointUnavailable(RuntimeError):
    pass


class ScanJobs:
    def __init__(self, db_path=None, checkpoint_store=None):
        self._lock = threading.RLock()
        self._jobs = {}
        self._busy = False
        self._db_path = db_path
        self._checkpoint_store = checkpoint_store
        if db_path:
            self._ensure_schema()

    def _connect(self):
        conn = sqlite3.connect(self._db_path, timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL"); conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _ensure_schema(self):
        conn = self._connect()
        try:
            conn.execute("""CREATE TABLE IF NOT EXISTS durable_scan_jobs(
              job_id TEXT PRIMARY KEY, owner TEXT NOT NULL, signature TEXT NOT NULL,
              started_at REAL NOT NULL, finished_at REAL, status TEXT NOT NULL,
              processed INTEGER NOT NULL, total INTEGER NOT NULL, eta_seconds REAL,
              summary_json TEXT NOT NULL, updated_at REAL NOT NULL)""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_durable_scan_owner_time ON durable_scan_jobs(owner,started_at)")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(durable_scan_jobs)")}
            for name, definition in (
                ("fencing_token", "INTEGER NOT NULL DEFAULT 1"),
                ("metadata_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("recovered", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if name not in columns:
                    conn.execute(f"ALTER TABLE durable_scan_jobs ADD COLUMN {name} {definition}")
            conn.execute("""CREATE TABLE IF NOT EXISTS durable_scan_candidates(
              job_id TEXT NOT NULL, instrument TEXT NOT NULL, item_json TEXT NOT NULL,
              status TEXT NOT NULL, fencing_token INTEGER NOT NULL, result_json TEXT,
              rejection_json TEXT, quote_observed_at TEXT, governance_decision_at TEXT,
              updated_at REAL NOT NULL, PRIMARY KEY(job_id,instrument))""")
            conn.execute("UPDATE durable_scan_jobs SET status='INTERRUPTED', finished_at=COALESCE(finished_at,updated_at) WHERE status='RUNNING'")
            conn.execute("UPDATE durable_scan_candidates SET status='PENDING' WHERE status='RUNNING'")
            conn.commit()
        finally: conn.close()

    @staticmethod
    def _summary(job):
        return {"signals":[{"Ticker":s.get("Ticker"),"score":s.get("score")} for s in job.get("signals",[])],
                "rejections":job.get("rejections",{}),"timeouts":job.get("timeouts",0),
                "worker_exceptions":job.get("worker_exceptions",0),
                "checkpoint_conflicts":job.get("checkpoint_conflicts",0),
                "error":job.get("error")}

    @profile_timed("checkpoint_sqlite_job_summary")
    def _persist(self, owner, signature, job, status=None):
        if not self._db_path: return
        elapsed=max(time.time()-job["started_at"],1e-6); rate=job["processed"]/elapsed
        eta=(job["total"]-job["processed"])/rate if rate>0 and not job.get("complete") else 0
        conn=self._connect()
        try:
            conn.execute("""INSERT INTO durable_scan_jobs(
                job_id,owner,signature,started_at,finished_at,status,processed,total,
                eta_seconds,summary_json,updated_at,fencing_token,metadata_json,recovered)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(job_id) DO UPDATE SET finished_at=excluded.finished_at,status=excluded.status,
              processed=excluded.processed,total=excluded.total,eta_seconds=excluded.eta_seconds,
              summary_json=excluded.summary_json,updated_at=excluded.updated_at,
              metadata_json=excluded.metadata_json,recovered=excluded.recovered
              WHERE durable_scan_jobs.fencing_token=excluded.fencing_token""",
              (job["id"],owner,signature,job["started_at"],job.get("finished_at"),status or
               ("COMPLETE" if job.get("complete") else "RUNNING"),job["processed"],job["total"],eta,
               json.dumps(self._summary(job),default=str),time.time(),
               int(job.get("fencing_token", 1)),
               json.dumps(job.get("metadata") or {}, default=str),
               int(bool(job.get("recovered")))));
            conn.commit()
        finally: conn.close()

    @staticmethod
    def _instrument(item):
        return str(item.get("ticker") if isinstance(item, dict) else item)

    @staticmethod
    def _safe_json(value):
        if value is None:
            return None
        if isinstance(value, dict):
            return {str(k): ScanJobs._safe_json(v) for k, v in value.items() if k != "_returns"}
        if isinstance(value, (list, tuple)):
            return [ScanJobs._safe_json(v) for v in value]
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if isinstance(value, (str, int, bool)):
            return value
        if hasattr(value, "item"):
            return value.item()
        return str(value)

    def _create_checkpoints(self, job, items):
        if self._db_path:
            conn = self._connect()
            try:
                for item in items:
                    conn.execute("""INSERT OR IGNORE INTO durable_scan_candidates
                      (job_id,instrument,item_json,status,fencing_token,updated_at)
                      VALUES (?,?,?,'PENDING',?,?)""", (
                        job["id"], self._instrument(item),
                        json.dumps(self._safe_json(item), separators=(",", ":")),
                        int(job["fencing_token"]), time.time()))
                conn.commit()
            finally:
                conn.close()
        if self._checkpoint_store is not None and self._checkpoint_store.configured:
            self._checkpoint_store.create_run(job, items)

    def _checkpoint_candidate(self, job, item, result, rejection):
        instrument = self._instrument(item)
        quote_at = (result or {}).get("_quote_observed_at")
        governance_at = ((result or {}).get("_governance") or {}).get("decision_at")
        if self._checkpoint_store is not None and self._checkpoint_store.configured:
            if not profile_call("checkpoint_postgres_candidate", self._checkpoint_store.checkpoint_candidate,
                run_id=job["id"], instrument=instrument,
                fencing_token=job["fencing_token"], result=self._safe_json(result),
                rejection=self._safe_json(rejection), quote_observed_at=quote_at,
                governance_decision_at=governance_at,
            ):
                return False
        if self._db_path:
            with span("checkpoint_sqlite_candidate"):
                conn = self._connect()
                try:
                    changed = conn.execute("""UPDATE durable_scan_candidates
                  SET status='COMPLETE',result_json=?,rejection_json=?,quote_observed_at=?,
                      governance_decision_at=?,updated_at=?
                  WHERE job_id=? AND instrument=? AND fencing_token=?
                    AND status<>'COMPLETE'""", (
                    json.dumps(self._safe_json(result), separators=(",", ":")) if result is not None else None,
                    json.dumps(self._safe_json(rejection), separators=(",", ":")) if rejection is not None else None,
                    quote_at, governance_at, time.time(), job["id"], instrument,
                    int(job["fencing_token"]))).rowcount
                    conn.commit()
                finally:
                    conn.close()
            if changed != 1:
                return False
        return True

    @staticmethod
    def _recovered_result_is_fresh(job, result):
        if not job.get("recovered"):
            return True
        governance = dict((result or {}).get("_governance") or {})
        if governance.get("allow_trade") is not True:
            return False
        boundary = dt.datetime.fromtimestamp(job["recovery_started_at"], dt.timezone.utc)
        try:
            quote_at = dt.datetime.fromisoformat(str(result["_quote_observed_at"]).replace("Z", "+00:00"))
            governance_at = dt.datetime.fromisoformat(str(governance["decision_at"]).replace("Z", "+00:00"))
            if quote_at.tzinfo is None or governance_at.tzinfo is None:
                return False
            return quote_at.astimezone(dt.timezone.utc) >= boundary and governance_at.astimezone(dt.timezone.utc) >= boundary
        except (KeyError, TypeError, ValueError):
            return False

    def snapshot(self, owner, signature):
        with self._lock:
            job = self._jobs.get((owner, signature))
            if job:
                result=copy.deepcopy(job); elapsed=max(time.time()-result["started_at"],1e-6)
                rate=result["processed"]/elapsed
                result["eta_seconds"]=round((result["total"]-result["processed"])/rate) if rate>0 else None
                return result
            return None

    def cancel(self, owner, signature):
        with self._lock:
            job=self._jobs.get((owner,signature))
            if not job or job.get("complete"): return False
            job["cancel_requested"]=True
            return True

    def previous_completed(self, owner, before_job_id=None):
        if not self._db_path: return None
        conn=self._connect()
        try:
            query="SELECT job_id,started_at,finished_at,processed,total,summary_json FROM durable_scan_jobs WHERE owner=? AND status='COMPLETE'"
            params=[owner]
            if before_job_id: query+=" AND job_id<>?"; params.append(before_job_id)
            row=conn.execute(query+" ORDER BY started_at DESC LIMIT 1",params).fetchone()
        finally: conn.close()
        if not row: return None
        return {"id":row[0],"started_at":row[1],"finished_at":row[2],"processed":row[3],"total":row[4],"summary":json.loads(row[5])}

    def recoverable(self, owner, signature):
        if self._checkpoint_store is not None and self._checkpoint_store.configured:
            remote = self._checkpoint_store.latest_recoverable(owner, signature)
            if remote:
                return remote
        if not self._db_path:
            return None
        conn = self._connect()
        try:
            row = conn.execute("""SELECT j.job_id,j.status,j.fencing_token,j.metadata_json,
                     SUM(CASE WHEN c.status<>'COMPLETE' THEN 1 ELSE 0 END),
                     SUM(CASE WHEN c.status='COMPLETE' THEN 1 ELSE 0 END)
              FROM durable_scan_jobs j JOIN durable_scan_candidates c ON c.job_id=j.job_id
              WHERE j.owner=? AND j.signature=? AND j.status IN ('RUNNING','INTERRUPTED','CANCELLED','RECOVERING')
              GROUP BY j.job_id ORDER BY j.started_at DESC LIMIT 1""", (owner, signature)).fetchone()
            if not row or int(row[4] or 0) == 0:
                return None
            unfinished = [item[0] for item in conn.execute(
                "SELECT instrument FROM durable_scan_candidates WHERE job_id=? AND status<>'COMPLETE' ORDER BY instrument",
                (row[0],)).fetchall()]
            return {"id": row[0], "status": row[1], "fencing_token": int(row[2]),
                    "metadata": json.loads(row[3] or "{}"), "unfinished": unfinished,
                    "archived_completed": int(row[5] or 0)}
        finally:
            conn.close()

    def start(self, owner, signature, items, worker, workers=6, timeout=90, metadata=None):
        items = tuple(items)
        with self._lock:
            if self._busy:
                raise ScanBusy("A scan is active or its timed-out requests are still draining.")
            # Bound memory and private result retention, including abandoned sessions.
            now = time.time()
            self._jobs = {k: v for k, v in self._jobs.items() if now - v['started_at'] < 3600}
            while len(self._jobs) >= 16:
                del self._jobs[next(iter(self._jobs))]
            job = dict(id=uuid.uuid4().hex, started_at=now, finished_at=None,
                       complete=False, draining=False, processed=0, total=len(items),
                       signals=[], rejections={}, examples=[], issues=[], timeouts=0,
                       worker_exceptions=0, checkpoint_conflicts=0, cancel_requested=False, metadata=copy.deepcopy(metadata or {}),
                       owner=owner, signature=signature, fencing_token=1, recovered=False)
            job["application_id"] = f"{job['id']}:{job['fencing_token']}"
            self._jobs[(owner, signature)] = job
            self._busy = True
            self._persist(owner,signature,job,"RUNNING")
            try:
                self._create_checkpoints(job, items)
            except Exception as exc:
                job["finished_at"] = time.time()
                job["complete"] = True
                job["error"] = type(exc).__name__
                self._persist(owner, signature, job, "INTERRUPTED")
                self._jobs.pop((owner, signature), None)
                self._busy = False
                raise CheckpointUnavailable("Durable equity scan checkpoint initialization failed") from exc
        thread = threading.Thread(target=self._run, args=(job, items, worker, workers, timeout), daemon=True)
        try:
            thread.start()
        except BaseException:
            with self._lock:
                self._busy = False
                self._jobs.pop((owner, signature), None)
            raise
        return job['id']

    def recover(self, owner, signature, worker, workers=6, timeout=90, metadata=None):
        requested_metadata = copy.deepcopy(metadata or {})
        with self._lock:
            if self._busy:
                raise ScanBusy("A scan is active or its timed-out requests are still draining.")
            source = self.recoverable(owner, signature)
            if not source:
                raise CheckpointUnavailable("No interrupted equity scan is available")
            if self._checkpoint_store is not None and self._checkpoint_store.configured:
                claimed = self._checkpoint_store.claim_recovery(source["id"], owner)
                if not claimed:
                    raise CheckpointUnavailable("Interrupted scan was already claimed")
                token = claimed["fencing_token"]
                items = tuple(claimed["items"])
                recovered_metadata = claimed["metadata"]
            else:
                token = int(source["fencing_token"]) + 1
                recovered_metadata = dict(source.get("metadata") or {})
                conn = self._connect()
                try:
                    rows = conn.execute("SELECT item_json FROM durable_scan_candidates WHERE job_id=? AND status<>'COMPLETE' ORDER BY instrument", (source["id"],)).fetchall()
                    items = tuple(json.loads(row[0]) for row in rows)
                finally:
                    conn.close()
            if self._db_path:
                conn = self._connect()
                try:
                    conn.execute("UPDATE durable_scan_jobs SET fencing_token=?,status='RECOVERING',recovered=1 WHERE job_id=?", (token, source["id"]))
                    conn.execute("UPDATE durable_scan_candidates SET fencing_token=?,status='PENDING' WHERE job_id=? AND status<>'COMPLETE'", (token, source["id"]))
                    conn.commit()
                finally:
                    conn.close()
            now = time.time()
            recovered_metadata.update(requested_metadata)
            recovered_metadata.update({"recovery_started_at": now, "archived_completed": int(source.get("archived_completed", 0))})
            job = dict(id=source["id"], started_at=now, finished_at=None,
                       complete=False, draining=False, processed=0, total=len(items),
                       signals=[], rejections={}, examples=[], issues=[], timeouts=0,
                       worker_exceptions=0, checkpoint_conflicts=0, cancel_requested=False, metadata=recovered_metadata,
                       owner=owner, signature=signature, fencing_token=token,
                       recovered=True, recovery_started_at=now)
            job["application_id"] = f"{job['id']}:{job['fencing_token']}"
            self._jobs[(owner, signature)] = job
            self._busy = True
            self._persist(owner, signature, job, "RECOVERING")
        thread = threading.Thread(target=self._run, args=(job, items, worker, workers, timeout), daemon=True)
        try:
            thread.start()
        except BaseException:
            with self._lock:
                job["finished_at"] = time.time()
                job["complete"] = True
                job["error"] = "WorkerStartFailure"
                self._persist(owner, signature, job, "INTERRUPTED")
                self._jobs.pop((owner, signature), None)
                self._busy = False
            raise
        return job["id"]

    def _reject(self, job, ticker, category, reason):
        job['rejections'][category] = job['rejections'].get(category, 0) + 1
        row = dict(Ticker=ticker, Category=category, Reason=str(reason)[:300])
        job['issues'].append(row)
        if sum(x['Category'] == category for x in job['examples']) < 5:
            job['examples'].append(row)

    @profile_controller
    def _run(self, job, items, worker, workers, timeout):
        executor = None
        started = time.monotonic()
        pending = set()
        try:
            executor = futures.ThreadPoolExecutor(max_workers=max(1, min(int(workers), 12)))
            tasks = {executor.submit(run_candidate, job['id'], self._instrument(item),
                                     time.perf_counter(), worker, item): item for item in items}
            pending = set(tasks)
            deadline = started + max(float(timeout), .01)
            while pending and time.monotonic() < deadline:
                if job.get("cancel_requested"):
                    break
                done, _ = futures.wait(pending, timeout=min(.5, max(0, deadline-time.monotonic())),
                                       return_when=futures.FIRST_COMPLETED)
                for future in done:
                    pending.remove(future)
                    with self._lock:
                        job['processed'] += 1
                        try:
                            result, rejection = future.result()
                            if result is None:
                                rejection = rejection or {'category': 'Data', 'reason': 'No analysis result'}
                            elif not self._recovered_result_is_fresh(job, result):
                                result = None
                                rejection = {
                                    'category': 'Recovery',
                                    'reason': 'Recovered candidate lacked a fresh quote and governance re-evaluation',
                                }
                            with candidate_context(job['id'], self._instrument(tasks[future])):
                                checkpoint_ok = self._checkpoint_candidate(job, tasks[future], result, rejection)
                            if not checkpoint_ok:
                                job['checkpoint_conflicts'] += 1
                                continue
                            if result is not None:
                                job['signals'].append(result)
                            else:
                                self._reject(job, tasks[future], rejection.get('category', 'Data'), rejection.get('reason', ''))
                        except Exception as exc:
                            job['worker_exceptions'] += 1
                            rejection = {'category': 'Error', 'reason': type(exc).__name__}
                            self._checkpoint_candidate(job, tasks[future], None, rejection)
                            self._reject(job, tasks[future], 'Error', type(exc).__name__)
                    self._persist(job["owner"],job["signature"],job,"RUNNING")
            milestone(job['id'], "result_collection_ended")
            with self._lock:
                for future in pending:
                    future.cancel()
                    if job.get('cancel_requested'):
                        self._reject(job, tasks[future], 'Cancelled', 'Cancelled by user; late result discarded')
                    else:
                        self._reject(job, tasks[future], 'Timeout', 'Analysis deadline exceeded; late result discarded')
                job['timeouts'] = 0 if job.get('cancel_requested') else len(pending)
        except Exception as exc:
            with self._lock:
                job['error'] = type(exc).__name__
        finally:
            with self._lock:
                job['analysis_secs'] = round(time.monotonic() - started, 2)
                job['finished_at'] = time.time()
                job['complete'] = True
                job['draining'] = any(not f.done() for f in pending)
                job['cancelled'] = bool(job.get('cancel_requested'))
                final_status = (
                    "CANCELLED" if job['cancelled'] else
                    "INTERRUPTED" if pending or job.get('error') or job.get('checkpoint_conflicts') else
                    "COMPLETE"
                )
                self._persist(job["owner"],job["signature"],job,final_status)
                if self._checkpoint_store is not None and self._checkpoint_store.configured:
                    profile_call("checkpoint_postgres_heartbeat", self._checkpoint_store.heartbeat,
                        job["id"], job["fencing_token"],
                        status=final_status,
                        finished_at=job["finished_at"], error_kind=job.get("error"),
                    )
            try:
                if executor:
                    executor.shutdown(wait=True, cancel_futures=True)
            finally:
                with self._lock:
                    job['draining'] = False
                    self._busy = False
