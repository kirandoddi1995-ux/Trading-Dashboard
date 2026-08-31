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
