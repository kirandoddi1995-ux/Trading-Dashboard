"""Read-only public NAV cross-check for the live-market audit."""
import hashlib
import io

import numpy as np
import pandas as pd
import requests

import mf_research
from audit_20260831_checks import load_functions


def main():
    response = requests.get("https://api.tigzig.com/mf/v1/download?format=latest.csv.gz", timeout=(5, 15))
    response.raise_for_status()
    snapshot = pd.read_csv(io.BytesIO(response.content), compression="gzip", low_memory=False)
    names = snapshot["scheme_name"].str.lower()
    selected = snapshot[names.str.contains("icici prudential large cap") & names.str.contains("direct")
                        & names.str.contains("growth")]
    if len(selected) != 1:
        print(selected[["scheme_code", "scheme_name"]].to_string(index=False))
        raise ValueError("Expected an unambiguous fund match")
    code = str(int(selected.iloc[0]["scheme_code"]))
    response = requests.get("https://api.tigzig.com/mf/v1/nav",
                            params={"scheme": code, "since": "2014-08-01"}, timeout=(5, 15))
    response.raise_for_status()
    payload = response.json()
    series = pd.DataFrame(payload["data"])
    series["date"] = pd.to_datetime(series["date"])
    series["nav"] = pd.to_numeric(series["nav"])
    series = series.sort_values("date").drop_duplicates("date", keep="last")
    latest = series.iloc[-1]
    outputs = {"scheme": payload["scheme_name"], "amfi_code": code,
               "nav_date": str(latest["date"].date()), "nav": float(latest["nav"])}
    for years in (1, 3, 5):
        earlier = series.loc[series["date"] <= latest["date"] - pd.DateOffset(years=years)].iloc[-1]
        outputs[f"{years}y_cagr"] = (float(latest["nav"] / earlier["nav"]) ** (1 / years) - 1) * 100
        outputs[f"{years}y_start_date"] = str(earlier["date"].date())
        outputs[f"{years}y_start_nav"] = float(earlier["nav"])
    risk_nav = series.loc[series["date"] >= latest["date"] - pd.DateOffset(years=3), "nav"]
    returns = risk_nav.pct_change().dropna()
    outputs["volatility"] = float(returns.std() * np.sqrt(252) * 100)
    window = series.loc[series["date"] >= latest["date"] - pd.DateOffset(years=5) - pd.Timedelta(days=31), "nav"]
    outputs["max_drawdown"] = float((window / window.cummax() - 1).min() * 100)
    ns = load_functions("_normalize_tigzig_nav_item", "compute_mf_returns")
    ns.update(hashlib=hashlib, mfr=mf_research)
    calculated = ns["compute_mf_returns"](ns["_normalize_tigzig_nav_item"](payload))
    for independently_computed, app_key in (("1y_cagr", "ret_1y"), ("3y_cagr", "cagr_3y"),
                                          ("5y_cagr", "cagr_5y"), ("volatility", "volatility"),
                                          ("max_drawdown", "max_drawdown")):
        assert np.isclose(outputs[independently_computed], calculated[app_key]), app_key
    print(outputs)
    print("PASS: independent NAV return/volatility/drawdown arithmetic agrees with application function.")
    print("This is same-provider arithmetic verification, not independent confirmation of upstream NAV accuracy.")


if __name__ == "__main__":
    main()
