"""Execution costs, cross-sectional ranking and portfolio-level selection."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ExecutionCostEstimate:
    spread_bps: float
    slippage_bps: float
    impact_bps: float
    statutory_bps: float
    brokerage_bps: float

    @property
    def round_trip_bps(self):
        return self.spread_bps + self.slippage_bps + self.impact_bps + self.statutory_bps + self.brokerage_bps


def estimate_execution_cost(*, price, bid=None, ask=None, order_value=0, average_daily_value=0,
                            asset_class="equity") -> ExecutionCostEstimate:
    price = max(float(price or 0), 1e-9)
    spread = max(float(ask or price) - float(bid or price), 0.0) / price * 10_000
    participation = max(float(order_value or 0), 0) / max(float(average_daily_value or 0), 1)
    impact = min(100.0, 15.0 * np.sqrt(participation))
    slippage = max(2.0, spread * .5)
    statutory = 8.0 if asset_class == "equity" else 12.0
    brokerage = 4.0
    return ExecutionCostEstimate(float(spread), float(slippage), float(impact), statutory, brokerage)


def cross_sectional_scores(frame: pd.DataFrame, features, sector_col="Sector", liquidity_col="Liquidity"):
    out = frame.copy()
    usable = [feature for feature in features if feature in out]
    if not usable: raise ValueError("No cross-sectional features are available")
    group_cols = [sector_col] if sector_col in out else []
    if liquidity_col in out:
        out["_liquidity_bucket"] = pd.qcut(out[liquidity_col].rank(method="first"), 5, labels=False, duplicates="drop")
        group_cols.append("_liquidity_bucket")
    transformed = []
    for feature in usable:
        values = pd.to_numeric(out[feature], errors="coerce")
        if group_cols:
            rank = out.assign(_v=values).groupby(group_cols, dropna=False)["_v"].rank(pct=True)
        else:
            rank = values.rank(pct=True)
        name = f"{feature}_cross_sectional"
        out[name] = (rank.fillna(.5) * 100).clip(0, 100)
        transformed.append(name)
    out["Cross-sectional Score"] = out[transformed].mean(axis=1)
    return out.drop(columns=["_liquidity_bucket"], errors="ignore")


def optimize_portfolio(candidates, *, max_positions=10, max_sector_weight=.30,
                       correlation_limit=.75, risk_budget=1.0):
    """Greedy marginal-risk optimizer with sector and correlation constraints."""
    ranked = sorted(candidates, key=lambda row: float(row.get("score", 0)), reverse=True)
    selected, sector_weight = [], {}
    equal_weight = 1.0 / max(int(max_positions), 1)
    for row in ranked:
        if len(selected) >= max_positions: break
        sector = row.get("_sector") or row.get("Sector") or "Unclassified"
        if sector_weight.get(sector, 0) + equal_weight > max_sector_weight + 1e-9: continue
        returns = row.get("_returns")
        too_correlated = False
        for chosen in selected:
            other = chosen.get("_returns")
            if isinstance(returns, pd.Series) and isinstance(other, pd.Series):
                aligned = pd.concat([returns, other], axis=1).dropna()
                # For a long-only portfolio, strong negative correlation is a
                # diversifier; reject only excessive positive co-movement.
                if len(aligned) >= 20 and float(aligned.corr().iloc[0, 1]) > correlation_limit:
                    too_correlated = True; break
        if too_correlated: continue
        item = dict(row); item["_portfolio_weight"] = equal_weight; item["_risk_budget_share"] = risk_budget * equal_weight
        selected.append(item); sector_weight[sector] = sector_weight.get(sector, 0) + equal_weight
    return selected
