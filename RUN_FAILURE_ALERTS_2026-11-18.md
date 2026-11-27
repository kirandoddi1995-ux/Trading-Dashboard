# Phone alerts for failed unattended runs (18 Nov 2026)

Kiran chose Telegram phone alerts (17 Nov). `run_failure_alert.py` sends one plain-text
message when the collector (`scheduled-collector.yml`, job `collect`) or the nightly archive
(`drive-archive.yml`, job `archive`) fails, is cancelled or times out:

    FAILED: <workflow> (<mode>) at <dd Mon HH:MM IST>. Open the run: <run link>

- Last step of each job, `if: failure() || cancelled()`; a PARTIAL collector run exits 2,
  so it alerts. `job.status = cancelled` says "CANCELLED or TIMED OUT".
- Secrets `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (Kiran set them 18 Nov 00:02 IST) reach
  the step only as env. Without them the step prints RUN_ALERT_NOT_CONFIGURED and sends nothing.
- The text is built from validated fields only (workflow name, mode, run id, repository);
  no parse mode, no logs, no provider text. Transport: `overnight_operations_alerts.
  telegram_https_post` (fixed host, TLS, no redirects, bounded reply). Standard library only,
  so it works even when `pip install` failed.
- Always exits 0 (the job is already red). The log shows one word: RUN_ALERT_SENT,
  RUN_ALERT_DELIVERY_UNVERIFIED, RUN_ALERT_DESTINATION_INVALID, RUN_ALERT_FIELDS_INVALID or
  RUN_ALERT_NOT_CONFIGURED. The bot credential and chat id are never printed.
- `alert-test.yml` (manual): sends "Test: trading dashboard alerts are working" and fails
  unless RUN_ALERT_SENT.

Limits (need an outside watchdog): a failed checkout leaves no script to run; a run GitHub
drops while it waits in the concurrency queue, or a collector the Supabase cron never
dispatched, starts no job. The separate durable overnight alert design
(`overnight_operations_alerts`, inactive) is unchanged.

`drive-archive.yml` is a pinned source: its `SOURCE_SUPERSESSIONS.json` entry now maps the
same predecessor to the new bytes, with this note as the reason.

## Watchdog (18 Nov): runs that never start

`run_watchdog.py` + `run-watchdog.yml` (GitHub schedule 06:00 / 10:30 UTC Mon-Fri, 22:30 UTC
daily; manual = all slots) closes the limits above. After each Supabase Cron slot it lists that
workflow's main-branch workflow_dispatch runs created in [slot-15 min, slot+2 h] with the slot's
run title ("Collector scan" via the collector's new `run-name`, "Nightly archive (on-time
dispatch)"), so a close/manual/feature-branch run cannot stand in for a missed slot.

- OK (success or skipped) and RUNNING (running, or queued < 2 h): log only.
- MISSING (no run), NOT OK (no success), STUCK (queued > 2 h, never started): one Telegram message.
- A failed run can give two messages (in-job + watchdog); accepted, because a failed checkout
  gives only the watchdog's.
- Slot times are pinned by a test against `supabase/*-cron.sql`; change both together.
- Not covered here: pg_cron jobs that don't dispatch GitHub (VACUUM 8: see the nightly DB
  maintenance check below; purge 7 retired), and a GitHub schedule that GitHub drops entirely.
- `RUN_ALERT_NOT_CONFIGURED missing=<names>` names the absent secret(s) (never values).
- Exit 1 (27 Nov) when a slot could not be checked (`CHECK_UNAVAILABLE` after one retry 15 s later,
  `WATCHDOG_FIELDS_INVALID`) or a needed alert was not delivered: the run turns red and the workflow's
  last step alerts, so a blind or mute watchdog is loud. The DB maintenance steps still run after it
  (`!cancelled()`). If Telegram itself is down, that last step cannot deliver either: the red run (and
  GitHub's own failed-run notice) is then the only signal.

## On-time watchdog start (18 Nov, later)

GitHub started the 22:30 UTC watchdog at 03:47 UTC (5 h late). `supabase/run-watchdog-cron.sql`
adds three Supabase Cron jobs at the same three crons. Each sends its own fixed target
(`run-watchdog-1130`, `-1600`, `-0400`) to `dispatch-scheduled-collector`, which dispatches
`run-watchdog.yml` with input `slot` = that job's cron (the caller cannot change it). The run
checks that one slot only, as a scheduled run does. The GitHub schedule stays as a fallback.

- A miss gives one alert from the on-time run, and maybe one more when the late GitHub
  fallback run arrives (accepted: two beats none).
- Manual run with `slot` empty: checks every slot (unchanged).
- Owner steps: redeploy the Edge Function first, then run `supabase/run-watchdog-cron.sql` in
  the SQL Editor and check the three rows it prints are active.

## Nightly DB maintenance check (24 Nov)

pg_cron job 8 `nightly-vacuum-growing-tables` (22:45 UTC) runs inside Supabase and dispatches
nothing, so no alert saw it. The runtime role cannot read the cron schema (`cron.job_run_details`),
so `db_maintenance_watch.py` checks, read-only, what the job leaves behind:
`pg_stat_user_tables.last_vacuum` (manual VACUUM, not autovacuum) of the four tables in job 8 is at
most 26 h old. It catches a failed, paused, deleted or edited job and a stopped scheduler. A
statistics reset (crash recovery) reads as LATE until the next VACUUM.

`run-watchdog.yml` runs it after the GitHub check in the 04:00 IST slot (22:30 UTC; the previous
VACUUM is then 23 h 45 m old, so a failed VACUUM shows the next night) and on every run that is
not a scan slot (manual runs), with `DATABASE_URL` (runtime role, same secret as the collector)
in that one step only, a read-only TLS session and 15 s / 2 s statement / lock limits.

- LATE, or a database it cannot read (a failed read is retried once after 20 s; a missing secret
  is not retried): one Telegram message from fixed text and numbers, never error text. OK: log only.
- Exit 0, or 1 when a needed alert was not delivered: the run turns red and the new last step
  (`if: failure() || cancelled()`, also for a failed `psycopg` install, which skips the check) tries
  once more. The two steps run only when the GitHub check step ran (not after a failed checkout);
  the check step only when the install succeeded.
- A late GitHub fallback run of the same slot checks again (a real problem may alert twice).
- If job 8 changes its tables or runs less than daily, change `db_maintenance_watch.py` too (a new
  run time inside the day needs no change).
- Option (not built): a SELECT-only login role + its own secret instead of the runtime role.

Job 7 `purge_raw_quotes` (20:00 UTC, `UPDATE quant_app.market_quotes SET raw = NULL WHERE
observed_at < now() - interval '3 days'`): Kiran chose to retire it (24 Nov). Since `typed_only_v1` every
new quote row holds only the 35-byte marker `{"retention": "typed_only_v1"}` in `raw`, and the
archive deletes quotes after 14 days, so the job saved at most ~2 MB while rewriting every row older
than 3 days each night (23 Nov: 44,054 rows written, 5,520 newly purged). Owner step: run
`supabase/retire-purge-raw-quotes-cron.sql` once in the SQL Editor (pre-check, `cron.unschedule`,
check; rollback in its header; a second run stops at the pre-check, as expected).
