"""Bounded, process-local scan timings; never persist inputs, results or errors.

Spans are inclusive and overlap across threads: their totals are NOT wall time.
No timing collected outside a scan context. Diagnostics never change exceptions.
"""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import json
import logging
import threading
import time

_context = ContextVar("equity_scan_profile", default=None)
_lock = threading.RLock()
_profiles = OrderedDict()
MAX_SCANS = 8
MAX_EVENTS = 10000


def _record(stage, start, end=None, *, state="complete"):
    try:
        context = _context.get()
        if context is None:
            return None
        scan_id, candidate = context
        with _lock:
            profile = _profiles.get(scan_id)
            if profile is None:
                return None
            event = {"candidate": candidate, "stage": stage,
                     "start_seconds": start - profile["origin"], "state": state}
            if end is not None:
                event["seconds"] = end - start
            if len(profile["events"]) < MAX_EVENTS:
                profile["events"].append(event)
                return event
            profile["dropped_events"] += 1
    except Exception:
        pass  # Diagnostics cannot interrupt a scan or obscure its real error.
    return None


@contextmanager
def span(stage):
    if _context.get() is None:
        yield
        return
    start = time.perf_counter()
    event = _record(stage, start, state="running")
    state = "complete"
    try:
        yield
    except BaseException:
        state = "raised"
        raise
    finally:
        if event is not None:
            try:
                with _lock:
                    event.update(seconds=time.perf_counter() - start, state=state)
            except Exception:
                pass


def timed(stage):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with span(stage):
                return function(*args, **kwargs)
        return wrapped
    return decorate


def call(stage, function, *args, **kwargs):
    with span(stage):
        return function(*args, **kwargs)


@contextmanager
def candidate_context(scan_id, candidate):
    token = _context.set((scan_id, candidate))
    try:
        yield
    finally:
        _context.reset(token)


def run_candidate(scan_id, candidate, submitted_at, worker, item):
    with candidate_context(scan_id, candidate):
        _record("executor_queue_wait", submitted_at, time.perf_counter())
        with span("candidate_total"):
            return worker(item)


def snapshot(scan_id):
    with _lock:
        profile = _profiles.get(scan_id)
        if profile is None:
            return None
        events = [dict(event) for event in profile["events"]]
        totals = {}
        for event in events:
            if "seconds" not in event:
                continue
            row = totals.setdefault(event["stage"], {"count": 0, "total_seconds": 0, "max_seconds": 0})
            row["count"] += 1
            row["total_seconds"] += event["seconds"]
            row["max_seconds"] = max(row["max_seconds"], event["seconds"])
        return {"scan_id": scan_id, "inclusive_overlapping_spans": True,
                "process_local_only": True, "dropped_events": profile["dropped_events"],
                "milestones": dict(profile["milestones"]), "totals": totals, "events": events}


def milestone(scan_id, name):
    try:
        with _lock:
            profile = _profiles.get(scan_id)
            if profile is not None:
                profile["milestones"][name] = time.perf_counter() - profile["origin"]
    except Exception:
        pass


def profile_controller(function):
    @wraps(function)
    def wrapped(self, job, *args, **kwargs):
        scan_id = job["id"]
        with _lock:
            _profiles[scan_id] = {"origin": time.perf_counter(), "events": [],
                                  "milestones": {}, "dropped_events": 0}
            while len(_profiles) > MAX_SCANS:
                _profiles.popitem(last=False)
        try:
            with candidate_context(scan_id, None):
                return function(self, job, *args, **kwargs)
        finally:
            milestone(scan_id, "workers_drained")
            try:
                logging.getLogger(__name__).warning("EQUITY_SCAN_PROFILE %s", json.dumps(snapshot(scan_id)))
            except Exception:
                pass
    return wrapped


class _ObservedCache:
    """Delegate to the SAME cache and locks; only time actual lock acquisition."""
    def __init__(self, cache):
        self.cache = cache

    def __getattr__(self, name):
        return getattr(self.cache, name)

    @contextmanager
    def compute_value_lock(self, key):
        lock = self.cache.compute_value_lock(key)
        start = time.perf_counter()
        with lock:
            _record("health_cache_lock_wait", start, time.perf_counter())
            yield


def observe_health_cache(cached_function):
    """Streamlit 1.62 adapter; unsupported internals leave caching untouched.

The original double-checked cache miss and its lock are retained. Cache hits
have no lock-wait event (not an invented zero). The returned function retains
Streamlit's clear() method. No global Streamlit cache is patched.
"""
    supported = False
    handler = getattr(cached_function, "_handle_cache_miss", None)
    if callable(handler):
        @wraps(handler)
        def observed(cache, *args, **kwargs):
            return handler(_ObservedCache(cache), *args, **kwargs)
        try:
            cached_function._handle_cache_miss = observed
            supported = True
        except (AttributeError, TypeError):
            pass

    @wraps(cached_function)
    def wrapped(*args, **kwargs):
        if not supported:
            now = time.perf_counter()
            _record("health_cache_lock_instrumentation_unavailable", now, now)
        with span("health_cache_call"):
            return cached_function(*args, **kwargs)
    if hasattr(cached_function, "clear"):
        wrapped.clear = cached_function.clear
    return wrapped
