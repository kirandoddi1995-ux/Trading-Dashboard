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
from iv_surface import calendar_total_variance_check


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
    FeatureDefinition(
        "option_volume_activity_robust_z", "1", "float", "prospective-option-chain",
        "Current contract volume minus the same-contract, same-capture-context rolling median, divided by 1.4826 times rolling MAD",
        "Current and every baseline snapshot must have first-receipt available_at no later than feature computation; every included snapshot must pass IV/no-arbitrage validation",
        maximum_age_seconds=120,
    ),
    FeatureDefinition(
        "option_oi_activity_robust_z", "1", "float", "prospective-option-chain",
        "Current contract open interest minus the same-contract, same-capture-context rolling median, divided by 1.4826 times rolling MAD",
        "Current and every baseline snapshot must have first-receipt available_at no later than feature computation; every included snapshot must pass IV/no-arbitrage validation",
        maximum_age_seconds=120,
    ),
    FeatureDefinition(
        "unusual_option_activity_score", "1", "float", "prospective-option-chain",
        "Positive maximum of separately measured rolling robust volume and open-interest z-scores; no fixed activity threshold is embedded",
        "Published only when both same-contract rolling baselines are PIT-complete and the current option row passed IV/no-arbitrage validation",
        maximum_age_seconds=120, minimum=0,
    ),
    FeatureDefinition(
        "put_call_oi_skew_near_money", "1", "float", "prospective-option-chain",
        "(put OI-call OI)/(put OI+call OI) for validated contracts with absolute model delta from 0.35 through 0.65",
        "All included option-chain rows must be available by feature time and pass IV/no-arbitrage validation; incomplete OI in the bucket makes the feature unavailable",
        maximum_age_seconds=120, minimum=-1, maximum=1,
    ),
    FeatureDefinition(
        "put_call_oi_skew_far_otm", "1", "float", "prospective-option-chain",
        "(put OI-call OI)/(put OI+call OI) for validated contracts with absolute model delta from 0.05 through 0.25",
        "All included option-chain rows must be available by feature time and pass IV/no-arbitrage validation; incomplete OI in the bucket makes the feature unavailable",
        maximum_age_seconds=120, minimum=-1, maximum=1,
    ),
    FeatureDefinition(
        "put_call_oi_skew_ntm_minus_fotm", "1", "float", "prospective-option-chain",
        "Near-money put/call OI imbalance minus far-OTM put/call OI imbalance",
        "Derived only from PIT-available, IV/no-arbitrage-valid rows with complete OI in both delta buckets",
        maximum_age_seconds=120, minimum=-2, maximum=2,
    ),
    FeatureDefinition(
        "iv_term_structure_steepness", "1", "float", "prospective-option-surface",
        "Least-squares slope of validated ATM executable-mid model IV percentage points against square-root years across expiries",
        "Each expiry surface must be first-received by feature time and the combined surface must pass calendar total-variance validation",
        maximum_age_seconds=120, minimum=-2000, maximum=2000,
    ),
    FeatureDefinition(
        "iv_skew_steepness", "1", "float", "prospective-option-surface",
        "Nearest-expiry OTM-wing executable-mid model IV percentage-point slope against log strike/spot moneyness",
        "Uses only first-received, IV/no-arbitrage-valid OTM puts below spot and calls above spot available by feature time",
        maximum_age_seconds=120, minimum=-5000, maximum=5000,
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


OPTION_SURFACE_REQUIRED = {
    "instrument_key", "expiry", "strike", "option_type", "years",
    "log_moneyness", "model_iv", "model_delta", "volume", "open_interest",
    "effective_at", "available_at", "production_valid",
}


def _pit_option_surface(surface: pd.DataFrame, *, as_of) -> tuple[pd.DataFrame, int]:
    """Return validated, first-known option rows without silently accepting future data."""
    if not isinstance(surface, pd.DataFrame) or surface.empty:
        raise ValueError("Option surface is empty")
    missing = OPTION_SURFACE_REQUIRED - set(surface.columns)
    if missing:
        raise ValueError(f"Option surface requires {sorted(missing)}")
    decision = _aware(as_of, "as_of")
    data = surface.copy()
    data["effective_at"] = data["effective_at"].map(
        lambda value: _aware(value, "effective_at")
    )
    data["available_at"] = data["available_at"].map(
        lambda value: _aware(value, "available_at")
    )
    if (data["effective_at"] > data["available_at"]).any():
        raise ValueError("Option surface has reversed effective/availability timestamps")
    if (data["available_at"] > decision).any():
        raise ValueError("Option surface contains data unavailable at feature time")

    def explicitly_valid(value):
        if isinstance(value, (bool, np.bool_)):
            return bool(value)
        if isinstance(value, (int, np.integer)) and not isinstance(value, bool):
            return int(value) == 1
        return False

    valid_mask = data["production_valid"].map(explicitly_valid)
    rejected = int((~valid_mask).sum())
    return data.loc[valid_mask].copy().reset_index(drop=True), rejected


def _numeric_nonnegative(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")
        result.loc[~np.isfinite(result[column]) | result[column].lt(0), column] = np.nan
    return result


def _rolling_robust_z(current: float, history: pd.Series) -> tuple[float | None, dict]:
    values = pd.to_numeric(history, errors="coerce")
    values = values[np.isfinite(values)]
    if values.empty:
        return None, {"count": 0, "median": None, "mad": None}
    median = float(values.median())
    mad = float((values - median).abs().median())
    scale = 1.4826 * mad
    if not math.isfinite(scale) or scale <= 0:
        return None, {"count": int(len(values)), "median": median, "mad": mad}
    return (float(current) - median) / scale, {
        "count": int(len(values)), "median": median, "mad": mad,
    }


def unusual_option_activity_features(current_surface: pd.DataFrame,
                                      history: pd.DataFrame, *, as_of,
                                      capture_context: str,
                                      rolling_window: int = 60,
                                      minimum_history: int = 20) -> pd.DataFrame:
    """Measure contract-level volume/OI surprises against a PIT rolling baseline.

    Volume is intraday cumulative, so mixing morning and afternoon snapshots would
    manufacture activity.  A caller-supplied capture context is therefore mandatory
    and historical rows from any other context are excluded.
    """
    context = str(capture_context or "").strip()
    if not context:
        raise ValueError("capture_context is required")
    if int(minimum_history) < 20 or int(rolling_window) < int(minimum_history):
        raise ValueError("rolling_window must cover at least 20 baseline snapshots")
    current, validation_rejected = _pit_option_surface(current_surface, as_of=as_of)
    history_valid, history_validation_rejected = _pit_option_surface(history, as_of=as_of)
    current = _numeric_nonnegative(current, ("volume", "open_interest"))
    history_valid = _numeric_nonnegative(history_valid, ("volume", "open_interest"))
    if "capture_context" not in history_valid.columns:
        raise ValueError("Historical option surface requires capture_context")
    history_valid = history_valid[
        history_valid["capture_context"].astype(str).eq(context)
    ]
    decision = _aware(as_of, "as_of")
    rows = []
    for _, row in current.iterrows():
        identifier = str(row.get("instrument_key") or "").strip()
        output = {
            "instrument_key": identifier or None,
            "expiry": row.get("expiry"), "strike": row.get("strike"),
            "option_type": row.get("option_type"), "capture_context": context,
            "feature_at": decision, "feature_status": "UNAVAILABLE",
            "option_volume_activity_robust_z": np.nan,
            "option_oi_activity_robust_z": np.nan,
            "unusual_option_activity_score": np.nan,
        }
        if not identifier or pd.isna(row["volume"]) or pd.isna(row["open_interest"]):
            output["failure"] = "Current volume/OI or contract identity is incomplete"
            rows.append(output)
            continue
        prior = history_valid[
            history_valid["instrument_key"].astype(str).eq(identifier)
            & history_valid["available_at"].lt(row["available_at"])
        ].sort_values("available_at").tail(int(rolling_window))
        complete = prior.dropna(subset=["volume", "open_interest"])
        if len(complete) < int(minimum_history):
            output.update(
                failure="Insufficient same-contract, same-context rolling history",
                baseline_count=int(len(complete)),
            )
            rows.append(output)
            continue
        volume_z, volume_baseline = _rolling_robust_z(row["volume"], complete["volume"])
        oi_z, oi_baseline = _rolling_robust_z(row["open_interest"], complete["open_interest"])
        output.update(
            volume_baseline_count=volume_baseline["count"],
            volume_baseline_median=volume_baseline["median"],
            volume_baseline_mad=volume_baseline["mad"],
            oi_baseline_count=oi_baseline["count"],
            oi_baseline_median=oi_baseline["median"],
            oi_baseline_mad=oi_baseline["mad"],
        )
        if volume_z is None or oi_z is None:
            output["failure"] = "Rolling baseline has no measurable variation"
            rows.append(output)
            continue
        output.update({
            "feature_status": "PASS", "failure": None,
            "option_volume_activity_robust_z": float(volume_z),
            "option_oi_activity_robust_z": float(oi_z),
            "unusual_option_activity_score": float(max(0.0, volume_z, oi_z)),
        })
        rows.append(output)
    result = pd.DataFrame(rows)
    result.attrs.update({
        "pit_verified": True, "consumed_by_scoring": False,
        "validation_rejected": validation_rejected,
        "history_validation_rejected": history_validation_rejected,
        "rolling_window": int(rolling_window), "minimum_history": int(minimum_history),
    })
    return result


def option_oi_skew_features(surface: pd.DataFrame, *, as_of,
                            near_delta=(0.35, 0.65), far_delta=(0.05, 0.25)) -> dict:
    """Contrast validated near-money and far-OTM put/call OI concentration."""
    valid, validation_rejected = _pit_option_surface(surface, as_of=as_of)
    valid = _numeric_nonnegative(valid, ("open_interest",))
    valid["model_delta"] = pd.to_numeric(valid["model_delta"], errors="coerce")
    valid.loc[~np.isfinite(valid["model_delta"]), "model_delta"] = np.nan
    valid["absolute_delta"] = valid["model_delta"].abs()
    failures = []
    values = {}
    diagnostics = {"validation_rejected": validation_rejected}
    skews = {}
    for label, bounds in (("near_money", near_delta), ("far_otm", far_delta)):
        low, high = map(float, bounds)
        if not 0 <= low < high <= 1:
            raise ValueError("Delta buckets must satisfy 0 <= low < high <= 1")
        bucket = valid[valid["absolute_delta"].between(low, high, inclusive="both")]
        if bucket.empty or bucket["open_interest"].isna().any():
            failures.append(f"{label} bucket has incomplete open interest")
            continue
        call_oi = float(bucket.loc[bucket["option_type"].eq("CE"), "open_interest"].sum())
        put_oi = float(bucket.loc[bucket["option_type"].eq("PE"), "open_interest"].sum())
        if call_oi <= 0 or put_oi <= 0:
            failures.append(f"{label} bucket requires positive call and put open interest")
            continue
        skews[label] = (put_oi - call_oi) / (put_oi + call_oi)
        diagnostics[label] = {
            "call_oi": call_oi, "put_oi": put_oi, "contract_count": int(len(bucket)),
            "absolute_delta_bounds": [low, high],
        }
    if "near_money" in skews:
        values["put_call_oi_skew_near_money"] = float(skews["near_money"])
    if "far_otm" in skews:
        values["put_call_oi_skew_far_otm"] = float(skews["far_otm"])
    if len(skews) == 2:
        values["put_call_oi_skew_ntm_minus_fotm"] = float(
            skews["near_money"] - skews["far_otm"]
        )
    return {
        "status": "PASS" if len(values) == 3 else "UNAVAILABLE",
        "values": values if len(values) == 3 else {},
        "failures": failures, "diagnostics": diagnostics,
        "pit_verified": True, "consumed_by_scoring": False,
    }


def iv_surface_shape_features(surface: pd.DataFrame, *, as_of,
                              maximum_atm_log_moneyness=0.05,
                              maximum_skew_log_moneyness=0.20) -> dict:
    """Compute term and nearest-expiry skew slopes from validated surface rows."""
    valid, validation_rejected = _pit_option_surface(surface, as_of=as_of)
    numeric = ("years", "log_moneyness", "model_iv", "model_delta")
    for column in numeric:
        valid[column] = pd.to_numeric(valid[column], errors="coerce")
    finite = np.isfinite(valid[list(numeric)].to_numpy(dtype=float)).all(axis=1)
    valid = valid.loc[finite & valid["years"].gt(0) & valid["model_iv"].gt(0)].copy()
    failures = []
    values = {}
    diagnostics = {"validation_rejected": validation_rejected,
                   "validated_rows": int(len(valid))}

    calendar = calendar_total_variance_check(valid)
    diagnostics["calendar_total_variance"] = calendar
    if calendar.get("status") != "PASS":
        failures.append("Term structure failed calendar total-variance validation")
    else:
        atm_points = []
        for years, expiry_rows in valid.groupby("years"):
            side_points = []
            for side in ("CE", "PE"):
                rows = expiry_rows[expiry_rows["option_type"].eq(side)]
                if rows.empty:
                    continue
                nearest = rows.loc[rows["log_moneyness"].abs().idxmin()]
                if abs(float(nearest["log_moneyness"])) <= float(maximum_atm_log_moneyness):
                    side_points.append(float(nearest["model_iv"]))
            if len(side_points) == 2:
                atm_points.append((float(years), float(np.mean(side_points))))
        if len(atm_points) < 2:
            failures.append("At least two expiries need validated call/put ATM IV")
        else:
            atm_points.sort()
            x = np.sqrt(np.array([item[0] for item in atm_points], dtype=float))
            y = np.array([item[1] for item in atm_points], dtype=float)
            if np.ptp(x) <= 1e-12:
                failures.append("Expiry tenors are not distinct")
            else:
                values["iv_term_structure_steepness"] = float(np.polyfit(x, y, 1)[0])
                diagnostics["atm_points"] = [
                    {"years": years, "model_iv_pct": iv} for years, iv in atm_points
                ]

    if valid.empty:
        failures.append("No validated IV rows remain")
    else:
        nearest_years = float(valid["years"].min())
        nearest = valid[np.isclose(valid["years"], nearest_years)].copy()
        wing = nearest[
            nearest["log_moneyness"].abs().le(float(maximum_skew_log_moneyness))
            & (
                (nearest["option_type"].eq("PE") & nearest["log_moneyness"].le(0))
                | (nearest["option_type"].eq("CE") & nearest["log_moneyness"].ge(0))
            )
        ]
        wing = wing.groupby("log_moneyness", as_index=False)["model_iv"].mean().sort_values(
            "log_moneyness"
        )
        if (len(wing) < 4 or not (wing["log_moneyness"] < 0).any()
                or not (wing["log_moneyness"] > 0).any()
                or np.ptp(wing["log_moneyness"].to_numpy(dtype=float)) < 0.05):
            failures.append("Nearest expiry needs four validated OTM-wing points spanning spot")
        else:
            values["iv_skew_steepness"] = float(np.polyfit(
                wing["log_moneyness"].to_numpy(dtype=float),
                wing["model_iv"].to_numpy(dtype=float), 1,
            )[0])
            diagnostics["skew_years"] = nearest_years
            diagnostics["skew_points"] = int(len(wing))

    expected = {"iv_term_structure_steepness", "iv_skew_steepness"}
    status = "PASS" if expected.issubset(values) else ("PARTIAL" if values else "UNAVAILABLE")
    return {
        "status": status, "values": values, "failures": failures,
        "diagnostics": diagnostics, "pit_verified": True,
        "consumed_by_scoring": False,
    }


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
