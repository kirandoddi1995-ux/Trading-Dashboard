"""Low-overhead, credential-safe runtime measurements for Quant Terminal.

The registry is process-local by design: it is useful for finding slow reruns,
duplicate provider calls and cache misses without adding another production
service.  Only normalized operation names and numeric metadata are retained;
request headers, bodies, query strings and credentials are never recorded.
"""

from __future__ import annotations

from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import math
import threading
import time
from urllib.parse import urlsplit
import uuid


@dataclass(frozen=True)
class MetricEvent:
    timestamp: float
    category: str
    name: str
    duration_ms: float
    ok: bool = True
    cache_hit: bool | None = None
    status: int | str | None = None
    count: int = 1
    correlation_id: str | None = None


def safe_endpoint(url: str) -> str:
    """Return host + path only, deliberately dropping query and credentials."""
    try:
        parsed = urlsplit(str(url))
        host = parsed.hostname or "unknown-host"
        path = parsed.path or "/"
        return f"{host}{path}"
    except Exception:
        return "unknown-endpoint"


class MetricsRegistry:
    def __init__(self, max_events: int = 10_000):
        self._events = deque(maxlen=max(int(max_events), 100))
        self._lock = threading.RLock()
        self._finished_runs = deque(maxlen=2_000)
        self._finished_run_ids: set[str] = set()

    def record(
        self,
        category: str,
        name: str,
        duration_seconds: float,
        *,
        ok: bool = True,
        cache_hit: bool | None = None,
        status: int | str | None = None,
        count: int = 1,
        correlation_id: str | None = None,
    ) -> None:
        duration_ms = max(float(duration_seconds or 0.0) * 1000.0, 0.0)
        event = MetricEvent(
            timestamp=time.time(),
            category=str(category)[:64],
            name=str(name)[:240],
            duration_ms=duration_ms,
            ok=bool(ok),
            cache_hit=cache_hit if cache_hit is None else bool(cache_hit),
            status=status,
            count=max(int(count or 1), 1),
            correlation_id=(str(correlation_id)[:64] if correlation_id else None),
        )
        with self._lock:
            self._events.append(event)

    @contextmanager
    def span(self, category: str, name: str, *, cache_hit: bool | None = None):
        started = time.perf_counter()
        ok = False
        status = None
        try:
            yield
            ok = True
        except Exception as exc:
            status = type(exc).__name__
            raise
        finally:
            self.record(
                category, name, time.perf_counter() - started,
                ok=ok, cache_hit=cache_hit, status=status,
            )

    def begin_rerun(self) -> tuple[str, float]:
        return uuid.uuid4().hex, time.perf_counter()

    def finish_rerun(self, run_id: str, started: float, page: str, outcome: str = "complete") -> None:
        if not run_id:
            return
        with self._lock:
            if run_id in self._finished_run_ids:
                return
            if len(self._finished_runs) == self._finished_runs.maxlen:
                expired = self._finished_runs.popleft()
                self._finished_run_ids.discard(expired)
            self._finished_runs.append(run_id)
            self._finished_run_ids.add(run_id)
        self.record("rerun", page or "unknown-page", time.perf_counter() - started, status=outcome)

    def events(self, *, window_seconds: float = 900.0) -> list[dict]:
        cutoff = time.time() - max(float(window_seconds), 1.0)
        with self._lock:
            return [asdict(event) for event in self._events if event.timestamp >= cutoff]

    def summary(self, *, window_seconds: float = 900.0) -> list[dict]:
        grouped: dict[tuple[str, str], list[MetricEvent]] = defaultdict(list)
        cutoff = time.time() - max(float(window_seconds), 1.0)
        with self._lock:
            for event in self._events:
                if event.timestamp >= cutoff:
                    grouped[(event.category, event.name)].append(event)

        rows = []
        for (category, name), events in grouped.items():
            durations = sorted(event.duration_ms for event in events)
            weighted_count = sum(event.count for event in events)
            p95_index = max(math.ceil(len(durations) * 0.95) - 1, 0)
            cache_events = [event for event in events if event.cache_hit is not None]
            rows.append({
                "Category": category,
                "Operation": name,
                "Calls": weighted_count,
                "Errors": sum(not event.ok for event in events),
                "Avg ms": round(sum(durations) / len(durations), 2),
                "P95 ms": round(durations[p95_index], 2),
                "Max ms": round(durations[-1], 2),
                "Cache hit %": (
                    round(sum(bool(event.cache_hit) for event in cache_events) / len(cache_events) * 100.0, 1)
                    if cache_events else None
                ),
            })
        return sorted(rows, key=lambda row: (row["Category"], -row["Avg ms"], row["Operation"]))


_REGISTRY = MetricsRegistry()


def get_registry() -> MetricsRegistry:
    return _REGISTRY


def observed_request(client, method: str, url: str, **kwargs):
    """Measure a requests-compatible call without retaining sensitive inputs."""
    registry = get_registry()
    started = time.perf_counter()
    response = None
    ok = False
    status = None
    try:
        response = client.request(method, url, **kwargs)
        status = getattr(response, "status_code", None)
        ok = status is None or int(status) < 400
        return response
    except Exception as exc:
        status = type(exc).__name__
        raise
    finally:
        registry.record(
            "api", f"{str(method).upper()} {safe_endpoint(url)}",
            time.perf_counter() - started, ok=ok, status=status,
        )
