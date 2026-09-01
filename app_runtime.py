"""Small, independently testable runtime safeguards (no provider credentials)."""
import datetime as dt
import math
import logging
import re
import secrets
import time
from email.utils import parsedate_to_datetime


class SecretRedactor(logging.Filter):
    def __init__(self, values=()):
        super().__init__()
        self.values = tuple(str(v) for v in values if v)

    def filter(self, record):
        message = record.getMessage()
        for value in self.values:
            message = message.replace(value, '[REDACTED]')
        message = re.sub(r'(?i)(Bearer\s+)[^\s,;]+', r'\1[REDACTED]', message)
        message = re.sub(r'(?i)([?&](?:key|token|api_key|access_token)=)[^&\s]+', r'\1[REDACTED]', message)
        record.msg, record.args = message, ()
        # Exception strings can include provider URLs or credentials. Keep type only.
        if record.exc_info and record.exc_info[0]:
            record.msg += ' [' + record.exc_info[0].__name__ + ']'
            record.exc_info, record.exc_text = None, None
        return True


def retain_preferences(state):
    """Detach disappearing widgets from Streamlit cleanup; keep a durable copy.

    Runs before widgets are declared. Widget events are applied before this call,
    so a just-edited value wins over the saved copy, not vice versa.
    """
    allowed = {"sb_refresh_secs", "sb_refresh_v2", "sb_investment_capital", "sb_max_risk_pct",
               "sb_max_position_pct", "sb_max_sector_pct", "sb_options_notrade_threshold",
               "sb_require_mtf", "sb_tickers", "eq_days_input", "eq_price_filter",
               "eq_weekly_filter", "eq_advanced_filters", "eq_scan_mode_simple",
               "mf_category_select", "mf_validation_cost"}
    def is_preference(key):
        return key in allowed or str(key).startswith("subpage_")
    # Buttons and file uploaders must NEVER be assigned through session_state.
    saved = {k:v for k,v in state.get("_preferences", {}).items() if is_preference(k)}
    keys = set(saved) | {k for k in state if is_preference(k)}
    for key in keys:
        value = state[key] if key in state else saved[key]
        state[key] = value
        saved[key] = value
    state["_preferences"] = saved


def session_identity(state):
    """Unpredictable per-session ownership, without introducing a login system."""
    if not state.get("_private_session_id"):
        state["_private_session_id"] = secrets.token_hex(32)
    return state["_private_session_id"]


def csv_bytes(frame):
    """Neutralize formula strings in spreadsheet exports; numeric columns stay numeric."""
    def safe(value):
        if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
            return "'" + value
        return value
    return frame.map(safe).to_csv(index=False).encode('utf-8-sig')


def quote_is_fresh(quote, now=None, max_age=30.0):
    now = time.time() if now is None else float(now)
    try:
        stamp = float(quote.get("_ts", 0))
        price = float(quote.get("last_price", 0))
        return math.isfinite(price) and price > 0 and 0 <= now - stamp <= max_age
    except (AttributeError, TypeError, ValueError):
        return False


def option_oi_change_bias(chain_data, spot_price, strikes_each_side=5):
    """Summarize fresh near-ATM OI additions without treating total OI as flow.

    Put additions are evidence of support and call additions are evidence of
    resistance.  Only positive additions versus ``prev_oi`` are compared;
    missing or internally balanced data deliberately returns no direction.
    """
    try:
        spot = float(spot_price)
        if not math.isfinite(spot) or spot <= 0:
            return {"bias": None, "call_add": 0.0, "put_add": 0.0, "ratio": None, "contracts": 0}
        rows = []
        for item in chain_data or []:
            strike = float(item.get("strike_price"))
            call = ((item.get("call_options") or {}).get("market_data") or {})
            put = ((item.get("put_options") or {}).get("market_data") or {})
            values = (call.get("oi"), call.get("prev_oi"), put.get("oi"), put.get("prev_oi"))
            if any(value is None for value in values):
                continue
            call_add = max(float(values[0]) - float(values[1]), 0.0)
            put_add = max(float(values[2]) - float(values[3]), 0.0)
            if all(math.isfinite(value) for value in (strike, call_add, put_add)):
                rows.append((abs(strike - spot), call_add, put_add))
        limit = max(int(strikes_each_side) * 2 + 1, 3)
        selected = sorted(rows, key=lambda row: row[0])[:limit]
        call_add = sum(row[1] for row in selected)
        put_add = sum(row[2] for row in selected)
        total = call_add + put_add
        if len(selected) < 3 or total <= 0:
            bias, ratio = None, None
        else:
            ratio = put_add / call_add if call_add > 0 else math.inf
            if put_add >= call_add * 1.25 and put_add > 0:
                bias = "Bullish"
            elif call_add >= put_add * 1.25 and call_add > 0:
                bias = "Bearish"
            else:
                bias = None
        return {
            "bias": bias,
            "call_add": round(call_add, 2),
            "put_add": round(put_add, 2),
            "ratio": None if ratio is None else ("inf" if math.isinf(ratio) else round(ratio, 3)),
            "contracts": len(selected),
        }
    except (AttributeError, TypeError, ValueError, OverflowError):
        return {"bias": None, "call_add": 0.0, "put_add": 0.0, "ratio": None, "contracts": 0}


def score_option_direction(
    *, price, previous_close, ema20, vwap=None, rsi=None, macd_hist=None,
    pcr=None, oi_change_bias=None, trend_15m=None, trend_1h=None,
    volume_confirmed=False, market_open=True, minimum_score=25,
):
    """Conservative CE/PE direction decision with explicit conflict gates.

    No single indicator can authorize a trade. During an open session a usable
    15-minute trend is mandatory; mild signals also require matching 1-hour
    confirmation. A move opposite today's index direction is allowed only as a
    strong, confirmed reversal. The function returns ``Neutral`` whenever the
    evidence is incomplete or contradictory.
    """
    def finite(value):
        try:
            parsed = float(value)
            return parsed if math.isfinite(parsed) else None
        except (TypeError, ValueError):
            return None

    price = finite(price)
    previous_close = finite(previous_close)
    ema20 = finite(ema20)
    vwap = finite(vwap)
    rsi = finite(rsi)
    macd_hist = finite(macd_hist)
    pcr = finite(pcr)
    if not price or price <= 0 or not previous_close or previous_close <= 0 or not ema20 or ema20 <= 0:
        return {
            "bias": "Neutral", "bull_score": 0.0, "bear_score": 0.0, "net_score": 0.0,
            "threshold": max(float(minimum_score), 25.0), "decision_reason": "Required spot/close/EMA data unavailable",
            "bull_factors": [], "bear_factors": [], "day_change_pct": None,
        }

    scores = {"Bullish": 0.0, "Bearish": 0.0}
    factors = {"Bullish": [], "Bearish": []}
    groups = {"Bullish": set(), "Bearish": set()}

    def add(direction, name, weight, group):
        if direction not in scores or weight <= 0:
            return
        scores[direction] += float(weight)
        factors[direction].append(name)
        groups[direction].add(group)

    ema_gap_pct = (price / ema20 - 1.0) * 100.0
    if ema_gap_pct > 0.05:
        add("Bullish", "EMA20", 15, "trend")
    elif ema_gap_pct < -0.05:
        add("Bearish", "EMA20", 15, "trend")

    if vwap and vwap > 0:
        vwap_gap_pct = (price / vwap - 1.0) * 100.0
        if vwap_gap_pct > 0.05:
            add("Bullish", "VWAP", 10, "trend")
        elif vwap_gap_pct < -0.05:
            add("Bearish", "VWAP", 10, "trend")

    day_change_pct = (price / previous_close - 1.0) * 100.0
    if abs(day_change_pct) >= 0.05:
        direction = "Bullish" if day_change_pct > 0 else "Bearish"
        add(direction, "Session move", min(10.0, abs(day_change_pct) / 0.50 * 10.0), "momentum")

    if rsi is not None:
        if rsi > 52:
            add("Bullish", "RSI", min(10.0, (rsi - 52.0) / 18.0 * 10.0), "momentum")
        elif rsi < 48:
            add("Bearish", "RSI", min(10.0, (48.0 - rsi) / 18.0 * 10.0), "momentum")

    if macd_hist is not None:
        if macd_hist > 0:
            add("Bullish", "MACD", 10, "momentum")
        elif macd_hist < 0:
            add("Bearish", "MACD", 10, "momentum")

    if pcr is not None:
        if pcr >= 1.05:
            add("Bullish", "PCR level", 5, "positioning")
        elif pcr <= 0.85:
            add("Bearish", "PCR level", 5, "positioning")

    if oi_change_bias in ("Bullish", "Bearish"):
        add(oi_change_bias, "Near-ATM OI change", 10, "positioning")

    for trend, name in ((trend_15m, "15m trend"), (trend_1h, "1h trend")):
        if trend in ("Bullish", "Bearish"):
            add(trend, name, 15, "intraday")

    leader = "Bullish" if scores["Bullish"] > scores["Bearish"] else "Bearish"
    if volume_confirmed and len(factors[leader]) >= 3:
        add(leader, "Volume confirmation", 5, "participation")

    bull_score = min(scores["Bullish"], 100.0)
    bear_score = min(scores["Bearish"], 100.0)
    net_score = round(bull_score - bear_score, 1)
    threshold = max(float(minimum_score), 25.0)
    direction = "Bullish" if net_score > 0 else ("Bearish" if net_score < 0 else None)
    strength = abs(net_score)
    reason = None

    if direction is None or strength < threshold:
        reason = "Directional score below the conservative threshold"
    elif len(factors[direction]) < 3 or len(groups[direction]) < 2:
        reason = "Fewer than three aligned factors from two independent evidence groups"
    elif market_open and trend_15m not in ("Bullish", "Bearish"):
        reason = "Current-session 15-minute trend unavailable"
    elif market_open and trend_15m != direction:
        reason = "Current 15-minute trend conflicts with the proposed direction"
    elif strength < 45 and trend_1h != direction:
        reason = "Mild direction lacks matching 1-hour confirmation"
    elif trend_1h in ("Bullish", "Bearish") and trend_1h != direction:
        reason = "One-hour trend conflicts with the proposed direction"
    elif direction == "Bearish" and day_change_pct >= 0.10:
        if not (strength >= 45 and trend_15m == "Bearish" and trend_1h == "Bearish" and len(factors[direction]) >= 4):
            reason = "Bearish proposal conflicts with a positive session and lacks strong reversal confirmation"
    elif direction == "Bullish" and day_change_pct <= -0.10:
        if not (strength >= 45 and trend_15m == "Bullish" and trend_1h == "Bullish" and len(factors[direction]) >= 4):
            reason = "Bullish proposal conflicts with a negative session and lacks strong reversal confirmation"

    bias = "Neutral" if reason else (("Bullish" if strength >= 45 else "Mildly Bullish") if direction == "Bullish"
                                      else ("Bearish" if strength >= 45 else "Mildly Bearish"))
    return {
        "bias": bias,
        "bull_score": round(bull_score, 1),
        "bear_score": round(bear_score, 1),
        "net_score": net_score,
        "threshold": threshold,
        "decision_reason": reason or "Aligned evidence",
        "bull_factors": factors["Bullish"],
        "bear_factors": factors["Bearish"],
        "bull_groups": sorted(groups["Bullish"]),
        "bear_groups": sorted(groups["Bearish"]),
        "day_change_pct": round(day_change_pct, 3),
        "trend_15m": trend_15m,
        "trend_1h": trend_1h,
    }


def retry_delay(value, now=None):
    """Retry-After permits either seconds or an HTTP date. Never shorten it."""
    try:
        delay = float(value)
        return max(delay, 0.0) if math.isfinite(delay) else 1.0
    except (TypeError, ValueError):
        try:
            when = parsedate_to_datetime(str(value))
            when = when.replace(tzinfo=dt.timezone.utc) if when.tzinfo is None else when
            return max(0.0, when.timestamp() - (time.time() if now is None else now))
        except (TypeError, ValueError, OverflowError):
            return 1.0


def scan_counts(signals, rejections, stats, displayed=0):
    errors = sum(int(rejections.get(k, 0)) for k in ("Data", "Error", "Timeout"))
    rejected = sum(int(v) for v in rejections.values())
    return {"submitted": int(stats.get("futures_submitted", 0)),
            "processed": int(stats.get("completed", len(signals) + rejected)),
            "valid_data": len(signals) + rejected - errors,
            "data_failures": errors,
            "technical_rejections": rejected - errors,
            "passed": len(signals), "displayed": int(displayed)}


def equity_action(score, price, stop, target, atr, horizon_days):
    """Risk feasibility is a screening guardrail, not a probability forecast."""
    try:
        values = [float(x) for x in (score, price, stop, target, atr)]
        score, price, stop, target, atr = values
        if not all(math.isfinite(x) for x in values) or not (0 < stop < price < target) or atr <= 0:
            return "Unavailable", "Invalid trade levels"
        if (price - stop) / price > .20 or target - price > atr * max(4., 2. * math.sqrt(max(horizon_days, 1))):
            return "Watch", "Wide stop or target relative to this horizon; no actionable size"
        return ("Buy", "") if score >= 70 else ("Watch", "Score below the action threshold")
    except (TypeError, ValueError):
        return "Unavailable", "Invalid trade levels"


def trade_outcome(bars, entry, stop, target, cost_pct=0.30):
    """Long trade, next-bar entry, conservative barriers and net costs on ALL exits.

    bars contains (Open, High, Low, Close). Stop gaps execute at the lower open;
    target gaps receive only the target (conservative limit-fill assumption).
    """
    if not all(math.isfinite(float(x)) for x in (entry, stop, target, cost_pct)) or cost_pct < 0:
        raise ValueError("Invalid trade costs or levels")
    if not (0 < stop < entry < target) or not bars:
        raise ValueError("Invalid trade or empty holding window")
    exit_price, reason, offset = float(bars[-1][3]), "TIME", len(bars) - 1
    for offset, (opening, high, low, close) in enumerate(bars):
        if not all(math.isfinite(float(x)) and float(x) > 0 for x in (opening, high, low, close)):
            raise ValueError("Invalid OHLC in holding window")
        if opening <= stop:
            exit_price, reason = float(opening), "GAP_STOP"
            break
        if low <= stop:
            exit_price, reason = float(stop), "BOTH_STOP" if high >= target else "STOP"
            break
        if high >= target:
            exit_price, reason = float(target), "TARGET"
            break
    net = (exit_price / float(entry) - 1) * 100 - max(float(cost_pct), 0.)
    return {"net_return_pct": net, "win": int(net > 0), "exit_price": exit_price,
            "reason": reason, "offset": offset}
