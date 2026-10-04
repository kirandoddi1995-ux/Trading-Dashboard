"""Development-only underlying research diagnostics; never executable option P&L."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def _day(value):
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp) or timestamp.tzinfo is None:
        raise ValueError("Aware development timestamps required")
    day = timestamp.tz_convert("Asia/Kolkata").date()
    if not 2022 <= day.year <= 2024:
        raise ValueError("Development only: 2025 validation and 2026 holdout remain frozen")
    return day.isoformat()


def _distribution(values):
    values = np.asarray(values, dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("Finite research returns and excursions required")
    if not len(values):
        return {"count": 0, "mean": None, "sample_std": None, "quantiles": None}
    return {"count": len(values), "mean": float(values.mean()),
            "sample_std": float(values.std(ddof=1)) if len(values) > 1 else None,
            "quantiles": dict(zip(("p05", "p25", "p50", "p75", "p95"),
                                  map(float, np.quantile(values, [.05, .25, .5, .75, .95]))))}


def summarize(report, *, repetitions=5000, seed=20221001):
    """Resample entire accepted sessions, including sessions with zero episodes.

    Estimate the episode-weighted mean (not a mean of session means). Cluster
    sampling retains within-session dependence, but NOT dependence across days.
    Percentile intervals are descriptive; no multiple-testing correction or edge
    certification is implied. No strategy selection or out-of-sample access.
    """
    if (report.get("mode") != "DIRECTIONAL_RESEARCH" or report.get("approval_authority") is not False
            or report.get("fill_evidence") is not False or report.get("option_pnl") is not None):
        raise ValueError("Unmodified directional research report required")
    if type(repetitions) is not int or not 100 <= repetitions <= 20000:
        raise ValueError("Bootstrap repetitions must be 100..20000")
    sessions = [_day(item["session_open"]) for item in report["decisions"]]
    if (len(set(sessions)) != len(sessions) or len(sessions) != report["accepted_sessions"]
            or sessions != sorted(sessions)):
        raise ValueError("Unique chronological accepted-session inventory required")
    for excluded in report["excluded_sessions"]:
        _day(excluded["open"])
    index = {day: i for i, day in enumerate(sessions)}
    result = {"diagnostics_version": "development-cluster-v1",
              "mode": "DEVELOPMENT_DIRECTIONAL_DIAGNOSTICS", "approval_authority": False,
              "fill_evidence": False, "option_pnl": None, "session_count": len(sessions),
              "excluded_sessions": len(report["excluded_sessions"]),
              "bootstrap": {"method": "SESSION_CLUSTER_PERCENTILE", "repetitions": repetitions,
                            "seed": seed, "confidence": .95,
                            "cross_session_dependence_preserved": False}, "variants": {}}
    for name, variant in report["variants"].items():
        trades = variant["trades"]
        if len(trades) != variant["episodes"]:
            raise ValueError("Episode count mismatch")
        totals, counts = np.zeros(len(sessions)), np.zeros(len(sessions), dtype=int)
        by_year = {}
        for trade in trades:
            day = _day(trade["entry_at"])
            if day not in index or _day(trade["exit_at"]) != day:
                raise ValueError("Episodes must enter and exit in one accepted session")
            if pd.Timestamp(trade["exit_at"]) <= pd.Timestamp(trade["entry_at"]):
                raise ValueError("Episode exit must follow entry")
            values = [trade[key] for key in ("directional_return_pct", "mae_pct", "mfe_pct")]
            if not all(type(value) in (int, float) and np.isfinite(value) for value in values):
                raise ValueError("Finite numeric episode measures required")
            if trade["mae_pct"] > 0 or trade["mfe_pct"] < 0:
                raise ValueError("Excursion sign mismatch")
            totals[index[day]] += trade["directional_return_pct"]
            counts[index[day]] += 1
            by_year.setdefault(day[:4], []).append(trade["directional_return_pct"])
        draws = []
        if len(sessions) >= 2 and trades:
            rng = np.random.default_rng(seed)
            # Bound temporary memory; never allocate repetitions x history unbounded.
            for start in range(0, repetitions, 100):
                sampled = rng.integers(0, len(sessions), size=(min(100, repetitions - start), len(sessions)))
                denominators = counts[sampled].sum(axis=1)
                numerators = totals[sampled].sum(axis=1)
                draws.extend((numerators[denominators > 0] / denominators[denominators > 0]).tolist())
        result["variants"][name] = {
            "episodes": len(trades), "session_count": len(sessions),
            "zero_episode_sessions": int(np.count_nonzero(counts == 0)),
            "directional_return_pct": _distribution([t["directional_return_pct"] for t in trades]),
            "mae_pct": _distribution([t["mae_pct"] for t in trades]),
            "mfe_pct": _distribution([t["mfe_pct"] for t in trades]),
            "exit_reasons": dict(Counter(t["reason"] for t in trades)),
            "per_year": {year: {"accepted_sessions": sum(day.startswith(year) for day in sessions),
                                "returns": _distribution(by_year.get(year, []))}
                         for year in sorted({day[:4] for day in sessions})},
            "mean_cluster_ci95_pct": list(map(float, np.quantile(draws, [.025, .975]))) if draws else None,
            "bootstrap_defined_draws": len(draws),
            "bootstrap_undefined_draws": repetitions - len(draws) if len(sessions) >= 2 and trades else None,
        }
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, help="Existing 2022-2024 directional replay JSON only")
    parser.add_argument("--repetitions", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=20221001)
    args = parser.parse_args(argv)
    raw = Path(args.report).read_bytes()
    result = summarize(json.loads(raw.decode("utf-8-sig")),
                       repetitions=args.repetitions, seed=args.seed)
    result["source_report_sha256"] = hashlib.sha256(raw).hexdigest()
    print(json.dumps(result, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
