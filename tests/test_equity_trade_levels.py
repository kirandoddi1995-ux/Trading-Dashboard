"""Synthetic regression fixtures, not historical trade or profitability evidence."""
import ast
import logging
from pathlib import Path

import pandas as pd
import pytest

SOURCE = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")


def derive(frame, price=100, atr=2, horizon=15):
    node = next(n for n in ast.parse(SOURCE).body
                if isinstance(n, ast.FunctionDef) and n.name == "derive_long_trade_levels")
    namespace = {"LOGGER": logging.getLogger(__name__)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "app.py", "exec"), namespace)
    return namespace[node.name](frame, price, atr, horizon)


def history(support, resistance):
    return pd.DataFrame({"Low": [support] * 60, "High": [resistance] * 60})


def test_discount_applies_to_upside_not_full_price():
    stop, target, _, _ = derive(history(99, 120), horizon=70)
    assert stop == 97
    # ATR target=108; 85% of its upside gives 106.80, not 91.80.
    assert target == 106.80


def test_resistance_caps_corrected_discounted_target():
    assert derive(history(99, 106), horizon=70)[1] == 106


def test_fifteen_session_resistance_branch_still_uses_floor():
    assert derive(history(99, 120))[1] == 104.20


def test_no_suitable_resistance_uses_undiscounted_atr_target():
    assert derive(history(99, 101))[1] == 104.86


def test_wider_structural_stop_and_risk_based_target_floor():
    stop, target, _, _ = derive(history(95, 101))
    assert stop == 94.70
    assert target == 107.42


@pytest.mark.parametrize("support", [99, 97, 95, 90])
@pytest.mark.parametrize("resistance", [101, 120])
def test_fifteen_session_gross_bound_with_price_rounding(support, resistance):
    stop, target, _, _ = derive(history(support, resistance))
    risk = 100 - stop
    # Returned prices are rounded to cents; allow that quantization explicitly.
    assert target - 100 <= (34 / 21) * risk + 0.02


def test_only_equity_stage2_uses_equity_constant_and_message_is_dynamic():
    tree = ast.parse(SOURCE)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "calculate_trade_math"]
    equity_calls = [n for n in calls if any(k.arg == "minimum_ratio"
                   and isinstance(k.value, ast.Attribute)
                   and k.value.attr == "EQUITY_MIN_NET_REWARD_RISK" for k in n.keywords)]
    assert len(equity_calls) == 1
    assert ast.unparse(equity_calls[0].args[0]) == "price"
    assert ast.unparse(equity_calls[0].args[1]) == "sl"
    options_calls = [n for n in calls if any(k.arg == "minimum_ratio"
                    and isinstance(k.value, ast.Attribute)
                    and k.value.attr == "MIN_NET_REWARD_RISK" for k in n.keywords)]
    assert options_calls
    assert "is below {trade_math['minimum_ratio']:.2f}" in SOURCE
    assert "is below 2.00 after estimated" not in SOURCE
