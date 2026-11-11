"""On-time nightly archive: Supabase Cron -> Edge Function -> drive-archive.yml mode=nightly.

GitHub delivered the 20:15 UTC archive schedule 3.5-6.5 h late (10 Nov 2026: 02:45 UTC,
after the 21:15 UTC VACUUM). The same Supabase dispatcher that starts the collector on
time now also sends a fixed `archive-nightly` target. The late GitHub schedule stays as
a fallback and skips itself when the on-time run's archive job already succeeded
(archive_on_time_check.py; its own tests are in test_archive_on_time_check.py).

Covers: the dispatcher's own TypeScript tests (run with node, otherwise never run in CI);
that SQL, Edge Function, workflow and check module agree on names and wiring; the
job-level owner gates over every event/mode/variable combination; and the launcher's
decisions. No network, no database, no credentials.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

import archive_maintenance as maintenance
import archive_on_time_check as check
from test_archive_commissioning_hold import _launcher

ROOT = Path(__file__).resolve().parents[1]
FUNCTION_DIR = ROOT / "supabase/functions/dispatch-scheduled-collector"
SQL = (ROOT / "supabase/archive-nightly-cron.sql").read_text(encoding="utf-8")
COLLECTOR_SQL = (ROOT / "supabase/scheduled-collector-cron.sql").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github/workflows/drive-archive.yml").read_text(encoding="utf-8")
EDGE = (FUNCTION_DIR / "index.ts").read_text(encoding="utf-8")
NIGHTLY_ARGS = ["--mode", "delete", "--table", "growing", "--max-batches", "100"]
MANUAL_MODES = ["preview", "export", "restore-check", "delete", "prune-preserved"]


def _node_flags():
    """Type-stripping flag for this node (built in from 23.6, flagged in 22.x)."""
    version = subprocess.run(["node", "--version"], capture_output=True, text=True, check=True).stdout
    major, minor = (int(part) for part in version.strip().lstrip("v").split(".")[:2])
    return [] if (major, minor) >= (23, 6) else ["--experimental-strip-types"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_dispatcher_typescript_tests_pass():
    """handler.test.ts (collector modes, archive target, pinned target set) passes on this node."""
    # TAP reporter pinned: Node 23+ defaults to the "spec" reporter (CI runs Node 24), 22 to TAP.
    result = subprocess.run(
        ["node", *_node_flags(), "--no-warnings", "--test", "--test-reporter=tap", "handler.test.ts"],
        cwd=FUNCTION_DIR, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-2000:]
    summary = dict(re.findall(r"^# (pass|fail) (\d+)$", result.stdout, re.M))
    assert summary == {"pass": "10", "fail": "0"}, result.stdout[-2000:]


def _http_post_without_body(sql, body_marker):
    """The net.http_post(...) call that carries `body_marker`, with its body line removed."""
    calls = re.findall(r"select net\.http_post\(.*?\n    \);", sql, re.S)
    [call] = [call for call in calls if body_marker in call]
    return re.sub(r"\n      body := [^\n]*", "", call)


def test_sql_edge_function_and_workflow_agree():
    """Same target name, workflow, input, slot; VACUUM after the archive window."""
    body = json.loads(re.search(r"body := '(\{.*?\})'::jsonb", SQL).group(1))
    assert body == {"target": "archive-nightly", "schedule": "01:45 IST daily"}
    target = re.search(r'"archive-nightly": Object\.freeze\(\{ workflow: "([^"]+)", '
                       r'inputs: Object\.freeze\(\{ mode: "([^"]+)" \}\) \}\)', EDGE)
    assert target.groups() == (check.WORKFLOW_FILE, "nightly")
    assert "options: [preview, export, restore-check, delete, prune-preserved, nightly]" in WORKFLOW
    assert re.search(r"'archive-nightly-0145-ist',\s*'15 20 \* \* \*'", SQL)
    assert "- cron: '15 20 * * *'" in WORKFLOW  # fallback keeps the same slot
    assert re.search(r"jobname = 'nightly-vacuum-growing-tables'\),\s*schedule := '45 22 \* \* \*'", SQL)
    # Secret names only: no token-shaped value anywhere in the SQL.
    assert not re.search(r"gh[pousr]_|github_pat_|eyJ", SQL)


def test_sql_dispatch_wiring_is_the_collectors_except_the_body():
    """URL, function path, header name, Vault names and timeout: byte-equal to the live collector jobs."""
    archive = _http_post_without_body(SQL, '"target":"archive-nightly"')
    collector = _http_post_without_body(COLLECTOR_SQL, '"mode":"scan","schedule":"10:07 IST')
    assert archive == collector
    assert "/functions/v1/dispatch-scheduled-collector" in archive and "'x-dispatch-secret'" in archive


def test_sql_checks_the_vacuum_job_before_changing_anything():
    """Step 0 raises (changing nothing) when the hand-made VACUUM job is missing or inactive."""
    precheck = SQL.index("raise exception 'nightly-vacuum-growing-tables missing or inactive")
    assert precheck < SQL.index("select cron.unschedule(") < SQL.index("select cron.schedule(")
    assert precheck < SQL.index("select cron.alter_job(")
    assert (
        "do $precheck$\n"
        "begin\n"
        "  if not exists (select 1 from cron.job where jobname = 'nightly-vacuum-growing-tables' and active) then\n"
        "    raise exception 'nightly-vacuum-growing-tables missing or inactive in cron.job: nothing changed';\n"
        "  end if;\n"
        "end\n"
        "$precheck$;\n") in SQL


RUN_NAME = ("run-name: >-\n"
            "  ${{ (github.event_name == 'workflow_dispatch' && inputs.mode == 'nightly')\n"
            f"  && '{check.ON_TIME_TITLE}' || github.workflow }}}}\n")


def _archive_job():
    """The archive job's YAML text."""
    return _job(check.ARCHIVE_JOB)


def _steps():
    """The archive job's steps, one text block each, in order."""
    return ["      - " + block for block in _archive_job().split("    steps:\n", 1)[1].split("\n      - ")]


def _step(marker):
    """The one archive-job step whose text contains `marker`."""
    [step] = [step for step in _steps() if marker in step]
    return step


def test_run_name_titles_only_the_nightly_dispatch():
    """The title is the only thing that tells the nightly dispatch from a manual run: pinned exactly."""
    assert WORKFLOW.startswith(f"name: Verified Drive archive (nightly restore-proven retention when enabled)\n{RUN_NAME}")
    assert WORKFLOW.count(check.ON_TIME_TITLE) == 1  # only the run-name; the check owns the rest
    condition = "(github.event_name == 'workflow_dispatch' && inputs.mode == 'nightly')"
    for event, mode in EVENTS:
        titled = _evaluate_if(condition, {"event": event, "mode": mode, "enabled": "", "nightly": ""})
        assert titled is (event == "workflow_dispatch" and mode == "nightly"), (event, mode)


def _job(name):
    """One job's YAML text (up to the next job)."""
    return re.split(r"\n  [a-z-]+:\n", WORKFLOW.split(f"\n  {name}:\n", 1)[1], maxsplit=1)[0].rstrip("\n")


def test_jobs_permissions_and_token_scope_match_the_check_module():
    """`archive` is the job id the check looks for; only `on-time-check` can read Actions or holds the token."""
    assert f"\n  {check.ARCHIVE_JOB}:\n    needs: on-time-check  # defined below\n" in WORKFLOW
    assert "\n    name:" not in WORKFLOW  # job names are the job ids the check compares
    assert "    permissions:\n      contents: read\n    steps:" in _job("archive")
    assert "    permissions:\n      contents: read\n      actions: read\n" in _job("on-time-check")
    assert "write" not in WORKFLOW.split("\njobs:\n", 1)[1]


def test_the_actions_token_exists_only_in_the_check_job():
    """One env line, in on-time-check; no GITHUB_TOKEN; no ignored default-variable overrides."""
    assert WORKFLOW.count("ACTIONS_READ_TOKEN") == 1 and "ACTIONS_READ_TOKEN" in _job("on-time-check")
    assert "GITHUB_TOKEN" not in WORKFLOW
    # Default variables cannot be overridden (GitHub ignores it): the check reads the real ones.
    assert "GITHUB_REPOSITORY:" not in WORKFLOW and "GITHUB_RUN_ID:" not in WORKFLOW


def test_the_on_time_check_is_its_own_fail_open_least_privilege_job():
    """Late schedule with both gates on; continue-on-error; 5-minute cap; output read by `archive`."""
    assert _job("on-time-check") == (
        "    # Late schedule only: did tonight's on-time archive job already succeed? Its own job,\n"
        "    # so it alone gets `actions: read` and the token. Fail open: continue-on-error, and\n"
        "    # a failed, timed-out or skipped check leaves `skip` empty, so `archive` still runs.\n"
        "    if: github.event_name == 'schedule' && vars.ARCHIVE_ENABLED == 'true' && vars.ARCHIVE_NIGHTLY_DELETE == 'true'\n"
        "    runs-on: ubuntu-24.04\n"
        "    timeout-minutes: 5\n"
        "    continue-on-error: true\n"
        "    permissions:\n"
        "      contents: read\n"
        "      actions: read\n"
        "    outputs:\n"
        "      skip: ${{ steps.check.outputs.skip }}\n"
        "    steps:\n"
        "      - uses: actions/checkout@v5\n"
        "        with:\n"
        "          persist-credentials: false\n"
        "      - id: check\n"
        "        env:\n"
        "          ACTIONS_READ_TOKEN: ${{ github.token }}\n"
        "        run: python3 archive_on_time_check.py")
    # Without a status function GitHub adds success(): a skipped/failed check would skip archive.
    assert _job_if("archive").endswith(" && !cancelled()")
    order = [next(i for i, step in enumerate(_steps()) if marker in step) for marker in
             ("actions/checkout@v5", "actions/setup-python@v6",
              "pip install -r requirements-archive.txt", "python - <<'PY'")]
    assert order == sorted(order)
    assert "        with:\n          persist-credentials: false" in _step("actions/checkout@v5")


def test_archive_step_reads_each_gate_from_the_right_variable():
    """A missing or misspelled env line would make the launcher disagree with the job-level gates."""
    archive_step = _step("python - <<'PY'")
    for line in ("EVENT_NAME: ${{ github.event_name }}", "ARCHIVE_ENABLED: ${{ vars.ARCHIVE_ENABLED }}",
                 "NIGHTLY_DELETE: ${{ vars.ARCHIVE_NIGHTLY_DELETE }}", "REQUESTED_MODE: ${{ inputs.mode }}",
                 "ON_TIME_SKIP: ${{ needs.on-time-check.outputs.skip }}",
                 "ARCHIVE_DELETE_ENABLED: ${{ vars.ARCHIVE_DELETE_ENABLED }}"):
        assert f"\n          {line}\n" in archive_step, line
    assert "ACTIONS_READ_TOKEN" not in archive_step and "urlopen" not in archive_step


def test_concurrency_and_job_limits_that_the_design_relies_on():
    """One archive run at a time, never cancelled midway: a late schedule waits for the on-time run."""
    assert "\nconcurrency:\n  group: verified-drive-archive\n  cancel-in-progress: false\n" in WORKFLOW
    assert "    timeout-minutes: 180\n" in _archive_job()


def _job_if(job):
    """A job's `if:` expression (one line, or a folded `>-` block) as a single line."""
    section = _job(job) + "\n"
    folded = re.search(r"^    if: >-\n((?:      [^\n]*\n)+)", section, re.M)
    if folded:
        return " ".join(line.strip() for line in folded.group(1).splitlines())
    return re.search(r"^    if: ([^\n]+)$", section, re.M).group(1)


def _evaluate_if(expression, context):
    """Evaluate a GitHub `if:` made only of ==, !=, &&, ||, parentheses, quoted strings and 4 values.

    Like GitHub, string comparison ignores case (values are lower-cased; literals here
    are lower case). An unset `vars.X` is '' and `inputs.mode` on a schedule run is null.
    """
    names = {"github.event_name": "event", "inputs.mode": "mode",
             "vars.ARCHIVE_ENABLED": "enabled", "vars.ARCHIVE_NIGHTLY_DELETE": "nightly"}
    python = expression.replace(" && !cancelled()", "")  # the run is never cancelled here
    for name, variable in names.items():
        python = python.replace(name, variable)
    python = python.replace("&&", " and ").replace("||", " or ")
    leftover = re.sub(r"'[a-z_-]*'|\b(?:event|mode|enabled|nightly|and|or)\b|==|!=|[()\s]", "", python)
    assert leftover == "", f"unsupported expression syntax: {leftover!r}"
    values = {key: value.lower() if isinstance(value, str) else value for key, value in context.items()}
    return bool(eval(python, {"__builtins__": {}}, values))  # noqa: S307 - vetted above


def _expected_jobs(event, mode, enabled, nightly):
    """Which jobs must run: manual modes always archive; nightly runs need both owner gates;
    only the late schedule asks the on-time check."""
    if event == "workflow_dispatch" and mode != "nightly":
        return {"archive"}
    if enabled.lower() != "true":
        return set()
    if nightly.lower() != "true":
        return {"scheduled-hold"}
    return {"on-time-check", "archive"} if event == "schedule" else {"archive"}


EVENTS = [("schedule", None)] + [("workflow_dispatch", mode) for mode in MANUAL_MODES + ["nightly"]]
GATE_VALUES = ["", "true", "false", "True", "TRUE"]


@pytest.mark.parametrize("event, mode", EVENTS)
@pytest.mark.parametrize("enabled", GATE_VALUES)
@pytest.mark.parametrize("nightly", GATE_VALUES)
def test_job_level_gates_run_exactly_the_expected_job(event, mode, enabled, nightly):
    """Held nightly runs never start `archive` (no checkout, no secrets), so they never count."""
    context = {"event": event, "mode": mode, "enabled": enabled, "nightly": nightly}
    ran = {job for job in ("scheduled-hold", "on-time-check", "archive") if _evaluate_if(_job_if(job), context)}
    assert ran == _expected_jobs(event, mode, enabled, nightly)


def _set_env(monkeypatch, values):
    """Set each variable, or remove it when its value is None."""
    for name, value in values.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


def _run(monkeypatch, *, event, mode="", enabled="true", nightly="true", skip=None):
    """Execute the workflow's launcher script; return (exit code, archive main mock)."""
    _, script = _launcher()
    _set_env(monkeypatch, {"EVENT_NAME": event, "REQUESTED_MODE": mode, "ARCHIVE_ENABLED": enabled,
                           "NIGHTLY_DELETE": nightly, "ON_TIME_SKIP": skip,
                           "REQUESTED_TABLE": "evidence_ledger_events", "REQUESTED_MAX_BATCHES": "200"})
    main = Mock(return_value=0)
    monkeypatch.setattr(maintenance, "main", main)
    with pytest.raises(SystemExit) as caught:
        exec(compile(script, "<drive-archive-launcher>", "exec"), {})
    return caught.value.code, main


def test_on_time_dispatch_runs_exactly_the_nightly_retention(monkeypatch):
    """mode=nightly = the schedule's delete/growing/100, other inputs ignored; the skip flag is the schedule's only."""
    code, main = _run(monkeypatch, event="workflow_dispatch", mode="nightly", skip="true")
    assert code == 0
    main.assert_called_once_with(NIGHTLY_ARGS)


STARTED_NIGHTLY = [(event, mode, enabled, nightly)
                   for event, mode in (("schedule", None), ("workflow_dispatch", "nightly"))
                   for enabled in GATE_VALUES for nightly in GATE_VALUES
                   if "archive" in _expected_jobs(event, mode, enabled, nightly)]


@pytest.mark.parametrize("event, mode, enabled, nightly", STARTED_NIGHTLY)
def test_whenever_the_job_level_gate_starts_archive_the_launcher_runs_the_retention(
        monkeypatch, event, mode, enabled, nightly):
    """Both layers agree on every value (GitHub ignores case): a started nightly archive job never
    exits 0 without the retention, so a successful archive job always means it ran."""
    code, main = _run(monkeypatch, event=event, mode=mode or "", enabled=enabled, nightly=nightly)
    assert code == 0
    main.assert_called_once_with(NIGHTLY_ARGS)


@pytest.mark.parametrize("enabled, nightly", [("false", "true"), (None, "true"), ("true", "false"), ("true", None)])
def test_a_nightly_dispatch_with_gates_off_inside_the_archive_job_fails(monkeypatch, capsys, enabled, nightly):
    """Only broken wiring gets here (the job-level gate held it otherwise): red, never counted."""
    code, main = _run(monkeypatch, event="workflow_dispatch", mode="nightly", enabled=enabled, nightly=nightly)
    assert code == 3
    main.assert_not_called()
    assert "NIGHTLY_GATE_MISMATCH" in capsys.readouterr().out


def test_late_schedule_skips_when_the_check_step_said_so(monkeypatch, capsys):
    """No second restore proof and delete pass on the same night."""
    code, main = _run(monkeypatch, event="schedule", skip="true")
    assert code == 0
    main.assert_not_called()
    assert "ARCHIVE_SCHEDULE_SKIPPED_ON_TIME_RUN_SUCCEEDED" in capsys.readouterr().out


@pytest.mark.parametrize("skip", [None, "", "false", "True", "yes"])
def test_late_schedule_runs_unless_the_check_wrote_exactly_skip_true(monkeypatch, skip):
    """Unset (check failed or crashed: continue-on-error), false or anything else: run the retention."""
    code, main = _run(monkeypatch, event="schedule", skip=skip)
    assert code == 0
    main.assert_called_once_with(NIGHTLY_ARGS)


def test_late_schedule_still_holds_without_the_owner_variable(monkeypatch, capsys):
    """The fallback never runs when nightly deletion is off (schedule runs are never counted)."""
    code, main = _run(monkeypatch, event="schedule", nightly=None)
    assert code == 0
    main.assert_not_called()
    assert "ARCHIVE_SCHEDULE_HELD_NO_IO" in capsys.readouterr().out


@pytest.mark.parametrize("mode", MANUAL_MODES)
def test_every_manual_mode_passes_its_own_inputs_never_the_nightly_preset(monkeypatch, mode):
    """No manual mode (read-only or not) can become the nightly delete, or read the skip flag."""
    code, main = _run(monkeypatch, event="workflow_dispatch", mode=mode, skip="true")
    assert code == 0
    [args] = main.call_args.args
    assert args[:4] == ["--mode", mode, "--table", "evidence_ledger_events"]
    assert args != NIGHTLY_ARGS and "growing" not in args
