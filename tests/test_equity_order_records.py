import datetime as dt
import ast
from pathlib import Path

import pytest

from equity_manual_review import build_manual_review, decision_digest, review_status
from equity_order_records import build_order_intent, build_order_result
from test_equity_execution_policy import NOW, execution, ev


def candidate():
    return {"Ticker": "ABC", "_price_val": 100, "_sl": 95, "_tgt": 108,
            "_system_action": "Buy", "_decision_id": "decision", "_quote_observed_at": NOW.isoformat(),
            "_governance": {"allow_trade": True, "decision_at": NOW.isoformat(), "execution": execution()}}


def reviewed():
    signal = candidate()
    review = build_manual_review(signal, secondary_platform="Fixture", secondary_price=100,
                                 reviewer="owner", attested_at=NOW, confirmed=True)
    return signal, review


def intent():
    signal, review = reviewed()
    return build_order_intent(signal, review, owner_id="owner", now=NOW)


def test_approve_before_current_fill_but_never_override_governance():
    signal, review = reviewed()
    assert intent()["production_evidence_eligible"] is False
    signal["_governance"]["allow_trade"] = False
    with pytest.raises(ValueError):
        build_order_intent(signal, review, owner_id="owner", now=NOW)


def test_changed_quantity_limit_and_stale_quote_require_new_checks():
    for key, value in (("quantity", 2), ("limit_price", 101)):
        signal, review = reviewed()
        original = decision_digest(signal)
        signal["_governance"]["execution"]["plan"][key] = value
        assert decision_digest(signal) != original
        with pytest.raises(ValueError):
            build_order_intent(signal, review, owner_id="owner", now=NOW)
    signal, review = reviewed()
    assert not review_status(signal, review, now=NOW+dt.timedelta(seconds=6))["actionable"]


def test_actual_result_never_satisfies_ev_and_missing_prices_are_not_defaulted():
    order = intent()
    kwargs = dict(status="FILLED", filled_quantity=1, average_fill_price=100,
                  broker_order_id="real-id-fixture", broker_event_at=NOW, confirmed=True, now=NOW)
    record = build_order_result(order, **kwargs)
    assert record["production_evidence_eligible"] is False
    assert ev(record)["expected_value_per_order"] is None
    with pytest.raises(ValueError):
        build_order_result(order, **{**kwargs, "average_fill_price": None})
    unplaced = build_order_result(order, status="NOT_PLACED", filled_quantity=0, average_fill_price=None,
                                 broker_order_id=None, broker_event_at=None, confirmed=True, now=NOW)
    assert unplaced["average_fill_price"] is None
    assert unplaced["broker_event_at"] is None


def test_partial_fill_requires_actual_quantity_and_confirmed_final_status():
    order = {**intent(), "quantity": 10}
    record = build_order_result(order, status="PARTIAL_FINAL", filled_quantity=3, average_fill_price=100.1,
                                broker_order_id="partial", broker_event_at=NOW, confirmed=True, now=NOW)
    assert record["filled_quantity"] == 3
    with pytest.raises(ValueError):
        build_order_result(order, status="FILLED", filled_quantity=3, average_fill_price=100.1,
                           broker_order_id="partial", broker_event_at=NOW, confirmed=True, now=NOW)


def test_ui_refresh_is_bound_to_safe_governance_callback_and_stored_pit_inputs():
    source = (Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_refresh_equity_order"]
    assert len(calls) == 1
    supplied = next(k.value for k in calls[0].keywords if k.arg == "governance_check")
    assert isinstance(supplied, ast.Name) and supplied.id == "_evaluate_governance_fail_closed"
    refresh = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_refresh_equity_order")
    body = ast.get_source_segment(source, refresh)
    assert 'feature_lineage=packet["feature_lineage"]' in body
    assert 'get_live_market_quotes(' in body
    assert 'result.get("allow_trade") is not True' in body
    assert 'source_quote_observed_at=None' not in body
