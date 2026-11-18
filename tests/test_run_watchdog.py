"""Watchdog for expected unattended runs: right slot instance, right window, one alert, never raises."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

import pytest

import run_watchdog as wd

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
ENV = {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_TOKEN": "ghs_x",
       "TELEGRAM_BOT_TOKEN": "123456789:" + "A" * 35, "TELEGRAM_CHAT_ID": "-1001234567890"}
MON = datetime(2026, 11, 16, tzinfo=UTC)   # a Monday


def _run(created, conclusion="success", title="Collector scan", event="workflow_dispatch", branch="main",
         status=None):
    """A GitHub workflow run as the REST API lists it."""
    return {"created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"), "conclusion": conclusion,
            "display_title": title, "event": event, "head_branch": branch,
            "status": status or ("completed" if conclusion else "in_progress")}


def _sent(calls):
    """A Telegram transport that records the text and accepts it."""
    def post(path, body):
        """Echo the text back the way Telegram does."""
        text = json.loads(body)["text"]
        calls.append(text)
        return 200, json.dumps({"ok": True, "result": {"text": text, "chat": {"id": -1001234567890}}}).encode()
    return post


@pytest.mark.parametrize("slot,now,expected", [
    (wd.SCAN_1007, MON.replace(hour=6), MON.replace(hour=4, minute=37)),
    (wd.SCAN_1007, MON.replace(hour=5, minute=36), MON - timedelta(days=3) + timedelta(hours=4, minutes=37)),  # Fri
    (wd.SCAN_1007, MON + timedelta(days=5, hours=12), MON + timedelta(days=4, hours=4, minutes=37)),  # Sat -> Fri
    (wd.SCAN_1437, MON.replace(hour=10, minute=30), MON.replace(hour=9, minute=7)),
    (wd.SCAN_1007, MON.replace(hour=14), MON.replace(hour=4, minute=37)),   # 06:00 watchdog fired 8 h late
    (wd.ARCHIVE, MON + timedelta(days=5, hours=22, minutes=30), MON + timedelta(days=5, hours=20, minutes=15)),  # Sat ok
    (wd.ARCHIVE, MON + timedelta(days=1, hours=1), MON.replace(hour=20, minute=15)),   # past UTC midnight
])
def test_latest_instance(slot, now, expected):
    """The most recent allowed-weekday slot that settled at least an hour ago."""
    assert wd.latest_instance(slot, now) == expected


def test_verdict_window():
    """Only the slot's own dispatch created 15 min before to 2 h after the slot counts."""
    start = MON.replace(hour=4, minute=37)
    v = lambda runs: wd.verdict(runs, wd.SCAN_1007, start, start + timedelta(hours=1, minutes=23))
    assert v([]) == "MISSING"
    assert v([_run(start - timedelta(minutes=16))]) == "MISSING"
    assert v([_run(start + timedelta(hours=2, minutes=1))]) == "MISSING"
    assert v([_run(start - timedelta(minutes=15))]) == "OK"
    assert v([_run(start + timedelta(hours=2))]) == "OK"
    assert v([_run(start, "failure")]) == "NOT_OK"
    assert v([_run(start, "cancelled")]) == "NOT_OK"
    assert v([_run(start, "failure"), _run(start + timedelta(minutes=5))]) == "OK"


@pytest.mark.parametrize("status", ["queued", "in_progress", "waiting", "requested", "pending"])
def test_unfinished_run_is_running_not_an_alert(status):
    """A slow but healthy run at the check is RUNNING (a hang ends in the job timeout + in-job alert)."""
    start = MON.replace(hour=20, minute=15)
    run = _run(start, None, title=wd.ARCHIVE.title, status=status)
    soon = start + timedelta(hours=1, minutes=59)
    assert wd.verdict([run], wd.ARCHIVE, start, soon) == "RUNNING"
    assert wd.verdict([run, _run(start, "failure", title=wd.ARCHIVE.title)], wd.ARCHIVE, start, soon) == "RUNNING"
    late = start + timedelta(hours=2, minutes=15)
    assert wd.verdict([run], wd.ARCHIVE, start, late) == ("RUNNING" if status == "in_progress" else "STUCK")


def test_skipped_archive_is_ok():
    """Archive switched off on purpose (jobs skipped) is not a missed night."""
    start = MON.replace(hour=20, minute=15)
    assert wd.verdict([_run(start, "skipped", title=wd.ARCHIVE.title)], wd.ARCHIVE, start, start) == "OK"


@pytest.mark.parametrize("other", [
    dict(title="Collector close"), dict(title="Collector all"), dict(event="schedule"),
    dict(branch="feature"), dict(title="Verified Drive archive (nightly restore-proven retention when enabled)")])
def test_other_runs_never_hide_a_missed_slot(other):
    """A close/manual/feature-branch run in the window is not the slot's dispatch."""
    start = MON.replace(hour=9, minute=7)
    assert wd.verdict([_run(start + timedelta(minutes=68), **other)], wd.SCAN_1437, start, start) == "MISSING"


def test_ok_sends_nothing():
    """A successful run in the window: one OK line, no alert."""
    calls = []
    start = MON.replace(hour=4, minute=37)
    lines = wd.check(ENV, (wd.SCAN_1007,), MON.replace(hour=6),
                     runs=lambda *a: [_run(start + timedelta(minutes=1))], post=_sent(calls))
    assert lines == ["collector 10:07 IST scan: OK"] and calls == []


def test_missing_sends_one_alert_with_the_fixed_text():
    """No run at all: one MISSING alert naming the slot, IST time and the workflow page."""
    calls = []
    seen = []
    lines = wd.check(ENV, (wd.SCAN_1007,), MON.replace(hour=6),
                     runs=lambda *a: seen.append(a) or [], post=_sent(calls))
    assert lines == ["collector 10:07 IST scan: MISSING RUN_ALERT_SENT"]
    assert calls == ["MISSING: collector 10:07 IST scan (16 Nov 10:07 IST) - no run started. "
                     "Check: https://github.com/owner/repo/actions/workflows/scheduled-collector.yml"]
    assert seen == [("owner/repo", "scheduled-collector.yml", MON.replace(hour=4, minute=37), "ghs_x")]


def test_failed_run_says_no_successful_run():
    """A run that exists but did not succeed is NOT_OK with its own wording."""
    calls = []
    start = MON.replace(hour=20, minute=15)
    lines = wd.check(ENV, (wd.ARCHIVE,), MON.replace(hour=22, minute=30),
                     runs=lambda *a: [_run(start, "failure", title=wd.ARCHIVE.title)], post=_sent(calls))
    assert lines == ["nightly archive 01:45 IST: NOT_OK RUN_ALERT_SENT"]
    assert calls[0].startswith("NOT OK: nightly archive 01:45 IST (17 Nov 01:45 IST) - no successful run.")


def test_running_sends_nothing():
    """RUNNING is logged, not alerted."""
    calls = []
    start = MON.replace(hour=20, minute=15)
    lines = wd.check(ENV, (wd.ARCHIVE,), MON.replace(hour=22, minute=30),
                     runs=lambda *a: [_run(start, None, title=wd.ARCHIVE.title)], post=_sent(calls))
    assert lines == ["nightly archive 01:45 IST: RUNNING"] and calls == []


def test_stuck_in_queue_alerts():
    """Queued for over 2 h (replaced in the queue later, or no runner): STUCK alert."""
    calls = []
    start = MON.replace(hour=20, minute=15)
    lines = wd.check(ENV, (wd.ARCHIVE,), MON.replace(hour=22, minute=30),
                     runs=lambda *a: [_run(start, None, title=wd.ARCHIVE.title, status="queued")], post=_sent(calls))
    assert lines == ["nightly archive 01:45 IST: STUCK RUN_ALERT_SENT"]
    assert calls[0].startswith("STUCK: nightly archive 01:45 IST (17 Nov 01:45 IST) - waiting to start for over 2 h.")


def test_unreachable_api_does_not_alert_or_raise():
    """GitHub API trouble is reported in the log, not as a false phone alert."""
    def broken(*a):
        """Raise like a failed request."""
        raise OSError("down")
    calls = []
    assert wd.check(ENV, (wd.SCAN_1437,), MON.replace(hour=10, minute=30), runs=broken,
                    post=_sent(calls)) == ["collector 14:37 IST scan: CHECK_UNAVAILABLE"]
    assert calls == []


def test_bad_repository_checks_nothing():
    """An unexpected repository name stops before any request."""
    assert wd.check(dict(ENV, GITHUB_REPOSITORY="x"), wd.SLOTS, MON, runs=None) == ["WATCHDOG_FIELDS_INVALID"]


@pytest.mark.parametrize("schedule,names", [
    ("0 6 * * 1-5", ["collector 10:07 IST scan"]), ("30 10 * * 1-5", ["collector 14:37 IST scan"]),
    ("30 22 * * *", ["nightly archive 01:45 IST"]),
    ("", ["collector 10:07 IST scan", "collector 14:37 IST scan", "nightly archive 01:45 IST"])])
def test_main_checks_the_slot_its_schedule_watches(monkeypatch, capsys, schedule, names):
    """A scheduled run checks only its slot (no repeat alerts); a manual run checks all; exit 0."""
    monkeypatch.setattr(wd, "github_runs", lambda *a: [])
    monkeypatch.setattr(wd.alert, "telegram_https_post", lambda p, b: (500, b""))
    now = MON + timedelta(days=1, hours=23)
    assert wd.main([], env=dict(ENV, WATCHDOG_SCHEDULE=schedule), now=now) == 0
    out = capsys.readouterr().out.splitlines()
    assert [line.rsplit(": ", 1)[0] for line in out] == names
    assert all(line.endswith("RUN_ALERT_DELIVERY_UNVERIFIED") for line in out)


class _Connection:
    """Stand-in for http.client.HTTPSConnection recording the request."""
    seen = {}

    def __init__(self, host, timeout, context):
        self.seen.update(host=host, timeout=timeout)

    def request(self, method, path, headers):
        self.seen.update(method=method, path=path, headers=headers)

    def getresponse(self):
        return self.response

    def close(self):
        self.seen["closed"] = True


class _Response:
    """A bounded HTTP reply."""
    def __init__(self, status, raw):
        self.status, self.raw = status, raw

    def read(self, limit):
        return self.raw[:limit]


def test_github_runs_request_and_reply(monkeypatch):
    """Fixed host, created>= filter, bearer credential, workflow_runs list; closes the connection."""
    _Connection.seen = {}
    _Connection.response = _Response(200, json.dumps({"workflow_runs": [{"id": 1}]}).encode())
    monkeypatch.setattr(wd.http.client, "HTTPSConnection", _Connection)
    start = MON.replace(hour=4, minute=37)
    assert wd.github_runs("owner/repo", "drive-archive.yml", start, "ghs_x") == [{"id": 1}]
    seen = _Connection.seen
    assert seen["host"] == "api.github.com" and seen["method"] == "GET" and seen["closed"]
    assert seen["path"] == ("/repos/owner/repo/actions/workflows/drive-archive.yml/runs"
                            "?created=2026-11-16T04%3A22%3A00Z..2026-11-16T06%3A37%3A00Z"
                            "&event=workflow_dispatch&branch=main&per_page=100")
    assert seen["headers"]["Authorization"] == "Bearer ghs_x"


@pytest.mark.parametrize("status,raw", [
    (404, b'{"workflow_runs": []}'), (200, b'{"workflow_runs": []}' + b" " * 2_000_000), (200, b"{}")])
def test_github_runs_bad_reply_raises(monkeypatch, status, raw):
    """Non-200, oversize or shapeless replies raise (check() turns that into CHECK_UNAVAILABLE)."""
    _Connection.response = _Response(status, raw)
    monkeypatch.setattr(wd.http.client, "HTTPSConnection", _Connection)
    with pytest.raises(Exception):
        wd.github_runs("owner/repo", "drive-archive.yml", MON, "ghs_x")


def test_workflow_schedules_match_the_slots():
    """run-watchdog.yml crons are exactly WATCHES, each at least an hour after its slot."""
    text = (ROOT / ".github/workflows/run-watchdog.yml").read_text()
    crons = re.findall(r"- cron: '([^']+)'", text)
    assert crons == list(wd.WATCHES)
    for cron, slot in wd.WATCHES.items():
        minute, hour = (int(v) for v in cron.split()[:2])
        assert (hour * 60 + minute) - (slot.at.hour * 60 + slot.at.minute) >= 60
    assert "WATCHDOG_SCHEDULE: ${{ github.event.schedule || inputs.slot }}" in text
    assert "actions: read" in text and "contents: read" in text and "persist-credentials: false" in text
    assert "run: python run_watchdog.py" in text


def test_slots_mirror_the_reviewed_cron_jobs():
    """Slot times and titles match the Supabase Cron SQL and the workflows' run titles."""
    collector_sql = (ROOT / "supabase/scheduled-collector-cron.sql").read_text()
    archive_sql = (ROOT / "supabase/archive-nightly-cron.sql").read_text()
    jobs = re.findall(r"'([0-9*, /-]+ [0-9*, /-]+ \* \* [0-9*-]+)',.*?body := '(\{[^']+\})'", collector_sql, re.S)
    scans = [cron for cron, body in jobs if json.loads(body)["mode"] == "scan"]
    assert scans == ["37 4 * * 1-5", "7 9 * * 1-5"]
    assert "'15 20 * * *'" in archive_sql and '"target":"archive-nightly"' in archive_sql
    for slot, cron in ((wd.SCAN_1007, "37 4 * * 1-5"), (wd.SCAN_1437, "7 9 * * 1-5"), (wd.ARCHIVE, "15 20 * * *")):
        minute, hour = (int(v) for v in cron.split()[:2])
        assert (slot.at.hour, slot.at.minute) == (hour, minute)
        assert cron in wd.__doc__
    assert wd.SCAN_1007.weekdays == wd.SCAN_1437.weekdays == frozenset(range(5))
    assert wd.ARCHIVE.weekdays == frozenset(range(7))
    collector = (ROOT / ".github/workflows/scheduled-collector.yml").read_text()
    archive = (ROOT / ".github/workflows/drive-archive.yml").read_text()
    assert "run-name: Collector ${{ inputs.mode }}" in collector and wd.SCAN_1007.title == "Collector scan"
    assert f"&& '{wd.ARCHIVE.title}' ||" in archive
