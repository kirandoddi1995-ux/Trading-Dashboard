"""Equity-only manual quote verification after system approval.

This module never changes a governance decision.  It can only add a second,
short-lived confirmation to an already-approved, current equity decision.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import uuid
from collections.abc import Mapping


POLICY = "equity-intent-manual-quote-v1"
MAXIMUM_REVIEW_AGE_SECONDS = 60
MAXIMUM_DIFFERENCE_BPS = 15.0


class ManualReviewError(ValueError):
    pass


def _utc(value, name):
    if isinstance(value, dt.datetime):
        parsed = value
    else:
        try:
            parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ManualReviewError(f"{name} must be a valid timestamp") from exc
    if parsed.tzinfo is None:
        raise ManualReviewError(f"{name} must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def _positive(value, name):
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ManualReviewError(f"{name} must be numeric") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ManualReviewError(f"{name} must be positive and finite")
    return parsed


def decision_snapshot(signal: Mapping) -> dict:
    governance = dict(signal.get("_governance") or {})
    evidence = dict(governance.get("decision_evidence") or {})
    decision_id = str(signal.get("_decision_id") or evidence.get("decision_id") or "").strip()
    snapshot = {
        "policy": POLICY,
        "asset_class": "equity",
        "decision_id": decision_id,
        "scan_run_id": str(signal.get("_scan_run_id") or "").strip() or None,
        "instrument": str(signal.get("Ticker") or "").strip(),
        "system_action": str(signal.get("_system_action") or signal.get("Action") or "").strip(),
        "system_allow_trade": governance.get("allow_trade") is True,
        "entry": signal.get("_price_val"),
        "stop": signal.get("_sl"),
        "target": signal.get("_tgt"),
        "primary_quote_observed_at": signal.get("_quote_observed_at"),
        "governance_decision_at": governance.get("decision_at"),
        "execution_plan": (governance.get("execution") or {}).get("plan"),
    }
    return snapshot


def decision_digest(signal: Mapping) -> str:
    encoded = json.dumps(
        decision_snapshot(signal), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def require_reviewable(signal: Mapping) -> dict:
    snapshot = decision_snapshot(signal)
    if not snapshot["decision_id"]:
        raise ManualReviewError("A stored decision identity is required")
    if not snapshot["instrument"]:
        raise ManualReviewError("The equity instrument is required")
    if not snapshot["system_allow_trade"]:
        raise ManualReviewError("Manual review cannot override a governance rejection")
    if snapshot["system_action"].casefold() != "buy":
        raise ManualReviewError("Only a system-approved Buy can be manually confirmed")
    for field in ("entry", "stop", "target"):
        _positive(snapshot[field], field)
    _utc(snapshot["primary_quote_observed_at"], "primary_quote_observed_at")
    _utc(snapshot["governance_decision_at"], "governance_decision_at")
    return snapshot


def build_manual_review(
    signal: Mapping,
    *,
    secondary_platform: str,
    secondary_price,
    reviewer: str,
    attested_at,
    source_quote_observed_at=None,
    confirmed: bool,
    maximum_difference_bps: float = MAXIMUM_DIFFERENCE_BPS,
) -> dict:
    snapshot = require_reviewable(signal)
    if confirmed is not True:
        raise ManualReviewError("The manual cross-check must be explicitly confirmed")
    platform = str(secondary_platform or "").strip()
    if not platform:
        raise ManualReviewError("The second trading platform is required")
    reviewer_name = str(reviewer or "").strip()
    if not reviewer_name:
        raise ManualReviewError("The reviewer identity is required")
    checked_at = _utc(attested_at, "attested_at")
    source_at = (
        _utc(source_quote_observed_at, "source_quote_observed_at")
        if source_quote_observed_at is not None else None
    )
    if source_at is not None and source_at > checked_at:
        raise ManualReviewError("The source quote timestamp cannot be after the check")
    secondary = _positive(secondary_price, "secondary_price")
    primary = _positive(snapshot["entry"], "entry")
    limit = _positive(maximum_difference_bps, "maximum_difference_bps")
    difference = abs(secondary - primary) / primary * 10_000.0
    status = "CONFIRMED" if difference <= limit else "MISMATCH"
    return {
        "review_id": str(uuid.uuid4()),
        "purpose": "LIVE_EQUITY_MANUAL_QUOTE_CHECK",
        "policy": POLICY,
        "decision_id": snapshot["decision_id"],
        "decision_digest": decision_digest(signal),
        "scan_run_id": snapshot["scan_run_id"],
        "instrument": snapshot["instrument"],
        "reviewer": reviewer_name,
        "attested_at": checked_at.isoformat(),
        "secondary_platform": platform,
        "secondary_price": secondary,
        "source_quote_observed_at": source_at.isoformat() if source_at else None,
        "primary_price": primary,
        "difference_bps": difference,
        "maximum_difference_bps": limit,
        "status": status,
        "confirmed": status == "CONFIRMED",
        "system_allow_trade": True,
        "execution_plan": snapshot["execution_plan"],
        "primary_quote_observed_at": snapshot["primary_quote_observed_at"],
        "governance_decision_at": snapshot["governance_decision_at"],
    }


def review_status(signal: Mapping, review: Mapping | None, *, now=None) -> dict:
    """Return additive actionability; never modify the governance result."""
    try:
        snapshot = require_reviewable(signal)
    except ManualReviewError as exc:
        return {"actionable": False, "status": "INELIGIBLE", "reason": str(exc)}
    if not review:
        return {
            "actionable": False, "status": "REVIEW_REQUIRED",
            "reason": "Check this exact trade in a second trading platform before acting.",
        }
    if str(review.get("decision_id") or "") != snapshot["decision_id"]:
        return {"actionable": False, "status": "SUPERSEDED", "reason": "The review belongs to another decision."}
    if str(review.get("decision_digest") or "") != decision_digest(signal):
        return {"actionable": False, "status": "SUPERSEDED", "reason": "The approved trade details changed."}
    if review.get("confirmed") is not True or str(review.get("status")) != "CONFIRMED":
        return {"actionable": False, "status": "MISMATCH", "reason": "The manually checked price did not match."}
    current = _utc(now or dt.datetime.now(dt.timezone.utc), "now")
    try:
        checked = _utc(review.get("attested_at"), "attested_at")
        primary_at = _utc(snapshot["primary_quote_observed_at"], "primary_quote_observed_at")
        governance_at = _utc(snapshot["governance_decision_at"], "governance_decision_at")
    except ManualReviewError as exc:
        return {"actionable": False, "status": "STALE", "reason": str(exc)}
    ages = [(current - checked).total_seconds(), (current - primary_at).total_seconds(),
            (current - governance_at).total_seconds()]
    execution = signal.get("_governance", {}).get("execution", {})
    if execution.get("policy") == "equity-conservative-execution-v1":
        # The new limit/depth check is valid only for the stricter live quote age.
        from quant_foundation import PRODUCTION_QUANT_CONFIG
        if execution.get("status") != "PASS" or any(
            age < 0 or age > PRODUCTION_QUANT_CONFIG.execution.maximum_quote_age_seconds for age in ages
        ):
            return {"actionable": False, "status": "STALE", "reason": "Refresh the limit order and governance checks before acting."}
    if any(age < 0 or age > MAXIMUM_REVIEW_AGE_SECONDS for age in ages):
        return {
            "actionable": False, "status": "STALE",
            "reason": "The quote, governance decision, or manual check is no longer current.",
        }
    return {
        "actionable": True, "status": "CONFIRMED",
        "reason": "System approval and the decision-bound manual quote check are both current.",
    }
