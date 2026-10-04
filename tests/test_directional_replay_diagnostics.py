from copy import deepcopy

import pytest

from directional_replay_diagnostics import summarize


def fixture():
    return {"mode": "DIRECTIONAL_RESEARCH", "approval_authority": False, "fill_evidence": False,
            "option_pnl": None, "accepted_sessions": 3, "excluded_sessions": [],
            "decisions": [{"session_open": day + "T09:15:00+05:30"}
                          for day in ("2022-01-03", "2022-01-04", "2023-01-02")],
            "variants": {"C": {"episodes": 2, "trades": [
                {"entry_at": "2022-01-03T10:00:00+05:30", "exit_at": "2022-01-03T15:30:00+05:30",
                 "directional_return_pct": value, "mae_pct": -.5, "mfe_pct": .8,
                 "reason": "SESSION_END_CLOSE_REFERENCE"} for value in (1., -1.)]}}}


def test_sessions_not_episodes_are_resampled_and_zero_sessions_included():
    result = summarize(fixture(), repetitions=100)
    variant = result["variants"]["C"]
    assert variant["zero_episode_sessions"] == 2
    assert variant["mean_cluster_ci95_pct"] == [0., 0.]
    assert variant["bootstrap_undefined_draws"] > 0
    assert variant["directional_return_pct"]["mean"] == 0.
    assert variant["exit_reasons"] == {"SESSION_END_CLOSE_REFERENCE": 2}
    assert variant["per_year"]["2023"]["returns"]["count"] == 0
    assert result["approval_authority"] is False
    assert summarize(fixture(), repetitions=100) == result


@pytest.mark.parametrize("year", [2025, 2026])
def test_validation_and_holdout_are_rejected(year):
    report = fixture()
    report["decisions"][0]["session_open"] = f"{year}-01-03T09:15:00+05:30"
    with pytest.raises(ValueError, match="remain frozen"):
        summarize(report, repetitions=100)


@pytest.mark.parametrize("problem", ["nan", "count", "exit_day", "duplicate", "authority",
                                     "exit_before_entry", "unordered_sessions", "holdout_excluded"])
def test_inconsistent_evidence_rejected(problem):
    report = deepcopy(fixture())
    if problem == "nan":
        report["variants"]["C"]["trades"][0]["mae_pct"] = float("nan")
    elif problem == "count":
        report["variants"]["C"]["episodes"] = 3
    elif problem == "exit_day":
        report["variants"]["C"]["trades"][0]["exit_at"] = "2022-01-04T09:15:00+05:30"
    elif problem == "duplicate":
        report["decisions"][1] = report["decisions"][0]
    elif problem == "exit_before_entry":
        report["variants"]["C"]["trades"][0]["exit_at"] = "2022-01-03T09:30:00+05:30"
    elif problem == "unordered_sessions":
        report["decisions"].reverse()
    elif problem == "holdout_excluded":
        report["excluded_sessions"] = [{"open": "2026-01-02T09:15:00+05:30"}]
    else:
        report["approval_authority"] = True
    with pytest.raises(ValueError):
        summarize(report, repetitions=100)


def test_empty_episodes_and_single_session_have_no_invented_ci():
    report = fixture()
    report["variants"]["C"] = {"episodes": 0, "trades": []}
    assert summarize(report, repetitions=100)["variants"]["C"]["mean_cluster_ci95_pct"] is None


def test_cli_reports_hash_without_revealing_input_path(tmp_path, capsys):
    import hashlib
    import json
    from directional_replay_diagnostics import main
    raw = json.dumps(fixture()).encode()
    path = tmp_path / "private-development.json"
    path.write_bytes(raw)
    assert main(["--report", str(path), "--repetitions", "100"]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["source_report_sha256"] == hashlib.sha256(raw).hexdigest()
    assert str(path) not in output
