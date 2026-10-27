"""Pure bounded decoder, not a fetcher, data-admission gate or executable-price proof."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
import re
from typing import Any

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 1200


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DAILY_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _price(value: object) -> Decimal:
    if not isinstance(value, (int, Decimal)) or isinstance(value, bool):
        raise ValueError("DAILY_PRICE_TYPE")
    number = Decimal(value)
    if not number.is_finite() or not Decimal("0") < number <= Decimal("1000000000"):
        raise ValueError("DAILY_PRICE_BOUND")
    return number


def _integer(value: object) -> int:
    if type(value) is not int or not 0 <= value <= 10**14:
        raise ValueError("DAILY_INTEGER_BOUND")
    return value


def decode_daily(raw: bytes, *, instrument_key: str, start: str, end: str) -> dict[str, Any]:
    """Decode explicit response bytes only. No file/network/credential operations.

    A caller-supplied instrument key is not a signed request binding. Candle
    timestamps are session labels, never knowledge/availability timestamps.
    """
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError("DAILY_RESPONSE_BYTES_BOUND")
    if type(instrument_key) is not str or not re.fullmatch(r"NSE_EQ\|INE[A-Z0-9]{9}", instrument_key):
        raise ValueError("DAILY_INSTRUMENT_BINDING_REQUIRED")
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        if first.isoformat() != start or last.isoformat() != end:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("DAILY_DATE_BOUNDARY_REQUIRED") from None
    if not date(2022, 1, 1) <= first <= last <= date(2024, 12, 31):
        raise ValueError("DAILY_DEVELOPMENT_ONLY")
    try:
        value = json.loads(raw.decode("utf-8"), parse_float=Decimal,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
                           object_pairs_hook=_object)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("DAILY_JSON_INVALID") from None
    if (type(value) is not dict or value.get("status") != "success"
            or type(value.get("data")) is not dict):
        raise ValueError("DAILY_RESPONSE_SHAPE")
    candles = value["data"].get("candles")
    if type(candles) is not list or not 1 <= len(candles) <= MAX_ROWS:
        raise ValueError("DAILY_ROWS_BOUND")
    rows: list[dict[str, Any]] = []
    seen: set[date] = set()
    for candle in candles:
        if type(candle) is not list or len(candle) != 7 or type(candle[0]) is not str:
            raise ValueError("DAILY_CANDLE_SHAPE")
        try:
            stamp = datetime.fromisoformat(candle[0])
        except ValueError:
            raise ValueError("DAILY_TIMESTAMP_INVALID") from None
        if stamp.utcoffset() != timedelta(hours=5, minutes=30):
            raise ValueError("DAILY_TIMESTAMP_IST_REQUIRED")
        if (stamp.hour, stamp.minute, stamp.second, stamp.microsecond) not in ((0, 0, 0, 0), (9, 15, 0, 0)):
            raise ValueError("DAILY_CANDLE_LABEL_UNREVIEWED")
        day = stamp.date()
        if not first <= day <= last or day in seen:
            raise ValueError("DAILY_DATE_OUTSIDE_REQUEST_OR_DUPLICATE")
        seen.add(day)
        opening, high, low, close = map(_price, candle[1:5])
        if high < max(opening, close) or low > min(opening, close) or high < low:
            raise ValueError("DAILY_OHLC_INCONSISTENT")
        rows.append({"date": day.isoformat(), "provider_timestamp": candle[0],
                     "open": str(opening), "high": str(high), "low": str(low), "close": str(close),
                     "volume": _integer(candle[5]), "open_interest": _integer(candle[6])})
    rows.sort(key=lambda row: row["date"])
    result: dict[str, Any] = {
        "status": "UPSTOX_DAILY_STRUCTURE_ONLY_NOT_ADMISSION", "instrument_key": instrument_key,
        "binding": "CALLER_SUPPLIED_NOT_PROVIDER_SIGNED", "source_sha256": hashlib.sha256(raw).hexdigest(),
        "start": start, "end": end, "rows": rows, "row_count": len(rows),
        "availability_timestamp": "NOT_ESTABLISHED_BY_CANDLE_LABEL",
        "price_basis": "NOT_VERIFIED_AS_HISTORICAL_EXECUTABLE_RAW",
        "calendar_coverage_verified": False, "corporate_actions_verified": False,
        "rights_verified": False, "data_admission_authorised": False,
        "training_eligible": False, "performance_claim_verified": False,
        "network_calls": 0, "file_reads": 0, "writes": 0,
    }
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {**result, "decoded_sha256": hashlib.sha256(canonical.encode()).hexdigest()}
