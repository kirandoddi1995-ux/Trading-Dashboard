"""Pure, inactive study specification. Does not fetch/read data or grant use."""
from __future__ import annotations

from datetime import date
import hashlib
import json
import math
import re


def design(*, start: str, end: str, rule_sha256: str, universe_basis: str,
           prior_exposure: str, horizon_sessions: int,
           round_trip_cost_scenarios_bps: tuple[float, ...]) -> dict[str, object]:
    """Freeze a bounded design, not a fit, result, data licence or promotion.

    A numeric cost scenario is not a replacement for a dated charge schedule.
    A holdout cannot become unseen merely by assigning a new name to old data.
    """
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if not date(2022, 1, 1) <= first <= last <= date(2024, 12, 31):
        raise ValueError("DEVELOPMENT_DATE_BOUNDARY_REQUIRED")
    if not re.fullmatch("[a-f0-9]{64}", rule_sha256):
        raise ValueError("FROZEN_RULE_HASH_REQUIRED")
    if universe_basis not in {"HISTORICAL_MEMBERSHIP", "FIXED_DISCLOSED_INSTRUMENT_SET"}:
        raise ValueError("UNIVERSE_BASIS_REQUIRED")
    if prior_exposure not in {"KNOWN_USED", "UNKNOWN", "DECLARED_UNSEEN_NOT_VERIFIED"}:
        raise ValueError("PRIOR_EXPOSURE_REQUIRED")
    if type(horizon_sessions) is not int or not 1 <= horizon_sessions <= 60:
        raise ValueError("SESSION_HORIZON_REQUIRED")
    costs = round_trip_cost_scenarios_bps
    if (type(costs) is not tuple or not 2 <= len(costs) <= 8
            or any(type(x) not in (int, float) or not math.isfinite(x) or x < 0 for x in costs)
            or len(set(costs)) != len(costs) or tuple(sorted(costs)) != costs):
        raise ValueError("ORDERED_DISTINCT_COST_STRESSES_REQUIRED")
    spec: dict[str, object] = {
        "version": "equity-eod-development-design-v1", "start": start, "end": end,
        "rule_sha256": rule_sha256, "universe_basis": universe_basis,
        "prior_exposure": prior_exposure, "horizon_sessions": horizon_sessions,
        "cost_scenarios_bps": list(costs),
        "label": "RETROSPECTIVE_DEVELOPMENT_NOT_UNTOUCHED_OOS",
        "baselines": ["CASH_NO_TRADE", "SAME_UNIVERSE_BUY_AND_HOLD", "FROZEN_SIMPLE_RULE"],
        "required_checks": ["SOURCE_RIGHTS_AND_PERMITTED_DERIVATION", "EXACT_INPUT_MANIFEST",
                            "POINT_IN_TIME_UNIVERSE_OR_DISCLOSED_FIXED_SET",
                            "DELISTINGS_SYMBOL_CHANGES_AND_CORPORATE_ACTIONS",
                            "CALENDAR_GAPS_DUPLICATES_BAD_PRICES",
                            "CLOSE_AVAILABILITY_NEXT_SESSION_EXECUTION",
                            "DURATION_PURGING_AND_EMBARGO", "DATED_FEES_AND_LIQUIDITY",
                            "ALL_TRIALS_INCLUDING_FAILURES_REGISTERED"],
        "report_fields": ["COVERAGE_AND_EXCLUSIONS", "NET_RETURN_AND_DRAWDOWN",
                          "TURNOVER_EXPOSURE_AND_ABSTENTION", "BLOCK_UNCERTAINTY_INTERVALS",
                          "BASELINE_DIFFERENCES_AND_COST_SENSITIVITY",
                          "TRADE_LEDGER_AND_UNRESOLVED_MODEL_LIMITS"],
        "data_admission_authorised": False, "training_eligible": False,
        "promotion_authorised": False, "performance_claim_verified": False,
        "network_calls": 0, "source_data_reads": 0,
    }
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {**spec, "design_sha256": hashlib.sha256(canonical).hexdigest()}
