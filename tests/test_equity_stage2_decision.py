"""Behaviour tests for equity_stage2_decision.evaluate_stage2.

The main test is differential: app.py's REAL `evaluate_stock` (exec'd from app.py's
source, with its original helper defs and stubbed live-only evidence/governance)
and the headless copy run on the same synthetic inputs, and must reach the same
decision - same reject category/reason, or the same archived score, levels and
features on a pass. The AST parity test proves the code text matches; this proves
the parameter wiring (where app.py read page globals) behaves identically.

Not reached by any scenario (covered only by the text parity test): the No-Trade
Zone, Breakout Quality < 40, invalid ATR, invalid trade levels, NaN indicators and
a pass with a live bid/ask quote. `market_open` never changes a result here:
completed-bar filtering drops today's bar, and volume pacing only uses
`market_open` when the last bar is today.

No network, no database, no credentials, synthetic prices only.
"""
from __future__ import annotations

import ast
import datetime
import logging
import math
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import app_runtime
import technical_indicators as ta
import trade_contracts
from equity_observation_capture import EquityCapture
from equity_stage2_decision import evaluate_stage2
from feature_store import compute_feature_frame
from prediction_validation import STRATEGY_VERSION, TARGET_VERSION, scanner_composite_score
from quantitative_services import estimate_execution_cost
from risk_engine import RiskEngine
from test_equity_stage2_engine_parity import SHARED as ENGINE_SHARED

ROOT = Path(__file__).resolve().parents[1]
APP_TREE = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
TICKER, KEY = "SYNTH", "NSE_EQ|SYNTHETIC0001"
APP_ONLY_FEATURE_KEYS = {"equity_capture", "market_regime", "scan_mode"}  # added by app's _archive_stage2


def _ohlcv(n=600, drift=0.0025, noise=0.004, seed=7, tail_days=0, tail_drift=0.0, start_price=100.0,
           tail_noise=None, tail_volume=1.0, range_scale=1.0, future_days=0):
    """Raw daily OHLCV (no indicators). Bars end well before today unless `future_days`
    pushes the last bars to today/after (they are then not completed daily bars)."""
    rng = np.random.default_rng(seed)
    returns = drift + rng.normal(0, noise, size=n)
    span = np.ones(n)
    volume = rng.integers(500_000, 1_500_000, size=n).astype(float)
    if tail_days:
        returns[-tail_days:] = tail_drift + rng.normal(0, tail_noise or noise, size=tail_days)
        span[-tail_days:] = range_scale
        volume[-tail_days:] *= tail_volume
    close = start_price * np.cumprod(1 + returns)
    if future_days:
        today = pd.Timestamp(datetime.date.today())
        index = pd.bdate_range(end=today + pd.offsets.BDay(future_days), periods=n)
    else:
        index = pd.bdate_range(start="2023-06-01", periods=n)
    return pd.DataFrame({
        "Open": close * (1 + rng.normal(0, 0.002, size=n)),
        "High": close * (1 + span * np.abs(rng.normal(0, 0.004, size=n))),
        "Low": close * (1 - span * np.abs(rng.normal(0, 0.004, size=n))),
        "Close": close,
        "Volume": volume,
    }, index=index)


class _FeatureStore:
    """Cache-free stand-in for feature_store.TechnicalFeatureStore.enrich."""

    def enrich(self, instrument_key, source, compute_fn):
        """Compute features directly; report the mode the app would log."""
        return compute_fn(source), "computed"


class _Stub:
    """Accepts any constructor kwargs (evidence context/bundle stand-ins)."""

    def __init__(self, **kwargs):
        """Keep kwargs for inspection."""
        self.kwargs = kwargs

    def compatibility_fields(self):
        """Match LiveEvidenceContext's API used in app.py's display row."""
        return {}


class _PitStore:
    """Records what app.py would archive for each Stage-2 outcome."""

    def __init__(self):
        """Start with no archived rows."""
        self.rows = []

    def scanner_observation_id(self, *args):
        """Deterministic observation id."""
        return "obs-1"

    def record_scanner_observation(self, **row):
        """Capture the archived row instead of writing a database."""
        self.rows.append(row)


def _scenario(*, history, quote=None, market_open=False, max_price=100_000.0, weekly=False,
              advanced=False, key=KEY, days=15):
    """One set of scan inputs, shared by the app run and the engine run."""
    return dict(history=history, quote=quote, market_open=market_open, max_price=max_price,
                weekly=weekly, advanced=advanced, key=key, days=days)


def _fetch(scenario):
    """get_cached_history stand-in with app.py's call signature."""
    def get_cached_history(key, token, days=1200, fetch_fn=None):
        """Return the scenario's history (or raise its error), checking app.py's call arguments."""
        assert token == "token" and days == 1200 and fetch_fn == "fetch-sentinel"
        if isinstance(scenario["history"], Exception):
            raise scenario["history"]
        return scenario["history"].copy()
    return get_cached_history


def _nifty():
    """NIFTY 50 stand-in history."""
    return _ohlcv(drift=0.0004, seed=99, start_price=20_000.0)


def _risk_engine():
    """Same RiskEngine class app.py builds from its sidebar settings."""
    return RiskEngine(investment_capital=500_000, max_risk_pct=1.0, max_position_pct=20.0)


def _run_app(scenario):
    """Run app.py's own evaluate_stock (exec'd from source) and return (result, archived rows)."""
    ns = {
        "np": np, "pd": pd, "ta": ta, "runtime": app_runtime, "trade_contracts": trade_contracts,
        "datetime": datetime, "time": __import__("time"), "math": math, "logging": logging,
        "compute_feature_frame": compute_feature_frame, "estimate_execution_cost": estimate_execution_cost,
        "scanner_composite_score": scanner_composite_score,
        "STRATEGY_VERSION": STRATEGY_VERSION, "TARGET_VERSION": TARGET_VERSION,
        "LOGGER": logging.getLogger("god_mode_quant"),
        "IST": datetime.timezone(datetime.timedelta(hours=5, minutes=30)),
        # scan-page state
        "instrument_dict": ({TICKER: scenario["key"]} if scenario["key"] else {}),
        "live_quote_data": ({scenario["key"]: scenario["quote"]} if scenario["quote"] else {}),
        "access_token": "token", "get_cached_history": _fetch(scenario), "fetch_upstox_history": "fetch-sentinel",
        "TECHNICAL_FEATURE_STORE": _FeatureStore(), "nifty_hist_df": _nifty(),
        "MARKET_OPEN": scenario["market_open"], "custom_days": scenario["days"],
        "max_stock_price": scenario["max_price"], "require_weekly_align": scenario["weekly"],
        "use_advanced_signal_filters": scenario["advanced"], "risk_engine": _risk_engine(),
        "analysis_timing_log": [], "scan_mode": "Full", "regime": {"regime": "TEST"},
        "_scan_run_id": "run-1", "_scan_as_of_date": datetime.date(2026, 11, 9),
        "_scanner_strategy_version": "scanner-test",
        # live-only evidence / governance stand-ins (not part of the copied core)
        "PIT_STORE": _PitStore(), "DECISION_EVIDENCE_SPINE": types.SimpleNamespace(capture=lambda **kw: None),
        "_live_lineage_from_quote": lambda *a, **kw: (None, None, {}),
        "_register_runtime_lineage": lambda lineage: None, "_known_universe_lineage": lambda *a: None,
        "LiveEvidenceBundle": _Stub, "LiveEvidenceContext": _Stub,
        "EvidenceTier": types.SimpleNamespace(OBSERVATION="OBSERVATION"),
        "feature_schema_digest": lambda lineage: "digest", "build_equity_live_evidence": lambda **kw: None,
        "_evaluate_governance_fail_closed": lambda *a, **kw: {
            "allow_trade": True, "blocking_reasons": [], "decision_evidence": {"decision_id": "d"}},
        "MODEL_REGISTRY": None, "RUNTIME_EVIDENCE_STORE": None, "MODEL_ARTIFACT_SIGNER": None,
        "RUNTIME_EVIDENCE_SIGNER": None, "EQUITY_MANUAL_QUOTE_POLICY": None,
        "APP_BUILD": "test", "RUNTIME_CODE_HASH": "code", "RUNTIME_QUANT_CONFIG_HASH": "config",
        "RESILIENCE_CONTROL_PLANE": types.SimpleNamespace(policy=types.SimpleNamespace(digest="policy")),
    }
    wanted = (set(ENGINE_SHARED) - {"LOGGER", "IST"}) | {"evaluate_stock"}
    nodes = []
    for node in ast.walk(APP_TREE):
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and node in APP_TREE.body and any(
                isinstance(t, ast.Name) and t.id in wanted for t in node.targets):
            nodes.append(node)
    nodes.sort(key=lambda n: n.lineno)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), ns)
    return ns["evaluate_stock"](TICKER), ns["PIT_STORE"].rows


def _run_engine(scenario):
    """Run the headless copy on the same inputs; return (result, observation)."""
    observation = EquityCapture(identity={"ticker": TICKER}, settings={})
    result = evaluate_stage2(
        TICKER, key=scenario["key"],
        live_quote_data=({scenario["key"]: scenario["quote"]} if scenario["quote"] else {}),
        access_token="token", get_cached_history=_fetch(scenario), fetch_upstox_history="fetch-sentinel",
        feature_store=_FeatureStore(), nifty_hist_df=_nifty(), market_open=scenario["market_open"],
        custom_days=scenario["days"], max_stock_price=scenario["max_price"],
        require_weekly_align=scenario["weekly"], use_advanced_signal_filters=scenario["advanced"],
        risk_engine=_risk_engine(), observation=observation, analysis_timing_log=[],
    )
    return result, observation


QUOTE = {"last_price": None, "market_data": {"bid_price": None, "ask_price": None}}
SCENARIOS = {
    "no_instrument_key": _scenario(history=_ohlcv(), key=None),
    "short_history": _scenario(history=_ohlcv(n=150)),
    "history_error": _scenario(history=ConnectionError("provider down")),
    "price_filter": _scenario(history=_ohlcv(), max_price=50.0),
    "downtrend": _scenario(history=_ohlcv(drift=-0.002, seed=3)),
    "late_breakdown": _scenario(history=_ohlcv(tail_days=30, tail_drift=-0.006, seed=11)),
    "steady_uptrend": _scenario(history=_ohlcv()),
    "uptrend_market_open": _scenario(history=_ohlcv(), market_open=True),
    "uptrend_weekly_required": _scenario(history=_ohlcv(), weekly=True),
    "uptrend_advanced_filters": _scenario(history=_ohlcv(), advanced=True),
    "uptrend_with_quote": _scenario(history=_ohlcv(), quote={
        "last_price": 1.0, "market_data": {"bid_price": 0.99, "ask_price": 1.01}}),
    "noisy_flat": _scenario(history=_ohlcv(drift=0.0002, noise=0.02, seed=5)),
    "noisy_flat_advanced": _scenario(history=_ohlcv(drift=0.0002, noise=0.02, seed=5), advanced=True),
    "short_horizon": _scenario(history=_ohlcv(seed=21), days=5),
    "supertrend_flip": _scenario(history=_ohlcv(drift=0.0015, tail_days=8, tail_drift=-0.002, seed=4)),
    "flat_tail_rr": _scenario(history=_ohlcv(drift=0.004, noise=0.015, tail_days=40, tail_noise=0.002,
                                             tail_volume=2.5, seed=207), weekly=True),
    "breakout_not_confirmed": _scenario(history=_ohlcv(drift=0.0005, noise=0.015, tail_days=20, tail_drift=0.01,
                                                       tail_noise=0.02, range_scale=3.0, seed=88),
                                        weekly=True, advanced=True, days=5),
    # Found by randomized search to reach specific branches (seeds pinned).
    "completed_bar_shortfall": _scenario(history=_ohlcv(n=215, future_days=10)),
    "ema20_below_ema50": _scenario(history=_ohlcv(drift=-0.003, noise=0.008, tail_days=5, tail_drift=0.02,
                                                  tail_noise=0.002, range_scale=3.0, seed=89), weekly=True, days=30),
    "weekly_bearish": _scenario(history=_ohlcv(drift=0.0025, noise=0.015, tail_volume=2.5, seed=484),
                                weekly=True, days=5),
    "pass_buy": _scenario(history=_ohlcv(drift=0.004, noise=0.008, tail_days=40, tail_drift=0.004,
                                         tail_noise=0.002, range_scale=3.0, seed=396)),
    "advanced_pass": _scenario(history=_ohlcv(drift=0.0005, noise=0.015, tail_days=3, tail_drift=0.02,
                                              tail_noise=0.02, tail_volume=4.0, range_scale=3.0, seed=477),
                               advanced=True),
    "advanced_pass_buy": _scenario(history=_ohlcv(drift=0.004, noise=0.008, tail_days=1, tail_noise=0.002,
                                                  tail_volume=4.0, range_scale=3.0, seed=199), advanced=True),
}


@pytest.fixture(scope="module")
def outcomes():
    """Both implementations' results for every scenario (computed once)."""
    return {name: (_run_app(s), _run_engine(s)) for name, s in SCENARIOS.items()}


def _fix_live_quote_price(scenario):
    """A live last_price must be near the history close, as in production."""
    if scenario["quote"] and scenario["quote"].get("last_price") == 1.0:
        close = float(scenario["history"]["Close"].iloc[-1])
        scenario["quote"] = {"last_price": close, "market_data": {"bid_price": close * 0.999,
                                                                  "ask_price": close * 1.001}}


for _s in SCENARIOS.values():
    _fix_live_quote_price(_s)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_headless_copy_reaches_the_same_decision_as_app(outcomes, name):
    """Same reject (category + reason), or same archived score/levels/features/action on a pass."""
    (app_result, archived), ((engine_record, engine_reject), observation) = outcomes[name]
    app_row, app_reject = app_result
    assert (app_row is None) == (engine_record is None), f"{name}: pass/reject differs"
    if app_row is None:
        assert engine_reject == app_reject
        if SCENARIOS[name]["key"] is None:
            assert archived == []  # app.py archives nothing without an instrument key
            return
        assert archived[-1]["stage2_pass"] is False
        assert archived[-1]["rejection_reason"] == f"{app_reject['category']}: {app_reject['reason']}"
        # Caller archives score/levels from observation.inputs, exactly as app.py's _reject does.
        for column, field in (("score", "score"), ("entry", "price"), ("stop", "sl"), ("target", "tgt")):
            assert archived[-1][column] == observation.inputs.get(field)
        return
    assert engine_reject is None
    passed = archived[-1]
    assert passed["stage2_pass"] is True
    for column in ("score", "entry", "stop", "target"):
        assert engine_record[column] == passed[column], column
    app_features = {k: v for k, v in passed["features"].items() if k not in APP_ONLY_FEATURE_KEYS}
    assert engine_record["features"] == app_features
    assert engine_record["action"] == app_row["Action"]
    assert engine_record["action_reason"] == app_row["_action_reason"]
    assert engine_record["governance_evaluated"] is False
    app_inputs = dict(passed["features"]["equity_capture"]["inputs"])
    engine_inputs = dict(observation.snapshot()["inputs"])
    app_inputs.pop("timing", None), engine_inputs.pop("timing", None)
    # elapsed_fraction reads the wall clock (both runs are milliseconds apart); during
    # market hours after the 0.15 floor it differs in the last digits, so compare loosely.
    app_fraction, engine_fraction = app_inputs.pop("elapsed_fraction"), engine_inputs.pop("elapsed_fraction")
    assert (app_fraction is None) == (engine_fraction is None)
    assert app_fraction is None or abs(app_fraction - engine_fraction) < 0.001
    assert engine_inputs == app_inputs


def test_scenarios_exercise_the_pass_path_and_many_reject_branches(outcomes):
    """Guard against a vacuous differential: a pass and at least 5 distinct reject reasons are hit."""
    # outcomes[name] == (app_output, (engine_result, observation)); engine_result == (record, reject)
    engine_results = {name: engine_result for name, (_app, (engine_result, _obs)) in outcomes.items()}
    passes = [name for name, (record, _reject) in engine_results.items() if record is not None]
    reasons = {reject["reason"] for _record, reject in engine_results.values() if reject}
    assert passes, "no scenario reached the pass path"
    assert len(reasons) >= 5, sorted(reasons)


def test_specific_rejects(outcomes):
    """Known inputs hit the expected app.py reject reasons."""
    def reject(name):
        """The engine's reject dict for scenario `name`."""
        return outcomes[name][1][0][1]
    assert reject("no_instrument_key") == {"category": "Data", "reason": "No instrument key found for this ticker"}
    assert reject("short_history") == {"category": "Data",
                                       "reason": "Insufficient price history (need 210+ trading days)"}
    assert reject("history_error") == {"category": "Error", "reason": "Analysis error: ConnectionError"}
    assert reject("price_filter")["category"] == "Price Filter"
    assert reject("downtrend")["category"] == "Trend"
    assert reject("supertrend_flip") == {"category": "Trend", "reason": "SuperTrend indicator is bearish"}
    assert reject("flat_tail_rr")["category"] == "Risk:Reward"
    assert reject("breakout_not_confirmed") == {
        "category": "Volume", "reason": "Breakout not confirmed: ADX, volume, and ATR aren't all rising together"}
    assert reject("completed_bar_shortfall") == {"category": "Data",
                                                 "reason": "Insufficient completed daily price history"}
    assert reject("ema20_below_ema50") == {"category": "Trend", "reason": "20-day EMA is below the 50-day EMA"}
    assert reject("weekly_bearish")["category"] == "Weekly Trend"


def test_pass_paths_include_buy_and_advanced_filters(outcomes):
    """Passes are reached with the default and the advanced filter set, including a "Buy" action."""
    def record(name):
        """The engine's pass record for scenario `name`."""
        return outcomes[name][1][0][0]
    assert record("pass_buy")["action"] == "Buy"
    assert record("advanced_pass") is not None
    assert record("advanced_pass_buy")["action"] == "Buy"


def test_pass_record_shape(outcomes):
    """A pass carries app.py's archive fields plus action/timing, and says governance was not evaluated."""
    record, reject = outcomes["steady_uptrend"][1][0]
    assert reject is None
    assert set(record) == {"score", "entry", "stop", "target", "features", "action", "action_reason",
                           "timing", "governance_evaluated"}
    assert record["governance_evaluated"] is False
    assert 0 < record["stop"] < record["entry"] < record["target"]
    assert {"components", "horizon_days", "execution_cost_bps", "weekly_trend"} <= set(record["features"])
