"""Read-only, evidence-spine-backed model-readiness progress.

This module never creates observations, trains a model, or changes governance.
It counts only immutable DECISION_EVALUATED/OUTCOME_MATURED pairs supplied by
the durable repository and reports the exact production policy thresholds.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
from dataclasses import dataclass
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

from prediction_validation import chronological_holdout_split, purged_walk_forward_splits


UTC = dt.timezone.utc


@dataclass(frozen=True)
class ProgressPolicy:
    minimum_total_samples: int = 1000
    minimum_oof_samples: int = 500
    minimum_holdout_samples: int = 500
    minimum_observation_days: int = 120
    minimum_holdout_dates: int = 20
    holdout_fraction: float = 0.15
    folds: int = 5
    minimum_fold_training_samples: int = 200
    embargo_sessions: int = 20


@dataclass(frozen=True)
class AssetEvidenceContract:
    key: str
    label: str
    asset_classes: tuple[str, ...]
    strategy_id: str
    target_version: str
    horizon_sessions: int
    required_features: tuple[str, ...]
    independent_pipeline_available: bool


ASSET_CONTRACTS = (
    AssetEvidenceContract(
        "equity", "Equity", ("equity",), "equity-scanner-v19.0",
        "net-excess-execution-v2", 5, ("scanner_composite_score",), True,
    ),
    AssetEvidenceContract(
        "options", "Options", ("options",), "index-options-directional-v1",
        "options-premium-barrier-v1", 1, ("market_bias_score", "dte"), False,
    ),
    AssetEvidenceContract(
        "futures", "Futures", ("futures", "index_futures"),
        "index-futures-directional-v1", "futures-atr-barrier-v1", 1, (), False,
    ),
    AssetEvidenceContract(
        "mcx", "MCX", ("commodity_futures", "mcx"), "mcx-directional-v1",
        "mcx-atr-barrier-v1", 1, (), False,
    ),
    AssetEvidenceContract(
        "smc", "SMC", ("equity_smc", "technical_research", "smc"),
        "smc-structure-v1", "smc-atr-structure-v1", 15, (), False,
    ),
)


def _aware(value, name="timestamp") -> dt.datetime:
    parsed = pd.Timestamp(value)
    if pd.isna(parsed) or parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed.to_pydatetime().astimezone(UTC)


def _matches_contract(row: Mapping, contract: AssetEvidenceContract) -> bool:
    return (
        str(row.get("asset_class") or "").casefold()
        in {value.casefold() for value in contract.asset_classes}
        and str(row.get("strategy_id") or "") == contract.strategy_id
        and str(row.get("target_version") or "") == contract.target_version
        and int(row.get("horizon_sessions") or -1) == contract.horizon_sessions
    )


def _has_required_features(row: Mapping, contract: AssetEvidenceContract) -> bool:
    observed = {str(name) for name in (row.get("feature_names") or ())}
    return set(contract.required_features).issubset(observed)


def _partition_counts(rows: list[Mapping], policy: ProgressPolicy) -> tuple[int, int, int]:
    if not rows:
        return 0, 0, 0
    frame = pd.DataFrame({
        "as_of_date": [row["decision_at"] for row in rows],
        "label_end_date": [row["outcome_at"] for row in rows],
    })
    development, holdout = chronological_holdout_split(
        frame,
        holdout_fraction=policy.holdout_fraction,
        minimum_holdout_dates=policy.minimum_holdout_dates,
        embargo_sessions=policy.embargo_sessions,
    )
    splits = purged_walk_forward_splits(
        development,
        folds=policy.folds,
        min_train=policy.minimum_fold_training_samples,
        embargo_sessions=policy.embargo_sessions,
    ) if not development.empty else []
    oof_indices = set()
    for _, validation_indices in splits:
        oof_indices.update(int(value) for value in validation_indices)
    return int(len(development)), int(len(oof_indices)), int(len(holdout))


def _business_days_between(start: dt.date, end: dt.date) -> int:
    if end < start:
        return 0
    return int(np.busday_count(start.isoformat(), (end + dt.timedelta(days=1)).isoformat()))


def _add_business_days(start: dt.date, days: int) -> dt.date:
    current = start
    remaining = max(int(days), 0)
    while remaining:
        current += dt.timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def _pace_and_estimate(eligible: list[Mapping], *, policy: ProgressPolicy,
                       now: dt.datetime) -> tuple[float | None, str | None, str]:
    if not eligible:
        return None, None, "No eligible matured observations exist"
    dates = sorted({_aware(row["decision_at"], "decision_at").date() for row in eligible})
    elapsed_business_days = _business_days_between(dates[0], max(dates[-1], now.date()))
    if len(dates) < 5 or elapsed_business_days < 5:
        return None, None, "At least five distinct evidence days are required for a pace estimate"
    pace = len(eligible) / elapsed_business_days
    if not math.isfinite(pace) or pace <= 0:
        return None, None, "Observed evidence pace is zero"

    current_days = len(dates)
    required_days = None
    for projected_days in range(current_days, 5001):
        total = pace * projected_days
        holdout_days = max(
            int(math.ceil(projected_days * policy.holdout_fraction)),
            policy.minimum_holdout_dates,
        )
        holdout = pace * holdout_days
        development_days = max(
            projected_days - holdout_days - policy.embargo_sessions, 0,
        )
        development = pace * development_days
        approximate_oof = max(development - policy.minimum_fold_training_samples, 0)
        if (
            total >= policy.minimum_total_samples
            and projected_days >= policy.minimum_observation_days
            and holdout >= policy.minimum_holdout_samples
            and approximate_oof >= policy.minimum_oof_samples
        ):
            required_days = projected_days
            break
    if required_days is None:
        return pace, None, "Threshold date is beyond the five-thousand-day projection guard"
    additional = max(required_days - current_days, 0)
    estimate = _add_business_days(now.date(), additional).isoformat()
    return pace, estimate, (
        "Projection uses the observed eligible rows per elapsed weekday; exchange holidays, "
        "class balance, regime coverage and model-quality failures can move the date later"
    )


def summarize_evidence_progress(records: Iterable[Mapping], *, now=None,
                                policy=ProgressPolicy()) -> dict:
    """Summarize genuine evidence without filling, reconstructing or interpolating rows."""
    current = _aware(now or dt.datetime.now(UTC), "now")
    source = [dict(row or {}) for row in records or ()]
    assets = []
    for contract in ASSET_CONTRACTS:
        asset_rows = [
            row for row in source
            if str(row.get("asset_class") or "").casefold()
            in {value.casefold() for value in contract.asset_classes}
        ]
        contract_rows = [row for row in asset_rows if _matches_contract(row, contract)]
        matured = [row for row in contract_rows if row.get("matured") is True]
        eligible = [
            row for row in matured
            if row.get("training_eligible") is True and _has_required_features(row, contract)
        ]
        rejected = len(matured) - len(eligible)
        distinct_days = len({
            _aware(row["decision_at"], "decision_at").date() for row in eligible
        }) if eligible else 0
        development, oof, holdout = _partition_counts(eligible, policy)
        pace, estimated_date, estimate_note = _pace_and_estimate(
            eligible, policy=policy, now=current,
        )
        count_gate = (
            len(eligible) >= policy.minimum_total_samples
            and distinct_days >= policy.minimum_observation_days
            and oof >= policy.minimum_oof_samples
            and holdout >= policy.minimum_holdout_samples
        )
        if not contract.independent_pipeline_available:
            status_detail = "Independent training/calibration pipeline is not configured"
        elif count_gate:
            status_detail = "Count gate reached; model quality evaluation is required"
        else:
            status_detail = "Waiting for genuine matured, eligible evidence"
        assets.append({
            "key": contract.key,
            "label": contract.label,
            "status": "READY_FOR_MODEL_EVALUATION" if count_gate else "INSUFFICIENT_EVIDENCE",
            "status_detail": status_detail,
            "promotable": False,
            "raw_decisions": len(contract_rows),
            "other_contract_decisions": len(asset_rows) - len(contract_rows),
            "matured_observations": len(matured),
            "eligible_observations": len(eligible),
            "rejected_matured_observations": rejected,
            "development_pool": development,
            "oof_eligible": oof,
            "holdout_observations": holdout,
            "distinct_trading_days": distinct_days,
            "observations_per_elapsed_weekday": pace,
            "estimated_threshold_date": estimated_date,
            "estimate_note": estimate_note,
            "contract": {
                "strategy_id": contract.strategy_id,
                "target_version": contract.target_version,
                "horizon_sessions": contract.horizon_sessions,
                "required_features": list(contract.required_features),
            },
            "independent_pipeline_available": contract.independent_pipeline_available,
        })
    return {
        "status": "PASS",
        "generated_at": current.isoformat(),
        "source": "immutable-decision-outcome-evidence-spine",
        "policy": {
            "minimum_total_samples": policy.minimum_total_samples,
            "minimum_oof_samples": policy.minimum_oof_samples,
            "minimum_holdout_samples": policy.minimum_holdout_samples,
            "minimum_observation_days": policy.minimum_observation_days,
            "holdout_fraction": policy.holdout_fraction,
            "minimum_holdout_dates": policy.minimum_holdout_dates,
            "embargo_sessions": policy.embargo_sessions,
        },
        "assets": assets,
    }


def load_production_progress(database_url=None, *, now=None) -> dict:
    from production_repository import ProductionRepository

    url = str(database_url or os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        return {
            "status": "UNAVAILABLE", "promotable": False,
            "reason": "Restricted production DATABASE_URL is not configured",
            "source": "immutable-decision-outcome-evidence-spine",
        }
    repository = ProductionRepository(url, schema_mode="validate", enforce_restricted_role=True)
    return summarize_evidence_progress(repository.decision_outcome_records(), now=now)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = load_production_progress()
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
