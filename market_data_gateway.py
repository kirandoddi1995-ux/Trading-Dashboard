"""Shared market-data gateway with request coalescing and source metadata."""

from __future__ import annotations

from dataclasses import dataclass
import copy
import threading
import time
from typing import Any, Callable

from observability import get_registry


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


class _Flight:
    def __init__(self):
        self.event = threading.Event()
        self.value = None
        self.error: BaseException | None = None


class MarketDataGateway:
    """One process-wide coordination point for quote and history reads.

    Identical concurrent loads share one provider request. Short TTLs coalesce
    Streamlit reruns without turning live prices into long-lived cache entries.
    """

    def __init__(self, max_entries: int = 2_000):
        self._cache: dict[tuple, _CacheEntry] = {}
        self._inflight: dict[tuple, _Flight] = {}
        self._lock = threading.RLock()
        self._max_entries = max(int(max_entries), 100)
        self._metrics = get_registry()

    @staticmethod
    def _copy(value):
        if hasattr(value, "copy"):
            try:
                return value.copy(deep=True)
            except TypeError:
                return value.copy()
        return copy.deepcopy(value)

    def _trim(self, now: float) -> None:
        expired = [key for key, entry in self._cache.items() if entry.expires_at <= now]
        for key in expired:
            self._cache.pop(key, None)
        if len(self._cache) > self._max_entries:
            for key in list(self._cache)[:len(self._cache) - self._max_entries]:
                self._cache.pop(key, None)

    def get_or_load(self, namespace: str, key: tuple, loader: Callable[[], Any], *, ttl: float):
        cache_key = (str(namespace),) + tuple(key)
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry and entry.expires_at > now:
                self._metrics.record("cache", namespace, 0.0, cache_hit=True)
                return self._copy(entry.value)
            flight = self._inflight.get(cache_key)
            leader = flight is None
            if leader:
                flight = _Flight()
                self._inflight[cache_key] = flight

        if not leader:
            wait_started = time.perf_counter()
            completed = flight.event.wait(timeout=30.0)
            self._metrics.record(
                "cache", f"{namespace}:coalesced", time.perf_counter() - wait_started,
                ok=completed, cache_hit=True, status=None if completed else "TimeoutError",
            )
            if not completed:
                raise TimeoutError(f"Timed out waiting for coalesced {namespace} request")
            if flight.error is not None:
                raise flight.error
            return self._copy(flight.value)

        started = time.perf_counter()
        try:
            value = loader()
            with self._lock:
                self._cache[cache_key] = _CacheEntry(self._copy(value), time.monotonic() + max(float(ttl), 0.0))
                self._trim(time.monotonic())
                flight.value = self._copy(value)
            self._metrics.record("cache", namespace, time.perf_counter() - started, cache_hit=False)
            return value
        except BaseException as exc:
            flight.error = exc
            self._metrics.record("cache", namespace, time.perf_counter() - started, ok=False, cache_hit=False, status=type(exc).__name__)
            raise
        finally:
            with self._lock:
                self._inflight.pop(cache_key, None)
                flight.event.set()

    @staticmethod
    def annotate_quote(quote: dict, *, now: float | None = None) -> dict:
        now = time.time() if now is None else float(now)
        result = dict(quote or {})
        received_at = result.get("_ts")
        try:
            age = max(now - float(received_at), 0.0)
        except (TypeError, ValueError):
            age = None
        result["_received_at"] = received_at
        result["_age_seconds"] = round(age, 3) if age is not None else None
        result["_freshness"] = "fresh" if age is not None and age <= 5.0 else ("aging" if age is not None and age <= 30.0 else "stale")
        result["_source"] = result.get("_source") or "unknown"
        return result

    def quotes(
        self,
        keys: list[str],
        *,
        rest_loader: Callable[[list[str]], dict],
        buffer=None,
        market_open: bool = False,
        scope: str = "page",
        websocket_limit: int = 200,
        rest_ttl: float = 0.75,
        quote_validator: Callable[[dict], bool] | None = None,
    ) -> dict:
        ordered = [key for key in dict.fromkeys(keys or []) if key]
        if not ordered:
            return {}

        snapshot = {}
        use_socket = bool(buffer is not None and market_open and len(ordered) <= int(websocket_limit))
        if buffer is not None:
            if use_socket:
                reconcile = getattr(buffer, "reconcile", None)
                if callable(reconcile):
                    reconcile(scope, ordered)
                else:
                    buffer.ensure(ordered)
                snapshot = buffer.snapshot(ordered)
                if quote_validator is not None:
                    snapshot = {
                        key: quote for key, quote in snapshot.items()
                        if quote_validator(quote)
                    }
            else:
                release = getattr(buffer, "release_scope", None)
                if callable(release):
                    release(scope)

        missing = [key for key in ordered if key not in snapshot]
        if missing:
            signature = tuple(sorted(missing))
            rest = self.get_or_load("quotes", signature, lambda: rest_loader(missing), ttl=rest_ttl)
            snapshot.update(rest or {})

        now = time.time()
        result = {}
        for key in ordered:
            quote = snapshot.get(key)
            if quote:
                result[key] = self.annotate_quote(quote, now=now)
        return result

    def history(self, instrument_key: str, days: int, loader: Callable[[], Any], *, ttl: float = 30.0):
        return self.get_or_load("history", (str(instrument_key), int(days)), loader, ttl=ttl)

    def stats(self) -> dict:
        with self._lock:
            now = time.monotonic()
            active = sum(entry.expires_at > now for entry in self._cache.values())
            return {"active_cache_entries": active, "inflight_requests": len(self._inflight)}


_GATEWAY = MarketDataGateway()


def get_market_data_gateway() -> MarketDataGateway:
    return _GATEWAY
