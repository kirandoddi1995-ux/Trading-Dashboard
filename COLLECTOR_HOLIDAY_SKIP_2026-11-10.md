# Scheduled scan skips NSE holidays instead of failing, 10 Nov 2026

## Problem

pg_cron dispatches the `scan` runs (10:07 and 14:37 IST) Monday to Friday, NSE holidays
included. On a holiday the Upstox NSE status is closed or was last changed the previous
day, so `fetch_nse_exchange_status` fails closed and the run goes red. Seen on
10 Nov 2026 (Diwali-Balipratipada): run 42756997155, "NSE exchange status was not updated
for the current IST trading date (65279s old)".

## Change (`scheduled_collector.py`)

`_market_status_or_holiday_skip` runs right after the scan-window check:

- Reviewed calendar (`nifty_session_calendar.cash_session`) says CLOSED and the live
  status is not today's NORMAL_OPEN (stale, closed, unreachable, HTTP error, token
  rejected) -> scan returns `SKIPPED`, reason "NSE holiday (reviewed calendar)", with
  the calendar source and the status check result. No universe, quote or database
  writes. The run finishes SUCCESS (green), like the existing outside-window skip.
- Calendar says CLOSED but NSE reports today's NORMAL_OPEN -> scan runs (the live
  exchange wins) and records quality event `CALENDAR_CLOSED_BUT_EXCHANGE_OPEN`.
- Calendar REGULAR or SPECIAL -> unchanged fail-closed status check. An unscheduled
  closure or a stale feed on a trading day stays a visible failure.
- Year not in the calendar (2027 onward until added) -> never assumed open or closed;
  the fail-closed check runs and its error says to add the year to
  `nifty_session_calendar.ANNUAL`.

Two sources must agree before a scan is skipped, so a wrong calendar entry can never
silently drop a live session.

## Follow-up

Add the 2027 NSE holiday list (NSE circular, usually published in December) to
`nifty_session_calendar.ANNUAL` before 1 Jan 2027.

Source pin: `SOURCE_SUPERSESSIONS.json` maps the historical `scheduled_collector.py` pin
`6be0f301...` to these bytes (previous successor from AUTO_STAGE2_COLLECTOR_2026-11-10.md);
`security_profile_successors.SUPERSESSIONS_SHA256` re-pins the record.

Tests: `tests/test_collector_holiday_skip.py` (11; every decision branch mutation-tested).
