"""Phone alerts for failed unattended runs: never raise, never leak, fixed message shape."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

import run_failure_alert as alert
from overnight_operations_alerts import OperationError

ROOT = Path(__file__).resolve().parents[1]
BOT = "123456789:" + "A" * 35
CHAT = "-1001234567890"
NOW = datetime(2026, 11, 18, 4, 40, tzinfo=timezone.utc)   # 10:10 IST
ENV = {"TELEGRAM_BOT_TOKEN": BOT, "TELEGRAM_CHAT_ID": CHAT, "GITHUB_WORKFLOW": "Scheduled evidence collector",
       "GITHUB_REPOSITORY": "owner/repo", "GITHUB_RUN_ID": "44018415858"}
TEXT = ("FAILED: Scheduled evidence collector (scan) at 18 Nov 10:10 IST. "
        "Open the run: https://github.com/owner/repo/actions/runs/44018415858")


def _post(replies, calls):
    """A fake transport that records (path, body) and returns the next reply."""
    def post(path, body):
        """Record the call; return or raise the next scripted reply."""
        calls.append((path, json.loads(body)))
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
    return post


def _ok(text, chat=CHAT):
    """Telegram's sendMessage reply for a delivered message."""
    return 200, json.dumps({"ok": True, "result": {"text": text, "chat": {"id": int(chat)}}}).encode()


def test_sends_the_fixed_message_and_reports_sent():
    """One POST to sendMessage with exactly the fixed fields; a matching reply is SENT."""
    calls = []
    assert alert.send(ENV, "scan", post=_post([_ok(TEXT)], calls), clock=lambda: NOW) == "RUN_ALERT_SENT"
    path, body = calls[0]
    assert path == "/bot" + BOT + "/sendMessage"
    assert body == {"chat_id": CHAT, "text": TEXT, "disable_web_page_preview": True, "allow_paid_broadcast": False}


def test_test_message():
    """The --test message names the run and says alerts work."""
    assert alert.message(ENV, "test", NOW, test=True) == (
        "Test: trading dashboard alerts are working (18 Nov 10:10 IST). "
        "Run: https://github.com/owner/repo/actions/runs/44018415858")


@pytest.mark.parametrize("missing", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"])
@pytest.mark.parametrize("value", [None, "", "   "])
def test_not_configured_sends_nothing(missing, value):
    """Missing or blank secrets: no transport call (safe before Kiran adds them)."""
    env = dict(ENV)
    if value is None:
        env.pop(missing)
    else:
        env[missing] = value
    calls = []
    assert alert.send(env, "scan", post=_post([], calls), clock=lambda: NOW) == "RUN_ALERT_NOT_CONFIGURED missing=" + missing
    assert calls == []


@pytest.mark.parametrize("key,value", [
    ("TELEGRAM_BOT_TOKEN", "not-a-bot"), ("TELEGRAM_BOT_TOKEN", BOT + "/x"),
    ("TELEGRAM_CHAT_ID", "@channel"), ("TELEGRAM_CHAT_ID", "12a")])
def test_invalid_destination_sends_nothing(key, value):
    """Malformed bot credential or chat id: nothing is sent."""
    calls = []
    env = dict(ENV, **{key: value})
    assert alert.send(env, "scan", post=_post([], calls), clock=lambda: NOW) == "RUN_ALERT_DESTINATION_INVALID"
    assert calls == []


@pytest.mark.parametrize("key,value", [
    ("GITHUB_RUN_ID", "0"), ("GITHUB_RUN_ID", "12 3"), ("GITHUB_REPOSITORY", "owner/repo/../x"),
    ("GITHUB_WORKFLOW", "x\ny"), ("GITHUB_WORKFLOW", ""), ("GITHUB_REPOSITORY", "")])
def test_unexpected_fields_send_nothing(key, value):
    """Run fields outside their pattern never reach the message."""
    calls = []
    env = dict(ENV, **{key: value})
    assert alert.send(env, "scan", post=_post([], calls), clock=lambda: NOW) == "RUN_ALERT_FIELDS_INVALID"
    assert calls == []


@pytest.mark.parametrize("label", ["", "a b", "$(id)", "x" * 41, "scan\n"])
def test_unexpected_label_sends_nothing(label):
    """Only a plain label goes into the text (no spaces, shell or newline)."""
    calls = []
    assert alert.send(ENV, label, post=_post([], calls), clock=lambda: NOW) == "RUN_ALERT_FIELDS_INVALID"
    assert calls == []


@pytest.mark.parametrize("reply", [
    (500, b"{}"), (500, _ok(TEXT)[1]), (201, _ok(TEXT)[1]), (200, b"not json"), (200, b'{"ok": false, "result": {}}'),
    (200, json.dumps({"ok": True, "result": {"text": "other", "chat": {"id": int(CHAT)}}}).encode()),
    (200, json.dumps({"ok": True, "result": {"text": TEXT, "chat": {"id": 1}}}).encode()),
    (200, b'{"ok": true}'), OperationError("ALERT_TRANSPORT_UNAVAILABLE"), RuntimeError("boom")])
def test_any_bad_reply_is_unverified_and_never_raises(reply):
    """Every bad status, body, echo or transport error is UNVERIFIED, never an exception."""
    calls = []
    assert alert.send(ENV, "scan", post=_post([reply], calls), clock=lambda: NOW) == "RUN_ALERT_DELIVERY_UNVERIFIED"


def test_main_always_exits_zero_and_prints_only_the_status(capsys):
    """The CLI exits 0 and prints one status word."""
    assert alert.main(["--label", "scan"], env={}) == 0
    out = capsys.readouterr().out
    assert out == "RUN_ALERT_NOT_CONFIGURED missing=TELEGRAM_BOT_TOKEN,TELEGRAM_CHAT_ID\n"


def test_main_never_prints_the_destination(capsys, monkeypatch):
    """A failed delivery prints the status only, never the bot credential or chat id."""
    calls = []
    monkeypatch.setattr(alert, "telegram_https_post", _post([(500, b"")], calls))
    assert alert.main(["--label", "scan"], env=ENV) == 0
    assert len(calls) == 1   # the real transport is the default
    out = capsys.readouterr().out
    assert out == "RUN_ALERT_DELIVERY_UNVERIFIED\n" and BOT not in out and CHAT not in out


def _job(name, job, next_job):
    """One job's text from a workflow file (from `  job:` to the next top-level job or the end)."""
    text = (ROOT / ".github/workflows" / name).read_text()
    start = text.index(f"\n  {job}:\n")
    end = text.index(f"\n  {next_job}:\n", start) if next_job else len(text)
    return text, text[start:end]


@pytest.mark.parametrize("name,job,next_job,label", [
    ("scheduled-collector.yml", "collect", None, "ALERT_LABEL: ${{ inputs.mode }}"),
    ("drive-archive.yml", "archive", "on-time-check", "ALERT_LABEL: archive-${{ inputs.mode || github.event_name }}")])
def test_unattended_workflows_alert_on_failure(name, job, next_job, label):
    """The alert is the LAST step of the collector's and the nightly archive's job, on failure or cancel."""
    text, body = _job(name, job, next_job)
    steps = body.split("\n      - ")
    step = steps[-1]
    assert step.startswith("name: Phone alert when this run fails")
    assert "if: failure() || cancelled()" in step.splitlines()[1]
    assert "TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}" in step
    assert "TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}" in step
    assert "JOB_STATUS: ${{ job.status }}" in step
    assert label in step
    assert 'run: python3 run_failure_alert.py --label "$ALERT_LABEL"' in step   # label via env, not shell source
    assert text.count("run_failure_alert.py") == 1


def test_cancelled_jobs_say_so():
    """job.status = cancelled (manual cancel or timeout) is not reported as a failure."""
    text = alert.message(dict(ENV, JOB_STATUS="cancelled"), "scan", NOW)
    assert text.startswith("CANCELLED or TIMED OUT: Scheduled evidence collector (scan)")
    assert alert.message(dict(ENV, JOB_STATUS="failure"), "scan", NOW) == TEXT


def test_every_real_workflow_name_and_label_fits_the_message():
    """Renaming a workflow or adding a mode must not silently turn every alert into FIELDS_INVALID."""
    collector = (ROOT / ".github/workflows/scheduled-collector.yml").read_text()
    archive = (ROOT / ".github/workflows/drive-archive.yml").read_text()
    test = (ROOT / ".github/workflows/alert-test.yml").read_text()
    modes = re.search(r"options: \[([^\]]+)\]", collector)[1].split(", ")
    archive_modes = re.search(r"options: \[(preview[^\]]+)\]", archive)[1].split(", ")
    cases = [(collector, mode) for mode in modes] + [(test, "test")] + [
        (archive, "archive-" + mode) for mode in archive_modes + ["schedule", "workflow_dispatch"]]
    assert len(modes) >= 6 and len(archive_modes) >= 3
    for text, label in cases:
        workflow = re.search(r"^name: (.+)$", text, re.MULTILINE)[1].strip()
        assert alert.message(dict(ENV, GITHUB_WORKFLOW=workflow), label, NOW)


def test_alert_runs_without_third_party_packages():
    """The alert must work when pip install failed: its import chain is standard library only."""
    code = ("import sys; sys.path.insert(0, %r); import run_failure_alert; "
            "sys.exit(any('site-packages' in (getattr(m, '__file__', '') or '') for m in list(sys.modules.values())))"
            % str(ROOT))
    done = subprocess.run([sys.executable, "-I", "-S", "-c", code], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr


def test_alert_test_workflow_is_manual_and_checks_the_result():
    """The test workflow is manual, read-only and fails unless the alert was sent."""
    text = (ROOT / ".github/workflows/alert-test.yml").read_text()
    assert "  workflow_dispatch:" in text and "schedule:" not in text
    assert "contents: read" in text and "persist-credentials: false" in text
    assert '[ "$result" = "RUN_ALERT_SENT" ]' in text
