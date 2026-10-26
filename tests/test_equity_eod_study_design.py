import pytest

from equity_eod_study_design import design


def plan(**changes):
    args = dict(start="2022-01-01", end="2024-12-31", rule_sha256="a" * 64,
                universe_basis="FIXED_DISCLOSED_INSTRUMENT_SET", prior_exposure="UNKNOWN",
                horizon_sessions=5, round_trip_cost_scenarios_bps=(30., 60.))
    return design(**(args | changes))


def test_design_is_reproducible_bounded_and_never_grants_eligibility():
    result = plan()
    assert result == plan()
    assert result["label"] == "RETROSPECTIVE_DEVELOPMENT_NOT_UNTOUCHED_OOS"
    for key in ("data_admission_authorised", "training_eligible", "promotion_authorised", "performance_claim_verified"):
        assert result[key] is False
    assert result["network_calls"] == result["source_data_reads"] == 0
    assert plan(horizon_sessions=10)["design_sha256"] != result["design_sha256"]


@pytest.mark.parametrize("changes", [
    {"end": "2025-01-01"}, {"start": "2021-12-31"}, {"start": "2024-12-31", "end": "2022-01-01"},
    {"rule_sha256": "unfrozen"}, {"universe_basis": "TODAYS_WINNERS"},
    {"prior_exposure": "OOS_VERIFIED"}, {"horizon_sessions": True}, {"horizon_sessions": 0},
    {"round_trip_cost_scenarios_bps": (0., float("nan"))},
    {"round_trip_cost_scenarios_bps": (30., 30.)}, {"round_trip_cost_scenarios_bps": (60., 30.)},
    {"round_trip_cost_scenarios_bps": (True, 30.)},
])
def test_invalid_or_sealed_design_is_rejected_without_io(changes):
    with pytest.raises(ValueError):
        plan(**changes)


def test_declared_unseen_never_becomes_verified_oos():
    assert plan(prior_exposure="DECLARED_UNSEEN_NOT_VERIFIED")["label"].startswith("RETROSPECTIVE")
