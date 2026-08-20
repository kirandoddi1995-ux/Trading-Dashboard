import streamlit as st
import pandas_ta as ta
import pandas as pd
import numpy as np
import requests
import re
import datetime
import time
import os
import json
import concurrent.futures
import threading
import urllib.parse
import sqlite3
import plotly.graph_objects as go
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import warnings
import scipy.stats as si
import math
import logging
from dataclasses import dataclass
from pathlib import Path
warnings.filterwarnings("ignore")

LOG_LEVEL = os.environ.get("QUANT_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
LOGGER = logging.getLogger("god_mode_quant")
APP_BUILD = "v13.0-ENTERPRISE-PRODUCTION"

# ==========================================
# EMBEDDED RISK ENGINE + ADVANCED MARGIN API
# ==========================================

try:
    import upstox_client
    UPSTOX_SDK_AVAILABLE = True
except ImportError:
    upstox_client = None
    UPSTOX_SDK_AVAILABLE = False


@dataclass
class PositionSizing:
    qty: int
    risk_based_qty: int
    capital_based_qty: int
    margin_based_qty: int | None = None
    initial_margin_req: float = 0.0
    exposure_req: float = 0.0


class RiskEngine:
    """Advanced institutional risk engine supporting live margin calculation and gap risk."""

    def __init__(self, investment_capital=0.0, max_risk_pct=1.0,
                 max_position_pct=20.0, asset_class="equity"):
        self.investment_capital = float(investment_capital or 0.0)
        self.max_risk_pct = float(max_risk_pct or 0.0)
        self.max_position_pct = float(max_position_pct or 0.0)
        self.asset_class = str(asset_class).lower()

    def risk_budget(self):
        return self.investment_capital * self.max_risk_pct / 100.0

    def position_capital_budget(self):
        return self.investment_capital * self.max_position_pct / 100.0

    @staticmethod
    def calculate_stop(entry, atr, direction="long", multiplier=1.5):
        entry = float(entry)
        atr = max(float(atr), 0.0)
        distance = atr * float(multiplier)
        if str(direction).lower() == "short":
            return entry + distance
        return entry - distance

    @staticmethod
    def calculate_target(entry, atr, direction="long", multiplier=2.0):
        entry = float(entry)
        atr = max(float(atr), 0.0)
        distance = atr * float(multiplier)
        if str(direction).lower() == "short":
            return entry - distance
        return entry + distance

    @staticmethod
    def calculate_risk_per_unit(entry, stop, cost_buffer=0.0, gap_buffer_pct=0.0):
        risk_base = abs(float(entry) - float(stop))
        gap_adjusted_risk = risk_base * (1.0 + max(float(gap_buffer_pct), 0.0) / 100.0)
        return max(gap_adjusted_risk + max(float(cost_buffer or 0.0), 0.0), 0.0)

    def calculate_position_size(self, risk_per_unit, price_per_unit,
                                unit_multiplier=1, actual_margin_required=None):
        risk_per_unit = float(risk_per_unit or 0.0)
        price_per_unit = float(price_per_unit or 0.0)
        unit_multiplier = max(int(unit_multiplier or 1), 1)
        if risk_per_unit <= 0 or price_per_unit <= 0 or self.investment_capital <= 0:
            return PositionSizing(0, 0, 0, 0 if actual_margin_required is not None else None, 0.0, 0.0)

        risk_per_position_unit = risk_per_unit * unit_multiplier
        risk_qty = math.floor(self.risk_budget() / risk_per_position_unit) if risk_per_position_unit > 0 else 0

        position_value_per_unit = price_per_unit * unit_multiplier
        cap_qty = math.floor(self.position_capital_budget() / position_value_per_unit) if position_value_per_unit > 0 else 0

        margin_qty = None
        init_req_total = 0.0
        if actual_margin_required is not None and actual_margin_required > 0:
            margin_per_position_unit = float(actual_margin_required)
            margin_qty = math.floor(self.position_capital_budget() / margin_per_position_unit) if margin_per_position_unit > 0 else 0
            qty = min(risk_qty, cap_qty, margin_qty)
            init_req_total = margin_per_position_unit * qty
        else:
            qty = min(risk_qty, cap_qty)
            init_req_total = position_value_per_unit * qty

        final_qty = max(int(qty), 0)
        notional_exposure = position_value_per_unit * final_qty

        return PositionSizing(
            qty=final_qty,
            risk_based_qty=max(int(risk_qty), 0),
            capital_based_qty=max(int(cap_qty), 0),
            margin_based_qty=(max(int(margin_qty), 0) if margin_qty is not None else None),
            initial_margin_req=init_req_total,
            exposure_req=notional_exposure,
        )

    @staticmethod
    def calculate_capital_required(price_per_unit, qty, unit_multiplier=1, actual_margin_required=None):
        if actual_margin_required is not None and actual_margin_required > 0:
            return float(actual_margin_required) * max(int(qty or 0), 0)
        return max(float(price_per_unit or 0.0), 0.0) * max(int(qty or 0), 0) * max(int(unit_multiplier or 1), 1)

    def validate_trade(self, qty, capital_required):
        qty = int(qty or 0)
        capital_required = float(capital_required or 0.0)
        if qty <= 0:
            return False, "Quantity is zero; risk budget or capital cap is too small."
        if self.investment_capital <= 0:
            return False, "Investment capital must be greater than zero."
        if capital_required > self.position_capital_budget() + 1e-9:
            return False, "Position margin/capital requirement exceeds maximum position-capital limit."
        return True, "OK"

    @staticmethod
    def calculate_risk_reward(entry, stop, target):
        risk = abs(float(entry) - float(stop))
        reward = abs(float(target) - float(entry))
        if risk <= 0:
            return 0.0
        return round(reward / risk, 2)

    def calculate_portfolio_heat(self, risk_amounts):
        total = sum(float(x or 0.0) for x in risk_amounts)
        if self.investment_capital <= 0:
            return 0.0
        return total / self.investment_capital * 100.0


DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "market_cache.sqlite3")
_CACHE_INIT_LOCK = threading.Lock()


def _cache_connect(db_path=DEFAULT_DB_PATH):
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _ensure_cache_schema(db_path=DEFAULT_DB_PATH):
    with _CACHE_INIT_LOCK:
        conn = _cache_connect(db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS candles (
                    instrument_key TEXT NOT NULL,
                    dt TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    oi REAL,
                    PRIMARY KEY (instrument_key, dt)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_candles_key_dt ON candles(instrument_key, dt)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_meta (
                    instrument_key TEXT PRIMARY KEY,
                    last_sync_date TEXT
                )
            """)
            conn.commit()
        finally:
            conn.close()


_ensure_cache_schema()


def _serialize_history(instrument_key, df, db_path=DEFAULT_DB_PATH):
    if df is None or df.empty:
        return 0
    _ensure_cache_schema(db_path)
    rows = []
    for idx, row in df.iterrows():
        try:
            dt = pd.Timestamp(idx).tz_localize(None).isoformat()
        except Exception:
            dt = str(idx)
        rows.append((
            instrument_key, dt,
            float(row.get("Open")) if pd.notna(row.get("Open")) else None,
            float(row.get("High")) if pd.notna(row.get("High")) else None,
            float(row.get("Low")) if pd.notna(row.get("Low")) else None,
            float(row.get("Close")) if pd.notna(row.get("Close")) else None,
            float(row.get("Volume")) if pd.notna(row.get("Volume")) else None,
            float(row.get("OI")) if pd.notna(row.get("OI")) else None,
        ))
    conn = _cache_connect(db_path)
    try:
        conn.executemany("""
            INSERT INTO candles(instrument_key, dt, open, high, low, close, volume, oi)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(instrument_key, dt) DO UPDATE SET
              open=excluded.open,
              high=excluded.high,
              low=excluded.low,
              close=excluded.close,
              volume=excluded.volume,
              oi=excluded.oi
        """, rows)
        conn.execute(
            "INSERT INTO sync_meta(instrument_key, last_sync_date) VALUES (?, ?) "
            "ON CONFLICT(instrument_key) DO UPDATE SET last_sync_date=excluded.last_sync_date",
            (instrument_key, datetime.datetime.now(IST).date().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def _read_cached_history(instrument_key, days, db_path=DEFAULT_DB_PATH):
    _ensure_cache_schema(db_path)
    cutoff = (pd.Timestamp.now().normalize() - pd.Timedelta(days=int(days))).isoformat()
    conn = _cache_connect(db_path)
    try:
        df = pd.read_sql_query(
            "SELECT dt AS Date, open AS Open, high AS High, low AS Low, close AS Close, volume AS Volume, oi AS OI "
            "FROM candles WHERE instrument_key = ? AND dt >= ? ORDER BY dt",
            conn, params=(instrument_key, cutoff)
        )
    finally:
        conn.close()
    if df.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume", "OI"])
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).set_index("Date")
    return df


def _cache_last_sync_date(instrument_key, db_path=DEFAULT_DB_PATH):
    _ensure_cache_schema(db_path)
    conn = _cache_connect(db_path)
    try:
        row = conn.execute("SELECT last_sync_date FROM sync_meta WHERE instrument_key = ?", (instrument_key,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def get_cached_history(instrument_key, token, days=365, fetch_fn=None, db_path=DEFAULT_DB_PATH):
    cached = _read_cached_history(instrument_key, days, db_path)
    today = datetime.datetime.now(IST).date().isoformat()
    sync_date = _cache_last_sync_date(instrument_key, db_path)

    required_rows = min(max(int(days * 0.55), 60), int(days))
    if sync_date == today and len(cached) >= required_rows:
        return cached

    if fetch_fn is None:
        return cached

    try:
        fresh = fetch_fn(instrument_key, token, days=days)
        if fresh is not None and not fresh.empty:
            _serialize_history(instrument_key, fresh, db_path)
            return _read_cached_history(instrument_key, days, db_path)
    except Exception as exc:
        LOGGER.warning("Historical fetch failed for %s: %s", instrument_key, exc)
    return cached


def get_avg_volumes_batched(db_path, keys_list, lookback=20):
    """Batched SQLite volume engine: fetches 20-day average volume for all instruments in one query."""
    if not keys_list:
        return {}
    _ensure_cache_schema(db_path)
    conn = _cache_connect(db_path)
    try:
        placeholders = ','.join(['?'] * len(keys_list))
        query = f"""
            SELECT instrument_key, volume FROM (
                SELECT instrument_key, volume, 
                       ROW_NUMBER() OVER (PARTITION BY instrument_key ORDER BY dt DESC) as rn
                FROM candles
                WHERE instrument_key IN ({placeholders}) AND volume IS NOT NULL
            ) WHERE rn <= ?
        """
        params = list(keys_list) + [int(lookback) + 1]
        df = pd.read_sql_query(query, conn, params=params)
    except Exception:
        df = pd.DataFrame(columns=["instrument_key", "volume"])
    finally:
        conn.close()

    result = {}
    if not df.empty:
        for k, grp in df.groupby("instrument_key"):
            vals = [float(x) for x in grp["volume"].values if x is not None and float(x) > 0]
            if len(vals) > int(lookback):
                vals = vals[1:]  # exclude today's partial volume
            vals = vals[:int(lookback)]
            if vals:
                result[k] = float(np.mean(vals))
    return result


def get_cache_stats(db_path=DEFAULT_DB_PATH):
    _ensure_cache_schema(db_path)
    conn = _cache_connect(db_path)
    try:
        symbols = conn.execute("SELECT COUNT(DISTINCT instrument_key) FROM candles").fetchone()[0]
        rows = conn.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
        today = datetime.datetime.now(IST).date().isoformat()
        synced_today = conn.execute("SELECT COUNT(*) FROM sync_meta WHERE last_sync_date = ?", (today,)).fetchone()[0]
    finally:
        conn.close()
    return {
        "symbols_cached": int(symbols or 0),
        "symbols_synced_today": int(synced_today or 0),
        "total_candle_rows": int(rows or 0),
    }


def warm_cache(instrument_keys, token, days=400, db_path=DEFAULT_DB_PATH,
               max_workers=8, progress_callback=None, fetch_fn=None):
    _ensure_cache_schema(db_path)
    keys = [k for k in dict.fromkeys(instrument_keys or []) if k]
    synced = 0
    already_fresh = 0
    failed = 0
    failed_keys = []
    today = datetime.datetime.now(IST).date().isoformat()

    def one(key):
        sync_date = _cache_last_sync_date(key, db_path)
        if sync_date == today:
            return key, "fresh"
        if fetch_fn is None:
            return key, "failed"
        try:
            fresh = fetch_fn(key, token, days=days)
            if fresh is None or fresh.empty:
                return key, "failed"
            _serialize_history(key, fresh, db_path)
            return key, "synced"
        except Exception as exc:
            LOGGER.warning("Warm cache failed for %s: %s", key, exc)
            return key, "failed"

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(max_workers))) as executor:
        futures = [executor.submit(one, key) for key in keys]
        total = len(futures)
        for idx, future in enumerate(concurrent.futures.as_completed(futures), 1):
            key, status = future.result()
            if status == "fresh":
                already_fresh += 1
            elif status == "synced":
                synced += 1
            else:
                failed += 1
                failed_keys.append(key)
            if progress_callback:
                try:
                    progress_callback(idx, total, key)
                except Exception:
                    pass

    return {
        "requested": len(keys),
        "synced": synced,
        "already_fresh": already_fresh,
        "failed": failed,
        "failed_keys": failed_keys,
    }

GEMINI_AVAILABLE = False
genai = None
try:
    from google import genai as genai_mod
    genai = genai_mod
    GEMINI_AVAILABLE = True
    GEMINI_SDK = "google.genai"
except ImportError:
    try:
        import google.generativeai as genai_mod
        genai = genai_mod
        GEMINI_AVAILABLE = True
        GEMINI_SDK = "google.generativeai"
    except ImportError:
        GEMINI_SDK = None

# --- PAGE CONFIG & RESPONSIVE CSS ---
st.set_page_config(layout="wide", page_title="God-Mode Quant Terminal v13.0")

st.markdown("""
    <style>
    .block-container {
        padding-top: 3.5rem;
        padding-bottom: 2rem;
        padding-left: 2rem;
        padding-right: 2rem;
        max-width: 100%;
    }
    .stApp { background-color: #050505; color: #d1d4dc; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    [data-testid="stSidebar"] { background-color: #0a0a0a; border-right: 1px solid #1f1f1f; }
    div.stMetric { background-color: #0f0f0f; border: 1px solid #1f1f1f; padding: 12px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); border-left: 3px solid #2962ff;}
    .stChatMessage { background-color: #0f0f0f; border-radius: 8px; padding: 10px; margin-bottom: 10px; border: 1px solid #1f1f1f; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# DYNAMIC MARKET STATUS ENGINE (Upstox API v2)
# ==========================================
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

@st.cache_data(ttl=60)
def fetch_nse_market_status():
    try:
        url = "https://api.upstox.com/v2/market/status/nse"
        headers = {"Accept": "application/json"}
        with requests.Session() as s:
            res = s.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json().get("data") or {}
                return data
    except Exception:
        pass
    return {}

def is_market_open():
    now = datetime.datetime.now(IST)
    if now.weekday() >= 5:
        return False
    status_data = fetch_nse_market_status()
    market_status = str(status_data.get("status", "")).lower()
    if market_status and ("closed" in market_status or "holiday" in market_status or "halt" in market_status):
        return False
    open_t = now.replace(hour=9, minute=15, second=0, microsecond=0)
    close_t = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return open_t <= now <= close_t

MARKET_OPEN = is_market_open()

# ==========================================
# COMMAND CENTER: SIDEBAR & AUTHENTICATION
# ==========================================
st.sidebar.header("Live Connection Status")
st.sidebar.caption(f"Build: {APP_BUILD}")

secret_upstox = ""
secret_gemini = ""
try:
    if hasattr(st, "secrets"):
        secret_upstox = st.secrets.get("UPSTOX_TOKEN", "")
        secret_gemini = st.secrets.get("GEMINI_API_KEY", "")
except Exception:
    pass

default_upstox = os.environ.get("UPSTOX_TOKEN", secret_upstox)
default_gemini = os.environ.get("GEMINI_API_KEY", secret_gemini)

st.sidebar.markdown("### API Keys")
upstox_input = st.sidebar.text_input("Upstox Token (Daily)", value=default_upstox, type="password", key="sb_upstox", autocomplete="current-password")
access_token = upstox_input if upstox_input else default_upstox

gemini_input = st.sidebar.text_input("Gemini API Key", value=default_gemini, type="password", key="sb_gemini", autocomplete="current-password")
gemini_api_key = gemini_input if gemini_input else default_gemini

if access_token:
    st.sidebar.success("UPSTOX: CONNECTED")
else:
    st.sidebar.error("UPSTOX: DISCONNECTED (Missing Token)")


st.sidebar.markdown("---")
st.sidebar.header("Engine Controls")
refresh_secs = st.sidebar.select_slider(
    "Auto-Refresh Interval", options=[5, 10, 15, 30, 60], value=15, key="sb_refresh_secs",
    help="The header ticker (NIFTY/SENSEX/BANKNIFTY) refreshes independently every 5s regardless of this setting. "
         "This controls how often the full page (option chain, screener, etc.) recomputes."
)
live_refresh = st.sidebar.toggle("Continuous Auto-Refresh", value=True, key="sb_refresh")

AUTOREFRESH_AVAILABLE = False
try:
    from streamlit_autorefresh import st_autorefresh
    AUTOREFRESH_AVAILABLE = True
except ImportError:
    AUTOREFRESH_AVAILABLE = False

if live_refresh:
    if AUTOREFRESH_AVAILABLE:
        st_autorefresh(interval=refresh_secs * 1000, key="autorefresh_timer")
    else:
        # IMPORTANT: without this package the toggle above does nothing — the page will
        # only ever update when you interact with a widget (e.g. switching tabs), which
        # is exactly the "data only changes when I click something" symptom. Fix:
        # add `streamlit-autorefresh` to requirements.txt and redeploy.
        st.sidebar.error(
            "⚠️ `streamlit-autorefresh` is NOT installed — auto-refresh is inactive. "
            "Add `streamlit-autorefresh` to requirements.txt and redeploy, otherwise this page "
            "will only update when you click something."
        )
        if st.sidebar.button("🔄 Refresh Now", key="manual_refresh_btn", use_container_width=True):
            st.rerun()

if st.sidebar.button("Force Reconnect & Clear Cache", use_container_width=True, key="sb_reconnect"):
    st.cache_data.clear()
    st.rerun()

# ==========================================
# REAL UPSTOX FUNDS & MARGIN FETCH
# ==========================================
@st.cache_data(ttl=60)
def fetch_upstox_funds_and_margin(token):
    if not token:
        return None
    try:
        url = "https://api.upstox.com/v2/user/get-funds-and-margin"
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        with get_robust_session() as session:
            res = session.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json().get("data", {})
                equity_data = data.get("equity", {})
                available = equity_data.get("available_margin") or equity_data.get("net")
                if available is not None:
                    return float(available)
    except Exception:
        pass
    return None

# ==========================================
# ACTUAL UPSTOX INSTRUMENT MARGIN API (/v2/charges/margin)
# ==========================================
@st.cache_data(ttl=300)
def fetch_upstox_instrument_margin(instrument_key, quantity, transaction_type, product, token):
    """Query Upstox Margin Details API to get exact required margin for an instrument."""
    if not token or not instrument_key:
        return None
    try:
        url = "https://api.upstox.com/v2/charges/margin"
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {
            "instruments": [
                {
                    "instrument_key": instrument_key,
                    "quantity": int(quantity),
                    "transaction_type": str(transaction_type).upper(),
                    "product": str(product).upper()
                }
            ]
        }
        with get_robust_session() as session:
            res = session.post(url, headers=headers, json=payload, timeout=6)
            if res.status_code == 200:
                data = res.json().get("data", {})
                total_margin = data.get("total_margin") or data.get("margin")
                if total_margin is not None:
                    return float(total_margin)
    except Exception:
        pass
    return None

# ==========================================
# PERSISTENT IV HISTORY
# ==========================================
IV_HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".iv_history_cache.json")

def load_iv_history_disk():
    try:
        if os.path.exists(IV_HISTORY_FILE):
            with open(IV_HISTORY_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_iv_history_disk(history):
    try:
        with open(IV_HISTORY_FILE, "w") as f:
            json.dump(history, f)
    except Exception:
        pass

# ==========================================
# ROBUST SESSION & DATA ENGINE
# ==========================================
def get_robust_session():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


# ==========================================
# HISTORICAL DATA ENGINE — EMBEDDED SINGLE FILE
# ==========================================
def _history_to_dataframe(candles):
    rows = []
    for candle in candles or []:
        if not isinstance(candle, (list, tuple)) or len(candle) < 6:
            continue
        rows.append(candle[:7])
    if not rows:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume", "OI"])
    df = pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume", "OI"][:len(rows[0])])
    for c in ["Open", "High", "Low", "Close", "Volume", "OI"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date", "Close"]).set_index("Date").sort_index()
    for c in ["Open", "High", "Low", "Close", "Volume", "OI"]:
        if c not in df.columns:
            df[c] = np.nan
    return df[["Open", "High", "Low", "Close", "Volume", "OI"]]


def _fetch_upstox_history_impl(instrument_key, token, days=400):
    if not token or not instrument_key:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume", "OI"])
    end_date = datetime.datetime.now(IST).date()
    start_date = end_date - datetime.timedelta(days=max(int(days), 30))

    if UPSTOX_SDK_AVAILABLE:
        try:
            configuration = upstox_client.Configuration()
            configuration.access_token = token
            api = upstox_client.HistoryApi(upstox_client.ApiClient(configuration))
            method = getattr(api, "get_historical_candle_data1", None) or getattr(api, "get_historical_candle_data", None)
            if callable(method):
                try:
                    resp = method(instrument_key, "day", end_date.isoformat(), start_date.isoformat(), "2.0")
                except TypeError:
                    resp = method(instrument_key, "day", end_date.isoformat())
                payload = resp.to_dict() if hasattr(resp, "to_dict") else resp
                candles = (((payload or {}).get("data") or {}).get("candles") or []) if isinstance(payload, dict) else []
                df = _history_to_dataframe(candles)
                if not df.empty:
                    return df
        except Exception as exc:
            LOGGER.debug("SDK historical fetch failed for %s: %s", instrument_key, exc)

    try:
        encoded_key = urllib.parse.quote(instrument_key, safe="")
        url = f"https://api.upstox.com/v2/historical-candle/{encoded_key}/day/{end_date.isoformat()}/{start_date.isoformat()}"
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        with get_robust_session() as session:
            res = session.get(url, headers=headers, timeout=10)
            if res.status_code != 200:
                LOGGER.warning("Historical API %s for %s: %s", res.status_code, instrument_key, res.text[:200])
                return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume", "OI"])
            candles = ((res.json().get("data") or {}).get("candles") or [])
            return _history_to_dataframe(candles)
    except Exception as exc:
        LOGGER.warning("Historical fetch failed for %s: %s", instrument_key, exc)
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume", "OI"])


def fetch_upstox_history(instrument_key, token, days=400):
    return _fetch_upstox_history_impl(instrument_key, token, days=days)

@st.cache_data(ttl=86400)
def get_full_nse_instrument_dictionary():
    try:
        url = 'https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz'
        df = pd.read_csv(url)
        nse_df = df[(df['exchange'] == 'NSE_EQ') & (df['instrument_type'] == 'EQUITY')]
        if 'series' in nse_df.columns:
            nse_df = nse_df[nse_df['series'].astype(str).str.upper() == 'EQ']
        else:
            bond_like = nse_df['tradingsymbol'].str.match(r'^[A-Za-z0-9]+\d{2}$', na=False) & \
                        nse_df['tradingsymbol'].str.contains(r'\d', na=False) & \
                        nse_df['tradingsymbol'].str.len().le(8)
            nse_df = nse_df[~(nse_df['tradingsymbol'].str.match(r'^\d', na=False) & bond_like)]
        return dict(zip(nse_df['tradingsymbol'], nse_df['instrument_key']))
    except Exception:
        return {}

instrument_dict = get_full_nse_instrument_dictionary()
all_nse_tickers = sorted(list(instrument_dict.keys())) if instrument_dict else ["RELIANCE", "TCS", "HDFCBANK", "INFY", "SBIN"]

LIQUID_CORE_TICKERS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "BHARTIARTL", "SBIN", "ITC", "LT",
    "AXISBANK", "KOTAKBANK", "BAJFINANCE", "BAJAJFINSV", "HINDUNILVR", "ASIANPAINT", "MARUTI",
    "M&M", "TATAMOTORS", "TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "COALINDIA", "ONGC",
    "NTPC", "POWERGRID", "ADANIENT", "ADANIPORTS", "DRREDDY", "CIPLA", "SUNPHARMA", "APOLLOHOSP",
    "BRITANNIA", "NESTLEIND", "TITAN", "ULTRACEMCO", "GRASIM", "SHREECEM", "DIVISLAB", "WIPRO",
    "TECHM", "HCLTECH", "LTIM", "BEL", "HAL", "BHEL", "RVNL", "IRFC", "IRCTC", "CONCOR", "SAIL",
    "NMDC", "ETERNAL", "PAYTM", "INDIGO", "TATAPOWER", "TATACONSUM", "DABUR", "GODREJCP", "MARICO",
    "HAVELLS", "VOLTAS", "POLYCAB", "DIXON", "PIDILITIND", "DLF", "GODREJPROP", "PNB", "BANKBARODA",
    "INDUSINDBK", "FEDERALBNK", "IDFCFIRSTB", "SBILIFE", "HDFCLIFE", "ICICIPRULI", "PFC", "RECLTD",
    "CHOLAFIN", "MUTHOOTFIN", "EICHERMOT", "TVSMOTOR", "BAJAJ-AUTO", "HEROMOTOCO", "ASHOKLEY",
    "TRENT", "DMART", "JUBLFOOD", "MAZDOCK", "SUZLON", "IREDA", "NHPC", "KPITTECH", "PERSISTENT",
    "COFORGE", "MPHASIS", "NAUKRI", "INDIAMART"
]

# ==========================================
# NSE SECTOR & FACTOR MAPPING
# ==========================================
NSE_SECTOR_MAP = {
    "RELIANCE": "Energy & Oil", "ONGC": "Energy & Oil", "COALINDIA": "Energy & Oil", "POWERGRID": "Utilities", "NTPC": "Utilities", "TATAPOWER": "Utilities", "ADANIENT": "Conglomerate", "ADANIPORTS": "Infrastructure",
    "TCS": "Information Technology", "INFY": "Information Technology", "WIPRO": "Information Technology", "HCLTECH": "Information Technology", "TECHM": "Information Technology", "LTIM": "Information Technology", "KPITTECH": "Information Technology", "PERSISTENT": "Information Technology", "COFORGE": "Information Technology", "MPHASIS": "Information Technology",
    "HDFCBANK": "Financial Services", "ICICIBANK": "Financial Services", "AXISBANK": "Financial Services", "SBIN": "Financial Services", "KOTAKBANK": "Financial Services", "INDUSINDBK": "Financial Services", "BAJFINANCE": "Financial Services", "BAJAJFINSV": "Financial Services", "SBILIFE": "Financial Services", "HDFCLIFE": "Financial Services", "ICICIPRULI": "Financial Services", "PFC": "Financial Services", "RECLTD": "Financial Services", "CHOLAFIN": "Financial Services", "MUTHOOTFIN": "Financial Services", "PNB": "Financial Services", "BANKBARODA": "Financial Services", "FEDERALBNK": "Financial Services", "IDFCFIRSTB": "Financial Services",
    "MARUTI": "Automobile", "TATAMOTORS": "Automobile", "M&M": "Automobile", "BAJAJ-AUTO": "Automobile", "EICHERMOT": "Automobile", "TVSMOTOR": "Automobile", "HEROMOTOCO": "Automobile", "ASHOKLEY": "Automobile",
    "SUNPHARMA": "Healthcare", "DRREDDY": "Healthcare", "CIPLA": "Healthcare", "APOLLOHOSP": "Healthcare",
    "ITC": "FMCG", "HINDUNILVR": "FMCG", "BRITANNIA": "FMCG", "NESTLEIND": "FMCG", "TATACONSUM": "FMCG", "DABUR": "FMCG", "GODREJCP": "FMCG", "MARICO": "FMCG",
    "TATASTEEL": "Metals & Mining", "JSWSTEEL": "Metals & Mining", "HINDALCO": "Metals & Mining", "VEDL": "Metals & Mining", "SAIL": "Metals & Mining", "NMDC": "Metals & Mining",
    "LT": "Capital Goods & Construction", "BEL": "Capital Goods & Construction", "HAL": "Capital Goods & Construction", "BHEL": "Capital Goods & Construction", "POLYCAB": "Capital Goods & Construction", "HAVELLS": "Capital Goods & Construction", "VOLTAS": "Capital Goods & Construction", "DIXON": "Capital Goods & Construction", "PIDILITIND": "Chemicals", "GRASIM": "Cement & Construction", "ULTRACEMCO": "Cement & Construction", "SHREECEM": "Cement & Construction",
    "ASIANPAINT": "Consumer Durables", "TITAN": "Consumer Durables", "ZOMATO": "Consumer Services", "PAYTM": "Financial Services", "INDIGO": "Aviation", "IRCTC": "Consumer Services", "CONCOR": "Logistics", "NAUKRI": "Consumer Services", "INDIAMART": "Consumer Services", "TRENT": "Retail", "DMART": "Retail", "JUBLFOOD": "Consumer Services", "MAZDOCK": "Capital Goods & Construction", "SUZLON": "Power & Renewables", "IREDA": "Financial Services", "NHPC": "Utilities", "RVNL": "Infrastructure", "IRFC": "Financial Services"
}

def get_ticker_sector(ticker):
    return NSE_SECTOR_MAP.get(ticker.upper(), "Other / Diversified")

def _normalize_quote_response(raw_data):
    normalized = {}
    if not isinstance(raw_data, dict):
        return normalized
    for k, v in raw_data.items():
        if not isinstance(v, dict):
            continue
        normalized[k] = v
        token_field = v.get('instrument_token')
        if token_field:
            normalized[token_field] = v
    return normalized


def _rest_ohlc_v3(keys_list, token, interval="1d"):
    if not token or not keys_list:
        return {}
    result = {}
    for i in range(0, len(keys_list), 500):
        chunk = keys_list[i:i + 500]
        try:
            url = "https://api.upstox.com/v3/market-quote/ohlc"
            headers = {"accept": "application/json", "Authorization": f"Bearer {token}"}
            with get_robust_session() as session:
                res = session.get(url, headers=headers, params={"instrument_key": ",".join(chunk), "interval": interval}, timeout=6)
                if res.status_code != 200:
                    LOGGER.warning("OHLC V3 %s: %s", res.status_code, res.text[:160])
                    continue
                raw = res.json().get("data") or {}
                for k, v in raw.items():
                    if not isinstance(v, dict):
                        continue
                    token_key = v.get("instrument_token") or k
                    o = v.get("ohlc") or {}
                    live_ohlc = v.get("live_ohlc") or {}
                    prev_ohlc = v.get("prev_ohlc") or {}
                    close = v.get("last_price") or o.get("close")
                    prev_close = prev_ohlc.get("close") or o.get("close")
                    result[token_key] = {
                        "instrument_token": token_key,
                        "last_price": v.get("last_price") or live_ohlc.get("close") or close,
                        "ohlc": {
                            "open": live_ohlc.get("open") or o.get("open"),
                            "high": live_ohlc.get("high") or o.get("high"),
                            "low": live_ohlc.get("low") or o.get("low"),
                            "close": prev_close,
                        },
                        "volume": v.get("volume") or live_ohlc.get("volume") or o.get("volume"),
                        "_source": "rest_ohlc_v3",
                        "_ts": time.time(),
                    }
        except Exception as exc:
            LOGGER.warning("OHLC V3 batch failed: %s", exc)
    return result


def get_live_scan_market_data(keys_list, token):
    if not token or not keys_list:
        return {}
    keys_list = [k for k in dict.fromkeys(keys_list) if k]
    result = get_live_market_quotes(keys_list, token)
    ohlc = _rest_ohlc_v3(keys_list, token, interval="1d")
    for key, q in ohlc.items():
        base = result.get(key, {})
        merged = dict(base)
        merged["last_price"] = base.get("last_price") or q.get("last_price")
        merged["ohlc"] = {**(q.get("ohlc") or {}), **(base.get("ohlc") or {})}
        merged["volume"] = q.get("volume") if q.get("volume") is not None else base.get("volume")
        result[key] = merged
    return result

# ==========================================
# LIVE MARKET DATA — WEBSOCKET + REST
# ==========================================
class MarketDataBuffer:
    def __init__(self, token):
        self.token = token
        self.lock = threading.RLock()
        self.quotes = {}
        self.subscribed = set()
        self.connected = False
        self.last_error = None
        self.last_message_ts = 0.0
        self.streamer = None
        self.thread = None
        self._start_lock = threading.Lock()

    @staticmethod
    def _plain(obj):
        if obj is None or isinstance(obj, (str,int,float,bool)):
            return obj
        if isinstance(obj, dict):
            return {str(k): MarketDataBuffer._plain(v) for k,v in obj.items()}
        if isinstance(obj, (list,tuple)):
            return [MarketDataBuffer._plain(v) for v in obj]
        try:
            from google.protobuf.json_format import MessageToDict
            if hasattr(obj, 'DESCRIPTOR'):
                return MessageToDict(obj, preserving_proto_field_name=True)
        except Exception:
            pass
        for attr in ('to_dict','toDict'):
            try:
                fn=getattr(obj,attr,None)
                if callable(fn): return MarketDataBuffer._plain(fn())
            except Exception: pass
        if hasattr(obj, '__dict__'):
            try: return {k:MarketDataBuffer._plain(v) for k,v in vars(obj).items() if not k.startswith('_')}
            except Exception: pass
        return str(obj)

    def _extract_quotes(self, message):
        data = self._plain(message)
        if not isinstance(data, dict): return []
        feeds = data.get('feeds') or data.get('Feeds') or data.get('data',{}).get('feeds')
        if not isinstance(feeds, dict): return []
        out=[]
        for key, feed in feeds.items():
            if not isinstance(feed, dict): continue
            ltpc = feed.get('ltpc') or {}
            full = feed.get('fullFeed') or feed.get('full_feed') or feed.get('ff') or feed.get('fullFeedUnion') or {}
            if isinstance(full, dict):
                market = full.get('marketFF') or full.get('market_ff') or full.get('marketFullFeed') or {}
                indexf = full.get('indexFF') or full.get('index_ff') or {}
            else:
                market, indexf = {}, {}
            if not ltpc:
                ltpc = market.get('ltpc') or indexf.get('ltpc') or {}
            ext = market.get('eFeedDetails') or market.get('extendedFeedDetails') or {}
            m_ohlc = market.get('marketOHLC') or market.get('marketOhlc') or {}
            ohlc_list = m_ohlc.get('ohlc') if isinstance(m_ohlc,dict) else None
            daily=None
            if isinstance(ohlc_list,list):
                for o in ohlc_list:
                    if isinstance(o,dict) and str(o.get('interval','')).lower() in ('1d','d1','1day'):
                        daily=o; break
            q={
                'instrument_token': key,
                'last_price': ltpc.get('ltp'),
                'last_trade_time': ltpc.get('ltt'),
                'last_trade_qty': ltpc.get('ltq'),
                'ohlc': {
                    'open': daily.get('open') if daily else ext.get('open'),
                    'high': daily.get('high') if daily else ext.get('yh'),
                    'low': daily.get('low') if daily else ext.get('yl'),
                    'close': ltpc.get('cp') or ext.get('cp') or ext.get('lastClose') or ext.get('lc'),
                },
                'volume': (daily.get('vol') if daily else None) or ext.get('vtt') or ext.get('tv'),
                'oi': ext.get('oi'),
                'oi_change': ext.get('changeOi'),
                'bid_price': ext.get('bp') or ext.get('bidPrice'),
                'ask_price': ext.get('ap') or ext.get('askPrice'),
                '_source': 'websocket',
                '_ts': time.time(),
            }
            out.append((key,q))
        return out

    def on_message(self, message):
        try:
            updates=self._extract_quotes(message)
            if not updates: return
            with self.lock:
                for key,q in updates:
                    if q.get('last_price') is not None or q.get('ohlc',{}).get('close') is not None:
                        self.quotes[key]=q
                self.last_message_ts=time.time()
        except Exception as e:
            self.last_error=str(e)

    def on_open(self):
        self.connected=True
        self.last_error=None
        try:
            with self.lock:
                keys=list(self.subscribed)
            if keys and self.streamer is not None:
                self.streamer.subscribe(keys, 'ltpc')
        except Exception as e:
            self.last_error=str(e)

    def on_close(self, *args):
        self.connected=False

    def on_error(self, err):
        self.last_error=str(err)
        self.connected=False

    def _run(self):
        try:
            configuration=upstox_client.Configuration()
            configuration.access_token=self.token
            self.streamer=upstox_client.MarketDataStreamerV3(upstox_client.ApiClient(configuration))
            self.streamer.on('open', self.on_open)
            self.streamer.on('message', self.on_message)
            self.streamer.on('close', self.on_close)
            self.streamer.on('error', self.on_error)
            try:
                self.streamer.auto_reconnect(True, 5, 20)
            except Exception:
                pass
            self.streamer.connect()
        except Exception as e:
            self.last_error=str(e)
            self.connected=False

    def ensure(self, keys):
        keys=[k for k in dict.fromkeys(keys) if k]
        if not keys or not self.token or not UPSTOX_SDK_AVAILABLE:
            return
        with self.lock:
            self.subscribed.update(keys)
        with self._start_lock:
            if self.thread is None or not self.thread.is_alive():
                self.thread=threading.Thread(target=self._run, daemon=True, name='upstox-market-stream')
                self.thread.start()
            elif self.connected:
                try:
                    if keys:
                        self.streamer.subscribe(keys, 'ltpc')
                except Exception:
                    pass

    def snapshot(self, keys):
        with self.lock:
            return {k:dict(self.quotes[k]) for k in keys if k in self.quotes}

    def status(self):
        with self.lock:
            age=(time.time()-self.last_message_ts) if self.last_message_ts else None
            return {'connected':self.connected,'subscribed':len(self.subscribed),'quotes':len(self.quotes),'age':age,'error':self.last_error}

@st.cache_resource(show_spinner=False)
def get_market_data_buffer(token):
    return MarketDataBuffer(token) if token else None

def _rest_market_quotes(keys_list, token):
    if not token or not keys_list: return {}
    try:
        keys_str=','.join(keys_list)
        url='https://api.upstox.com/v3/market-quote/ltp'
        headers={'accept':'application/json','Authorization':f'Bearer {token}'}
        with get_robust_session() as session:
            res=session.get(url, headers=headers, params={'instrument_key':keys_str}, timeout=5)
            if res.status_code==200:
                raw=res.json().get('data',{})
                return _normalize_quote_response(raw)
    except Exception:
        pass
    return {}

def get_live_market_quotes(keys_list, token):
    if not token or not keys_list: return {}
    keys_list=[k for k in dict.fromkeys(keys_list) if k]
    buffer=get_market_data_buffer(token) if UPSTOX_SDK_AVAILABLE else None
    if buffer is not None:
        buffer.ensure(keys_list)
        snap=buffer.snapshot(keys_list)
        missing=[k for k in keys_list if k not in snap]
        if missing:
            rest=_rest_market_quotes(missing, token)
            if rest:
                snap.update(rest)
        return snap
    return _rest_market_quotes(keys_list, token)

def get_live_market_quotes_chunked(keys_list, token, chunk_size=500):
    if not token or not keys_list: return {}
    result={}
    if UPSTOX_SDK_AVAILABLE:
        result.update(get_live_market_quotes(keys_list, token))
        return result
    for i in range(0,len(keys_list),chunk_size):
        result.update(get_live_market_quotes(keys_list[i:i+chunk_size], token))
    return result

if UPSTOX_SDK_AVAILABLE and access_token:
    try:
        _md_status = get_market_data_buffer(access_token).status()
        if _md_status["connected"]:
            st.sidebar.success(f"WEBSOCKET: LIVE · {_md_status['quotes']:,} quotes cached")
        else:
            st.sidebar.info("WEBSOCKET: CONNECTING / REST fills initial misses")
    except Exception:
        st.sidebar.info("WEBSOCKET: startup pending / REST fallback")
elif access_token:
    st.sidebar.caption("WebSocket SDK not installed — REST fallback active. Install: pip install upstox-python-sdk")

# ==========================================
# FAST UNIVERSE FUNNEL (Batched SQLite Volume Engine)
# ==========================================
_MARKET_OPEN_MIN = 9 * 60 + 15
_MARKET_CLOSE_MIN = 15 * 60 + 30
_SESSION_MINUTES = _MARKET_CLOSE_MIN - _MARKET_OPEN_MIN

def _session_elapsed_fraction(now=None):
    now = now or datetime.datetime.now(IST)
    open_dt = now.replace(hour=9, minute=15, second=0, microsecond=0)
    close_dt = now.replace(hour=15, minute=30, second=0, microsecond=0)
    total = (close_dt - open_dt).total_seconds()
    elapsed = (now - open_dt).total_seconds()
    if elapsed <= 0:
        return 0.05
    if elapsed >= total:
        return 1.0
    return min(max(elapsed / total, 0.15), 1.0)


def _clamp(value, lo=0.0, hi=100.0):
    return max(lo, min(hi, float(value)))


def _scale(value, low, high):
    if high <= low:
        return 50.0
    return _clamp((float(value) - low) / (high - low) * 100.0)


def stage1_multi_bucket_prefilter(tickers, instrument_dict, quotes, top_n,
                                db_path=DEFAULT_DB_PATH):
    keys_list = [instrument_dict.get(t) for t in tickers if instrument_dict.get(t)]
    avg_vols_map = get_avg_volumes_batched(db_path, keys_list, lookback=20)

    rows = []
    no_quote = 0
    elapsed_fraction = _session_elapsed_fraction()

    for ticker in tickers:
        key = instrument_dict.get(ticker)
        quote = quotes.get(key) if key else None
        if not quote:
            no_quote += 1
            continue

        try:
            ltp = float(quote.get("last_price") or 0.0)
            ohlc = quote.get("ohlc") or {}
            
            # Guaranteed previous-day close extraction: use completed bar's close
            prev_close = float(ohlc.get("close") or 0.0)
            day_high = float(ohlc.get("high") or ltp)
            day_low = float(ohlc.get("low") or ltp)
            day_volume = float(quote.get("volume") or 0.0)
            if ltp <= 0 or prev_close <= 0:
                continue

            momentum_pct = (ltp / prev_close - 1.0) * 100.0
            range_pct = ((day_high - day_low) / prev_close) * 100.0 if prev_close else 0.0
            close_location = ((ltp - day_low) / (day_high - day_low)) if day_high > day_low else 0.5
            close_location = _clamp(close_location, 0.0, 1.0)

            avg_vol = avg_vols_map.get(key)
            if avg_vol and avg_vol > 0 and day_volume > 0:
                raw_daily_ratio = day_volume / avg_vol
                volume_pace_ratio = raw_daily_ratio / elapsed_fraction if elapsed_fraction > 0 else raw_daily_ratio
            else:
                raw_daily_ratio = None
                volume_pace_ratio = None

            rows.append({
                "ticker": ticker,
                "momentum_pct": momentum_pct,
                "range_pct": range_pct,
                "close_location": close_location,
                "day_volume": day_volume,
                "avg_vol": avg_vol,
                "raw_volume_ratio": raw_daily_ratio,
                "volume_pace_ratio": volume_pace_ratio,
                "abs_move": abs(momentum_pct),
            })
        except Exception as exc:
            LOGGER.debug("Stage1 quote parse failed for %s: %s", ticker, exc)

    if not rows:
        return [], {
            "universe_size": len(tickers),
            "quoted": 0,
            "no_quote": no_quote,
            "shortlisted": 0,
            "session_fraction": round(elapsed_fraction, 3),
            "bucket_counts": {},
        }

    d = pd.DataFrame(rows)
    d["momentum_score"] = d["momentum_pct"].apply(lambda x: _scale(x, -5.0, 5.0))
    d["range_score"] = d["range_pct"].apply(lambda x: _scale(x, 0.0, 6.0))
    d["volume_score"] = d["volume_pace_ratio"].apply(lambda x: _scale(x, 0.5, 3.5) if pd.notna(x) else 50.0)
    d["near_high_score"] = d["close_location"] * 100.0
    d["balanced_score"] = (
        d["momentum_score"] * 0.30
        + d["volume_score"] * 0.25
        + d["range_score"] * 0.15
        + d["near_high_score"] * 0.20
        + d["abs_move"].apply(lambda x: _scale(x, 0.0, 5.0)) * 0.10
    )

    d["liquidity_pct"] = d["day_volume"].rank(pct=True) * 100.0
    d["balanced_score"] += d["liquidity_pct"] * 0.05

    buckets = {
        "momentum": d.sort_values(["momentum_score", "volume_score"], ascending=False),
        "volume": d.sort_values(["volume_score", "momentum_score"], ascending=False),
        "range": d.sort_values(["range_score", "volume_score"], ascending=False),
        "breakout": d.sort_values(["near_high_score", "momentum_score"], ascending=False),
        "balanced": d.sort_values(["balanced_score"], ascending=False),
    }

    per_bucket = max(10, int(math.ceil(top_n / max(len(buckets), 1))))
    selected = []
    selected_set = set()
    bucket_counts = {}

    for name, bucket in buckets.items():
        count = 0
        for row in bucket.itertuples(index=False):
            ticker = row.ticker
            if ticker in selected_set:
                continue
            selected.append(ticker)
            selected_set.add(ticker)
            count += 1
            if count >= per_bucket or len(selected) >= top_n:
                break
        bucket_counts[name] = count
        if len(selected) >= top_n:
            break

    if len(selected) < top_n:
        for row in d.sort_values("balanced_score", ascending=False).itertuples(index=False):
            if row.ticker in selected_set:
                continue
            selected.append(row.ticker)
            selected_set.add(row.ticker)
            if len(selected) >= top_n:
                break

    stats = {
        "universe_size": len(tickers),
        "quoted": len(d),
        "no_quote": no_quote,
        "shortlisted": len(selected),
        "session_fraction": round(elapsed_fraction, 3),
        "bucket_counts": bucket_counts,
    }
    return selected, stats


def prepare_live_daily_bar(df, quote):
    try:
        if df is None or df.empty or not quote:
            return df
        out = df.copy()
        ohlc = quote.get("ohlc") or {}
        live_price = quote.get("last_price")
        if live_price is None:
            return out
        live_price = float(live_price)
        today = datetime.datetime.now(IST).date()

        if out.index[-1].date() == today:
            idx = out.index[-1]
            out.loc[idx, "Close"] = live_price
            if ohlc.get("open") is not None:
                out.loc[idx, "Open"] = float(ohlc["open"])
            if ohlc.get("high") is not None:
                out.loc[idx, "High"] = float(ohlc["high"])
            if ohlc.get("low") is not None:
                out.loc[idx, "Low"] = float(ohlc["low"])
            if quote.get("volume") is not None:
                out.loc[idx, "Volume"] = float(quote.get("volume") or 0.0)
        elif MARKET_OPEN:
            prev_close = float(out["Close"].iloc[-1])
            open_px = float(ohlc.get("open") or prev_close)
            high_px = float(ohlc.get("high") or max(open_px, live_price))
            low_px = float(ohlc.get("low") or min(open_px, live_price))
            volume = float(quote.get("volume") or 0.0)
            current_idx = pd.Timestamp(datetime.datetime.now(IST).replace(tzinfo=None))
            out.loc[current_idx, ["Open", "High", "Low", "Close", "Volume", "OI"]] = [
                open_px, high_px, low_px, live_price, volume, 0.0
            ]
            out.sort_index(inplace=True)
        return out
    except Exception as exc:
        LOGGER.debug("Could not inject live daily bar: %s", exc)
        return df


def derive_long_trade_levels(df, price, atr, horizon_days=15):
    try:
        if df.empty or price <= 0 or atr <= 0:
            return None, None, None, None

        lookback = df.tail(60)
        prior = lookback.iloc[:-1] if len(lookback) > 2 else lookback
        support20 = float(prior["Low"].tail(20).min()) if not prior.empty else float(price - atr)
        resistance20 = float(prior["High"].tail(20).max()) if not prior.empty else float(price + 2 * atr)
        resistance60 = float(prior["High"].max()) if not prior.empty else float(price + 3 * atr)

        atr_stop = price - 1.5 * atr
        structural_stop = support20 - 0.15 * atr if support20 < price else atr_stop
        stop = min(atr_stop, structural_stop)
        if stop <= 0 or stop >= price:
            stop = price - 1.5 * atr

        risk_distance = price - stop
        target_floor = price + max(2.0 * atr, risk_distance * 1.4)
        horizon_mult = 2.0 * (1.0 + horizon_days / 70.0)
        atr_target = price + horizon_mult * atr

        resistance_candidates = [
            r for r in [resistance20, resistance60]
            if r > price * 1.005
        ]
        minimum_target = price + risk_distance * 1.5
        suitable_resistance = [r for r in resistance_candidates if r >= minimum_target]
        if suitable_resistance:
            target = min(min(suitable_resistance), max(target_floor, atr_target * 0.85))
            target = min(target, min(suitable_resistance))
        else:
            target = max(target_floor, atr_target)

        if target <= price:
            return None, None, None, None

        rr = (target - price) / risk_distance if risk_distance > 0 else 0.0
        return round(float(stop), 2), round(float(target), 2), round(float(rr), 2), {
            "support20": round(support20, 2),
            "resistance20": round(resistance20, 2),
            "resistance60": round(resistance60, 2),
        }
    except Exception as exc:
        LOGGER.debug("Trade-level derivation failed: %s", exc)
        return None, None, None, None


# ==========================================
# WALK-FORWARD OOS WIN-RATE ESTIMATOR
# ==========================================
def compute_walk_forward_probability(df, horizon_days=15, train_window=250, test_window=60):
    try:
        if df.empty or len(df) < train_window + test_window + horizon_days:
            return None
        
        d = df.copy()
        d['EMA_20'] = ta.ema(d['Close'], length=20)
        d['EMA_50'] = ta.ema(d['Close'], length=50)
        adx_df = ta.adx(d['High'], d['Low'], d['Close'], length=14)
        d['ADX'] = adx_df.iloc[:, 0] if adx_df is not None and not adx_df.empty else np.nan
        d['RSI'] = ta.rsi(d['Close'], length=14)
        d['ATR'] = ta.atr(d['High'], d['Low'], d['Close'], length=14)
        d = d.dropna()
        if len(d) < train_window + test_window + horizon_days:
            return None

        oos_outcomes = []
        n = len(d)
        step = test_window
        start_idx = train_window

        while start_idx + test_window + horizon_days <= n:
            test_set = d.iloc[start_idx : start_idx + test_window]
            for i in range(len(test_set)):
                row_idx = start_idx + i
                if row_idx + horizon_days >= n:
                    break
                row = test_set.iloc[i]
                if row['Close'] > row['EMA_50'] and row['EMA_20'] >= row['EMA_50'] and row['ADX'] >= 20:
                    entry = row['Close']
                    atr = row['ATR']
                    sl = entry - 1.5 * atr
                    tgt = entry + 2.0 * atr
                    future_slice = d.iloc[row_idx + 1 : row_idx + 1 + horizon_days]
                    if future_slice.empty:
                        continue
                    hit_target = (future_slice['High'] >= tgt).any()
                    hit_stop = (future_slice['Low'] <= sl).any()
                    if hit_target and not hit_stop:
                        oos_outcomes.append(1)
                    elif hit_stop and not hit_target:
                        oos_outcomes.append(0)
                    else:
                        final_close = future_slice['Close'].iloc[-1]
                        oos_outcomes.append(1 if final_close > entry else 0)

            start_idx += step

        if not oos_outcomes or len(oos_outcomes) < 5:
            return None

        calibrated_prob = float(np.mean(oos_outcomes) * 100.0)
        samples = len(oos_outcomes)
        if samples < 30:
            tier = f"Insufficient (<30 OOS samples, n={samples})"
        elif samples < 100:
            tier = f"Weak (30–99 OOS samples, n={samples})"
        elif samples < 250:
            tier = f"Moderate (100–249 OOS samples, n={samples})"
        else:
            tier = f"Strong (250+ OOS samples, n={samples})"

        return {
            "samples": samples,
            "out_of_sample_win_prob": round(calibrated_prob, 1),
            "sample_tier": tier,
        }
    except Exception as exc:
        LOGGER.debug("Walk-forward calibration failed: %s", exc)
        return None

# ==========================================
# MCX COMMODITIES ENGINE
# ==========================================
@st.cache_data(ttl=86400)
def get_mcx_instrument_dictionary():
    try:
        url = 'https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz'
        df = pd.read_csv(url)
        mcx_df = df[(df['exchange'] == 'MCX_FO') & (df['instrument_type'].isin(['FUTCOM', 'OPTCOM']))]
        return dict(zip(mcx_df['tradingsymbol'], mcx_df['instrument_key']))
    except Exception:
        return {}

mcx_dict = get_mcx_instrument_dictionary()
all_mcx_tickers = sorted(list(mcx_dict.keys())) if mcx_dict else ["GOLD", "SILVER", "CRUDEOIL", "NATURALGAS"]

@st.cache_data(ttl=86400)
def get_mcx_futures_instruments():
    try:
        url = 'https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz'
        df = pd.read_csv(url)
        return df[(df['exchange'] == 'MCX_FO') & (df['instrument_type'] == 'FUTCOM')]
    except Exception:
        return pd.DataFrame()

# ==========================================
# WATCHLIST PERSISTENCE
# ==========================================
# ==========================================
# OPTIONS CHAIN & CONTRACT ENGINE (Upstox v2)
# ==========================================
@st.cache_data(ttl=86400)
def get_fo_stock_symbols():
    """Returns the list of NSE F&O-eligible stock (FUTSTK) underlying symbols."""
    try:
        url = 'https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz'
        df = pd.read_csv(url)
        fo_df = df[(df['exchange'] == 'NSE_FO') & (df['instrument_type'] == 'FUTSTK')]
        name_col = 'name' if 'name' in fo_df.columns else ('asset_symbol' if 'asset_symbol' in fo_df.columns else None)
        if name_col and not fo_df.empty:
            symbols = sorted(set(fo_df[name_col].dropna().astype(str).str.upper()))
        else:
            extracted = fo_df['tradingsymbol'].astype(str).str.extract(r'^([A-Za-z&\-]+)')[0]
            symbols = sorted(set(extracted.dropna().str.upper()))
        return symbols
    except Exception:
        return []


@st.cache_data(ttl=86400)
def get_futures_instruments():
    """Returns a DataFrame of all NSE stock & index futures contracts (FUTSTK + FUTIDX)."""
    try:
        url = 'https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz'
        df = pd.read_csv(url)
        fut_df = df[(df['exchange'] == 'NSE_FO') & (df['instrument_type'].isin(['FUTSTK', 'FUTIDX']))].copy()
        if 'expiry' in fut_df.columns:
            fut_df['expiry'] = pd.to_datetime(fut_df['expiry'], errors='coerce')
            fut_df = fut_df.sort_values('expiry')
        return fut_df
    except Exception:
        return pd.DataFrame()


def get_nearest_future_row(fut_df, symbol_regex):
    """Given a futures DataFrame and a tradingsymbol regex, returns the nearest-expiry matching row."""
    try:
        if fut_df is None or fut_df.empty:
            return None
        matched = fut_df[fut_df['tradingsymbol'].astype(str).str.match(symbol_regex, na=False)]
        if matched.empty:
            return None
        if 'expiry' in matched.columns:
            matched = matched.sort_values('expiry')
        return matched.iloc[0]
    except Exception:
        return None


def get_lot_size_from_row(row, default=None):
    """Extracts the lot size from an instrument row, falling back to `default`."""
    try:
        if row is None:
            return default
        for col in ['lot_size', 'lotSize', 'minimum_lot']:
            if col in row and pd.notna(row[col]):
                val = int(row[col])
                if val > 0:
                    return val
        return default
    except Exception:
        return default


@st.cache_data(ttl=300)
def fetch_option_contracts(instrument_key, token):
    """Fetches the list of option contracts (all expiries/strikes) for an underlying via Upstox v2 API."""
    if not token or not instrument_key:
        return []
    try:
        url = "https://api.upstox.com/v2/option/contract"
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        params = {"instrument_key": instrument_key}
        with get_robust_session() as session:
            res = session.get(url, headers=headers, params=params, timeout=8)
            if res.status_code == 200:
                return res.json().get("data", []) or []
    except Exception:
        pass
    return []


def get_available_expiries(contracts):
    """Extracts a sorted, de-duplicated list of expiry dates from an option-contracts list."""
    try:
        return sorted({c.get('expiry') for c in (contracts or []) if c.get('expiry')})
    except Exception:
        return []


@st.cache_data(ttl=30)
def fetch_option_chain(instrument_key, expiry, token):
    """Fetches the live option chain (strikes, greeks, market data) for a given underlying/expiry."""
    if not token or not instrument_key or not expiry:
        return []
    try:
        url = "https://api.upstox.com/v2/option/chain"
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        params = {"instrument_key": instrument_key, "expiry_date": expiry}
        with get_robust_session() as session:
            res = session.get(url, headers=headers, params=params, timeout=8)
            if res.status_code == 200:
                return res.json().get("data", []) or []
    except Exception:
        pass
    return []


def compute_pcr_and_max_pain(chain_data):
    """Computes Put-Call Ratio (by OI) and the Max Pain strike from a live option chain payload."""
    try:
        total_call_oi, total_put_oi = 0.0, 0.0
        strikes = []
        for item in (chain_data or []):
            strike = item.get('strike_price')
            call_oi = ((item.get('call_options') or {}).get('market_data') or {}).get('oi') or 0
            put_oi = ((item.get('put_options') or {}).get('market_data') or {}).get('oi') or 0
            total_call_oi += float(call_oi)
            total_put_oi += float(put_oi)
            if strike is not None:
                strikes.append((float(strike), float(call_oi), float(put_oi)))

        pcr = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else None

        max_pain_strike = None
        if strikes:
            min_pain = None
            for candidate_strike, _, _ in strikes:
                total_pain = 0.0
                for s, c_oi, p_oi in strikes:
                    if candidate_strike > s:
                        total_pain += (candidate_strike - s) * c_oi
                    elif candidate_strike < s:
                        total_pain += (s - candidate_strike) * p_oi
                if min_pain is None or total_pain < min_pain:
                    min_pain = total_pain
                    max_pain_strike = candidate_strike
        return pcr, max_pain_strike
    except Exception:
        return None, None


def current_realized_vol_pct(hist_df, window=20):
    """Annualized realized volatility (%) over the trailing `window` sessions — used as an IV proxy."""
    try:
        if hist_df is None or hist_df.empty or len(hist_df) < window + 1:
            return None
        rets = hist_df['Close'].pct_change().dropna().tail(window)
        if rets.empty:
            return None
        ann_vol = float(rets.std() * np.sqrt(252) * 100)
        return ann_vol if np.isfinite(ann_vol) else None
    except Exception:
        return None


def realized_vol_percentile(hist_df, window=20, lookback=252):
    """Percentile rank (0-100) of the current realized-vol reading vs its trailing `lookback` history."""
    try:
        if hist_df is None or hist_df.empty or len(hist_df) < window + 30:
            return None
        rets = hist_df['Close'].pct_change().dropna()
        rolling_vol = (rets.rolling(window).std() * np.sqrt(252) * 100).dropna().tail(lookback)
        if rolling_vol.empty:
            return None
        current = rolling_vol.iloc[-1]
        pct = round(100 * float((rolling_vol < current).sum()) / len(rolling_vol), 1)
        return pct
    except Exception:
        return None


# ==========================================
# TECHNICAL CLASSIFICATION HELPERS
# ==========================================
def classify_ema_trend(latest):
    """Classifies EMA(20/50/200) alignment on the latest bar into a trend label."""
    try:
        e20 = float(latest['EMA_20'])
        e50 = float(latest['EMA_50'])
        e200 = float(latest['EMA_200']) if 'EMA_200' in latest and pd.notna(latest['EMA_200']) else None
        if e200 is not None and e20 > e50 > e200:
            return "🟢 Strong Uptrend (20>50>200)"
        if e200 is not None and e20 < e50 < e200:
            return "🔴 Strong Downtrend (20<50<200)"
        if e20 > e50:
            return "🟢 Uptrend (20>50)"
        return "🔴 Downtrend (20<50)"
    except Exception:
        return "⚪ Unclear"


def classify_macd(df):
    """Classifies the most recent MACD/Signal relationship as a crossover or trend continuation."""
    try:
        if 'MACD' not in df.columns or 'MACD_signal' not in df.columns:
            return "⚪ Neutral"
        d = df.dropna(subset=['MACD', 'MACD_signal'])
        if len(d) < 2:
            return "⚪ Neutral"
        last_macd, last_sig = d['MACD'].iloc[-1], d['MACD_signal'].iloc[-1]
        prev_macd, prev_sig = d['MACD'].iloc[-2], d['MACD_signal'].iloc[-2]
        if prev_macd <= prev_sig and last_macd > last_sig:
            return "🟢 Bullish Crossover"
        if prev_macd >= prev_sig and last_macd < last_sig:
            return "🔴 Bearish Crossover"
        return "🟢 Above Signal" if last_macd > last_sig else "🔴 Below Signal"
    except Exception:
        return "⚪ Neutral"


def compute_bollinger_percent_b(latest):
    """Computes Bollinger %B for the latest bar: 0% = lower band, 100% = upper band."""
    try:
        lower, upper, close = float(latest['BB_lower']), float(latest['BB_upper']), float(latest['Close'])
        if not np.isfinite(lower) or not np.isfinite(upper) or upper == lower:
            return None
        return round((close - lower) / (upper - lower) * 100.0, 1)
    except Exception:
        return None


def get_weekly_trend(df):
    """Resamples a daily OHLC DataFrame to weekly bars and returns a multi-timeframe trend label."""
    try:
        if df is None or df.empty or len(df) < 60:
            return "Neutral (Weekly)"
        weekly_close = df['Close'].resample('W').last().dropna()
        if len(weekly_close) < 12:
            return "Neutral (Weekly)"
        ema10 = ta.ema(weekly_close, length=10)
        if ema10 is None or ema10.dropna().empty:
            return "Neutral (Weekly)"
        last_close, last_ema = weekly_close.iloc[-1], ema10.iloc[-1]
        if pd.isna(last_ema):
            return "Neutral (Weekly)"
        if last_close > last_ema:
            return "Bullish (Weekly)"
        if last_close < last_ema:
            return "Bearish (Weekly)"
        return "Neutral (Weekly)"
    except Exception:
        return "Neutral (Weekly)"


def relative_strength_vs_nifty(df, lookback=20):
    """Stock return minus NIFTY 50 return over the trailing `lookback` sessions (percentage points)."""
    try:
        if df is None or df.empty or len(df) <= lookback:
            return None
        if nifty_hist_df is None or nifty_hist_df.empty or len(nifty_hist_df) <= lookback:
            return None
        stock_ret = (float(df['Close'].iloc[-1]) / float(df['Close'].iloc[-lookback - 1]) - 1.0) * 100.0
        nifty_ret = (float(nifty_hist_df['Close'].iloc[-1]) / float(nifty_hist_df['Close'].iloc[-lookback - 1]) - 1.0) * 100.0
        return round(stock_ret - nifty_ret, 2)
    except Exception:
        return None


def compute_volume_profile(df, bins=24, value_area_pct=0.70):
    """Computes a simple Volume Profile (POC / VAH / VAL) over the trailing history using typical price."""
    try:
        if df is None or df.empty or 'Volume' not in df.columns:
            return None
        d = df.tail(120)
        typical = (d['High'] + d['Low'] + d['Close']) / 3.0
        vol = d['Volume'].fillna(0.0)
        if vol.sum() <= 0:
            return None
        lo, hi = float(d['Low'].min()), float(d['High'].max())
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            return None
        bin_edges = np.linspace(lo, hi, bins + 1)
        bin_idx = np.clip(np.digitize(typical.values, bin_edges) - 1, 0, bins - 1)
        vol_by_bin = np.zeros(bins)
        for idx, v in zip(bin_idx, vol.values):
            vol_by_bin[idx] += v

        poc_idx = int(np.argmax(vol_by_bin))
        poc_price = (bin_edges[poc_idx] + bin_edges[poc_idx + 1]) / 2.0

        total_vol = vol_by_bin.sum()
        target_vol = total_vol * value_area_pct
        acc_vol = vol_by_bin[poc_idx]
        lo_i, hi_i = poc_idx, poc_idx
        while acc_vol < target_vol and (lo_i > 0 or hi_i < bins - 1):
            up_vol = vol_by_bin[hi_i + 1] if hi_i < bins - 1 else -1
            down_vol = vol_by_bin[lo_i - 1] if lo_i > 0 else -1
            if up_vol >= down_vol and hi_i < bins - 1:
                hi_i += 1
                acc_vol += vol_by_bin[hi_i]
            elif lo_i > 0:
                lo_i -= 1
                acc_vol += vol_by_bin[lo_i]
            else:
                break

        return {
            "poc": round(float(poc_price), 2),
            "vah": round(float(bin_edges[hi_i + 1]), 2),
            "val": round(float(bin_edges[lo_i]), 2),
        }
    except Exception:
        return None


# ==========================================
# MUTUAL FUND ENGINE (via mfapi.in / AMFI)
# ==========================================
MF_CATEGORY_KEYWORDS = {
    "Large Cap": ["large cap", "bluechip"],
    "Mid Cap": ["mid cap", "midcap"],
    "Small Cap": ["small cap", "smallcap"],
    "Flexi Cap": ["flexi cap", "flexicap"],
    "Multi Cap": ["multi cap", "multicap"],
    "ELSS (Tax Saver)": ["elss", "tax saver", "tax plan"],
    "Index Fund": ["index fund", "nifty 50 index", "sensex index"],
    "Debt / Liquid": ["liquid fund", "debt fund", "banking and psu", "corporate bond", "money market"],
    "Hybrid / Balanced": ["hybrid", "balanced advantage", "balanced fund"],
}


def is_direct_growth_plan(scheme_name):
    """True if a scheme name represents a Direct-Growth plan (excludes IDCW/Dividend/Regular)."""
    n = str(scheme_name or "").lower()
    return "direct" in n and "growth" in n and "idcw" not in n and "dividend" not in n


@st.cache_data(ttl=86400)
def fetch_mf_scheme_list():
    """Fetches the full AMFI mutual-fund scheme master list via the free mfapi.in service."""
    try:
        with get_robust_session() as session:
            res = session.get("https://api.mfapi.in/mf", timeout=15)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list):
                    return data
    except Exception:
        pass
    return []


def shortlist_mf_schemes(all_schemes, keywords):
    """Filters the scheme master list down to Direct-Growth schemes matching any of `keywords`."""
    try:
        out = []
        for s in (all_schemes or []):
            name = str(s.get("schemeName", ""))
            name_l = name.lower()
            if any(kw.lower() in name_l for kw in keywords) and is_direct_growth_plan(name):
                out.append(s)
        return out
    except Exception:
        return []


def search_mf_schemes(query):
    """Free-text search over the AMFI scheme master list by scheme name."""
    try:
        all_schemes = fetch_mf_scheme_list()
        q = str(query or "").lower()
        return [s for s in all_schemes if q in str(s.get("schemeName", "")).lower()]
    except Exception:
        return []


@st.cache_data(ttl=3600)
def fetch_mf_nav_history(scheme_code):
    """Fetches full NAV history + metadata for a scheme code via mfapi.in."""
    try:
        with get_robust_session() as session:
            res = session.get(f"https://api.mfapi.in/mf/{scheme_code}", timeout=10)
            if res.status_code == 200:
                return res.json()
    except Exception:
        pass
    return None


def compute_mf_returns(nav_json):
    """Derives latest NAV, 1Y return, 3Y CAGR, annualized volatility and a quality score from NAV history."""
    try:
        if not nav_json or not nav_json.get("data"):
            return None
        meta = nav_json.get("meta", {})
        df = pd.DataFrame(nav_json["data"])
        df['date'] = pd.to_datetime(df['date'], format="%d-%m-%Y", errors='coerce')
        df['nav'] = pd.to_numeric(df['nav'], errors='coerce')
        df = df.dropna(subset=['date', 'nav']).sort_values('date').reset_index(drop=True)
        if df.empty:
            return None

        latest_nav = float(df['nav'].iloc[-1])
        latest_date = df['date'].iloc[-1]

        def _nav_on_or_before(target_date):
            sub = df[df['date'] <= target_date]
            return float(sub['nav'].iloc[-1]) if not sub.empty else None

        ret_1y = None
        nav_1y_ago = _nav_on_or_before(latest_date - pd.DateOffset(years=1))
        if nav_1y_ago:
            ret_1y = ((latest_nav / nav_1y_ago) - 1.0) * 100.0

        cagr_3y = None
        nav_3y_ago = _nav_on_or_before(latest_date - pd.DateOffset(years=3))
        if nav_3y_ago and nav_3y_ago > 0:
            cagr_3y = (((latest_nav / nav_3y_ago) ** (1.0 / 3.0)) - 1.0) * 100.0

        daily_rets = df['nav'].pct_change().dropna().tail(252)
        volatility = float(daily_rets.std() * np.sqrt(252) * 100.0) if not daily_rets.empty else None

        quality = None
        if cagr_3y is not None and volatility:
            quality = round(cagr_3y / volatility, 2)
        elif cagr_3y is not None:
            quality = round(cagr_3y, 2)

        return {
            "scheme_name": meta.get("scheme_name", "N/A"),
            "fund_house": meta.get("fund_house", "N/A"),
            "latest_nav": latest_nav,
            "ret_1y": ret_1y,
            "cagr_3y": cagr_3y,
            "volatility": volatility,
            "quality": quality,
            "nav_df": df[['date', 'nav']],
        }
    except Exception:
        return None


WATCHLIST_FILE = "watchlist.json"

def load_watchlist():
    try:
        if os.path.exists(WATCHLIST_FILE):
            with open(WATCHLIST_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except Exception:
        pass
    return []

def save_watchlist(tickers):
    try:
        with open(WATCHLIST_FILE, "w") as f:
            json.dump(tickers, f)
    except Exception:
        pass

if "watchlist" not in st.session_state:
    st.session_state.watchlist = load_watchlist()

st.sidebar.markdown("---")
st.sidebar.header("⭐ Watchlist")
wl_options = ["-- Select --"] + [t for t in all_nse_tickers if t not in st.session_state.watchlist]
wl_add = st.sidebar.selectbox("Add ticker", wl_options, key="wl_add_select")
if st.sidebar.button("➕ Add to Watchlist", key="wl_add_btn", use_container_width=True) and wl_add != "-- Select --":
    st.session_state.watchlist.append(wl_add)
    save_watchlist(st.session_state.watchlist)
    st.rerun()

if st.session_state.watchlist:
    wl_remove = st.sidebar.selectbox("Remove ticker", ["-- Select --"] + st.session_state.watchlist, key="wl_remove_select")
    if st.sidebar.button("➖ Remove from Watchlist", key="wl_remove_btn", use_container_width=True) and wl_remove != "-- Select --":
        st.session_state.watchlist.remove(wl_remove)
        save_watchlist(st.session_state.watchlist)
        st.rerun()

    wl_keys = [instrument_dict.get(t) for t in st.session_state.watchlist if instrument_dict.get(t)]
    wl_quotes = get_live_market_quotes(wl_keys, access_token) if wl_keys else {}
    for t in st.session_state.watchlist:
        k = instrument_dict.get(t)
        if k and wl_quotes and k in wl_quotes:
            q = wl_quotes[k]
            ltp = q.get('last_price', 0.0)
            prev = q.get('ohlc', {}).get('close', 0.0)
            chg = ((ltp - prev) / prev * 100) if prev else 0.0
            icon = "🟢" if chg >= 0 else "🔴"
            st.sidebar.markdown(f"{icon} **{t}**: ₹{ltp:,.2f} ({chg:+.2f}%)")
        else:
            st.sidebar.markdown(f"⚪ **{t}**: no live quote")
else:
    st.sidebar.caption("No tickers in watchlist yet.")

# --- TICKER TAPE ---
with st.sidebar.expander("Customize Header Tickers"):
    available_indices = ["NIFTY 50", "SENSEX", "India VIX", "BANKNIFTY", "FINNIFTY", "NIFTY IT"]
    selected_indices = st.multiselect("Select Tickers to Display", options=available_indices, default=["NIFTY 50", "SENSEX", "BANKNIFTY"], key="sb_tickers")

HAS_FRAGMENT = hasattr(st, "fragment")

def _render_ticker_tape():
    if not selected_indices:
        return
    cols = st.columns(len(selected_indices))
    index_keys = {"NIFTY 50": "NSE_INDEX|Nifty 50", "SENSEX": "BSE_INDEX|SENSEX", "India VIX": "NSE_INDEX|India VIX", "BANKNIFTY": "NSE_INDEX|Nifty Bank", "FINNIFTY": "NSE_INDEX|Nifty Fin Service", "NIFTY IT": "NSE_INDEX|Nifty IT"}
    active_keys = [index_keys[idx] for idx in selected_indices if idx in index_keys]
    live_quotes = get_live_market_quotes(active_keys, access_token)

    for i, idx_name in enumerate(selected_indices):
        with cols[i]:
            key = index_keys.get(idx_name)
            if key and live_quotes and key in live_quotes:
                quote = live_quotes[key]
                ltp = quote.get('last_price', 0.0)
                yest_close = quote.get('ohlc', {}).get('close', 0.0)
                if yest_close > 0:
                    change = ltp - yest_close
                    pct_change = (change / yest_close) * 100
                    icon = "🟢" if change >= 0 else "🔴"
                    sign = "+" if change >= 0 else ""
                    st.markdown(f"{icon} **{idx_name}** `{ltp:,.2f}` `{sign}{change:,.2f} ({sign}{pct_change:.2f}%)`")
                else:
                    st.markdown(f"⚪ **{idx_name}** `{ltp:,.2f}`")
            elif key:
                idx_df = fetch_upstox_history(key, access_token, days=5)
                if not idx_df.empty and len(idx_df) >= 2:
                    today_close = idx_df.iloc[-1]['Close']
                    yest_close = idx_df.iloc[-2]['Close']
                    change = today_close - yest_close
                    pct_change = (change / yest_close) * 100
                    icon = "🟢" if change >= 0 else "🔴"
                    sign = "+" if change >= 0 else ""
                    st.markdown(f"{icon} **{idx_name}** `{today_close:,.2f} (History Close)` `{sign}{change:,.2f} ({sign}{pct_change:.2f}%)`")

if HAS_FRAGMENT:
    # Refreshes just this ticker strip every 5s WITHOUT rerunning the whole app
    # (no full-page reload, no lost scroll position, no re-fetch of option chains/screener state).
    # This is what actually makes the header feel "live" like a brokerage app; a full
    # st.rerun() every 15s is comparatively heavy and disruptive, which is why the old
    # implementation felt like it only updated on unrelated interactions (e.g. switching tabs).
    st.fragment(run_every=5)(_render_ticker_tape)()
else:
    st.caption("Tip: upgrade Streamlit (`pip install -U streamlit`) to enable 5-second live ticker refresh via st.fragment.")
    _render_ticker_tape()

# --- MARKET HOURS BANNER ---
if not MARKET_OPEN:
    st.info("🌙 **Market Closed / Holiday** — showing last available data. Exchange status verified via live Upstox status API.")

st.markdown("<hr style='border: 1px solid #1f1f1f; margin: 0px 0px 15px 0px;'>", unsafe_allow_html=True)

# ==========================================
# MARKET-WIDE VOLATILITY REGIME (India VIX) + NIFTY BENCHMARK
# ==========================================
_VIX_KEY = "NSE_INDEX|India VIX"
_vix_quotes = get_live_market_quotes([_VIX_KEY], access_token) if access_token else None
vix_value = _vix_quotes.get(_VIX_KEY, {}).get('last_price') if _vix_quotes else None
if not vix_value or vix_value <= 0:
    _vix_hist = fetch_upstox_history(_VIX_KEY, access_token, days=5)
    vix_value = float(_vix_hist.iloc[-1]['Close']) if not _vix_hist.empty else 15.0

if vix_value >= 20:
    volatility_regime = "High Volatility"
elif vix_value <= 12:
    volatility_regime = "Low Volatility"
else:
    volatility_regime = "Normal Volatility"

nifty_hist_df = fetch_upstox_history("NSE_INDEX|Nifty 50", access_token, days=400)

# ==========================================
# RISK & CAPITAL SETTINGS (Synced with Funds API)
# ==========================================
st.sidebar.markdown("---")
st.sidebar.header("Risk & Capital Settings")

live_broker_funds = fetch_upstox_funds_and_margin(access_token) if access_token else None
default_capital = live_broker_funds if live_broker_funds is not None and live_broker_funds > 0 else 500000.0

investment_capital = st.sidebar.number_input(
    "Investment Capital (₹)", min_value=0.0, value=default_capital, step=10000.0,
    key="sb_investment_capital", help="Total capital used to size every trade recommendation in this app."
)
if live_broker_funds is not None:
    st.sidebar.caption(f"💼 Synced from Upstox Funds API: ₹{live_broker_funds:,.2f}")

max_risk_pct = st.sidebar.slider(
    "Max Risk per Trade (%)", min_value=0.0, max_value=10.0, value=1.0, step=0.25,
    key="sb_max_risk_pct", help="% of capital you're willing to lose on a single trade if the stop is hit."
)
max_position_pct = st.sidebar.slider(
    "Max Position Size (% of Capital)", min_value=1.0, max_value=100.0, value=20.0, step=1.0,
    key="sb_max_position_pct", help="Caps capital deployed into a single position, independent of the risk-based quantity."
)
max_portfolio_heat_pct = st.sidebar.slider(
    "Max Portfolio Heat (%)", min_value=1.0, max_value=20.0, value=5.0, step=0.5,
    key="sb_max_portfolio_heat_pct", help="Caps total capital-at-risk across all selected screener picks combined."
)

risk_engine = RiskEngine(
    investment_capital=investment_capital,
    max_risk_pct=max_risk_pct,
    max_position_pct=max_position_pct,
)

# ==========================================
# STATE-MANAGED NAVIGATION
# ==========================================
nav_options = [
    "Options & Derivatives Chain", 
    "Futures & Derivatives", 
    "Equities Screener & Risk", 
    "Commodities (MCX)", 
    "Mutual Funds", 
    "SMC & Technical Analysis", 
    "AI Copilot"
]
selected_tab = st.radio("Navigation", nav_options, horizontal=True, label_visibility="collapsed", key="main_nav_radio")

st.markdown("<hr style='border: 1px solid #1f1f1f; margin: 5px 0px 15px 0px;'>", unsafe_allow_html=True)

# ==========================================
# TAB 1: OPTIONS & DERIVATIVES CHAIN
# ==========================================
if selected_tab == "Options & Derivatives Chain":
    st.subheader("Options Chain Analytics")

    if "iv_history" not in st.session_state:
        st.session_state.iv_history = load_iv_history_disk()

    instrument_mode = st.radio(
        "Instrument Type", ["Index", "Stock (F&O)"], horizontal=True, key="opt_instrument_mode",
        help="Index options (NIFTY/BANKNIFTY/FINNIFTY/SENSEX) or individual F&O stock options (e.g. SBIN)."
    )

    is_stock_mode = instrument_mode == "Stock (F&O)"

    if not is_stock_mode:
        selected_opt_asset = st.selectbox("Select Derivative Index:", ["NIFTY 50", "BANKNIFTY", "FINNIFTY", "SENSEX"], key="opt_asset_select")
        opt_mapping = {"NIFTY 50": ("NSE_INDEX|Nifty 50", 65), "BANKNIFTY": ("NSE_INDEX|Nifty Bank", 30), "FINNIFTY": ("NSE_INDEX|Nifty Fin Service", 60), "SENSEX": ("BSE_INDEX|SENSEX", 20)}
        live_key, lot_size = opt_mapping.get(selected_opt_asset, ("NSE_INDEX|Nifty 50", 65))
    else:
        fo_symbols = get_fo_stock_symbols()
        liquid_fo = [t for t in LIQUID_CORE_TICKERS if t in fo_symbols]
        stock_options_list = liquid_fo + [t for t in fo_symbols if t not in liquid_fo]
        if not stock_options_list:
            st.warning("Couldn't load the F&O stock list right now. Try again in a moment, or use Index options above.")
            st.stop()

        # --- Auto-scan: rank the liquid F&O universe by live momentum instead of
        # forcing a manual pick. Cheap quote-only pass (no option chain fetch per stock),
        # refreshed at most every 30s so it doesn't hammer the API on every rerun.
        auto_scan_on = st.checkbox(
            "🔍 Auto-scan F&O universe for top movers (recommended)", value=True, key="opt_stock_auto_scan",
            help="Ranks all liquid F&O stocks by live momentum and pre-selects the strongest setup below, "
                 "instead of you having to pick a stock manually one at a time."
        )

        top_movers = []
        if auto_scan_on:
            @st.cache_data(ttl=30, show_spinner=False)
            def _scan_fo_momentum(tickers_tuple, token):
                tickers = list(tickers_tuple)
                keys = {t: instrument_dict.get(t) for t in tickers if instrument_dict.get(t)}
                quotes = get_live_scan_market_data(list(keys.values()), token)
                rows = []
                for ticker, key in keys.items():
                    q = quotes.get(key)
                    if not q:
                        continue
                    try:
                        ltp = float(q.get("last_price") or 0.0)
                        ohlc = q.get("ohlc") or {}
                        prev_close = float(ohlc.get("close") or 0.0)
                        day_high = float(ohlc.get("high") or ltp)
                        day_low = float(ohlc.get("low") or ltp)
                        if ltp <= 0 or prev_close <= 0:
                            continue
                        momentum_pct = (ltp / prev_close - 1.0) * 100.0
                        range_pct = ((day_high - day_low) / prev_close) * 100.0 if prev_close else 0.0
                        rows.append({"ticker": ticker, "ltp": ltp, "momentum_pct": momentum_pct, "range_pct": range_pct})
                    except Exception:
                        continue
                rows.sort(key=lambda r: abs(r["momentum_pct"]), reverse=True)
                return rows

            scan_universe = tuple(liquid_fo) if liquid_fo else tuple(stock_options_list[:100])
            with st.spinner("Scanning F&O universe for live momentum..."):
                try:
                    top_movers = _scan_fo_momentum(scan_universe, access_token)
                except Exception as exc:
                    LOGGER.warning("F&O auto-scan failed: %s", exc)
                    top_movers = []

        if top_movers:
            movers_df = pd.DataFrame(top_movers[:10])[["ticker", "ltp", "momentum_pct", "range_pct"]]
            movers_df["Suggested Side"] = movers_df["momentum_pct"].apply(
                lambda x: "CE (Bullish)" if x >= 0.5 else ("PE (Bearish)" if x <= -0.5 else "Neutral")
            )
            movers_df = movers_df.rename(columns={
                "ticker": "Symbol", "ltp": "LTP", "momentum_pct": "Move %", "range_pct": "Day Range %"
            })
            st.markdown("#### Top F&O Movers (auto-ranked, live)")
            st.dataframe(
                movers_df.style.format({"LTP": "₹{:.2f}", "Move %": "{:.2f}", "Day Range %": "{:.2f}"}),
                use_container_width=True, hide_index=True
            )
            default_pick = top_movers[0]["ticker"]
            default_idx = stock_options_list.index(default_pick) if default_pick in stock_options_list else 0
        else:
            if auto_scan_on:
                st.caption("Auto-scan returned no ranked candidates yet (market closed or quotes still warming up) — pick a stock manually below.")
            default_idx = 0

        selected_opt_asset = st.selectbox(
            "Select F&O Stock:" if not top_movers else "F&O Stock (auto-selected top mover, override anytime):",
            stock_options_list, index=default_idx, key="opt_stock_select"
        )

        equity_key = instrument_dict.get(selected_opt_asset)
        if not equity_key:
            st.warning(f"Couldn't resolve an instrument key for {selected_opt_asset}. Try Force Reconnect & Clear Cache.")
            st.stop()
        live_key = equity_key

        stock_fut_df = get_futures_instruments()
        escaped_sym = re.escape(selected_opt_asset.replace("&", "").replace("-", ""))
        matched_fut_row = get_nearest_future_row(stock_fut_df, rf'^{escaped_sym}\d')
        lot_size = get_lot_size_from_row(matched_fut_row, None)
        if not lot_size or lot_size <= 0:
            lot_size = 1

    live_quotes = get_live_market_quotes([live_key], access_token)
    underlying_ltp = live_quotes.get(live_key, {}).get('last_price', 0.0) if live_quotes else 0.0
    if underlying_ltp <= 0:
        hist_df = fetch_upstox_history(live_key, access_token, days=5)
        underlying_ltp = float(hist_df.iloc[-1]['Close']) if not hist_df.empty else 24500.0

    if underlying_ltp > 20000:
        step = 100
    elif underlying_ltp > 2000:
        step = 50
    elif underlying_ltp > 500:
        step = 10
    elif underlying_ltp > 100:
        step = 5
    else:
        step = 1
    atm_strike = round(underlying_ltp / step) * step

    live_chain_data = []
    selected_expiry = None
    if access_token:
        contracts = fetch_option_contracts(live_key, access_token)
        expiries = get_available_expiries(contracts)
        if expiries:
            selected_expiry = st.selectbox("Expiry", expiries, key="opt_expiry_select")
            live_chain_data = fetch_option_chain(live_key, selected_expiry, access_token)
            try:
                contract_for_expiry = next((c for c in contracts if c.get('expiry') == selected_expiry), None)
                live_lot_size = None
                if contract_for_expiry:
                    for candidate_field in ['lot_size', 'lotSize', 'minimum_lot']:
                        if contract_for_expiry.get(candidate_field):
                            live_lot_size = int(contract_for_expiry[candidate_field])
                            break
                if live_lot_size and live_lot_size > 0:
                    lot_size = live_lot_size
            except Exception:
                pass

    pcr_val, max_pain_strike = (None, None)
    using_live_chain = False
    if live_chain_data:
        pcr_val, max_pain_strike = compute_pcr_and_max_pain(live_chain_data)
        using_live_chain = pcr_val is not None

    hist_for_iv = fetch_upstox_history(live_key, access_token, days=400)
    iv_percentile_proxy = realized_vol_percentile(hist_for_iv)

    if is_stock_mode:
        iv_seed_pct = current_realized_vol_pct(hist_for_iv) or vix_value
    else:
        iv_seed_pct = vix_value

    atm_iv_live = None
    session_iv_percentile = None
    if using_live_chain:
        try:
            chain_spot = live_chain_data[0].get('underlying_spot_price') if live_chain_data else None
            atm_reference_price = chain_spot if chain_spot else underlying_ltp
            atm_item = min(live_chain_data, key=lambda x: abs(x.get('strike_price', 0) - atm_reference_price))
            atm_iv_live = ((atm_item.get('call_options') or {}).get('option_greeks') or {}).get('iv')
        except Exception:
            atm_iv_live = None
        if atm_iv_live is not None:
            hist_list = st.session_state.iv_history.setdefault(selected_opt_asset, [])
            today_str = datetime.datetime.now(IST).strftime("%Y-%m-%d")
            if not hist_list or hist_list[-1].get("date") != today_str:
                hist_list.append({"date": today_str, "iv": atm_iv_live})
            else:
                hist_list[-1]["iv"] = atm_iv_live
            hist_list = hist_list[-252:]
            st.session_state.iv_history[selected_opt_asset] = hist_list
            save_iv_history_disk(st.session_state.iv_history)
            if len(hist_list) >= 10:
                ivs = [h["iv"] for h in hist_list]
                session_iv_percentile = round(100 * (sum(1 for v in ivs if v < atm_iv_live) / len(ivs)), 1)

    if not using_live_chain:
        pcr_val = None
        max_pain_strike = None

    RISK_FREE_RATE = 0.06
    chain_rows = []

    if using_live_chain:
        try:
            sorted_chain = sorted(live_chain_data, key=lambda x: x.get('strike_price', 0))
            atm_idx = min(range(len(sorted_chain)), key=lambda i: abs(sorted_chain[i].get('strike_price', 0) - atm_reference_price))
            lo, hi = max(0, atm_idx - 5), min(len(sorted_chain), atm_idx + 6)
            for item in sorted_chain[lo:hi]:
                strike = item.get('strike_price', 0)
                call = item.get('call_options') or {}
                put = item.get('put_options') or {}
                c_md, p_md = call.get('market_data') or {}, put.get('market_data') or {}
                c_g, p_g = call.get('option_greeks') or {}, put.get('option_greeks') or {}
                is_atm = strike == sorted_chain[atm_idx].get('strike_price')
                chain_rows.append({
                    "Strike": f"🎯 {strike}" if is_atm else str(strike),
                    "Call Delta": c_g.get('delta', 'N/A'),
                    "Call Gamma": c_g.get('gamma', 'N/A'),
                    "Call Theta": c_g.get('theta', 'N/A'),
                    "Call Vega": c_g.get('vega', 'N/A'),
                    "Call Rho": c_g.get('rho', 'N/A'),
                    "Call OI": c_md.get('oi', 'N/A'),
                    "Call LTP": f"₹{c_md.get('ltp', 0):,.2f}" if c_md.get('ltp') is not None else "N/A",
                    "Put LTP": f"₹{p_md.get('ltp', 0):,.2f}" if p_md.get('ltp') is not None else "N/A",
                    "Put OI": p_md.get('oi', 'N/A'),
                    "Put Delta": p_g.get('delta', 'N/A'),
                    "Put Theta": p_g.get('theta', 'N/A'),
                    "Put Vega": p_g.get('vega', 'N/A'),
                    "Put Rho": p_g.get('rho', 'N/A'),
                    "_call_bid": c_md.get('bid_price'), "_call_ask": c_md.get('ask_price'),
                    "_call_bid_qty": c_md.get('bid_qty'), "_call_ask_qty": c_md.get('ask_qty'),
                    "_call_volume": c_md.get('volume'),
                    "_put_bid": p_md.get('bid_price'), "_put_ask": p_md.get('ask_price'),
                    "_put_bid_qty": p_md.get('bid_qty'), "_put_ask_qty": p_md.get('ask_qty'),
                    "_put_volume": p_md.get('volume'),
                })
        except Exception:
            using_live_chain = False

    if selected_expiry:
        try:
            expiry_dt = pd.to_datetime(selected_expiry).date()
            dte = max((expiry_dt - datetime.datetime.now(IST).date()).days, 0)
        except Exception:
            dte = 7
    else:
        dte = 7
    t_val_shared = max(dte / 365.0, 1 / 365.0)
    DIVIDEND_YIELD_Q = 0.0

    if not using_live_chain or not chain_rows:
        chain_rows = []
        for i in range(-5, 6):
            strike = atm_strike + (i * step)
            call_iv = iv_seed_pct / 100.0
            t_val = t_val_shared
            q = DIVIDEND_YIELD_Q
            d1 = (np.log(underlying_ltp / strike) + (RISK_FREE_RATE - q + 0.5 * call_iv ** 2) * t_val) / (call_iv * np.sqrt(t_val))
            d2 = d1 - call_iv * np.sqrt(t_val)
            div_discount = np.exp(-q * t_val)

            c_delta = round(float(div_discount * si.norm.cdf(d1)), 2)
            p_delta = round(c_delta - div_discount, 2)
            gamma = round(float(div_discount * si.norm.pdf(d1) / (underlying_ltp * call_iv * np.sqrt(t_val))), 4)

            discount_factor = np.exp(-RISK_FREE_RATE * t_val)
            common_term = -(underlying_ltp * div_discount * call_iv * si.norm.pdf(d1)) / (2 * np.sqrt(t_val))
            call_theta = round(float((common_term - RISK_FREE_RATE * strike * discount_factor * si.norm.cdf(d2)
                                       + q * underlying_ltp * div_discount * si.norm.cdf(d1)) / 365.0), 2)
            put_theta = round(float((common_term + RISK_FREE_RATE * strike * discount_factor * si.norm.cdf(-d2)
                                      - q * underlying_ltp * div_discount * si.norm.cdf(-d1)) / 365.0), 2)

            vega = round(float(underlying_ltp * div_discount * si.norm.pdf(d1) * np.sqrt(t_val) / 100.0), 2)
            call_rho = round(float(strike * t_val * discount_factor * si.norm.cdf(d2) / 100.0), 4)
            put_rho = round(float(-strike * t_val * discount_factor * si.norm.cdf(-d2) / 100.0), 4)

            c_price = max(0.05, round(underlying_ltp * div_discount * si.norm.cdf(d1) - strike * discount_factor * si.norm.cdf(d2), 2))
            p_price = max(0.05, round(strike * discount_factor * si.norm.cdf(-d2) - underlying_ltp * div_discount * si.norm.cdf(-d1), 2))

            chain_rows.append({
                "Strike": f"🎯 {strike}" if i == 0 else str(strike),
                "Call Delta": c_delta, "Call Gamma": gamma, "Call Theta": call_theta,
                "Call Vega": vega, "Call Rho": call_rho,
                "Call LTP": f"₹{c_price}", "Put LTP": f"₹{p_price}",
                "Put Delta": p_delta, "Put Theta": put_theta, "Put Vega": vega, "Put Rho": put_rho,
            })

    def determine_market_bias():
        try:
            idx_hist_short = fetch_upstox_history(live_key, access_token, days=60)
            if idx_hist_short.empty or len(idx_hist_short) < 20:
                return "Neutral"
            ema20_series = ta.ema(idx_hist_short['Close'], length=20).dropna()
            if ema20_series.empty:
                return "Neutral"
            ema20_last = ema20_series.iloc[-1]
            price_above, price_below = underlying_ltp > ema20_last, underlying_ltp < ema20_last

            rsi_last = None
            try:
                rsi_series = ta.rsi(idx_hist_short['Close'], length=14).dropna()
                if not rsi_series.empty:
                    rsi_last = float(rsi_series.iloc[-1])
            except Exception:
                rsi_last = None
            rsi_bullish = rsi_last is not None and rsi_last >= 55
            rsi_bearish = rsi_last is not None and rsi_last <= 45

            macd_hist_last = None
            try:
                macd_df = ta.macd(idx_hist_short['Close'], fast=12, slow=26, signal=9).dropna()
                if not macd_df.empty:
                    hist_col = [c for c in macd_df.columns if c.startswith("MACDh_")]
                    if hist_col:
                        macd_hist_last = float(macd_df[hist_col[0]].iloc[-1])
            except Exception:
                macd_hist_last = None
            macd_bullish = macd_hist_last is not None and macd_hist_last > 0
            macd_bearish = macd_hist_last is not None and macd_hist_last < 0

            volume_confirmed = False
            try:
                if 'Volume' in idx_hist_short.columns and len(idx_hist_short) >= 20:
                    vol_avg20 = idx_hist_short['Volume'].rolling(20).mean().iloc[-1]
                    vol_last = idx_hist_short['Volume'].iloc[-1]
                    if MARKET_OPEN:
                        now_ist = datetime.datetime.now(IST)
                        session_start = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
                        session_end = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
                        elapsed_frac = min(max((now_ist - session_start).total_seconds() / (session_end - session_start).total_seconds(), 0.05), 1.0)
                    else:
                        elapsed_frac = 1.0
                    expected_vol_so_far = (vol_avg20 or 0) * elapsed_frac
                    volume_confirmed = bool(expected_vol_so_far and vol_last >= expected_vol_so_far)
            except Exception:
                volume_confirmed = False

            pcr_bullish = pcr_val is not None and pcr_val >= 1.05
            pcr_bearish = pcr_val is not None and pcr_val <= 0.85
            if price_above and pcr_bullish and rsi_bullish and macd_bullish and volume_confirmed:
                return "Bullish"
            if price_below and pcr_bearish and rsi_bearish and macd_bearish and volume_confirmed:
                return "Bearish"
            if price_above:
                return "Mildly Bullish"
            if price_below:
                return "Mildly Bearish"
            return "Neutral"
        except Exception:
            return "Neutral"

    market_bias = determine_market_bias()

    def build_option_recommendation(bias, best_row=None, strike_offset_steps=0):
        try:
            if bias in ("Bullish", "Mildly Bullish"):
                side, side_key = "CE", "Call LTP"
            elif bias in ("Bearish", "Mildly Bearish"):
                side, side_key = "PE", "Put LTP"
            else:
                return None

            if best_row is None:
                # Default behaviour preserved: pick strike closest to spot (ATM),
                # optionally shifted N strike-steps out-of-the-money in the direction of the bias.
                direction = 1 if side == "CE" else -1
                target_strike = atm_strike + (direction * strike_offset_steps * step)
                best_row, best_diff = None, None
                for row in chain_rows:
                    strike_str = str(row["Strike"]).replace("🎯 ", "").strip()
                    try:
                        strike_val = float(strike_str)
                    except ValueError:
                        continue
                    diff = abs(strike_val - target_strike)
                    if best_diff is None or diff < best_diff:
                        best_diff, best_row = diff, row
            if not best_row:
                return None

            premium_str = best_row.get(side_key, "N/A")
            if premium_str == "N/A":
                return None
            ltp_premium = float(str(premium_str).replace("₹", "").replace(",", ""))
            if ltp_premium <= 0:
                return None

            bid_key, ask_key = ("_call_bid", "_call_ask") if side == "CE" else ("_put_bid", "_put_ask")
            bid_qty_key, ask_qty_key = ("_call_bid_qty", "_call_ask_qty") if side == "CE" else ("_put_bid_qty", "_put_ask_qty")
            vol_key = "_call_volume" if side == "CE" else "_put_volume"
            bid_px, ask_px = best_row.get(bid_key), best_row.get(ask_key)

            spread_pct = None
            if bid_px and ask_px and bid_px > 0 and ask_px > 0:
                mid = (bid_px + ask_px) / 2.0
                spread_pct = round(((ask_px - bid_px) / mid) * 100, 2) if mid else None
                MAX_ALLOWED_SPREAD_PCT = 8.0
                if spread_pct is not None and spread_pct > MAX_ALLOWED_SPREAD_PCT:
                    return None
                premium = float(ask_px)
            else:
                premium = ltp_premium

            actual_strike = float(str(best_row["Strike"]).replace("🎯 ", "").strip())

            if not lot_size or lot_size <= 0:
                return None

            iv_pctl = session_iv_percentile if session_iv_percentile is not None else iv_percentile_proxy
            if iv_pctl is not None:
                if iv_pctl >= 70:
                    target_mult, stop_mult = 1.6, 0.60
                elif iv_pctl <= 30:
                    target_mult, stop_mult = 1.25, 0.80
                else:
                    target_mult, stop_mult = 1.4, 0.70
            else:
                target_mult, stop_mult = 1.4, 0.70

            target_premium = round(premium * target_mult, 2)
            stop_premium = round(premium * stop_mult, 2)

            ESTIMATED_ROUND_TRIP_COST_PCT = 0.7
            cost_buffer_per_unit = premium * (ESTIMATED_ROUND_TRIP_COST_PCT / 100.0)
            risk_per_unit = risk_engine.calculate_risk_per_unit(premium, stop_premium, cost_buffer_per_unit)
            if risk_per_unit <= 0:
                return None

            sizing = risk_engine.calculate_position_size(
                risk_per_unit=risk_per_unit, price_per_unit=premium, unit_multiplier=lot_size
            )
            lots = sizing.qty
            required_capital = risk_engine.calculate_capital_required(premium, lots, lot_size)
            is_valid, _ = risk_engine.validate_trade(lots, required_capital)
            if not is_valid:
                return None

            risk_per_lot = risk_per_unit * lot_size
            estimated_costs_per_lot = cost_buffer_per_unit * lot_size

            reward_risk = round((target_mult - 1.0) / max(1.0 - stop_mult, 0.01), 2)

            return {
                "side": side, "strike": actual_strike, "premium": premium, "lots": lots,
                "lot_size": lot_size, "target_premium": target_premium,
                "stop_premium": stop_premium, "bias": bias,
                "risk_per_lot": round(risk_per_lot, 2),
                "total_risk": round(risk_per_lot * lots, 2),
                "required_capital": round(required_capital, 2),
                "target_pct": round((target_mult - 1.0) * 100, 0),
                "stop_pct": round((1.0 - stop_mult) * 100, 0),
                "spread_pct": spread_pct,
                "bid": bid_px, "ask": ask_px,
                "bid_qty": best_row.get(bid_qty_key), "ask_qty": best_row.get(ask_qty_key),
                "volume": best_row.get(vol_key),
                "estimated_costs_per_lot": round(estimated_costs_per_lot, 2),
                "strike_offset_steps": strike_offset_steps,
                "reward_risk": reward_risk,
            }
        except Exception:
            return None

    def generate_ranked_recommendations(bias, max_ideas=3):
        """Scan ATM + nearby OTM strikes on the biased side and rank multiple
        tradeable ideas by reward:risk instead of only ever returning the single ATM strike."""
        ideas, seen_strikes = [], set()
        for offset in range(0, 4):  # ATM, 1-OTM, 2-OTM, 3-OTM
            candidate = build_option_recommendation(bias, strike_offset_steps=offset)
            if not candidate:
                continue
            if candidate["strike"] in seen_strikes:
                continue
            seen_strikes.add(candidate["strike"])
            ideas.append(candidate)
        ideas.sort(key=lambda r: r["reward_risk"], reverse=True)
        return ideas[:max_ideas]

    recommendations = generate_ranked_recommendations(market_bias) if using_live_chain else []

    st.markdown("### 🎯 Recommended Options Trades")
    if not using_live_chain:
        st.warning("⚠️ Live option chain unavailable — trade recommendations are disabled rather than generated from simulated data.")
    elif recommendations:
        strike_labels = {0: "ATM", 1: "1-OTM", 2: "2-OTM", 3: "3-OTM"}
        for rank, r in enumerate(recommendations, start=1):
            label = strike_labels.get(r["strike_offset_steps"], f"{r['strike_offset_steps']}-OTM")
            st.success(
                f"**#{rank} · {label} · {r['bias']} bias** → BUY **{selected_opt_asset} {int(r['strike'])} {r['side']}** "
                f"@ ~₹{r['premium']:.2f} · **{r['lots']} lot(s)** ({r['lots'] * r['lot_size']} qty) · "
                f"Target ~₹{r['target_premium']} (+{r['target_pct']:.0f}%) · Stop ~₹{r['stop_premium']} (-{r['stop_pct']:.0f}%) · "
                f"Reward:Risk ~{r['reward_risk']}x · "
                f"Capital at risk ~₹{r['total_risk']:,.0f} ({max_risk_pct:.1f}% budget) · "
                f"Required capital ~₹{r['required_capital']:,.0f}"
            )
        st.caption(
            "Ranked by reward:risk across ATM and nearby OTM strikes on the biased side. "
            "This is a directional-bias screen, not investment advice — check liquidity (bid/ask spread) before sizing up."
        )
    else:
        st.info(f"Market bias is currently **{market_bias}** — no high-conviction directional options trade to recommend right now.")

    with st.expander("📊 Detailed Options Analytics (Advanced / Optional)"):
        col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
        col_m1.metric("Underlying Spot", f"₹{underlying_ltp:,.2f}")
        col_m2.metric("Put-Call Ratio (PCR)", f"{pcr_val}" if pcr_val is not None else "N/A")
        col_m3.metric("Estimated Max Pain", f"₹{max_pain_strike}" if max_pain_strike is not None else "N/A")
        col_m4.metric("Live ATM IV", f"{atm_iv_live:.1f}%" if atm_iv_live is not None else "N/A")
        col_m5.metric("Lot Size", f"{lot_size}" if lot_size else "N/A")

        col_iv1, col_iv2 = st.columns(2)
        col_iv1.metric("Realized-Vol Percentile*", f"{iv_percentile_proxy}%" if iv_percentile_proxy is not None else "N/A")
        n_session = len(st.session_state.iv_history.get(selected_opt_asset, []))
        col_iv2.metric("IV Percentile (Persisted, up to 252d)**", f"{session_iv_percentile}% (n={n_session})" if session_iv_percentile is not None else f"Building (n={n_session})")

        st.markdown("#### Black-Scholes Strike Matrix & Full Greeks")
        chain_df = pd.DataFrame(chain_rows)
        st.dataframe(chain_df, use_container_width=True, hide_index=True)
        st.download_button("⬇️ Download Option Chain (CSV)", chain_df.to_csv(index=False).encode(),
                            file_name=f"{selected_opt_asset}_option_chain.csv", mime="text/csv", key="dl_option_chain")

    st.session_state["last_option_chain_summary"] = {
        "asset": selected_opt_asset, "spot": underlying_ltp, "pcr": pcr_val,
        "max_pain": max_pain_strike, "live": using_live_chain, "bias": market_bias,
    }

# ==========================================
# TAB: FUTURES & DERIVATIVES (Upgraded Margin API Integration)
# ==========================================
elif selected_tab == "Futures & Derivatives":
    st.subheader("Futures Trading")
    st.markdown("Index futures with real exchange margin lookup via Upstox Margin API.")

    fut_df = get_futures_instruments()
    if fut_df.empty:
        st.warning("Couldn't load the futures instrument list right now.")
    else:
        fut_index_mapping = {
            "NIFTY 50": ("NSE_INDEX|Nifty 50", r'^NIFTY\d', 65),
            "BANKNIFTY": ("NSE_INDEX|Nifty Bank", r'^BANKNIFTY\d', 30),
            "FINNIFTY": ("NSE_INDEX|Nifty Fin Service", r'^FINNIFTY\d', 60),
            "SENSEX": ("BSE_INDEX|SENSEX", r'^SENSEX\d', 20),
        }
        selected_fut_index = st.selectbox("Select Index:", list(fut_index_mapping.keys()), key="fut_index_select")
        spot_key, symbol_regex, lot_fallback = fut_index_mapping[selected_fut_index]

        spot_quotes = get_live_market_quotes([spot_key], access_token)
        spot_ltp = spot_quotes.get(spot_key, {}).get('last_price', 0.0) if spot_quotes else 0.0
        if spot_ltp <= 0:
            spot_hist = fetch_upstox_history(spot_key, access_token, days=5)
            spot_ltp = float(spot_hist.iloc[-1]['Close']) if not spot_hist.empty else 0.0

        fut_row = get_nearest_future_row(fut_df, symbol_regex)
        if fut_row is None:
            st.warning(f"No {selected_fut_index} futures contract found.")
        else:
            fut_symbol = fut_row.get('tradingsymbol', 'N/A')
            fut_instrument_key = fut_row.get('instrument_key', None)
            fut_expiry = fut_row.get('expiry', 'N/A')
            lot_size = get_lot_size_from_row(fut_row, lot_fallback)
            if not lot_size or lot_size <= 0:
                lot_size = 1

            fut_ltp = 0.0
            if fut_instrument_key:
                fq = get_live_market_quotes([fut_instrument_key], access_token)
                fut_ltp = fq.get(fut_instrument_key, {}).get('last_price', 0.0) if fq else 0.0

            basis = round(fut_ltp - spot_ltp, 2) if (fut_ltp and spot_ltp) else None

            fc1, fc2, fc3, fc4 = st.columns(4)
            fc1.metric("Spot", f"₹{spot_ltp:,.2f}")
            fc2.metric(f"Futures LTP ({fut_symbol})", f"₹{fut_ltp:,.2f}" if fut_ltp else "N/A")
            fc3.metric("Basis (Fut − Spot)", f"₹{basis:+,.2f}" if basis is not None else "N/A")
            fc4.metric("Lot Size", f"{lot_size}", help=f"Expiry: {fut_expiry}")

            def determine_futures_bias():
                try:
                    hist = fetch_upstox_history(spot_key, access_token, days=60)
                    if hist.empty or len(hist) < 20:
                        return "Neutral"
                    ema20 = ta.ema(hist['Close'], length=20).dropna()
                    if ema20.empty:
                        return "Neutral"
                    return "Bullish" if spot_ltp > ema20.iloc[-1] else "Bearish"
                except Exception:
                    return "Neutral"

            fut_bias = determine_futures_bias()
            hist_for_atr = fetch_upstox_history(spot_key, access_token, days=60)
            atr_series = ta.atr(hist_for_atr['High'], hist_for_atr['Low'], hist_for_atr['Close'], length=14).dropna() if not hist_for_atr.empty else pd.Series(dtype=float)

            st.markdown("### 🎯 Recommended Futures Trade")
            if fut_bias == "Neutral" or atr_series.empty or not spot_ltp or not lot_size:
                st.info(f"Trend is currently **{fut_bias}** — no high-conviction directional futures trade to recommend right now.")
            else:
                atr_val = atr_series.iloc[-1]
                direction = "LONG (Buy)" if fut_bias == "Bullish" else "SHORT (Sell)"
                entry = fut_ltp if fut_ltp else spot_ltp
                engine_direction = "long" if fut_bias == "Bullish" else "short"

                target = risk_engine.calculate_target(entry, atr_val, engine_direction, 2.0)
                stop = risk_engine.calculate_stop(entry, atr_val, engine_direction, 1.5)
                risk_per_lot_per_unit = risk_engine.calculate_risk_per_unit(entry, stop)

                tx_type = "BUY" if engine_direction == "long" else "SELL"
                live_margin_per_lot = fetch_upstox_instrument_margin(fut_instrument_key, lot_size, tx_type, "D", access_token) if fut_instrument_key and access_token else None
                
                if live_margin_per_lot is not None and live_margin_per_lot > 0:
                    margin_per_lot = live_margin_per_lot
                    actual_margin_unit = live_margin_per_lot / lot_size
                else:
                    actual_margin_unit = entry * 0.15
                    margin_per_lot = actual_margin_unit * lot_size

                sizing = risk_engine.calculate_position_size(
                    risk_per_unit=risk_per_lot_per_unit, price_per_unit=entry,
                    unit_multiplier=lot_size, actual_margin_required=actual_margin_unit,
                )
                capital_required = risk_engine.calculate_capital_required(entry, sizing.qty, lot_size, actual_margin_required=actual_margin_unit)
                is_valid, _ = risk_engine.validate_trade(sizing.qty, capital_required)
                lots = sizing.qty if is_valid else None
                risk_budget = risk_engine.risk_budget()

                if lots is None:
                    st.info(f"Trend is currently **{fut_bias}**, but sizing constraints prevent 1 lot.")
                else:
                    st.success(
                        f"**{fut_bias} trend** → {direction} **{fut_symbol}** @ ~₹{entry:,.2f} · "
                        f"**{lots} lot(s)** ({lots * lot_size} qty) · Target ~₹{target:,.2f} · Stop ~₹{stop:,.2f} · "
                        f"~₹{margin_per_lot * lots:,.0f} {'live exchange margin' if live_margin_per_lot else 'estimated margin'}"
                    )
                    st.session_state["last_futures_summary"] = {
                        "index": selected_fut_index, "symbol": fut_symbol, "direction": direction,
                        "entry": entry, "target": target, "stop": stop, "lots": lots, "bias": fut_bias,
                    }

# ==========================================
# TAB 2: EQUITIES SCREENER & RISK MANAGEMENT
# ==========================================
elif selected_tab == "Equities Screener & Risk":
    st.subheader("Equities Technical Screener & Position Sizing Engine")
    st.markdown("Tells you what to buy, how much, and how confident the signal is.")

    col_h1, col_h2, col_h3 = st.columns(3)
    with col_h1:
        custom_days = st.number_input("Investment Horizon (Days)", min_value=1, max_value=365, value=15, step=1, key="eq_days_input")
    with col_h2:
        max_stock_price = st.number_input("Max Stock Price Filter (₹)", min_value=10.0, value=50000.0, step=500.0, key="eq_price_filter")
    with col_h3:
        require_weekly_align = st.checkbox("Require Weekly Uptrend Confirmation", value=False, key="eq_weekly_filter")

    st.markdown("#### Scan Universe")
    scan_mode = st.radio(
        "Scan Mode",
        [f"Quick Scan (~{len(LIQUID_CORE_TICKERS)} Liquid Large/Mid Caps)", "Full NSE Scan — quote-scan the full live NSE equity universe"],
        horizontal=True, key="eq_scan_mode"
    )

    if scan_mode.startswith("Quick"):
        universe_tickers = [t for t in LIQUID_CORE_TICKERS if t in instrument_dict] or LIQUID_CORE_TICKERS
        technical_candidate_limit = min(150, len(universe_tickers))
        scan_workers = 6
        st.caption(f"Quick universe: {len(universe_tickers)} liquid names → technical analysis on up to {technical_candidate_limit} candidates.")
    else:
        total_nse = len(all_nse_tickers)
        technical_candidate_limit = st.slider(
            "Maximum candidates for full technical analysis",
            min_value=100, max_value=max(100, total_nse), value=min(250, max(100, total_nse)), step=25,
            key="eq_scan_count",
            help="The quote pass still scans the full NSE equity universe. This control limits only the expensive history/indicator stage after the diversified funnel."
        )
        universe_tickers = list(all_nse_tickers)
        scan_workers = min(12, max(6, technical_candidate_limit // 25))
        st.caption(
            f"Full NSE quote pass: {total_nse} eligible NSE equities. "
            f"Stage-1 funnel → up to {technical_candidate_limit} technical candidates."
        )

    cache_stats = get_cache_stats(DEFAULT_DB_PATH)
    cache_col1, cache_col2 = st.columns([3, 1])
    with cache_col1:
        st.caption(
            f"📦 Local cache: {cache_stats['symbols_cached']} symbols stored, "
            f"{cache_stats['symbols_synced_today']} synced today, "
            f"{cache_stats['total_candle_rows']:,} candle-rows on disk."
        )
    with cache_col2:
        warm_now = st.button(
            "🔄 Warm Technical Cache",
            key="eq_warm_cache_btn",
            help="Sync history only for the current technical shortlist when available."
        )

    st.markdown("---")
    st.markdown(f"### Top Institutional Stock Setups {'🔺 (High VIX — Tightened Stops)' if volatility_regime.startswith('High') else ''}")

    run_scan_now = True
    if scan_mode.startswith("Full"):
        run_scan_now = st.button(
            "🔍 Run Full NSE Quant Scan",
            key="eq_run_full_scan_btn",
            type="primary",
            use_container_width=True,
            help="Quote-scan the full NSE universe, then run heavy technical analysis only on diversified candidates."
        )
        if not run_scan_now and "last_full_scan_signals" in st.session_state:
            valid_signals = st.session_state["last_full_scan_signals"]
    else:
        run_scan_now = st.button("🚀 Run Quick Quant Scan", key="eq_run_quick_btn", type="primary")
        if not run_scan_now and "last_quick_signals" in st.session_state:
            valid_signals = st.session_state["last_quick_signals"]
            run_scan_now = False

    if warm_now:
        warm_tickers = st.session_state.get("last_stage1_shortlist")
        if not warm_tickers:
            warm_tickers = universe_tickers[:min(technical_candidate_limit, 300)] if scan_mode.startswith("Full") else universe_tickers
        warm_keys = [instrument_dict.get(t) for t in warm_tickers if instrument_dict.get(t)]
        warm_progress = st.progress(0, text="Warming cache...")

        def _warm_progress_cb(done, total, key):
            if total:
                warm_progress.progress(done / total, text=f"Cached {done}/{total}")

        warm_result = warm_cache(
            warm_keys, access_token, days=400, db_path=DEFAULT_DB_PATH,
            max_workers=scan_workers, progress_callback=_warm_progress_cb,
            fetch_fn=_fetch_upstox_history_impl,
        )
        warm_progress.empty()
        st.success(
            f"Cache warmed: {warm_result['synced']} symbols synced, "
            f"{warm_result['already_fresh']} already fresh today, "
            f"{warm_result['failed']} failed."
        )

    if run_scan_now:
        active_scan_keys = [instrument_dict.get(t) for t in universe_tickers if instrument_dict.get(t)]
        live_quote_data = get_live_scan_market_data(active_scan_keys, access_token)

        stage1_shortlist, funnel_stats = stage1_multi_bucket_prefilter(
            universe_tickers,
            instrument_dict,
            live_quote_data,
            technical_candidate_limit,
            DEFAULT_DB_PATH,
        )
        funnel_stats = dict(funnel_stats or {})
        funnel_stats.setdefault("universe_size", len(universe_tickers))
        funnel_stats.setdefault("quoted", 0)
        funnel_stats.setdefault("no_quote", max(len(universe_tickers) - funnel_stats.get("quoted", 0), 0))
        funnel_stats.setdefault("shortlisted", len(stage1_shortlist))
        funnel_stats.setdefault("session_fraction", _session_elapsed_fraction())
        funnel_stats.setdefault("bucket_counts", {})
        st.session_state["last_stage1_shortlist"] = stage1_shortlist

        def evaluate_stock(ticker):
            try:
                key = instrument_dict.get(ticker)
                if not key:
                    return None

                raw_quote = live_quote_data.get(key, {}) if live_quote_data else {}
                live_price = raw_quote.get("last_price")

                df = get_cached_history(key, access_token, days=400, fetch_fn=_fetch_upstox_history_impl)
                if df.empty or len(df) < 210:
                    return None

                df = prepare_live_daily_bar(df, raw_quote)
                if df.empty or len(df) < 210:
                    return None

                price = float(live_price) if live_price and float(live_price) > 0 else float(df['Close'].iloc[-1])

                df['EMA_20'] = ta.ema(df['Close'], length=20)
                df['EMA_50'] = ta.ema(df['Close'], length=50)
                df['EMA_200'] = ta.ema(df['Close'], length=200)

                macd_df = ta.macd(df['Close'], fast=12, slow=26, signal=9)
                if macd_df is not None and not macd_df.empty:
                    df['MACD'] = macd_df.iloc[:, 0]
                    df['MACD_signal'] = macd_df.iloc[:, 2]
                else:
                    df['MACD'] = np.nan
                    df['MACD_signal'] = np.nan

                bb_df = ta.bbands(df['Close'], length=20, std=2)
                if bb_df is not None and not bb_df.empty:
                    df['BB_lower'] = bb_df.iloc[:, 0]
                    df['BB_upper'] = bb_df.iloc[:, 2]
                else:
                    df['BB_lower'] = np.nan
                    df['BB_upper'] = np.nan

                adx_df = ta.adx(df['High'], df['Low'], df['Close'], length=14)
                df['ADX'] = adx_df.iloc[:, 0] if adx_df is not None and not adx_df.empty else np.nan
                df['RSI'] = ta.rsi(df['Close'], length=14)
                df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)

                typical = (df['High'] + df['Low'] + df['Close']) / 3.0
                vol = df['Volume'].fillna(0.0)
                rolling_pv = (typical * vol).rolling(20).sum()
                rolling_vol = vol.rolling(20).sum()
                df['VWAP20'] = rolling_pv / rolling_vol.replace(0, np.nan)

                st_df = ta.supertrend(df['High'], df['Low'], df['Close'], length=10, multiplier=3)
                supertrend_bullish = None
                if st_df is not None and not st_df.empty:
                    direction_col = None
                    for col in st_df.columns:
                        if 'SUPERTd' in col:
                            direction_col = st_df[col]
                            break
                    if direction_col is None:
                        direction_col = st_df.iloc[:, 1]
                    df['ST_direction'] = direction_col
                    last_dir = df['ST_direction'].iloc[-1]
                    supertrend_bullish = (last_dir == 1) if not pd.isna(last_dir) else None

                weekly_trend = get_weekly_trend(df)
                rs_vs_nifty = relative_strength_vs_nifty(df, lookback=min(20, len(df) - 1))

                df_clean = df.dropna(subset=['EMA_20', 'EMA_50', 'EMA_200', 'ATR'])
                if df_clean.empty:
                    return None
                latest = df_clean.iloc[-1]

                if price > max_stock_price:
                    return None
                if price < float(latest['EMA_50']):
                    return None
                if require_weekly_align and weekly_trend != "Bullish (Weekly)":
                    return None

                if not bool(supertrend_bullish):
                    return None
                if float(latest['EMA_20']) < float(latest['EMA_50']):
                    return None

                atr_val = float(latest['ATR'])
                if not np.isfinite(atr_val) or atr_val <= 0:
                    return None

                sl, tgt, rr_ratio, levels = derive_long_trade_levels(
                    df_clean, price, atr_val, horizon_days=custom_days
                )
                if sl is None or tgt is None or rr_ratio is None or rr_ratio < 1.35:
                    return None

                risk_per_share = risk_engine.calculate_risk_per_unit(price, sl)
                if risk_per_share <= 0:
                    return None
                sizing = risk_engine.calculate_position_size(
                    risk_per_unit=risk_per_share,
                    price_per_unit=price,
                    unit_multiplier=1,
                )
                qty_to_buy = sizing.qty
                capital_required = risk_engine.calculate_capital_required(price, qty_to_buy, 1)
                is_valid, _ = risk_engine.validate_trade(qty_to_buy, capital_required)
                if not is_valid:
                    return None

                exp_return_pct = ((tgt - price) / price) * 100.0
                risk_pct = (risk_per_share / price) * 100.0 if price else 0.0
                r_multiple = round(float(rr_ratio), 2)
                risk_reward_str = f"1 : {r_multiple}"

                adx_val = latest.get('ADX')
                rsi_val = latest.get('RSI')
                adx_display = round(float(adx_val), 1) if not pd.isna(adx_val) else "N/A"
                rsi_display = round(float(rsi_val), 1) if not pd.isna(rsi_val) else "N/A"
                ema_trend = classify_ema_trend(latest)
                macd_status = classify_macd(df_clean)
                bb_percent_b = compute_bollinger_percent_b(latest)

                ema20_now = float(latest['EMA_20'])
                slope_base_idx = max(len(df_clean) - 11, 0)
                ema20_prev = float(df_clean['EMA_20'].iloc[slope_base_idx])
                ema20_slope_pct = ((ema20_now / ema20_prev) - 1.0) * 100.0 if ema20_prev else 0.0

                avg_vol20 = float(df_clean['Volume'].tail(20).mean()) if 'Volume' in df_clean.columns else 0.0
                current_day_volume = float(df_clean['Volume'].iloc[-1]) if 'Volume' in df_clean.columns else 0.0
                elapsed_fraction = _session_elapsed_fraction()
                volume_pace_ratio = (current_day_volume / avg_vol20 / elapsed_fraction) if avg_vol20 > 0 else None

                # Walk-Forward OOS Probability Calibration Engine
                wf_result = compute_walk_forward_probability(df_clean, horizon_days=custom_days)
                oos_win_prob = wf_result['out_of_sample_win_prob'] if wf_result else 55.0
                sample_tier = wf_result['sample_tier'] if wf_result else "Insufficient (<30 OOS samples)"

                # Multi-Factor Model (Beta, Momentum Factor, Volatility Factor)
                stock_rets = df_clean['Close'].pct_change().dropna()
                nifty_rets = nifty_hist_df['Close'].pct_change().dropna() if nifty_hist_df is not None and not nifty_hist_df.empty else pd.Series(dtype=float)
                aligned_rets = pd.concat([stock_rets, nifty_rets], axis=1).dropna()
                if len(aligned_rets) > 30:
                    cov = np.cov(aligned_rets.iloc[:, 0], aligned_rets.iloc[:, 1])[0][1]
                    var_nifty = np.var(aligned_rets.iloc[:, 1])
                    stock_beta = float(cov / var_nifty) if var_nifty > 0 else 1.0
                else:
                    stock_beta = 1.0

                mom_factor = ((price / float(df_clean['Close'].iloc[-252])) - 1.0) * 100.0 if len(df_clean) >= 252 else 0.0
                beta_score = _clamp(100.0 - abs(stock_beta - 1.0) * 40.0)
                factor_score = (_scale(mom_factor, -20.0, 50.0) * 0.5) + (beta_score * 0.5)

                confirmations = 0
                if supertrend_bullish: confirmations += 1
                if macd_status in ("🟢 Bullish Crossover", "🟢 Above Signal"): confirmations += 1
                if weekly_trend == "Bullish (Weekly)": confirmations += 1
                if rs_vs_nifty is not None and rs_vs_nifty > 0: confirmations += 1
                if not pd.isna(adx_val) and float(adx_val) > 25: confirmations += 1
                if ema_trend.startswith("🟢"): confirmations += 1
                if price > float(latest.get('VWAP20', price)): confirmations += 1
                if volume_pace_ratio is not None and volume_pace_ratio >= 1.2: confirmations += 1

                trend_score = _clamp(
                    (40 if ema_trend.startswith("🟢") else 20)
                    + (20 if supertrend_bullish else 0)
                    + _scale(ema20_slope_pct, -2.0, 2.0) * 0.40
                )
                momentum_20d = ((price / float(df_clean['Close'].iloc[-21])) - 1.0) * 100.0 if len(df_clean) > 21 else 0.0
                momentum_score = _scale(momentum_20d, -10.0, 10.0)
                volume_score = _scale(volume_pace_ratio if volume_pace_ratio is not None else 1.0, 0.5, 3.0)
                rs_score = _scale(rs_vs_nifty if rs_vs_nifty is not None else 0.0, -5.0, 10.0)
                rr_score = _scale(r_multiple, 1.0, 4.0)
                adx_score = _scale(float(adx_val), 15.0, 45.0) if not pd.isna(adx_val) else 50.0
                volatility_pct = (atr_val / price) * 100.0 if price else 0.0
                volatility_score = _clamp(100.0 - abs(volatility_pct - 2.0) * 30.0)
                edge_score = _scale(oos_win_prob, 45.0, 75.0)

                score = (
                    trend_score * 0.15
                    + momentum_score * 0.12
                    + volume_score * 0.10
                    + rs_score * 0.10
                    + rr_score * 0.15
                    + adx_score * 0.08
                    + volatility_score * 0.06
                    + edge_score * 0.10
                    + factor_score * 0.14
                )

                if score >= 78:
                    conviction = "🟢🟢🟢 High"
                elif score >= 62:
                    conviction = "🟢🟢 Medium"
                else:
                    conviction = "🟢 Low"

                signal_strength = round(float(_clamp(score)), 1)
                ticker_sector = get_ticker_sector(ticker)

                return {
                    "Ticker": ticker,
                    "Sector": ticker_sector,
                    "Live Price": f"₹{price:,.2f}",
                    "Action": "BUY",
                    "Target": f"₹{tgt:,.2f}",
                    "Stop Loss": f"₹{sl:,.2f}",
                    "Qty (Position Sized)": qty_to_buy,
                    "Conviction": conviction,
                    "Signal Strength": signal_strength,
                    "Quality Ratio": r_multiple,
                    "R-Multiple": f"{r_multiple}R",
                    "Risk:Reward": risk_reward_str,
                    "Risk %": round(risk_pct, 2),
                    "Exp Return": f"+{exp_return_pct:.2f}%",
                    "OOS Win Prob": f"{oos_win_prob:.1f}%",
                    "Sample Tier": sample_tier,
                    "Beta": round(stock_beta, 2),
                    "EMA Trend": ema_trend,
                    "MACD": macd_status,
                    "Bollinger %B": f"{bb_percent_b}%" if bb_percent_b is not None else "N/A",
                    "RSI": rsi_display,
                    "ADX": adx_display,
                    "SuperTrend": "🟢 Bullish" if supertrend_bullish else "🔴 Bearish",
                    "Weekly Trend": weekly_trend,
                    "RS vs Nifty50": f"{rs_vs_nifty:+.2f}%" if rs_vs_nifty is not None else "N/A",
                    "20D VWAP": f"₹{float(latest.get('VWAP20')):,.2f}" if pd.notna(latest.get('VWAP20')) else "N/A",
                    "Volume Pace": f"{volume_pace_ratio:.2f}x" if volume_pace_ratio is not None else "N/A",
                    "EMA20 Slope": f"{ema20_slope_pct:+.2f}%",
                    "_price_val": float(price),
                    "_qty": int(qty_to_buy),
                    "_risk_amt": float(risk_per_share * qty_to_buy),
                    "_returns": df_clean['Close'].tail(120).pct_change().dropna(),
                    "_sector": ticker_sector,
                    "score": float(score),
                }
            except Exception as exc:
                LOGGER.debug("evaluate_stock failed for %s: %s", ticker, exc)
                return None

        valid_signals = []
        progress_bar = st.progress(0, text="Analyzing shortlist with Walk-Forward calibration & Multi-Factor scoring...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=scan_workers) as executor:
            futures = {executor.submit(evaluate_stock, ticker): ticker for ticker in stage1_shortlist}
            completed = 0
            for future in concurrent.futures.as_completed(futures):
                completed += 1
                ticker = futures[future]
                progress_bar.progress(completed / max(len(futures), 1), text=f"Analyzed {completed}/{len(futures)} — {ticker}")
                try:
                    result = future.result()
                    if result:
                        valid_signals.append(result)
                except Exception as exc:
                    LOGGER.exception("Unexpected worker failure for %s", ticker)
            progress_bar.empty()

        if scan_mode.startswith("Full"):
            st.session_state["last_full_scan_signals"] = valid_signals
        else:
            st.session_state["last_quick_signals"] = valid_signals

    if "valid_signals" not in locals():
        valid_signals = st.session_state.get("last_quick_signals" if scan_mode.startswith("Quick") else "last_full_scan_signals", [])

    def select_diversified_top_n(signals, n=10, corr_threshold=0.75, max_sector_pct=30.0):
        if not signals:
            return []
        heat_budget = investment_capital * (max_portfolio_heat_pct / 100.0) if investment_capital else float('inf')
        ranked = sorted(signals, key=lambda x: x['score'], reverse=True)

        returns_map = {
            s["Ticker"]: s["_returns"] for s in ranked
            if s.get("_returns") is not None and not s["_returns"].empty
        }
        corr_matrix = pd.DataFrame(returns_map).corr() if len(returns_map) >= 2 else pd.DataFrame()

        selected, rejected = [], []
        cumulative_risk = 0.0
        sector_allocation_counts = {}

        for cand in ranked:
            if len(selected) >= n:
                break
            if cumulative_risk + cand["_risk_amt"] > heat_budget:
                continue

            sec = cand.get("_sector", "Other")
            current_sector_count = sector_allocation_counts.get(sec, 0)
            max_allowed_sector_picks = max(1, int(n * (max_sector_pct / 100.0)))
            if current_sector_count >= max_allowed_sector_picks:
                rejected.append(cand)
                continue

            too_correlated = False
            for sel in selected:
                try:
                    if not corr_matrix.empty and cand["Ticker"] in corr_matrix.index and sel["Ticker"] in corr_matrix.columns:
                        corr_val = corr_matrix.loc[cand["Ticker"], sel["Ticker"]]
                        if pd.notna(corr_val) and corr_val > corr_threshold:
                            too_correlated = True
                            break
                except Exception:
                    continue
            if too_correlated:
                rejected.append(cand)
            else:
                selected.append(cand)
                cumulative_risk += cand["_risk_amt"]
                sector_allocation_counts[sec] = current_sector_count + 1

        for cand in rejected:
            if len(selected) >= n:
                break
            if cumulative_risk + cand["_risk_amt"] > heat_budget:
                continue
            sec = cand.get("_sector", "Other")
            current_sector_count = sector_allocation_counts.get(sec, 0)
            if current_sector_count >= max(2, int(n * 0.4)):
                continue
            selected.append(cand)
            cumulative_risk += cand["_risk_amt"]
            sector_allocation_counts[sec] = current_sector_count + 1

        return selected

    if valid_signals:
        valid_signals = select_diversified_top_n(valid_signals, n=10, corr_threshold=0.75, max_sector_pct=30.0)
        st.session_state["last_screener_results"] = valid_signals

        best = valid_signals[0]
        st.success(
            f"🏆 **Top Pick: {best['Ticker']} ({best['Sector']})** — Buy at {best['Live Price']}, Qty {best['_qty']}, "
            f"Target {best['Target']}, Stop {best['Stop Loss']} ({best['Conviction']} conviction, "
            f"OOS Win Prob {best['OOS Win Prob']}, R:R {best['Risk:Reward']})"
        )

        hidden_cols = ['score', '_price_val', '_qty', '_risk_amt', '_returns', '_sector']
        df_top10_display = pd.DataFrame(valid_signals).drop(columns=[c for c in hidden_cols if c in pd.DataFrame(valid_signals).columns])
        st.markdown(f"##### Top {len(df_top10_display)} Institutional Equities — {custom_days}-Day Horizon (Under ₹{max_stock_price:,.0f}):")
        st.dataframe(df_top10_display, use_container_width=True, hide_index=True)
        st.download_button("⬇️ Download Screener Results (CSV)", df_top10_display.to_csv(index=False).encode(),
                            file_name="screener_results.csv", mime="text/csv", key="dl_screener")

        st.markdown("### 📊 Portfolio Heat — Exposure If All Picks Are Taken")
        total_deployed = sum(s["_price_val"] * s["_qty"] for s in valid_signals)
        total_risk_amt = sum(s["_risk_amt"] for s in valid_signals)
        portfolio_heat_pct = risk_engine.calculate_portfolio_heat([s["_risk_amt"] for s in valid_signals])
        st.session_state["last_portfolio_heat"] = portfolio_heat_pct

        exp1, exp2, exp3, exp4 = st.columns(4)
        exp1.metric("Capital Deployed", f"₹{total_deployed:,.0f}", f"{(total_deployed/investment_capital*100):.1f}% of capital" if investment_capital else None)
        exp2.metric("Total ₹ at Risk", f"₹{total_risk_amt:,.0f}")
        exp3.metric("Portfolio Heat", f"{portfolio_heat_pct:.2f}%")
        exp4.metric("Picks", f"{len(valid_signals)}")

        sector_counts = pd.Series([s["Sector"] for s in valid_signals]).value_counts()
        st.markdown("**Sector Concentration Breakdown:**")
        sec_cols = st.columns(len(sector_counts) if len(sector_counts) <= 6 else 6)
        for idx, (sec_name, sec_cnt) in enumerate(sector_counts.items()):
            with sec_cols[idx % len(sec_cols)]:
                st.metric(sec_name, f"{sec_cnt} pick(s)")

        with st.expander("🔗 Correlation Check Across Current Picks"):
            price_series = {s["Ticker"]: s["_returns"] for s in valid_signals if s.get("_returns") is not None and not s["_returns"].empty}
            if len(price_series) >= 2:
                returns_df = pd.DataFrame(price_series).dropna()
                if not returns_df.empty:
                    corr_matrix = returns_df.corr().round(2)
                    st.dataframe(corr_matrix.style.background_gradient(cmap="RdYlGn_r", vmin=-1, vmax=1), use_container_width=True)
            else:
                st.info("Not enough return history.")

        with st.expander("🧪 Strategy Backtest — Upgraded Sanity Test"):
            st.caption(
                "This backtest uses out-of-sample walk-forward validation parameters with next-bar entry, "
                "structural support/resistance targets derived from derive_long_trade_levels() (matching live trading), "
                "no overlapping trades, conservative same-candle handling, and estimated round-trip costs."
            )
            if st.button("Run Upgraded Backtest", key="run_backtest_btn"):
                def backtest_signal(hist_df, hold_days, cost_pct=0.3):
                    try:
                        d = hist_df.copy()
                        d['EMA_20'] = ta.ema(d['Close'], length=20)
                        d['EMA_50'] = ta.ema(d['Close'], length=50)
                        adx_df = ta.adx(d['High'], d['Low'], d['Close'], length=14)
                        d['ADX'] = adx_df.iloc[:, 0] if adx_df is not None and not adx_df.empty else np.nan
                        d['ATR'] = ta.atr(d['High'], d['Low'], d['Close'], length=14)
                        d = d.dropna(subset=['EMA_20', 'EMA_50', 'ADX', 'ATR'])
                        if len(d) < hold_days + 70:
                            return None

                        closes = d['Close'].values
                        highs = d['High'].values
                        lows = d['Low'].values
                        opens = d['Open'].values
                        ema20 = d['EMA_20'].values
                        ema50 = d['EMA_50'].values
                        adx = d['ADX'].values
                        atr = d['ATR'].values

                        trades = []
                        curve = [1.0]
                        i = 60
                        while i < len(d) - hold_days - 2:
                            signal = closes[i] > ema50[i] and ema20[i] >= ema50[i] and adx[i] >= 20
                            if not signal:
                                i += 1
                                continue

                            entry_idx = i + 1
                            entry = opens[entry_idx]
                            if entry <= 0:
                                i += 1
                                continue

                            hist_window = d.iloc[max(0, i - 60):i + 1]
                            sl, tgt, rr, _ = derive_long_trade_levels(hist_window, entry, float(atr[i]), hold_days)
                            if sl is None or tgt is None or rr is None or rr < 1.2:
                                i += 1
                                continue

                            exit_idx = min(entry_idx + hold_days, len(d) - 1)
                            exit_price = closes[exit_idx]
                            outcome = "TIME"
                            for j in range(entry_idx, exit_idx + 1):
                                hit_sl = lows[j] <= sl
                                hit_tgt = highs[j] >= tgt
                                if hit_sl and hit_tgt:
                                    exit_idx = j
                                    exit_price = sl
                                    outcome = "BOTH→SL"
                                    break
                                if hit_sl:
                                    exit_idx = j
                                    exit_price = sl
                                    outcome = "SL"
                                    break
                                if hit_tgt:
                                    exit_idx = j
                                    exit_price = tgt
                                    outcome = "TP"
                                    break

                            gross = (exit_price / entry - 1.0) * 100.0
                            net = gross - cost_pct
                            trades.append({"ret": net, "outcome": outcome})
                            curve.append(curve[-1] * (1.0 + net / 100.0))
                            i = exit_idx + 1

                        if not trades:
                            return None

                        rets = np.array([t["ret"] for t in trades], dtype=float)
                        wins = int((rets > 0).sum())
                        losses = int((rets < 0).sum())
                        gross_profit = float(rets[rets > 0].sum()) if wins else 0.0
                        gross_loss = float(-rets[rets < 0].sum()) if losses else 0.0
                        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
                        running_max = np.maximum.accumulate(curve)
                        drawdowns = (np.array(curve) / running_max - 1.0) * 100.0
                        max_dd = float(drawdowns.min()) if len(drawdowns) else 0.0

                        return {
                            "Trades": len(trades),
                            "Win Rate": f"{100.0 * wins / len(trades):.1f}%",
                            "Avg Return/Trade": f"{rets.mean():+.2f}%",
                            "Profit Factor": f"{profit_factor:.2f}" if np.isfinite(profit_factor) else "∞",
                            "Max Drawdown": f"{max_dd:.2f}%",
                        }
                    except Exception as exc:
                        LOGGER.debug("Backtest failed: %s", exc)
                        return None

                bt_rows = []
                for s in valid_signals:
                    key = instrument_dict.get(s["Ticker"])
                    if not key:
                        continue
                    hdf = get_cached_history(key, access_token, days=400, fetch_fn=_fetch_upstox_history_impl)
                    if hdf.empty:
                        continue
                    result = backtest_signal(hdf, custom_days)
                    if result:
                        bt_rows.append({"Ticker": s["Ticker"], **result})
                if bt_rows:
                    st.dataframe(pd.DataFrame(bt_rows), use_container_width=True, hide_index=True)
                else:
                    st.warning("Not enough history to backtest these tickers.")
    else:
        st.warning("No equities matched the strict technical filter criteria. Try clicking 'Run Quick Quant Scan' or adjusting filters.")
        st.session_state["last_screener_results"] = []

# ==========================================
# TAB: COMMODITIES (MCX)
# ==========================================
elif selected_tab == "Commodities (MCX)":
    st.subheader("MCX Commodity Derivatives Terminal")
    st.markdown("Track and analyze major MCX commodity contracts (Gold, Silver, Crude Oil, Natural Gas, etc.) with live pricing and risk sizing.")

    mcx_fut_df = get_mcx_futures_instruments()
    if not all_mcx_tickers and mcx_fut_df.empty:
        st.warning("Couldn't load MCX instrument dictionary. Check your connection or clear cache.")
    else:
        selected_commodity = st.selectbox("Select Commodity Symbol:", all_mcx_tickers, key="mcx_ticker_select")
        mcx_key = mcx_dict.get(selected_commodity)

        if mcx_key:
            mcx_quotes = get_live_market_quotes([mcx_key], access_token)
            mcx_ltp = mcx_quotes.get(mcx_key, {}).get('last_price', 0.0) if mcx_quotes else 0.0
            
            if mcx_ltp <= 0:
                hist_mcx = fetch_upstox_history(mcx_key, access_token, days=30)
                mcx_ltp = float(hist_mcx.iloc[-1]['Close']) if not hist_mcx.empty else 0.0

            hist_df = fetch_upstox_history(mcx_key, access_token, days=120)
            
            mcx_col1, mcx_col2, mcx_col3 = st.columns(3)
            mcx_col1.metric("Live Commodity Price", f"₹{mcx_ltp:,.2f}" if mcx_ltp else "N/A")
            
            if not hist_df.empty:
                atr_series = ta.atr(hist_df['High'], hist_df['Low'], hist_df['Close'], length=14).dropna()
                curr_atr = float(atr_series.iloc[-1]) if not atr_series.empty else 0.0
                rsi_series = ta.rsi(hist_df['Close'], length=14).dropna()
                curr_rsi = float(rsi_series.iloc[-1]) if not rsi_series.empty else 50.0

                mcx_col2.metric("ATR (14)", f"₹{curr_atr:,.2f}")
                mcx_col3.metric("RSI (14)", f"{curr_rsi:.1f}")

                st.markdown("### 🎯 Commodity Risk-Managed Setup")
                if mcx_ltp > 0 and curr_atr > 0:
                    c_stop = round(mcx_ltp - (1.5 * curr_atr), 2)
                    c_target = round(mcx_ltp + (3.0 * curr_atr), 2)
                    c_risk_per_unit = risk_engine.calculate_risk_per_unit(mcx_ltp, c_stop)
                    
                    c_lot_size = 1
                    if "GOLD" in selected_commodity: c_lot_size = 100
                    elif "SILVER" in selected_commodity: c_lot_size = 30
                    elif "CRUDEOIL" in selected_commodity: c_lot_size = 100
                    elif "NATURALGAS" in selected_commodity: c_lot_size = 1250

                    c_margin = fetch_upstox_instrument_margin(mcx_key, c_lot_size, "BUY", "D", access_token) if access_token else None
                    c_unit_margin = (c_margin / c_lot_size) if c_margin and c_margin > 0 else (mcx_ltp * 0.10)

                    c_sizing = risk_engine.calculate_position_size(
                        risk_per_unit=c_risk_per_unit, price_per_unit=mcx_ltp, unit_multiplier=c_lot_size, actual_margin_required=c_unit_margin
                    )
                    
                    st.success(
                        f"**Setup for {selected_commodity}** → LONG @ ~₹{mcx_ltp:,.2f} · "
                        f"**{c_sizing.qty} lot(s)** ({c_sizing.qty * c_lot_size} units) · "
                        f"Target ~₹{c_target:,.2f} · Stop ~₹{c_stop:,.2f}"
                    )
                else:
                    st.info("Insufficient price action data to derive risk setup for this commodity.")

                fig = go.Figure(data=[go.Candlestick(
                    x=hist_df.index, open=hist_df['Open'], high=hist_df['High'],
                    low=hist_df['Low'], close=hist_df['Close'], name=selected_commodity
                )])
                ema_20 = ta.ema(hist_df['Close'], length=20)
                fig.add_trace(go.Scatter(x=hist_df.index, y=ema_20, line=dict(color='#ff9800', width=1.5), name='EMA 20'))
                fig.update_layout(xaxis_rangeslider_visible=False, height=450, template="plotly_dark", paper_bgcolor="#050505", plot_bgcolor="#0a0a0a")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("Could not fetch historical data for this commodity contract.")
        else:
            st.warning("Select a valid MCX commodity from the list above.")

# ==========================================
# TAB: MUTUAL FUNDS
# ==========================================
elif selected_tab == "Mutual Funds":
    st.subheader("Mutual Fund Suggestions")
    st.markdown("Real NAV/returns data from AMFI via the free public [mfapi.in](https://www.mfapi.in) service.")

    mf_tab1, mf_tab2 = st.tabs(["🏆 Top Picks by Category", "🔍 Look Up Any Fund"])

    with mf_tab1:
        selected_mf_category = st.selectbox("Category", list(MF_CATEGORY_KEYWORDS.keys()), key="mf_category_select")
        if st.button("Find Top Funds", key="mf_find_top_btn"):
            all_schemes = fetch_mf_scheme_list()
            if not all_schemes:
                st.warning("Couldn't reach the mutual fund data service right now.")
            else:
                candidates = shortlist_mf_schemes(all_schemes, MF_CATEGORY_KEYWORDS[selected_mf_category])
                if not candidates:
                    st.info(f"No Direct-Growth schemes matched '{selected_mf_category}'.")
                else:
                    MF_MAX_ANALYZED = 60
                    if len(candidates) > MF_MAX_ANALYZED:
                        candidates = candidates[:MF_MAX_ANALYZED]
                    results = []
                    progress = st.progress(0, text="Fetching NAV history...")
                    for i, c in enumerate(candidates):
                        progress.progress((i + 1) / len(candidates), text=f"Analyzing {c['schemeName'][:50]}...")
                        nav_json = fetch_mf_nav_history(c["schemeCode"])
                        stats = compute_mf_returns(nav_json)
                        if stats:
                            stats["scheme_code"] = c["schemeCode"]
                            results.append(stats)
                    progress.empty()

                    if not results:
                        st.warning("Couldn't compute returns for any candidate.")
                    else:
                        ranked = sorted(results, key=lambda x: (x["quality"] if x["quality"] is not None else -999), reverse=True)[:8]
                        rows = []
                        for r in ranked:
                            rows.append({
                                "Scheme": r["scheme_name"],
                                "Fund House": r["fund_house"],
                                "1Y Return": f"{r['ret_1y']:+.2f}%" if r['ret_1y'] is not None else "N/A",
                                "3Y CAGR": f"{r['cagr_3y']:+.2f}%" if r['cagr_3y'] is not None else "N/A",
                                "Volatility (ann.)": f"{r['volatility']:.2f}%" if r['volatility'] is not None else "N/A",
                                "Quality": r["quality"] if r["quality"] is not None else "N/A",
                                "Latest NAV": f"₹{r['latest_nav']:,.2f}",
                            })
                        st.success(f"Top {len(rows)} {selected_mf_category} funds:")
                        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                        st.session_state["last_mf_top_picks"] = {"category": selected_mf_category, "top": rows[:3]}

    with mf_tab2:
        mf_query = st.text_input("Search fund name (e.g. 'HDFC Flexi Cap')", key="mf_search_input")
        if mf_query and len(mf_query) >= 3:
            search_results = search_mf_schemes(mf_query)
            direct_growth_results = [s for s in search_results if is_direct_growth_plan(s.get("schemeName", ""))]
            display_results = direct_growth_results or search_results
            if display_results:
                options_map = {s["schemeName"]: s["schemeCode"] for s in display_results[:30]}
                chosen_name = st.selectbox("Matching schemes:", list(options_map.keys()), key="mf_search_select")
                if chosen_name:
                    nav_json = fetch_mf_nav_history(options_map[chosen_name])
                    stats = compute_mf_returns(nav_json)
                    if stats:
                        mc1, mc2, mc3, mc4 = st.columns(4)
                        mc1.metric("Latest NAV", f"₹{stats['latest_nav']:,.2f}")
                        mc2.metric("1Y Return", f"{stats['ret_1y']:+.2f}%" if stats['ret_1y'] is not None else "N/A")
                        mc3.metric("3Y CAGR", f"{stats['cagr_3y']:+.2f}%" if stats['cagr_3y'] is not None else "N/A")
                        mc4.metric("Volatility (ann.)", f"{stats['volatility']:.2f}%" if stats['volatility'] is not None else "N/A")

                        nav_df = stats["nav_df"]
                        fig = go.Figure(data=[go.Scatter(x=nav_df['date'], y=nav_df['nav'], mode='lines', line=dict(color='#2962ff', width=2))])
                        fig.update_layout(title=f"{chosen_name} — NAV History", height=400, template="plotly_dark",
                                           paper_bgcolor="#050505", plot_bgcolor="#0a0a0a")
                        st.plotly_chart(fig, use_container_width=True)

# ==========================================
# TAB 3: SMC & TECHNICAL ANALYSIS
# ==========================================
elif selected_tab == "SMC & Technical Analysis":
    st.subheader("Smart Money Concepts (SMC) & Interactive Plotly Charting")
    st.markdown("FVG, swing-based Order Blocks, BOS vs CHoCH, Liquidity Sweeps, and Volume Profile.")

    col_l1, col_l2 = st.columns([2, 2])
    with col_l1:
        search_ticker = st.selectbox("Select NSE Stock:", options=["-- Select Stock --"] + all_nse_tickers, key="stock_lookup_select")
    with col_l2:
        lookup_days = st.number_input("Target Horizon (Days)", min_value=1, max_value=365, value=15, step=1, key="lookup_days_input")

    def detect_market_structure(df, lookback=5):
        highs, lows = df['High'], df['Low']
        swing_highs, swing_lows = [], []
        for i in range(lookback, len(df) - lookback):
            window_h = highs.iloc[i - lookback:i + lookback + 1]
            window_l = lows.iloc[i - lookback:i + lookback + 1]
            if highs.iloc[i] == window_h.max():
                swing_highs.append(highs.iloc[i])
            if lows.iloc[i] == window_l.min():
                swing_lows.append(lows.iloc[i])

        trend_state = "Neutral / Ranging"
        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            last_sh, prev_sh = swing_highs[-1], swing_highs[-2]
            last_sl, prev_sl = swing_lows[-1], swing_lows[-2]
            if last_sh > prev_sh and last_sl > prev_sl:
                trend_state = "Bullish (HH-HL)"
            elif last_sh < prev_sh and last_sl < prev_sl:
                trend_state = "Bearish (LH-LL)"

        event = "None"
        if swing_highs and swing_lows:
            last_close = df['Close'].iloc[-1]
            last_sh, last_sl = swing_highs[-1], swing_lows[-1]
            if trend_state == "Bearish (LH-LL)" and last_close > last_sh:
                event = "🔄 Bullish CHoCH (reversal signal)"
            elif trend_state == "Bullish (HH-HL)" and last_close < last_sl:
                event = "🔄 Bearish CHoCH (reversal signal)"
            elif trend_state == "Bullish (HH-HL)" and last_close > last_sh:
                event = "➡️ Bullish BOS (continuation)"
            elif trend_state == "Bearish (LH-LL)" and last_close < last_sl:
                event = "➡️ Bearish BOS (continuation)"

        return trend_state, event

    def detect_order_block(df, atr_series_full, atr_latest):
        try:
            for i in range(len(df) - 2, max(len(df) - 25, 0), -1):
                candle = df.iloc[i]
                nxt = df.iloc[i + 1]
                impulse_atr = atr_series_full.iloc[i + 1] if (i + 1) < len(atr_series_full) and not pd.isna(atr_series_full.iloc[i + 1]) else atr_latest
                bullish_impulse = (nxt['Close'] - nxt['Open']) > (1.5 * impulse_atr)
                bearish_candle = candle['Close'] < candle['Open']
                if bearish_candle and bullish_impulse:
                    return f"Bullish OB Zone: ₹{candle['Low']:,.2f} - ₹{candle['High']:,.2f}"
                bearish_impulse = (nxt['Open'] - nxt['Close']) > (1.5 * impulse_atr)
                bullish_candle = candle['Close'] > candle['Open']
                if bullish_candle and bearish_impulse:
                    return f"Bearish OB Zone: ₹{candle['Low']:,.2f} - ₹{candle['High']:,.2f}"
            return "No Clear OB Detected"
        except Exception:
            return "No Clear OB Detected"

    def detect_liquidity_sweep(df, lookback=10):
        try:
            if len(df) < lookback + 2:
                return "No Sweep Detected"
            recent = df.iloc[-(lookback + 1):-1]
            prior_high, prior_low = recent['High'].max(), recent['Low'].min()
            last = df.iloc[-1]
            if last['High'] > prior_high and last['Close'] < prior_high:
                return f"🔺 Bearish Liquidity Sweep — swept high ₹{prior_high:,.2f}"
            if last['Low'] < prior_low and last['Close'] > prior_low:
                return f"🔻 Bullish Liquidity Sweep — swept low ₹{prior_low:,.2f}"
            return "No Sweep Detected"
        except Exception:
            return "No Sweep Detected"

    if search_ticker != "-- Select Stock --":
        s_key = instrument_dict.get(search_ticker)
        if s_key:
            with st.spinner(f"Analyzing SMC & Technical Structure for {search_ticker}..."):
                s_df = fetch_upstox_history(s_key, access_token, days=400)
                s_quotes = get_live_market_quotes([s_key], access_token)
                if not s_df.empty:
                    s_price = s_quotes.get(s_key, {}).get('last_price', s_df.iloc[-1]['Close']) if s_quotes else s_df.iloc[-1]['Close']
                    atr_series = ta.atr(s_df['High'], s_df['Low'], s_df['Close'], length=14).dropna()
                    if atr_series.empty:
                        st.warning(f"Not enough history to compute ATR for {search_ticker}.")
                    else:
                        s_atr = atr_series.iloc[-1]
                        atr_series_full = ta.atr(s_df['High'], s_df['Low'], s_df['Close'], length=14)

                        highs = s_df['High'].values
                        lows = s_df['Low'].values
                        fvg_status = "No Immediate FVG"
                        if len(s_df) > 3:
                            if lows[-1] > highs[-3]:
                                fvg_status = f"Bullish FVG: ₹{highs[-3]:,.2f} - ₹{lows[-1]:,.2f}"
                            elif highs[-1] < lows[-3]:
                                fvg_status = f"Bearish FVG: ₹{lows[-3]:,.2f} - ₹{highs[-1]:,.2f}"

                        trend_state, structure_event = detect_market_structure(s_df)
                        order_block = detect_order_block(s_df, atr_series_full, s_atr)
                        liquidity_sweep = detect_liquidity_sweep(s_df)
                        weekly_trend = get_weekly_trend(s_df)
                        rs_vs_nifty = relative_strength_vs_nifty(s_df, lookback=min(20, len(s_df) - 1))
                        vol_profile = compute_volume_profile(s_df)

                        smc_bias = "Bullish"
                        if "Bearish" in structure_event:
                            smc_bias = "Bearish"
                        elif "Bullish" in structure_event:
                            smc_bias = "Bullish"
                        elif trend_state.startswith("Bearish"):
                            smc_bias = "Bearish"
                        elif trend_state.startswith("Bullish"):
                            smc_bias = "Bullish"

                        s_multiplier = 1.0 + (lookup_days / 70.0)
                        if smc_bias == "Bullish":
                            s_sl = round(s_price - (1.5 * s_atr), 2)
                            s_tgt = round(s_price + (2.0 * s_atr * s_multiplier), 2)
                        else:
                            s_sl = round(s_price + (1.5 * s_atr), 2)
                            s_tgt = round(s_price - (2.0 * s_atr * s_multiplier), 2)
                        s_return = round(((s_tgt - s_price) / s_price) * 100, 2)

                        st.markdown(f"### Institutional Setup for {search_ticker} — {'🟢 LONG' if smc_bias == 'Bullish' else '🔴 SHORT'} bias")
                        sc1, sc2, sc3, sc4 = st.columns(4)
                        sc1.metric("Live Price", f"₹{s_price:,.2f}")
                        sc2.metric("Target Price", f"₹{s_tgt:,.2f}", f"{s_return:+.2f}%")
                        sc3.metric("Stop Loss", f"₹{s_sl:,.2f}")
                        sc4.metric("RS vs Nifty50 (20d)", f"{rs_vs_nifty:+.2f}%" if rs_vs_nifty is not None else "N/A")

                        sc5, sc6, sc7 = st.columns(3)
                        sc5.metric("Daily FVG", fvg_status)
                        sc6.metric("Structure Trend", trend_state)
                        sc7.metric("Weekly Trend (MTF)", weekly_trend)

                        st.markdown(f"**BOS / CHoCH Event:** {structure_event}")
                        st.markdown(f"**Order Block:** {order_block}")
                        st.markdown(f"**Liquidity Sweep:** {liquidity_sweep}")

                        if vol_profile:
                            vp1, vp2, vp3 = st.columns(3)
                            vp1.metric("Point of Control (POC)", f"₹{vol_profile['poc']:,.2f}")
                            vp2.metric("Value Area High (VAH)", f"₹{vol_profile['vah']:,.2f}")
                            vp3.metric("Value Area Low (VAL)", f"₹{vol_profile['val']:,.2f}")

                        fig = go.Figure(data=[go.Candlestick(
                            x=s_df.index, open=s_df['Open'], high=s_df['High'],
                            low=s_df['Low'], close=s_df['Close'], name=search_ticker
                        )])
                        ema_20 = ta.ema(s_df['Close'], length=20)
                        ema_50 = ta.ema(s_df['Close'], length=50)
                        fig.add_trace(go.Scatter(x=s_df.index, y=ema_20, line=dict(color='#ff9800', width=1.5), name='EMA 20'))
                        fig.add_trace(go.Scatter(x=s_df.index, y=ema_50, line=dict(color='#2962ff', width=1.5), name='EMA 50'))

                        if vol_profile:
                            fig.add_hline(y=vol_profile['poc'], line_dash="solid", line_color="#f5c518", annotation_text="POC", annotation_position="top left")
                            fig.add_hline(y=vol_profile['vah'], line_dash="dot", line_color="#4caf50", annotation_text="VAH", annotation_position="top left")
                            fig.add_hline(y=vol_profile['val'], line_dash="dot", line_color="#ef5350", annotation_text="VAL", annotation_position="top left")

                        fig.update_layout(xaxis_rangeslider_visible=False, height=520, template="plotly_dark", paper_bgcolor="#050505", plot_bgcolor="#0a0a0a")
                        st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning(f"Could not retrieve historical data for {search_ticker}.")
    else:
        st.info("Select a stock from the dropdown above to view institutional charts and SMC structure.")

# ==========================================
# TAB 4: AI COPILOT
# ==========================================
elif selected_tab == "AI Copilot":
    st.subheader("AI Quantitative Copilot (Google Gemini)")
    st.markdown("Ask natural language portfolio and trading queries.")

    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Hello! I am your AI Quantitative Copilot. Ask me about any NSE stock, risk metric, or market setup."}]

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]): st.markdown(msg["content"])

    def resolve_tickers_in_prompt(prompt_text, max_tickers=3):
        if not prompt_text or not instrument_dict:
            return []
        tokens = re.findall(r'[A-Za-z][A-Za-z&\-]{1,15}', prompt_text.upper())
        found = []
        for tok in tokens:
            if tok in instrument_dict and tok not in found:
                found.append(tok)
            if len(found) >= max_tickers:
                break
        return found

    def fetch_verified_stock_context(ticker):
        try:
            key = instrument_dict.get(ticker)
            if not key:
                return None
            quotes = get_live_market_quotes([key], access_token)
            price = quotes.get(key, {}).get('last_price') if quotes else None
            hist = fetch_upstox_history(key, access_token, days=120)
            if hist.empty:
                if price:
                    return f"{ticker}: live price ₹{price:,.2f} (insufficient history for indicators)."
                return f"{ticker}: no live data available right now."
            atr_s = ta.atr(hist['High'], hist['Low'], hist['Close'], length=14).dropna()
            rsi_s = ta.rsi(hist['Close'], length=14).dropna()
            ema50_s = ta.ema(hist['Close'], length=50).dropna()
            last_close = float(hist['Close'].iloc[-1])
            eff_price = price if price else last_close
            atr_val = float(atr_s.iloc[-1]) if not atr_s.empty else None
            rsi_val = float(rsi_s.iloc[-1]) if not rsi_s.empty else None
            ema50_val = float(ema50_s.iloc[-1]) if not ema50_s.empty else None
            trend = "above EMA50 (uptrend bias)" if (ema50_val and eff_price > ema50_val) else ("below EMA50 (downtrend bias)" if ema50_val else "N/A")
            return (
                f"{ticker}: live price ₹{eff_price:,.2f}, "
                f"RSI(14) {round(rsi_val, 1) if rsi_val is not None else 'N/A'}, "
                f"ATR(14) ₹{round(atr_val, 2) if atr_val is not None else 'N/A'}, "
                f"trend {trend}."
            )
        except Exception:
            return f"{ticker}: couldn't fetch live data right now."

    def build_ai_context(prompt_text=""):
        parts = [
            f"Current India VIX: {vix_value:.2f} ({volatility_regime}).",
            f"Market status: {'Open' if MARKET_OPEN else 'Closed'} (IST).",
        ]
        screener_results = st.session_state.get("last_screener_results")
        if screener_results:
            top3 = screener_results[:3]
            summary = "; ".join([f"{s['Ticker']} @ {s['Live Price']} (target {s['Target']}, SL {s['Stop Loss']}, RR {s['Risk:Reward']}, signal strength {s.get('Signal Strength', 'N/A')}/100, historical win rate {s.get('Historical Win Rate', 'N/A')}, conviction {s['Conviction']})" for s in top3])
            parts.append(f"Most recent equities screener top picks: {summary}.")
        heat = st.session_state.get("last_portfolio_heat")
        if heat is not None:
            parts.append(f"Current Portfolio Heat if all screener picks were taken: {heat:.2f}% of capital.")
        option_summary = st.session_state.get("last_option_chain_summary")
        if option_summary:
            pcr_disp = option_summary['pcr'] if option_summary['pcr'] is not None else "N/A"
            max_pain_disp = option_summary['max_pain'] if option_summary['max_pain'] is not None else "N/A"
            parts.append(
                f"Most recent option chain viewed: {option_summary['asset']} spot {option_summary['spot']:.2f}, "
                f"PCR {pcr_disp}, Max Pain {max_pain_disp}, bias {option_summary.get('bias', 'N/A')} "
                f"({'live OI data' if option_summary['live'] else 'no live chain — PCR/Max Pain unavailable'})."
            )
        futures_summary = st.session_state.get("last_futures_summary")
        if futures_summary:
            parts.append(
                f"Most recent futures recommendation: {futures_summary['index']} {futures_summary['symbol']} — "
                f"{futures_summary['direction']} (bias {futures_summary['bias']}), entry ~{futures_summary['entry']:.2f}, "
                f"target ~{futures_summary['target']:.2f}, stop ~{futures_summary['stop']:.2f}, {futures_summary['lots']} lot(s)."
            )
        mf_summary = st.session_state.get("last_mf_top_picks")
        if mf_summary:
            top_names = "; ".join([f"{t['Scheme']} ({t['3Y CAGR']} 3Y CAGR)" for t in mf_summary["top"]])
            parts.append(f"Most recent mutual fund top picks ({mf_summary['category']}): {top_names}.")

        mentioned_tickers = resolve_tickers_in_prompt(prompt_text)
        if mentioned_tickers:
            verified_lines = [fetch_verified_stock_context(t) for t in mentioned_tickers]
            verified_lines = [v for v in verified_lines if v]
            if verified_lines:
                parts.append(
                    "VERIFIED CURRENT DATA (fetched just now for ticker(s) named in this question — "
                    "prefer this over any stale info in the summaries above for these names): "
                    + " ".join(verified_lines)
                )
        return " ".join(parts)

    GEMINI_MODEL_CANDIDATES = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"]

    def stream_gemini_response(api_key, context_str, prompt):
        last_error = None
        for model_name in GEMINI_MODEL_CANDIDATES:
            try:
                if GEMINI_SDK == "google.genai":
                    client = genai.Client(api_key=api_key)
                    try:
                        from google.genai import types as genai_types
                        config = genai_types.GenerateContentConfig(
                            system_instruction=context_str,
                            thinking_config=genai_types.ThinkingConfig(thinking_level="medium"),
                        )
                    except Exception:
                        config = {"system_instruction": context_str}
                    stream = client.models.generate_content_stream(
                        model=model_name,
                        contents=prompt,
                        config=config,
                    )
                    got_any = False
                    for chunk in stream:
                        text = getattr(chunk, "text", None)
                        if text:
                            got_any = True
                            yield text
                    if got_any:
                        return
                else:
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel(model_name, system_instruction=context_str)
                    response = model.generate_content(prompt, stream=True)
                    got_any = False
                    for chunk in response:
                        if getattr(chunk, "text", None):
                            got_any = True
                            yield chunk.text
                    if got_any:
                        return
            except Exception as e:
                last_error = e
                continue
        if last_error is not None:
            raise last_error

    if prompt := st.chat_input("Ask your investment query...", key="copilot_chat_input"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)

        with st.chat_message("assistant"):
            if not GEMINI_AVAILABLE:
                final_response = "Gemini SDK Missing: run `pip install google-genai` or `pip install google-generativeai`."
                st.markdown(final_response)
            elif gemini_api_key:
                try:
                    context_str = build_ai_context(prompt)
                    try:
                        full_text = st.write_stream(stream_gemini_response(gemini_api_key, context_str, prompt))
                    except AttributeError:
                        placeholder = st.empty()
                        full_text = ""
                        for chunk_text in stream_gemini_response(gemini_api_key, context_str, prompt):
                            full_text += chunk_text
                            placeholder.markdown(full_text)
                    final_response = f"**Gemini Analysis:**\n\n{full_text}"
                except Exception as e:
                    final_response = f"Gemini Error: {str(e)}"
                    st.markdown(final_response)
            else:
                final_response = "Gemini Key Missing: Please enter your key in the sidebar."
                st.markdown(final_response)

            st.session_state.messages.append({"role": "assistant", "content": final_response})