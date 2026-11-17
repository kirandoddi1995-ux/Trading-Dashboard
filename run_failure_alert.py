"""Phone alert when an unattended GitHub Actions run fails (collector, nightly archive).

A workflow step with `if: failure() || cancelled()` runs `python run_failure_alert.py --label <what>`.
The run exits 0 in every case: the job is already failed and visible in GitHub; a missing
or broken alert must never hide that or add a second failure.

- Not configured (TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID repository secret empty): prints
  RUN_ALERT_NOT_CONFIGURED missing=<secret names> and sends nothing.
- The message is built only from validated fields (workflow name, label, run link, IST
  time), never from logs or provider text. Transport: `telegram_https_post` (fixed host,
  TLS, no redirects, bounded reply). Outcomes print as one fixed status word; the bot
  credential and the chat id are never printed.
- `--test` sends a one-off "alerts are working" message (alert-test.yml).
- JOB_STATUS (`job.status`) = cancelled says "CANCELLED or TIMED OUT" instead of "FAILED".

Limits: a failed checkout leaves no script to run (no alert); a run GitHub drops while it
waits in the concurrency queue never starts a job (no alert). Both need an outside watchdog.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
import re
from typing import Callable, Mapping

from overnight_operations_alerts import telegram_https_post

IST = timezone(timedelta(hours=5, minutes=30))
BOT_PATTERN = re.compile(r"[0-9]{5,20}:[A-Za-z0-9_-]{20,100}")
CHAT_PATTERN = re.compile(r"-?[0-9]{1,20}")
LABEL_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,40}")
WORKFLOW_PATTERN = re.compile(r"[A-Za-z0-9 _().-]{1,80}")
REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}")
RUN_ID_PATTERN = re.compile(r"[1-9][0-9]{0,19}")


def message(env: Mapping[str, str], label: str, now: datetime, test: bool = False) -> str:
    """The alert text from validated fields only; ValueError when a field is not as expected."""
    workflow = env.get("GITHUB_WORKFLOW", "")
    repository = env.get("GITHUB_REPOSITORY", "")
    run_id = env.get("GITHUB_RUN_ID", "")
    for value, pattern in ((workflow, WORKFLOW_PATTERN), (label, LABEL_PATTERN),
                           (repository, REPOSITORY_PATTERN), (run_id, RUN_ID_PATTERN)):
        if pattern.fullmatch(value) is None:
            raise ValueError("field")
    when = now.astimezone(IST).strftime("%d %b %H:%M IST")
    link = f"https://github.com/{repository}/actions/runs/{run_id}"
    if test:
        return f"Test: trading dashboard alerts are working ({when}). Run: {link}"
    what = "CANCELLED or TIMED OUT" if env.get("JOB_STATUS") == "cancelled" else "FAILED"
    return f"{what}: {workflow} ({label}) at {when}. Open the run: {link}"


def send(env: Mapping[str, str], label: str, *, test: bool = False,
         post: Callable[[str, bytes], tuple[int, bytes]] | None = None,
         clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> str:
    """Send one run alert; returns the status word to print (never raises)."""
    destination = _destination(env)
    if isinstance(destination, str):
        return destination
    try:
        text = message(env, label, clock(), test)
    except ValueError:
        return "RUN_ALERT_FIELDS_INVALID"
    return send_text(env, text, post=post)


def send_text(env: Mapping[str, str], text: str, *,
              post: Callable[[str, bytes], tuple[int, bytes]] | None = None) -> str:
    """Send a ready text (built from validated fields by the caller); never raises."""
    post = post or telegram_https_post
    destination = _destination(env)
    if isinstance(destination, str):
        return destination
    bot, chat = destination
    body = json.dumps({"chat_id": chat, "text": text, "disable_web_page_preview": True,
                       "allow_paid_broadcast": False}, separators=(",", ":")).encode()
    try:
        delivered = _delivered(*post("/bot" + bot + "/sendMessage", body), text, chat)
    except Exception:
        delivered = False
    return "RUN_ALERT_SENT" if delivered else "RUN_ALERT_DELIVERY_UNVERIFIED"


def _destination(env: Mapping[str, str]) -> tuple[str, str] | str:
    """(bot, chat) from the secrets, or the status word when missing or malformed."""
    bot = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = env.get("TELEGRAM_CHAT_ID", "").strip()
    if not bot or not chat:
        missing = [name for name, value in (("TELEGRAM_BOT_TOKEN", bot), ("TELEGRAM_CHAT_ID", chat)) if not value]
        return "RUN_ALERT_NOT_CONFIGURED missing=" + ",".join(missing)   # secret names only
    if BOT_PATTERN.fullmatch(bot) is None or CHAT_PATTERN.fullmatch(chat) is None:
        return "RUN_ALERT_DESTINATION_INVALID"
    return bot, chat


def _delivered(status: int, raw: bytes, text: str, chat: str) -> bool:
    """Telegram accepted exactly this text for this chat (anything else raises or is False)."""
    reply = json.loads(raw)
    sent = reply["result"]
    return (status == 200 and reply.get("ok") is True and sent.get("text") == text
            and str(sent.get("chat", {}).get("id")) == chat)


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    """CLI for the workflow step; always 0 (see the module docstring)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", default="run")
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args(argv)
    print(send(os.environ if env is None else env, args.label, test=args.test))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
