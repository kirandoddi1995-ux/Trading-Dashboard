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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    sector TEXT NOT NULL,
                    capital_deployed REAL NOT NULL,
                    added_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS option_signals (
                    signal_id TEXT PRIMARY KEY,
                    underlying TEXT NOT NULL,
                    expiry TEXT NOT NULL,
                    analysis_date TEXT NOT NULL,
                    signal_generated_at TEXT NOT NULL,
                    dte INTEGER,
                    direction TEXT NOT NULL,
                    strike REAL,
                    entry REAL,
                    target REAL,
                    stop REAL,
                    risk_reward REAL,
                    confidence TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_underlying_expiry ON option_signals(underlying, expiry, status)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS technical_snapshots_scalar_UNUSED (
                    -- RENAMED and marked UNUSED per explicit instruction: this table
                    -- was built as a prototype scalar-only cache, then found (before
                    -- activation) to be structurally insufficient — Trend/Volume
                    -- Quality Score and the False Breakout Filter need full historical
                    -- SERIES (252-day percentile windows, N-bars-ago comparisons), not
                    -- just today's scalar value. Nothing reads or writes this table.
                    -- It remains only so a future, correctly-designed historical-
                    -- source-series cache can reuse this migration slot cleanly.
                    -- DO NOT wire this into production without a redesign.
                    instrument_key TEXT PRIMARY KEY,
                    ticker TEXT NOT NULL,
                    snapshot_date TEXT NOT NULL,
                    last_close REAL,
                    ema20 REAL, ema50 REAL, ema200 REAL,
                    adx REAL, atr REAL,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()
        finally:
            conn.close()


_ensure_cache_schema()


def _serialize_history(instrument_key, df, db_path=DEFAULT_DB_PATH):
    if df is None or df.empty:
        return 0
    # schema already guaranteed by the module-level _ensure_cache_schema() call
    # at startup — removed the redundant per-call re-check, which was opening an
    # extra connection+lock on every single cache read/write and contributing
    # to 'database is locked' errors under concurrent scan load.
    rows = []
    for idx, row in df.iterrows():
        try:
            dt = pd.Timestamp(idx).tz_localize(None).isoformat()
        except Exception as e:
            LOGGER.debug("Suppressed exception: %s", e)
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
        # Small retry for SQLite's inherent single-writer limitation: even with
        # the redundant schema-check connections removed above, several
        # concurrent scan_workers (up to 12) can still legitimately collide
        # writing to the same file at once. busy_timeout=30000 already makes
        # SQLite itself wait before raising — this adds a couple of short,
        # cheap retries on top for the rare case that's still not enough,
        # rather than dropping the write and falling back to possibly-stale
        # cached data on the first collision.
        last_exc = None
        for attempt in range(3):
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
                last_exc = None
                break
            except sqlite3.OperationalError as e:
                last_exc = e
                if "locked" in str(e).lower() and attempt < 2:
                    time.sleep(0.3 * (attempt + 1))
                    continue
                raise
        if last_exc is not None:
            raise last_exc
    finally:
        conn.close()
    return len(rows)


def _read_cached_history(instrument_key, days, db_path=DEFAULT_DB_PATH):
    # schema already guaranteed by the module-level _ensure_cache_schema() call
    # at startup — removed the redundant per-call re-check, which was opening an
    # extra connection+lock on every single cache read/write and contributing
    # to 'database is locked' errors under concurrent scan load.
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
    df["Date"] = normalize_market_timestamp_series(df["Date"])  # defensive — write path already strips tz, this guards older/edge-case rows too
    df = df.dropna(subset=["Date"]).set_index("Date")
    return df


def _cache_last_sync_date(instrument_key, db_path=DEFAULT_DB_PATH):
    # schema already guaranteed by the module-level _ensure_cache_schema() call
    # at startup — removed the redundant per-call re-check, which was opening an
    # extra connection+lock on every single cache read/write and contributing
    # to 'database is locked' errors under concurrent scan load.
    conn = _cache_connect(db_path)
    try:
        row = conn.execute("SELECT last_sync_date FROM sync_meta WHERE instrument_key = ?", (instrument_key,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def get_cached_history(instrument_key, token, days=365, fetch_fn=None, db_path=DEFAULT_DB_PATH):
    cached = _read_cached_history(instrument_key, days, db_path)
    today_date = datetime.datetime.now(IST).date()
    today = today_date.isoformat()
    sync_date = _cache_last_sync_date(instrument_key, db_path)

    required_rows = min(max(int(days * 0.55), 60), int(days))
    if sync_date == today and len(cached) >= required_rows:
        return cached

    if fetch_fn is None:
        return cached

    # SURGICAL INCREMENTAL-REFRESH FIX: previously this branch always
    # requested the FULL `days` window from fetch_fn on every refresh, even
    # when the cache already holds most of that history and only needs a
    # small trailing gap filled (e.g. today's/this week's new bars). Now
    # requests only the missing gap when it's safe to do so, falling back to
    # the exact previous full-window behavior whenever that safety condition
    # isn't met — correctness takes priority over the optimization.
    #
    # "Safe" means BOTH:
    #   1. The cache has sufficient DEPTH already (its earliest date reaches
    #      back far enough to cover the requested `days` window on its own —
    #      if not, this is a depth shortfall, not a recency gap, and only a
    #      full fetch can fix it).
    #   2. The gap between the cache's latest date and today is small enough
    #      (<=30 calendar days) that an incremental fetch is clearly cheaper
    #      than a full one, and unlikely to be masking a deeper cache
    #      corruption/staleness issue that deserves a full refresh instead.
    incremental_fetch_days = None
    if not cached.empty:
        try:
            earliest_cached = cached.index.min().date()
            latest_cached = cached.index.max().date()
            required_earliest = today_date - datetime.timedelta(days=int(days))
            has_sufficient_depth = earliest_cached <= required_earliest + datetime.timedelta(days=15)  # small tolerance for the day cache started
            gap_calendar_days = (today_date - latest_cached).days

            if has_sufficient_depth and 0 < gap_calendar_days <= 30:
                # Small overlap buffer (+5 days) so the upsert can safely
                # re-confirm the boundary rather than risk a hairline gap.
                incremental_fetch_days = gap_calendar_days + 5
        except Exception as e:
            LOGGER.debug("Suppressed exception: %s", e)
            incremental_fetch_days = None  # any uncertainty -> fall back to full fetch below

    fetch_days = incremental_fetch_days if incremental_fetch_days is not None else days

    try:
        fresh = fetch_fn(instrument_key, token, days=fetch_days)
        if fresh is not None and not fresh.empty:
            _serialize_history(instrument_key, fresh, db_path)
            # Always re-read the FULL required window from the cache after
            # writing — whether the fetch was incremental or full, the
            # returned dataframe has the identical shape/contract either way,
            # since _serialize_history's upsert already merges the new rows
            # in with everything previously cached.
            return _read_cached_history(instrument_key, days, db_path)
    except Exception as exc:
        LOGGER.warning("Historical fetch failed for %s: %s", instrument_key, exc)
    return cached


def get_avg_volumes_batched(db_path, keys_list, lookback=20):
    """Batched SQLite volume engine: fetches 20-day average volume for all instruments in one query."""
    if not keys_list:
        return {}
    # schema already guaranteed by the module-level _ensure_cache_schema() call
    # at startup — removed the redundant per-call re-check, which was opening an
    # extra connection+lock on every single cache read/write and contributing
    # to 'database is locked' errors under concurrent scan load.
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
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
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
    # schema already guaranteed by the module-level _ensure_cache_schema() call
    # at startup — removed the redundant per-call re-check, which was opening an
    # extra connection+lock on every single cache read/write and contributing
    # to 'database is locked' errors under concurrent scan load.
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
    # schema already guaranteed by the module-level _ensure_cache_schema() call
    # at startup — removed the redundant per-call re-check, which was opening an
    # extra connection+lock on every single cache read/write and contributing
    # to 'database is locked' errors under concurrent scan load.
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
                except Exception as e:
                    LOGGER.debug("Suppressed exception: %s", e)
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


# ==========================================
# PORTFOLIO POSITIONS & SECTOR EXPOSURE
# ==========================================
def add_position(ticker, capital_deployed, db_path=DEFAULT_DB_PATH):
    conn = _cache_connect(db_path)
    try:
        conn.execute(
            "INSERT INTO positions (ticker, sector, capital_deployed, added_at) VALUES (?, ?, ?, ?)",
            (ticker.upper(), get_ticker_sector(ticker), float(capital_deployed),
             datetime.datetime.now(IST).isoformat())
        )
        conn.commit()
    finally:
        conn.close()


def remove_position(position_id, db_path=DEFAULT_DB_PATH):
    conn = _cache_connect(db_path)
    try:
        conn.execute("DELETE FROM positions WHERE id = ?", (position_id,))
        conn.commit()
    finally:
        conn.close()


def get_positions_df(db_path=DEFAULT_DB_PATH):
    conn = _cache_connect(db_path)
    try:
        df = pd.read_sql_query("SELECT id, ticker, sector, capital_deployed, added_at FROM positions ORDER BY added_at DESC", conn)
        return df
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
        return pd.DataFrame(columns=["id", "ticker", "sector", "capital_deployed", "added_at"])
    finally:
        conn.close()


def get_sector_exposure(db_path=DEFAULT_DB_PATH):
    """Returns {sector: total_capital_deployed} across all tracked positions."""
    df = get_positions_df(db_path)
    if df.empty:
        return {}
    return df.groupby("sector")["capital_deployed"].sum().to_dict()


def check_sector_exposure_warning(ticker, total_capital, max_sector_pct, db_path=DEFAULT_DB_PATH):
    """Returns a warning string if adding a new position in `ticker`'s sector
    would push that sector's total exposure over max_sector_pct of total_capital,
    or None if there's no concern (no existing exposure data, or within limits)."""
    if total_capital <= 0:
        return None
    sector = get_ticker_sector(ticker)
    exposure = get_sector_exposure(db_path)
    current_sector_capital = exposure.get(sector, 0.0)
    current_pct = (current_sector_capital / total_capital) * 100.0
    if current_pct >= max_sector_pct:
        return (f"⚠️ Sector Exposure Warning: you already have ~{current_pct:.1f}% of your capital in "
                f"**{sector}** (your limit is {max_sector_pct:.0f}%) — consider skipping or trimming before adding more here.")
    return None


# ==========================================
# STAGE 2B — OPTIONS SIGNAL LIFECYCLE
# ==========================================
ACTIVE_LIKE_STATUSES = ("NEW", "ACTIVE", "REVALIDATED")

def get_active_signal(underlying, expiry, db_path=DEFAULT_DB_PATH):
    """Most recent signal for this (underlying, expiry) still in an
    active-like status, or None if there isn't one."""
    conn = _cache_connect(db_path)
    try:
        placeholders = ",".join("?" * len(ACTIVE_LIKE_STATUSES))
        row = conn.execute(
            f"SELECT * FROM option_signals WHERE underlying=? AND expiry=? AND status IN ({placeholders}) "
            f"ORDER BY created_at DESC LIMIT 1",
            (underlying, expiry, *ACTIVE_LIKE_STATUSES)
        ).fetchone()
        if not row:
            return None
        cols = [d[0] for d in conn.execute("SELECT * FROM option_signals LIMIT 0").description]
        return dict(zip(cols, row))
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
        return None
    finally:
        conn.close()


def record_new_signal(underlying, expiry, analysis_date, signal_generated_at, dte, direction,
                       strike, entry, target, stop, risk_reward, confidence, db_path=DEFAULT_DB_PATH):
    """Inserts a genuinely new signal row with status=NEW."""
    now = datetime.datetime.now(IST).isoformat()
    signal_id = f"{underlying}_{expiry}_{strike}_{direction}_{now}"
    conn = _cache_connect(db_path)
    try:
        conn.execute(
            "INSERT INTO option_signals (signal_id, underlying, expiry, analysis_date, signal_generated_at, "
            "dte, direction, strike, entry, target, stop, risk_reward, confidence, status, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (signal_id, underlying, expiry, analysis_date, signal_generated_at, dte, direction, strike,
             entry, target, stop, risk_reward, confidence, "NEW", now, now)
        )
        conn.commit()
        return signal_id
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
        return None
    finally:
        conn.close()


def update_signal_status(signal_id, new_status, db_path=DEFAULT_DB_PATH, **refresh_fields):
    """Updates an existing signal's status in place (used for REVALIDATED,
    INVALIDATED, EXIT_TARGET, EXIT_STOP, EXPIRED transitions) — never inserts
    a duplicate row for the same underlying+expiry+strike+direction signal."""
    if not signal_id:
        return
    conn = _cache_connect(db_path)
    try:
        now = datetime.datetime.now(IST).isoformat()
        set_clauses = ["status=?", "updated_at=?"]
        params = [new_status, now]
        for field, value in refresh_fields.items():
            if field in ("entry", "target", "stop", "risk_reward", "dte", "signal_generated_at", "analysis_date"):
                set_clauses.append(f"{field}=?")
                params.append(value)
        params.append(signal_id)
        conn.execute(f"UPDATE option_signals SET {', '.join(set_clauses)} WHERE signal_id=?", params)
        conn.commit()
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
    finally:
        conn.close()


def get_signal_history(underlying, expiry, db_path=DEFAULT_DB_PATH, limit=20):
    conn = _cache_connect(db_path)
    try:
        rows = conn.execute(
            "SELECT analysis_date, direction, strike, entry, status FROM option_signals "
            "WHERE underlying=? AND expiry=? ORDER BY created_at DESC LIMIT ?",
            (underlying, expiry, limit)
        ).fetchall()
        return [{"Date": r[0], "Signal": f"{r[1]} {r[2]}", "Entry": r[3], "Status": r[4]} for r in rows]
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
        return []
    finally:
        conn.close()


TECHNICAL_SNAPSHOT_SCHEMA_VERSION = 1

def get_technical_snapshot_UNUSED(instrument_key, today_str, db_path=DEFAULT_DB_PATH):
    """Returns cached indicator values for `instrument_key` ONLY if they were
    computed today (snapshot_date == today_str) and match the current schema
    version — otherwise returns None, meaning evaluate_stock must compute
    fresh (exactly as it always has). This is the single freshness guard that
    prevents a stale snapshot from ever silently driving today's decision."""
    conn = _cache_connect(db_path)
    try:
        row = conn.execute(
            "SELECT last_close, ema20, ema50, ema200, adx, atr FROM technical_snapshots_scalar_UNUSED "
            "WHERE instrument_key=? AND snapshot_date=? AND schema_version=?",
            (instrument_key, today_str, TECHNICAL_SNAPSHOT_SCHEMA_VERSION)
        ).fetchone()
        if not row:
            return None
        return {"last_close": row[0], "ema20": row[1], "ema50": row[2], "ema200": row[3], "adx": row[4], "atr": row[5]}
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
        return None
    finally:
        conn.close()


def write_technical_snapshot_UNUSED(instrument_key, ticker, today_str, last_close, ema20, ema50, ema200, adx, atr, db_path=DEFAULT_DB_PATH):
    conn = _cache_connect(db_path)
    try:
        now = datetime.datetime.now(IST).isoformat()
        conn.execute(
            "INSERT INTO technical_snapshots_scalar_UNUSED (instrument_key, ticker, snapshot_date, last_close, ema20, ema50, ema200, "
            "adx, atr, schema_version, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(instrument_key) DO UPDATE SET ticker=excluded.ticker, snapshot_date=excluded.snapshot_date, "
            "last_close=excluded.last_close, ema20=excluded.ema20, ema50=excluded.ema50, ema200=excluded.ema200, "
            "adx=excluded.adx, atr=excluded.atr, schema_version=excluded.schema_version, updated_at=excluded.updated_at",
            (instrument_key, ticker, today_str, last_close, ema20, ema50, ema200, adx, atr, TECHNICAL_SNAPSHOT_SCHEMA_VERSION, now)
        )
        conn.commit()
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
    finally:
        conn.close()


def evaluate_signal_lifecycle(underlying, expiry, analysis_date, dte, current_pick, current_live_premium_lookup, db_path=DEFAULT_DB_PATH):
    """Orchestrates the daily NEW/REVALIDATED/INVALIDATED/NEW-replace decision,
    plus an intraday target/stop check — WITHOUT touching generate_ranked_
    recommendations or build_option_recommendation, which are called exactly
    as before, unchanged, by the caller. This function only interprets their
    already-computed output against the persisted previous signal.

    current_pick: the top recommendation dict from generate_ranked_recommendations
                  (or None if recommendations is empty / NO TRADE this evaluation).
    current_live_premium_lookup: callable(strike, direction) -> float or None,
                  used ONLY for the target/stop check — if unavailable, status
                  is left as-is rather than fabricating an exit (per instruction).

    Returns (status_label, active_signal_row_or_None).
    """
    prev = get_active_signal(underlying, expiry, db_path)

    # Expiry check takes precedence over everything else.
    if dte is not None and dte <= 0:
        if prev:
            update_signal_status(prev["signal_id"], "EXPIRED", db_path)
        return "NO_TRADE", None

    # Intraday target/stop check on an existing active-like signal, using
    # live premium for that EXACT contract if we have it this evaluation.
    if prev and prev["status"] in ACTIVE_LIKE_STATUSES:
        try:
            live_premium = current_live_premium_lookup(prev["strike"], prev["direction"])
        except Exception:
            live_premium = None
        if live_premium is not None:
            if prev["direction"] and live_premium >= (prev["target"] or float("inf")):
                update_signal_status(prev["signal_id"], "EXIT_TARGET", db_path)
                return "EXIT_TARGET", prev
            if prev["direction"] and live_premium <= (prev["stop"] or float("-inf")):
                update_signal_status(prev["signal_id"], "EXIT_STOP", db_path)
                return "EXIT_STOP", prev

    if not current_pick:
        # Fresh evaluation says NO TRADE — close out any previous active signal.
        if prev and prev["status"] in ACTIVE_LIKE_STATUSES:
            update_signal_status(prev["signal_id"], "INVALIDATED", db_path)
        return "NO_TRADE", None

    same_setup = (
        prev is not None and prev["status"] in ACTIVE_LIKE_STATUSES and
        float(prev["strike"]) == float(current_pick["strike"]) and
        prev["direction"] == current_pick["side"]
    )

    if same_setup:
        # Same setup, independently reconfirmed by fresh data — REVALIDATED,
        # updated in place (not a duplicate row), refreshed to current values.
        update_signal_status(
            prev["signal_id"], "REVALIDATED", db_path,
            entry=current_pick["premium"], target=current_pick["target_premium"],
            stop=current_pick["stop_premium"], risk_reward=current_pick["reward_risk"],
            dte=dte, signal_generated_at=current_pick.get("signal_generated_at"),
            analysis_date=analysis_date,
        )
        refreshed = get_active_signal(underlying, expiry, db_path)
        return "REVALIDATED", refreshed
    else:
        # Setup changed materially (different strike and/or direction), or
        # there was no previous active signal — close the old one if any,
        # open a genuinely new one.
        if prev and prev["status"] in ACTIVE_LIKE_STATUSES:
            update_signal_status(prev["signal_id"], "INVALIDATED", db_path)
        record_new_signal(
            underlying, expiry, analysis_date, current_pick.get("signal_generated_at"), dte,
            current_pick["side"], current_pick["strike"], current_pick["premium"],
            current_pick["target_premium"], current_pick["stop_premium"],
            current_pick["reward_risk"], current_pick.get("bias"), db_path,
        )
        new_row = get_active_signal(underlying, expiry, db_path)
        return "NEW", new_row


def compute_relative_strength_pct(price_now, price_prev, benchmark_pct):
    """Single source of truth for the RS-vs-benchmark formula used across F&O
    scanning, Sector Strength, and (soon) any future RS-based feature. Was
    previously reimplemented independently 5 separate times across the file —
    consolidated here so a future fix only needs to happen once. Not cached:
    it's a trivial in-memory arithmetic operation, caching would add overhead
    for no benefit."""
    try:
        price_now, price_prev = float(price_now), float(price_prev)
        if price_now <= 0 or price_prev <= 0:
            return None, None
        momentum_pct = (price_now / price_prev - 1.0) * 100.0
        rel_strength = (momentum_pct - benchmark_pct) if benchmark_pct is not None else None
        return momentum_pct, rel_strength
    except Exception:
        return None, None


@st.cache_data(ttl=60, show_spinner=False)
def compute_sector_strength(token):
    """Aggregates Relative Strength (vs NIFTY) across the liquid stock universe,
    grouped by sector via NSE_SECTOR_MAP, to show which sectors are genuinely
    LEADING or LAGGING the market right now — not just which single stocks moved
    most. Reuses the same RS methodology already built for F&O auto-scan.
    Falls back to the last completed session if live quotes are unavailable
    (market closed / feed warming up). Returns (rows, used_fallback) where rows
    is a list of {"sector", "avg_rs", "stock_count"} sorted strongest-first."""
    NIFTY_KEY = "NSE_INDEX|Nifty 50"
    tickers = [t for t in LIQUID_CORE_TICKERS if t in instrument_dict]
    keys = {t: instrument_dict[t] for t in tickers}
    quote_keys = list(keys.values()) + [NIFTY_KEY]
    quotes = get_live_scan_market_data(quote_keys, token)

    nifty_pct = None
    nq = quotes.get(NIFTY_KEY)
    if nq:
        n_ltp = float(nq.get("last_price") or 0.0)
        n_prev = float((nq.get("ohlc") or {}).get("close") or 0.0)
        if n_ltp > 0 and n_prev > 0:
            nifty_pct = (n_ltp / n_prev - 1.0) * 100.0

    stock_rs = {}
    if nifty_pct is not None:
        for ticker, key in keys.items():
            q = quotes.get(key)
            if not q:
                continue
            try:
                ltp = float(q.get("last_price") or 0.0)
                prev_close = float((q.get("ohlc") or {}).get("close") or 0.0)
                momentum_pct, rel_strength = compute_relative_strength_pct(ltp, prev_close, nifty_pct)
                if momentum_pct is None:
                    continue
                stock_rs[ticker] = rel_strength if rel_strength is not None else momentum_pct
            except Exception as e:
                LOGGER.debug("Suppressed exception: %s", e)
                continue

    used_fallback = False
    if not stock_rs:
        used_fallback = True
        nifty_df = fetch_upstox_history(NIFTY_KEY, token, days=5)
        nifty_pct_fb = None
        if not nifty_df.empty and len(nifty_df) >= 2:
            n_last, n_prev = float(nifty_df.iloc[-1]['Close']), float(nifty_df.iloc[-2]['Close'])
            if n_prev > 0:
                nifty_pct_fb = (n_last / n_prev - 1.0) * 100.0

        def _fetch_one(ticker):
            key = keys.get(ticker)
            if not key:
                return None
            df = fetch_upstox_history(key, token, days=5)
            if df.empty or len(df) < 2:
                return None
            last_close, prev_close = float(df.iloc[-1]['Close']), float(df.iloc[-2]['Close'])
            if prev_close <= 0:
                return None
            return ticker, (last_close / prev_close - 1.0) * 100.0

        if nifty_pct_fb is not None:
            with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
                for result in executor.map(_fetch_one, tickers):
                    if result:
                        t, m = result
                        stock_rs[t] = m - nifty_pct_fb

    if not stock_rs:
        return [], used_fallback

    sector_rs_lists = {}
    for ticker, rs in stock_rs.items():
        sector = get_ticker_sector(ticker)
        sector_rs_lists.setdefault(sector, []).append(rs)

    rows = [
        {"sector": sector, "avg_rs": round(sum(rs_list) / len(rs_list), 2), "stock_count": len(rs_list)}
        for sector, rs_list in sector_rs_lists.items()
    ]
    rows.sort(key=lambda r: r["avg_rs"], reverse=True)
    return rows, used_fallback


@st.cache_data(ttl=300, show_spinner=False)
def compute_market_breadth(token):
    """Advance/Decline, % of liquid universe above 20/50/200 DMA, and new 52-week
    highs/lows across a large/mid-cap liquid stock sample (NOT the full NSE
    universe — see caller for the honest label on this). Reuses the SAME
    cached-history pattern already used by the equities screener.

    Data-staleness fix: Upstox's daily-candle API does not include today's
    still-forming candle during market hours, which would otherwise make this
    silently reflect YESTERDAY's advance/decline all session. Patches in each
    ticker's live quote via prepare_live_daily_bar (same fix already proven for
    the market bias engine) so breadth reflects today's actual session."""
    tickers = [t for t in LIQUID_CORE_TICKERS if t in instrument_dict]
    keys = {t: instrument_dict[t] for t in tickers}
    live_quotes = get_live_scan_market_data(list(keys.values()), token)

    def _one(ticker):
        key = keys.get(ticker)
        if not key:
            return None
        try:
            df = get_cached_history(key, token, days=280, fetch_fn=_fetch_upstox_history_impl)
        except Exception as e:
            LOGGER.debug("Suppressed exception: %s", e)
            return None
        if df is None or df.empty or len(df) < 20:
            return None
        quote = live_quotes.get(key)
        if quote:
            df = prepare_live_daily_bar(df, quote)
        last_close = float(df['Close'].iloc[-1])
        prev_close = float(df['Close'].iloc[-2]) if len(df) >= 2 else last_close
        dma20 = float(df['Close'].tail(20).mean())
        dma50 = float(df['Close'].tail(50).mean()) if len(df) >= 50 else None
        dma200 = float(df['Close'].tail(200).mean()) if len(df) >= 200 else None
        lookback = df['Close'].tail(252)
        has_full_year = len(df) >= 200  # only call it "52-week" if we actually have close to a year of data
        high_52w, low_52w = float(lookback.max()), float(lookback.min())
        return {
            "advancing": last_close > prev_close,
            "above_20dma": last_close > dma20,
            "above_50dma": (last_close > dma50) if dma50 is not None else None,
            "above_200dma": (last_close > dma200) if dma200 is not None else None,
            "new_high": has_full_year and high_52w > 0 and last_close >= high_52w * 0.999,
            "new_low": has_full_year and low_52w > 0 and last_close <= low_52w * 1.001,
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = [r for r in executor.map(_one, tickers) if r]

    total = len(results)
    if total == 0:
        return None

    advances = sum(1 for r in results if r["advancing"])
    above20 = sum(1 for r in results if r["above_20dma"])
    above50_vals = [r["above_50dma"] for r in results if r["above_50dma"] is not None]
    above200_vals = [r["above_200dma"] for r in results if r["above_200dma"] is not None]
    above50 = sum(1 for v in above50_vals if v)
    above200 = sum(1 for v in above200_vals if v)
    new_highs = sum(1 for r in results if r["new_high"])
    new_lows = sum(1 for r in results if r["new_low"])

    pct_above_50 = (above50 / len(above50_vals) * 100.0) if above50_vals else None
    pct_above_200 = (above200 / len(above200_vals) * 100.0) if above200_vals else None

    # Simple weighted composite (0-100): breadth is "healthy" when most stocks are
    # advancing AND trading above their key moving averages, not just a few large caps.
    breadth_score = (advances / total) * 40.0 + (above20 / total) * 20.0
    breadth_score += (pct_above_50 / 100.0 * 20.0) if pct_above_50 is not None else 10.0
    breadth_score += (pct_above_200 / 100.0 * 20.0) if pct_above_200 is not None else 10.0

    return {
        "total_sampled": total, "advances": advances, "declines": total - advances,
        "pct_above_20dma": round(above20 / total * 100.0, 1),
        "pct_above_50dma": round(pct_above_50, 1) if pct_above_50 is not None else None,
        "pct_above_200dma": round(pct_above_200, 1) if pct_above_200 is not None else None,
        "new_highs": new_highs, "new_lows": new_lows,
        "breadth_score": round(breadth_score, 1),
    }


def _percentile_rank(series, current_value):
    """What percentile `current_value` sits at within `series`'s own recent
    history (0-100). This is what actually makes a threshold adaptive: a VIX
    of 22 means something different in a calm year vs a volatile one, and
    percentile rank adjusts for that automatically instead of hardcoding a
    fixed number that only fits 'typical' conditions."""
    try:
        clean = series.dropna()
        if clean.empty or current_value is None or len(clean) < 20:
            return None
        return float((clean < current_value).mean() * 100.0)
    except Exception:
        return None


def compute_trend_quality_score(df):
    """PHASE 1 — Trend Quality Engine. Real, inspectable formula, not a fake
    AI score. Requires df to already have Close/High/Low/EMA_20/EMA_50/ADX/ATR
    columns (matches the exact columns already computed in the equities
    screener — no new indicators, no duplicate calculation of what's already
    there when called from that path).

    Components (each 0-100, weighted):
    1. EMA-20 slope (20%) — 6-bar % change in EMA20, linearly mapped so a
       +/-5% slope over 6 bars maps to the 0-100 extremes. This is a disclosed
       linear transform of a real computed value, not a trained/fitted score.
    2. Higher-High count (15%) — % of the last 10 bars where High > prior High.
    3. Higher-Low count (15%) — % of the last 10 bars where Low > prior Low.
    4. ADX percentile (20%) — real percentile rank vs the stock's own 252-day
       ADX history (reuses _percentile_rank, same adaptive-threshold approach
       as Market Regime).
    5. Trend duration (15%) — consecutive bars price has stayed above EMA_20,
       capped at 20 bars = 100.
    6. Volatility-adjusted trend strength (15%) — EMA slope % divided by
       ATR-as-%-of-price. The same raw % move means more in a low-ATR stock
       than a high-ATR one; this normalizes for that instead of ignoring it.

    Returns {"score": 0-100, "label": str, ...component breakdown...} or None
    if there isn't enough history to compute meaningfully."""
    try:
        required_cols = {'Close', 'High', 'Low', 'EMA_20', 'ATR', 'ADX'}
        if df is None or df.empty or not required_cols.issubset(df.columns) or len(df) < 30:
            return None
        d = df.dropna(subset=['EMA_20', 'ATR', 'ADX'])
        if len(d) < 30:
            return None

        # 1. EMA slope
        ema_now, ema_prev = float(d['EMA_20'].iloc[-1]), float(d['EMA_20'].iloc[-6])
        slope_pct = (ema_now / ema_prev - 1.0) * 100.0 if ema_prev else 0.0
        slope_score = min(100.0, max(0.0, 50.0 + slope_pct * 10.0))

        # 2 & 3. Higher highs / higher lows over the last 10 bars (vectorized)
        recent = d.tail(11)  # need 11 to get 10 comparisons
        hh_count = int((recent['High'].diff().dropna() > 0).sum())
        hl_count = int((recent['Low'].diff().dropna() > 0).sum())
        hh_score = min(100.0, hh_count / 10.0 * 100.0)
        hl_score = min(100.0, hl_count / 10.0 * 100.0)

        # 4. ADX percentile — real, adaptive, same methodology as Market Regime
        adx_val = float(d['ADX'].iloc[-1])
        adx_percentile = _percentile_rank(d['ADX'].tail(252), adx_val)
        adx_score = adx_percentile if adx_percentile is not None else 50.0

        # 5. Trend duration: consecutive bars close has stayed above EMA_20
        above_ema = (d['Close'] > d['EMA_20']).values
        duration = 0
        for v in above_ema[::-1]:
            if not v:
                break
            duration += 1
        duration_score = min(100.0, duration / 20.0 * 100.0)

        # 6. Volatility-adjusted trend strength
        last_close = float(d['Close'].iloc[-1])
        atr_val = float(d['ATR'].iloc[-1])
        atr_pct_of_price = (atr_val / last_close * 100.0) if last_close > 0 else None
        vol_adj_strength = (slope_pct / atr_pct_of_price) if atr_pct_of_price and atr_pct_of_price > 0 else 0.0
        vol_adj_score = min(100.0, max(0.0, 50.0 + vol_adj_strength * 15.0))

        composite = (
            slope_score * 0.20 + hh_score * 0.15 + hl_score * 0.15 +
            adx_score * 0.20 + duration_score * 0.15 + vol_adj_score * 0.15
        )
        composite = round(composite, 1)

        if composite >= 80:
            label = "Excellent Trend"
        elif composite >= 65:
            label = "Strong Trend"
        elif composite >= 45:
            label = "Average Trend"
        else:
            label = "Weak Trend"

        return {
            "score": composite, "label": label,
            "ema_slope_pct": round(slope_pct, 2),
            "hh_count": hh_count, "hl_count": hl_count,
            "adx_percentile": round(adx_percentile, 0) if adx_percentile is not None else None,
            "trend_duration_bars": duration,
            "vol_adjusted_strength": round(vol_adj_strength, 2),
        }
    except Exception as exc:
        LOGGER.debug("Trend quality computation failed: %s", exc)
        return None


def compute_volume_quality_score(df):
    """PHASE 2 — Volume Quality Engine. Real formula, reuses the Volume column
    already present in every df computed elsewhere in the app — no new API
    calls, no duplicate volume fetching.

    Components (each 0-100, weighted):
    1. Session-Adjusted RVOL (25%) — see formula below. Corrected in this pass
       to account for what fraction of the trading day has elapsed.
    2. Volume percentile (25%) — real percentile rank vs the stock's own
       252-day volume history.
    3. Volume acceleration (20%) — 5-day average volume vs the PRIOR 5-day
       average volume (is participation actually increasing, not just today).
    4. Volume expansion (15%) — % of the last 5 days with volume higher than
       the day before (consistent expansion vs one noisy spike).
    5. Volume consistency (15%) — inverse coefficient of variation over the
       last 20 days (std/mean) — steady elevated volume scores higher than
       one wild spike surrounded by dead days.

    SESSION-AWARE RVOL — exact formula:
        raw_rvol             = current_volume / avg_volume_20d
        session_adjusted_rvol = min(raw_volume_pace_ratio, 5.0)
        where raw_volume_pace_ratio = raw_rvol / elapsed_session_fraction

    elapsed_session_fraction reuses the EXISTING shared _session_elapsed_fraction()
    helper (already used elsewhere in this app for the identical purpose) rather
    than reimplementing it — per explicit reuse requirement. That helper handles:
      - Pre-market (before 9:15 IST): returns a 0.05 floor
      - Market open (just after 9:15): floored at 0.15 minimum, so the first few
        minutes of trading don't produce an artificially explosive ratio (e.g.
        2 minutes of volume compared to a tiny elapsed-fraction denominator)
      - Mid-session: proportional elapsed/total time
      - At/after close (15:30 IST): returns 1.0 (no adjustment needed — the
        day's volume IS the full day's volume by then)

    WHY THIS MATTERS (bug found in prior pass): comparing partial-day volume-so-far
    directly against a 20-day average of COMPLETE days understates RVOL for
    anything evaluated before market close — e.g. at 11am (~30% of the session
    elapsed), even a genuinely strong volume day would show raw RVOL well below
    1.0x just because 70% of the day's volume hasn't happened yet, wrongly
    reading as weak participation.

    LOOK-AHEAD BIAS CHECK: elapsed_session_fraction uses only the current wall-
    clock time (datetime.now) and current_volume uses only data already patched
    into df up to and including right now (via prepare_live_daily_bar upstream,
    confirmed in this pass to include Volume, not just price) — no future data
    of any kind is used. Session-adjustment is applied ONLY when the market is
    genuinely open AND df's last row is dated today; otherwise (market closed,
    weekend, stale/unpatched data) it falls back to the plain, unadjusted
    ratio, since a fraction-of-day adjustment is meaningless on a day that's
    already fully complete.

    Returns {"score": 0-100, "label": str, "rvol": raw, "session_adjusted_rvol":
    adjusted, ...} or None if insufficient data."""
    try:
        if df is None or df.empty or 'Volume' not in df.columns or len(df) < 30:
            return None
        d = df.dropna(subset=['Volume'])
        if len(d) < 30:
            return None

        current_vol = float(d['Volume'].iloc[-1])
        avg_vol20 = float(d['Volume'].tail(20).mean())

        # 1. RVOL — both raw and session-adjusted, shown separately for comparison.
        raw_rvol = min(current_vol / avg_vol20, 5.0) if avg_vol20 > 0 else 0.0

        session_adjusted_rvol = raw_rvol
        is_session_adjusted = False
        try:
            last_row_is_today = d.index[-1].date() == datetime.datetime.now(IST).date()
        except Exception:
            last_row_is_today = False
        if MARKET_OPEN and last_row_is_today and avg_vol20 > 0:
            elapsed_fraction = _session_elapsed_fraction()
            if elapsed_fraction > 0:
                session_adjusted_rvol = min(current_vol / avg_vol20 / elapsed_fraction, 5.0)
                is_session_adjusted = True

        # Session-adjusted RVOL is the correct number to score on during live
        # market hours (see docstring) — falls back to raw RVOL when adjustment
        # doesn't apply (market closed / stale data), matching the existing
        # volume_pace_ratio's own fallback behavior elsewhere in this app.
        rvol_for_scoring = session_adjusted_rvol
        rvol_score = min(100.0, rvol_for_scoring / 3.0 * 100.0)  # RVOL of 3x+ maps to 100

        # 2. Volume percentile — real, adaptive
        vol_percentile = _percentile_rank(d['Volume'].tail(252), current_vol)
        vol_pct_score = vol_percentile if vol_percentile is not None else 50.0

        # 3. Volume acceleration: recent 5-day avg vs prior 5-day avg
        accel_score = 50.0
        if len(d) >= 10:
            recent5 = float(d['Volume'].tail(5).mean())
            prior5 = float(d['Volume'].iloc[-10:-5].mean())
            if prior5 > 0:
                accel_pct = (recent5 / prior5 - 1.0) * 100.0
                accel_score = min(100.0, max(0.0, 50.0 + accel_pct * 2.0))

        # 4. Volume expansion: consistency of day-over-day increases, not one spike
        last5_diffs = d['Volume'].tail(6).diff().dropna()
        expansion_days = int((last5_diffs > 0).sum())
        expansion_score = min(100.0, expansion_days / 5.0 * 100.0)

        # 5. Volume consistency: inverse coefficient of variation (lower CV = more consistent)
        vol20 = d['Volume'].tail(20)
        cv = float(vol20.std() / vol20.mean()) if vol20.mean() > 0 else 1.0
        consistency_score = min(100.0, max(0.0, 100.0 - cv * 50.0))

        composite = (
            rvol_score * 0.25 + vol_pct_score * 0.25 + accel_score * 0.20 +
            expansion_score * 0.15 + consistency_score * 0.15
        )
        composite = round(composite, 1)

        if composite >= 80:
            label = "Exceptional"
        elif composite >= 65:
            label = "Strong"
        elif composite >= 45:
            label = "Average"
        else:
            label = "Weak"

        return {
            "score": composite, "label": label,
            "rvol": round(raw_rvol, 2),
            "session_adjusted_rvol": round(session_adjusted_rvol, 2),
            "is_session_adjusted": is_session_adjusted,
            "volume_percentile": round(vol_percentile, 0) if vol_percentile is not None else None,
            "expansion_days_of_5": expansion_days,
        }
    except Exception as exc:
        LOGGER.debug("Volume quality computation failed: %s", exc)
        return None


def compute_breakout_quality_score(df, rs_vs_nifty=None, trend_quality=None, volume_quality=None):
    """PHASE 3 — False Breakout Filter, upgraded from binary pass/reject to a
    continuous 0-100 breakout_quality_score. Built by COMPOSING the already-
    validated Trend Quality and Volume Quality engines (Phases 1-2), not
    reimplementing their logic — per explicit reuse requirement, and because
    those two were specifically checked last turn for redundancy against the
    existing scoring system before being trusted as inputs here.

    trend_quality / volume_quality can be passed in pre-computed (the caller
    already computes both per-stock for its own display columns) to avoid
    calling those functions twice on the same df — zero duplicate calculation.

    Components (each 0-100, weighted):
    1. Trend Quality (25%) — from compute_trend_quality_score, reused as-is.
    2. Volume Quality (25%) — from compute_volume_quality_score, reused as-is
       (already includes the session-adjusted RVOL fix from this session).
    3. ATR Expansion (15%) — % change in ATR over the last ~5 bars, mapped to
       0-100. A breakout without expanding volatility behind it is more often
       fake (same principle as the existing binary False Breakout Filter, made
       continuous instead of a hard yes/no).
    4. ADX Strength (20%) — real 252-day percentile rank of current ADX (same
       adaptive methodology as Market Regime and Trend Quality, not a fixed
       threshold).
    5. Relative Strength (15%) — the stock's RS vs NIFTY, normalized with the
       SAME scale already used by the existing scanner composite (_scale(rs,
       -5, 10)) rather than inventing a new, inconsistent normalization range.

    Returns {"score": 0-100, "label": str, ...} or None if insufficient data."""
    try:
        required_cols = {'Close', 'High', 'Low', 'ATR', 'ADX'}
        if df is None or df.empty or not required_cols.issubset(df.columns) or len(df) < 30:
            return None
        d = df.dropna(subset=['ATR', 'ADX'])
        if len(d) < 30:
            return None

        if trend_quality is None:
            trend_quality = compute_trend_quality_score(df)
        if volume_quality is None:
            volume_quality = compute_volume_quality_score(df)
        trend_score_component = trend_quality['score'] if trend_quality else 50.0
        volume_score_component = volume_quality['score'] if volume_quality else 50.0

        # 3. ATR Expansion — continuous version of the existing binary check
        atr_now = float(d['ATR'].iloc[-1])
        atr_expansion_score = 50.0
        if len(d) >= 6:
            atr_prev = float(d['ATR'].iloc[-6])
            if atr_prev > 0:
                atr_change_pct = (atr_now / atr_prev - 1.0) * 100.0
                atr_expansion_score = min(100.0, max(0.0, 50.0 + atr_change_pct * 5.0))

        # 4. ADX Strength — real percentile, same methodology as Market Regime
        adx_val = float(d['ADX'].iloc[-1])
        adx_percentile = _percentile_rank(d['ADX'].tail(252), adx_val)
        adx_strength_score = adx_percentile if adx_percentile is not None else 50.0

        # 5. Relative Strength — reuses the EXACT existing normalization scale
        # already used by the scanner's composite score, for consistency
        # rather than a second, differently-calibrated RS transform.
        rs_score_component = _scale(rs_vs_nifty if rs_vs_nifty is not None else 0.0, -5.0, 10.0)

        composite = (
            trend_score_component * 0.25 + volume_score_component * 0.25 +
            atr_expansion_score * 0.15 + adx_strength_score * 0.20 +
            rs_score_component * 0.15
        )
        composite = round(composite, 1)

        if composite >= 75:
            label = "High-Quality Breakout"
        elif composite >= 55:
            label = "Moderate Breakout"
        elif composite >= 35:
            label = "Weak Breakout"
        else:
            label = "Likely False Breakout"

        return {
            "score": composite, "label": label,
            "trend_component": round(trend_score_component, 1),
            "volume_component": round(volume_score_component, 1),
            "atr_expansion_component": round(atr_expansion_score, 1),
            "adx_strength_component": round(adx_strength_score, 1),
            "rs_component": round(rs_score_component, 1),
        }
    except Exception as exc:
        LOGGER.debug("Breakout quality computation failed: %s", exc)
        return None


@st.cache_data(ttl=300, show_spinner=False)
def compute_market_regime(nifty_df, nifty_quote, vix_df, vix_val, breadth_score):
    """Rule-based (not ML) market regime classifier using NIFTY's own trend (ADX,
    ATR, EMA slope) and India VIX — all data already computed elsewhere in the
    app, just combined here into one read. Honest about what this is: a
    transparent, inspectable set of rules, not a trained model.

    ADAPTIVE THRESHOLDS: classification now uses 252-day rolling PERCENTILES of
    VIX/ADX/ATR against their own recent history, instead of fixed numbers like
    'VIX >= 25'. A fixed threshold doesn't adjust when volatility regimes
    themselves shift over months — percentile rank does, using only real
    historical data already available, no synthetic scoring.

    Data-staleness fix: patches in NIFTY's live quote (same prepare_live_daily_bar
    fix used for market bias and breadth) so this reflects today's session, not
    yesterday's stale closed candle, during live market hours.

    False-confidence fix: regime_score is now literally the ADX percentile
    itself (0-100), not an arbitrary distance formula — a real, inspectable
    number, not a made-up confidence."""
    try:
        if nifty_df is None or nifty_df.empty or len(nifty_df) < 30:
            return None
        if nifty_quote:
            nifty_df = prepare_live_daily_bar(nifty_df, nifty_quote)

        adx_series = ta.adx(nifty_df['High'], nifty_df['Low'], nifty_df['Close'], length=14)
        adx_series = adx_series.iloc[:, 0] if adx_series is not None and not adx_series.empty else pd.Series(dtype=float)
        adx_val = float(adx_series.dropna().iloc[-1]) if not adx_series.dropna().empty else None
        adx_percentile = _percentile_rank(adx_series.tail(252), adx_val)

        atr_series = ta.atr(nifty_df['High'], nifty_df['Low'], nifty_df['Close'], length=14)
        atr_val = float(atr_series.dropna().iloc[-1]) if atr_series is not None and not atr_series.dropna().empty else None
        atr_percentile = _percentile_rank(atr_series.tail(252), atr_val) if atr_series is not None else None

        vix_percentile = None
        if vix_df is not None and not vix_df.empty and vix_val is not None and len(vix_df) >= 20:
            vix_percentile = _percentile_rank(vix_df['Close'].tail(252), vix_val)

        ema20 = ta.ema(nifty_df['Close'], length=20).dropna()
        ema_slope_pct = None
        if len(ema20) >= 6:
            e_now, e_prev = float(ema20.iloc[-1]), float(ema20.iloc[-6])
            ema_slope_pct = (e_now / e_prev - 1.0) * 100.0 if e_prev else None

        last_close = float(nifty_df['Close'].iloc[-1])
        ema20_last = float(ema20.iloc[-1]) if not ema20.empty else last_close
        above_ema20 = last_close > ema20_last

        # Adaptive classification: percentile-based where we have enough history
        # for a meaningful percentile (>=20 data points), falling back to the
        # previous fixed thresholds only when history is too short to rank against
        # (e.g. right after a fresh cache, or a newly listed instrument).
        vix_hot = (vix_percentile >= 90) if vix_percentile is not None else (vix_val is not None and vix_val >= 25)
        vix_calm = (vix_percentile <= 15) if vix_percentile is not None else (vix_val is not None and vix_val <= 11)
        adx_trending = (adx_percentile >= 75) if adx_percentile is not None else (adx_val is not None and adx_val >= 25)

        if vix_hot:
            regime = "PANIC" if (ema_slope_pct is not None and ema_slope_pct < -1.0) else "HIGH_VOLATILITY"
        elif vix_calm and breadth_score is not None and breadth_score >= 70:
            regime = "EUPHORIA"
        elif adx_trending:
            regime = "TRENDING_BULL" if above_ema20 else "TRENDING_BEAR"
        else:
            regime = "SIDEWAYS"

        # regime_score is now a REAL number (ADX's own percentile rank), not an
        # invented distance formula — falls back to 50 (neutral) only when there
        # isn't enough history yet to compute a meaningful percentile.
        regime_score = adx_percentile if adx_percentile is not None else 50.0

        return {
            "regime": regime, "regime_score": round(regime_score, 0),
            "adx": round(adx_val, 1) if adx_val is not None else None,
            "adx_percentile": round(adx_percentile, 0) if adx_percentile is not None else None,
            "atr_percentile": round(atr_percentile, 0) if atr_percentile is not None else None,
            "ema20_slope_pct": round(ema_slope_pct, 2) if ema_slope_pct is not None else None,
            "vix": round(vix_val, 1) if vix_val is not None else None,
            "vix_percentile": round(vix_percentile, 0) if vix_percentile is not None else None,
            "breadth_score": breadth_score,
            "adaptive": adx_percentile is not None and vix_percentile is not None,
        }
    except Exception as exc:
        LOGGER.debug("Market regime computation failed: %s", exc)
        return None

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


@st.cache_data(ttl=300)
def fetch_nse_market_status():
    try:
        url = "https://api.upstox.com/v2/market/status/nse"
        headers = {"Accept": "application/json"}
        with requests.Session() as s:
            res = s.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json().get("data") or {}
                return data
    except Exception as e:
        LOGGER.warning("fetch_nse_market_status failed: %s", e)
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
except Exception as e:
    LOGGER.debug("Suppressed exception: %s", e)
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
    help="The header ticker refreshes independently every 5s regardless of this setting. "
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
        # Without this package the toggle above does nothing — the page only
        # updates when you interact with a widget. Fix: add `streamlit-autorefresh`
        # to requirements.txt and redeploy.
        st.sidebar.error(
            "⚠️ `streamlit-autorefresh` is NOT installed — auto-refresh is inactive. "
            "Add `streamlit-autorefresh` to requirements.txt and redeploy, otherwise this page "
            "will only update when you click something."
        )
        if st.sidebar.button("🔄 Refresh Now", key="manual_refresh_btn", width='stretch'):
            st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader("💰 Capital & Risk")
investment_capital = st.sidebar.number_input(
    "Investment Capital (₹)", min_value=0.0, value=1000000.0, step=10000.0, key="sb_investment_capital",
    help="Total capital used to size every trade recommendation in this app."
)
max_risk_pct = st.sidebar.slider(
    "Max Risk per Trade (%)", min_value=0.5, max_value=10.0, value=2.0, step=0.5, key="sb_max_risk_pct",
    help="What % of your capital you're willing to lose if a single trade hits its stop loss."
)
max_position_pct = st.sidebar.slider(
    "Max Capital per Position (%)", min_value=1.0, max_value=100.0, value=20.0, step=1.0, key="sb_max_position_pct",
    help="Caps how much of your total capital any single position can use, even if the risk budget alone would allow more (e.g. very tight stops on a cheap option could otherwise size an oversized position)."
)
max_sector_exposure_pct = st.sidebar.slider(
    "Max Sector Exposure (%)", min_value=5.0, max_value=100.0, value=30.0, step=5.0, key="sb_max_sector_pct",
    help="Warns you before adding a new position if your tracked positions already have this much capital concentrated in the same sector (e.g. too much in Banking or IT)."
)
options_no_trade_threshold = st.sidebar.slider(
    "Options: Min. Directional Score Gap", min_value=5, max_value=50, value=15, step=5, key="sb_options_notrade_threshold",
    help="How decisively bull_score must beat bear_score (both 0-100) before the app recommends a directional CE/PE trade. "
         "Below this gap, conflicting signals produce NO TRADE instead of a weak directional call. Raise this for a stricter, "
         "more selective options engine; lower it to see more (weaker-conviction) trade ideas."
)

with st.sidebar.expander("📁 My Positions (for sector exposure tracking)"):
    st.caption("Manually log your current positions here so the app can warn you about sector concentration before recommending more of the same sector. This is separate from live Upstox holdings — nothing here is fetched automatically.")
    pos_col1, pos_col2 = st.columns(2)
    with pos_col1:
        new_pos_ticker = st.text_input("Ticker", key="sb_new_pos_ticker", placeholder="e.g. HDFCBANK")
    with pos_col2:
        new_pos_capital = st.number_input("Capital Deployed (₹)", min_value=0.0, step=1000.0, key="sb_new_pos_capital")
    if st.button("+ Add Position", key="sb_add_position", width='stretch'):
        if new_pos_ticker and new_pos_capital > 0:
            add_position(new_pos_ticker, new_pos_capital)
            st.rerun()
        else:
            st.warning("Enter both a ticker and a capital amount.")

    positions_df = get_positions_df()
    if not positions_df.empty:
        st.markdown("**Current positions:**")
        for _, prow in positions_df.iterrows():
            pcol1, pcol2 = st.columns([4, 1])
            with pcol1:
                st.caption(f"{prow['ticker']} · {prow['sector']} · ₹{prow['capital_deployed']:,.0f}")
            with pcol2:
                if st.button("🗑", key=f"sb_del_pos_{prow['id']}"):
                    remove_position(prow['id'])
                    st.rerun()

        exposure = get_sector_exposure()
        total_deployed = sum(exposure.values())
        if total_deployed > 0:
            st.markdown("**Sector breakdown:**")
            for sector, cap in sorted(exposure.items(), key=lambda x: -x[1]):
                pct = cap / investment_capital * 100.0 if investment_capital > 0 else 0.0
                flag = " ⚠️" if pct >= max_sector_exposure_pct else ""
                st.caption(f"{sector}: ₹{cap:,.0f} ({pct:.1f}% of capital){flag}")
    else:
        st.caption("No positions logged yet.")

st.sidebar.markdown("---")
require_mtf_confirmation = st.sidebar.toggle(
    "📊 Multi-Timeframe Confirmation", value=False, key="sb_require_mtf",
    help="Checks whether 15-min and 1-hour trend agree with the daily bias before showing a recommendation. "
         "OFF by default — enabling this may reduce how many recommendations appear, since only setups "
         "confirmed across timeframes will show."
)

if st.sidebar.button("Force Reconnect & Clear Cache", width='stretch', key="sb_reconnect"):
    st.cache_data.clear()
    st.cache_resource.clear()  # also drops the live WebSocket connection object so it starts fully fresh
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
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
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
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
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
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
        pass
    return {}

def save_iv_history_disk(history):
    try:
        with open(IV_HISTORY_FILE, "w") as f:
            json.dump(history, f)
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
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
def normalize_market_timestamp_series(series):
    """CANONICAL TIMESTAMP CONVENTION for this app: all internal market-data
    timestamps are timezone-NAIVE IST market time.

    ROOT CAUSE this exists to fix: Upstox's raw API returns ISO8601 timestamps
    WITH a timezone offset (e.g. '2026-08-20T09:15:00+05:30'), which pandas
    automatically parses as timezone-AWARE. Meanwhile prepare_live_daily_bar's
    live-bar insertion (and the SQLite cache write path in _serialize_history)
    both already produce timezone-NAIVE timestamps. Mixing the two in the same
    DataFrame index throws 'Cannot compare tz-naive and tz-aware timestamps'
    the moment pandas needs to sort or compare them (e.g. sort_index() after
    inserting today's live bar into cached history).

    Applied once, here, at the single shared entry point every fresh Upstox
    history fetch passes through (_history_to_dataframe) — this makes every
    DataFrame in the app consistently tz-naive from the moment data enters it,
    rather than patching each downstream comparison individually."""
    try:
        if hasattr(series, 'dt') and series.dt.tz is not None:
            return series.dt.tz_localize(None)
        return series
    except Exception as e:
        LOGGER.debug("Timestamp normalization skipped: %s", e)
        return series


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
    df["Date"] = normalize_market_timestamp_series(df["Date"])  # ROOT-CAUSE FIX — see docstring above
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


def fetch_upstox_intraday_series(instrument_key, token, unit, interval, days_back=10):
    """Fetches candles at a specific intraday granularity (e.g. unit='minutes',
    interval=15 for 15-min bars; unit='hours', interval=1 for 1-hour bars) using
    Upstox's V3 historical-candle endpoint:
      https://api.upstox.com/v3/historical-candle/{key}/{unit}/{interval}/{to}/{from}
    Confirmed against Upstox's own V3 API documentation. Used for multi-timeframe
    trend confirmation — NOT used anywhere by default; only called when the
    opt-in "Multi-Timeframe Confirmation" toggle is enabled, and degrades to an
    empty DataFrame (treated as "confirmation unavailable") on any failure rather
    than raising, so it can never break the existing recommendation flow."""
    empty = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume", "OI"])
    if not token or not instrument_key:
        return empty
    end_date = datetime.datetime.now(IST).date()
    start_date = end_date - datetime.timedelta(days=max(int(days_back), 1))
    try:
        encoded_key = urllib.parse.quote(instrument_key, safe="")
        url = (f"https://api.upstox.com/v3/historical-candle/{encoded_key}/{unit}/{interval}/"
               f"{end_date.isoformat()}/{start_date.isoformat()}")
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        with get_robust_session() as session:
            res = session.get(url, headers=headers, timeout=10)
            if res.status_code != 200:
                LOGGER.debug("V3 intraday candle %s for %s (%s/%s): %s", res.status_code, instrument_key, unit, interval, res.text[:200])
                return empty
            candles = ((res.json().get("data") or {}).get("candles") or [])
            return _history_to_dataframe(candles)
    except Exception as exc:
        LOGGER.debug("V3 intraday candle fetch failed for %s (%s/%s): %s", instrument_key, unit, interval, exc)
        return empty


def get_timeframe_trend_label(df, ema_length=20):
    """Simple, consistent-with-existing-bias trend label for one timeframe's
    candle series: last close vs EMA — same logic already used for the daily
    market bias, just applied at whatever granularity df is in."""
    try:
        if df is None or df.empty or len(df) < ema_length:
            return None
        ema_series = ta.ema(df['Close'], length=ema_length).dropna()
        if ema_series.empty:
            return None
        last_close = float(df['Close'].iloc[-1])
        last_ema = float(ema_series.iloc[-1])
        if last_ema <= 0:
            return None
        diff_pct = (last_close - last_ema) / last_ema * 100.0
        if diff_pct > 0.05:
            return "Bullish"
        elif diff_pct < -0.05:
            return "Bearish"
        return "Neutral"
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
        return None


@st.cache_data(ttl=180, show_spinner=False)
def get_multi_timeframe_confirmation(instrument_key, token, daily_bias):
    """Checks whether 15-min and 1-hour trend agree with the given daily bias.
    Returns (status, detail_dict):
      status: "Aligned Bullish" / "Aligned Bearish" / "Mixed" / "Unavailable"
      detail_dict: {"15m": "Bullish"/..., "1H": "Bullish"/..., "Daily": daily_bias}
    Cached for 3 min since intraday trend doesn't meaningfully change faster than that.
    """
    detail = {"Daily": daily_bias}
    if daily_bias not in ("Bullish", "Bearish"):
        # Only meaningful to confirm a directional bias; Neutral/Mildly-* have no
        # strict signal to confirm against.
        return "Unavailable", detail

    df_15m = fetch_upstox_intraday_series(instrument_key, token, "minutes", 15, days_back=10)
    df_1h = fetch_upstox_intraday_series(instrument_key, token, "hours", 1, days_back=20)

    trend_15m = get_timeframe_trend_label(df_15m)
    trend_1h = get_timeframe_trend_label(df_1h)
    detail["15m"] = trend_15m or "N/A"
    detail["1H"] = trend_1h or "N/A"

    if trend_15m is None and trend_1h is None:
        return "Unavailable", detail

    timeframe_votes = [t for t in (trend_15m, trend_1h) if t in ("Bullish", "Bearish")]
    if not timeframe_votes:
        return "Unavailable", detail

    if all(t == daily_bias for t in timeframe_votes):
        return f"Aligned {daily_bias}", detail
    return "Mixed", detail

@st.cache_data(ttl=86400)
def get_full_nse_instrument_dictionary():
    # SAFETY NET (Section 3): a genuinely complete NSE equity universe has
    # numbered in the thousands for many years — this floor is a sanity check
    # against a LOADING/FILTERING BUG, not a target to hit. If the app is
    # ever legitimately correct at a smaller number (e.g. Upstox itself
    # changes what it serves), this constant is the one place to revisit —
    # it is never used to pad, fabricate, or select which instruments load.
    MIN_EXPECTED_NSE_UNIVERSE = 1000
    try:
        url = 'https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz'
        df = pd.read_csv(url)

        # === DIAGNOSTIC INSTRUMENTATION (unchanged from the prior investigation) ===
        raw_rows = len(df)
        LOGGER.info("NSE_UNIVERSE_DIAG: raw CSV rows = %d", raw_rows)
        LOGGER.info("NSE_UNIVERSE_DIAG: columns = %s", df.columns.tolist())
        if 'exchange' in df.columns:
            LOGGER.info("NSE_UNIVERSE_DIAG: exchange unique values (up to 20) = %s", df['exchange'].unique()[:20].tolist())
        else:
            LOGGER.info("NSE_UNIVERSE_DIAG: 'exchange' column NOT PRESENT")
        if 'instrument_type' in df.columns:
            LOGGER.info("NSE_UNIVERSE_DIAG: instrument_type unique values (up to 20) = %s", df['instrument_type'].unique()[:20].tolist())
        else:
            LOGGER.info("NSE_UNIVERSE_DIAG: 'instrument_type' column NOT PRESENT")
        if 'series' in df.columns:
            LOGGER.info("NSE_UNIVERSE_DIAG: series unique values (up to 20) = %s", df['series'].unique()[:20].tolist())
        else:
            LOGGER.info("NSE_UNIVERSE_DIAG: 'series' column NOT PRESENT")
        # === END schema diagnostics ===

        # ROBUSTNESS FIX: this sandbox has no network access to Upstox's live
        # asset URL, so the EXACT current schema cannot be verified here —
        # stated plainly rather than guessed. What changed: matching is now
        # case-insensitive and whitespace-tolerant, and instrument_type
        # accepts BOTH "EQUITY" and "EQ" — Upstox's documented instrument
        # master conventions have used short-form type codes ("EQ", "FUT",
        # "CE", "PE") in various versions, so a strict match on the full word
        # "EQUITY" alone is a plausible, well-grounded candidate for
        # collapsing the match to near-nothing. This BROADENS acceptance
        # rather than guessing a single replacement value — it will correctly
        # match whichever convention the live file actually uses, and changes
        # nothing about which SEGMENT of instruments is intended (still only
        # genuine NSE cash equities, not derivatives/bonds/other exchanges).
        nse_df = df[df['exchange'].astype(str).str.strip().str.upper() == 'NSE_EQ']
        LOGGER.info("NSE_UNIVERSE_DIAG: rows after exchange=='NSE_EQ' filter = %d (removed %d)", len(nse_df), raw_rows - len(nse_df))

        nse_df = nse_df[nse_df['instrument_type'].astype(str).str.strip().str.upper().isin(['EQUITY', 'EQ'])]
        LOGGER.info("NSE_UNIVERSE_DIAG: rows after instrument_type in ('EQUITY','EQ') filter = %d", len(nse_df))

        if 'series' in nse_df.columns:
            before_series = len(nse_df)
            nse_df = nse_df[nse_df['series'].astype(str).str.strip().str.upper() == 'EQ']
            LOGGER.info("NSE_UNIVERSE_DIAG: rows after series=='EQ' filter = %d (removed %d)", len(nse_df), before_series - len(nse_df))
        else:
            LOGGER.info("NSE_UNIVERSE_DIAG: series filter SKIPPED (column absent) — rows unchanged = %d", len(nse_df))

        # Belt-and-suspenders regardless of whether the 'series' filter above ran:
        # bonds/NCDs/preference-share-style instruments (e.g. "1003IIFL29") use
        # numeric-prefixed trading symbols — no legitimate NSE equity ticker starts
        # with a digit.
        before_digit_filter = len(nse_df)
        nse_df = nse_df[~nse_df['tradingsymbol'].astype(str).str.match(r'^\d', na=False)]
        LOGGER.info("NSE_UNIVERSE_DIAG: rows after digit-prefix exclusion = %d (removed %d)", len(nse_df), before_digit_filter - len(nse_df))

        # === Dictionary construction audit ===
        rows_before_dict = len(nse_df)
        unique_symbols = nse_df['tradingsymbol'].nunique()
        duplicate_count = rows_before_dict - unique_symbols
        result_dict = dict(zip(nse_df['tradingsymbol'], nse_df['instrument_key']))
        LOGGER.info(
            "NSE_UNIVERSE_DIAG: rows before dict conversion = %d, unique tradingsymbol = %d, "
            "duplicate symbol rows = %d, final dict size = %d",
            rows_before_dict, unique_symbols, duplicate_count, len(result_dict)
        )
        # === END instrumentation ===

        # SAFETY NET, enforced (Section 3): loudly flag — never silently
        # accept — a suspiciously small "complete" universe. This does not
        # change what was loaded; it only makes a broken load impossible to
        # miss, in logs and (via nse_universe_validation_failed below) in
        # the UI.
        if len(result_dict) < MIN_EXPECTED_NSE_UNIVERSE:
            LOGGER.error(
                "NSE_UNIVERSE_VALIDATION_FAILED: only %d instruments loaded (expected >= %d for a genuinely "
                "complete NSE equity universe). This indicates a loading/filtering bug, not a legitimately "
                "small NSE. Full NSE scans will be materially incomplete until this is resolved.",
                len(result_dict), MIN_EXPECTED_NSE_UNIVERSE
            )

        return result_dict
    except Exception as e:
        LOGGER.warning("NSE_UNIVERSE_DIAG: EXCEPTION during instrument load/filter: %s", e)
        LOGGER.debug("Suppressed exception: %s", e)
        global NSE_INSTRUMENT_LOAD_EXCEPTION
        NSE_INSTRUMENT_LOAD_EXCEPTION = True
        return {}

NSE_INSTRUMENT_LOAD_EXCEPTION = False  # set True only if the loader itself threw — distinct from "loaded fine but small"
instrument_dict = get_full_nse_instrument_dictionary()
# REMOVED: the previous 5-stock fallback (["RELIANCE","TCS","HDFCBANK","INFY","SBIN"])
# silently made a total load failure look like a valid, if tiny, universe — that's
# exactly the "fake Full NSE universe" failure mode this fix exists to prevent.
# An empty/failed load now stays empty, and is BLOCKED explicitly below rather
# than quietly proceeding with 5 stocks as if that were reasonable.
all_nse_tickers = sorted(instrument_dict.keys()) if instrument_dict else []
# Mirrors the loader's own validation, at the module-level variable actually
# consumed by Full NSE — checked here too (not just inside the cached
# function) so this stays accurate even across a Streamlit cache hit that
# skips re-running the function body/its LOGGER.error call.
NSE_UNIVERSE_VALIDATION_FAILED = len(all_nse_tickers) < 1000

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
        # Circuit breaker state: prevents hammering Upstox with rapid reconnect
        # attempts when the failure is auth-related (403) rather than transient
        # network noise — retrying a bad/expired token instantly in a loop just
        # gets the API key flagged for abuse without ever fixing anything.
        self.auth_failed = False
        self.consecutive_failures = 0
        self.last_attempt_ts = 0.0

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
        except Exception as e:
            LOGGER.debug("Suppressed exception: %s", e)
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
        self.auth_failed=False
        self.consecutive_failures=0
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
        err_str=str(err)
        self.last_error=err_str
        self.connected=False
        self.consecutive_failures+=1
        # A 403/Forbidden handshake means the token itself was rejected —
        # this will NEVER succeed on retry until the token is fixed, so stop
        # hammering Upstox's servers instead of retrying in a tight loop.
        if '403' in err_str or 'Forbidden' in err_str:
            self.auth_failed=True
            LOGGER.warning("Upstox WebSocket auth rejected (403) — halting auto-reconnect until token is refreshed.")

    def _run(self):
        try:
            configuration=upstox_client.Configuration()
            configuration.access_token=self.token
            self.streamer=upstox_client.MarketDataStreamerV3(upstox_client.ApiClient(configuration))
            self.streamer.on('open', self.on_open)
            self.streamer.on('message', self.on_message)
            self.streamer.on('close', self.on_close)
            self.streamer.on('error', self.on_error)
            # NOTE: intentionally NOT using the SDK's built-in auto_reconnect() here.
            # It was observed retrying failed (403) handshakes multiple times per
            # second regardless of the configured interval, which risks the API key
            # getting flagged for abuse. We manage reconnection ourselves in ensure()
            # with a proper backoff + circuit breaker instead.
            self.streamer.connect()
        except Exception as e:
            self.last_error=str(e)
            self.connected=False
            if '403' in str(e) or 'Forbidden' in str(e):
                self.auth_failed=True

    def ensure(self, keys):
        keys=[k for k in dict.fromkeys(keys) if k]
        if not keys or not self.token or not UPSTOX_SDK_AVAILABLE:
            return
        with self.lock:
            self.subscribed.update(keys)
        with self._start_lock:
            if self.connected:
                try:
                    if keys:
                        self.streamer.subscribe(keys, 'ltpc')
                except Exception as e:
                    LOGGER.debug("Suppressed exception: %s", e)
                    pass
                return
            if self.thread is not None and self.thread.is_alive():
                return
            if self.auth_failed:
                # Don't auto-retry an auth failure — the token needs to change first.
                # reset_auth_failure() (called from "Force Reconnect & Clear Cache") is
                # the only way to clear this and allow another attempt.
                return
            # Exponential backoff for non-auth failures (network blips, timeouts, etc.):
            # 5s, 10s, 20s, 40s... capped at 60s between attempts.
            backoff = min(60.0, 5.0 * (2 ** self.consecutive_failures))
            if time.time() - self.last_attempt_ts < backoff:
                return
            self.last_attempt_ts = time.time()
            self.thread=threading.Thread(target=self._run, daemon=True, name='upstox-market-stream')
            self.thread.start()

    def reset_auth_failure(self):
        """Call after the user supplies a fresh token to allow reconnect attempts again."""
        with self.lock:
            self.auth_failed=False
            self.consecutive_failures=0
            self.last_attempt_ts=0.0

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
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
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
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
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
                volume_pace_ratio = min(raw_daily_ratio / elapsed_fraction, 5.0) if elapsed_fraction > 0 else raw_daily_ratio
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
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
        return {}

mcx_dict = get_mcx_instrument_dictionary()
all_mcx_tickers = sorted(list(mcx_dict.keys())) if mcx_dict else ["GOLD", "SILVER", "CRUDEOIL", "NATURALGAS"]

@st.cache_data(ttl=86400)
def get_mcx_futures_instruments():
    try:
        url = 'https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz'
        df = pd.read_csv(url)
        return df[(df['exchange'] == 'MCX_FO') & (df['instrument_type'] == 'FUTCOM')]
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
        return pd.DataFrame()

# ==========================================
# WATCHLIST PERSISTENCE
# ==========================================
# ==========================================
# OPTIONS CHAIN & CONTRACT ENGINE (Upstox v2)
# ==========================================
@st.cache_data(ttl=86400)
def get_fo_stock_symbols():
    """Returns the list of NSE F&O-eligible stock (FUTSTK) underlying symbols.

    IMPORTANT: must return tradingsymbol-compatible values (e.g. "ADANIPORTS"),
    NOT the free-text company display name (e.g. "ADANI PORT & SEZ LTD") — the
    latter does not exist as a key in instrument_dict (which is keyed by
    tradingsymbol from the NSE_EQ instrument list) and silently breaks every
    lookup for any stock whose display name differs from its trading symbol."""
    try:
        url = 'https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz'
        df = pd.read_csv(url)
        fo_df = df[(df['exchange'] == 'NSE_FO') & (df['instrument_type'] == 'FUTSTK')]
        extracted = fo_df['tradingsymbol'].astype(str).str.extract(r'^([A-Za-z&\-]+)')[0]
        symbols = sorted(set(extracted.dropna().str.upper()))
        # Only keep symbols that actually resolve in instrument_dict — anything
        # left over is a parsing edge case, not something safe to show as pickable.
        if instrument_dict:
            symbols = [s for s in symbols if s in instrument_dict]
        return symbols
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
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
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
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
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
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
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
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
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
        pass
    return []


def get_available_expiries(contracts):
    """Extracts a sorted, de-duplicated list of expiry dates from an option-contracts list."""
    try:
        return sorted({c.get('expiry') for c in (contracts or []) if c.get('expiry')})
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
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
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
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
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
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
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
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
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
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
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
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
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
        return "⚪ Neutral"


def compute_bollinger_percent_b(latest):
    """Computes Bollinger %B for the latest bar: 0% = lower band, 100% = upper band."""
    try:
        lower, upper, close = float(latest['BB_lower']), float(latest['BB_upper']), float(latest['Close'])
        if not np.isfinite(lower) or not np.isfinite(upper) or upper == lower:
            return None
        return round((close - lower) / (upper - lower) * 100.0, 1)
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
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
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
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
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
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
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
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
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
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
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
        return []


def search_mf_schemes(query):
    """Free-text search over the AMFI scheme master list by scheme name."""
    try:
        all_schemes = fetch_mf_scheme_list()
        q = str(query or "").lower()
        return [s for s in all_schemes if q in str(s.get("schemeName", "")).lower()]
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
        return []


@st.cache_data(ttl=3600)
def fetch_mf_nav_history(scheme_code):
    """Fetches full NAV history + metadata for a scheme code via mfapi.in."""
    try:
        with get_robust_session() as session:
            res = session.get(f"https://api.mfapi.in/mf/{scheme_code}", timeout=10)
            if res.status_code == 200:
                return res.json()
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
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
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
        return None


WATCHLIST_FILE = "watchlist.json"

def load_watchlist():
    try:
        if os.path.exists(WATCHLIST_FILE):
            with open(WATCHLIST_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
        pass
    return []

def save_watchlist(tickers):
    try:
        with open(WATCHLIST_FILE, "w") as f:
            json.dump(tickers, f)
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
        pass

if "watchlist" not in st.session_state:
    st.session_state.watchlist = load_watchlist()

st.sidebar.markdown("---")
st.sidebar.header("⭐ Watchlist")
wl_options = ["-- Select --"] + [t for t in all_nse_tickers if t not in st.session_state.watchlist]
wl_add = st.sidebar.selectbox("Add ticker", wl_options, key="wl_add_select")
if st.sidebar.button("➕ Add to Watchlist", key="wl_add_btn", width='stretch') and wl_add != "-- Select --":
    st.session_state.watchlist.append(wl_add)
    save_watchlist(st.session_state.watchlist)
    st.rerun()

if st.session_state.watchlist:
    wl_remove = st.sidebar.selectbox("Remove ticker", ["-- Select --"] + st.session_state.watchlist, key="wl_remove_select")
    if st.sidebar.button("➖ Remove from Watchlist", key="wl_remove_btn", width='stretch') and wl_remove != "-- Select --":
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

@st.cache_data(ttl=300, show_spinner=False)
def _get_prev_close(key, token):
    """Yesterday's close, used as a change-% reference when the live quote
    itself doesn't carry ohlc.close (common on REST-only quotes before the
    WebSocket fully connects). Cached for 5 min since it only changes once a day."""
    df = fetch_upstox_history(key, token, days=5)
    if not df.empty:
        return float(df.iloc[-1]['Close'])
    return 0.0

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
                if not yest_close:
                    # REST-only quotes (before WebSocket connects) often omit
                    # ohlc.close — fall back to yesterday's historical close
                    # instead of showing the price with no change at all.
                    yest_close = _get_prev_close(key, access_token)
                if yest_close > 0 and ltp > 0:
                    change = ltp - yest_close
                    pct_change = (change / yest_close) * 100
                    icon = "🟢" if change >= 0 else "🔴"
                    color = "green" if change >= 0 else "red"
                    sign = "+" if change >= 0 else ""
                    st.markdown(f"{icon} **{idx_name}** `{ltp:,.2f}` :{color}[{sign}{change:,.2f} ({sign}{pct_change:.2f}%)]")
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
                    color = "green" if change >= 0 else "red"
                    sign = "+" if change >= 0 else ""
                    st.markdown(f"{icon} **{idx_name}** `{today_close:,.2f} (History Close)` :{color}[{sign}{change:,.2f} ({sign}{pct_change:.2f}%)]")

def _render_true_live_ticker(relay_url, relay_secret):
    """True push-based ticker: JS opens its own WebSocket straight to the relay
    server and updates prices directly in the DOM on every tick. No Streamlit
    rerun is involved for this component at all — this is what actually matches
    the tick-by-tick feel of a native brokerage app.

    NOTE: not currently wired into the sidebar — the relay-hosting attempt hit
    an unresolved 403 from Upstox regardless of host (Render, multiple regions,
    multiple tokens). Left in place in case this is revisited later with a
    working relay deployment; just re-add the sidebar inputs and the
    use_true_live check below to turn it back on."""
    key_map = {"NSE_INDEX|Nifty 50": "nifty", "BSE_INDEX|SENSEX": "sensex", "NSE_INDEX|Nifty Bank": "banknifty"}
    labels = {"nifty": "NIFTY 50", "sensex": "SENSEX", "banknifty": "BANKNIFTY"}
    ws_url = relay_url.rstrip("/") + "/ws?token=" + relay_secret
    cards_html = "".join(
        f'<div style="display:inline-block;margin-right:28px;font-family:monospace;">'
        f'<span id="{k}-dot">⚪</span> <b>{labels[k]}</b> '
        f'<span id="{k}-ltp">--</span> <span id="{k}-chg"></span></div>'
        for k in labels
    )
    st.components.v1.html(f"""
        <div id="live-ticker-root">{cards_html}
          <div id="live-ticker-status" style="font-size:11px;color:#888;margin-top:4px;">connecting to relay...</div>
        </div>
        <script>
        (function() {{
            const keyMap = {json.dumps(key_map)};
            const statusEl = document.getElementById('live-ticker-status');
            function connect() {{
                const ws = new WebSocket("{ws_url}");
                ws.onopen = () => {{ statusEl.textContent = 'live — connected to relay'; }};
                ws.onclose = () => {{ statusEl.textContent = 'relay disconnected — retrying in 3s...'; setTimeout(connect, 3000); }};
                ws.onerror = () => {{ statusEl.textContent = 'relay connection error'; }};
                ws.onmessage = (event) => {{
                    const data = JSON.parse(event.data);
                    const short = keyMap[data.key];
                    if (!short) return;
                    const ltp = data.ltp, close = data.close;
                    const ltpEl = document.getElementById(short + '-ltp');
                    const chgEl = document.getElementById(short + '-chg');
                    const dotEl = document.getElementById(short + '-dot');
                    if (ltp != null) ltpEl.textContent = ltp.toLocaleString(undefined, {{minimumFractionDigits:2, maximumFractionDigits:2}});
                    if (ltp != null && close) {{
                        const chg = ltp - close, pct = (chg / close) * 100;
                        const sign = chg >= 0 ? '+' : '';
                        chgEl.textContent = `${{sign}}${{chg.toFixed(2)}} (${{sign}}${{pct.toFixed(2)}}%)`;
                        chgEl.style.color = chg >= 0 ? '#2ecc71' : '#e74c3c';
                        dotEl.textContent = chg >= 0 ? '🟢' : '🔴';
                    }}
                }};
            }}
            connect();
        }})();
        </script>
    """, height=60)


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
# TRADE SETUPS — RISK-BASED POSITION SIZING
# ==========================================
risk_engine = RiskEngine(
    investment_capital=investment_capital, max_risk_pct=max_risk_pct, max_position_pct=max_position_pct
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
        used_fallback = False
        if auto_scan_on:
            NIFTY_KEY = "NSE_INDEX|Nifty 50"

            @st.cache_data(ttl=30, show_spinner=False)
            def _scan_fo_momentum(tickers_tuple, token):
                tickers = list(tickers_tuple)
                keys = {t: instrument_dict.get(t) for t in tickers if instrument_dict.get(t)}
                quote_keys = list(keys.values()) + [NIFTY_KEY]
                quotes = get_live_scan_market_data(quote_keys, token)

                # Relative Strength benchmark: NIFTY's own move over the same window.
                # A stock's raw % move is a weak signal on its own — up 2% while the
                # whole market is up 1.8% is barely outperformance, while up 2% while
                # NIFTY is flat/red is real relative strength. RS = stock move - NIFTY move.
                nifty_pct = None
                nq = quotes.get(NIFTY_KEY)
                if nq:
                    n_ltp = float(nq.get("last_price") or 0.0)
                    n_prev = float((nq.get("ohlc") or {}).get("close") or 0.0)
                    if n_ltp > 0 and n_prev > 0:
                        nifty_pct = (n_ltp / n_prev - 1.0) * 100.0

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
                        momentum_pct, rel_strength = compute_relative_strength_pct(ltp, prev_close, nifty_pct)
                        if momentum_pct is None:
                            continue
                        range_pct = ((day_high - day_low) / prev_close) * 100.0 if prev_close else 0.0
                        rows.append({
                            "ticker": ticker, "ltp": ltp, "momentum_pct": momentum_pct,
                            "range_pct": range_pct, "rel_strength": rel_strength,
                        })
                    except Exception as e:
                        LOGGER.debug("Suppressed exception: %s", e)
                        continue
                # Rank by relative strength (real signal) when we have a benchmark,
                # falling back to raw momentum only if NIFTY's own quote failed.
                if nifty_pct is not None:
                    rows.sort(key=lambda r: abs(r["rel_strength"]) if r["rel_strength"] is not None else 0, reverse=True)
                else:
                    rows.sort(key=lambda r: abs(r["momentum_pct"]), reverse=True)
                return rows

            @st.cache_data(ttl=3600, show_spinner=False)
            def _scan_fo_last_session_movers(tickers_tuple, token):
                """Fallback for when live quotes are empty (market closed, or the
                feed hasn't warmed up yet): rank by the last completed session's
                move instead of leaving the person with nothing but the raw list.
                Parallelized since this hits the historical-candle endpoint once
                per ticker; cached for an hour since it only changes once a day."""
                tickers = list(tickers_tuple)

                nifty_df = fetch_upstox_history(NIFTY_KEY, token, days=5)
                nifty_pct = None
                if not nifty_df.empty and len(nifty_df) >= 2:
                    n_last, n_prev = float(nifty_df.iloc[-1]['Close']), float(nifty_df.iloc[-2]['Close'])
                    if n_prev > 0:
                        nifty_pct = (n_last / n_prev - 1.0) * 100.0

                rows = []
                def _fetch_one(ticker):
                    key = instrument_dict.get(ticker)
                    if not key:
                        return None
                    df = fetch_upstox_history(key, token, days=5)
                    if df.empty or len(df) < 2:
                        return None
                    last_close = float(df.iloc[-1]['Close'])
                    prev_close = float(df.iloc[-2]['Close'])
                    day_high = float(df.iloc[-1]['High']) if 'High' in df.columns else last_close
                    day_low = float(df.iloc[-1]['Low']) if 'Low' in df.columns else last_close
                    momentum_pct, rel_strength = compute_relative_strength_pct(last_close, prev_close, nifty_pct)
                    if momentum_pct is None:
                        return None
                    range_pct = ((day_high - day_low) / prev_close) * 100.0
                    return {
                        "ticker": ticker, "ltp": last_close, "momentum_pct": momentum_pct,
                        "range_pct": range_pct, "rel_strength": rel_strength,
                    }
                with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
                    for result in executor.map(_fetch_one, tickers):
                        if result:
                            rows.append(result)
                if nifty_pct is not None:
                    rows.sort(key=lambda r: abs(r["rel_strength"]) if r["rel_strength"] is not None else 0, reverse=True)
                else:
                    rows.sort(key=lambda r: abs(r["momentum_pct"]), reverse=True)
                return rows

            scan_universe = tuple(liquid_fo) if liquid_fo else tuple(stock_options_list[:100])
            with st.spinner("Scanning F&O universe for live momentum..."):
                try:
                    top_movers = _scan_fo_momentum(scan_universe, access_token)
                except Exception as exc:
                    LOGGER.warning("F&O auto-scan failed: %s", exc)
                    top_movers = []

            if not top_movers:
                # Live scan came up empty (market closed / feed warming up) —
                # fall back to last-session movers instead of leaving a blank scan.
                with st.spinner("Live data unavailable — checking last session's movers instead..."):
                    try:
                        top_movers = _scan_fo_last_session_movers(scan_universe, access_token)
                        used_fallback = bool(top_movers)
                    except Exception as exc:
                        LOGGER.warning("F&O last-session fallback scan failed: %s", exc)
                        top_movers = []

        if top_movers:
            movers_df = pd.DataFrame(top_movers[:10])[["ticker", "ltp", "momentum_pct", "range_pct", "rel_strength"]]
            movers_df["Suggested Side"] = movers_df["momentum_pct"].apply(
                lambda x: "CE (Bullish)" if x >= 0.5 else ("PE (Bearish)" if x <= -0.5 else "Neutral")
            )
            movers_df = movers_df.rename(columns={
                "ticker": "Symbol", "ltp": "LTP", "momentum_pct": "Move %",
                "range_pct": "Day Range %", "rel_strength": "vs NIFTY (RS)"
            })
            heading = "Top F&O Movers (last completed session)" if used_fallback else "Top F&O Movers (auto-ranked, live)"
            st.markdown(f"#### {heading}")
            if used_fallback:
                st.caption("Live quotes aren't available right now (market closed or feed still warming up) — ranked by the last completed session's move instead.")
            st.caption("Ranked by Relative Strength vs NIFTY (excess move over the index), not raw momentum alone — a stock beating the index is a stronger signal than one just moving with it.")
            st.dataframe(
                movers_df.style.format({
                    "LTP": "₹{:.2f}", "Move %": "{:.2f}", "Day Range %": "{:.2f}",
                    "vs NIFTY (RS)": lambda v: f"{v:+.2f}" if pd.notna(v) else "—",
                }, na_rep="—")
                .map(lambda v: f"color: {'#2ecc71' if v >= 0 else '#e74c3c'}", subset=["Move %"])
                .map(lambda v: (f"color: {'#2ecc71' if v >= 0 else '#e74c3c'}" if pd.notna(v) else ""), subset=["vs NIFTY (RS)"]),
                width='stretch', hide_index=True
            )
            default_pick = top_movers[0]["ticker"]
            default_idx = stock_options_list.index(default_pick) if default_pick in stock_options_list else 0

            # --- Quick multi-stock trade ideas: gives an actual "top list" of
            # tradeable ATM setups across the top movers, instead of forcing a
            # manual pick-and-check loop. Simplified vs the full detailed
            # analysis below (ATM strike only, fixed 25%/20% target/stop) —
            # meant as a fast overview to scan, not a replacement for the
            # detailed per-stock analysis you get by selecting one below.
            @st.cache_data(ttl=60, show_spinner=False)
            def _quick_top_trade_ideas(movers_tuple, token):
                def _one(row):
                    ticker, momentum, spot = row
                    if abs(momentum) < 0.5:
                        return None  # no clear direction — skip rather than guess
                    side = "CE" if momentum >= 0.5 else "PE"
                    key = instrument_dict.get(ticker)
                    if not key:
                        return None
                    try:
                        contracts = fetch_option_contracts(key, token)
                        expiries = get_available_expiries(contracts)
                        if not expiries:
                            return None
                        nearest_expiry = expiries[0]
                        chain = fetch_option_chain(key, nearest_expiry, token)
                        if not chain:
                            return None
                        sorted_chain = sorted(chain, key=lambda x: x.get('strike_price', 0))
                        atm_item = min(sorted_chain, key=lambda x: abs(x.get('strike_price', 0) - spot))
                        opt_side = (atm_item.get('call_options') if side == "CE" else atm_item.get('put_options')) or {}
                        premium = (opt_side.get('market_data') or {}).get('ltp')
                        if not premium or premium <= 0:
                            return None
                        return {
                            "Symbol": ticker, "Side": side, "Strike": atm_item.get('strike_price'),
                            "Premium": round(float(premium), 2), "Target (+25%)": round(float(premium) * 1.25, 2),
                            "Stop (-20%)": round(float(premium) * 0.80, 2), "Expiry": nearest_expiry,
                        }
                    except Exception as e:
                        LOGGER.debug("Suppressed exception: %s", e)
                        return None
                ideas = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                    for result in executor.map(_one, movers_tuple):
                        if result:
                            ideas.append(result)
                return ideas

            movers_for_ideas = tuple(
                (m["ticker"], m["momentum_pct"], m["ltp"]) for m in top_movers[:5]
            )
            with st.spinner("Building quick trade ideas for top movers..."):
                try:
                    quick_ideas = _quick_top_trade_ideas(movers_for_ideas, access_token)
                except Exception as exc:
                    LOGGER.warning("Quick multi-stock trade ideas failed: %s", exc)
                    quick_ideas = []

            if quick_ideas:
                st.markdown("#### 🎯 Quick Trade Ideas — Top Movers (ATM, no manual selection needed)")
                st.caption("Fast overview across multiple stocks at once — ATM strike, fixed +25%/-20% target/stop. Select a stock below for the full detailed analysis (multiple strikes, real risk sizing).")
                st.dataframe(pd.DataFrame(quick_ideas), width='stretch', hide_index=True)
        else:
            if auto_scan_on:
                st.caption("Auto-scan couldn't rank anything right now (live and last-session data both unavailable) — pick a stock manually below.")
            default_idx = 0

        # BUG FIX: Streamlit selectboxes ignore the `index=` parameter once a
        # value already exists in session_state for that key — meaning the
        # "auto-select top mover" only ever worked on the very first run, then
        # got permanently stuck on whatever was picked once, even as the top
        # mover changed on later reruns. Fix: explicitly update session_state
        # ourselves, but ONLY if the current value still matches our last
        # auto-pick (i.e. the user hasn't manually overridden it) — this keeps
        # "auto-updates with the market" working while still respecting a
        # manual override, matching what "override anytime" actually promises.
        if top_movers:
            auto_pick = top_movers[0]["ticker"]
            last_auto_pick = st.session_state.get("_auto_picked_stock")
            current_selection = st.session_state.get("opt_stock_select")
            if "opt_stock_select" not in st.session_state or current_selection == last_auto_pick:
                st.session_state["opt_stock_select"] = auto_pick
            st.session_state["_auto_picked_stock"] = auto_pick

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
    using_stale_price = underlying_ltp <= 0
    if using_stale_price:
        # IMPORTANT: this is a fallback, not live data. If the live quote fetch is
        # failing (auth/websocket issues, rate limits, etc.) this silently freezes
        # the price used for bias/recommendations at yesterday's close all day —
        # we surface a visible warning below so that failure mode is never silent.
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
        raw_expiries = get_available_expiries(contracts)

        # STAGE 2A: expiry-vs-current-date validation. Previously `expiries` was
        # passed to the selectbox completely unfiltered — trusting Upstox's API
        # to never return an already-past expiry, and trusting Streamlit's
        # session_state to always hold a still-valid selection. Neither is
        # guaranteed. Filter out anything before today (current_date > expiry
        # is invalid and must never reach a live recommendation); today's own
        # expiry stays selectable (current_date == expiry is valid to view —
        # Stage 1's existing dte<=0 check already correctly turns that into
        # NO TRADE, this filter is purely about not offering ALREADY-EXPIRED
        # contracts as if they were live).
        today_date = datetime.datetime.now(IST).date()
        expiries = []
        for e in raw_expiries:
            try:
                if pd.to_datetime(e).date() >= today_date:
                    expiries.append(e)
            except Exception:
                continue  # unparseable expiry string — exclude rather than risk using it

        # Guard against stale session_state: if a previously-selected expiry has
        # now rolled off the valid list (e.g. the app was left open across an
        # expiry date), reset it explicitly rather than letting Streamlit's
        # selectbox behavior with an out-of-list session_state value be
        # implicit/undefined. "Next Expiry" (the default, expiries[0] since the
        # list is sorted ascending) then naturally resolves to the nearest
        # valid FUTURE expiry with zero extra logic needed.
        if expiries and st.session_state.get("opt_expiry_select") not in expiries:
            st.session_state["opt_expiry_select"] = expiries[0]

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
            except Exception as e:
                LOGGER.debug("Suppressed exception: %s", e)
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
        except Exception as e:
            LOGGER.debug("Suppressed exception: %s", e)
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
        except Exception as e:
            LOGGER.debug("Suppressed exception: %s", e)
            using_live_chain = False

    if selected_expiry:
        try:
            expiry_dt = pd.to_datetime(selected_expiry).date()
            dte = max((expiry_dt - datetime.datetime.now(IST).date()).days, 0)
        except Exception as e:
            LOGGER.debug("Suppressed exception: %s", e)
            dte = 7
    else:
        dte = 7
    t_val_shared = max(dte / 365.0, 1 / 365.0)
    DIVIDEND_YIELD_Q = 0.0

    if not using_live_chain or not chain_rows:
        # INTEGRATION FIX (found while tracing Stage 2B live behavior): this
        # branch repopulates chain_rows with SYNTHETIC Black-Scholes fallback
        # data — but previously left using_live_chain untouched, so if it
        # triggered because chain_rows was empty despite using_live_chain
        # already being True, that flag would keep lying afterward, telling
        # every downstream consumer (including the Stage 2B signal lifecycle)
        # this was live data when it was actually fabricated. Explicitly
        # correcting the flag here, at the single point where the fallback
        # decision is made, rather than patching each downstream consumer.
        using_live_chain = False
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
        """Returns (bias_label, score_details_dict). bias_label stays within the
        SAME 5-value space downstream code already expects (Bullish/Mildly
        Bullish/Neutral/Mildly Bearish/Bearish) — build_option_recommendation's
        `if bias in (...)` checks are UNCHANGED, and any string outside those 4
        recognized values already falls through to its existing `return None`
        (NO TRADE) branch, so "Neutral" now genuinely means NO TRADE without
        touching that function at all.

        REPLACES the previous crude AND-gate (all 5 factors must align for
        "Bullish", otherwise silently fall back to EMA20-ALONE for "Mildly
        Bullish" — which build_option_recommendation then treated identically
        to full "Bullish"). That fallback was the confirmed root cause of
        weak/conflicting-signal trades: satisfying all 5 factors together is a
        high bar, so most real recommendations were likely coming from the
        EMA20-only tier.

        WEIGHTED SCORE (0-100 each side), explained:
          - Price vs EMA20      20 pts — existing factor, unchanged threshold
          - Price vs VWAP       15 pts — NEW: session VWAP, computed from 15-min
                                 intraday bars via the SAME fetch_upstox_intraday_series
                                 already used for MTF confirmation (no new API path)
          - RSI                 15 pts — same 14-period RSI already computed, now
                                 GRADUATED by distance from 50 (scales to full 15
                                 pts at RSI 75+/25-) instead of a binary >=55/<=45 cutoff
          - MACD histogram      15 pts — same calculation, sign-based (magnitude
                                 isn't normalized across instruments, so kept binary
                                 to avoid a noisy, asset-dependent scale)
          - PCR                 15 pts — same 1.05/0.85 thresholds, unchanged
          - Volume confirmation 20 pts — same session-elapsed-adjusted check,
                                 added as a CONFIRMATION bonus to whichever side
                                 the other 5 factors already favor (volume
                                 confirms a direction, it doesn't set one — this
                                 mirrors its original role as an AND-gate
                                 condition rather than an independent signal)
        Max 100 per side. net_score = bull_score - bear_score.
        """
        try:
            idx_hist_short = fetch_upstox_history(live_key, access_token, days=60)
            if idx_hist_short.empty or len(idx_hist_short) < 20:
                return "Neutral", {}
            # CRITICAL: Upstox's daily historical-candle endpoint does NOT include
            # today's still-forming candle during live market hours — without this,
            # EMA/RSI/MACD are frozen on yesterday's close all day, which is why the
            # bias barely changed even as the market moved. Patch in today's live
            # price so these indicators actually react to today's session.
            if live_quotes and live_key in live_quotes:
                idx_hist_short = prepare_live_daily_bar(idx_hist_short, live_quotes[live_key])
            ema20_series = ta.ema(idx_hist_short['Close'], length=20).dropna()
            if ema20_series.empty:
                return "Neutral", {}
            ema20_last = ema20_series.iloc[-1]
            price_above, price_below = underlying_ltp > ema20_last, underlying_ltp < ema20_last

            rsi_last = None
            try:
                rsi_series = ta.rsi(idx_hist_short['Close'], length=14).dropna()
                if not rsi_series.empty:
                    rsi_last = float(rsi_series.iloc[-1])
            except Exception as e:
                LOGGER.debug("Suppressed exception: %s", e)
                rsi_last = None

            macd_hist_last = None
            try:
                macd_df = ta.macd(idx_hist_short['Close'], fast=12, slow=26, signal=9).dropna()
                if not macd_df.empty:
                    hist_col = [c for c in macd_df.columns if c.startswith("MACDh_")]
                    if hist_col:
                        macd_hist_last = float(macd_df[hist_col[0]].iloc[-1])
            except Exception as e:
                LOGGER.debug("Suppressed exception: %s", e)
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
            except Exception as e:
                LOGGER.debug("Suppressed exception: %s", e)
                volume_confirmed = False

            pcr_bullish = pcr_val is not None and pcr_val >= 1.05
            pcr_bearish = pcr_val is not None and pcr_val <= 0.85

            # VWAP — session volume-weighted average price, computed from 15-min
            # intraday bars via the SAME fetch function already used for MTF
            # confirmation (no new API integration point).
            vwap_last = None
            price_above_vwap, price_below_vwap = False, False
            try:
                intraday_15m = fetch_upstox_intraday_series(live_key, access_token, unit="minutes", interval=15, days_back=1)
                if not intraday_15m.empty:
                    today_ist = datetime.datetime.now(IST).date()
                    todays_bars = intraday_15m[intraday_15m.index.date == today_ist] if hasattr(intraday_15m.index, 'date') else intraday_15m
                    if not todays_bars.empty and 'Volume' in todays_bars.columns:
                        typical_price = (todays_bars['High'] + todays_bars['Low'] + todays_bars['Close']) / 3.0
                        cum_pv = (typical_price * todays_bars['Volume']).cumsum()
                        cum_vol = todays_bars['Volume'].cumsum().replace(0, np.nan)
                        vwap_series = (cum_pv / cum_vol).dropna()
                        if not vwap_series.empty:
                            vwap_last = float(vwap_series.iloc[-1])
                            price_above_vwap = underlying_ltp > vwap_last
                            price_below_vwap = underlying_ltp < vwap_last
            except Exception as e:
                LOGGER.debug("Suppressed exception: %s", e)
                vwap_last = None

            bull_score, bear_score = 0.0, 0.0
            if price_above: bull_score += 20
            elif price_below: bear_score += 20
            if price_above_vwap: bull_score += 15
            elif price_below_vwap: bear_score += 15
            if rsi_last is not None:
                rsi_delta = rsi_last - 50.0
                if rsi_delta > 0:
                    bull_score += min(15.0, rsi_delta / 25.0 * 15.0)
                elif rsi_delta < 0:
                    bear_score += min(15.0, abs(rsi_delta) / 25.0 * 15.0)
            if macd_bullish: bull_score += 15
            elif macd_bearish: bear_score += 15
            if pcr_bullish: bull_score += 15
            elif pcr_bearish: bear_score += 15
            if volume_confirmed:
                if bull_score > bear_score: bull_score += 20
                elif bear_score > bull_score: bear_score += 20

            net_score = round(bull_score - bear_score, 1)
            score_details = {
                "bull_score": round(bull_score, 1), "bear_score": round(bear_score, 1), "net_score": net_score,
                "ema20": round(float(ema20_last), 2), "vwap": round(vwap_last, 2) if vwap_last is not None else None,
                "rsi": round(rsi_last, 1) if rsi_last is not None else None,
                "macd_bullish": macd_bullish, "macd_bearish": macd_bearish,
                "pcr": pcr_val, "volume_confirmed": volume_confirmed,
            }

            threshold = options_no_trade_threshold
            strong_threshold = max(threshold * 3, 45)  # e.g. threshold=15 -> strong bar at 45
            if net_score >= threshold:
                return ("Bullish" if net_score >= strong_threshold else "Mildly Bullish"), score_details
            if net_score <= -threshold:
                return ("Bearish" if net_score <= -strong_threshold else "Mildly Bearish"), score_details
            return "Neutral", score_details
        except Exception as e:
            LOGGER.debug("Suppressed exception: %s", e)
            return "Neutral", {}

    market_bias, market_bias_scores = determine_market_bias()

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

            # DTE-TIER FRAMEWORK (Stage 1 fix): target/stop bands now genuinely
            # change based on time remaining to expiry, not just IV percentile.
            # Theta decay accelerates as expiry nears, so the same theoretical
            # % move in premium becomes progressively less realistic to expect
            # with fewer days left — previously this app computed DTE correctly
            # but never let it influence the actual recommendation, which was
            # the confirmed root cause of recommendations looking DTE-blind.
            if dte <= 0:
                # Expiry day: theta decay is near-total and spreads widen sharply.
                # A directional options BUY here is high-risk in a way a normal-
                # looking trade card shouldn't paper over — NO TRADE by design,
                # not a bug, not something to force just to populate the UI.
                return None
            elif dte <= 2:
                dte_tier = "Low DTE"
                target_mult = 1.0 + (target_mult - 1.0) * 0.75  # reduced target — less time for a big move
                stop_mult = min(stop_mult + 0.10, 0.90)  # tighter stop — less room while little time remains
            elif dte <= 4:
                dte_tier = "Medium DTE"
                target_mult = 1.0 + (target_mult - 1.0) * 0.90
                stop_mult = min(stop_mult + 0.05, 0.85)
            else:
                dte_tier = "Higher DTE"
                # unchanged — existing IV-percentile-driven bands as before

            target_premium = round(premium * target_mult, 2)
            stop_premium = round(premium * stop_mult, 2)

            ESTIMATED_ROUND_TRIP_COST_PCT = 0.7
            cost_buffer_per_unit = premium * (ESTIMATED_ROUND_TRIP_COST_PCT / 100.0)
            estimated_costs_per_lot = cost_buffer_per_unit * lot_size

            # Risk-based position sizing: how many lots fit within both the risk
            # budget (max loss if stop is hit) AND the capital budget (max ₹ tied
            # up in this one position), whichever is more restrictive.
            risk_per_unit_premium = max(premium - stop_premium, 0.01)
            risk_per_lot = risk_per_unit_premium * lot_size + estimated_costs_per_lot
            risk_qty = math.floor(risk_engine.risk_budget() / risk_per_lot) if risk_per_lot > 0 else 0

            position_value_per_lot = premium * lot_size
            cap_qty = math.floor(risk_engine.position_capital_budget() / position_value_per_lot) if position_value_per_lot > 0 else 0

            lots = min(risk_qty, cap_qty)
            if lots <= 0:
                # Not enough risk/capital budget to take even 1 lot at current
                # settings — skip rather than show a meaningless "buy 0 lots" idea.
                # (This is the fix for "position size can become zero too easily":
                # instead of silently showing qty=0, we filter it out entirely.)
                return None

            total_risk = round(risk_per_lot * lots, 2)
            required_capital = round(position_value_per_lot * lots, 2)

            # STAGE 1.1 (Approach B): net-of-cost reward:risk, replacing the
            # previous pure theoretical-multiplier ratio. Applied AFTER the
            # DTE-tier target_mult/stop_mult adjustments above (per requirement),
            # using ONLY data already computed in this function — spread_pct
            # (the hard-reject filter's own variable) and
            # ESTIMATED_ROUND_TRIP_COST_PCT (already used for position-sizing's
            # risk_per_lot, a DIFFERENT calculation — using the same cost number
            # for two different purposes is not double-counting, it's the same
            # real cost applied to the two different things it actually affects).
            # Cost is defaulted to 0 extra spread (not invented) when bid/ask is
            # unavailable — the round-trip fee still applies as a baseline.
            total_cost_pct = (spread_pct if spread_pct is not None else 0.0) + ESTIMATED_ROUND_TRIP_COST_PCT
            net_reward_fraction = (target_mult - 1.0) - (total_cost_pct / 100.0)
            net_risk_fraction = (1.0 - stop_mult) + (total_cost_pct / 100.0)
            reward_risk = round(net_reward_fraction / max(net_risk_fraction, 0.01), 2)

            # Minimum reward:risk gate (Stage 1, CORRECTED after testing found
            # a regression): only applies to the Medium/Low DTE tiers, where
            # target/stop tightening was intentionally introduced — this is
            # where "reject a setup whose reward:risk got squeezed near expiry"
            # was actually meant to bite, per the original request. Deliberately
            # does NOT apply to "Higher DTE" (the unchanged baseline) — testing
            # found the pre-existing mid/low-IV bands (R:R 1.33 and 1.25) never
            # met 1.35 even before Stage 1 existed, so gating them here would
            # have silently broken "baseline behavior remains unchanged" for
            # what's likely the most common case in practice. Note: Higher-DTE's
            # DISPLAYED reward_risk is now also cost-adjusted (more honest), but
            # its ACCEPTANCE behavior is unaffected since no gate applies to it.
            MIN_REWARD_RISK = 1.35
            if dte_tier != "Higher DTE" and reward_risk < MIN_REWARD_RISK:
                return None

            return {
                "side": side, "strike": actual_strike, "premium": premium, "lots": lots,
                "lot_size": lot_size, "target_premium": target_premium,
                "stop_premium": stop_premium, "bias": bias,
                "target_pct": round((target_mult - 1.0) * 100, 0),
                "stop_pct": round((1.0 - stop_mult) * 100, 0),
                "spread_pct": spread_pct,
                "bid": bid_px, "ask": ask_px,
                "bid_qty": best_row.get(bid_qty_key), "ask_qty": best_row.get(ask_qty_key),
                "volume": best_row.get(vol_key),
                "estimated_costs_per_lot": round(estimated_costs_per_lot, 2),
                "strike_offset_steps": strike_offset_steps,
                "reward_risk": reward_risk,
                "total_risk": total_risk,
                "required_capital": required_capital,
                "dte": dte, "dte_tier": dte_tier,
                "signal_generated_at": datetime.datetime.now(IST).strftime("%d-%b-%Y %I:%M %p"),
            }
        except Exception as e:
            LOGGER.debug("Suppressed exception: %s", e)
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

    # STAGE 2B: interpret the (unchanged) recommendation output against the
    # persisted previous signal — does not alter what generate_ranked_
    # recommendations/build_option_recommendation return in any way.
    def _live_premium_lookup(strike, direction):
        side_key = "Call LTP" if direction == "CE" else "Put LTP"
        for row in chain_rows:
            row_strike_str = str(row.get("Strike", "")).replace("🎯 ", "").strip()
            try:
                if float(row_strike_str) == float(strike):
                    val = str(row.get(side_key, "")).replace("₹", "").replace(",", "")
                    return float(val) if val and val != "N/A" else None
            except (ValueError, TypeError):
                continue
        return None

    lifecycle_status, lifecycle_signal = None, None
    if using_live_chain and chain_rows:
        top_pick = recommendations[0] if recommendations else None
        had_previous_signal = get_active_signal(selected_opt_asset, selected_expiry) is not None
        try:
            lifecycle_status, lifecycle_signal = evaluate_signal_lifecycle(
                selected_opt_asset, selected_expiry, str(datetime.datetime.now(IST).date()),
                dte, top_pick, _live_premium_lookup,
            )
        except Exception as exc:
            LOGGER.warning("Signal lifecycle evaluation failed: %s", exc)
    else:
        had_previous_signal = False

    st.markdown("### 🎯 Recommended Options Trades")
    if is_stock_mode:
        sector_warning = check_sector_exposure_warning(selected_opt_asset, investment_capital, max_sector_exposure_pct)
        if sector_warning:
            st.warning(sector_warning)
    if using_stale_price:
        st.error(
            "⚠️ Live price feed unavailable right now — this recommendation is based on **yesterday's closing price**, "
            "not the current market. It will NOT reflect today's price action until the live quote connection recovers. "
            "Check the WEBSOCKET status in the sidebar."
        )
    if not using_live_chain:
        st.warning("⚠️ Live option chain unavailable — trade recommendations are disabled rather than generated from simulated data.")
    elif recommendations:
        mtf_status, mtf_detail = (None, None)
        if require_mtf_confirmation:
            with st.spinner("Checking 15-min / 1-hour trend confirmation..."):
                try:
                    mtf_status, mtf_detail = get_multi_timeframe_confirmation(live_key, access_token, market_bias)
                except Exception as exc:
                    LOGGER.warning("MTF confirmation failed: %s", exc)
                    mtf_status, mtf_detail = "Unavailable", {}
            if mtf_status == "Unavailable":
                st.caption("⚠️ Multi-timeframe data unavailable right now — showing recommendations without MTF filtering.")
            else:
                badge = "✅" if mtf_status.startswith("Aligned") else "⚠️"
                st.caption(f"{badge} **MTF Confirmation: {mtf_status}** · 15m: {mtf_detail.get('15m','N/A')} · 1H: {mtf_detail.get('1H','N/A')} · Daily: {mtf_detail.get('Daily','N/A')}")
                if mtf_status == "Mixed":
                    st.warning("Recommendations below are NOT confirmed across timeframes (15m/1H disagree with the daily bias) — filtered out since Multi-Timeframe Confirmation is enabled.")
                    recommendations = []

        strike_labels = {0: "ATM", 1: "1-OTM", 2: "2-OTM", 3: "3-OTM"}

        def _dte_warning_for(dte_display):
            if dte_display is None:
                return ""
            if dte_display <= 1:
                return " ⚠️ Expiry tomorrow" if dte_display == 1 else " ⚠️ Expiry today"
            elif dte_display <= 2:
                return " ⚠️ Expiry approaching"
            return ""

        # === WORKSTREAM A: Decision-first presentation. Every value below is
        # read from the SAME recommendation dicts already produced by
        # generate_ranked_recommendations — nothing here recalculates
        # anything. This block only changes how those existing values are
        # laid out on screen. ===
        if recommendations:
            best = recommendations[0]
            alternatives = recommendations[1:]
            best_label = strike_labels.get(best["strike_offset_steps"], f"{best['strike_offset_steps']}-OTM")
            best_dte_warning = _dte_warning_for(best.get("dte"))

            st.markdown("## 🎯 Best Trade")
            st.markdown(f"### BUY {selected_opt_asset} {int(best['strike'])} {best['side']}")
            st.caption(f"{best_label} · {best['bias']} bias · DTE {best.get('dte')} ({best.get('dte_tier','')}){best_dte_warning}")

            bc1, bc2, bc3, bc4 = st.columns(4)
            bc1.metric("Entry", f"₹{best['premium']:.2f}")
            bc2.metric("Target", f"₹{best['target_premium']}", f"+{best['target_pct']:.0f}%")
            bc3.metric("Stop", f"₹{best['stop_premium']}", f"-{best['stop_pct']:.0f}%")
            bc4.metric("R:R", f"{best['reward_risk']}x")

            bc5, bc6, bc7 = st.columns(3)
            bc5.metric("Position Size", f"{best['lots']} lot(s)", f"{best['lots'] * best['lot_size']} qty")
            bc6.metric("Capital Required", f"₹{best['required_capital']:,.0f}")
            bc7.metric("Capital at Risk", f"₹{best['total_risk']:,.0f}", f"{max_risk_pct:.1f}% budget")

            if lifecycle_status:
                status_labels = {
                    "NEW": "🆕 NEW", "REVALIDATED": "✅ REVALIDATED — same setup, independently reconfirmed today",
                    "EXIT_TARGET": "🎯 EXIT (Target hit)", "EXIT_STOP": "🛑 EXIT (Stop hit)",
                }
                st.markdown(f"**Status: {status_labels.get(lifecycle_status, lifecycle_status)}**")
            st.caption(f"Generated: {best.get('signal_generated_at', 'N/A')} — freshly evaluated this run, not carried over from a previous day.")

            if alternatives:
                st.markdown("#### Alternatives")
                for rank, r in enumerate(alternatives, start=2):
                    alt_label = strike_labels.get(r["strike_offset_steps"], f"{r['strike_offset_steps']}-OTM")
                    alt_dte_warning = _dte_warning_for(r.get("dte"))
                    st.markdown(
                        f"**#{rank} · {alt_label}** → BUY {selected_opt_asset} {int(r['strike'])} {r['side']} @ ~₹{r['premium']:.2f} "
                        f"· Target ~₹{r['target_premium']} · Stop ~₹{r['stop_premium']} · R:R {r['reward_risk']}x{alt_dte_warning}"
                    )

            with st.expander("Why this trade? ▾"):
                if market_bias_scores:
                    mbs = market_bias_scores
                    st.markdown(
                        f"**Directional Score:** Bull {mbs.get('bull_score','N/A')}/100 vs Bear {mbs.get('bear_score','N/A')}/100 "
                        f"(net {mbs.get('net_score','N/A'):+.1f}, needed ±{options_no_trade_threshold} minimum for a directional call) — "
                        f"replaces the old all-or-nothing rule where a single EMA20 tick alone could drive a recommendation."
                    )
                    factor_bits = []
                    if mbs.get("ema20") is not None:
                        factor_bits.append(f"Price {'above' if underlying_ltp > mbs['ema20'] else 'below'} EMA20 (₹{mbs['ema20']:,.2f})")
                    if mbs.get("vwap") is not None:
                        factor_bits.append(f"Price {'above' if underlying_ltp > mbs['vwap'] else 'below'} VWAP (₹{mbs['vwap']:,.2f})")
                    if mbs.get("rsi") is not None:
                        factor_bits.append(f"RSI {mbs['rsi']}")
                    factor_bits.append(f"MACD {'bullish' if mbs.get('macd_bullish') else 'bearish' if mbs.get('macd_bearish') else 'neutral'}")
                    if mbs.get("pcr") is not None:
                        factor_bits.append(f"PCR {mbs['pcr']:.2f}")
                    factor_bits.append(f"Volume {'confirmed' if mbs.get('volume_confirmed') else 'not confirmed'}")
                    st.caption(" · ".join(factor_bits))
                st.markdown(f"**Ranking:** ATM and nearby OTM strikes on the {best['bias']}-biased side are evaluated and ranked by reward:risk. "
                            f"#{1} shown above is the strongest; alternatives are the next-best by the same measure.")
                st.markdown(f"**DTE reasoning:** {best.get('dte_tier','N/A')} tier — target/stop bands are DTE-aware, tightening as expiry "
                            f"approaches since less time remains for the theoretical move to play out.")
                st.markdown(f"**Risk:Reward:** {best['reward_risk']}x, net of real transaction costs (spread + round-trip fees) — "
                            f"must clear 1.35 minimum for Medium/Low DTE tiers to be shown at all.")
                if best.get("spread_pct") is not None:
                    st.markdown(f"**Liquidity:** bid ₹{best.get('bid','N/A')} / ask ₹{best.get('ask','N/A')} · spread {best['spread_pct']}% · volume {best.get('volume','N/A')}")
                if require_mtf_confirmation:
                    if mtf_status == "Unavailable":
                        st.caption("⚠️ Multi-timeframe data unavailable right now — shown without MTF filtering.")
                    else:
                        badge = "✅" if mtf_status.startswith("Aligned") else "⚠️"
                        st.markdown(f"**Multi-Timeframe Confirmation:** {badge} {mtf_status} · 15m: {mtf_detail.get('15m','N/A')} · 1H: {mtf_detail.get('1H','N/A')} · Daily: {mtf_detail.get('Daily','N/A')}")
                st.caption(
                    "Position sized per your sidebar Capital & Risk settings — ideas that don't fit even 1 lot, or whose "
                    "reward:risk falls below 1.35 after DTE adjustment, are filtered out entirely, never shown ranked-low. "
                    "Not investment advice — check liquidity before sizing up."
                )
        if not recommendations:
            # recommendations may have been reset to [] by the MTF-mixed
            # filter above even though we're inside this branch — these
            # NO TRADE messages are unchanged from before, just no longer
            # preceded by a duplicate caption (that reasoning now lives in
            # the "Why this trade?" expander above, shown once, not twice).
            if require_mtf_confirmation and mtf_status == "Mixed":
                pass  # warning already shown above
            elif dte is not None and dte <= 0:
                st.info("⚪ **NO TRADE — Expiry day.** Theta decay is near-total and spreads widen sharply on expiry day; this app doesn't recommend directional options buys with 0 DTE.")
            elif lifecycle_status == "NO_TRADE" and lifecycle_signal is None:
                st.info("⚪ **NO TRADE.** Previous signal is no longer valid under current market conditions." if
                         had_previous_signal else
                         "⚪ **NO TRADE.** Current conditions don't provide a sufficiently strong risk-adjusted setup.")
            else:
                st.info("⚪ **NO TRADE.** Current setups don't clear the minimum 1.35 reward:risk bar once DTE-adjusted target/stop bands are applied — a weak setup near expiry is downgraded to no recommendation rather than shown anyway.")

        with st.expander("📜 Signal History", expanded=False):
            history = get_signal_history(selected_opt_asset, selected_expiry) if using_live_chain else []
            if history:
                st.dataframe(pd.DataFrame(history), width='stretch', hide_index=True)
            else:
                st.caption("No signal history yet for this underlying/expiry.")
    else:
        score_suffix = f" (Bull {market_bias_scores['bull_score']}/100 vs Bear {market_bias_scores['bear_score']}/100 — needed ±{options_no_trade_threshold} minimum)" if market_bias_scores else ""
        st.info(f"Market bias is currently **{market_bias}**{score_suffix} — no high-conviction directional options trade to recommend right now.")

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
        st.dataframe(chain_df, width='stretch', hide_index=True)
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
                except Exception as e:
                    LOGGER.debug("Suppressed exception: %s", e)
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

                # Deliberately fixed 1-lot reference here (not risk-sized) — this
                # tab's own caption below explains it's a setup only.
                lots = 1
                st.success(
                    f"**{fut_bias} trend** → {direction} **{fut_symbol}** @ ~₹{entry:,.2f} (lot size {lot_size}) · "
                    f"Target ~₹{target:,.2f} · Stop ~₹{stop:,.2f}"
                )
                st.caption("Setup only — no position sizing or capital/margin figures shown; size your own quantity per your own risk management.")
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

    if NSE_UNIVERSE_VALIDATION_FAILED:
        if NSE_INSTRUMENT_LOAD_EXCEPTION:
            st.error(
                "⚠️ **Full NSE unavailable**\n\n"
                "The NSE instrument master could not be downloaded/parsed at all (an error occurred during loading — "
                "check Streamlit Cloud's logs for `NSE_UNIVERSE_DIAG: EXCEPTION` for the exact error). This is a "
                "**download failure**, not a small-but-valid universe.\n\n"
                "Full NSE is blocked until this resolves. **Quick Scan remains available.**"
            )
        else:
            st.error(
                f"⚠️ **Full NSE unavailable**\n\n"
                f"NSE instrument universe validation failed.\n\n"
                f"Loaded: **{len(all_nse_tickers)}**\n\n"
                f"Expected: a complete NSE equity universe (several thousand).\n\n"
                f"This indicates a loading/filtering bug, not a legitimately small NSE. Check Streamlit Cloud's logs "
                f"for lines starting with `NSE_UNIVERSE_DIAG:` for the exact cause.\n\n"
                f"Full NSE is blocked until this resolves. **Quick Scan remains available.**"
            )

    with st.expander("⚙️ Filters (optional — sensible defaults already applied)", expanded=False):
        col_h1, col_h2, col_h3 = st.columns(3)
        with col_h1:
            custom_days = st.number_input("Investment Horizon (Days)", min_value=1, max_value=365, value=15, step=1, key="eq_days_input")
        with col_h2:
            max_stock_price = st.number_input("Max Stock Price Filter (₹)", min_value=10.0, value=50000.0, step=500.0, key="eq_price_filter",
                                                help="Default is ₹50,000 — effectively no cap. Lowering this excludes higher-priced stocks like RELIANCE, TCS, etc.")
        with col_h3:
            require_weekly_align = st.checkbox("Require Weekly Uptrend Confirmation", value=False, key="eq_weekly_filter",
                                                 help="Stricter filter — leave off for more results, turn on to only see setups also confirmed on the weekly timeframe.")

        use_advanced_signal_filters = st.checkbox(
            "🎯 Advanced Signal Filters (False Breakout Filter + No-Trade Zone)", value=False, key="eq_advanced_filters",
            help="OFF by default since it further reduces results. False Breakout Filter requires ADX, "
                 "volume, and ATR to all be genuinely rising before accepting a setup — rejects breakouts "
                 "that lack real conviction behind them. No-Trade Zone suppresses signals entirely during "
                 "choppy, low-volume, mixed-timeframe conditions where forcing a trade tends to lose. "
                 "Both only ever remove signals, never add new ones — turning this on can reduce your "
                 "result count, never increase it."
        )

        st.markdown("#### Scan Universe")
        scan_mode = st.radio(
            "Scan Mode",
            ["● Quick", "○ Full NSE"],
            horizontal=True, key="eq_scan_mode_simple",
            help=f"Quick: fast scan of {len(LIQUID_CORE_TICKERS)} liquid large/mid-cap stocks. Full NSE: the complete eligible NSE equity universe."
        )
        scan_mode = "Quick Scan" if "Quick" in scan_mode else "Full NSE Scan"

        if scan_mode.startswith("Quick"):
            universe_tickers = [t for t in LIQUID_CORE_TICKERS if t in instrument_dict] or LIQUID_CORE_TICKERS
            technical_candidate_limit = min(150, len(universe_tickers))
            scan_workers = 6
            st.caption(f"{len(universe_tickers)} liquid large/mid-cap stocks")
        else:
            total_nse = len(all_nse_tickers)
            # Backend-determined, not user-exposed: "Full NSE" means the entire
            # eligible universe gets quote-scanned; this only caps how many of
            # the diversified stage-1 shortlist go through the expensive
            # technical/history stage. 250 is a reasonable, tested default
            # balancing thoroughness vs scan time — same value that was
            # previously this slider's own default before anyone touched it,
            # now just applied automatically instead of asked as a question
            # the user has no principled way to answer.
            technical_candidate_limit = min(250, max(100, total_nse))
            universe_tickers = list(all_nse_tickers)
            scan_workers = min(12, max(6, technical_candidate_limit // 25))
            st.caption(f"{total_nse} eligible NSE equities")

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

    try:
        breadth = compute_market_breadth(access_token)
    except Exception as exc:
        LOGGER.warning("Market breadth computation failed: %s", exc)
        breadth = None
    try:
        nifty_quote = get_live_market_quotes(["NSE_INDEX|Nifty 50"], access_token)
        nifty_quote = nifty_quote.get("NSE_INDEX|Nifty 50") if nifty_quote else None
        # PERFORMANCE FIX: fetch_upstox_history() has no caching — it would hit
        # the network on every single rerun (every 5-15s via autorefresh).
        # Routed through get_cached_history() instead, the same SQLite-cached
        # path compute_market_breadth already uses correctly, so this only
        # actually re-fetches once the cached data goes stale (once/day).
        vix_hist_df = get_cached_history("NSE_INDEX|India VIX", access_token, days=280, fetch_fn=_fetch_upstox_history_impl)
        regime = compute_market_regime(nifty_hist_df, nifty_quote, vix_hist_df, vix_value, breadth["breadth_score"] if breadth else None)
    except Exception as exc:
        LOGGER.warning("Market regime computation failed: %s", exc)
        regime = None

    st.markdown("#### 🌐 Market Regime")
    _regime_labels_small = {
        "TRENDING_BULL": "🟢 Bullish", "TRENDING_BEAR": "🔴 Bearish",
        "SIDEWAYS": "🟡 Sideways", "HIGH_VOLATILITY": "🟠 High Volatility",
        "PANIC": "🔴 Panic", "EUPHORIA": "🟢 Euphoria (extended)",
    }
    _risk_labels_small = {
        "TRENDING_BULL": "Normal", "TRENDING_BEAR": "Elevated",
        "SIDEWAYS": "Normal", "HIGH_VOLATILITY": "Elevated",
        "PANIC": "High — reduce size", "EUPHORIA": "Elevated — extended market",
    }
    if regime:
        smc1, smc2 = st.columns(2)
        smc1.metric("Market Regime", _regime_labels_small.get(regime["regime"], regime["regime"]))
        smc2.metric("Risk", _risk_labels_small.get(regime["regime"], "Normal"))
    else:
        st.caption("Market regime unavailable right now.")

    with st.expander("Market Details ▾ (breadth, VIX, sector leaders/laggards)", expanded=False):
        if regime:
            regime_labels = {
                "TRENDING_BULL": "🟢 Trending Bull", "TRENDING_BEAR": "🔴 Trending Bear",
                "SIDEWAYS": "🟡 Sideways / Choppy", "HIGH_VOLATILITY": "🟠 High Volatility",
                "PANIC": "🔴 Panic", "EUPHORIA": "🟢 Euphoria (extended)",
            }
            rc1, rc2, rc3, rc4 = st.columns(4)
            rc1.metric("Market Regime", regime_labels.get(regime["regime"], regime["regime"]))
            rc2.metric("Regime Score (ADX %ile)", f"{regime['regime_score']:.0f}/100")
            rc3.metric("NIFTY ADX", f"{regime['adx']:.1f}" + (f" ({regime['adx_percentile']:.0f}th %ile)" if regime['adx_percentile'] is not None else "") if regime['adx'] is not None else "N/A")
            rc4.metric("India VIX", f"{regime['vix']:.1f}" + (f" ({regime['vix_percentile']:.0f}th %ile)" if regime['vix_percentile'] is not None else "") if regime['vix'] is not None else "N/A")
            if regime.get("adaptive"):
                st.caption("Adaptive: classification uses each metric's own 252-day percentile rank, not a fixed number — Regime Score is literally NIFTY's ADX percentile, a real measured value.")
            else:
                st.caption("⚠️ Not enough history yet for percentile ranking — using fixed fallback thresholds until more data is cached.")
            if regime["regime"] in ("PANIC", "HIGH_VOLATILITY"):
                st.caption("⚠️ Elevated-risk regime — consider smaller position sizes or wider stops regardless of individual signal quality.")
        else:
            st.caption("Market regime unavailable right now.")

        if breadth:
            bc1, bc2, bc3, bc4 = st.columns(4)
            bc1.metric("Advance / Decline", f"{breadth['advances']} / {breadth['declines']}")
            bc2.metric("% Above 50-DMA", f"{breadth['pct_above_50dma']:.0f}%" if breadth['pct_above_50dma'] is not None else "N/A")
            bc3.metric("New Highs (sample)", breadth["new_highs"])
            bc4.metric("New Lows (sample)", breadth["new_lows"])
            st.caption(
                f"Large/Mid-Cap Breadth Score: {breadth['breadth_score']:.0f}/100 · sampled {breadth['total_sampled']} liquid stocks "
                f"(not the full NSE universe — a proxy from your liquid large/mid-cap list, not full-market breadth)."
            )
        else:
            st.caption("Market breadth unavailable right now.")

        st.markdown("#### 🏭 Sector Leaders & Laggards")
        st.caption("Which sectors are leading or lagging the market right now, by average Relative Strength vs NIFTY across liquid stocks in each sector. Informational only — doesn't affect the stock picks above.")
        try:
            sector_rows, sector_used_fallback = compute_sector_strength(access_token)
        except Exception as exc:
            LOGGER.warning("Sector strength computation failed: %s", exc)
            sector_rows, sector_used_fallback = [], False

        # Minimum sample-size guard: an "average" from 1-2 stocks is statistically
        # meaningless and shouldn't be shown with the same visual confidence as a
        # sector sampled with 15-20 stocks. Filter those out rather than display
        # a precise-looking number backed by almost no data.
        MIN_SECTOR_SAMPLE = 3
        low_sample_sectors = [r["sector"] for r in sector_rows if r["stock_count"] < MIN_SECTOR_SAMPLE]
        sector_rows = [r for r in sector_rows if r["stock_count"] >= MIN_SECTOR_SAMPLE]

        if sector_rows:
            if sector_used_fallback:
                st.caption("⚠️ Live quotes unavailable — based on the last completed session instead.")
            if low_sample_sectors:
                st.caption(f"Hidden (fewer than {MIN_SECTOR_SAMPLE} stocks sampled, not statistically meaningful): {', '.join(low_sample_sectors)}")
            sector_df = pd.DataFrame(sector_rows).rename(columns={
                "sector": "Sector", "avg_rs": "Avg RS vs NIFTY", "stock_count": "Stocks Sampled"
            })
            ssc1, ssc2 = st.columns(2)
            with ssc1:
                st.markdown("**🟢 Leading Sectors**")
                st.dataframe(
                    sector_df.head(5).style.format({"Avg RS vs NIFTY": "{:+.2f}"})
                    .map(lambda v: f"color: {'#2ecc71' if v >= 0 else '#e74c3c'}", subset=["Avg RS vs NIFTY"]),
                    width='stretch', hide_index=True
                )
            with ssc2:
                st.markdown("**🔴 Lagging Sectors**")
                st.dataframe(
                    sector_df.tail(5).sort_values("Avg RS vs NIFTY").style.format({"Avg RS vs NIFTY": "{:+.2f}"})
                    .map(lambda v: f"color: {'#2ecc71' if v >= 0 else '#e74c3c'}", subset=["Avg RS vs NIFTY"]),
                    width='stretch', hide_index=True
                )
        else:
            st.caption("Sector strength unavailable right now (no quote or historical data reachable, or all sectors below minimum sample size).")

    st.markdown(f"### 🚀 Top Institutional Stock Setups {'🔺 (High VIX — Tightened Stops)' if volatility_regime.startswith('High') else ''}")

    run_scan_now = True
    if scan_mode.startswith("Full"):
        if NSE_UNIVERSE_VALIDATION_FAILED:
            # BLOCK, per explicit requirement — do not send quotes for a
            # fake/partial universe, do not run expensive analysis, do not
            # let the button even attempt a scan against an invalid universe.
            st.button(
                "🔍 Full NSE Unavailable",
                key="eq_run_full_scan_btn",
                type="primary",
                width='stretch',
                disabled=True,
                help="Blocked because the loaded NSE universe failed validation — see the error above. Quick Scan remains available."
            )
            run_scan_now = False
            if "last_full_scan_signals" in st.session_state:
                del st.session_state["last_full_scan_signals"]  # never show a stale/partial Full NSE result as current
            valid_signals = []
        else:
            run_scan_now = st.button(
                "🔍 Run Full NSE Quant Scan",
                key="eq_run_full_scan_btn",
                type="primary",
                width='stretch',
                help="Quote-scan the full NSE universe, then run heavy technical analysis only on diversified candidates."
            )
            if not run_scan_now and "last_full_scan_signals" in st.session_state:
                valid_signals = st.session_state["last_full_scan_signals"]
    else:
        # Auto-run once per session on first visit — after that, reuse the cached
        # result and only re-scan when explicitly asked. This gives "zero clicks"
        # for the first view without silently re-running an expensive full
        # historical+indicator scan on every 15s autorefresh cycle in the background,
        # which would burn through Upstox API quota for no benefit.
        already_scanned_this_session = "last_quick_signals" in st.session_state
        if not already_scanned_this_session:
            st.caption("🚀 Auto-running your first scan now — no click needed...")
            run_scan_now = True
        else:
            run_scan_now = st.button("🔄 Refresh Results", key="eq_run_quick_btn", width='stretch')
            if not run_scan_now:
                valid_signals = st.session_state["last_quick_signals"]

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
        scan_timing = {}
        _t0 = time.perf_counter()
        active_scan_keys = [instrument_dict.get(t) for t in universe_tickers if instrument_dict.get(t)]
        live_quote_data = get_live_scan_market_data(active_scan_keys, access_token)
        scan_timing["quote_retrieval_secs"] = round(time.perf_counter() - _t0, 2)

        _t1 = time.perf_counter()
        stage1_shortlist, funnel_stats = stage1_multi_bucket_prefilter(
            universe_tickers,
            instrument_dict,
            live_quote_data,
            technical_candidate_limit,
            DEFAULT_DB_PATH,
        )
        scan_timing["funnel_secs"] = round(time.perf_counter() - _t1, 2)
        funnel_stats = dict(funnel_stats or {})
        funnel_stats.setdefault("universe_size", len(universe_tickers))
        funnel_stats.setdefault("quoted", 0)
        funnel_stats.setdefault("no_quote", max(len(universe_tickers) - funnel_stats.get("quoted", 0), 0))
        funnel_stats.setdefault("shortlisted", len(stage1_shortlist))
        funnel_stats.setdefault("session_fraction", _session_elapsed_fraction())
        funnel_stats.setdefault("bucket_counts", {})
        st.session_state["last_stage1_shortlist"] = stage1_shortlist

        # DECOMPOSING expensive_analysis_secs (measurement only, per explicit
        # request — zero algorithm/control-flow changes). A plain list append
        # is used rather than threading timing through evaluate_stock's return
        # tuple (which would touch all ~15 existing return points again — the
        # exact pattern that's caused real bugs earlier tonight). list.append()
        # from multiple ThreadPoolExecutor worker threads onto the SAME list is
        # safe in CPython specifically (GIL-protected), which is what this app
        # runs on. Aggregated into a summary AFTER the executor completes, in
        # the main thread, alongside where rejection_counts already gets
        # finalized the same way.
        analysis_timing_log = []

        def evaluate_stock(ticker):
            # REDESIGN NOTE: every `return None` below now returns
            # `None, {"category": ..., "reason": ...}` instead — a companion
            # rejection reason, added alongside the existing decision, not
            # replacing it. Every threshold and condition below is UNCHANGED
            # from before; this only makes the existing decision visible
            # instead of silent, per "do not change prediction logic yet."
            try:
                key = instrument_dict.get(ticker)
                if not key:
                    return None, {"category": "Data", "reason": "No instrument key found for this ticker"}

                raw_quote = live_quote_data.get(key, {}) if live_quote_data else {}
                live_price = raw_quote.get("last_price")

                # LOOKBACK CORRECTNESS FIX: compute_walk_forward_probability needs
                # train_window(250) + test_window(60) + horizon_days(15 default)
                # = 325 TRADING bars, but that's checked AFTER indicator warmup
                # consumes rows via .dropna() — EMA_50's ~50-row warmup is the
                # binding constraint among the 5 indicators it computes (EMA_20,
                # EMA_50, ADX, RSI, ATR), so the TRUE minimum is ~375 raw trading
                # bars, not 325. days=400 CALENDAR days only yields ~270-280
                # TRADING days (confirmed: this environment has no network access
                # to empirically verify pandas-ta's exact warmup row count, so a
                # generous buffer is used rather than a razor-thin exact figure).
                # 750 calendar days, combined with get_cached_history's existing
                # required_rows=days*0.55 sufficiency check, yields ~412 rows
                # before the cache is considered fresh — comfortably above 375
                # with real margin, and flows through the incremental-cache depth
                # check (also parameterized on `days`) automatically, with no
                # separate change needed there.
                _hist_t0 = time.perf_counter()
                df = get_cached_history(key, access_token, days=750, fetch_fn=_fetch_upstox_history_impl)
                if df.empty or len(df) < 210:
                    analysis_timing_log.append(("history_retrieval", time.perf_counter() - _hist_t0))
                    return None, {"category": "Data", "reason": "Insufficient price history (need 210+ trading days)"}

                df = prepare_live_daily_bar(df, raw_quote)
                analysis_timing_log.append(("history_retrieval", time.perf_counter() - _hist_t0))
                if df.empty or len(df) < 210:
                    return None, {"category": "Data", "reason": "Insufficient price history after live update"}

                price = float(live_price) if live_price and float(live_price) > 0 else float(df['Close'].iloc[-1])

                _indicators_t0 = time.perf_counter()
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
                analysis_timing_log.append(("indicators", time.perf_counter() - _indicators_t0))

                df_clean = df.dropna(subset=['EMA_20', 'EMA_50', 'EMA_200', 'ATR'])
                if df_clean.empty:
                    return None, {"category": "Data", "reason": "Indicators could not be computed (NaN in EMA/ATR)"}
                latest = df_clean.iloc[-1]

                if price > max_stock_price:
                    return None, {"category": "Price Filter", "reason": f"Price ₹{price:,.2f} exceeds your ₹{max_stock_price:,.0f} filter"}
                if price < float(latest['EMA_50']):
                    return None, {"category": "Trend", "reason": "Price is below the 50-day EMA"}
                if require_weekly_align and weekly_trend != "Bullish (Weekly)":
                    return None, {"category": "Weekly Trend", "reason": f"Weekly trend is '{weekly_trend}', not confirmed Bullish"}

                if not bool(supertrend_bullish):
                    return None, {"category": "Trend", "reason": "SuperTrend indicator is bearish"}
                if float(latest['EMA_20']) < float(latest['EMA_50']):
                    return None, {"category": "Trend", "reason": "20-day EMA is below the 50-day EMA"}

                atr_val = float(latest['ATR'])
                if not np.isfinite(atr_val) or atr_val <= 0:
                    return None, {"category": "Data", "reason": "Invalid ATR (zero or non-finite)"}

                if use_advanced_signal_filters:
                    _breakout_t0 = time.perf_counter()
                    adx_val = float(latest['ADX']) if pd.notna(latest['ADX']) else None
                    current_vol = float(latest['Volume']) if pd.notna(latest.get('Volume')) else 0.0
                    avg_vol20 = float(df_clean['Volume'].tail(20).mean()) if 'Volume' in df_clean.columns else 0.0

                    # No-Trade Zone: choppy ADX (18-22) + low volume + weekly not
                    # confirming the daily/supertrend direction = a transitional,
                    # low-conviction period. Skip rather than force a trade.
                    is_choppy_adx = adx_val is not None and 18 <= adx_val <= 22
                    is_low_volume = avg_vol20 > 0 and current_vol < avg_vol20 * 0.7
                    timeframes_mixed = weekly_trend != "Bullish (Weekly)"
                    if is_choppy_adx and is_low_volume and timeframes_mixed:
                        analysis_timing_log.append(("false_breakout_filter", time.perf_counter() - _breakout_t0))
                        return None, {"category": "Volume", "reason": "No-Trade Zone: choppy ADX, low volume, and weekly trend not confirming"}

                    # False Breakout Filter: require ADX, volume, AND ATR to all
                    # genuinely be rising vs a few sessions ago — a breakout without
                    # rising participation/volatility behind it is more likely fake.
                    if len(df_clean) >= 11:
                        adx_prev = float(df_clean['ADX'].iloc[-6]) if pd.notna(df_clean['ADX'].iloc[-6]) else None
                        atr_prev = float(df_clean['ATR'].iloc[-6]) if pd.notna(df_clean['ATR'].iloc[-6]) else None
                        vol_prev_avg = float(df_clean['Volume'].iloc[-11:-6].mean())
                        adx_rising = adx_val is not None and adx_prev is not None and adx_val > adx_prev
                        atr_expanding = atr_val > atr_prev if atr_prev is not None else False
                        vol_rising = vol_prev_avg > 0 and current_vol > vol_prev_avg
                        if not (adx_rising and atr_expanding and vol_rising):
                            analysis_timing_log.append(("false_breakout_filter", time.perf_counter() - _breakout_t0))
                            return None, {"category": "Volume", "reason": "Breakout not confirmed: ADX, volume, and ATR aren't all rising together"}
                    analysis_timing_log.append(("false_breakout_filter", time.perf_counter() - _breakout_t0))

                sl, tgt, rr_ratio, levels = derive_long_trade_levels(
                    df_clean, price, atr_val, horizon_days=custom_days
                )
                if sl is None or tgt is None or rr_ratio is None or rr_ratio < 1.35:
                    return None, {"category": "Risk:Reward", "reason": f"Reward:Risk {round(rr_ratio, 2) if rr_ratio is not None else 'N/A'} is below the 1.35 minimum"}

                risk_per_share = risk_engine.calculate_risk_per_unit(price, sl)
                if risk_per_share <= 0:
                    return None, {"category": "Data", "reason": "Invalid risk-per-share calculation"}
                # Reference qty for this screener signal (shows risk % per share
                # separately below) — not risk-sized like the options recommendations.
                qty_to_buy = 1

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
                volume_pace_ratio = min(current_day_volume / avg_vol20 / elapsed_fraction, 5.0) if avg_vol20 > 0 and elapsed_fraction > 0 else None

                # Walk-Forward OOS Probability Calibration Engine
                _wf_t0 = time.perf_counter()
                wf_result = compute_walk_forward_probability(df_clean, horizon_days=custom_days)
                analysis_timing_log.append(("walk_forward", time.perf_counter() - _wf_t0))
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

                # PHASE 1/2 — Trend Quality & Volume Quality Engines: shown as
                # separate, clearly-labeled columns rather than blended into the
                # existing `score` composite above. There's real conceptual
                # overlap between these and the existing trend_score/adx_score/
                # volume_score components — silently merging them without
                # re-validating the existing (already-working) composite would
                # risk changing signal_strength/Conviction results in ways not
                # yet tested. Shown side-by-side so you can compare, not replace.
                _tq_t0 = time.perf_counter()
                trend_quality = compute_trend_quality_score(df_clean)
                analysis_timing_log.append(("trend_quality", time.perf_counter() - _tq_t0))
                _vq_t0 = time.perf_counter()
                volume_quality = compute_volume_quality_score(df_clean)
                analysis_timing_log.append(("volume_quality", time.perf_counter() - _vq_t0))
                # PHASE 3 — Breakout Quality Engine: composed from the two
                # functions above (already computed, passed in — zero duplicate
                # calculation) plus ATR expansion, ADX percentile, and RS.
                breakout_quality = compute_breakout_quality_score(
                    df_clean, rs_vs_nifty=rs_vs_nifty,
                    trend_quality=trend_quality, volume_quality=volume_quality,
                )

                if use_advanced_signal_filters and breakout_quality is not None:
                    # Extends the EXISTING opt-in Advanced Signal Filters toggle
                    # (built earlier this session, off by default) rather than
                    # adding a second, separate always-on gate — "reject weak
                    # breakouts" per Phase 3, applied only when the person has
                    # already chosen the stricter filtering mode.
                    if breakout_quality["score"] < 40:
                        return None, {"category": "Volume", "reason": f"Breakout Quality score {breakout_quality['score']:.0f}/100 is below the 40 minimum"}

                return {
                    "Ticker": ticker,
                    "Sector": ticker_sector,
                    "Live Price": f"₹{price:,.2f}",
                    "Action": "BUY",
                    "Target": f"₹{tgt:,.2f}",
                    "Stop Loss": f"₹{sl:,.2f}",
                    "Conviction": conviction,
                    "Signal Strength": signal_strength,
                    "Trend Quality": f"{trend_quality['score']:.0f} ({trend_quality['label']})" if trend_quality else "N/A",
                    "Volume Quality": f"{volume_quality['score']:.0f} ({volume_quality['label']})" if volume_quality else "N/A",
                    "Breakout Quality": f"{breakout_quality['score']:.0f} ({breakout_quality['label']})" if breakout_quality else "N/A",
                    "RVOL (raw)": f"{volume_quality['rvol']:.2f}x" if volume_quality else "N/A",
                    "RVOL (session-adj.)": (f"{volume_quality['session_adjusted_rvol']:.2f}x" + ("" if volume_quality['is_session_adjusted'] else " *")) if volume_quality else "N/A",
                    "R-Multiple": f"{r_multiple}R",
                    "Risk Summary": f"Risk {risk_pct:.1f}% → Reward +{exp_return_pct:.1f}% (1:{r_multiple})",
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
                    # Real components of the ACTUAL ranking formula (score),
                    # captured here so "Institutional Score Breakdown" and "Why
                    # Selected" can show the true drivers of selection — not the
                    # separate Trend/Volume/Breakout Quality engines, which are
                    # informational only and don't affect ranking (confirmed in
                    # the earlier audit this session).
                    "_score_components": {
                        "Trend": (trend_score, 0.15), "Momentum": (momentum_score, 0.12),
                        "Volume": (volume_score, 0.10), "Relative Strength": (rs_score, 0.10),
                        "Risk:Reward": (rr_score, 0.15), "ADX Strength": (adx_score, 0.08),
                        "Volatility Fit": (volatility_score, 0.06), "Historical Edge": (edge_score, 0.10),
                        "Momentum/Beta Factor": (factor_score, 0.14),
                    },
                    "_sl": float(sl), "_tgt": float(tgt),
                    "_resistance60": float(levels.get("resistance60")) if levels and levels.get("resistance60") else None,
                    "_risk_per_share": float(risk_per_share),
                    "score": float(score),
                }, None
            except Exception as exc:
                LOGGER.debug("evaluate_stock failed for %s: %s", ticker, exc)
                return None, {"category": "Error", "reason": f"Unexpected error: {exc}"}

        valid_signals = []
        rejection_examples = []  # a few sample reasons per category, for display
        rejection_counts = {}
        _t2 = time.perf_counter()
        progress_bar = st.progress(0, text="Analyzing shortlist with Walk-Forward calibration & Multi-Factor scoring...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=scan_workers) as executor:
            futures = {executor.submit(evaluate_stock, ticker): ticker for ticker in stage1_shortlist}
            completed = 0
            for future in concurrent.futures.as_completed(futures):
                completed += 1
                ticker = futures[future]
                progress_bar.progress(completed / max(len(futures), 1), text=f"Analyzed {completed}/{len(futures)} — {ticker}")
                try:
                    result, rejection = future.result()
                    if result:
                        valid_signals.append(result)
                    elif rejection:
                        category = rejection.get("category", "Other")
                        rejection_counts[category] = rejection_counts.get(category, 0) + 1
                        if len(rejection_examples) < 40:
                            rejection_examples.append({"Ticker": ticker, "Category": category, "Reason": rejection.get("reason", "")})
                except Exception as exc:
                    LOGGER.exception("Unexpected worker failure for %s", ticker)
            progress_bar.empty()
        scan_timing["expensive_analysis_secs"] = round(time.perf_counter() - _t2, 2)

        # Aggregate the per-stage timing log collected above (measurement only,
        # zero effect on which stocks pass/fail or their scores).
        analysis_breakdown = {}
        for stage_name, elapsed in analysis_timing_log:
            entry = analysis_breakdown.setdefault(stage_name, {"total": 0.0, "count": 0})
            entry["total"] += elapsed
            entry["count"] += 1
        for stage_name, entry in analysis_breakdown.items():
            entry["total"] = round(entry["total"], 3)
            entry["avg"] = round(entry["total"] / entry["count"], 4) if entry["count"] else 0.0
        scan_timing["analysis_breakdown"] = analysis_breakdown

        # Honest disclosure: Relative Strength is currently a SCORING input only,
        # never a pass/fail gate anywhere in this function — so it's not possible
        # for anything to be genuinely rejected "for RS", and reporting a fake
        # count here would misrepresent how the screener actually works.
        rejection_counts.setdefault("Relative Strength", 0)
        st.session_state["last_rejection_counts"] = rejection_counts
        st.session_state["last_rejection_examples"] = rejection_examples
        st.session_state["last_funnel_stats"] = funnel_stats
        scan_timing["total_secs"] = round(sum(v for k, v in scan_timing.items() if k.endswith("_secs")), 2)
        st.session_state["last_scan_timing"] = scan_timing

        if scan_mode.startswith("Full"):
            st.session_state["last_full_scan_signals"] = valid_signals
        else:
            st.session_state["last_quick_signals"] = valid_signals

    if "valid_signals" not in locals():
        valid_signals = st.session_state.get("last_quick_signals" if scan_mode.startswith("Quick") else "last_full_scan_signals", [])
    rejection_counts = st.session_state.get("last_rejection_counts", {})
    rejection_examples = st.session_state.get("last_rejection_examples", [])
    funnel_stats = st.session_state.get("last_funnel_stats", {})

    def select_diversified_top_n(signals, n=10, corr_threshold=0.75, max_sector_pct=30.0):
        if not signals:
            return []
        # No capital-based heat budget anymore — diversification is by correlation/sector only.
        heat_budget = float('inf')
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
                except Exception as e:
                    LOGGER.debug("Suppressed exception: %s", e)
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

    total_rejected = sum(rejection_counts.values())
    if rejection_counts or valid_signals:
        with st.expander(f"Diagnostics ▾ — {len(valid_signals)} passed, {total_rejected} rejected", expanded=not valid_signals):
            st.markdown("**Scan Summary**")
            sm1, sm2, sm3, sm4 = st.columns(4)
            sm1.metric("Universe", funnel_stats.get("universe_size", "N/A"))
            sm2.metric("Quotes received", funnel_stats.get("quoted", "N/A"))
            analyzed = len(valid_signals) + total_rejected
            sm3.metric("Successfully analyzed", analyzed)
            sm4.metric("Final picks", len(valid_signals))
            scan_timing_display = st.session_state.get("last_scan_timing", {})
            if scan_timing_display:
                st.markdown("**Scan Timing** (real measured values — first honest baseline, per the Workstream B investigation)")
                tm1, tm2, tm3, tm4, tm5 = st.columns(5)
                tm1.metric("Quote Retrieval", f"{scan_timing_display.get('quote_retrieval_secs', 0):.2f}s")
                tm2.metric("Funnel", f"{scan_timing_display.get('funnel_secs', 0):.2f}s")
                tm3.metric("Analysis", f"{scan_timing_display.get('expensive_analysis_secs', 0):.2f}s")
                tm4.metric("Ranking", f"{scan_timing_display.get('ranking_secs', 0):.2f}s")
                tm5.metric("Total (scan)", f"{scan_timing_display.get('total_secs', 0):.2f}s")
                st.caption("'Total (scan)' does not yet include Ranking, which runs in a separate code path — sum Analysis + Ranking for the true end-to-end figure until this is unified.")
                breakdown = scan_timing_display.get("analysis_breakdown", {})
                if breakdown:
                    st.markdown("**Analysis Stage Breakdown** (sum of per-candidate time across the whole scan — candidates run in parallel, so this total can exceed the wall-clock Analysis time above)")
                    bd_rows = [{"Stage": k, "Total (s)": v["total"], "Calls": v["count"], "Avg/call (s)": v["avg"]} for k, v in sorted(breakdown.items(), key=lambda x: -x[1]["total"])]
                    st.dataframe(pd.DataFrame(bd_rows), width='stretch', hide_index=True)
            st.markdown("**Data issues (by category)**")
            if rejection_counts:
                rc_cols = st.columns(len(rejection_counts))
                for i, (category, count) in enumerate(sorted(rejection_counts.items(), key=lambda x: -x[1])):
                    label = category if category != "Relative Strength" else "Relative Strength *"
                    rc_cols[i].metric(f"{label}", count)
                st.caption("* Relative Strength is currently a scoring input only — it never rejects a candidate anywhere in this screener, so this will always read 0. Shown for completeness, not because it's a real filter yet.")
            if rejection_examples:
                st.markdown("**Sample rejected candidates:**")
                st.dataframe(pd.DataFrame(rejection_examples), width='stretch', hide_index=True)

    if valid_signals:
        _t3 = time.perf_counter()
        valid_signals = select_diversified_top_n(valid_signals, n=10, corr_threshold=0.75, max_sector_pct=30.0)
        _ranking_secs = round(time.perf_counter() - _t3, 2)
        # Ranking runs OUTSIDE the run_scan_now block (it also applies when
        # displaying session-state-cached results from a prior scan), so
        # `scan_timing` isn't reliably in local scope here — updating
        # session_state directly instead, merging with whatever timing data
        # already exists there rather than requiring it to be freshly defined
        # this rerun. This closes the real gap found during Step 2's trace:
        # ranking was previously entirely unmeasured.
        _existing_timing = dict(st.session_state.get("last_scan_timing", {}))
        _existing_timing["ranking_secs"] = _ranking_secs
        st.session_state["last_scan_timing"] = _existing_timing
        st.session_state["last_screener_results"] = valid_signals

        best = valid_signals[0]
        st.success(
            f"🏆 **Top Pick: {best['Ticker']} ({best['Sector']})** — Buy at {best['Live Price']}, "
            f"Target {best['Target']}, Stop {best['Stop Loss']} ({best['Conviction']} conviction, "
            f"OOS Win Prob {best['OOS Win Prob']}, R:R {best['Risk:Reward']})"
        )

        # 'Risk %', 'Exp Return', 'Risk:Reward' stay in the underlying dict
        # (still used below for the avg-risk aggregate metric) but are hidden
        # from the table now that 'Risk Summary' consolidates all three into
        # one readable field — same numbers, one column instead of three.
        # (hidden_cols removed — was only used by the old flat dataframe table,
        # replaced by the card rendering below; csv_hidden_cols below still
        # controls what goes into the CSV export)
        # (df_display_cols removed — was only used by the old flat dataframe
        # table, replaced by the card rendering below)

        # Requirement (this redesign): simple ranked Top Stocks list — no
        # score components, no bucket expanders, no internal funnel/candidate
        # details. Uses the EXISTING "Signal Strength" field unchanged — this
        # only changes how results are DISPLAYED, not which stocks passed or
        # what their score is.
        st.markdown(f"##### {len(valid_signals)} Institutional Equities — {custom_days}-Day Horizon (Under ₹{max_stock_price:,.0f})")

        def _render_risk_card(sig):
            """Requirement 1: trader-friendly risk card, per stock. All numbers
            here are re-derived from values evaluate_stock already computed —
            nothing new is calculated, this only presents it more usably."""
            entry = sig["_price_val"]
            sl_val, tgt_val = sig["_sl"], sig["_tgt"]
            resistance60 = sig.get("_resistance60")
            risk_per_share = sig["_risk_per_share"]

            # Genuine risk-based position size using the SAME risk_engine already
            # used for Options recommendations elsewhere in this app — the
            # screener's own "_qty" stays a fixed reference (1 share, unchanged,
            # per the existing documented design), this is a separate, real
            # sizing calculation for the card, driven by your sidebar Capital &
            # Risk settings. Doesn't change which stocks are selected or ranked.
            risk_qty = math.floor(risk_engine.risk_budget() / risk_per_share) if risk_per_share > 0 else 0
            cap_qty = math.floor(risk_engine.position_capital_budget() / entry) if entry > 0 else 0
            real_qty = max(min(risk_qty, cap_qty), 0)
            capital_required = entry * real_qty

            cc1, cc2, cc3, cc4 = st.columns(4)
            cc1.metric("Entry", f"₹{entry:,.2f}")
            cc2.metric("Stop Loss", f"₹{sl_val:,.2f}")
            cc3.metric("Target 1", f"₹{tgt_val:,.2f}")
            if resistance60 and resistance60 > tgt_val:
                cc4.metric("Target 2 (extended)", f"₹{resistance60:,.2f}")
            else:
                cc4.metric("Target 2", "N/A")
            if resistance60 and resistance60 > tgt_val:
                st.caption("Target 2 is the 60-day resistance level, shown as a further extension zone — not a separately validated profit target the way Target 1 is.")

            cc5, cc6, cc7, cc8 = st.columns(4)
            cc5.metric("Risk:Reward", sig["Risk:Reward"] if "Risk:Reward" in sig else f"1:{sig.get('R-Multiple', 'N/A')}")
            cc6.metric("Position Size", f"{real_qty} shares" if real_qty > 0 else "Below min. size")
            cc7.metric("Capital Required", f"₹{capital_required:,.0f}" if real_qty > 0 else "N/A")
            cc8.metric("Confidence", sig["Conviction"])

        def _render_score_breakdown(sig):
            """Requirement 2: real weighted components of the actual ranking
            score — not the separate Trend/Volume/Breakout Quality engines,
            which don't affect ranking. Weekly Trend is shown separately since
            it's a confirmation flag in this formula, not a weighted input —
            stated plainly rather than implied to be something it isn't."""
            components = sig.get("_score_components", {})
            if not components:
                st.caption("Score breakdown unavailable for this signal.")
                return
            rows = []
            for name, (val, weight) in components.items():
                rows.append({"Component": name, "Score (0-100)": round(val, 1), "Weight": f"{weight*100:.0f}%", "Weighted Contribution": round(val * weight, 1)})
            breakdown_df = pd.DataFrame(rows)
            st.dataframe(breakdown_df, width='stretch', hide_index=True)
            st.caption(f"Weekly Trend: {sig.get('Weekly Trend', 'N/A')} — informational confirmation only, not a weighted input to this score. Total Signal Strength: {sig.get('Signal Strength', 'N/A')}/100.")

        def _render_why_selected(sig):
            """Requirement 3: real top positive/negative contributors, computed
            as (component_score - 50) * weight — i.e. how far each real
            component pulled the total away from a neutral 50 baseline, and by
            how much its weight amplified that pull. Not a fabricated summary —
            derived directly from the same numbers shown in the breakdown above."""
            components = sig.get("_score_components", {})
            if not components:
                return
            contributions = [(name, (val - 50.0) * weight) for name, (val, weight) in components.items()]
            contributions.sort(key=lambda x: x[1], reverse=True)
            positives = [c for c in contributions if c[1] > 0][:3]
            negatives = [c for c in contributions if c[1] < 0][-3:]
            wc1, wc2 = st.columns(2)
            with wc1:
                st.markdown("**✅ Top positive contributors**")
                if positives:
                    for name, contrib in positives:
                        st.caption(f"• {name}: +{contrib:.1f}")
                else:
                    st.caption("No components scored meaningfully above neutral.")
            with wc2:
                st.markdown("**⚠️ Top negative contributors**")
                if negatives:
                    for name, contrib in sorted(negatives, key=lambda x: x[1]):
                        st.caption(f"• {name}: {contrib:.1f}")
                else:
                    st.caption("No components scored meaningfully below neutral.")

        # === TOP STOCKS — clean ranked list, no score components shown here ===
        def _signal_label(sig_strength):
            if sig_strength >= 85:
                return "Strong Buy"
            elif sig_strength >= 70:
                return "Buy"
            elif sig_strength >= 55:
                return "Watch"
            else:
                return "Developing"

        ranked = sorted(valid_signals, key=lambda s: s.get("Signal Strength", 0), reverse=True)
        rank_emoji = {1: "🥇", 2: "🥈", 3: "🥉"}
        for i, sig in enumerate(ranked, start=1):
            rc1, rc2, rc3, rc4 = st.columns([0.6, 2, 2, 2])
            with rc1:
                st.markdown(f"**{rank_emoji.get(i, f'{i}.')}**")
            with rc2:
                st.markdown(f"**{sig['Ticker']}**  \n{sig.get('Signal Strength', 0):.0f}/100 · {_signal_label(sig.get('Signal Strength', 0))}")
            with rc3:
                st.markdown(f"{sig['Live Price']}  \n→ {sig['Target']}")
            with rc4:
                st.markdown(f"Stop {sig['Stop Loss']}  \n{sig.get('Risk:Reward', '')}")

        st.markdown("---")
        ticker_options = [sig["Ticker"] for sig in ranked]
        selected_detail_ticker = st.selectbox(
            "🔍 Select a stock for full details",
            ["— Select —"] + ticker_options, key="eq_detail_select"
        )
        if selected_detail_ticker != "— Select —":
            detail_sig = next((s for s in ranked if s["Ticker"] == selected_detail_ticker), None)
            if detail_sig:
                st.markdown(f"#### {detail_sig['Ticker']} — {detail_sig['Sector']} — Complete Analysis")
                _render_risk_card(detail_sig)
                with st.expander("📊 Institutional Score Breakdown", expanded=True):
                    _render_score_breakdown(detail_sig)
                with st.expander("🔍 Why Selected", expanded=True):
                    _render_why_selected(detail_sig)
                with st.expander("📈 Technical Details (EMA, RSI, ADX, ATR, SuperTrend, MACD, RVOL, etc.)", expanded=False):
                    detail_technical_cols = [c for c in pd.DataFrame([detail_sig]).columns if not c.startswith('_') and c not in
                                              ('Ticker', 'Sector', 'Live Price', 'Action', 'Target', 'Stop Loss', 'Conviction',
                                               'Signal Strength', 'Risk Summary')]
                    st.dataframe(pd.DataFrame([detail_sig])[detail_technical_cols], width='stretch', hide_index=True)

        # CSV export uses the fuller column set (only excluding internal/plumbing
        # fields, not the simplified-for-display ones) — a power user downloading
        # for spreadsheet analysis should get the raw granular numbers back,
        # even though the on-screen buckets above show the consolidated version.
        csv_hidden_cols = ['score', '_price_val', '_qty', '_risk_amt', '_returns', '_sector',
                           '_score_components', '_sl', '_tgt', '_resistance60', '_risk_per_share']
        csv_display_cols = [c for c in pd.DataFrame(valid_signals).columns if c not in csv_hidden_cols]
        df_top10_display = pd.DataFrame(valid_signals)[csv_display_cols]
        st.caption("* RVOL (session-adj.) falls back to the raw ratio when the market is closed or data isn't dated today, since a partial-day adjustment is meaningless once a session is already complete.")
        st.download_button("⬇️ Download Screener Results (CSV)", df_top10_display.to_csv(index=False).encode(),
                            file_name="screener_results.csv", mime="text/csv", key="dl_screener")

        st.markdown("### 📊 Watchlist Summary (per-share basis — no capital sizing)")
        avg_risk_pct = sum(s["Risk %"] for s in valid_signals) / len(valid_signals) if valid_signals else 0.0

        exp1, exp2 = st.columns(2)
        exp1.metric("Avg Risk % to Stop", f"{avg_risk_pct:.2f}%")
        exp2.metric("Picks", f"{len(valid_signals)}")
        st.caption("No capital deployed or portfolio-heat figures shown — size each pick per your own risk management.")

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
                    st.dataframe(corr_matrix.style.background_gradient(cmap="RdYlGn_r", vmin=-1, vmax=1), width='stretch')
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
                    st.dataframe(pd.DataFrame(bt_rows), width='stretch', hide_index=True)
                else:
                    st.warning("Not enough history to backtest these tickers.")
    else:
        st.warning(
            "No equities matched the strict technical filter criteria right now. This can genuinely happen on "
            "days without many clean setups — but if it happens often, open '⚙️ Filters' above and check: "
            "Max Stock Price Filter (default ₹50,000 — a low value like ₹1,000 excludes most large-caps) "
            "and Require Weekly Uptrend Confirmation (stricter — try turning it off)."
        )
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

                st.markdown("### 🎯 Commodity Setup")
                if mcx_ltp > 0 and curr_atr > 0:
                    c_stop = round(mcx_ltp - (1.5 * curr_atr), 2)
                    c_target = round(mcx_ltp + (3.0 * curr_atr), 2)

                    c_lot_size = 1
                    if "GOLD" in selected_commodity: c_lot_size = 100
                    elif "SILVER" in selected_commodity: c_lot_size = 30
                    elif "CRUDEOIL" in selected_commodity: c_lot_size = 100
                    elif "NATURALGAS" in selected_commodity: c_lot_size = 1250

                    st.success(
                        f"**Setup for {selected_commodity}** → LONG @ ~₹{mcx_ltp:,.2f} (lot size {c_lot_size}) · "
                        f"Target ~₹{c_target:,.2f} · Stop ~₹{c_stop:,.2f}"
                    )
                    st.caption("Setup only — no position sizing or margin figures shown; size your own quantity per your own risk management.")
                else:
                    st.info("Insufficient price action data to derive setup for this commodity.")

                fig = go.Figure(data=[go.Candlestick(
                    x=hist_df.index, open=hist_df['Open'], high=hist_df['High'],
                    low=hist_df['Low'], close=hist_df['Close'], name=selected_commodity
                )])
                ema_20 = ta.ema(hist_df['Close'], length=20)
                fig.add_trace(go.Scatter(x=hist_df.index, y=ema_20, line=dict(color='#ff9800', width=1.5), name='EMA 20'))
                fig.update_layout(xaxis_rangeslider_visible=False, height=450, template="plotly_dark", paper_bgcolor="#050505", plot_bgcolor="#0a0a0a")
                st.plotly_chart(fig, width='stretch')
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
                    MF_MAX_ANALYZED = 40
                    if len(candidates) > MF_MAX_ANALYZED:
                        candidates = candidates[:MF_MAX_ANALYZED]
                    results = []
                    progress = st.progress(0, text="Fetching NAV history...")
                    completed = 0

                    def _fetch_and_score(c):
                        nav_json = fetch_mf_nav_history(c["schemeCode"])
                        stats = compute_mf_returns(nav_json)
                        if stats:
                            stats["scheme_code"] = c["schemeCode"]
                            return stats
                        return None

                    # IMPORTANT: mfapi.in is a free public API. 15 concurrent threads
                    # was almost certainly triggering rate-limiting on their end, which
                    # combined with get_robust_session()'s 3x exponential-backoff retries
                    # could stack up to minutes of blocking wait — freezing the entire
                    # app for that whole time, since Streamlit can't render anything else
                    # while this script is still running. Fixed with: (1) lower concurrency
                    # to stay well under likely rate limits, (2) a hard overall wall-clock
                    # cap so this can NEVER hang indefinitely no matter how the external
                    # API behaves — whatever hasn't completed by the deadline is simply
                    # skipped, and partial results are still shown.
                    MF_FETCH_HARD_TIMEOUT_SECS = 45
                    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                        futures = {executor.submit(_fetch_and_score, c): c for c in candidates}
                        done, not_done = concurrent.futures.wait(futures, timeout=MF_FETCH_HARD_TIMEOUT_SECS)
                        for future in done:
                            completed += 1
                            c = futures[future]
                            progress.progress(completed / len(candidates), text=f"Analyzing {c['schemeName'][:50]}...")
                            try:
                                result = future.result()
                            except Exception as e:
                                LOGGER.debug("Suppressed exception: %s", e)
                                result = None
                            if result:
                                results.append(result)
                        for future in not_done:
                            future.cancel()
                    progress.empty()
                    if not_done:
                        st.caption(f"⏱️ Stopped after {MF_FETCH_HARD_TIMEOUT_SECS}s — analyzed {len(done)}/{len(candidates)} funds (the data service was slow to respond for the rest).")

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
                        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
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
                        st.plotly_chart(fig, width='stretch')

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
        except Exception as e:
            LOGGER.debug("Suppressed exception: %s", e)
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
        except Exception as e:
            LOGGER.debug("Suppressed exception: %s", e)
            return "No Sweep Detected"

    if search_ticker != "-- Select Stock --":
        s_key = instrument_dict.get(search_ticker)
        if s_key:
            with st.spinner(f"Analyzing SMC & Technical Structure for {search_ticker}..."):
                s_df = fetch_upstox_history(s_key, access_token, days=400)
                s_quotes = get_live_market_quotes([s_key], access_token)
                if not s_df.empty:
                    # DEFENSIVE VALIDATION (root cause fix): _history_to_dataframe
                    # only drops rows missing Date/Close — a row with a valid
                    # Close but NaN High/Low can slip through and reach ta.atr()
                    # with NaN mid-series (not just at the warmup edge). pandas_ta
                    # can respond to that by returning None instead of a NaN-filled
                    # Series, and calling .dropna() on None throws exactly the
                    # crash reported here. Fixed locally (not in the shared
                    # _history_to_dataframe, which many other features depend on
                    # and shouldn't have its behavior changed blindly).
                    required_cols = {'High', 'Low', 'Close'}
                    if not required_cols.issubset(s_df.columns):
                        st.warning(f"Historical data for {search_ticker} is missing required price columns — cannot compute technical structure.")
                        s_df = pd.DataFrame()  # short-circuits the block below cleanly
                    else:
                        s_df = s_df.dropna(subset=['High', 'Low', 'Close'])

                    atr_series_full = None
                    if not s_df.empty and len(s_df) >= 15:
                        atr_series_full = ta.atr(s_df['High'], s_df['Low'], s_df['Close'], length=14)

                    if atr_series_full is None:
                        if not s_df.empty:
                            st.warning(f"Not enough clean history to compute ATR for {search_ticker} ({len(s_df)} valid candles after removing incomplete rows — need at least 15).")
                        atr_series = pd.Series(dtype=float)
                    else:
                        atr_series = atr_series_full.dropna()

                    s_price = s_quotes.get(s_key, {}).get('last_price', s_df.iloc[-1]['Close']) if (s_quotes and not s_df.empty) else (s_df.iloc[-1]['Close'] if not s_df.empty else None)
                    if atr_series.empty:
                        if s_price is not None:
                            st.warning(f"Not enough history to compute ATR for {search_ticker}.")
                    else:
                        s_atr = atr_series.iloc[-1]
                        # (BUG FOUND — related to the crash: this line used to
                        # call ta.atr() a second time on the identical inputs,
                        # redundantly recomputing the exact same indicator.
                        # atr_series_full is now computed once, above, and reused.)

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
                        st.plotly_chart(fig, width='stretch')
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
        except Exception as e:
            LOGGER.debug("Suppressed exception: %s", e)
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
                    except Exception as e:
                        LOGGER.debug("Suppressed exception: %s", e)
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
