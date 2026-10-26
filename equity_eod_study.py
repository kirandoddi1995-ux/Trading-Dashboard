"""Inactive equity report rehearsal using the existing, unchanged replay engine.

No file loading, provider connection, live scanner invocation, fitting or orders.
The generated prices are arithmetic fixtures, never a development dataset.
"""
from __future__ import annotations

from datetime import timedelta, timezone
import hashlib
import json
from typing import Any

import pandas as pd

from equity_eod_study_design import design
from event_backtest import run_long_bracket_backtest

COSTS = (30., 60., 100.)
SCENARIOS = (
    ("Adverse opening gap", 90., 96., 89., 94.),
    ("Target opening then reversal", 115., 116., 90., 100.),
    ("Both levels touched after inside open", 100., 112., 94., 100.),
    ("Opening exactly at stop", 95., 112., 94., 100.),
)
AUTHORITY_FLAGS = ("data_admission_authorised", "training_eligible", "promotion_authorised",
                   "performance_claim_verified", "fill_evidence")


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode("utf-8")).hexdigest()


def readiness() -> dict[str, object]:
    """Cheap, fixed facts only; never discover inputs or check credentials."""
    return {"status": "REAL_STUDY_NOT_RUN", "source": "NO_ADMITTED_MARKET_DATA",
            "requirements": ["Permitted private data use and exact 2022–2024 source manifest",
                             "Frozen cohort and historical-membership or survivorship disclosure",
                             "Corporate actions, calendar, missing-data and executable-price checks",
                             "Dated fees, liquidity assumptions, baselines and full trial accounting"],
            **{flag: False for flag in AUTHORITY_FLAGS},
            "network_calls": 0, "market_data_reads": 0}


def rehearsal() -> dict[str, Any]:
    """Run four fixed synthetic execution examples at three scenario cost levels.

    This is not a scanner strategy trial or a market accuracy result. There is
    exactly one predeclared entry in each artificial three-bar example.
    """
    recipe = {"version": "equity-eod-execution-rehearsal-v1", "costs_bps": list(COSTS),
              "scenarios": [list(row) for row in SCENARIOS], "entry": 100., "stop": 95., "target": 110.,
              "signal": "ONE_SYNTHETIC_ENTRY_NOT_SCANNER_LOGIC"}
    specification = design(start="2022-01-03", end="2022-01-05", rule_sha256=fingerprint(recipe),
                           universe_basis="FIXED_DISCLOSED_INSTRUMENT_SET", prior_exposure="KNOWN_USED",
                           horizon_sessions=3, round_trip_cost_scenarios_bps=COSTS)
    rows = []
    for name, opening, high, low, close in SCENARIOS:
        bars = pd.DataFrame({"Open": [100., 100., opening], "High": [101., 102., high],
                             "Low": [99., 99., low], "Close": [100., 101., close]},
                            index=pd.date_range("2022-01-03", periods=3,
                                                tz=timezone(timedelta(hours=5, minutes=30))))
        for cost in COSTS:
            result = run_long_bracket_backtest(
                bars, signal=lambda history: len(history) == 1,
                levels=lambda history, entry, holding: (95., 110.),
                maximum_holding_bars=3, round_trip_cost_bps=cost)
            trade = result["trades"][0]
            rows.append({"scenario": name, "cost_bps": cost,
                         "outcome": trade["outcome"], "entry": trade["entry_price"],
                         "exit": trade["exit_price"], "net_return_scenario_only": trade["net_return"]})
    payload: dict[str, Any] = {
        "status": "SYNTHETIC_EXECUTION_REHEARSAL_NOT_MARKET_RESULTS",
        "source": "GENERATED_2022_FIXTURE_ONLY", "recipe": recipe,
        "recipe_sha256": fingerprint(recipe), "design": specification,
        "engine": "event-driven-bracket-v2", "rows": rows,
        "real_study_status": "NOT_RUN", "real_baselines_status": "NOT_RUN",
        "market_accuracy": None, "portfolio_return": None,
        "limitations": ["Flat costs are stresses, not a dated charge schedule",
                        "Resting target fill is assumed; liquidity, circuits and queue not proved",
                        "Daily inside-bar ambiguity uses stop-first",
                        "No corporate-action, historical-universe or market-calendar proof",
                        "No confidence interval or model result from four artificial scenarios"],
        **{flag: False for flag in AUTHORITY_FLAGS},
        "network_calls": 0, "market_data_reads": 0,
    }
    return {"payload": payload, "report_sha256": fingerprint(payload)}


def validate_rehearsal(value: object) -> dict[str, Any]:
    """Validate only this synthetic report; never confer real-input eligibility."""
    if not isinstance(value, dict) or set(value) != {"payload", "report_sha256"}:
        raise ValueError("EQUITY_REHEARSAL_SHAPE_INVALID")
    raw = json.dumps(value, sort_keys=True, allow_nan=False)
    if len(raw.encode("utf-8")) > 65536:
        raise ValueError("EQUITY_REHEARSAL_BOUND_EXCEEDED")
    payload = value["payload"]
    if (not isinstance(payload, dict) or value["report_sha256"] != fingerprint(payload)
            or payload.get("status") != "SYNTHETIC_EXECUTION_REHEARSAL_NOT_MARKET_RESULTS"
            or payload.get("source") != "GENERATED_2022_FIXTURE_ONLY"
            or any(payload.get(flag) is not False for flag in AUTHORITY_FLAGS)):
        raise ValueError("EQUITY_REHEARSAL_BINDING_INVALID")
    # Only this one fixed generated recipe is admitted. A hash is not evidence
    # that rehashed numbers, nested flags or dates are true. Recompute the small
    # fixture; canonical comparison also distinguishes false from numeric zero.
    if raw != json.dumps(rehearsal(), sort_keys=True, allow_nan=False):
        raise ValueError("EQUITY_REHEARSAL_SEMANTICS_INVALID")
    return value
