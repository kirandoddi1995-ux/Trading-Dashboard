"""Pure Stage-1 equity scanner funnel shared by UI and scheduled collectors.

The function in this module deliberately performs no network, database, model,
governance, or order activity.  It only ranks the point-in-time quote snapshot
supplied by its caller.  This keeps unattended and manual scans mathematically
identical and easy to regression test.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd


def _clamp(value, lo=0.0, hi=100.0):
    return max(lo, min(hi, float(value)))


def stage1_prefilter(
    tickers: Sequence[str],
    instrument_dict: Mapping[str, str],
    quotes: Mapping[str, Mapping],
    top_n: int,
    *,
    average_volumes: Mapping[str, float | None] | None = None,
    elapsed_fraction: float | None = None,
):
    """Rank one immutable quote snapshot without changing any trade gate.

    ``elapsed_fraction`` must describe the market-session progress measured by
    the caller at quote capture time.  Passing ``None`` intentionally disables
    intraday volume pacing rather than inventing a timestamp.
    """
    average_volumes = dict(average_volumes or {})
    evidence_by_ticker: dict[str, dict] = {}
    rows: list[dict] = []
    no_quote = 0

    for ticker in tickers:
        key = instrument_dict.get(ticker)
        quote = quotes.get(key) if key else None
        if not quote:
            no_quote += 1
            evidence_by_ticker[ticker] = {
                "instrument_key": key,
                "trading_symbol": ticker,
                "stage1_pass": False,
                "rejection_reason": "No usable quote",
                "score": None,
                "features": {},
            }
            continue

        try:
            ltp = float(quote.get("last_price") or 0.0)
            ohlc = quote.get("ohlc") or quote.get("live_ohlc") or {}
            previous = quote.get("prev_ohlc") or {}
            prev_close = float(
                quote.get("prev_close_price") or previous.get("close")
                or ohlc.get("close") or 0.0
            )
            day_high = float(ohlc.get("high") or ltp)
            day_low = float(ohlc.get("low") or ltp)
            day_volume = float(quote.get("volume") or ohlc.get("volume") or 0.0)
            if ltp <= 0 or prev_close <= 0:
                evidence_by_ticker[ticker] = {
                    "instrument_key": key,
                    "trading_symbol": ticker,
                    "stage1_pass": False,
                    "rejection_reason": "Invalid last price or previous close",
                    "score": None,
                    "features": {"last_price": ltp, "previous_close": prev_close},
                }
                continue

            momentum_pct = (ltp / prev_close - 1.0) * 100.0
            range_pct = ((day_high - day_low) / prev_close) * 100.0
            close_location = (
                (ltp - day_low) / (day_high - day_low) if day_high > day_low else 0.5
            )
            close_location = _clamp(close_location, 0.0, 1.0)
            avg_vol = average_volumes.get(key)
            if avg_vol and float(avg_vol) > 0 and day_volume > 0:
                raw_daily_ratio = day_volume / float(avg_vol)
                volume_pace_ratio = (
                    min(raw_daily_ratio / float(elapsed_fraction), 5.0)
                    if elapsed_fraction is not None and float(elapsed_fraction) > 0
                    else raw_daily_ratio
                )
            else:
                raw_daily_ratio = None
                volume_pace_ratio = None

            rows.append({
                "ticker": ticker,
                "momentum_pct": momentum_pct,
                "range_pct": range_pct,
                "close_location": close_location,
                "day_volume": day_volume,
                "avg_vol": avg_vol,
                "raw_volume_ratio": raw_daily_ratio,
                "volume_pace_ratio": volume_pace_ratio,
                "abs_move": abs(momentum_pct),
            })
        except (TypeError, ValueError, OverflowError):
            evidence_by_ticker[ticker] = {
                "instrument_key": key,
                "trading_symbol": ticker,
                "stage1_pass": False,
                "rejection_reason": "Quote parse failed",
                "score": None,
                "features": {},
            }

    if not rows:
        return [], {
            "universe_size": len(tickers),
            "quoted": 0,
            "no_quote": no_quote,
            "shortlisted": 0,
            "session_fraction": (
                round(float(elapsed_fraction), 3) if elapsed_fraction is not None else None
            ),
            "bucket_counts": {},
            "_evidence": list(evidence_by_ticker.values()),
        }

    frame = pd.DataFrame(rows)
    frame["momentum_score"] = np.clip(
        (frame["momentum_pct"].to_numpy(dtype=float) + 5.0) / 10.0 * 100.0,
        0.0,
        100.0,
    )
    frame["range_score"] = np.clip(
        frame["range_pct"].to_numpy(dtype=float) / 6.0 * 100.0, 0.0, 100.0
    )
    volume_values = frame["volume_pace_ratio"].to_numpy(dtype=float)
    frame["volume_score"] = np.where(
        np.isfinite(volume_values),
        np.clip((volume_values - 0.5) / 3.0 * 100.0, 0.0, 100.0),
        50.0,
    )
    frame["near_high_score"] = frame["close_location"] * 100.0
    frame["balanced_score"] = (
        frame["momentum_score"] * 0.30
        + frame["volume_score"] * 0.25
        + frame["range_score"] * 0.15
        + frame["near_high_score"] * 0.20
        + np.clip(frame["abs_move"].to_numpy(dtype=float) / 5.0 * 100.0, 0.0, 100.0)
        * 0.10
    )
    frame["liquidity_pct"] = frame["day_volume"].rank(pct=True) * 100.0
    frame["balanced_score"] += frame["liquidity_pct"] * 0.05

    buckets = {
        "momentum": frame.sort_values(["momentum_score", "volume_score"], ascending=False),
        "volume": frame.sort_values(["volume_score", "momentum_score"], ascending=False),
        "range": frame.sort_values(["range_score", "volume_score"], ascending=False),
        "breakout": frame.sort_values(["near_high_score", "momentum_score"], ascending=False),
        "balanced": frame.sort_values(["balanced_score"], ascending=False),
    }
    requested = max(0, int(top_n))
    per_bucket = max(10, int(math.ceil(requested / max(len(buckets), 1))))
    selected: list[str] = []
    selected_set: set[str] = set()
    bucket_counts: dict[str, int] = {}
    for name, bucket in buckets.items():
        count = 0
        for row in bucket.itertuples(index=False):
            if row.ticker in selected_set:
                continue
            selected.append(row.ticker)
            selected_set.add(row.ticker)
            count += 1
            if count >= per_bucket or len(selected) >= requested:
                break
        bucket_counts[name] = count
        if len(selected) >= requested:
            break

    if len(selected) < requested:
        for row in frame.sort_values("balanced_score", ascending=False).itertuples(index=False):
            if row.ticker in selected_set:
                continue
            selected.append(row.ticker)
            selected_set.add(row.ticker)
            if len(selected) >= requested:
                break

    for row in frame.to_dict("records"):
        ticker = row["ticker"]
        evidence_by_ticker[ticker] = {
            "instrument_key": instrument_dict.get(ticker),
            "trading_symbol": ticker,
            "stage1_pass": ticker in selected_set,
            "rejection_reason": (
                None
                if ticker in selected_set
                else "Not selected by diversified Stage-1 ranking"
            ),
            "score": float(row["balanced_score"]),
            "features": {
                "momentum_pct": row["momentum_pct"],
                "range_pct": row["range_pct"],
                "close_location": row["close_location"],
                "day_volume": row["day_volume"],
                "average_volume_20d": row["avg_vol"],
                "raw_volume_ratio": row["raw_volume_ratio"],
                "volume_pace_ratio": row["volume_pace_ratio"],
                "liquidity_percentile": row["liquidity_pct"],
            },
        }

    return selected, {
        "universe_size": len(tickers),
        "quoted": len(frame),
        "no_quote": no_quote,
        "shortlisted": len(selected),
        "session_fraction": (
            round(float(elapsed_fraction), 3) if elapsed_fraction is not None else None
        ),
        "bucket_counts": bucket_counts,
        "_evidence": list(evidence_by_ticker.values()),
    }
