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
- Not covered: pg_cron jobs that don't dispatch GitHub (purge 7, VACUUM 8), and a GitHub
  schedule that GitHub drops entirely.
- `RUN_ALERT_NOT_CONFIGURED missing=<names>` names the absent secret(s) (never values).

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
