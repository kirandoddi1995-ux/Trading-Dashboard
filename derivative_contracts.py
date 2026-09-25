"""Versioned derivatives reference data. No I/O or inferred exchange rules."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json


class FoundationError(ValueError):
    """Safe, non-secret blocking reason for derivative preflight."""


def stamp(value):
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise FoundationError("Timezone-aware source timestamp required") from None


def number(value, *, positive=False):
    try:
        if isinstance(value, bool) or value is None:
            raise ValueError
        result = Decimal(str(value))
        if not result.is_finite() or (positive and result <= 0):
            raise ValueError
        return result
    except (ValueError, InvalidOperation):
        raise FoundationError("Invalid numeric reference data") from None


def digest(value):
    def canonical(item):
        # JSONB may round-trip 1.0 as 1. Preserve numeric value, not JSON spelling;
        # tagged nodes keep numbers distinct from strings, booleans and objects.
        if item is None:
            return ["null"]
        if isinstance(item, bool):
            return ["bool", item]
        if isinstance(item, (int, float, Decimal)):
            numeric = number(item)
            text = format(numeric, "f")
            if "." in text:
                text = text.rstrip("0").rstrip(".")
            return ["number", "0" if numeric == 0 else text]
        if isinstance(item, dict):
            return ["object", [[k, canonical(v)] for k, v in sorted(item.items())]]
        if isinstance(item, (list, tuple)):
            return ["array", [canonical(v) for v in item]]
        return ["string", str(item)]
    return hashlib.sha256(json.dumps(canonical(value), separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class Contract:
    key: str
    underlying: str
    symbol: str
    exchange: str
    segment: str
    kind: str
    underlying_type: str
    tenor: str
    strike: Decimal
    lot: int
    tick: Decimal
    expiry: datetime
    session_open: datetime
    session_close: datetime
    settlement: str
    delivery: str
    version: str
    rule_version: str


def resolve_contract(master, rules, *, now):
    """Rules are reviewed, dated records; a BOD expiry marker is not a trading cutoff."""
    now = stamp(now)
    if not isinstance(master, dict) or not isinstance(rules, dict):
        raise FoundationError("Contract master or reviewed exchange rules unavailable")
    required = ("source", "known_at", "effective_from", "effective_until", "expiry_at",
                "session_open", "session_close", "settlement", "delivery",
                "corporate_action_version", "tenor", "tick_scale", "instrument_key",
                "master_hash", "exchange", "segment", "trading_status", "session_date")
    if any(rules.get(k) is None or rules.get(k) == "" for k in required):
        raise FoundationError("Incomplete reviewed exchange rules")
    if stamp(rules["known_at"]) > now or not stamp(rules["effective_from"]) <= now < stamp(rules["effective_until"]):
        raise FoundationError("Exchange rules are stale or not yet known")
    key, venue = master.get("instrument_key"), master.get("exchange")
    segment = master.get("segment")
    if venue not in {"NSE", "BSE"} or segment != venue + "_FO":
        raise FoundationError("Unsupported derivative venue/segment")
    if not isinstance(key, str) or not key.startswith(segment + "|"):
        raise FoundationError("Instrument identifier/venue mismatch")
    if (rules["instrument_key"] != key or rules["exchange"] != venue or
            rules["segment"] != segment or rules["master_hash"] != digest(master)):
        raise FoundationError("Contract/rule version mismatch")
    if rules["trading_status"] != "ACTIVE" or rules.get("corporate_action_status") != "VERIFIED":
        raise FoundationError("Trading status or corporate action unverified")
    kind = master.get("instrument_type")
    under_type = master.get("underlying_type")
    if kind not in {"CE", "PE", "FUT"} or under_type not in {"INDEX", "EQUITY"}:
        raise FoundationError("Unsupported derivative type")
    if not master.get("underlying_key") or not master.get("underlying_symbol"):
        raise FoundationError("Underlying identity unavailable")
    tenor = rules["tenor"]
    if tenor not in {"WEEKLY", "MONTHLY"}:
        raise FoundationError("Unsupported contract tenor")
    if master.get("weekly") is not (tenor == "WEEKLY"):
        raise FoundationError("Master tenor disagrees with exchange rules")
    if under_type == "EQUITY" and tenor != "MONTHLY":
        raise FoundationError("Unsupported stock tenor")
    expiry = stamp(rules["expiry_at"])
    # Compare dates in the rule's local offset; never assume a weekday or expiry hour.
    raw_expiry = datetime.fromtimestamp(float(number(master.get("expiry"))) / 1000, timezone.utc)
    local_zone = datetime.fromisoformat(str(rules["expiry_at"])).tzinfo
    if raw_expiry.astimezone(local_zone).date() != expiry.astimezone(local_zone).date():
        raise FoundationError("Master expiry date disagrees with reviewed cutoff")
    start, end = stamp(rules["session_open"]), stamp(rules["session_close"])
    session_local = datetime.fromisoformat(str(rules["session_open"]))
    if session_local.date().isoformat() != rules["session_date"] or now.astimezone(session_local.tzinfo).date() != session_local.date():
        raise FoundationError("Exchange session date mismatch")
    if not start <= now < min(end, expiry):
        raise FoundationError("Contract session closed or expired")
    lot = number(master.get("lot_size"), positive=True)
    if lot != lot.to_integral_value():
        raise FoundationError("Non-integral lot size")
    tick = number(master.get("tick_size"), positive=True) * number(rules["tick_scale"], positive=True)
    strike = number(master.get("strike_price", 0))
    if kind != "FUT" and strike <= 0:
        raise FoundationError("Invalid option strike")
    if rules["settlement"] not in {"CASH", "PHYSICAL"}:
        raise FoundationError("Unknown settlement obligation")
    if venue == "NSE" and tenor == "WEEKLY" and master["underlying_key"] not in rules.get("weekly_underlyings", []):
        raise FoundationError("Weekly underlying not authorized by reviewed exchange rules")
    return Contract(key, master["underlying_key"], master["underlying_symbol"], venue,
                    segment, kind, under_type, tenor, strike, int(lot), tick, expiry,
                    start, end, rules["settlement"], rules["delivery"], digest(master), digest(rules))
