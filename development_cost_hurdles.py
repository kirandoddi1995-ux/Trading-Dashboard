"""Offline cost sensitivity of development spot references, NOT futures P&L."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from directional_replay_diagnostics import summarize


# Percentage points per round trip, not fractional rates or commissioned tariffs.
# The 0.05 scenario equals the current futures STT percentage on SELL turnover;
# treating it as a constant percentage of ENTRY notional remains a proxy.
HURDLES_PCT = ("0", "0.02", "0.04", "0.05", "0.06", "0.08")
STT_SOURCE = "https://nsearchives.nseindia.com/content/circulars/FATAX73524.pdf"


def _shift(value, hurdle):
    return None if value is None else str(Decimal(str(value)) - hurdle)


def screen(report, *, repetitions=5000, seed=20221001):
    """Reuse the session-cluster estimator without changing any episode.

    A constant hypothetical cost shifts every episode's return and its bootstrap
    mean by the same amount. This is NOT a historical tax calculation: actual
    costs depend on contract prices, turnover, quantity, orders and dated tariffs.
    Zero-episode sessions remain in the bootstrap. Unknown statistics stay null.
    summarize rejects even excluded sessions outside 2022-2024 before scoring.
    """
    diagnostics = summarize(report, repetitions=repetitions, seed=seed)
    variants = {}
    for name, item in diagnostics["variants"].items():
        mean = item["directional_return_pct"]["mean"]
        interval = item["mean_cluster_ci95_pct"]
        cases = []
        for value in HURDLES_PCT:
            hurdle = Decimal(value)
            shifted = [_shift(bound, hurdle) for bound in interval] if interval is not None else None
            cases.append({
                "assumed_round_trip_hurdle_pct": value,
                "reference_mean_minus_hurdle_pct": _shift(mean, hurdle),
                "reference_ci95_minus_hurdle_pct": shifted,
                "screen": ("INSUFFICIENT_EVIDENCE" if shifted is None else
                           "UPPER_INTERVAL_BELOW_ASSUMED_HURDLE" if Decimal(shifted[1]) < 0 else
                           "LOWER_INTERVAL_ABOVE_ASSUMED_HURDLE" if Decimal(shifted[0]) > 0 else
                           "INTERVAL_INCLUDES_ASSUMED_HURDLE"),
            })
        variants[name] = {"episodes": item["episodes"],
                          "gross_reference_mean_pct": None if mean is None else str(mean),
                          "gross_reference_ci95_pct": interval,
                          "hypothetical_cost_sensitivity": cases,
                          "diagnostics": item}
    return {"policy": "development-cost-hurdles-v1", "mode": "SPOT_REFERENCE_COST_SENSITIVITY",
            "data_period": "2022-2024_DEVELOPMENT_ONLY", "approval_authority": False,
            "fill_evidence": False, "futures_pnl": None, "option_pnl": None,
            "cost_policy_commissioned": False, "historical_costs_applied": False,
            "confidence_intervals_are_hard_bounds": False,
            "multiple_testing_corrected": False,
            "cross_session_dependence_preserved": False,
            "current_stt_reference": {"effective_from": "2026-04-01",
                "futures_sell_pct": "0.05", "basis": "ACTUAL_FUTURES_SELL_TURNOVER",
                "source": STT_SOURCE, "applied_to_historical_trades": False},
            "limitations": ["NIFTY spot references are not executable futures prices",
                "Constant hurdles are assumed sensitivity scenarios, not charges or slippage evidence",
                "95% percentile intervals are estimates, not maximum possible expected returns",
                "Entire development period already explored; no newly virgin internal holdback",
                "No candidate selection, approval, or validation/holdout access"],
            "bootstrap": diagnostics["bootstrap"], "accepted_sessions": diagnostics["session_count"],
            "excluded_sessions": diagnostics["excluded_sessions"], "variants": variants}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, help="Existing 2022-2024 replay JSON only")
    args = parser.parse_args(argv)
    raw = Path(args.report).read_bytes()
    result = screen(json.loads(raw.decode("utf-8-sig")))
    result["source_report_sha256"] = hashlib.sha256(raw).hexdigest()
    print(json.dumps(result, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
