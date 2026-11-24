"""Watchdog for the nightly Supabase pg_cron VACUUM job, which has no in-job alert.

pg_cron runs it inside the database (recorded live 24 Nov 2026):
  8 nightly-vacuum-growing-tables  45 22 * * *  VACUUM (ANALYZE) of the four TABLES below
The runtime role cannot read the cron schema, so this checks, read-only, what the job leaves behind:
`pg_stat_user_tables.last_vacuum` (set by a manual VACUUM such as job 8; autovacuum does not
count) of every table is at most 26 h (VACUUM_AGE) old. That catches a failed, paused, deleted or
edited job and a stopped scheduler. A statistics reset (crash recovery) clears last_vacuum: LATE
until the next VACUUM (rare, and loud is the safe side).
(Job 7 purge_raw_quotes is retired by supabase/retire-purge-raw-quotes-cron.sql: new quote rows hold
only the 35-byte raw marker {"retention": "typed_only_v1"}, and the archive deletes quotes after 14 days.)

run-watchdog.yml runs it in the 04:00 IST slot (22:30 UTC, before that night's VACUUM, so the
previous one is ~23 h 45 m old: a failed VACUUM shows the next night) and on every run that is not
a scan slot. LATE, or a database it cannot read (one retry 20 s after a failed read), sends one
Telegram message built from validated fields only. If job 8 changes its tables or runs less than
daily, change this file too. Exits 0, or 1 when a needed alert was not delivered (the run turns red
and the workflow's failure step tries once more).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import os
import time
from typing import Any, Callable, Mapping

import run_failure_alert as alert

VACUUM_AGE = timedelta(hours=26)
TABLES = ("market_quotes", "scanner_observations", "universe_membership_versions", "universe_membership")
VACUUM_SQL = ("SELECT t.name, s.last_vacuum FROM unnest(%s::text[]) AS t(name) "
              "LEFT JOIN pg_catalog.pg_stat_user_tables s ON s.schemaname = 'quant_app' AND s.relname = t.name")
RETRY_WAIT = 20   # seconds


def measure(database_url: str) -> tuple[Any, Any]:
    """TLS, read-only, short limits: (database now, [(table, last_vacuum)])."""
    import psycopg
    with psycopg.connect(database_url, connect_timeout=10, sslmode="require") as connection:
        connection.read_only = True
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout='15s'")
            cursor.execute("SET LOCAL lock_timeout='2s'")
            cursor.execute("SELECT now()")
            now = cursor.fetchone()[0]
            cursor.execute(VACUUM_SQL, (list(TABLES),))
            return now, cursor.fetchall()


def assess(now: Any, vacuums: Any) -> str | None:
    """The problem text (None = OK); ValueError / TypeError when the reply is not as expected."""
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("database time")
    rows = [tuple(row) for row in vacuums]
    last = dict(rows)
    if len(rows) != len(TABLES) or set(last) != set(TABLES):
        raise ValueError("vacuum reply")
    stale = []
    for name in TABLES:
        when = last[name]
        if when is None:
            stale.append(f"{name} none recorded")
            continue
        if not isinstance(when, datetime) or when.utcoffset() is None:
            raise ValueError("vacuum reply")
        if now - when > VACUUM_AGE:
            stale.append(f"{name} {int((now - when).total_seconds() // 3600)} h ago")
    return "VACUUM (pg_cron job 8) late: " + ", ".join(stale) if stale else None


def read(env: Mapping[str, str], measure_fn: Callable[[str], Any],
         sleep: Callable[[float], None]) -> tuple[str | None] | str:
    """(assess() of one read,) with one retry after a failed read, or a fixed failure code."""
    url = env.get("DATABASE_URL", "").strip()
    if not url:
        return "DATABASE_CONNECTION_REQUIRED"
    try:
        reply = measure_fn(url)
    except Exception:
        sleep(RETRY_WAIT)
        try:
            reply = measure_fn(url)
        except Exception:
            return "MAINTENANCE_CHECK_UNAVAILABLE"
    try:
        return (assess(*reply),)
    except (TypeError, ValueError):
        return "MAINTENANCE_MEASUREMENT_INVALID"


def check(env: Mapping[str, str], *, measure_fn: Callable[[str], Any] = measure,
          post: Callable[[str, bytes], tuple[int, bytes]] | None = None,
          sleep: Callable[[float], None] = time.sleep,
          clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> list[str]:
    """Status lines to print; one alert when the VACUUM is late or the check cannot read."""
    result = read(env, measure_fn, sleep)
    when = clock().astimezone(alert.IST).strftime("%d %b %H:%M IST")
    if isinstance(result, str):
        lines = [f"nightly DB maintenance: CHECK_FAILED {result}"]
        text = (f"CHECK FAILED: nightly DB maintenance check ({when}) could not read the database "
                f"({result}); VACUUM (pg_cron job 8) is unchecked.")
    else:
        problem = result[0]
        lines = [f"VACUUM (job 8): {'LATE' if problem else 'OK'}"]
        if not problem:
            return lines
        text = (f"LATE: nightly DB maintenance ({when}) - {problem}. "
                "Check the job history: Supabase > Integrations > Cron.")
    return lines + ["alert: " + alert.send_text(env, text, post=post)]


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    """CLI for run-watchdog.yml; 1 only when an alert was needed and not delivered."""
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    lines = check(os.environ if env is None else env)
    for line in lines:
        print(line)
    return 1 if any(line.startswith("alert: ") and line != "alert: RUN_ALERT_SENT" for line in lines) else 0


if __name__ == "__main__":
    raise SystemExit(main())
