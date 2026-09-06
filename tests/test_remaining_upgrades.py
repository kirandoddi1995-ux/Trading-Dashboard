import sqlite3, threading, time
import numpy as np
import pandas as pd
import pytest

from provider_contracts import ProviderContractError, ProviderErrorKind, OptionGreeks, classify_provider_error
from quantitative_services import estimate_execution_cost, cross_sectional_scores, optimize_portfolio
from iv_surface import (
    black_scholes_greeks,
    black_scholes_price,
    calendar_total_variance_check,
    implied_volatility,
    normalize_iv_surface,
)
from model_registry import ModelRegistry
from mf_archive import MutualFundArchive
from risk_engine import RiskEngine
from scan_jobs import ScanJobs


def connect(path):
    conn=sqlite3.connect(path,timeout=10,check_same_thread=False); conn.execute("PRAGMA journal_mode=WAL"); return conn


def test_provider_contracts_classify_and_reject_bad_schema():
    assert classify_provider_error(status_code=401)==ProviderErrorKind.AUTHENTICATION
    assert classify_provider_error(status_code=429)==ProviderErrorKind.RATE_LIMIT
    assert classify_provider_error(TimeoutError())==ProviderErrorKind.TIMEOUT
    with pytest.raises(ProviderContractError): OptionGreeks.parse({"iv":"bad"})


def test_liquidity_costs_increase_with_spread_and_participation():
    liquid=estimate_execution_cost(price=100,bid=99.99,ask=100.01,order_value=10_000,average_daily_value=10_000_000)
    illiquid=estimate_execution_cost(price=100,bid=99,ask=101,order_value=1_000_000,average_daily_value=2_000_000)
    assert illiquid.round_trip_bps>liquid.round_trip_bps


def test_cross_section_and_portfolio_constraints():
    frame=pd.DataFrame({"Sector":["A","A","B","B"],"Liquidity":[1,2,3,4],"Momentum":[10,20,30,40]})
    scored=cross_sectional_scores(frame,["Momentum"]); assert scored["Cross-sectional Score"].between(0,100).all()
    base=pd.Series(np.arange(50,dtype=float)); other=pd.Series(np.arange(50,dtype=float)[::-1])
    candidates=[{"Ticker":"A1","score":90,"_sector":"A","_returns":base},
                {"Ticker":"A2","score":89,"_sector":"A","_returns":base},
                {"Ticker":"B1","score":88,"_sector":"B","_returns":other}]
    chosen=optimize_portfolio(candidates,max_positions=2,max_sector_weight=.5,correlation_limit=.75)
    assert [x["Ticker"] for x in chosen]==["A1","B1"]


def test_iv_surface_normalizes_fractional_iv_and_flags_invalid_greeks():
    chain=[{"strike_price":100,"call_options":{"market_data":{"bid_price":9,"ask_price":10},
            "option_greeks":{"iv":.2,"delta":.5,"gamma":.01,"theta":-1,"vega":2}}}]
    surface=normalize_iv_surface(chain,100,"2026-12-31",now="2026-09-01 10:00+05:30")
    assert surface.iloc[0].iv==20
    assert not bool(surface.iloc[0].greeks_valid)


def test_iv_and_greeks_are_recomputed_from_executable_mid():
    now = pd.Timestamp("2026-09-01 10:00", tz="Asia/Kolkata")
    expiry = pd.Timestamp("2026-12-31 15:30", tz="Asia/Kolkata")
    years = (expiry - now).total_seconds() / (365 * 86400)
    price = black_scholes_price(100, 100, years, .25, option_type="CE")
    greeks = black_scholes_greeks(100, 100, years, .25, option_type="CE")
    chain = [{"strike_price": 100, "call_options": {
        "market_data": {"bid_price": price - .01, "ask_price": price + .01},
        "option_greeks": {"iv": .25, **greeks},
    }}]
    surface = normalize_iv_surface(chain, 100, expiry, now=now)
    assert implied_volatility(price, 100, 100, years, option_type="CE") == pytest.approx(.25, rel=1e-5)
    assert bool(surface.iloc[0].production_valid)


def test_option_price_bound_and_put_call_parity_violations_fail_closed():
    now = pd.Timestamp("2026-09-01 10:00", tz="Asia/Kolkata")
    expiry = pd.Timestamp("2026-12-31 15:30", tz="Asia/Kolkata")
    years = (expiry - now).total_seconds() / (365 * 86400)
    call = black_scholes_price(100, 100, years, .25, option_type="CE")
    call_greeks = black_scholes_greeks(100, 100, years, .25, option_type="CE")
    put_greeks = black_scholes_greeks(100, 100, years, .25, option_type="PE")
    chain = [{"strike_price": 100,
              "call_options": {"market_data": {"bid_price": call - .01, "ask_price": call + .01},
                               "option_greeks": {"iv": .25, **call_greeks}},
              "put_options": {"market_data": {"bid_price": 30, "ask_price": 31},
                              "option_greeks": {"iv": .25, **put_greeks}}}]
    surface = normalize_iv_surface(chain, 100, expiry, now=now)
    assert not surface.production_valid.any()
    assert any("parity" in reason.lower() or "bounds" in reason.lower()
               for reasons in surface.validation_failures for reason in reasons)


def test_calendar_total_variance_decrease_blocks_surface():
    surface = pd.DataFrame({
        "log_moneyness": [0.0, 0.0],
        "years": [0.1, 0.2],
        "model_iv": [40.0, 20.0],
    })
    result = calendar_total_variance_check(surface)
    assert result["status"] == "NO_TRADE"


def test_model_drift_and_mutual_fund_archive(tmp_path):
    path=str(tmp_path/"models.sqlite3"); registry=ModelRegistry(connect,path)
    assert registry.population_stability_index(np.arange(100),np.arange(100))==pytest.approx(0)
    registry.register("m","logit","SIDEWAYS","1","challenger",{}, {},status="SHADOW")
    archive=MutualFundArchive(connect,path)
    assert archive.archive([{"scheme_code":"1","scheme_name":"F","category":"Equity","ter":.5}])==1
    conn=connect(path); assert conn.execute("SELECT COUNT(*) FROM mf_point_in_time").fetchone()[0]==1; conn.close()


def test_scan_job_persists_eta_and_can_cancel(tmp_path):
    path=str(tmp_path/"jobs.sqlite3"); jobs=ScanJobs(path); gate=threading.Event()
    def worker(item): gate.wait(.3); return ({"Ticker":item,"score":1},None)
    jobs.start("owner","sig",list("ABCDE"),worker,workers=1,timeout=5)
    time.sleep(.03); snap=jobs.snapshot("owner","sig"); assert "eta_seconds" in snap
    assert jobs.cancel("owner","sig"); gate.set()
    deadline=time.time()+3
    while time.time()<deadline and not jobs.snapshot("owner","sig")["complete"]: time.sleep(.02)
    conn=connect(path); status=conn.execute("SELECT status FROM durable_scan_jobs").fetchone()[0]; conn.close()
    assert status=="CANCELLED"


def test_risk_engine_was_extracted_without_behavior_change():
    risk=RiskEngine(1_000_000,2,20); sizing=risk.calculate_position_size(10,100)
    assert sizing.qty==2000 and risk.calculate_risk_reward(100,90,120)==2
