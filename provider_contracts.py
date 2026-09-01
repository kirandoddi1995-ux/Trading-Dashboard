"""Typed provider payload validation and stable error classification."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class ProviderErrorKind(str, Enum):
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    STALE_DATA = "stale_data"
    SCHEMA = "schema"
    TIMEOUT = "timeout"
    NETWORK = "network"
    SERVER = "server"
    PROGRAMMING = "programming"


class ProviderContractError(RuntimeError):
    def __init__(self, kind: ProviderErrorKind, message: str, status_code=None):
        super().__init__(message)
        self.kind, self.status_code = kind, status_code


def classify_provider_error(error=None, status_code=None) -> ProviderErrorKind:
    status = int(status_code) if status_code is not None else None
    if status in (401, 403): return ProviderErrorKind.AUTHENTICATION
    if status == 429: return ProviderErrorKind.RATE_LIMIT
    if status is not None and status >= 500: return ProviderErrorKind.SERVER
    name = type(error).__name__.lower() if error else ""
    if "timeout" in name: return ProviderErrorKind.TIMEOUT
    if any(part in name for part in ("connection", "network", "dns")): return ProviderErrorKind.NETWORK
    if isinstance(error, (KeyError, TypeError, ValueError)): return ProviderErrorKind.SCHEMA
    return ProviderErrorKind.PROGRAMMING


def require_mapping(value: Any, context: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise ProviderContractError(ProviderErrorKind.SCHEMA, f"{context} must be an object")
    return value


def finite_number(value, field: str, *, required=True):
    if value is None and not required: return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ProviderContractError(ProviderErrorKind.SCHEMA, f"{field} is not numeric") from exc
    if number != number or number in (float("inf"), float("-inf")):
        raise ProviderContractError(ProviderErrorKind.SCHEMA, f"{field} is not finite")
    return number


@dataclass(frozen=True)
class OptionGreeks:
    iv: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None

    @classmethod
    def parse(cls, payload):
        row = require_mapping(payload or {}, "option_greeks")
        return cls(*(finite_number(row.get(key), key, required=False) for key in ("iv", "delta", "gamma", "theta", "vega")))


@dataclass(frozen=True)
class OptionMarketData:
    ltp: float | None
    bid: float | None
    ask: float | None
    volume: float | None
    oi: float | None

    @classmethod
    def parse(cls, payload):
        row = require_mapping(payload, "option market_data")
        return cls(finite_number(row.get("ltp"), "ltp", required=False),
                   finite_number(row.get("bid_price"), "bid_price", required=False),
                   finite_number(row.get("ask_price"), "ask_price", required=False),
                   finite_number(row.get("volume"), "volume", required=False),
                   finite_number(row.get("oi"), "oi", required=False))
