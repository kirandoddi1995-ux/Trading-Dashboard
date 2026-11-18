"""On-time run watchdog: Supabase Cron -> Edge Function -> run-watchdog.yml.

Checks that the SQL, the Edge Function target and the workflow's own schedule agree, and
that the SQL dispatch wiring is byte-equal to the live archive job except for its body.
No network, no database, no credentials.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import run_watchdog
from test_archive_on_time_dispatch import _http_post_without_body

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase/run-watchdog-cron.sql").read_text(encoding="utf-8")
ARCHIVE_SQL = (ROOT / "supabase/archive-nightly-cron.sql").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github/workflows/run-watchdog.yml").read_text(encoding="utf-8")
EDGE = (ROOT / "supabase/functions/dispatch-scheduled-collector/index.ts").read_text(encoding="utf-8")
JOBS = {"run-watchdog-1130-ist": "0 6 * * 1-5", "run-watchdog-1600-ist": "30 10 * * 1-5",
        "run-watchdog-0400-ist": "30 22 * * *"}


def test_sql_jobs_match_the_watchdog_slots_and_workflow_schedule():
    """One Cron job per watchdog slot, each at exactly the GitHub fallback's cron."""
    scheduled = dict(re.findall(r"select cron\.schedule\(\n  '([^']+)',\n  '([^']+)',", SQL))
    assert scheduled == JOBS
    assert set(JOBS.values()) == set(run_watchdog.WATCHES)
    for cron in JOBS.values():
        assert f"- cron: '{cron}'" in WORKFLOW
    assert "  workflow_dispatch:\n" in WORKFLOW
    # Re-run safety: every job it creates is unscheduled first.
    unschedule = re.search(r"where jobname in \(([^)]*)\);", SQL).group(1)
    assert sorted(re.findall(r"'([^']+)'", unschedule)) == sorted(JOBS)
    assert SQL.index("cron.unschedule(") < SQL.index("cron.schedule(")


TARGETS = {"run-watchdog-1130-ist": "run-watchdog-1130", "run-watchdog-1600-ist": "run-watchdog-1600",
           "run-watchdog-0400-ist": "run-watchdog-0400"}


def test_each_job_sends_its_own_target_and_the_target_carries_that_jobs_slot():
    """Job -> target -> Edge Function slot input == the job's own cron, so each run checks one slot."""
    jobs = re.findall(r"select cron\.schedule\(\n  '([^']+)',\n  '([^']+)',.*?body := '(\{.*?\})'::jsonb", SQL, re.S)
    assert len(jobs) == 3
    for name, cron, raw in jobs:
        body = json.loads(raw)
        assert set(body) == {"target", "schedule"} and body["target"] == TARGETS[name]
        line = (f'"{body["target"]}": Object.freeze({{ workflow: "run-watchdog.yml", '
                f'inputs: Object.freeze({{ slot: "{cron}" }}) }}),')
        assert line in EDGE


def test_workflow_accepts_the_slot_input_and_uses_it():
    """Optional string input `slot` only (no required input: a dispatch would 422), wired to WATCHDOG_SCHEDULE."""
    dispatch = WORKFLOW.split("  workflow_dispatch:\n", 1)[1].split("\npermissions:", 1)[0]
    assert re.findall(r"^      (\w+):$", dispatch, re.M) == ["slot"]
    assert "required: false" in dispatch and "required: true" not in dispatch
    assert "WATCHDOG_SCHEDULE: ${{ github.event.schedule || inputs.slot }}" in WORKFLOW
    assert "group: run-watchdog-${{ github.event.schedule || inputs.slot || 'all' }}" in WORKFLOW


def test_sql_prechecks_vault_secrets_before_changing_anything():
    """Step 0 raises, changing nothing, when a Vault secret the jobs read is missing."""
    precheck = SQL.index("raise exception 'collector_dispatch_* Vault secrets missing")
    assert precheck < SQL.index("cron.unschedule(") < SQL.index("cron.schedule(")


def test_sql_dispatch_wiring_is_the_archive_jobs_except_the_body():
    """URL, function path, header, Vault names, timeout: byte-equal to the live archive job."""
    archive = _http_post_without_body(ARCHIVE_SQL, '"target":"archive-nightly"')
    for label in ("11:30 IST", "16:00 IST", "04:00 IST"):
        assert _http_post_without_body(SQL, f'"schedule":"{label}') == archive
    assert not re.search(r"gh[pousr]_|github_pat_|eyJ", SQL)
