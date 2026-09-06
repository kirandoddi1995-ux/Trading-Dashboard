"""Single-source presentation and capital policy for live evidence maturity."""
from __future__ import annotations

import math
from typing import Any, Mapping

from live_evidence import EvidenceTier


HARD_SAFE_STATES = {"NO_TRADE", "READ_ONLY", "EMERGENCY_STOP"}


def evidence_tier_decision(governance: Mapping[str, Any]) -> dict[str, Any]:
    contract = dict(governance.get("evidence_contract") or {})
    try:
        tier = EvidenceTier(str(contract.get("tier") or "OBSERVATION").upper())
    except ValueError:
        tier = EvidenceTier.OBSERVATION
    resilience = dict(governance.get("resilience") or {})
    safety_state = str(resilience.get("state") or "NO_TRADE").upper()
    gate_allows = governance.get("allow_trade") is True
    correctness = dict(governance.get("predictive_correctness") or {})

    if safety_state in HARD_SAFE_STATES:
        action, reason = "No Trade", f"Safety state is {safety_state}"
    elif tier is EvidenceTier.DEVELOPING or safety_state == "DEGRADED":
        action, reason = "Watch", "Developing/degraded evidence is paper-only"
    elif tier.permits_production_probability and gate_allows and safety_state == "NORMAL":
        action, reason = "Buy", "Validated evidence and every production gate passed"
    else:
        action, reason = "No Trade", "Production evidence or a required gate is unavailable"

    allocation = dict(governance.get("allocation") or {})
    raw_weight = allocation.get("weight")
    try:
        weight = float(raw_weight)
    except (TypeError, ValueError, OverflowError):
        weight = 0.0
    if action != "Buy" or allocation.get("status") != "PASS" or not math.isfinite(weight):
        weight = 0.0

    calibration = dict(governance.get("calibration") or {})
    probability = calibration.get("probability") if tier.permits_production_probability else None
    claim = correctness.get("claim") if correctness else "99% not established"
    if correctness.get("established") is not True:
        claim = "99% not established"
    return {
        "tier": tier.value,
        "action": action,
        "paper_only": action == "Watch",
        "production_order_allowed": action == "Buy",
        "kelly_weight": weight,
        "probability": probability,
        "predictive_correctness_claim": claim,
        "reason": reason,
        "missing_or_blocking": list(governance.get("blocking_reasons") or contract.get("compatibility_failures") or []),
    }
