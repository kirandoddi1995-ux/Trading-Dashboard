"""Offline calendar/previous-close audit. Original downloads are never changed."""
import argparse
from collections import Counter
from datetime import date, timedelta
import gzip
import json
from pathlib import Path

import pandas as pd

from download_nifty_history import KEY, VERSION, candles, encoded, immutable, sha
from nifty_session_calendar import session


def daily_closes(root):
    found = {}
    for path in sorted(root.glob("days-1-*.json.gz")):
        artifact = json.loads(gzip.decompress(path.read_bytes()))
        meta, rows = artifact["metadata"], artifact["candles"]
        if (meta["version"] != VERSION or meta["key"] != KEY or
                meta["unit"] != "days" or meta["interval"] != 1 or
                meta["rows_sha256"] != sha(encoded(rows)) or meta["row_count"] != len(rows)):
            raise ValueError("DAILY_ARTIFACT_INVALID")
        rows = candles({"status": "success", "data": {"candles": rows}},
                       date.fromisoformat(meta["start"]), date.fromisoformat(meta["end"]))
        for row in rows:
            day = pd.Timestamp(row[0]).tz_convert("Asia/Kolkata").date()
            if day in found:
                raise ValueError("DUPLICATE_DAILY_DATE")
            found[day] = {"close": row[4], "source_sha256": sha(path.read_bytes())}
    return found


def audit(frame, start, end, closes, reviewed=False):
    if start > end or start < date(2022, 1, 1):
        raise ValueError("INVALID_CALENDAR_RANGE")
    if frame.index.tz is None or frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError("UNIQUE_ORDERED_AWARE_BARS_REQUIRED")
    local = frame.index.tz_convert("Asia/Kolkata")
    if any(not start <= d <= end for d in local.date):
        raise ValueError("BARS_OUTSIDE_REQUESTED_RANGE")
    days, sessions = [], []
    # Explicit anchor, not a fallback to any earlier available row. Missing daily
    # data excludes the first session. Calendar acknowledgement covers this anchor.
    previous = date(2021, 12, 31)
    cursor = date(2022, 1, 1)
    reset = True
    while cursor <= end:
        definition = session(cursor)
        if cursor < start:
            if definition["kind"] != "CLOSED":
                previous = cursor
            cursor += timedelta(days=1)
            continue
        actual = frame.loc[local.date == cursor]
        expected = pd.DatetimeIndex([], tz="UTC")
        for opening, closing in definition["windows"] or []:
            expected = expected.append(pd.date_range(
                pd.Timestamp(f"{cursor} {opening}", tz="Asia/Kolkata"),
                pd.Timestamp(f"{cursor} {closing}", tz="Asia/Kolkata"),
                freq="5min", inclusive="left").tz_convert("UTC"))
        missing = expected.difference(actual.index)
        unexpected = actual.index.difference(expected)
        kind = definition["kind"]
        regular = actual
        outside = pd.DatetimeIndex([], tz="UTC")
        if kind == "REGULAR":
            opening, closing = expected[0], expected[-1] + pd.Timedelta(minutes=5)
            regular = actual.loc[(actual.index >= opening) & (actual.index < closing)]
            outside = actual.index.difference(regular.index)
        prior = closes.get(previous)
        complete = regular.index.equals(expected) and bool(len(expected))
        availability_ok = complete and bool((pd.to_datetime(regular.available_at, utc=True).array ==
            (regular.index + pd.Timedelta(minutes=5)).array).all())
        eligible = reviewed and kind == "REGULAR" and complete and availability_ok and prior is not None
        status = ("CLOSED" if actual.empty else "UNEXPECTED_CLOSED_BARS") if kind == "CLOSED" else (
            f"{kind}_TIMING_UNVERIFIED" if definition["windows"] is None else
            "REGULAR_COMPLETE_WITH_OUT_OF_SESSION_BARS" if complete and kind == "REGULAR" and len(outside) else
            f"{kind}_COMPLETE" if complete else f"{kind}_MISSING" if actual.empty else
            f"{kind}_EXTRA_BARS" if not len(missing) else f"{kind}_INCOMPLETE")
        record = dict(date=str(cursor), status=status, count=len(actual), expected=len(expected),
            missing=[t.isoformat() for t in missing], unexpected=[t.isoformat() for t in unexpected],
            regular_bar_count=len(regular) if kind == "REGULAR" else None,
            out_of_session_bars=[t.isoformat() for t in outside],
            in_session_unexpected=[t.isoformat() for t in unexpected.difference(outside)],
            previous_session=str(previous), previous_close_available=prior is not None,
            availability_matches_bar_end=availability_ok,
            replay_eligible=eligible, source=definition["source"])
        days.append(record)
        if kind != "CLOSED":
            # Full-date containment allows unsupported special windows to be
            # accounted for without scoring them or pretending their timing is known.
            windows = definition["windows"]
            opening = pd.Timestamp(f"{cursor} {windows[0][0] if windows else '00:00'}", tz="Asia/Kolkata")
            closing = (pd.Timestamp(f"{cursor} {windows[-1][1]}", tz="Asia/Kolkata") if windows else
                       opening + pd.Timedelta(days=1))
            sessions.append(dict(open=opening.isoformat(), close=closing.isoformat(),
                windows=windows, timing_verified=windows is not None,
                out_of_session_bars=record["out_of_session_bars"],
                kind=kind, date=str(cursor), replay_eligible=eligible,
                exclusion_reason=("CALENDAR_NOT_REVIEWED" if not reviewed else
                    status if not complete or kind != "REGULAR" else
                    "DELAYED_BAR_AVAILABILITY_UNSUPPORTED" if not availability_ok else "PREVIOUS_DAILY_CLOSE_MISSING"),
                previous_close=prior["close"] if prior else None, previous_close_date=str(previous),
                previous_close_source="UPSTOX_DAILY_NOT_INDEPENDENT_PROVIDER",
                previous_close_source_sha256=prior["source_sha256"] if prior else None,
                source=definition["source"], availability_basis="historical_final_assumed_bar_end",
                reset_warmup=reset))
            reset = not eligible
            previous = cursor
        cursor += timedelta(days=1)
    blocked = any(d["status"] == "UNEXPECTED_CLOSED_BARS" for d in days)
    before = sum(d["status"] == "REGULAR_COMPLETE" for d in days)
    restored = sum(d["status"] == "REGULAR_COMPLETE_WITH_OUT_OF_SESSION_BARS" for d in days)
    return {"version": "nifty-readiness-v2", "calendar_reviewed": reviewed,
        "regular_grid_counts": {"before_boundary_filter": before, "restored": restored,
            "after_boundary_filter": before + restored},
        "replay_ready": reviewed and not blocked and any(d["replay_eligible"] for d in days),
        "approval_authority": False, "counts": dict(Counter(d["status"] for d in days)), "days": days}, sessions


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2022, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 9, 30))
    parser.add_argument("--calendar-reviewed", action="store_true")
    args = parser.parse_args(argv)
    stem = args.root / f"nifty-five-minute-{args.start}-{args.end}"
    csv = Path(str(stem) + ".csv").read_bytes()
    parquet = Path(str(stem) + ".parquet").read_bytes()
    manifest = json.loads(Path(str(stem) + ".manifest.json").read_text())
    if sha(csv) != manifest["csv_sha256"] or sha(parquet) != manifest["parquet_sha256"]:
        raise ValueError("SOURCE_HASH_MISMATCH")
    frame = pd.read_csv(Path(str(stem) + ".csv"))
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("timestamp"), utc=True))
    if len(frame) != manifest["row_count"]:
        raise ValueError("SOURCE_ROW_COUNT_MISMATCH")
    report, sessions = audit(frame, args.start, args.end, daily_closes(args.root), args.calendar_reviewed)
    if not any(d["status"] == "UNEXPECTED_CLOSED_BARS" for d in report["days"]):
        # Apply the same OHLC/availability checks as the eventual replay, before
        # issuing readiness. No decisions or holdout outcomes are calculated.
        from intraday_directional_replay import validate
        validate(frame, sessions)
    report["source_csv_sha256"] = sha(csv)
    report["calendar_sha256"] = sha(Path(__file__).with_name("nifty_session_calendar.py").read_bytes())
    immutable(args.output / "quality.json", encoded(report))
    immutable(args.output / "sessions.json", encoded(sessions))
    print(json.dumps({k: report[k] for k in ("replay_ready", "counts", "approval_authority")}))
    return 0 if report["replay_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
