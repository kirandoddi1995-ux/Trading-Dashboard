"""Read-only reproductions for the 31-Aug-2026 live audit; does not import/run the app."""
import ast
import datetime
import logging
import math
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


def load_functions(*names):
    source = Path(__file__).with_name("app.py").read_text(encoding="utf-8")
    nodes = [node for node in ast.parse(source).body
             if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {"datetime": datetime, "IST": ZoneInfo("Asia/Kolkata"),
                 "pd": pd, "np": np, "math": math, "MARKET_OPEN": True,
                 "LOGGER": logging.getLogger("audit")}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), namespace)
    return namespace


def main():
    ns = load_functions("prepare_live_daily_bar", "get_live_market_quotes",
                        "compute_historical_setup_probability")
    today = pd.Timestamp.now(tz="Asia/Kolkata").normalize().tz_localize(None)
    frame = pd.DataFrame({"Open": [100.], "High": [102.], "Low": [99.],
                          "Close": [101.], "Volume": [1000.], "OI": [0.]}, index=[today])
    quote = {"last_price": 102., "volume": 1500.,
             "ohlc": {"open": 100., "high": 103., "low": 99.}}
    once = ns["prepare_live_daily_bar"](frame, quote)
    twice = ns["prepare_live_daily_bar"](once, quote)
    assert twice["Volume"].iloc[-1] == 1500. and len(twice) == 1
    print("PASS: repeated cumulative-volume snapshot remains 1500, not 3000.")

    rest_calls = []
    stale = {"NSE_EQ|AUDIT": {"last_price": 100., "_ts": 1., "_source": "websocket"}}
    ns.update(UPSTOX_SDK_AVAILABLE=True,
              get_market_data_buffer=lambda token: SimpleNamespace(ensure=lambda keys: None,
                                                                   snapshot=lambda keys: stale.copy()),
              _rest_market_quotes=lambda keys, token: rest_calls.append(keys) or
              {"NSE_EQ|AUDIT": {"last_price": 110.}})
    result = ns["get_live_market_quotes"](["NSE_EQ|AUDIT"], "DUMMY-NOT-A-CREDENTIAL")
    assert result["NSE_EQ|AUDIT"]["last_price"] == 100. and not rest_calls
    print("CONFIRMED DEFECT: an arbitrarily old cached websocket quote bypasses REST freshness recovery.")

    # Controlled indicator fixtures isolate the target-exit cost branch, not indicator quality.
    ns["ta"] = SimpleNamespace(
        ema=lambda close, length: close - (1. if length == 20 else 2.),
        adx=lambda high, low, close, length: pd.DataFrame({"ADX": 30.}, index=close.index),
        atr=lambda high, low, close, length: pd.Series(.05, index=close.index),
    )
    dates = pd.bdate_range("2024-01-01", periods=220)
    close = pd.Series(100. + np.arange(len(dates)) * .01, index=dates)
    history = pd.DataFrame({"Open": close, "Close": close, "High": close + .2, "Low": close - .005})
    probability = ns["compute_historical_setup_probability"](history, horizon_days=1,
                                                              min_samples=20, transaction_cost_pct=.30)
    assert probability["wins"] == probability["samples"]
    assert ((.1 / 100.) * 100. - .30) < 0
    print("CONFIRMED DEFECT: target exits counted as wins although 0.10% gross reward is below 0.30% costs.")
    print({key: probability[key] for key in ("samples", "wins", "win_probability")})

    entry, stop, lot, lots = 38.85, 34.97, 65, 74
    fee_only = (entry - stop + entry * .007) * lot * lots
    fee_and_spread = (entry - stop + entry * .0096) * lot * lots
    print("OBSERVED OPTION SAMPLE:", {"quantity": lot * lots, "capital": round(entry * lot * lots, 2),
          "risk_fee_only": round(fee_only, 2), "risk_same_cost_assumption_as_RR": round(fee_and_spread, 2),
          "budget": 20000., "net_RR_formula": round((.1875 - .0096) / (.1 + .0096), 2)})
    coforge = {"entry": 2005.50, "target": 2416.69, "stop": 1711.79}
    risk = coforge["entry"] - coforge["stop"]
    quantity = min(math.floor(20000 / risk), math.floor(200000 / coforge["entry"]))
    print("OBSERVED EQUITY SAMPLE:", {"ticker": "COFORGE", "risk_percent": round(risk / coforge["entry"] * 100, 2),
          "target_return_percent": round((coforge["target"] / coforge["entry"] - 1) * 100, 2),
          "reward_risk": round((coforge["target"] - coforge["entry"]) / risk, 2),
          "risk_sized_shares": quantity, "capital": round(quantity * coforge["entry"], 2)})


if __name__ == "__main__":
    main()
