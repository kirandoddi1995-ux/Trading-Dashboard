"""Synthetic fixtures only; no fixture is a claim about live execution results."""
import copy
import datetime as dt

import pytest

from equity_execution_policy import (
    EVIDENCE_KIND, calibration_uncertainty, equity_execution_ev,
    pretrade_execution, validate_execution_outcomes,
)
from prediction_validation import wilson_score_interval
from resilience_control_plane import canonical_hash


NOW = dt.datetime(2026, 9, 13, 4, 0, tzinfo=dt.timezone.utc)
CONTEXT = dict(strategy_id="equity-fixture", asset_class="equity", target_version="target-fixture",
               horizon_sessions=15, feature_schema_hash="a"*64, instrument="ABC")


def seal(package):
    result = copy.deepcopy(package)
    result.pop("artifact_hash", None)
    result["artifact_hash"] = canonical_hash(result)
    return result


def artifact():
    records = []
    for i in range(500):
        submitted = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=i)
        filled = 0 if i % 5 == 0 else 10
        records.append({
            **CONTEXT,
            "source_kind": "BROKER_EXECUTION", "purpose": "RECONCILED_BROKER_OUTCOME", "simulated": False,
            "broker_order_id": str(i), "broker_record_sha256": "a"*64,
            "submitted_at": submitted.isoformat(), "completed_at": (submitted+dt.timedelta(days=25)).isoformat(),
            "requested_quantity": 10, "filled_quantity": filled,
            "fill_price": 100 if filled else None, "exit_price": 102 if filled else None,
            "cost_per_filled_share": .2 if filled else None, "non_fill_cost": 0 if not filled else None,
            "outcome": "UNFILLED" if not filled else "TIME_EXIT" if i % 10 == 1 else "TARGET",
        })
    return seal({**CONTEXT, "kind": EVIDENCE_KIND, "status": "VALIDATED",
                 "purpose": "VALIDATED_EXECUTION_EVIDENCE", "source_kind": "BROKER_RECONCILED_EXECUTION_OUTCOMES",
                 "created_at": (NOW-dt.timedelta(days=1)).isoformat(), "valid_until": (NOW+dt.timedelta(days=1)).isoformat(),
                 "validation": {"chronological_oos": True, "partial_fills_accounted": True,
                                "broker_records_reconciled": True, "costs_measured": True,
                                "dependence_accounted": True, "report_sha256": "b"*64,
                                "interval_method": "reviewed-date-block-bounds-fixture", "confidence_level": .95},
                 "records": records, "fill_fraction_mean": .8, "fill_fraction_lower": .7,
                 "time_exit_net_return_lower": -.01, "adverse_selection_bps": 2})


def execution(**overrides):
    arguments = dict(plan={"order_type": "LIMIT", "quantity": 1, "limit_price": 100,
                           "ask": 100, "bid": 99.99, "ask_quantity": 1000, "bid_quantity": 1000,
                           "average_daily_value": 1000000},
                     stop=95, target=108, decision_at=NOW, quote_observed_at=NOW,
                     quote_received_at=NOW, costs={"slippage_bps": 2, "impact_bps": 1,
                                                   "statutory_bps": 3, "brokerage_bps": 1})
    arguments.update(overrides)
    return pretrade_execution(**arguments)


def ev(package):
    return equity_execution_ev(evidence=package, context=CONTEXT, decision_at=NOW,
                               calibration={"usable": True, "status": "PASS", "conservative_probability": .65},
                               execution=execution())


def test_new_equity_path_passes_complete_synthetic_validated_evidence():
    result = validate_execution_outcomes(artifact(), context=CONTEXT, decision_at=NOW)
    assert result["usable"]
    assert result["time_exit_probability"] == .125
    assert result["conservative_fill_probability"] == .7
    assert ev(artifact())["status"] == "PASS"


@pytest.mark.parametrize("package", [None, {}, {"purpose": "RESEARCH_OBSERVATION"},
    {"purpose": "LIVE_EQUITY_MANUAL_QUOTE_CHECK", "confirmed": True},
    {"purpose": "USER_REPORTED_BROKER_RESULT", "status": "FILLED", "filled_quantity": 10}])
def test_new_equity_path_rejects_missing_research_and_manual_inputs(package):
    result = ev(package)
    assert result["status"] == "ABSTAIN"
    assert result["expected_value_per_order"] is None


@pytest.mark.parametrize("field", ["fill_fraction_lower", "time_exit_net_return_lower", "adverse_selection_bps"])
def test_new_equity_path_never_defaults_missing_numeric_evidence(field):
    package = artifact()
    del package[field]
    assert ev(seal(package))["expected_value_per_order"] is None


@pytest.mark.parametrize("field,value", [
    ("source_kind", "RESEARCH_OBSERVATION"), ("purpose", "USER_REPORTED_BROKER_RESULT"),
    ("simulated", True), ("fill_price", None), ("cost_per_filled_share", None),
    ("broker_order_id", "0"), ("broker_record_sha256", None),
])
def test_provenance_and_actuals_required_even_inside_resealed_artifact(field, value):
    package = artifact()
    package["records"][1][field] = value
    assert ev(seal(package))["expected_value_per_order"] is None


def test_no_time_exits_is_missing_evidence_not_zero_return():
    package = artifact()
    for record in package["records"]:
        if record["outcome"] == "TIME_EXIT":
            record["outcome"] = "TARGET"
    assert "time-exit" in " ".join(ev(seal(package))["failures"])


def test_context_expiry_integrity_and_real_quantity_mismatch_block():
    for key, value in (("instrument", "OTHER"), ("asset_class", "options"),
                       ("fill_fraction_mean", .99), ("valid_until", "2026-01-01T00:00:00+00:00")):
        package = artifact()
        package[key] = value
        assert ev(seal(package))["status"] == "ABSTAIN"
    package = artifact()
    package["fill_fraction_lower"] = .9
    assert ev(package)["status"] == "ABSTAIN"


@pytest.mark.parametrize("count,expected", [(100, "ABSTAIN"), (1000, "PASS")])
def test_uncertainty_uses_actual_group_counts(count, expected):
    low, high = wilson_score_interval(count//2, count)
    package = {"probability": .7, "probability_interval_low": low, "probability_interval_high": high,
               "reliability": [{"lower_edge": .6, "upper_edge": .8, "count": count,
                                "successes": count//2, "wilson_low": low, "wilson_high": high}]}
    result = calibration_uncertainty(package, {"usable": True, "status": "PASS"})
    assert result["status"] == expected
    package["probability_interval_high"] = low+.01
    assert calibration_uncertainty(package, {"usable": True, "status": "PASS"})["status"] == "ABSTAIN"


def test_depth_staleness_limit_and_costs_are_not_defaulted():
    assert execution()["status"] == "PASS"
    assert execution()["fill_probability"] is None
    plan = execution()["plan"]
    for key, value in (("ask_quantity", None), ("bid_quantity", 1), ("ask", None),
                       ("limit_price", 99), ("limit_price", 107), ("quantity", 30), ("order_type", "MARKET")):
        assert execution(plan={**plan, key: value})["status"] == "ABSTAIN"
    assert execution(quote_observed_at=NOW-dt.timedelta(seconds=6))["status"] == "ABSTAIN"
    assert execution(costs={})["status"] == "ABSTAIN"


@pytest.mark.parametrize("width,expected", [(.149999, "PASS"), (.15, "PASS"), (.150001, "ABSTAIN")])
def test_exact_provisional_width_boundary(monkeypatch, width, expected):
    import equity_execution_policy
    # Boundary arithmetic fixture, not claimed empirical Wilson evidence.
    monkeypatch.setattr(equity_execution_policy, "wilson_score_interval", lambda *a: (.6, .6+width))
    package = {"probability": .7, "probability_interval_low": .6, "probability_interval_high": .6+width,
               "reliability": [{"lower_edge": .6, "upper_edge": .8, "count": 500, "successes": 350,
                                "wilson_low": .6, "wilson_high": .6+width}]}
    assert calibration_uncertainty(package, {"usable": True, "status": "PASS"})["status"] == expected


def test_exit_stress_uses_limit_not_last_and_does_not_double_count_entry_spread():
    result = execution()
    assert result["entry"] == 100
    assert result["exit_stress_bps"] == 4  # twice explicit 2bps estimated slippage
    assert result["stop"] == 94.96
    assert result["target"] == 107.96
    assert result["cost_bps"] == 5  # impact + statutory + brokerage
    assert result["trade_math"]["minimum_ratio"] == 1.30
