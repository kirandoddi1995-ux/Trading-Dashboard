"""Complete read-only decision/outcome track record derived from the evidence spine."""
from __future__ import annotations

import datetime as dt
import math
from collections import Counter
from typing import Iterable, Mapping

import numpy as np

from prediction_validation import wilson_score_interval


UTC = dt.timezone.utc


def _finite(value):
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError, OverflowError):
        return None


def build_complete_track_record(records: Iterable[Mapping], *, generated_at=None) -> dict:
    """Summarize every supplied decision, retaining losses and unresolved rows."""
    source = [dict(record or {}) for record in records or ()]
    rows = []
    invalid_matured = 0
    for record in source:
        matured = record.get("matured") is True
        realized = _finite(record.get("actual_forward_return")) if matured else None
        if matured and realized is None:
            invalid_matured += 1
        rows.append({
            "decision_id": str(record.get("decision_id") or ""),
            "decision_at": record.get("decision_at"),
            "asset_class": str(record.get("asset_class") or "UNKNOWN"),
            "strategy_id": str(record.get("strategy_id") or ""),
            "action": str(record.get("action") or "UNKNOWN").upper(),
            "matured": matured,
            "outcome": str(record.get("outcome") or "PENDING").upper() if matured else "PENDING",
            "actual_forward_return": realized,
            "training_eligible": record.get("training_eligible") is True,
            "eligibility_failures": list(record.get("eligibility_failures") or ()),
        })
    rows.sort(key=lambda row: (str(row.get("decision_at") or ""), row["decision_id"]))
    matured_rows = [row for row in rows if row["matured"]]
    valid_returns = np.asarray([
        row["actual_forward_return"] for row in matured_rows
        if row["actual_forward_return"] is not None
    ], dtype=float)
    wins = int(np.sum(valid_returns > 0))
    losses = int(np.sum(valid_returns < 0))
    flats = int(np.sum(valid_returns == 0))
    interval = wilson_score_interval(wins, len(valid_returns)) if len(valid_returns) else (math.nan, math.nan)
    generated = generated_at or dt.datetime.now(UTC)
    if isinstance(generated, dt.datetime) and generated.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    return {
        "status": "PASS",
        "source": "immutable-decision-outcome-evidence-spine",
        "generated_at": str(generated.isoformat() if isinstance(generated, dt.datetime) else generated),
        "denominators": {
            "all_decisions": len(rows),
            "matured": len(matured_rows),
            "pending": len(rows) - len(matured_rows),
            "valid_realized_returns": int(len(valid_returns)),
            "invalid_matured": invalid_matured,
            "training_eligible": sum(row["training_eligible"] for row in rows),
        },
        "actions": dict(sorted(Counter(row["action"] for row in rows).items())),
        "outcomes": dict(sorted(Counter(row["outcome"] for row in matured_rows).items())),
        "performance": {
            "wins": wins,
            "losses": losses,
            "flat": flats,
            "positive_return_rate": (wins / len(valid_returns) if len(valid_returns) else None),
            "positive_return_wilson_95_low": (interval[0] if len(valid_returns) else None),
            "positive_return_wilson_95_high": (interval[1] if len(valid_returns) else None),
            "mean_decision_return": (float(np.mean(valid_returns)) if len(valid_returns) else None),
            "median_decision_return": (float(np.median(valid_returns)) if len(valid_returns) else None),
            "worst_decision_return": (float(np.min(valid_returns)) if len(valid_returns) else None),
            "best_decision_return": (float(np.max(valid_returns)) if len(valid_returns) else None),
        },
        "rows": rows,
        "limitations": [
            "Decision returns may overlap and are not presented as a portfolio equity curve",
            "Broker fill statistics require separately linked order/fill events",
            "Pending outcomes remain visible and are never imputed",
        ],
    }
