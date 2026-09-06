import math

from evidence_tiers import evidence_tier_decision


def governance(tier, *, state="NORMAL", allowed=False, allocation=None, correctness=None):
    return {
        "allow_trade": allowed,
        "evidence_contract": {"tier": tier, "compatibility_failures": ["missing"]},
        "resilience": {"state": state},
        "allocation": allocation or {"status": "UNAVAILABLE", "weight": 0},
        "calibration": {"probability": .73},
        "predictive_correctness": correctness or {"established": False, "claim": "99% not established"},
        "blocking_reasons": [] if allowed else ["missing"],
    }


def test_developing_evidence_is_watch_paper_only_and_never_gets_kelly():
    result = evidence_tier_decision(governance(
        "DEVELOPING", allowed=True, allocation={"status": "PASS", "weight": .20}
    ))
    assert result["action"] == "Watch"
    assert result["paper_only"]
    assert result["kelly_weight"] == 0
    assert result["probability"] is None


def test_validated_evidence_is_actionable_only_in_normal_state_with_all_gates():
    result = evidence_tier_decision(governance(
        "VALIDATED", allowed=True, allocation={"status": "PASS", "weight": .02}
    ))
    assert result["action"] == "Buy"
    assert result["production_order_allowed"]
    assert result["kelly_weight"] == .02
    assert result["probability"] == .73


def test_degraded_and_hard_safe_states_remove_production_allocation():
    degraded = evidence_tier_decision(governance(
        "VALIDATED", state="DEGRADED", allowed=True,
        allocation={"status": "PASS", "weight": .02},
    ))
    emergency = evidence_tier_decision(governance(
        "ESTABLISHED_99", state="EMERGENCY_STOP", allowed=True,
        allocation={"status": "PASS", "weight": float("nan")},
    ))
    assert degraded["action"] == "Watch" and degraded["kelly_weight"] == 0
    assert emergency["action"] == "No Trade" and emergency["kelly_weight"] == 0
    assert math.isfinite(emergency["kelly_weight"])


def test_99_percent_claim_is_never_inferred_from_tier_alone():
    result = evidence_tier_decision(governance("ESTABLISHED_99", allowed=True))
    assert result["predictive_correctness_claim"] == "99% not established"
