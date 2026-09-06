"""Independent, fail-closed validation contracts for every non-equity live path."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

import pandas as pd

from calibration_artifacts import build_calibration_artifact
from live_evidence import aware_utc
from prediction_validation import CalibrationPolicy, run_advanced_chronological_validation


@dataclass(frozen=True)
class StrategyValidationSpec:
    strategy_id: str
    asset_class: str
    target_version: str
    horizon_sessions: int
    score_feature: str
    required_path_columns: tuple[str, ...]

    @property
    def namespace(self) -> str:
        return f"{self.strategy_id}|{self.asset_class}|{self.target_version}|{self.horizon_sessions}"


INDEPENDENT_VALIDATION_SPECS = {
    "options": StrategyValidationSpec(
        "index-options-directional-v1", "options", "options-premium-barrier-v1", 1,
        "options_signal_score",
        ("contract_id", "expiry", "option_bid", "option_ask", "underlying_observed_at",
         "greeks_valid", "no_arbitrage_valid"),
    ),
    "futures": StrategyValidationSpec(
        "index-futures-directional-v1", "futures", "futures-atr-barrier-v1", 1,
        "futures_signal_score",
        ("contract_id", "contract_multiplier", "roll_id", "execution_bid", "execution_ask"),
    ),
    "mcx": StrategyValidationSpec(
        "mcx-directional-v1", "commodity_futures", "mcx-atr-barrier-v1", 1,
        "mcx_signal_score",
        ("contract_id", "contract_multiplier", "roll_id", "execution_bid", "execution_ask"),
    ),
    "smc": StrategyValidationSpec(
        "smc-structure-v1", "equity_smc", "smc-atr-structure-v1", 15,
        "smc_signal_score",
        ("setup_id", "structure_confirmed", "execution_bid", "execution_ask"),
    ),
}

COMMON_COLUMNS = {
    "strategy_id", "asset_class", "target_version", "horizon_sessions",
    "decision_timestamp", "feature_available_at", "quote_observed_at", "quote_received_at",
    "entry_timestamp", "label_end_timestamp", "score", "target_before_stop", "excess_return",
    "pit_snapshot_id", "round_trip_cost_bps",
}


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def validate_strategy_dataset(rows: pd.DataFrame, spec: StrategyValidationSpec) -> dict[str, Any]:
    """Validate path identity, PIT ordering, executable inputs and label chronology."""
    if not isinstance(rows, pd.DataFrame) or rows.empty:
        return {"status": "INSUFFICIENT_EVIDENCE", "failures": ["No observations were supplied"]}
    missing = (COMMON_COLUMNS | set(spec.required_path_columns)) - set(rows.columns)
    if missing:
        return {"status": "INVALID_EVIDENCE", "failures": [f"Missing columns: {sorted(missing)}"]}
    failures = []
    expected = {
        "strategy_id": spec.strategy_id, "asset_class": spec.asset_class,
        "target_version": spec.target_version, "horizon_sessions": spec.horizon_sessions,
    }
    for name, value in expected.items():
        if not rows[name].map(str).eq(str(value)).all():
            failures.append(f"Mixed or incorrect {name}; equity or cross-path evidence is forbidden")
    normalized = rows.copy()
    for index, row in rows.iterrows():
        try:
            decision = aware_utc(row["decision_timestamp"], name="decision_timestamp")
            feature = aware_utc(row["feature_available_at"], name="feature_available_at")
            observed = aware_utc(row["quote_observed_at"], name="quote_observed_at")
            received = aware_utc(row["quote_received_at"], name="quote_received_at")
            entry = aware_utc(row["entry_timestamp"], name="entry_timestamp")
            label_end = aware_utc(row["label_end_timestamp"], name="label_end_timestamp")
            if not (feature <= decision and observed <= received <= decision < entry <= label_end):
                failures.append(f"Row {index} violates PIT/quote/entry/label timestamp ordering")
            normalized.loc[index, "as_of_date"] = decision.isoformat()
            normalized.loc[index, "label_end_date"] = label_end.isoformat()
        except ValueError as exc:
            failures.append(f"Row {index}: {exc}")
        if not _finite(row["score"]) or not _finite(row["excess_return"]):
            failures.append(f"Row {index} has a non-finite score or return")
        if str(row["target_before_stop"]) not in {"0", "1", "0.0", "1.0"}:
            failures.append(f"Row {index} has a non-binary outcome")
        if not str(row["pit_snapshot_id"]).strip():
            failures.append(f"Row {index} has no immutable PIT snapshot identity")
        if not _finite(row["round_trip_cost_bps"]) or float(row["round_trip_cost_bps"]) < 0:
            failures.append(f"Row {index} has invalid execution costs")
    if spec.asset_class == "options":
        for flag in ("greeks_valid", "no_arbitrage_valid"):
            if not rows[flag].map(lambda value: value is True).all():
                failures.append(f"Options evidence contains {flag}=false")
        if not rows.apply(lambda row: _finite(row["option_bid"]) and _finite(row["option_ask"])
                          and 0 <= float(row["option_bid"]) <= float(row["option_ask"]), axis=1).all():
            failures.append("Options evidence lacks valid executable bid/ask")
    else:
        if not rows.apply(lambda row: _finite(row["execution_bid"]) and _finite(row["execution_ask"])
                          and 0 <= float(row["execution_bid"]) <= float(row["execution_ask"]), axis=1).all():
            failures.append("Evidence lacks valid executable bid/ask")
    if failures:
        return {"status": "INVALID_EVIDENCE", "failures": sorted(set(failures))}
    normalized.attrs.update({
        "pit_verified": True, "costs_applied": True,
        "strategy_version": spec.strategy_id, "target_version": spec.target_version,
        "horizon_sessions": spec.horizon_sessions, "asset_class": spec.asset_class,
        "validation_namespace": spec.namespace,
    })
    return {"status": "PASS", "failures": [], "dataset": normalized}


def run_independent_strategy_validation(
    rows: pd.DataFrame,
    spec: StrategyValidationSpec,
    *,
    policy: CalibrationPolicy = CalibrationPolicy(),
    **validation_options,
) -> dict[str, Any]:
    check = validate_strategy_dataset(rows, spec)
    if check["status"] != "PASS":
        return {**check, "validation_namespace": spec.namespace, "calibration_reusable_by": [spec.namespace]}
    result = run_advanced_chronological_validation(
        check["dataset"], policy=policy, **validation_options,
    )
    return {
        **result,
        "strategy_id": spec.strategy_id, "asset_class": spec.asset_class,
        "target_version": spec.target_version, "horizon_sessions": spec.horizon_sessions,
        "validation_namespace": spec.namespace,
        "calibration_reusable_by": [spec.namespace],
        "validated_dataset": check["dataset"],
    }


def build_independent_calibration_candidate(
    result: Mapping[str, Any],
    *,
    spec: StrategyValidationSpec,
    run_id: str,
    feature_schema_hash: str,
    valid_days: int = 30,
) -> dict[str, Any]:
    """Build a path-specific candidate; never accepts a result from another namespace."""
    if str(result.get("validation_namespace")) != spec.namespace:
        raise ValueError("Validation result belongs to another strategy/asset/target/horizon")
    if list(result.get("calibration_reusable_by") or []) != [spec.namespace]:
        raise ValueError("Calibration reuse scope is not path-exclusive")
    dataset = result.get("validated_dataset")
    return build_calibration_artifact(
        result, dataset, run_id=run_id, strategy_id=spec.strategy_id,
        target_version=spec.target_version, horizon_sessions=spec.horizon_sessions,
        feature_schema_hash=feature_schema_hash, asset_class=spec.asset_class,
        score_feature=spec.score_feature, valid_days=valid_days,
    )
