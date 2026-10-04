from copy import deepcopy
from decimal import Decimal
import hashlib
import json

import pytest

from development_cost_hurdles import HURDLES_PCT, main, screen


def report():
    return {"mode": "DIRECTIONAL_RESEARCH", "approval_authority": False,
            "fill_evidence": False, "option_pnl": None, "accepted_sessions": 2,
            "excluded_sessions": [], "decisions": [
                {"session_open": f"2022-01-{day:02d}T09:15:00+05:30"} for day in (3, 4)],
            "variants": {"C": {"episodes": 2, "trades": [
                {"entry_at": f"2022-01-{day:02d}T10:00:00+05:30",
                 "exit_at": f"2022-01-{day:02d}T15:30:00+05:30",
                 "directional_return_pct": .03, "mae_pct": -.1, "mfe_pct": .1,
                 "reason": "SESSION_END_CLOSE_REFERENCE"} for day in (3, 4)]}}}


def test_constant_hurdles_shift_reference_not_actual_pnl():
    original = report()
    unchanged = deepcopy(original)
    result = screen(original, repetitions=100)
    assert original == unchanged
    cases = result["variants"]["C"]["hypothetical_cost_sensitivity"]
    assert [c["assumed_round_trip_hurdle_pct"] for c in cases] == list(HURDLES_PCT)
    case = next(c for c in cases if c["assumed_round_trip_hurdle_pct"] == "0.05")
    assert Decimal(case["reference_mean_minus_hurdle_pct"]) == Decimal("-0.02")
    assert list(map(Decimal, case["reference_ci95_minus_hurdle_pct"])) == [Decimal("-.02")] * 2
    assert case["screen"] == "UPPER_INTERVAL_BELOW_ASSUMED_HURDLE"
    assert result["futures_pnl"] is None and result["option_pnl"] is None
    for flag in ("approval_authority", "fill_evidence", "cost_policy_commissioned",
                 "historical_costs_applied", "multiple_testing_corrected",
                 "confidence_intervals_are_hard_bounds"):
        assert result[flag] is False
    assert result["current_stt_reference"]["applied_to_historical_trades"] is False


@pytest.mark.parametrize("year", [2025, 2026])
@pytest.mark.parametrize("location", ["accepted", "excluded", "trade"])
def test_frozen_periods_rejected(year, location):
    data = report()
    at = f"{year}-01-03T09:15:00+05:30"
    if location == "accepted":
        data["decisions"][0]["session_open"] = at
    elif location == "excluded":
        data["excluded_sessions"] = [{"open": at}]
    else:
        data["variants"]["C"]["trades"][0]["entry_at"] = at
    with pytest.raises(ValueError, match="remain frozen"):
        screen(data, repetitions=100)


def test_empty_has_no_invented_mean_or_ci():
    data = report()
    data["variants"]["C"] = {"episodes": 0, "trades": []}
    result = screen(data, repetitions=100)
    for case in result["variants"]["C"]["hypothetical_cost_sensitivity"]:
        assert case["reference_mean_minus_hurdle_pct"] is None
        assert case["reference_ci95_minus_hurdle_pct"] is None
        assert case["screen"] == "INSUFFICIENT_EVIDENCE"


def test_exact_boundary_does_not_claim_positive_or_negative_edge():
    data = report()
    for trade in data["variants"]["C"]["trades"]:
        trade["directional_return_pct"] = .02
    case = screen(data, repetitions=100)["variants"]["C"]["hypothetical_cost_sensitivity"][1]
    assert case["screen"] == "INTERVAL_INCLUDES_ASSUMED_HURDLE"


def test_cli_hash_and_no_private_path_or_network(tmp_path, capsys, monkeypatch):
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("Offline screen attempted network access")

    monkeypatch.setattr(socket, "socket", forbidden)
    path = tmp_path / "development.json"
    raw = json.dumps(report()).encode()
    path.write_bytes(raw)
    assert main(["--report", str(path)]) == 0
    output = capsys.readouterr().out
    assert str(path) not in output
    assert json.loads(output)["source_report_sha256"] == hashlib.sha256(raw).hexdigest()
