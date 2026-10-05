"""Bounded, process-local diagnostics; never certify data or change cache policy."""
from __future__ import annotations

from collections import Counter
from datetime import date
import logging
from threading import Lock
from typing import Any


class HistoryFreshness:
    """Aggregate instrument warnings without hiding current missing sessions.

    At most one warning per expected session is emitted for each failure kind.
    Publication timing is unknown: missing today's completed candle is NOT
    certified fresh and is NOT asserted to be a provider outage or normal delay.
    State lives only in memory and is capped; snapshots contain no credentials.
    """

    def __init__(self, maximum: int = 2000) -> None:
        if maximum < 1:
            raise ValueError('Positive diagnostic capacity required')
        self._maximum = maximum
        self._rows: dict[str, dict[str, Any]] = {}
        self._warned: set[tuple[str | None, str]] = set()
        self._lock = Lock()

    def record(self, instrument: str, *, expected: date | None, latest: date | None,
               today: date, logger: logging.Logger) -> None:
        """Record actual coverage; never write a freshness marker or fetch data."""
        status = ('CALENDAR_UNVERIFIED' if expected is None else
                  'CURRENT' if latest is not None and latest >= expected else
                  'EXPECTED_SESSION_NOT_RECEIVED' if expected == today else 'STALE_HISTORY')
        row = dict(status=status, expected=expected.isoformat() if expected else None,
                   latest=latest.isoformat() if latest else None, checked_on=today.isoformat())
        key = (row['expected'], status)
        with self._lock:
            self._rows.pop(instrument, None)
            self._rows[instrument] = row
            if len(self._rows) > self._maximum:
                del self._rows[next(iter(self._rows))]
            # Bound warning suppression separately; restarting may log again.
            if len(self._warned) > 32:
                self._warned.clear()
            warn = status != 'CURRENT' and key not in self._warned
            if warn:
                self._warned.add(key)
        if warn:
            logger.warning('History freshness: %s; expected session %s. Freshness markers remain '
                           'unadvanced for missing data. Per-instrument details are aggregated in '
                           'Settings / Equity runtime health; publication delay is unverified.',
                           status, row['expected'])

    def snapshot(self, today: date) -> dict[str, Any]:
        """Only today's observations; not a complete-universe readiness claim."""
        with self._lock:
            rows = {key: dict(row) for key, row in self._rows.items()
                    if row['checked_on'] == today.isoformat()}
        missing = {key: row for key, row in rows.items() if row['status'] != 'CURRENT'}
        return dict(observed_instruments=len(rows), missing_instruments=len(missing),
                    by_status=dict(Counter(row['status'] for row in rows.values())),
                    samples=[dict(instrument=key, **row) for key, row in sorted(missing.items())[:5]],
                    publication_timing='UNVERIFIED', diagnostic_only=True)


HISTORY_FRESHNESS = HistoryFreshness()
