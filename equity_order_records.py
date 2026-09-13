"""Append-only user-reported equity orders. Never production EV evidence."""
from __future__ import annotations

import datetime as dt
import uuid

from equity_execution_policy import POLICY, _number
from equity_manual_review import decision_digest, require_reviewable, review_status
from live_evidence import aware_utc


FINAL_STATUSES = {"FILLED", "PARTIAL_FINAL", "CANCELLED", "REJECTED", "NOT_PLACED"}


def build_order_intent(signal, review, *, owner_id, now):
    snapshot = require_reviewable(signal)
    if not review_status(signal, review, now=now)["actionable"]:
        raise ValueError("A fresh decision-bound manual review is required")
    execution = signal.get("_governance", {}).get("execution", {})
    if execution.get("status") != "PASS" or execution.get("policy") != POLICY:
        raise ValueError("The conservative execution policy has not passed")
    if not str(owner_id or "").strip() or review.get("reviewer") != owner_id:
        raise ValueError("Order owner must match the manual reviewer")
    return {
        "intent_id": str(uuid.uuid4()), "owner_id": owner_id,
        "purpose": "USER_REPORTED_ORDER_INTENT", "production_evidence_eligible": False,
        "decision_id": snapshot["decision_id"], "decision_digest": decision_digest(signal),
        "review_id": review["review_id"], "instrument": snapshot["instrument"],
        "quantity": execution["plan"]["quantity"], "limit_price": execution["plan"]["limit_price"],
        "created_at": aware_utc(now, name="now").isoformat(), "policy": POLICY,
    }


def build_order_result(intent, *, status, filled_quantity, average_fill_price,
                       broker_order_id, broker_event_at, confirmed, now=None):
    """Record only supplied actuals. Partial-final means remainder was cancelled."""
    current = aware_utc(now or dt.datetime.now(dt.timezone.utc), name="now")
    if intent.get("purpose") != "USER_REPORTED_ORDER_INTENT" or confirmed is not True:
        raise ValueError("A recorded intent and explicit reconciliation confirmation are required")
    if status not in FINAL_STATUSES:
        raise ValueError("Reconcile a final broker status; pending orders remain unresolved")
    qty = _number(filled_quantity, "filled quantity", 0, intent["quantity"])
    if qty != int(qty):
        raise ValueError("Filled quantity must be a whole number of shares")
    if status == "FILLED" and qty != intent["quantity"]:
        raise ValueError("FILLED requires the entire intended quantity")
    if status == "PARTIAL_FINAL" and not 0 < qty < intent["quantity"]:
        raise ValueError("Partial-final requires a partial fill and cancelled remainder")
    if status in {"CANCELLED", "REJECTED", "NOT_PLACED"} and qty != 0:
        raise ValueError("Use PARTIAL_FINAL for a cancelled order with a partial fill")
    price = _number(average_fill_price, "actual average fill price", 1e-12) if qty else None
    if not qty and average_fill_price not in (None, ""):
        raise ValueError("An unfilled order must not have an invented fill price")
    if status != "NOT_PLACED" and not str(broker_order_id or "").strip():
        raise ValueError("The actual broker order ID is required")
    event_at = aware_utc(broker_event_at, name="broker_event_at") if status != "NOT_PLACED" else None
    if event_at and not aware_utc(intent["created_at"], name="intent created_at") <= event_at <= current:
        raise ValueError("Broker result timestamp is outside the order lifetime")
    return {"result_id": str(uuid.uuid4()), "intent_id": intent["intent_id"],
            "owner_id": intent["owner_id"], "purpose": "USER_REPORTED_BROKER_RESULT",
            "production_evidence_eligible": False, "status": status,
            "filled_quantity": int(qty), "average_fill_price": price,
            "broker_order_id": str(broker_order_id).strip() if broker_order_id else None,
            "broker_event_at": event_at.isoformat() if event_at else None,
            "recorded_at": current.isoformat(), "confirmed": True}
