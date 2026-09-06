import ast
import logging
import pathlib
import pytest

import app_runtime as runtime


ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_rejection_without_net_ratio_is_safe_and_keeps_governance_reason():
    rejection = runtime.rejection_record(
        "governance_blocked",
        "Production governance blocked the candidate",
        blocking_reasons=["Validated options calibration evidence is unavailable"],
    )
    selected = runtime.select_rejection([rejection])
    assert selected["net_ratio"] is None
    assert runtime.rejection_messages([selected]) == [
        "Validated options calibration evidence is unavailable"
    ]


def test_measured_reward_risk_rejection_is_selected_without_unsafe_key_access():
    records = [
        {"reason": "governance_blocked", "detail": "No calibration"},
        {"reason": "reward_risk_below_threshold", "net_ratio": 1.45},
    ]
    selected = runtime.select_rejection(records)
    assert selected["reason"] == "reward_risk_below_threshold"
    assert selected["net_ratio"] == pytest.approx(1.45)


def test_no_trade_message_separates_passed_bias_from_real_blocker():
    message = runtime.no_trade_message(
        "options contract",
        bias="Bearish",
        bias_passed=True,
        net_score=-49.5,
        threshold=25,
        blocking_reasons=["Validated options calibration evidence is unavailable"],
    )
    assert "Bearish directional bias passed" in message
    assert "net -49.5 versus required -25" in message
    assert "NO TRADE" in message
    assert "Validated options calibration evidence is unavailable" in message
    assert "Aligned evidence" not in message


def test_no_trade_message_keeps_scan_summary_out_of_blocking_reasons():
    message = runtime.no_trade_message(
        "equity candidate",
        blocking_reasons=["Price is below the 50-day EMA"],
        context="Quick scan completed successfully; 95 candidates analyzed",
    )
    blocking_section, context_section = message.split("**Decision context:**")
    assert "Price is below the 50-day EMA" in blocking_section
    assert "Quick scan completed successfully" not in blocking_section
    assert "Quick scan completed successfully" in context_section


def test_all_five_asset_displays_use_the_shared_message_contract():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    for label in (
        '"options contract"', '"futures contract"', '"equity candidate"',
        '"MCX contract"', '"SMC setup"',
    ):
        assert "runtime.no_trade_message(\n" in source
        assert label in source


def test_safe_exception_label_names_only_the_missing_identifier():
    try:
        raise NameError("name 'market_regime' is not defined", name="market_regime")
    except NameError as exc:
        assert runtime.safe_exception_label(exc) == "NameError (market_regime)"


def test_market_regime_code_is_explicit_and_fail_closed():
    assert runtime.market_regime_code({"regime": "SIDEWAYS"}) == "SIDEWAYS"
    assert runtime.market_regime_code(None) is None
    assert runtime.market_regime_code("SIDEWAYS") is None


def test_unexpected_governance_exception_is_observable_and_fail_closed():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    node = next(
        item for item in ast.parse(source).body
        if isinstance(item, ast.FunctionDef) and item.name == "_evaluate_governance_fail_closed"
    )

    class Observer:
        def __init__(self):
            self.events = []

        def record(self, *args, **kwargs):
            self.events.append((args, kwargs))

    observer = Observer()

    def broken_governance(**_kwargs):
        raise NameError("name 'gate_state' is not defined", name="gate_state")

    namespace = {
        "runtime": runtime,
        "LOGGER": logging.getLogger("governance-fallback-test"),
        "OBSERVABILITY": observer,
        "evaluate_live_governance_contract": broken_governance,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), "app.py", "exec"), namespace)
    result = namespace["_evaluate_governance_fail_closed"]("Equity", instrument="TEST")

    assert result["allow_trade"] is False
    assert result["status"] == "SYSTEM_ERROR_NO_TRADE"
    assert result["system_error"] == "NameError (gate_state)"
    assert result["blocking_reasons"] == [
        "Equity governance system error — treated as NO TRADE."
    ]
    assert observer.events[0][1]["ok"] is False


def test_all_four_interactive_governance_paths_use_exception_boundary():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    for label in ('"Futures"', '"Equity"', '"MCX"', '"SMC"'):
        assert "_evaluate_governance_fail_closed(\n" in source
        assert label in source
    assert source.count("_evaluate_governance_fail_closed(") == 5  # definition + four calls
    assert "_embedded_live_governance_contract_v22_1" not in source
