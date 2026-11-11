"""archive_on_time_check: may the late GitHub schedule skip tonight's archive?

Fixed clock, fake urlopen, no network. Skip only on a recent on-time nightly run whose
`archive` job concluded success; everything else (held runs, old runs, malformed or
failed API answers) fails open, i.e. answers False so the fallback runs.
"""
from __future__ import annotations

import datetime as dt
import io
import json

import pytest

import archive_on_time_check as check

NOW = dt.datetime(2026, 11, 11, 2, 45, tzinfo=dt.timezone.utc)
ENV = {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_RUN_ID": "999"}
TOKEN = "read-only-token"
LISTING = ("https://api.github.com/repos/owner/repo/actions/workflows/drive-archive.yml/runs"
           "?event=workflow_dispatch&status=success&branch=main&per_page=20")
NOT_FOUND = {"status": "ON_TIME_RUN_NOT_FOUND", "source_deletes": 0}
ARCHIVE_OK = [{"name": "scheduled-hold", "conclusion": "skipped"}, {"name": "archive", "conclusion": "success"}]


def _stamp(delta):
    """GitHub-style UTC timestamp `delta` before NOW."""
    return (NOW - delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(run_id=7, ago=dt.timedelta(hours=6), **extra):
    """One listing entry for an on-time nightly run created `ago` before NOW."""
    return {"id": run_id, "display_title": check.ON_TIME_TITLE, "head_branch": "main",
            "created_at": _stamp(ago), **extra}


class FakeGitHub:
    """Serves the run listing and per-run jobs; records every request."""

    def __init__(self, listing=None, jobs=None, raw_listing=None, error_on=None):
        """`listing` = workflow_runs; `jobs` = {run id: jobs}; `raw_listing` = whole body."""
        self.listing, self.jobs, self.raw_listing, self.error_on = listing, jobs or {}, raw_listing, error_on
        self.requests = []

    def __call__(self, request, timeout=None):
        """urlopen stand-in: answer one GET, or raise for URLs containing `error_on`."""
        self.requests.append((request.full_url, dict(request.header_items()), timeout))
        if self.error_on and self.error_on in request.full_url:
            raise OSError("network down")
        if request.full_url.endswith("/jobs"):
            run_id = int(request.full_url.rsplit("/", 2)[-2])
            body = {"jobs": self.jobs.get(run_id, [])}
        elif self.raw_listing is not None:
            body = self.raw_listing
        else:
            body = {"workflow_runs": self.listing or []}
        return io.BytesIO(json.dumps(body).encode())


def _ask(github, environ=ENV, token=TOKEN):
    """Call the check with the fixed clock; return (answer, emitted lines)."""
    lines = []
    answer = check.on_time_nightly_succeeded(environ, token, urlopen=github, now=NOW, emit=lines.append)
    return answer, [json.loads(line) for line in lines]


def test_skips_on_a_recent_on_time_run_whose_archive_job_succeeded():
    """The one case that skips: listing, then that run's jobs; token never printed."""
    github = FakeGitHub([_run()], {7: ARCHIVE_OK})
    answer, lines = _ask(github)
    assert answer is True
    assert lines == [{"status": "ARCHIVE_SCHEDULE_SKIPPED_ON_TIME_RUN_SUCCEEDED",
                      "on_time_run_id": 7, "source_deletes": 0}]
    assert [url for url, _, _ in github.requests] == [
        LISTING, "https://api.github.com/repos/owner/repo/actions/runs/7/jobs"]
    assert TOKEN not in json.dumps(lines)


def test_every_request_is_authenticated_versioned_and_bounded():
    """Bearer token, GitHub JSON media type, pinned API version, 20 s timeout on each GET."""
    github = FakeGitHub([_run()], {7: ARCHIVE_OK})
    _ask(github)
    expected = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json",
                "X-github-api-version": "2022-11-28"}
    assert [(headers, timeout) for _, headers, timeout in github.requests] == [(expected, 20)] * 2


@pytest.mark.parametrize("ago, skips", [
    (dt.timedelta(hours=3, minutes=30), True),     # earliest observed late start
    (dt.timedelta(hours=6, minutes=30), True),     # latest observed late start (10 Nov)
    (dt.timedelta(hours=19, minutes=30), True),
    (dt.timedelta(hours=20), True),                # exactly the window edge counts
    (dt.timedelta(hours=20, seconds=1), False),
    (dt.timedelta(hours=20, minutes=30), False),
    (dt.timedelta(hours=24), False),               # last night's on-time run
])
def test_window_is_twenty_hours(ago, skips):
    """Tonight's on-time run counts; the previous night's (>= 24 h) never does."""
    answer, _ = _ask(FakeGitHub([_run(ago=ago)], {7: ARCHIVE_OK}))
    assert answer is skips


@pytest.mark.parametrize("jobs", [
    [],
    [{"name": "scheduled-hold", "conclusion": "success"}, {"name": "archive", "conclusion": "skipped"}],
    [{"name": "archive", "conclusion": "failure"}],
    [{"name": "archive", "conclusion": "cancelled"}],
    [{"name": "archive", "conclusion": "neutral"}],
    [{"name": "archive", "conclusion": None}],
    [{"name": "Archive", "conclusion": "success"}],
    ["archive", None, 7],
])
def test_a_run_without_a_successful_archive_job_never_counts(jobs):
    """Held, failed, cancelled, unfinished or malformed jobs: run the fallback."""
    answer, lines = _ask(FakeGitHub([_run()], {7: jobs}))
    assert answer is False and lines == [NOT_FOUND]


def test_keeps_looking_past_a_held_run_to_a_successful_one():
    """A held run listed first must not hide a later successful one."""
    github = FakeGitHub([_run(run_id=8, ago=dt.timedelta(hours=2)), _run(run_id=7)],
                        {8: [{"name": "archive", "conclusion": "skipped"}], 7: ARCHIVE_OK})
    answer, lines = _ask(github)
    assert answer is True and lines[0]["on_time_run_id"] == 7


@pytest.mark.parametrize("entry", [
    {"id": 7, "display_title": "Verified Drive archive (nightly restore-proven retention when enabled)",
     "head_branch": "main", "created_at": _stamp(dt.timedelta(hours=1))},  # a manual run
    {"id": 7, "display_title": check.ON_TIME_TITLE, "head_branch": "test-branch",
     "created_at": _stamp(dt.timedelta(hours=1))},                         # dispatched from a branch
    {"id": 7, "display_title": check.ON_TIME_TITLE, "created_at": _stamp(dt.timedelta(hours=1))},
    {"id": 7, "display_title": check.ON_TIME_TITLE, "head_branch": "main", "created_at": None},
    {"id": 7, "display_title": check.ON_TIME_TITLE, "head_branch": "main"},
    {"id": 7, "display_title": check.ON_TIME_TITLE, "head_branch": "main",
     "created_at": "2026-11-10T20:15:00"},                                  # naive
    {"id": 7, "display_title": check.ON_TIME_TITLE, "head_branch": "main", "created_at": "yesterday"},
    {"id": 7, "display_title": check.ON_TIME_TITLE, "head_branch": "main", "created_at": 1731269700},
    "not a run",
    None,
    # This schedule run itself: impossible in a workflow_dispatch listing, kept as defence in depth.
    {"id": 999, "display_title": check.ON_TIME_TITLE, "head_branch": "main",
     "created_at": _stamp(dt.timedelta(hours=1))},
])
def test_entries_that_do_not_qualify_are_skipped_without_a_jobs_call(entry):
    """Wrong title or branch, missing/naive/garbage time, non-dict entries, own run id."""
    github = FakeGitHub([entry], {7: ARCHIVE_OK, 999: ARCHIVE_OK})
    answer, lines = _ask(github)
    assert answer is False and lines == [NOT_FOUND]
    assert [url for url, _, _ in github.requests] == [LISTING]


@pytest.mark.parametrize("body", [[], "text", 7, None, {"workflow_runs": None}, {"workflow_runs": {}},
                                  {"workflow_runs": {"a": 1}}, {"other": []}])
def test_unexpected_listing_shapes_answer_false(body):
    """Any JSON shape other than a run list: no skip, no exception."""
    answer, lines = _ask(FakeGitHub(raw_listing=body))
    assert answer is False and lines == [NOT_FOUND]


@pytest.mark.parametrize("github", [
    FakeGitHub(error_on="/runs?"),                                    # listing fails
    FakeGitHub([_run()], {7: ARCHIVE_OK}, error_on="/jobs"),          # jobs call fails
    FakeGitHub(raw_listing={"workflow_runs": 7}),                     # not iterable
    FakeGitHub([_run(run_id="seven")]),                               # id not an integer
    FakeGitHub([{"display_title": check.ON_TIME_TITLE, "head_branch": "main",
                 "created_at": _stamp(dt.timedelta(hours=1))}]),           # no id
])
def test_any_failure_fails_open_and_says_so(github):
    """The check never raises and never cancels the night; it reports the failure type."""
    answer, lines = _ask(github)
    assert answer is False
    assert [line["status"] for line in lines] == ["ON_TIME_RUN_CHECK_FAILED"]
    assert TOKEN not in json.dumps(lines)


def test_invalid_json_fails_open():
    """A non-JSON body (proxy error page) is a failed check, not a crash."""
    def urlopen(request, timeout=None):
        """Return an HTML error page."""
        return io.BytesIO(b"<html>502</html>")
    lines = []
    assert check.on_time_nightly_succeeded(ENV, TOKEN, urlopen=urlopen, now=NOW, emit=lines.append) is False
    assert json.loads(lines[0]) == {"status": "ON_TIME_RUN_CHECK_FAILED", "error": "JSONDecodeError"}


@pytest.mark.parametrize("environ, token", [(ENV, ""), ({"GITHUB_RUN_ID": "999"}, TOKEN), ({}, "")])
def test_no_token_or_repository_means_no_call(environ, token):
    """Without both, answer False at once (run the fallback), say why, and touch nothing."""
    github = FakeGitHub([_run()], {7: ARCHIVE_OK})
    answer, lines = _ask(github, environ=environ, token=token)
    assert answer is False and github.requests == []
    assert lines == [{"status": "ON_TIME_RUN_CHECK_FAILED", "error": "MissingTokenOrRepository"}]


def test_default_clock_and_urlopen_are_used_when_not_injected(monkeypatch):
    """The workflow calls it with (os.environ, token) only: real clock, urllib.request.urlopen."""
    created = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    github = FakeGitHub([{"id": 7, "display_title": check.ON_TIME_TITLE, "head_branch": "main",
                          "created_at": created}], {7: ARCHIVE_OK})
    monkeypatch.setattr(check.urllib.request, "urlopen", github)
    assert check.on_time_nightly_succeeded(ENV, TOKEN, emit=lambda line: None) is True
    assert len(github.requests) == 2


def test_a_numeric_string_run_id_is_used_as_an_integer():
    """GitHub ids are integers; a string id is converted, never pasted into the URL as given."""
    github = FakeGitHub([_run(run_id="07")], {7: ARCHIVE_OK})
    answer, _ = _ask(github)
    assert answer is True and github.requests[1][0].endswith("/actions/runs/7/jobs")


@pytest.mark.parametrize("found, written", [(True, "skip=true\n"), (False, "skip=false\n")])
def test_cli_appends_the_decision_to_github_output_and_exits_zero(tmp_path, found, written):
    """The workflow step: token from ACTIONS_READ_TOKEN, decision appended to $GITHUB_OUTPUT."""
    output = tmp_path / "github_output"
    output.write_text("earlier=1\n")
    github = FakeGitHub([_run()], {7: ARCHIVE_OK if found else []})
    lines = []
    environ = {**ENV, "ACTIONS_READ_TOKEN": TOKEN, "GITHUB_OUTPUT": str(output)}
    assert check.main(environ, urlopen=github, now=NOW, emit=lines.append) == 0
    assert output.read_text() == "earlier=1\n" + written
    assert github.requests[0][1]["Authorization"] == f"Bearer {TOKEN}"


def test_cli_without_output_file_or_token_still_exits_zero():
    """No $GITHUB_OUTPUT (local run) and no token: report, write nothing, exit 0."""
    lines = []
    assert check.main({"GITHUB_REPOSITORY": "owner/repo"}, urlopen=FakeGitHub(), now=NOW, emit=lines.append) == 0
    assert json.loads(lines[0])["status"] == "ON_TIME_RUN_CHECK_FAILED"
    assert lines[1].startswith("::warning title=On-time archive check failed::") and len(lines) == 2


@pytest.mark.parametrize("jobs, statuses", [
    (ARCHIVE_OK, ["ARCHIVE_SCHEDULE_SKIPPED_ON_TIME_RUN_SUCCEEDED"]),
    ([], ["ON_TIME_RUN_NOT_FOUND"]),
])
def test_cli_warns_only_when_the_check_failed(jobs, statuses):
    """SKIPPED and NOT_FOUND are normal answers: one status line, no annotation."""
    lines = []
    environ = {**ENV, "ACTIONS_READ_TOKEN": TOKEN}
    assert check.main(environ, urlopen=FakeGitHub([_run()], {7: jobs}), now=NOW, emit=lines.append) == 0
    assert [json.loads(line)["status"] for line in lines] == statuses


def test_cli_runs_as_a_script_with_the_real_environment(tmp_path, monkeypatch):
    """`python archive_on_time_check.py` (the step's command) reads os.environ; no token: no network."""
    import runpy
    output = tmp_path / "github_output"
    monkeypatch.delenv("ACTIONS_READ_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    with pytest.raises(SystemExit) as caught:
        runpy.run_path(check.__file__, run_name="__main__")
    assert caught.value.code == 0 and output.read_text() == "skip=false\n"
