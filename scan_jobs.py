"""Process-local scan jobs that survive Streamlit script reruns.

Only the controller writes results. Timed-out worker results are discarded, and
the concurrency slot is retained until those workers drain (threads cannot be
forcibly killed safely). No Streamlit or account APIs are called by this module.
"""
import copy
import concurrent.futures as futures
import json
import sqlite3
import threading
import time
import uuid


class ScanBusy(RuntimeError):
    pass


class ScanJobs:
    def __init__(self, db_path=None):
        self._lock = threading.RLock()
        self._jobs = {}
        self._busy = False
        self._db_path = db_path
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
            conn.execute("UPDATE durable_scan_jobs SET status='INTERRUPTED', finished_at=COALESCE(finished_at,updated_at) WHERE status='RUNNING'")
            conn.commit()
        finally: conn.close()

    @staticmethod
    def _summary(job):
        return {"signals":[{"Ticker":s.get("Ticker"),"score":s.get("score")} for s in job.get("signals",[])],
                "rejections":job.get("rejections",{}),"timeouts":job.get("timeouts",0),
                "worker_exceptions":job.get("worker_exceptions",0),"error":job.get("error")}

    def _persist(self, owner, signature, job, status=None):
        if not self._db_path: return
        elapsed=max(time.time()-job["started_at"],1e-6); rate=job["processed"]/elapsed
        eta=(job["total"]-job["processed"])/rate if rate>0 and not job.get("complete") else 0
        conn=self._connect()
        try:
            conn.execute("""INSERT INTO durable_scan_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(job_id) DO UPDATE SET finished_at=excluded.finished_at,status=excluded.status,
              processed=excluded.processed,total=excluded.total,eta_seconds=excluded.eta_seconds,
              summary_json=excluded.summary_json,updated_at=excluded.updated_at""",
              (job["id"],owner,signature,job["started_at"],job.get("finished_at"),status or
               ("COMPLETE" if job.get("complete") else "RUNNING"),job["processed"],job["total"],eta,
               json.dumps(self._summary(job),default=str),time.time())); conn.commit()
        finally: conn.close()

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
                       worker_exceptions=0, cancel_requested=False, metadata=copy.deepcopy(metadata or {}),
                       owner=owner, signature=signature)
            self._jobs[(owner, signature)] = job
            self._busy = True
            self._persist(owner,signature,job,"RUNNING")
        thread = threading.Thread(target=self._run, args=(job, items, worker, workers, timeout), daemon=True)
        try:
            thread.start()
        except BaseException:
            with self._lock:
                self._busy = False
                self._jobs.pop((owner, signature), None)
            raise
        return job['id']

    def _reject(self, job, ticker, category, reason):
        job['rejections'][category] = job['rejections'].get(category, 0) + 1
        row = dict(Ticker=ticker, Category=category, Reason=str(reason)[:300])
        job['issues'].append(row)
        if sum(x['Category'] == category for x in job['examples']) < 5:
            job['examples'].append(row)

    def _run(self, job, items, worker, workers, timeout):
        executor = None
        started = time.monotonic()
        pending = set()
        try:
            executor = futures.ThreadPoolExecutor(max_workers=max(1, min(int(workers), 12)))
            tasks = {executor.submit(worker, item): item for item in items}
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
                            if result is not None:
                                job['signals'].append(result)
                            else:
                                rejection = rejection or {'category': 'Data', 'reason': 'No analysis result'}
                                self._reject(job, tasks[future], rejection.get('category', 'Data'), rejection.get('reason', ''))
                        except Exception as exc:
                            job['worker_exceptions'] += 1
                            self._reject(job, tasks[future], 'Error', type(exc).__name__)
                    self._persist(job["owner"],job["signature"],job,"RUNNING")
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
                self._persist(job["owner"],job["signature"],job,"CANCELLED" if job['cancelled'] else "COMPLETE")
            try:
                if executor:
                    executor.shutdown(wait=True, cancel_futures=True)
            finally:
                with self._lock:
                    job['draining'] = False
                    self._busy = False
