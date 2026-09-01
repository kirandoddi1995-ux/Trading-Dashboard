"""Leakage-safe targets, scanner replay and calibrated probability validation."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import sqlite3
import threading
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize


TARGET_VERSION = "net-excess-next-open-v1"
STRATEGY_VERSION = "equity-scanner-v16.2"


@dataclass(frozen=True)
class TargetDefinition:
    horizon_sessions: int
    round_trip_cost_bps: float = 30.0
    entry_rule: str = "next_session_open"
    exit_rule: str = "first_target_or_stop_else_horizon_close"
    same_bar_rule: str = "stop_first_conservative"
    benchmark: str = "NSE_INDEX|Nifty 50"


@dataclass(frozen=True)
class CalibrationPolicy:
    minimum_training_samples: int = 200
    minimum_class_samples: int = 30
    minimum_oos_samples: int = 100
    maximum_ece: float = 0.10
    minimum_probability: float = 0.60
    minimum_probability_margin: float = 0.05
    minimum_pit_coverage: float = 0.90


def _frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out.index = pd.to_datetime(out.index, errors="coerce").tz_localize(None)
    return out[~out.index.isna()].sort_index()


def compute_forward_target(prices: pd.DataFrame, as_of_date, definition: TargetDefinition,
                           stop: float, target: float, benchmark: pd.DataFrame | None = None) -> dict | None:
    """Label a signal without using the signal day's closing price as entry."""
    prices = _frame(prices)
    after = prices.loc[prices.index > pd.Timestamp(as_of_date)]
    if len(after) < definition.horizon_sessions or not {"Open", "High", "Low", "Close"}.issubset(after.columns):
        return None
    window = after.iloc[:definition.horizon_sessions]
    entry = float(window.iloc[0]["Open"])
    if not np.isfinite(entry) or entry <= 0:
        return None
    exit_price = float(window.iloc[-1]["Close"])
    outcome = "horizon"
    outcome_date = window.index[-1]
    # Conservative convention removes unknowable intraday sequencing whenever
    # both levels occur in the same daily bar.
    for date, bar in window.iterrows():
        if float(bar["Low"]) <= float(stop):
            exit_price, outcome, outcome_date = float(stop), "stop", date
            break
        if float(bar["High"]) >= float(target):
            exit_price, outcome, outcome_date = float(target), "target", date
            break
    gross_return = exit_price / entry - 1.0
    net_return = gross_return - definition.round_trip_cost_bps / 10_000.0
    benchmark_return = None
    if benchmark is not None and not benchmark.empty:
        bench = _frame(benchmark).reindex(window.index).dropna(subset=["Open", "Close"])
        if len(bench) == len(window):
            benchmark_return = float(bench.iloc[-1]["Close"] / bench.iloc[0]["Open"] - 1.0)
    excess = net_return - benchmark_return if benchmark_return is not None else None
    return {
        "target_version": TARGET_VERSION,
        "horizon_sessions": definition.horizon_sessions,
        "entry_date": window.index[0].date().isoformat(),
        "label_end_date": window.index[-1].date().isoformat(),
        "outcome_date": pd.Timestamp(outcome_date).date().isoformat(),
        "entry": entry, "exit": exit_price, "outcome": outcome,
        "target_before_stop": int(outcome == "target"),
        "gross_return": gross_return, "net_return": net_return,
        "benchmark_return": benchmark_return, "excess_return": excess,
        "positive_excess": (int(excess > 0) if excess is not None else None),
        "cost_bps": definition.round_trip_cost_bps,
    }


def scanner_composite_score(components: dict[str, float]) -> float:
    """The exact v16.2 live ranking weights, shared by live and replay paths."""
    weights = {
        "trend": .15, "momentum": .12, "volume": .10, "relative_strength": .10,
        "risk_reward": .15, "adx": .08, "volatility": .06, "historical_edge": .10,
        "momentum_beta": .14,
    }
    missing = set(weights) - set(components)
    if missing:
        raise ValueError(f"Missing scanner components: {sorted(missing)}")
    values = {key: float(np.clip(components[key], 0.0, 100.0)) for key in weights}
    return float(np.clip(sum(values[key] * weight for key, weight in weights.items()), 0.0, 100.0))


def purged_walk_forward_splits(rows: pd.DataFrame, *, folds=5, min_train=200, embargo_sessions=20):
    """Expanding time folds with overlapping labels purged from training."""
    required = {"as_of_date", "label_end_date"}
    if not required.issubset(rows.columns):
        raise ValueError(f"Rows require {sorted(required)}")
    ordered = rows.copy()
    ordered["as_of_date"] = pd.to_datetime(ordered["as_of_date"])
    ordered["label_end_date"] = pd.to_datetime(ordered["label_end_date"])
    ordered = ordered.sort_values("as_of_date").reset_index(drop=True)
    unique_dates = np.array(sorted(ordered["as_of_date"].dt.normalize().unique()))
    if len(unique_dates) < folds + 2:
        return []
    validation_dates = np.array_split(unique_dates[max(1, len(unique_dates) // 3):], folds)
    result = []
    for fold_dates in validation_dates:
        if len(fold_dates) == 0:
            continue
        val_start, val_end = pd.Timestamp(fold_dates[0]), pd.Timestamp(fold_dates[-1])
        # Leave an explicit business-session embargo between training labels
        # and validation observations, in addition to purging labels that
        # overlap the validation boundary.
        training_cutoff = val_start - pd.offsets.BDay(max(int(embargo_sessions), 0))
        train_mask = ((ordered["as_of_date"] < training_cutoff)
                      & (ordered["label_end_date"] < training_cutoff))
        val_mask = ordered["as_of_date"].dt.normalize().isin(fold_dates)
        train_idx = ordered.index[train_mask].to_numpy()
        val_idx = ordered.index[val_mask].to_numpy()
        if len(train_idx) < min_train or not len(val_idx):
            continue
        result.append((train_idx, val_idx))
        # Embargo is naturally enforced by the next fold's strict historical
        # training and label-end purge; retained in metadata by caller.
    return result


class PlattCalibrator:
    def __init__(self):
        self.intercept = 0.0
        self.slope = 0.0

    @staticmethod
    def _sigmoid(value):
        value = np.clip(value, -35.0, 35.0)
        return 1.0 / (1.0 + np.exp(-value))

    def fit(self, scores, outcomes):
        x = np.asarray(scores, dtype=float) / 100.0
        y = np.asarray(outcomes, dtype=float)
        if len(x) != len(y) or len(x) == 0 or len(np.unique(y)) < 2:
            raise ValueError("Calibration needs non-empty scores and both outcome classes")

        def objective(params):
            p = np.clip(self._sigmoid(params[0] + params[1] * x), 1e-9, 1 - 1e-9)
            loss = -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
            return loss + 1e-3 * params[1] ** 2

        fitted = minimize(objective, np.array([0.0, 1.0]), method="L-BFGS-B")
        if not fitted.success:
            raise RuntimeError("Probability calibration did not converge")
        self.intercept, self.slope = map(float, fitted.x)
        return self

    def predict(self, scores):
        x = np.asarray(scores, dtype=float) / 100.0
        return self._sigmoid(self.intercept + self.slope * x)


def calibration_metrics(outcomes, probabilities, bins=10) -> dict:
    y = np.asarray(outcomes, dtype=float)
    p = np.clip(np.asarray(probabilities, dtype=float), 1e-9, 1 - 1e-9)
    if not len(y) or len(y) != len(p):
        raise ValueError("Outcomes and probabilities must be equal and non-empty")
    brier = float(np.mean((p - y) ** 2))
    log_loss = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    baseline = float(np.mean((np.mean(y) - y) ** 2))
    edges = np.linspace(0.0, 1.0, bins + 1)
    reliability, ece = [], 0.0
    for index in range(bins):
        mask = (p >= edges[index]) & (p < edges[index + 1] if index < bins - 1 else p <= 1.0)
        if not mask.any():
            continue
        predicted, actual, count = float(p[mask].mean()), float(y[mask].mean()), int(mask.sum())
        ece += count / len(y) * abs(predicted - actual)
        reliability.append({"lower": edges[index], "upper": edges[index + 1], "predicted": predicted,
                            "actual": actual, "count": count})
    return {"samples": len(y), "brier": brier, "baseline_brier": baseline,
            "log_loss": log_loss, "ece": float(ece), "reliability": reliability}


def decide_abstention(probability, metrics, *, training_samples, positive_samples,
                      negative_samples, pit_coverage, policy=CalibrationPolicy()) -> tuple[bool, str]:
    checks = [
        (pit_coverage < policy.minimum_pit_coverage, "Point-in-time universe coverage is below 90%"),
        (training_samples < policy.minimum_training_samples, "Insufficient completed training samples"),
        (min(positive_samples, negative_samples) < policy.minimum_class_samples, "Insufficient examples in one outcome class"),
        (int(metrics.get("samples", 0)) < policy.minimum_oos_samples, "Insufficient out-of-sample validation samples"),
        (float(metrics.get("brier", math.inf)) >= float(metrics.get("baseline_brier", -math.inf)),
         "Calibrated model does not beat the base-rate Brier score"),
        (float(metrics.get("ece", math.inf)) > policy.maximum_ece, "Calibration error is too high"),
        (abs(float(probability) - 0.5) < policy.minimum_probability_margin, "Prediction is inside the uncertainty/no-trade zone"),
        (float(probability) < policy.minimum_probability, "Probability is below the validated trade threshold"),
    ]
    for failed, reason in checks:
        if failed:
            return True, reason
    return False, "Validated evidence threshold passed"


def run_purged_walk_forward_validation(rows: pd.DataFrame, *, folds=5, embargo_sessions=20,
                                       policy=CalibrationPolicy()) -> dict:
    """Fit only on the past, predict each future fold, then assess calibration.

    `rows` must contain the exact archived scanner score and completed labels;
    this function never reconstructs candidates from today's universe.
    """
    required = {"as_of_date", "label_end_date", "score", "target_before_stop", "excess_return"}
    if not required.issubset(rows.columns):
        raise ValueError(f"Validation rows require {sorted(required)}")
    clean = rows.dropna(subset=list(required)).copy()
    splits = purged_walk_forward_splits(
        clean, folds=folds, min_train=policy.minimum_training_samples,
        embargo_sessions=embargo_sessions,
    )
    oos_index, oos_probability = [], []
    fold_details = []
    for fold_number, (train_idx, validation_idx) in enumerate(splits, 1):
        train_y = clean.iloc[train_idx]["target_before_stop"].astype(int)
        if min(int(train_y.sum()), int((1 - train_y).sum())) < policy.minimum_class_samples:
            continue
        calibrator = PlattCalibrator().fit(clean.iloc[train_idx]["score"], train_y)
        predicted = calibrator.predict(clean.iloc[validation_idx]["score"])
        oos_index.extend(validation_idx.tolist())
        oos_probability.extend(predicted.tolist())
        fold_details.append({
            "fold": fold_number, "training_samples": len(train_idx), "validation_samples": len(validation_idx),
            "validation_start": str(clean.iloc[validation_idx]["as_of_date"].min()),
            "validation_end": str(clean.iloc[validation_idx]["as_of_date"].max()),
        })
    if not oos_index:
        return {"status": "INSUFFICIENT_EVIDENCE", "reason": "No valid purged walk-forward fold",
                "training_samples": len(clean), "oos_samples": 0, "metrics": {}, "folds": []}
    y_oos = clean.iloc[oos_index]["target_before_stop"].astype(int).to_numpy()
    metrics = calibration_metrics(y_oos, oos_probability)
    all_y = clean["target_before_stop"].astype(int)
    final_model = PlattCalibrator().fit(clean["score"], all_y)
    representative_probability = float(final_model.predict([float(clean.iloc[-1]["score"])])[0])
    abstain, reason = decide_abstention(
        representative_probability, metrics, training_samples=len(clean),
        positive_samples=int(all_y.sum()), negative_samples=int((1 - all_y).sum()),
        pit_coverage=float(clean.get("pit_coverage", pd.Series([1.0])).min()), policy=policy,
    )
    returns = clean.iloc[oos_index]["excess_return"].astype(float).to_numpy()
    return {
        "status": "ABSTAIN" if abstain else "VALIDATED",
        "reason": reason,
        "training_samples": len(clean), "oos_samples": len(oos_index),
        "metrics": metrics, "folds": fold_details,
        "model": {"type": "platt_logistic", "intercept": final_model.intercept, "slope": final_model.slope},
        "latest_probability": representative_probability,
        "return_quantiles": {
            "p10": float(np.quantile(returns, .10)), "p50": float(np.quantile(returns, .50)),
            "p90": float(np.quantile(returns, .90)),
        },
        "policy": asdict(policy), "embargo_sessions": int(embargo_sessions),
    }


class ValidationStore:
    def __init__(self, connect_fn, db_path):
        self._connect_fn, self._db_path = connect_fn, db_path
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self):
        return self._connect_fn(self._db_path)

    def _ensure_schema(self):
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS prediction_targets (
                        observation_id TEXT NOT NULL,
                        horizon_sessions INTEGER NOT NULL,
                        target_version TEXT NOT NULL,
                        entry_date TEXT NOT NULL,
                        label_end_date TEXT NOT NULL,
                        outcome_date TEXT NOT NULL,
                        outcome TEXT NOT NULL,
                        target_before_stop INTEGER NOT NULL,
                        gross_return REAL NOT NULL,
                        net_return REAL NOT NULL,
                        benchmark_return REAL,
                        excess_return REAL,
                        positive_excess INTEGER,
                        cost_bps REAL NOT NULL,
                        PRIMARY KEY (observation_id, horizon_sessions, target_version)
                    );
                    CREATE TABLE IF NOT EXISTS validation_runs (
                        run_id TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL,
                        strategy_version TEXT NOT NULL,
                        target_version TEXT NOT NULL,
                        horizon_sessions INTEGER NOT NULL,
                        training_samples INTEGER NOT NULL,
                        oos_samples INTEGER NOT NULL,
                        metrics_json TEXT NOT NULL,
                        model_json TEXT NOT NULL,
                        status TEXT NOT NULL,
                        status_reason TEXT NOT NULL
                    );
                """)
                conn.commit()
            finally:
                conn.close()

    def save_target(self, observation_id, target):
        conn = self._connect()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO prediction_targets(observation_id, horizon_sessions, target_version,
                    entry_date, label_end_date, outcome_date, outcome, target_before_stop, gross_return,
                    net_return, benchmark_return, excess_return, positive_excess, cost_bps)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (observation_id, target["horizon_sessions"], target["target_version"], target["entry_date"],
                  target["label_end_date"], target["outcome_date"], target["outcome"],
                  target["target_before_stop"], target["gross_return"], target["net_return"],
                  target["benchmark_return"], target["excess_return"], target["positive_excess"], target["cost_bps"]))
            conn.commit()
        finally:
            conn.close()

    def pending_observations(self, horizon_sessions: int, limit=25) -> list[dict]:
        """Completed scanner signals that do not yet have this horizon label."""
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT o.observation_id, o.as_of_date, o.instrument_key, o.trading_symbol,
                       o.entry, o.stop, o.target
                FROM scanner_observations o
                LEFT JOIN prediction_targets t ON t.observation_id=o.observation_id
                    AND t.horizon_sessions=? AND t.target_version=?
                WHERE o.stage2_pass=1 AND o.entry IS NOT NULL AND o.stop IS NOT NULL
                    AND o.target IS NOT NULL AND t.observation_id IS NULL
                ORDER BY o.as_of_date, o.instrument_key LIMIT ?
            """, (int(horizon_sessions), TARGET_VERSION, int(limit))).fetchall()
        finally:
            conn.close()
        names = ["observation_id", "as_of_date", "instrument_key", "trading_symbol", "entry", "stop", "target"]
        return [dict(zip(names, row)) for row in rows]

    def evidence_summary(self) -> dict:
        conn = self._connect()
        try:
            observations = conn.execute("SELECT COUNT(*) FROM scanner_observations").fetchone()[0]
            targets = conn.execute("SELECT COUNT(*) FROM prediction_targets").fetchone()[0]
            validated = conn.execute("SELECT COUNT(*) FROM validation_runs WHERE status='VALIDATED'").fetchone()[0]
            latest = conn.execute("SELECT created_at, status, status_reason, metrics_json FROM validation_runs ORDER BY created_at DESC LIMIT 1").fetchone()
        finally:
            conn.close()
        return {"observations": int(observations), "targets": int(targets), "validated_runs": int(validated),
                "latest": ({"created_at": latest[0], "status": latest[1], "reason": latest[2],
                            "metrics": json.loads(latest[3])} if latest else None)}

    def validation_dataset(self, horizon_sessions: int) -> pd.DataFrame:
        conn = self._connect()
        try:
            return pd.read_sql_query("""
                SELECT o.observation_id, o.as_of_date, o.instrument_key, o.trading_symbol,
                       o.strategy_version, o.score, o.universe_snapshot_date,
                       t.label_end_date, t.target_before_stop, t.net_return, t.benchmark_return,
                       t.excess_return
                FROM scanner_observations o
                JOIN prediction_targets t ON t.observation_id=o.observation_id
                JOIN pit_universe_snapshots u ON u.snapshot_date=o.universe_snapshot_date
                WHERE o.stage1_pass=1 AND o.stage2_pass=1 AND o.score IS NOT NULL
                  AND t.horizon_sessions=? AND t.target_version=? AND u.is_complete=1
                ORDER BY o.as_of_date, o.instrument_key
            """, conn, params=(int(horizon_sessions), TARGET_VERSION))
        finally:
            conn.close()

    def save_validation_run(self, result, horizon_sessions, strategy_version=STRATEGY_VERSION) -> str:
        created_at = dt.datetime.now(dt.timezone.utc).isoformat()
        material = json.dumps({"created_at": created_at, "strategy": strategy_version,
                               "horizon": horizon_sessions}, sort_keys=True)
        run_id = hashlib.sha256(material.encode()).hexdigest()
        conn = self._connect()
        try:
            conn.execute("""
                INSERT INTO validation_runs(run_id, created_at, strategy_version, target_version,
                    horizon_sessions, training_samples, oos_samples, metrics_json, model_json,
                    status, status_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (run_id, created_at, strategy_version, TARGET_VERSION, int(horizon_sessions),
                  int(result.get("training_samples", 0)), int(result.get("oos_samples", 0)),
                  json.dumps(result.get("metrics", {}), sort_keys=True),
                  json.dumps({"model": result.get("model"), "return_quantiles": result.get("return_quantiles"),
                              "policy": result.get("policy"), "folds": result.get("folds")}, sort_keys=True),
                  result.get("status", "INSUFFICIENT_EVIDENCE"), result.get("reason", "Unknown")))
            conn.commit()
        finally:
            conn.close()
        return run_id
