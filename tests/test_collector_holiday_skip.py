"""A scheduled scan on an NSE holiday is SKIPPED, not FAILED.

pg_cron dispatches the 10:07 and 14:37 IST scans Monday-Friday, holidays included.
On 10 Nov 2026 (Diwali-Balipratipada) the live NSE status was a day old, so the
fail-closed status check raised and the run went red. The scan now skips when the
reviewed calendar (nifty_session_calendar) says CLOSED and the live status does not
show today's NORMAL_OPEN. Every other case keeps the fail-closed check.
No network: the Upstox status endpoint is faked with the shape it really returns.
"""
from __future__ import annotations

import datetime as dt

import pytest

import scheduled_collector as collector
from test_prospective_collection import MemoryRepository

UTC = dt.timezone.utc
HOLIDAY = dt.datetime(2026, 11, 10, 10, 7, tzinfo=collector.IST)      # Diwali-Balipratipada
TRADING_DAY = dt.datetime(2026, 11, 11, 10, 7, tzinfo=collector.IST)
UNREVIEWED_DAY = dt.datetime(2027, 1, 5, 10, 7, tzinfo=collector.IST)  # calendar ends 2026
REAL_STATUS = collector.fetch_nse_exchange_status


class Response:
    """Minimal requests.Response stand-in."""

    def __init__(self, payload, status_code=200):
        """Store the JSON payload."""
        self._payload = payload
        self.status_code = status_code

    def json(self):
        """Return the payload."""
        return self._payload

    def raise_for_status(self):
        """Raise on an HTTP error like requests does."""
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class StatusClient:
    """Fake Upstox client for /v2/market/status/NSE; records every URL."""

    def __init__(self, status="NORMAL_CLOSE", updated=None, *, http=200, error=None):
        """`updated`: when the status last changed; `error`: exception to raise."""
        self.status, self.updated, self.http, self.error = status, updated, http, error
        self.calls = []

    def get(self, url, **kwargs):
        """Answer the market-status request."""
        self.calls.append(url)
        if self.error is not None:
            raise self.error
        return Response({"status": "success", "data": {
            "exchange": "NSE", "status": self.status,
            "last_updated": int(self.updated.timestamp() * 1000)}}, self.http)


class StopAfterStatus(Exception):
    """Raised by the fake universe fetch: proves the scan went past the status gate."""


@pytest.fixture
def repo(monkeypatch):
    """A memory repository; status checks use the scan's own clock."""
    clock = {}

    def status(client, token, now=None):
        """The real status check, evaluated at the scan instant."""
        return REAL_STATUS(client, token, now=now or clock["now"])

    def universe(client):
        """Stop the scan right after the status gate."""
        raise StopAfterStatus

    monkeypatch.setattr(collector, "fetch_nse_exchange_status", status)
    monkeypatch.setattr(collector, "fetch_nse_universe", universe)
    store = MemoryRepository()
    store.clock = clock
    return store


def _scan(repo, client, now):
    """Run the scheduled Stage-1 scan at `now`."""
    repo.clock["now"] = now
    return collector._scheduled_stage1(repo, client, "token-secret-123", "run-h", now=now)


def test_calendar_knows_the_2026_holidays_and_trading_days():
    """The reviewed calendar is the first source: today closed, tomorrow regular."""
    assert collector.nse_calendar_day(HOLIDAY.date())["kind"] == "CLOSED"
    assert collector.nse_calendar_day(dt.date(2026, 11, 24))["kind"] == "CLOSED"
    assert collector.nse_calendar_day(dt.date(2026, 12, 25))["kind"] == "CLOSED"
    assert collector.nse_calendar_day(TRADING_DAY.date())["kind"] == "REGULAR"
    unknown = collector.nse_calendar_day(UNREVIEWED_DAY.date())
    assert unknown["kind"] == "UNREVIEWED" and "UNREVIEWED" in unknown["error"]


def test_holiday_with_stale_status_is_skipped_without_scanning(repo):
    """10 Nov 2026 exactly: status last changed at 16:00 IST the day before."""
    client = StatusClient("NORMAL_CLOSE", HOLIDAY - dt.timedelta(hours=18, minutes=7))
    result = _scan(repo, client, HOLIDAY)
    assert result["status"] == "SKIPPED"
    assert result["reason"] == "NSE holiday (reviewed calendar)"
    assert result["calendar"]["kind"] == "CLOSED" and "CMTR71775" in result["calendar"]["source"]
    assert "current IST trading date" in result["exchange_check"]
    assert len(client.calls) == 1  # one status read, no universe/quote requests
    assert repo.scanner == [] and repo.ledger == [] and repo.features == []
    assert repo.quality_events == []


@pytest.mark.parametrize("client", [
    StatusClient("CLOSED", HOLIDAY),                               # fresh but closed
    StatusClient(error=ConnectionError("upstream timeout")),       # network failure
    StatusClient(http=503, updated=HOLIDAY),                       # provider error
    StatusClient(http=401, updated=HOLIDAY),                       # token rejected
])
def test_holiday_skips_whatever_the_live_status_says_unless_open(repo, client):
    """Closed, unreachable or unauthorised on a calendar holiday -> skip, never fail."""
    result = _scan(repo, client, HOLIDAY)
    assert result["status"] == "SKIPPED" and result["calendar"]["kind"] == "CLOSED"
    assert "token-secret-123" not in str(result)


def test_holiday_but_exchange_open_scans_and_flags_the_calendar(repo):
    """The live exchange wins: an open session is never skipped on the calendar's word."""
    client = StatusClient("NORMAL_OPEN", HOLIDAY - dt.timedelta(minutes=52))
    with pytest.raises(StopAfterStatus):
        _scan(repo, client, HOLIDAY)
    (args, _), = repo.quality_events
    assert args[:3] == ("scheduled_scan", "WARNING", "CALENDAR_CLOSED_BUT_EXCHANGE_OPEN")


def test_trading_day_keeps_the_fail_closed_status_check(repo):
    """A regular day with a stale or closed status is still a visible failure."""
    stale = StatusClient("NORMAL_CLOSE", TRADING_DAY - dt.timedelta(hours=18))
    with pytest.raises(RuntimeError, match="current IST trading date"):
        _scan(repo, stale, TRADING_DAY)
    with pytest.raises(RuntimeError, match="not in NORMAL_OPEN"):
        _scan(repo, StatusClient("CLOSED", TRADING_DAY), TRADING_DAY)
    with pytest.raises(StopAfterStatus):
        _scan(repo, StatusClient("NORMAL_OPEN", TRADING_DAY - dt.timedelta(minutes=52)), TRADING_DAY)
    assert repo.quality_events == []


def test_unreviewed_year_fails_with_a_calendar_hint_and_never_skips(repo):
    """No calendar for the year: not assumed open or closed; the failure says what to add."""
    stale = StatusClient("NORMAL_CLOSE", UNREVIEWED_DAY - dt.timedelta(hours=18))
    with pytest.raises(RuntimeError, match="calendar for 2027 is not reviewed"):
        _scan(repo, stale, UNREVIEWED_DAY)
    with pytest.raises(StopAfterStatus):
        _scan(repo, StatusClient("NORMAL_OPEN", UNREVIEWED_DAY - dt.timedelta(minutes=52)),
              UNREVIEWED_DAY)


def test_special_session_day_keeps_the_fail_closed_check(repo, monkeypatch):
    """An announced special session is not a holiday: live status decides, fail closed."""
    monkeypatch.setattr(collector, "cash_session",
                        lambda day: {"kind": "SPECIAL", "windows": None, "source": "notice"})
    with pytest.raises(RuntimeError, match="current IST trading date"):
        _scan(repo, StatusClient("NORMAL_CLOSE", TRADING_DAY - dt.timedelta(hours=18)), TRADING_DAY)


def test_holiday_run_finishes_green(monkeypatch):
    """run('scan') on a holiday: workflow succeeds, run row SUCCESS, reason kept."""
    class RunRepo(MemoryRepository):
        """Repository with the run/lease API run() needs."""

        def __init__(self):
            """Start empty."""
            super().__init__()
            self.finished = []

        def acquire_collector_lease(self, *a, **k):
            """Grant the lease."""
            return {"fencing_token": 3}

        def renew_collector_lease(self, *a, **k):
            """Keep the lease."""
            return True

        def release_collector_lease(self, *a, **k):
            """Release the lease."""
            return True

        def start_run(self, *a, **k):
            """Run id."""
            return "run-h"

        def finish_run(self, run_id, **kwargs):
            """Record the final status."""
            self.finished.append(kwargs)

    store = RunRepo()
    client = StatusClient("NORMAL_CLOSE", HOLIDAY - dt.timedelta(hours=18))
    real = collector._scheduled_stage1
    monkeypatch.setenv("UPSTOX_ANALYTICS_TOKEN", "token")
    monkeypatch.setattr(collector, "ProductionRepository", lambda *a, **k: store)
    monkeypatch.setattr(collector, "session", lambda: client)
    monkeypatch.setattr(collector, "fetch_nse_exchange_status",
                        lambda c, t, now=None: REAL_STATUS(c, t, now=HOLIDAY))
    monkeypatch.setattr(collector, "_scheduled_stage1",
                        lambda r, c, t, run_id, **kw: real(r, c, t, run_id, now=HOLIDAY, **kw))
    result = collector.run("scan")
    assert result["status"] == "SUCCESS"
    assert result["scheduled_stage1"]["reason"] == "NSE holiday (reviewed calendar)"
    assert store.finished[-1]["status"] == "SUCCESS" and store.finished[-1]["record_count"] == 0
