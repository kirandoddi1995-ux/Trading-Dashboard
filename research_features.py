"""PIT-safe research feature calculations that are structurally non-scoring.

This module has no imports from live governance, calibration, model registry or
order execution.  Outputs may be registered and stored as prospective research
observations, but cannot unlock a recommendation.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from decision_evidence import FeatureDefinition, FeatureRegistry


UTC = dt.timezone.utc


def _aware(value, name="timestamp") -> dt.datetime:
    if isinstance(value, dt.datetime):
        parsed = value
    else:
        try:
            parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be timezone-aware") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _finite(value, name, *, minimum=None):
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(parsed) or (minimum is not None and parsed < minimum):
        raise ValueError(f"{name} must be finite")
    return parsed


RESEARCH_FEATURE_DEFINITIONS = (
    FeatureDefinition(
        "order_book_imbalance_d5", "1", "float", "licensed-primary-depth",
        "(sum bid quantity - sum ask quantity) / total visible D5 quantity",
        "Provider exchange timestamp <= first collector receipt <= feature decision time",
        maximum_age_seconds=120, minimum=-1, maximum=1,
    ),
    FeatureDefinition(
        "microprice_d5", "1", "float", "licensed-primary-depth",
        "Best-level quantity-weighted opposite-side microprice",
        "Provider exchange timestamp <= first collector receipt <= feature decision time",
        maximum_age_seconds=120, minimum=0,
    ),
    FeatureDefinition(
        "secondary_quote_spread_bps", "1", "float", "licensed-secondary-kite",
        "10000 * (ask-bid) / midpoint from independent NSE quote",
        "Kite exchange timestamp <= receipt timestamp <= reconciliation decision time",
        maximum_age_seconds=5, minimum=0,
    ),
    FeatureDefinition(
        "cross_sectional_return_rank", "1", "float", "prospective-equity-panel",
        "Percentile rank of PIT return within the same timestamped universe snapshot",
        "Every panel member must be available no later than the snapshot decision time",
        maximum_age_seconds=300, minimum=0, maximum=1,
    ),
    FeatureDefinition(
        "cross_sectional_return_robust_z", "1", "float", "prospective-equity-panel",
        "Median/MAD standardized PIT return within one universe snapshot",
        "Every panel member must be available no later than the snapshot decision time",
        maximum_age_seconds=300, minimum=-20, maximum=20,
    ),
    FeatureDefinition(
        "leader_return_lag_1", "1", "float", "prospective-lead-lag-panel",
        "Previous completed interval return of the configured leader instrument",
        "Leader interval availability must precede the target feature timestamp",
        maximum_age_seconds=900, minimum=-1, maximum=1,
    ),
    FeatureDefinition(
        "lead_lag_rolling_correlation", "1", "float", "prospective-lead-lag-panel",
        "Rolling correlation of lagged leader return with target return",
        "Only completed intervals ending no later than feature time are included",
        maximum_age_seconds=900, minimum=-1, maximum=1,
    ),
    FeatureDefinition(
        "minutes_to_known_event", "1", "float", "official-economic-calendar",
        "Minutes from decision to next event that was published before decision time",
        "Event publication/availability timestamp must be <= decision timestamp",
        maximum_age_seconds=86400 * 31, minimum=0, maximum=60 * 24 * 366,
    ),
    FeatureDefinition(
        "minutes_since_known_event", "1", "float", "official-economic-calendar",
        "Minutes since previous event that was published before decision time",
        "Event publication/availability timestamp must be <= decision timestamp",
        maximum_age_seconds=86400 * 31, minimum=0, maximum=60 * 24 * 366,
    ),
)
RESEARCH_DEFINITIONS_BY_NAME = {item.name: item for item in RESEARCH_FEATURE_DEFINITIONS}


def register_research_features(registry: FeatureRegistry, *, registered_at=None) -> list[dict]:
    return [registry.register(item, registered_at=registered_at) for item in RESEARCH_FEATURE_DEFINITIONS]


def publish_research_features(writer, *, instrument_key: str, values: Mapping[str, float],
                              effective_at, available_at) -> dict:
    """Pass calculated values through the shared registry/quality/storage path."""
    stored, rejected = 0, 0
    for name, value in dict(values or {}).items():
        definition = RESEARCH_DEFINITIONS_BY_NAME.get(str(name))
        if definition is None:
            raise ValueError(f"Unregistered research feature: {name}")
        result = writer.record(
            instrument_key=str(instrument_key), definition=definition, value=value,
            effective_at=effective_at, available_at=available_at, observed_at=available_at,
        )
        stored += int(bool(result.get("stored")))
        rejected += int(not bool(result.get("stored")))
    return {"stored": stored, "rejected": rejected, "consumed_by_scoring": False}


def secondary_quote_features(*, bid, ask) -> dict:
    bid_value, ask_value = _finite(bid, "secondary bid", minimum=0), _finite(
        ask, "secondary ask", minimum=0,
    )
    if bid_value <= 0 or ask_value <= 0 or bid_value > ask_value:
        raise ValueError("Secondary quote is crossed or non-positive")
    midpoint = (bid_value + ask_value) / 2
    return {"secondary_quote_spread_bps": (ask_value - bid_value) / midpoint * 10_000}


def order_book_features(buy_levels: Sequence[Mapping], sell_levels: Sequence[Mapping]) -> dict:
    buys, sells = list(buy_levels or ()), list(sell_levels or ())
    if not buys or not sells or len(buys) > 5 or len(sells) > 5:
        raise ValueError("D5 order book requires one to five levels on both sides")
    bid_prices = [_finite(row.get("price"), "bid price", minimum=0) for row in buys]
    ask_prices = [_finite(row.get("price"), "ask price", minimum=0) for row in sells]
    bid_qty = [_finite(row.get("quantity"), "bid quantity", minimum=0) for row in buys]
    ask_qty = [_finite(row.get("quantity"), "ask quantity", minimum=0) for row in sells]
    if min(bid_prices) <= 0 or min(ask_prices) <= 0 or bid_prices[0] > ask_prices[0]:
        raise ValueError("D5 order book is crossed or contains non-positive prices")
    total_bid, total_ask = sum(bid_qty), sum(ask_qty)
    if total_bid + total_ask <= 0 or bid_qty[0] + ask_qty[0] <= 0:
        raise ValueError("D5 visible quantities are empty")
    midpoint = (bid_prices[0] + ask_prices[0]) / 2
    return {
        "order_book_imbalance_d5": (total_bid - total_ask) / (total_bid + total_ask),
        "microprice_d5": (
            ask_prices[0] * bid_qty[0] + bid_prices[0] * ask_qty[0]
        ) / (bid_qty[0] + ask_qty[0]),
        "spread_bps": (ask_prices[0] - bid_prices[0]) / midpoint * 10_000,
        "visible_bid_quantity": total_bid, "visible_ask_quantity": total_ask,
    }


def cross_sectional_features(frame: pd.DataFrame, *, snapshot_at,
                             value_column="return_1d") -> pd.DataFrame:
    required = {"instrument_key", "effective_at", "available_at", value_column}
    if not isinstance(frame, pd.DataFrame) or frame.empty or not required.issubset(frame.columns):
        raise ValueError(f"Cross-sectional panel requires {sorted(required)}")
    decision = _aware(snapshot_at, "snapshot_at")
    data = frame.copy()
    data["effective_at"] = data["effective_at"].map(lambda value: _aware(value, "effective_at"))
    data["available_at"] = data["available_at"].map(lambda value: _aware(value, "available_at"))
    if (data["available_at"] > decision).any() or (data["effective_at"] > data["available_at"]).any():
        raise ValueError("Cross-sectional panel contains future or reversed availability")
    if data["instrument_key"].astype(str).duplicated().any():
        raise ValueError("Cross-sectional snapshot contains duplicate instruments")
    values = pd.to_numeric(data[value_column], errors="coerce")
    if not np.isfinite(values.to_numpy(dtype=float)).all() or len(values) < 3:
        raise ValueError("Cross-sectional panel needs at least three finite values")
    median = float(values.median())
    mad = float((values - median).abs().median())
    data["cross_sectional_return_rank"] = values.rank(method="average", pct=True)
    data["cross_sectional_return_robust_z"] = 0.0 if mad == 0 else (values - median) / (1.4826 * mad)
    data["feature_at"] = decision
    data.attrs.update({"pit_verified": True, "consumed_by_scoring": False})
    return data


def lead_lag_features(frame: pd.DataFrame, *, leader: str, targets: Iterable[str],
                      window=20) -> pd.DataFrame:
    required = {"instrument_key", "interval_end", "available_at", "return"}
    if not isinstance(frame, pd.DataFrame) or frame.empty or not required.issubset(frame.columns):
        raise ValueError(f"Lead-lag panel requires {sorted(required)}")
    if int(window) < 5:
        raise ValueError("Lead-lag window must be at least five completed intervals")
    data = frame.copy()
    data["interval_end"] = data["interval_end"].map(lambda value: _aware(value, "interval_end"))
    data["available_at"] = data["available_at"].map(lambda value: _aware(value, "available_at"))
    if (data["available_at"] < data["interval_end"]).any():
        raise ValueError("A return cannot be available before its interval ends")
    data["return"] = pd.to_numeric(data["return"], errors="coerce")
    if not np.isfinite(data["return"].to_numpy(dtype=float)).all():
        raise ValueError("Lead-lag returns must be finite")
    if data.duplicated(["instrument_key", "interval_end"]).any():
        raise ValueError("Lead-lag panel contains duplicate instrument intervals")
    pivot = data.pivot(index="interval_end", columns="instrument_key", values="return").sort_index()
    if str(leader) not in pivot:
        raise ValueError("Configured leader is absent")
    leader_lag = pivot[str(leader)].shift(1)
    rows = []
    for target in dict.fromkeys(str(value) for value in targets):
        if target not in pivot:
            continue
        correlation = leader_lag.rolling(int(window), min_periods=int(window)).corr(pivot[target])
        for timestamp in pivot.index:
            lag_value, corr_value = leader_lag.loc[timestamp], correlation.loc[timestamp]
            if pd.isna(lag_value) or pd.isna(corr_value):
                continue
            rows.append({
                "instrument_key": target, "leader": str(leader), "feature_at": timestamp,
                "leader_return_lag_1": float(lag_value),
                "lead_lag_rolling_correlation": float(corr_value),
            })
    output = pd.DataFrame(rows)
    output.attrs.update({"pit_verified": True, "consumed_by_scoring": False})
    return output


@dataclass(frozen=True)
class CalendarEvent:
    event_id: str
    category: str
    event_at: dt.datetime
    published_at: dt.datetime
    available_at: dt.datetime
    source: str


def parse_official_calendar(rows: Iterable[Mapping], *, collected_at) -> list[CalendarEvent]:
    receipt = _aware(collected_at, "collected_at")
    events = []
    for raw in rows or ():
        row = dict(raw or {})
        event_at = _aware(row.get("event_at"), "event_at")
        published = _aware(row.get("published_at"), "published_at")
        available = _aware(row.get("available_at") or receipt, "available_at")
        source = str(row.get("source") or "").strip()
        if not source or available > receipt or published > available:
            raise ValueError("Calendar event lacks valid official publication lineage")
        events.append(CalendarEvent(
            str(row.get("event_id") or "").strip(), str(row.get("category") or "").strip().upper(),
            event_at, published, available, source,
        ))
    if any(not item.event_id or item.category not in {"RBI_POLICY", "UNION_BUDGET", "MACRO_RELEASE"}
           for item in events):
        raise ValueError("Calendar event identity/category is invalid")
    return events


def calendar_distance_features(decision_at, events: Iterable[CalendarEvent]) -> dict[str, dict]:
    decision = _aware(decision_at, "decision_at")
    known = [item for item in events if item.available_at <= decision and item.published_at <= decision]
    output = {}
    for category in ("RBI_POLICY", "UNION_BUDGET", "MACRO_RELEASE"):
        group = [item for item in known if item.category == category]
        before = [item for item in group if item.event_at <= decision]
        after = [item for item in group if item.event_at > decision]
        output[category] = {
            "minutes_since_known_event": (
                (decision - max(before, key=lambda item: item.event_at).event_at).total_seconds() / 60
                if before else None
            ),
            "minutes_to_known_event": (
                (min(after, key=lambda item: item.event_at).event_at - decision).total_seconds() / 60
                if after else None
            ),
            "known_event_ids": [item.event_id for item in group],
        }
    return output
