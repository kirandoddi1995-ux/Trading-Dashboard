"""V3 normalization and executable, timestamp-bounded snapshots (not fill evidence)."""
from dataclasses import dataclass
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from derivative_contracts import FoundationError, number, stamp, digest


def decode_v3(message, *, received_at, generation):
    """Do not merge partial updates into a fresh-looking book or invent exchange time."""
    received = stamp(received_at)
    source_ms = message.get("currentTs", message.get("current_ts"))
    source_at = (datetime.fromtimestamp(float(number(source_ms)) / 1000, timezone.utc)
                 if source_ms is not None else None)
    result = {}
    for key, feed in (message.get("feeds") or {}).items():
        full = feed.get("fullFeed", feed.get("full_feed", {}))
        market = full.get("marketFF", full.get("market_ff", {}))
        index = full.get("indexFF", full.get("index_ff", {}))
        ltpc = market.get("ltpc") or index.get("ltpc") or feed.get("ltpc") or {}
        levels = market.get("marketLevel", market.get("market_level", {}))
        depth = levels.get("bidAskQuote", levels.get("bid_ask_quote", []))
        best = depth[0] if depth else {}
        result[key] = dict(key=key, source_at=source_at, received_at=received,
                           exchange_at=None, last_trade_at=ltpc.get("ltt"),
                           generation=generation, reference=ltpc.get("ltp"),
                           bid=best.get("bidP", best.get("bid_p")),
                           ask=best.get("askP", best.get("ask_p")),
                           bid_size=best.get("bidQ", best.get("bid_q")),
                           ask_size=best.get("askQ", best.get("ask_q")),
                           oi=market.get("oi"), iv=market.get("iv"),
                           volume=market.get("vtt"),
                           greeks=market.get("optionGreeks", market.get("option_greeks")),
                           source="UPSTOX_V3_FULL")
    return result


@dataclass(frozen=True)
class QuotePolicy:
    max_age_seconds: float
    max_skew_seconds: float
    max_spread_fraction: Decimal
    version: str

    def validate(self):
        if not self.version:
            raise FoundationError("Quote policy version required")
        for value in (self.max_age_seconds, self.max_skew_seconds, self.max_spread_fraction):
            number(value, positive=True)


def snapshot(contract, quotes, *, now, generation, quantity, side, policy,
             extra_required=()):
    policy.validate()
    now = stamp(now)
    qty = number(quantity, positive=True)
    if qty != qty.to_integral_value() or qty % contract.lot:
        raise FoundationError("Quantity must be whole contract lots")
    if side not in {"BUY", "SELL"}:
        raise FoundationError("Unknown order side")
    times, retained = [], {}
    keys = tuple(dict.fromkeys((contract.key, contract.underlying, *extra_required)))
    for key in keys:
        q = quotes.get(key)
        if not q or q.get("key") != key or q.get("generation") != generation or q.get("source") != "UPSTOX_V3_FULL":
            raise FoundationError("Missing, mismatched or pre-reconnect quote")
        source, received = stamp(q.get("source_at")), stamp(q.get("received_at"))
        age = (now - source).total_seconds()
        if not 0 <= age <= policy.max_age_seconds or not 0 <= (now - received).total_seconds() <= policy.max_age_seconds or source > received:
            raise FoundationError("Stale or future-dated quote")
        times.append(source)
        retained[key] = dict(deepcopy(q), age_seconds=age)
        if key != contract.key:
            if key == contract.underlying and contract.underlying_type == "INDEX":
                number(q.get("reference"), positive=True)
                index_time = datetime.fromtimestamp(float(number(q.get("last_trade_at"))) / 1000, timezone.utc)
                if not 0 <= (now - index_time).total_seconds() <= policy.max_age_seconds:
                    raise FoundationError("Stale index reference value")
                times.append(index_time)
            else:
                # A fresh packet can carry an old LTP. Use a validated stock/futures
                # book midpoint as reference, never treat packet age as trade age.
                ref_bid, ref_ask = number(q.get("bid"), positive=True), number(q.get("ask"), positive=True)
                number(q.get("bid_size"), positive=True)
                number(q.get("ask_size"), positive=True)
                if ref_bid > ref_ask or (ref_ask-ref_bid)/((ref_ask+ref_bid)/2) > number(policy.max_spread_fraction):
                    raise FoundationError("Invalid required reference book")
                retained[key]["reference"] = (ref_bid + ref_ask) / 2
    if (max(times) - min(times)).total_seconds() > policy.max_skew_seconds:
        raise FoundationError("Required quote timestamps are not aligned")
    q = retained[contract.key]
    bid, ask = number(q.get("bid"), positive=True), number(q.get("ask"), positive=True)
    bid_size, ask_size = number(q.get("bid_size"), positive=True), number(q.get("ask_size"), positive=True)
    if bid > ask or bid % contract.tick or ask % contract.tick:
        raise FoundationError("Crossed book or tick-size mismatch")
    spread = ask - bid
    if spread / ((ask + bid) / 2) > number(policy.max_spread_fraction):
        raise FoundationError("Spread exceeds quote policy")
    if qty > (ask_size if side == "BUY" else bid_size):
        raise FoundationError("Insufficient executable top-of-book size")
    if contract.kind != "FUT":
        for name in ("delta", "gamma", "theta", "vega"):
            number((q.get("greeks") or {}).get(name))
        number(q.get("iv"), positive=True)
        if number(q.get("oi")) < 0:
            raise FoundationError("Invalid open interest")
        delta = number(q["greeks"]["delta"])
        if not (0 <= delta <= 1 if contract.kind == "CE" else -1 <= delta <= 0):
            raise FoundationError("Invalid option delta sign/range")
        if any(number(q["greeks"][name]) < 0 for name in ("gamma", "vega")):
            raise FoundationError("Invalid option Greek range")
    record = dict(contract_version=contract.version, rule_version=contract.rule_version,
                  policy_version=policy.version, quotes=retained, side=side, quantity=int(qty),
                  reference_price=ask if side == "BUY" else bid, spread=spread,
                  available_size=ask_size if side == "BUY" else bid_size,
                  validated_at=now,
                  expires_at=min(contract.expiry, contract.session_close,
                                 min(times) + timedelta(seconds=float(policy.max_age_seconds))))
    return dict(record, snapshot_id=digest(record))
