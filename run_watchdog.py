"""Watchdog: phone alert when an expected unattended run never succeeded (no run at all included).

`run_failure_alert.py` alerts from inside a failing job. It cannot see runs that never start
a job: a Supabase Cron dispatch that did not happen, a run GitHub dropped from the concurrency
queue, or a failed checkout. This scheduled check (run-watchdog.yml) asks the GitHub API, after
each slot, whether a successful run of that workflow was created inside the slot's window; if
not, it sends one Telegram message.

Slots mirror the active Supabase Cron jobs (cron.job, checked 18 Nov 2026):
  2 collector-scan-1007-ist  37 4 * * 1-5  -> scheduled-collector.yml
  3 collector-scan-1437-ist   7 9 * * 1-5  -> scheduled-collector.yml
  9 archive-nightly-0145-ist 15 20 * * *   -> drive-archive.yml
If a cron time changes, change SLOTS too (else this alerts every day). NSE holidays are fine:
the collector still runs and ends SUCCESS with a SKIPPED scan.

A run counts only when it is that slot's dispatch: workflow_dispatch on main with the slot's
run title ("Collector scan", "Nightly archive (on-time dispatch)"), created in the window, so
a close/global/manual run or a feature-branch run can never stand in for a missed slot.
OK = success or skipped (archive switched off on purpose; a held archive also ends success).
RUNNING = running, or queued for under 2 h, at the check: no alert (a hung run hits its job
timeout and the in-job alert fires). STUCK = queued for over 2 h (never started: no in-job alert). MISSING / NOT_OK alert; a failed run may also have sent the in-job
alert, so a failure can give two messages (accepted: a failed checkout gives only this one).

A run checks only the slot it watches: the on-time Supabase dispatch passes that slot's cron
as input `slot`, the late GitHub fallback schedule passes it as github.event.schedule (both
keys of WATCHES); a manual run with no slot checks every slot's latest instance. Always exits 0; prints one status word per slot. Standard library only.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
import http.client
import json
import os
import ssl
from typing import Callable, Mapping
import urllib.parse

import run_failure_alert as alert


@dataclass(frozen=True)
class Slot:
    """One expected run: a workflow file dispatched at a UTC time on the given weekdays."""
    name: str
    workflow: str
    title: str
    at: time
    weekdays: frozenset


SCAN_1007 = Slot("collector 10:07 IST scan", "scheduled-collector.yml", "Collector scan", time(4, 37),
                 frozenset(range(5)))
SCAN_1437 = Slot("collector 14:37 IST scan", "scheduled-collector.yml", "Collector scan", time(9, 7),
                 frozenset(range(5)))
ARCHIVE = Slot("nightly archive 01:45 IST", "drive-archive.yml", "Nightly archive (on-time dispatch)",
               time(20, 15), frozenset(range(7)))
BRANCH = "main"   # the Edge Function dispatches `config.ref ?? "main"`; another ref = MISSING every day
UNFINISHED = {"queued", "in_progress", "waiting", "requested", "pending"}
SLOTS = (SCAN_1007, SCAN_1437, ARCHIVE)
# Watchdog cron (run-watchdog.yml) -> the slot it checks.
WATCHES = {"0 6 * * 1-5": SCAN_1007, "30 10 * * 1-5": SCAN_1437, "30 22 * * *": ARCHIVE}
EARLY = timedelta(minutes=15)     # a run created this long before the slot still counts
WINDOW = timedelta(hours=2)       # ... and up to this long after it (dispatch or queue delay)
SETTLE = timedelta(minutes=60)    # a slot is only judged once this long has passed
QUEUE_LIMIT = timedelta(hours=2)  # a run still waiting to start after this long is STUCK


def latest_instance(slot: Slot, now: datetime) -> datetime:
    """The most recent slot time on an allowed weekday that is at least SETTLE in the past."""
    day = now.date()
    for back in range(8):
        candidate = datetime.combine(day - timedelta(days=back), slot.at, tzinfo=timezone.utc)
        if candidate.weekday() in slot.weekdays and candidate + SETTLE <= now:
            return candidate
    raise ValueError("no slot instance")


def verdict(runs: list[dict], slot: Slot, start: datetime, now: datetime) -> str:
    """OK / RUNNING / STUCK / NOT_OK / MISSING for the slot's own dispatch in [start-EARLY, start+WINDOW]."""
    inside = []
    for run in runs:
        created = datetime.fromisoformat(str(run.get("created_at", "")).replace("Z", "+00:00"))
        if (run.get("display_title") == slot.title and run.get("event") == "workflow_dispatch"
                and run.get("head_branch") == BRANCH and start - EARLY <= created <= start + WINDOW):
            inside.append((run, created))
    if any(run.get("conclusion") in ("success", "skipped") for run, _ in inside):
        return "OK"
    waiting = [(run, created) for run, created in inside if run.get("status") in UNFINISHED]
    if any(run.get("status") == "in_progress" or created > now - QUEUE_LIMIT for run, created in waiting):
        return "RUNNING"
    if waiting:
        return "STUCK"     # never started: a queue replacement or runner expiry gives no in-job alert
    return "NOT_OK" if inside else "MISSING"


def github_runs(repository: str, workflow: str, start: datetime, credential: str) -> list[dict]:
    """Main-branch dispatches of one workflow created inside the slot window (GitHub REST, bounded)."""
    stamp = "%Y-%m-%dT%H:%M:%SZ"
    query = urllib.parse.urlencode({
        "created": f"{(start - EARLY).strftime(stamp)}..{(start + WINDOW).strftime(stamp)}",
        "event": "workflow_dispatch", "branch": BRANCH, "per_page": 100})
    connection = http.client.HTTPSConnection("api.github.com", timeout=20, context=ssl.create_default_context())
    try:
        connection.request("GET", f"/repos/{repository}/actions/workflows/{workflow}/runs?{query}", headers={
            "Authorization": "Bearer " + credential, "Accept": "application/vnd.github+json",
            "User-Agent": "run-watchdog", "X-GitHub-Api-Version": "2022-11-28"})
        response = connection.getresponse()
        raw = response.read(2_000_001)
        if response.status != 200 or len(raw) > 2_000_000:
            raise ValueError("github reply")
        return list(json.loads(raw)["workflow_runs"])
    finally:
        connection.close()


def message(slot: Slot, start: datetime, result: str, repository: str, workflow_file: str) -> str:
    """The alert text (fixed shape; validated fields only)."""
    when = start.astimezone(alert.IST).strftime("%d %b %H:%M IST")
    head, what = {"MISSING": ("MISSING", "no run started"), "STUCK": ("STUCK", "waiting to start for over 2 h")
                  }.get(result, ("NOT OK", "no successful run"))
    return (f"{head}: {slot.name} ({when}) - {what}. "
            f"Check: https://github.com/{repository}/actions/workflows/{workflow_file}")


def check(env: Mapping[str, str], slots, now: datetime,
          runs: Callable[[str, str, datetime, str], list[dict]] | None = None,
          post: Callable[[str, bytes], tuple[int, bytes]] | None = None) -> list[str]:
    """One status line per slot: OK, RUNNING, MISSING/NOT_OK plus the send status, or CHECK_UNAVAILABLE."""
    runs = runs or github_runs
    repository = env.get("GITHUB_REPOSITORY", "")
    if alert.REPOSITORY_PATTERN.fullmatch(repository) is None:
        return ["WATCHDOG_FIELDS_INVALID"]
    lines = []
    for slot in slots:
        try:
            start = latest_instance(slot, now)
            result = verdict(runs(repository, slot.workflow, start, env.get("GITHUB_TOKEN", "")), slot, start, now)
        except Exception:
            lines.append(f"{slot.name}: CHECK_UNAVAILABLE")
            continue
        if result in ("OK", "RUNNING"):
            lines.append(f"{slot.name}: {result}")
            continue
        sent = alert.send_text(env, message(slot, start, result, repository, slot.workflow), post=post)
        lines.append(f"{slot.name}: {result} {sent}")
    return lines


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None,
         now: datetime | None = None) -> int:
    """CLI for run-watchdog.yml; always 0."""
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    env = os.environ if env is None else env
    schedule = env.get("WATCHDOG_SCHEDULE", "")
    slots = (WATCHES[schedule],) if schedule in WATCHES else SLOTS
    for line in check(env, slots, now or datetime.now(timezone.utc)):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
