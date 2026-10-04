"""Bounded local Upstox history acquisition; no import-time I/O or database access."""
from __future__ import annotations

import argparse
import calendar
from datetime import date, datetime, timedelta, timezone
import getpass
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import tempfile
import time
from zoneinfo import ZoneInfo

import pandas as pd
import requests

KEY = "NSE_INDEX|Nifty 50"
BASE = "https://api.upstox.com/v3/historical-candle/NSE_INDEX%7CNifty%2050"
VERSION = "nifty-history-v1"
MAX_RESPONSE = 8 * 1024 * 1024


class HistoryError(ValueError):
    """Fixed codes only: never expose transport exceptions or credential content."""


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def monthly(start, end):
    if start < date(2022, 1, 1) or start > end:
        raise HistoryError("INVALID_HISTORY_RANGE")
    while start <= end:
        last = date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])
        stop = min(last, end)
        yield start, stop
        start = stop + timedelta(days=1)


def candles(body, start, end):
    if not isinstance(body, dict) or body.get("status") != "success":
        raise HistoryError("INVALID_RESPONSE")
    data = body.get("data")
    rows = data.get("candles") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise HistoryError("INVALID_CANDLES")
    found = {}
    for row in rows:
        if not isinstance(row, list) or len(row) != 7 or not isinstance(row[0], str):
            raise HistoryError("INVALID_CANDLE_SHAPE")
        try:
            ts = pd.Timestamp(row[0])
            if pd.isna(ts) or ts.tzinfo is None:
                raise ValueError()
            local = ts.tz_convert("Asia/Kolkata")
            values = [float(x) for x in row[1:]]
            if any(isinstance(x, (bool, str)) for x in row[1:]):
                raise ValueError()
            if not all(math.isfinite(x) for x in values):
                raise ValueError()
            opening, high, low, close, volume, oi = values
            if (min(opening, high, low, close) <= 0 or volume < 0 or oi < 0 or
                    low > min(opening, close) or high < max(opening, close) or low > high):
                raise ValueError()
            if not start <= local.date() <= end:
                raise ValueError()
        except (TypeError, ValueError, OverflowError):
            raise HistoryError("INVALID_CANDLE_VALUES") from None
        identity = ts.tz_convert("UTC").isoformat()
        if identity in found:
            raise HistoryError("DUPLICATE_OR_REVISED_TIMESTAMP")
        found[identity] = row
    return [found[key] for key in sorted(found)]


class Reader:
    def __init__(self, token, session, sleep=time.sleep):
        if not token or any(ch.isspace() for ch in token):
            raise HistoryError("AUTH_REQUIRED")
        self.token, self.session, self.sleep = token, session, sleep

    def fetch(self, start, end, unit="minutes", interval=5):
        if (unit, interval) not in {("minutes", 5), ("days", 1)}:
            raise HistoryError("FORBIDDEN_INTERVAL")
        if start > end or start.month != end.month or start.year != end.year:
            raise HistoryError("REQUEST_MUST_STAY_WITHIN_MONTH")
        url = f"{BASE}/{unit}/{interval}/{end.isoformat()}/{start.isoformat()}"
        for attempt in range(3):
            try:
                with self.session.get(url, headers={"Authorization": "Bearer " + self.token,
                        "Accept": "application/json"}, timeout=(5, 30), verify=True,
                        allow_redirects=False, stream=True) as response:
                    status = response.status_code
                    if status in (401, 403):
                        raise HistoryError("AUTH_REQUIRED")
                    if status == 429 or 500 <= status < 600:
                        if attempt == 2:
                            raise HistoryError("RETRIES_EXHAUSTED")
                        try:
                            delay = float(response.headers.get("Retry-After", 2 ** attempt))
                        except (TypeError, ValueError):
                            delay = 2 ** attempt
                        if not math.isfinite(delay) or not 0 <= delay <= 60:
                            raise HistoryError("RETRY_AFTER_OUT_OF_BOUNDS")
                        self.sleep(max(delay, 1))
                        continue
                    if status != 200:
                        raise HistoryError("HTTP_REJECTED")
                    raw = bytearray()
                    for chunk in response.iter_content(65536):
                        raw.extend(chunk)
                        if len(raw) > MAX_RESPONSE:
                            raise HistoryError("RESPONSE_TOO_LARGE")
                    try:
                        body = json.loads(raw)
                    except (ValueError, TypeError):
                        raise HistoryError("INVALID_JSON") from None
                    return candles(body, start, end)
            except requests.RequestException:
                if attempt == 2:
                    raise HistoryError("TRANSPORT_FAILED") from None
                self.sleep(2 ** attempt)
        raise HistoryError("RETRIES_EXHAUSTED")


def immutable(path, data):
    """Create atomically without replacing existing bytes; safe restart/conflict check."""
    if path.exists():
        if path.read_bytes() != data:
            raise HistoryError("LOCAL_ARTIFACT_CONFLICT")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".history-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        # A same-directory hard link publishes complete bytes without overwriting
        # another writer. NTFS supports it; unsupported filesystems fail explicitly.
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise HistoryError("LOCAL_ARTIFACT_CONFLICT") from None
    finally:
        os.unlink(temporary)


def acquire(reader, root, start, end, unit="minutes", interval=5):
    path = root / f"{unit}-{interval}-{start}-{end}.json.gz"
    if path.exists():
        try:
            artifact = json.loads(gzip.decompress(path.read_bytes()))
            meta = artifact["metadata"]
            rows = artifact["candles"]
            if (meta["version"], meta["key"], meta["start"], meta["end"], meta["unit"], meta["interval"]) != (
                    VERSION, KEY, str(start), str(end), unit, interval):
                raise ValueError()
            if meta["rows_sha256"] != sha(encoded(rows)) or meta["row_count"] != len(rows):
                raise ValueError()
            rows = candles({"status": "success", "data": {"candles": rows}}, start, end)
            return rows, path
        except (KeyError, TypeError, ValueError, OSError, EOFError):
            raise HistoryError("LOCAL_ARTIFACT_INVALID") from None
    if reader is None:
        raise HistoryError("SESSION_ARTIFACT_MISSING")
    rows = reader.fetch(start, end, unit, interval)
    artifact = {"metadata": {"version": VERSION, "key": KEY, "start": str(start), "end": str(end),
        "unit": unit, "interval": interval, "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "row_count": len(rows), "rows_sha256": sha(encoded(rows)), "timestamp_basis": "BAR_START_DOCUMENTED",
        "mode": "HISTORICAL_FINAL_RESEARCH"}, "candles": rows}
    immutable(path, gzip.compress(encoded(artifact), mtime=0))
    return rows, path


def check_session(rows, day):
    index = pd.DatetimeIndex([pd.Timestamp(row[0]).tz_convert("Asia/Kolkata") for row in rows])
    opening = pd.Timestamp(str(day) + " 09:15", tz="Asia/Kolkata")
    expected = pd.date_range(opening, periods=75, freq="5min")
    return {"version": VERSION, "date": str(day), "status": "PASS" if index.equals(expected) else "FAIL",
        "count": len(rows), "missing": [t.isoformat() for t in expected.difference(index)],
        "unexpected": [t.isoformat() for t in index.difference(expected)], "rows_sha256": sha(encoded(rows)),
        "meaning": "STRUCTURAL_START_TIME_CHECK_NOT_INDEPENDENT_PRICE_VERIFICATION"}


def export(rows):
    if not rows:
        raise HistoryError("EMPTY_HISTORY")
    frame = pd.DataFrame(rows, columns=["timestamp", "Open", "High", "Low", "Close", "Volume", "OI"])
    index = pd.DatetimeIndex([pd.Timestamp(v).tz_convert("UTC") for v in frame.timestamp])
    frame["timestamp"] = [v.isoformat() for v in index]
    frame["available_at"] = [(v + pd.Timedelta(minutes=5)).isoformat() for v in index]
    frame["availability_basis"] = "historical_final_assumed_bar_end"
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False, compression="zstd")
    if not pd.read_parquet(io.BytesIO(buffer.getvalue())).equals(frame):
        raise HistoryError("PARQUET_ROUNDTRIP_FAILED")
    return frame.to_csv(index=False).encode(), buffer.getvalue()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["check", "download"])
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2022, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 9, 30))
    parser.add_argument("--reviewed-session-check", action="store_true")
    parser.add_argument("--licence-confirmed", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        project = Path(__file__).resolve().parent
        if root == project or project in root.parents:
            raise HistoryError("DATA_MUST_BE_OUTSIDE_PROJECT")
        if not args.licence_confirmed:
            raise HistoryError("LICENCE_CONFIRMATION_REQUIRED")
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        if args.mode == "check" and (not args.date or args.date >= today):
            raise HistoryError("COMPLETED_SESSION_DATE_REQUIRED")
        if args.mode == "download":
            receipt = json.loads((root / "session-check.json").read_text()) if (root / "session-check.json").exists() else {}
            if not args.reviewed_session_check or receipt.get("status") != "PASS":
                raise HistoryError("REVIEWED_SESSION_CHECK_REQUIRED")
            checked = date.fromisoformat(receipt["date"])
            verified_rows, _ = acquire(None, root, checked, checked)
            if check_session(verified_rows, checked) != receipt:
                raise HistoryError("SESSION_RECEIPT_INVALID")
            if args.end >= today:
                raise HistoryError("COMPLETED_HISTORY_ONLY")
            ranges = list(monthly(args.start, args.end))
        else:
            ranges = [(args.date, args.date)]
        token = os.environ.get("UPSTOX_ANALYTICS_TOKEN") or getpass.getpass("Analytics token (hidden): ")
        with requests.Session() as session:
            reader = Reader(token, session)
            all_rows = []
            for start, end in ranges:
                rows, _ = acquire(reader, root, start, end)
                all_rows.extend(rows)
                print(json.dumps({"status": "CHUNK_VERIFIED", "start": str(start), "end": str(end), "rows": len(rows)}))
            if args.mode == "check":
                report = check_session(all_rows, args.date)
                immutable(root / "session-check.json", encoded(report))
                print(json.dumps(report))
                return 0 if report["status"] == "PASS" else 1
            all_rows = candles({"status": "success", "data": {"candles": all_rows}}, args.start, args.end)
            csv, parquet = export(all_rows)
            stem = f"nifty-five-minute-{args.start}-{args.end}"
            immutable(root / (stem + ".csv"), csv)
            immutable(root / (stem + ".parquet"), parquet)
            immutable(root / (stem + ".manifest.json"), encoded({"version": VERSION, "row_count": len(all_rows),
                "csv_sha256": sha(csv), "parquet_sha256": sha(parquet), "rows_sha256": sha(encoded(all_rows)),
                "split": {"development": "2022-2024", "validation": "2025", "holdout": "2026"},
                "sessions": "REQUIRES_SEPARATELY_VERIFIED_CALENDAR_AND_PREVIOUS_DAILY_CLOSES"}))
            print(json.dumps({"status": "DOWNLOAD_VERIFIED", "rows": len(all_rows), "replay_ready": False}))
            return 0
    except (HistoryError, OSError, ValueError, KeyError, TypeError, EOFError):
        # Fixed-code errors only, including filesystem/JSON errors whose text may
        # contain user-controlled or credential-bearing values.
        import sys
        error = sys.exc_info()[1]
        print(json.dumps({"status": "FAILED", "code": str(error) if isinstance(error, HistoryError) else "LOCAL_CONFIGURATION_INVALID"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
