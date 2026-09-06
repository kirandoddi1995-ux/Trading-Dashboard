import pandas as pd

from strategy_validation import (
    INDEPENDENT_VALIDATION_SPECS,
    run_independent_strategy_validation,
    validate_strategy_dataset,
)


def _row(spec):
    base = {
        "strategy_id": spec.strategy_id, "asset_class": spec.asset_class,
        "target_version": spec.target_version, "horizon_sessions": spec.horizon_sessions,
        "decision_timestamp": "2026-09-01T04:31:00Z",
        "feature_available_at": "2026-09-01T04:30:30Z",
        "quote_observed_at": "2026-09-01T04:30:40Z",
        "quote_received_at": "2026-09-01T04:30:41Z",
        "entry_timestamp": "2026-09-01T04:32:00Z",
        "label_end_timestamp": "2026-09-02T10:00:00Z",
        "score": 70.0, "target_before_stop": 1, "excess_return": .01,
        "pit_snapshot_id": "ledger:abc", "round_trip_cost_bps": 30.0,
    }
    if spec.asset_class == "options":
        base.update(contract_id="NSE_OPT_1", expiry="2026-09-24", option_bid=99.0,
                    option_ask=100.0, underlying_observed_at="2026-09-01T04:30:40Z",
                    greeks_valid=True, no_arbitrage_valid=True)
    elif spec.asset_class == "equity_smc":
        base.update(setup_id="smc-1", structure_confirmed=True,
                    execution_bid=99.0, execution_ask=100.0)
    else:
        base.update(contract_id="FUT_1", contract_multiplier=50, roll_id="2026-09",
                    execution_bid=99.0, execution_ask=100.0)
    return base


def test_each_non_equity_path_has_an_exclusive_validation_namespace():
    namespaces = {spec.namespace for spec in INDEPENDENT_VALIDATION_SPECS.values()}
    assert len(namespaces) == 4
    for spec in INDEPENDENT_VALIDATION_SPECS.values():
        result = run_independent_strategy_validation(pd.DataFrame([_row(spec)]), spec)
        assert result["validation_namespace"] == spec.namespace
        assert result["calibration_reusable_by"] == [spec.namespace]
        assert result["status"] == "INSUFFICIENT_EVIDENCE"


def test_equity_or_cross_path_labels_cannot_unlock_options():
    spec = INDEPENDENT_VALIDATION_SPECS["options"]
    row = _row(spec)
    row["asset_class"] = "equity"
    result = validate_strategy_dataset(pd.DataFrame([row]), spec)
    assert result["status"] == "INVALID_EVIDENCE"
    assert any("cross-path" in reason for reason in result["failures"])


def test_pre_entry_or_naive_timestamps_are_rejected():
    spec = INDEPENDENT_VALIDATION_SPECS["futures"]
    row = _row(spec)
    row["feature_available_at"] = "2026-09-01 10:00:00"
    row["entry_timestamp"] = "2026-09-01T04:30:00Z"
    result = validate_strategy_dataset(pd.DataFrame([row]), spec)
    assert result["status"] == "INVALID_EVIDENCE"
    assert any("timezone-aware" in reason or "ordering" in reason for reason in result["failures"])


def test_bad_options_greeks_cannot_enter_validation():
    spec = INDEPENDENT_VALIDATION_SPECS["options"]
    row = _row(spec)
    row["greeks_valid"] = False
    result = validate_strategy_dataset(pd.DataFrame([row]), spec)
    assert result["status"] == "INVALID_EVIDENCE"
    assert any("greeks_valid" in reason for reason in result["failures"])
