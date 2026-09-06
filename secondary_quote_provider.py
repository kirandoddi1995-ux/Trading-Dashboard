"""Licensed, read-only secondary NSE quote integration.

The initial adapter targets Zerodha Kite Connect v3.  It deliberately exposes
no order methods and remains unavailable until explicit credentials and an
instrument mapping are configured.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
from dataclasses import dataclass
from typing import Iterable, Mapping


UTC = dt.timezone.utc
KITE_QUOTE_URL = "https://api.kite.trade/quote"


class SecondaryQuoteUnavailable(RuntimeError):
    pass


def _aware(value) -> dt.datetime:
    if isinstance(value, dt.datetime):
        parsed = value
    else:
        try:
            parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise SecondaryQuoteUnavailable("Secondary quote timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SecondaryQuoteUnavailable("Secondary quote timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _finite(value, name: str, *, minimum=None):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SecondaryQuoteUnavailable(f"{name} is invalid") from exc
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise SecondaryQuoteUnavailable(f"{name} is invalid")
    return result


@dataclass(frozen=True)
class SecondaryQuote:
    instrument_key: str
    provider_symbol: str
    price: float
    bid: float
    ask: float
    exchange_at: str
    received_at: str
    source: str = "ZERODHA_KITE_V3"


class KiteSecondaryQuoteProvider:
    def __init__(self, *, api_key: str, access_token: str,
                 symbol_map: Mapping[str, str], session, endpoint=KITE_QUOTE_URL):
        if not str(api_key).strip() or not str(access_token).strip():
            raise SecondaryQuoteUnavailable("Kite API key and access token are required")
        self.api_key = str(api_key).strip()
        self.access_token = str(access_token).strip()
        self.symbol_map = {str(key): str(value) for key, value in dict(symbol_map or {}).items()}
        if not self.symbol_map or any(not value.startswith("NSE:") for value in self.symbol_map.values()):
            raise SecondaryQuoteUnavailable("An explicit NSE instrument mapping is required")
        self.session = session
        self.endpoint = str(endpoint)

    @classmethod
    def from_environment(cls, session, environ=None):
        environ = environ or os.environ
        if str(environ.get("SECONDARY_QUOTE_PROVIDER") or "").upper() != "KITE":
            raise SecondaryQuoteUnavailable("Secondary quote provider is not enabled as KITE")
        try:
            symbol_map = json.loads(str(environ.get("SECONDARY_QUOTE_SYMBOL_MAP_JSON") or "{}"))
        except json.JSONDecodeError as exc:
            raise SecondaryQuoteUnavailable("Secondary quote symbol map is invalid JSON") from exc
        return cls(
            api_key=environ.get("KITE_API_KEY", ""),
            access_token=environ.get("KITE_ACCESS_TOKEN", ""),
            symbol_map=symbol_map, session=session,
        )

    def fetch(self, instrument_keys: Iterable[str], *, now=None) -> dict[str, SecondaryQuote]:
        keys = list(dict.fromkeys(str(key) for key in instrument_keys))
        missing = [key for key in keys if key not in self.symbol_map]
        if missing:
            raise SecondaryQuoteUnavailable(f"Secondary symbol mapping missing for {len(missing)} instruments")
        received = _aware(now or dt.datetime.now(UTC))
        output: dict[str, SecondaryQuote] = {}
        reverse = {self.symbol_map[key]: key for key in keys}
        for offset in range(0, len(keys), 500):
            symbols = [self.symbol_map[key] for key in keys[offset:offset + 500]]
            response = self.session.get(
                self.endpoint, params=[("i", symbol) for symbol in symbols],
                headers={"X-Kite-Version": "3",
                         "Authorization": f"token {self.api_key}:{self.access_token}"},
                timeout=(5, 20),
            )
            if int(getattr(response, "status_code", 0)) != 200:
                raise SecondaryQuoteUnavailable(
                    f"Kite quote request failed with HTTP {getattr(response, 'status_code', 0)}"
                )
            payload = response.json()
            data = payload.get("data") if isinstance(payload, Mapping) else None
            if not isinstance(data, Mapping):
                raise SecondaryQuoteUnavailable("Kite quote response has no data object")
            for symbol, raw in data.items():
                if symbol not in reverse or not isinstance(raw, Mapping):
                    continue
                depth = raw.get("depth") or {}
                buys, sells = depth.get("buy") or [], depth.get("sell") or []
                if not buys or not sells:
                    continue
                bid = _finite(buys[0].get("price"), "secondary bid", minimum=0)
                ask = _finite(sells[0].get("price"), "secondary ask", minimum=0)
                price = _finite(raw.get("last_price"), "secondary last price", minimum=0)
                if bid <= 0 or ask <= 0 or price <= 0 or bid > ask:
                    continue
                timestamp = _aware(raw.get("timestamp"))
                key = reverse[symbol]
                output[key] = SecondaryQuote(
                    key, symbol, price, bid, ask, timestamp.isoformat(), received.isoformat(),
                )
        absent = sorted(set(keys) - set(output))
        if absent:
            raise SecondaryQuoteUnavailable(f"Secondary quotes missing or invalid for {len(absent)} instruments")
        return output


def reconciliation_payload(quote: SecondaryQuote) -> dict:
    return {
        "price": quote.price, "bid": quote.bid, "ask": quote.ask,
        "exchange_at": quote.exchange_at, "received_at": quote.received_at,
        "source": quote.source,
    }
