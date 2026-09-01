"""Position sizing and trade-risk calculations independent of Streamlit."""
from dataclasses import dataclass
import math


@dataclass
class PositionSizing:
    qty: int
    risk_based_qty: int
    capital_based_qty: int
    margin_based_qty: int | None = None
    initial_margin_req: float = 0.0
    exposure_req: float = 0.0


class RiskEngine:
    def __init__(self, investment_capital=0.0, max_risk_pct=1.0, max_position_pct=20.0, asset_class="equity"):
        self.investment_capital=float(investment_capital or 0); self.max_risk_pct=float(max_risk_pct or 0)
        self.max_position_pct=float(max_position_pct or 0); self.asset_class=str(asset_class).lower()
    def risk_budget(self): return self.investment_capital*self.max_risk_pct/100
    def position_capital_budget(self): return self.investment_capital*self.max_position_pct/100
    @staticmethod
    def calculate_stop(entry,atr,direction="long",multiplier=1.5):
        distance=max(float(atr),0)*float(multiplier); return float(entry)+(distance if str(direction).lower()=="short" else -distance)
    @staticmethod
    def calculate_target(entry,atr,direction="long",multiplier=2.0):
        distance=max(float(atr),0)*float(multiplier); return float(entry)+(-distance if str(direction).lower()=="short" else distance)
    @staticmethod
    def calculate_risk_per_unit(entry,stop,cost_buffer=0,gap_buffer_pct=0):
        return max(abs(float(entry)-float(stop))*(1+max(float(gap_buffer_pct),0)/100)+max(float(cost_buffer or 0),0),0)
    def calculate_position_size(self,risk_per_unit,price_per_unit,unit_multiplier=1,actual_margin_required=None):
        risk_per_unit=float(risk_per_unit or 0); price_per_unit=float(price_per_unit or 0); unit_multiplier=max(int(unit_multiplier or 1),1)
        if risk_per_unit<=0 or price_per_unit<=0 or self.investment_capital<=0:
            return PositionSizing(0,0,0,0 if actual_margin_required is not None else None,0,0)
        risk_qty=math.floor(self.risk_budget()/(risk_per_unit*unit_multiplier))
        position_value=price_per_unit*unit_multiplier; cap_qty=math.floor(self.position_capital_budget()/position_value)
        margin_qty=None
        if actual_margin_required is not None and actual_margin_required>0:
            margin_qty=math.floor(self.position_capital_budget()/float(actual_margin_required)); qty=min(risk_qty,cap_qty,margin_qty)
            initial=float(actual_margin_required)*qty
        else: qty=min(risk_qty,cap_qty); initial=position_value*qty
        qty=max(int(qty),0)
        return PositionSizing(qty,max(int(risk_qty),0),max(int(cap_qty),0),max(int(margin_qty),0) if margin_qty is not None else None,initial,position_value*qty)
    @staticmethod
    def calculate_capital_required(price_per_unit,qty,unit_multiplier=1,actual_margin_required=None):
        if actual_margin_required is not None and actual_margin_required>0: return float(actual_margin_required)*max(int(qty or 0),0)
        return max(float(price_per_unit or 0),0)*max(int(qty or 0),0)*max(int(unit_multiplier or 1),1)
    def validate_trade(self,qty,capital_required):
        if int(qty or 0)<=0: return False,"Quantity is zero; risk budget or capital cap is too small."
        if self.investment_capital<=0: return False,"Investment capital must be greater than zero."
        if float(capital_required or 0)>self.position_capital_budget()+1e-9: return False,"Position margin/capital requirement exceeds maximum position-capital limit."
        return True,"OK"
    @staticmethod
    def calculate_risk_reward(entry,stop,target):
        risk=abs(float(entry)-float(stop)); return round(abs(float(target)-float(entry))/risk,2) if risk>0 else 0
    def calculate_portfolio_heat(self,risk_amounts):
        return sum(float(x or 0) for x in risk_amounts)/self.investment_capital*100 if self.investment_capital>0 else 0
