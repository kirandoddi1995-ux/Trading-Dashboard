"""No-arbitrage diagnostics and normalized implied-volatility surface."""
from __future__ import annotations
import numpy as np
import pandas as pd


def normalize_iv_surface(chain, spot, expiry, now=None):
    now = pd.Timestamp.now(tz="Asia/Kolkata") if now is None else pd.Timestamp(now)
    expiry_ts = pd.Timestamp(expiry)
    if expiry_ts.tzinfo is None: expiry_ts = expiry_ts.tz_localize("Asia/Kolkata")
    dte = max((expiry_ts - now).total_seconds() / 86400.0, 1/24)
    rows = []
    for item in chain or []:
        strike = float(item.get("strike_price") or 0)
        if strike <= 0: continue
        for side, option_type in (("call_options", "CE"), ("put_options", "PE")):
            option = item.get(side) or {}; greeks = option.get("option_greeks") or {}; market = option.get("market_data") or {}
            iv = greeks.get("iv")
            if iv is None: continue
            iv = float(iv); iv = iv * 100 if 0 < iv < 3 else iv
            bid, ask = market.get("bid_price"), market.get("ask_price")
            rows.append({"strike": strike, "option_type": option_type, "dte": dte,
                         "log_moneyness": float(np.log(strike / float(spot))), "iv": iv,
                         "delta": greeks.get("delta"), "gamma": greeks.get("gamma"),
                         "theta": greeks.get("theta"), "vega": greeks.get("vega"),
                         "bid": bid, "ask": ask,
                         "spread_pct": ((float(ask)-float(bid))/max((float(ask)+float(bid))/2, 1e-9)*100
                                        if bid is not None and ask is not None else None)})
    frame = pd.DataFrame(rows)
    if frame.empty: return frame
    frame["iv_zscore"] = frame.groupby(["dte", "option_type"])["iv"].transform(
        lambda x: (x-x.median()) / max(float((x-x.median()).abs().median())*1.4826, 1e-9))
    frame["greeks_valid"] = (
        pd.to_numeric(frame["iv"], errors="coerce").between(.1, 500)
        & pd.to_numeric(frame["gamma"], errors="coerce").fillna(0).ge(0)
        & pd.to_numeric(frame["delta"], errors="coerce").abs().fillna(2).le(1.05)
    )
    frame["surface_outlier"] = frame["iv_zscore"].abs() > 4
    return frame

