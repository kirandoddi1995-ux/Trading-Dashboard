"""Offline NIFTY directional research. No quotes, fills, P&L or approval authority."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from app_runtime import score_option_direction
import technical_indicators as ta


def stamp(value):
    result = pd.Timestamp(value)
    if pd.isna(result) or result.tzinfo is None:
        raise ValueError("Timezone-aware timestamps required")
    return result.tz_convert("UTC")


def validate(bars, sessions):
    """Require explicit session boundaries and all completed five-minute bars.

    Index is bar START, available_at is observation availability, not bar start.
    Retrospectively downloaded bars are allowed only as historical-final research;
    their assumed bar-end availability must be explicitly labelled in metadata.
    """
    required = {"Open", "High", "Low", "Close", "available_at"}
    if bars.empty or not required.issubset(bars.columns):
        raise ValueError("OHLC and available_at required")
    frame = bars.copy()
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError("Timezone-aware bar-start index required")
    frame.index = frame.index.tz_convert("UTC")
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError("Unique increasing bars required; revisions need a separate dataset")
    frame["available_at"] = pd.to_datetime([stamp(v) for v in frame.available_at], utc=True)
    frame["end"] = frame.index + pd.Timedelta(minutes=5)
    if (frame.available_at < frame.end).any():
        raise ValueError("Forming bars cannot be available before completion")
    values = frame[["Open", "High", "Low", "Close"]].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(values.to_numpy()).all() or (values <= 0).any().any():
        raise ValueError("Positive finite OHLC required")
    if ((values.High < values[["Open", "Close"]].max(axis=1)) |
            (values.Low > values[["Open", "Close"]].min(axis=1)) |
            (values.Low > values.High)).any():
        raise ValueError("Invalid OHLC relationships")
    frame[values.columns] = values
    accepted, excluded, covered = [], [], set()
    prior_end = None
    for session in sessions:
        opening, closing = stamp(session["open"]), stamp(session["close"])
        local_open = opening.tz_convert("Asia/Kolkata")
        if prior_end is not None and opening <= prior_end:
            raise ValueError("Sessions must be ordered and non-overlapping")
        prior_end = closing
        if session.get("kind", "REGULAR") != "REGULAR" or session.get("replay_eligible") is False:
            # Preserve all bars from excluded calendar dates without scoring.
            # Specials may occur outside the ordinary 09:15-15:30 window.
            day = local_open.date()
            covered.update(frame.index[frame.index.tz_convert("Asia/Kolkata").date == day])
            excluded.append({"open": opening.isoformat(),
                "reason": session.get("exclusion_reason", "CALENDAR_SESSION_EXCLUDED")})
            continue
        if (closing - opening != pd.Timedelta(minutes=375) or
                (local_open.hour, local_open.minute, local_open.second, local_open.microsecond) != (9, 15, 0, 0)):
            raise ValueError("V1 supports verified 375-minute regular sessions only")
        previous = float(session["previous_close"])
        if not np.isfinite(previous) or previous <= 0 or not session.get("source"):
            raise ValueError("Verified previous close and session source required")
        expected = pd.date_range(opening, closing, freq="5min", inclusive="left")
        actual = frame.loc[(frame.index >= opening) & (frame.index < closing)]
        if "out_of_session_bars" in session:
            # Exact, auditable boundary classification, never an arbitrary list
            # of timestamps to drop. In-session extras remain in actual and fail.
            declared = [stamp(t) for t in session["out_of_session_bars"]]
            day = frame.loc[frame.index.tz_convert("Asia/Kolkata").date == local_open.date()]
            outside = day.index[(day.index < opening) | (day.index >= closing)]
            if len(declared) != len(set(declared)) or set(declared) != set(outside):
                raise ValueError("Out-of-session classification does not match source bars")
            covered.update(outside)
        covered.update(actual.index)
        reason = None
        if not actual.index.equals(expected):
            reason = "INCOMPLETE_OR_MISALIGNED_SESSION"
        elif (actual.available_at != actual.end).any():
            # Next-bar opens precede genuinely delayed observation availability.
            # Do not silently backdate them. Event-level delayed replay is future work.
            reason = "DELAYED_BAR_AVAILABILITY_UNSUPPORTED"
        elif session.get("availability_basis") not in {"recorded_bar_end", "historical_final_assumed_bar_end"}:
            raise ValueError("Explicit availability_basis required")
        if reason:
            excluded.append({"open": opening.isoformat(), "reason": reason})
        else:
            clean = dict(session)
            clean["reset_warmup"] = bool(session.get("reset_warmup")) or bool(
                excluded and (not accepted or stamp(excluded[-1]["open"]) > stamp(accepted[-1][0]["open"])))
            accepted.append((clean, actual))
    if set(frame.index) - covered:
        raise ValueError("Bars outside supplied session calendar")
    return accepted, excluded


def trend(history, minutes, today):
    """Aggregate complete anchored buckets only. No partial closing hour."""
    closes, dates = [], []
    count = minutes // 5
    for day, frame in history:
        for offset in range(0, len(frame) - count + 1, count):
            closes.append(float(frame.Close.iloc[offset + count - 1]))
            dates.append(day)
    if len(closes) < 20 or dates[-1] != today:
        return None
    average = ta.ema(pd.Series(closes), length=20).iloc[-1]
    gap = (closes[-1] / average - 1) * 100
    return "Bullish" if gap > .05 else "Bearish" if gap < -.05 else "Neutral"


def _trend_labels(segment, minutes):
    """One causal EWM pass over completed, session-anchored buckets.

    Mapping uses only buckets complete at each five-minute bar. The trailing
    partial closing hour is omitted, exactly as in the reference trend helper.
    """
    count = minutes // 5
    bucket_closes = [float(frame.Close.iloc[i]) for _, frame in segment
                     for i in range(count - 1, len(frame), count)]
    averages = ta.ema(pd.Series(bucket_closes, dtype=float), 20)
    labels = []
    offset = 0
    for _, frame in segment:
        day = []
        for i in range(len(frame)):
            completed = (i + 1) // count
            index = offset + completed - 1
            if not completed or index < 19:
                day.append(None)
            else:
                gap = (bucket_closes[index] / averages.iloc[index] - 1) * 100
                day.append("Bullish" if gap > .05 else "Bearish" if gap < -.05 else "Neutral")
        labels.append(day)
        offset += len(frame) // count
    return labels


def _segment_decisions(segment):
    # EWM/RSI/MACD are causal: batch computation does not change any prefix.
    # Calculate once per uninterrupted segment, not once per session/bar.
    closes = pd.concat([frame.Close for _, frame in segment], ignore_index=True)
    ema, rsi, macd = ta.ema(closes, 20), ta.rsi(closes, 14), ta.macd(closes, 12, 26, 9)
    histogram = macd.filter(like="MACDh_").iloc[:, 0]
    trends15, trends60 = _trend_labels(segment, 15), _trend_labels(segment, 60)
    result = []
    offset = 0
    for day, (session, frame) in enumerate(segment):
        rows = []
        for i in range(len(frame)):
            j = offset + i
            mh = float(histogram.iloc[j])
            inputs = (float(ema.iloc[j]), float(rsi.iloc[j]), mh)
            t15, t60 = trends15[day][i], trends60[day][i]
            if not all(np.isfinite(inputs)) or t15 is None:
                detail = {"bias": "Unavailable", "decision_reason": "INDICATOR_OR_SESSION_TREND_WARMUP"}
            else:
                detail = score_option_direction(price=float(frame.Close.iloc[i]),
                    previous_close=session["previous_close"], ema20=inputs[0], rsi=inputs[1],
                    macd_hist=inputs[2], trend_15m=t15, trend_1h=t60, volume_confirmed=False,
                    market_open=True, minimum_score=25)
            bias = detail["bias"]
            direction = (1 if bias in {"Bullish", "Mildly Bullish"} else
                         -1 if bias in {"Bearish", "Mildly Bearish"} else 0)
            rows.append({"at": frame.end.iloc[i].isoformat(), "direction": direction,
                         "available": bias != "Unavailable", "detail": detail})
        result.append((session, frame, rows))
        offset += len(frame)
    return result


def decisions(accepted):
    """Candidate C, identical causal math with linear-time trend preparation."""
    result, segment = [], []
    for item in accepted:
        if item[0].get("reset_warmup") and segment:
            result.extend(_segment_decisions(segment))
            segment = []
        segment.append(item)
    if segment:
        result.extend(_segment_decisions(segment))
    return result


def replay_session(frame, rows, confirmations):
    """Synthetic underlying exposure, not an index order or option fill.

    Decisions at bar end act at the NEXT bar's open. Last-bar close is an explicit
    session-end reference; there is no claim of broker deadline or executability.
    """
    trades, position, streak, last_direction = [], None, 0, 0

    def close(price, at, reason):
        nonlocal position
        direction, entry = position["direction"], position["entry_reference"]
        position.update(exit_reference=float(price), exit_at=at.isoformat(), reason=reason,
                        directional_return_pct=direction * (float(price) / entry - 1) * 100)
        trades.append(position)
        position = None

    for i, (_, bar) in enumerate(frame.iterrows()):
        if i:
            signal = rows[i - 1]
            direction = signal["direction"] if signal["available"] else 0
            streak = streak + 1 if direction and direction == last_direction else (1 if direction else 0)
            last_direction = direction
            qualified = direction if streak >= confirmations else 0
            if position and qualified == -position["direction"]:
                close(bar.Open, frame.index[i], "REVERSAL_NEXT_OPEN_REFERENCE")
            elif position is None and qualified:
                position = dict(direction=qualified, entry_reference=float(bar.Open),
                                entry_at=frame.index[i].isoformat(), mae_pct=0.0, mfe_pct=0.0)
        if position:
            entry, direction = position["entry_reference"], position["direction"]
            returns = [direction * (float(p) / entry - 1) * 100 for p in (bar.Low, bar.High)]
            position["mae_pct"] = min(position["mae_pct"], *returns)
            position["mfe_pct"] = max(position["mfe_pct"], *returns)
    if position:
        close(frame.Close.iloc[-1], frame.index[-1] + pd.Timedelta(minutes=5), "SESSION_END_CLOSE_REFERENCE")
    return trades


def run(bars, sessions):
    accepted, excluded = validate(bars, sessions)
    prepared = decisions(accepted)
    variants = {}
    for name, confirmations in (("C_single_bar_no_volume", 1), ("C_persistent_no_volume", 2)):
        trades = [trade for _, frame, rows in prepared for trade in replay_session(frame, rows, confirmations)]
        variants[name] = {"episodes": len(trades), "trades": trades,
            "mean_directional_return_pct": float(np.mean([t["directional_return_pct"] for t in trades])) if trades else None,
            "positive_directional_episode_fraction": sum(t["directional_return_pct"] > 0 for t in trades) / len(trades) if trades else None}
    return {"policy": "intraday-directional-v1", "mode": "DIRECTIONAL_RESEARCH",
            "out_of_session_bars": [{"session_open": s["open"], "timestamps": s.get("out_of_session_bars", [])}
                for s, _ in accepted if s.get("out_of_session_bars")],
            "option_pnl": None, "fill_evidence": False, "approval_authority": False,
            "availability_bases": sorted({s["availability_basis"] for s, _ in accepted}),
            "accepted_sessions": len(accepted), "excluded_sessions": excluded,
            "decisions": [{"session_open": s["open"], "rows": rows} for s, _, rows in prepared],
            "variants": variants}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", required=True, help="CSV: timestamp,Open,High,Low,Close,available_at")
    parser.add_argument("--sessions", required=True, help="JSON array: open,close,previous_close,source,availability_basis")
    args = parser.parse_args(argv)
    frame = pd.read_csv(args.bars)
    frame.index = pd.DatetimeIndex([stamp(v) for v in frame.pop("timestamp")])
    report = run(frame, json.loads(Path(args.sessions).read_text(encoding="utf-8")))
    print(json.dumps(report, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
