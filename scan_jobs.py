"""Process-local scan jobs that survive Streamlit script reruns.

Only the controller writes results. Timed-out worker results are discarded, and
the concurrency slot is retained until those workers drain (threads cannot be
forcibly killed safely). No Streamlit or account APIs are called by this module.
"""
import copy
import concurrent.futures as futures
import threading
import time
import uuid


class ScanBusy(RuntimeError):
    pass


class ScanJobs:
    def __init__(self):
        self._lock = threading.RLock()
        self._jobs = {}
        self._busy = False

    def snapshot(self, owner, signature):
        with self._lock:
            job = self._jobs.get((owner, signature))
            return copy.deepcopy(job) if job else None

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
                       worker_exceptions=0, metadata=copy.deepcopy(metadata or {}))
            self._jobs[(owner, signature)] = job
            self._busy = True
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
            with self._lock:
                for future in pending:
                    future.cancel()
                    self._reject(job, tasks[future], 'Timeout', 'Analysis deadline exceeded; late result discarded')
                job['timeouts'] = len(pending)
        except Exception as exc:
            with self._lock:
                job['error'] = type(exc).__name__
        finally:
            with self._lock:
                job['analysis_secs'] = round(time.monotonic() - started, 2)
                job['finished_at'] = time.time()
                job['complete'] = True
                job['draining'] = any(not f.done() for f in pending)
            try:
                if executor:
                    executor.shutdown(wait=True, cancel_futures=True)
            finally:
                with self._lock:
                    job['draining'] = False
                    self._busy = False
