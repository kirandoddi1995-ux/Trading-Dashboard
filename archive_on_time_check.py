"""Fallback check for the late GitHub nightly-archive schedule.

ARCHIVE_ON_TIME_DISPATCH_2026-11-10.md: Supabase Cron dispatches drive-archive.yml
with mode=nightly on time (20:15 UTC). GitHub still fires the workflow's own
20:15 UTC schedule, but 3.5-6.5 h late. That late run runs this module as its own
step (`python archive_on_time_check.py`, the only step that holds the Actions token)
and the archive step skips when the step wrote `skip=true`.

"Already did the retention" means all of:
  * a workflow_dispatch run of drive-archive.yml on main with status success,
  * titled ON_TIME_TITLE (the workflow's run-name for mode=nightly only),
  * created within WINDOW before now,
  * whose `archive` job concluded success.
A held on-time run (owner gates off: only the no-I/O `scheduled-hold` job runs and
`archive` is skipped) is a successful run too, so the job check is what keeps it
from counting. Inside the archive job a nightly dispatch never exits 0 without
running the retention (the launcher fails on a gate mismatch).

Everything fails open. A missing token, an API error or a malformed answer returns
False, so the fallback runs. The nightly run is idempotent (a second pass re-proves
and deletes only what is still past retention), so a wrong "not done" costs runner
time, never data. A failed check also prints a GitHub warning annotation, so a check
that breaks every night is visible on the run page.

The only I/O is read-only GitHub API GETs. No database, Drive or archive imports.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import urllib.request
from typing import Any, Callable, Mapping

ON_TIME_TITLE = "Nightly archive (on-time dispatch)"
WORKFLOW_FILE = "drive-archive.yml"
BRANCH = "main"  # the Edge Function always dispatches ref main
ARCHIVE_JOB = "archive"
# The late schedule starts 3.5-6.5 h after the on-time run, and the previous
# night's on-time run is at least 24 h old. 20 h separates them with margin.
WINDOW = dt.timedelta(hours=20)
RUNS_PER_PAGE = 20
API_VERSION = "2022-11-28"
REQUEST_TIMEOUT_SECONDS = 20


def _get_json(url: str, token: str, urlopen: Callable[..., Any]) -> dict:
    """GET one GitHub API URL and return its JSON object ({} for any other JSON shape)."""
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
    })
    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        body = json.load(response)
    return body if isinstance(body, dict) else {}


def _created_at(run: dict) -> dt.datetime | None:
    """The run's timezone-aware creation time, or None when absent or malformed."""
    try:
        stamp = dt.datetime.fromisoformat(str(run["created_at"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        return None
    return stamp if stamp.tzinfo is not None else None


def _is_recent_on_time_run(run: object, cutoff: dt.datetime, own_run_id: str | None) -> bool:
    """True for a run entry titled as the on-time dispatch, created at or after cutoff, not this run."""
    if not isinstance(run, dict) or run.get("display_title") != ON_TIME_TITLE or run.get("head_branch") != BRANCH:
        return False
    created = _created_at(run)
    # The id check is defence in depth: this schedule run never appears in a
    # workflow_dispatch listing.
    return created is not None and created >= cutoff and str(run.get("id")) != own_run_id


def _archive_job_succeeded(api: str, run: dict, token: str, urlopen: Callable[..., Any]) -> bool:
    """True when the run's `archive` job (not the hold job) concluded success."""
    jobs = _get_json(f"{api}/runs/{int(run['id'])}/jobs", token, urlopen).get("jobs") or []
    return any(
        isinstance(job, dict) and job.get("name") == ARCHIVE_JOB and job.get("conclusion") == "success"
        for job in jobs
    )


def on_time_nightly_succeeded(
    environ: Mapping[str, str],
    token: str,
    *,
    urlopen: Callable[..., Any] | None = None,
    now: dt.datetime | None = None,
    emit: Callable[[str], None] = print,
) -> bool:
    """True if tonight's on-time nightly dispatch already ran its archive job to success.

    `environ` supplies GITHUB_REPOSITORY and GITHUB_RUN_ID. `token` needs Actions
    read only. Prints exactly one JSON status line: SKIPPED, NOT_FOUND or
    CHECK_FAILED. Never raises: any problem answers False (run the fallback).
    """
    repository = environ.get("GITHUB_REPOSITORY")
    if not token or not repository:
        emit(json.dumps({"status": "ON_TIME_RUN_CHECK_FAILED", "error": "MissingTokenOrRepository"}))
        return False
    urlopen = urlopen or urllib.request.urlopen
    api = f"https://api.github.com/repos/{repository}/actions"
    cutoff = (now or dt.datetime.now(dt.timezone.utc)) - WINDOW
    listing = (f"{api}/workflows/{WORKFLOW_FILE}/runs"
               f"?event=workflow_dispatch&status=success&branch={BRANCH}&per_page={RUNS_PER_PAGE}")
    try:
        runs = _get_json(listing, token, urlopen).get("workflow_runs") or []
        for run in runs:
            if _is_recent_on_time_run(run, cutoff, environ.get("GITHUB_RUN_ID")) and \
                    _archive_job_succeeded(api, run, token, urlopen):
                emit(json.dumps({"status": "ARCHIVE_SCHEDULE_SKIPPED_ON_TIME_RUN_SUCCEEDED",
                                 "on_time_run_id": run.get("id"), "source_deletes": 0}))
                return True
    except Exception as exc:  # fail open: the check must never cancel the night
        emit(json.dumps({"status": "ON_TIME_RUN_CHECK_FAILED", "error": type(exc).__name__}))
        return False
    emit(json.dumps({"status": "ON_TIME_RUN_NOT_FOUND", "source_deletes": 0}))
    return False


def main(environ: Mapping[str, str] | None = None, **check_options: Any) -> int:
    """Workflow step: decide, then append `skip=true|false` to $GITHUB_OUTPUT. Exit 0.

    The token comes from ACTIONS_READ_TOKEN (this step's env only). The step also
    has `continue-on-error: true`, so even a crash here leaves `skip` unset and the
    archive step runs. A failure here can never stop the late run's retention.
    """
    environ = os.environ if environ is None else environ
    emit = check_options.pop("emit", print)
    lines: list[str] = []

    def report(line: str) -> None:
        """Pass the status line on and remember it."""
        lines.append(line)
        emit(line)

    skip = on_time_nightly_succeeded(environ, environ.get("ACTIONS_READ_TOKEN", ""), emit=report, **check_options)
    if any('"ON_TIME_RUN_CHECK_FAILED"' in line for line in lines):
        emit("::warning title=On-time archive check failed::The late schedule could not confirm tonight's "
             "on-time run, so it runs the retention itself (see the status line above).")
    output = environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"skip={'true' if skip else 'false'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
