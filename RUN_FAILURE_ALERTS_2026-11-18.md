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
