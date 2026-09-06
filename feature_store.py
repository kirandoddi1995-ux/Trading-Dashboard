"""Persistent, exact technical-feature cache backed by SQLite.

Feature calculations remain owned by the caller.  This module detects an
unchanged OHLCV source series, returns its stored feature frame, and performs
incremental writes when only new/the current bar changed.  On any ambiguous
history correction it safely rewrites the complete feature series.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time

import numpy as np
import pandas as pd

from observability import get_registry
FEATURE_VERSION = 3
SOURCE_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]
FEATURE_COLUMNS = [
    "EMA_12", "EMA_20", "EMA_26", "EMA_50", "EMA_200", "MACD", "MACD_signal",
    "BB_lower", "BB_upper", "ADX", "RSI", "ATR", "VWAP20", "ST_direction",
    "AVG_GAIN_14", "AVG_LOSS_14", "PLUS_DM_14", "MINUS_DM_14",
    "ST_ATR_10", "ST_upper", "ST_lower",
]


def source_hash(frame: pd.DataFrame) -> str:
    cols = [column for column in SOURCE_COLUMNS if column in frame.columns]
    if frame is None or frame.empty or not cols:
        return "empty"
    normalized = frame[cols].apply(pd.to_numeric, errors="coerce")
    hashed = pd.util.hash_pandas_object(normalized, index=True).values.tobytes()
    return hashlib.sha256(hashed).hexdigest()


def compute_feature_frame(frame: pd.DataFrame, ta_module) -> pd.DataFrame:
    out = frame.copy()
    out["EMA_12"] = ta_module.ema(out["Close"], length=12)
    out["EMA_20"] = ta_module.ema(out["Close"], length=20)
    out["EMA_26"] = ta_module.ema(out["Close"], length=26)
    out["EMA_50"] = ta_module.ema(out["Close"], length=50)
    out["EMA_200"] = ta_module.ema(out["Close"], length=200)

    macd = ta_module.macd(out["Close"], fast=12, slow=26, signal=9)
    out["MACD"] = macd.iloc[:, 0] if macd is not None and not macd.empty else np.nan
    out["MACD_signal"] = macd.iloc[:, 2] if macd is not None and not macd.empty else np.nan

    bands = ta_module.bbands(out["Close"], length=20, std=2)
    out["BB_lower"] = bands.iloc[:, 0] if bands is not None and not bands.empty else np.nan
    out["BB_upper"] = bands.iloc[:, 2] if bands is not None and not bands.empty else np.nan

    adx = ta_module.adx(out["High"], out["Low"], out["Close"], length=14)
    out["ADX"] = adx.iloc[:, 0] if adx is not None and not adx.empty else np.nan
    out["RSI"] = ta_module.rsi(out["Close"], length=14)
    out["ATR"] = ta_module.atr(out["High"], out["Low"], out["Close"], length=14)
    out["ST_ATR_10"] = ta_module.atr(out["High"], out["Low"], out["Close"], length=10)

    delta = pd.to_numeric(out["Close"], errors="coerce").diff()
    out["AVG_GAIN_14"] = delta.clip(lower=0.0).ewm(alpha=1.0 / 14.0, adjust=False, min_periods=14).mean()
    out["AVG_LOSS_14"] = (-delta.clip(upper=0.0)).ewm(alpha=1.0 / 14.0, adjust=False, min_periods=14).mean()
    up_move = pd.to_numeric(out["High"], errors="coerce").diff()
    down_move = -pd.to_numeric(out["Low"], errors="coerce").diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0.0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0.0), 0.0)
    out["PLUS_DM_14"] = plus_dm.ewm(alpha=1.0 / 14.0, adjust=False, min_periods=14).mean()
    out["MINUS_DM_14"] = minus_dm.ewm(alpha=1.0 / 14.0, adjust=False, min_periods=14).mean()

    typical = (out["High"] + out["Low"] + out["Close"]) / 3.0
    volume = out["Volume"].fillna(0.0)
    out["VWAP20"] = (typical * volume).rolling(20).sum() / volume.rolling(20).sum().replace(0, np.nan)

    supertrend = ta_module.supertrend(out["High"], out["Low"], out["Close"], length=10, multiplier=3)
    direction_columns = [column for column in supertrend.columns if "SUPERTd" in column]
    out["ST_direction"] = (
        supertrend[direction_columns[0]] if direction_columns
        else (supertrend.iloc[:, 1] if supertrend is not None and not supertrend.empty else np.nan)
    )
    upper_columns = [column for column in supertrend.columns if "SUPERTu" in column]
    lower_columns = [column for column in supertrend.columns if "SUPERTb" in column]
    out["ST_upper"] = supertrend[upper_columns[0]] if upper_columns else np.nan
    out["ST_lower"] = supertrend[lower_columns[0]] if lower_columns else np.nan
    return out


class TechnicalFeatureStore:
    def __init__(self, connect_fn, db_path: str):
        self._connect_fn = connect_fn
        self._db_path = db_path
        self._schema_lock = threading.Lock()
        self._metrics = get_registry()
        self._ensure_schema()

    def _connect(self):
        return self._connect_fn(self._db_path)

    def _ensure_schema(self):
        with self._schema_lock:
            conn = self._connect()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS technical_feature_meta (
                        instrument_key TEXT NOT NULL,
                        feature_version INTEGER NOT NULL,
                        source_hash TEXT NOT NULL,
                        prefix_hash TEXT NOT NULL,
                        row_count INTEGER NOT NULL,
                        first_dt TEXT,
                        last_dt TEXT,
                        updated_at REAL NOT NULL,
                        PRIMARY KEY (instrument_key, feature_version)
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS technical_features (
                        instrument_key TEXT NOT NULL,
                        feature_version INTEGER NOT NULL,
                        dt TEXT NOT NULL,
                        ema12 REAL, ema20 REAL, ema26 REAL, ema50 REAL, ema200 REAL,
                        macd REAL, macd_signal REAL,
                        bb_lower REAL, bb_upper REAL,
                        adx REAL, rsi REAL, atr REAL, vwap20 REAL,
                        st_direction REAL, avg_gain14 REAL, avg_loss14 REAL,
                        plus_dm14 REAL, minus_dm14 REAL, st_atr10 REAL, st_upper REAL, st_lower REAL,
                        PRIMARY KEY (instrument_key, feature_version, dt)
                    )
                """)
                existing_columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(technical_features)").fetchall()
                }
                for column in (
                    "ema12", "ema26", "avg_gain14", "avg_loss14", "plus_dm14",
                    "minus_dm14", "st_atr10", "st_upper", "st_lower",
                ):
                    if column not in existing_columns:
                        conn.execute(f"ALTER TABLE technical_features ADD COLUMN {column} REAL")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_technical_features_key_dt ON technical_features(instrument_key, dt)")
                conn.commit()
            finally:
                conn.close()

    @staticmethod
    def _iso_index(frame: pd.DataFrame) -> list[str]:
        return [pd.Timestamp(value).tz_localize(None).isoformat() for value in frame.index]

    def _meta(self, instrument_key: str):
        conn = self._connect()
        try:
            return conn.execute(
                "SELECT source_hash, prefix_hash, row_count, first_dt, last_dt FROM technical_feature_meta "
                "WHERE instrument_key=? AND feature_version=?",
                (instrument_key, FEATURE_VERSION),
            ).fetchone()
        finally:
            conn.close()

    def _read(self, instrument_key: str, source: pd.DataFrame) -> pd.DataFrame | None:
        conn = self._connect()
        try:
            feature_frame = pd.read_sql_query(
                "SELECT dt, ema12 AS EMA_12, ema20 AS EMA_20, ema26 AS EMA_26, "
                "ema50 AS EMA_50, ema200 AS EMA_200, "
                "macd AS MACD, macd_signal AS MACD_signal, bb_lower AS BB_lower, bb_upper AS BB_upper, "
                "adx AS ADX, rsi AS RSI, atr AS ATR, vwap20 AS VWAP20, st_direction AS ST_direction, "
                "avg_gain14 AS AVG_GAIN_14, avg_loss14 AS AVG_LOSS_14, "
                "plus_dm14 AS PLUS_DM_14, minus_dm14 AS MINUS_DM_14, st_atr10 AS ST_ATR_10, "
                "st_upper AS ST_upper, st_lower AS ST_lower "
                "FROM technical_features WHERE instrument_key=? AND feature_version=? ORDER BY dt",
                conn, params=(instrument_key, FEATURE_VERSION),
            )
        finally:
            conn.close()
        feature_frame["dt"] = pd.to_datetime(feature_frame["dt"], errors="coerce")
        if feature_frame["dt"].isna().any():
            return None
        feature_frame = feature_frame.set_index("dt")
        expected = pd.DatetimeIndex(source.index).tz_localize(None)
        if not expected.isin(feature_frame.index).all():
            return None
        feature_frame = feature_frame.loc[expected]
        result = source.copy()
        for column in FEATURE_COLUMNS:
            result[column] = feature_frame[column].to_numpy()
        return result

    @staticmethod
    def _incremental_features(source: pd.DataFrame, base: pd.DataFrame, start_row: int):
        """Update appended/current rows exactly from persisted recursive state."""
        if start_row < 200 or base is None or len(base) != start_row:
            return None
        out = source.copy()
        for column in FEATURE_COLUMNS:
            out[column] = np.nan
            out.loc[base.index, column] = base[column].to_numpy()

        required_state = [
            "EMA_12", "EMA_20", "EMA_26", "EMA_50", "EMA_200", "MACD_signal",
            "ATR", "AVG_GAIN_14", "AVG_LOSS_14", "PLUS_DM_14", "MINUS_DM_14",
            "ADX", "ST_direction", "ST_ATR_10", "ST_upper", "ST_lower",
        ]
        for i in range(start_row, len(out)):
            previous = out.iloc[i - 1]
            if any(pd.isna(previous.get(column)) for column in required_state):
                return None
            current = out.iloc[i]
            close = float(current["Close"])
            prev_close = float(previous["Close"])
            high, low = float(current["High"]), float(current["Low"])
            prev_high, prev_low = float(previous["High"]), float(previous["Low"])

            def recursive_ema(column, length):
                alpha = 2.0 / (float(length) + 1.0)
                return close * alpha + float(previous[column]) * (1.0 - alpha)

            values = {
                "EMA_12": recursive_ema("EMA_12", 12),
                "EMA_20": recursive_ema("EMA_20", 20),
                "EMA_26": recursive_ema("EMA_26", 26),
                "EMA_50": recursive_ema("EMA_50", 50),
                "EMA_200": recursive_ema("EMA_200", 200),
            }
            values["MACD"] = values["EMA_12"] - values["EMA_26"]
            values["MACD_signal"] = values["MACD"] * 0.2 + float(previous["MACD_signal"]) * 0.8

            close_window = pd.to_numeric(out["Close"].iloc[i - 19:i + 1], errors="coerce")
            if len(close_window) < 20 or close_window.isna().any():
                return None
            middle = float(close_window.mean())
            deviation = float(close_window.std(ddof=0))
            values["BB_lower"], values["BB_upper"] = middle - 2.0 * deviation, middle + 2.0 * deviation

            alpha14 = 1.0 / 14.0
            true_range = max(high - low, abs(high - prev_close), abs(low - prev_close))
            values["ATR"] = true_range * alpha14 + float(previous["ATR"]) * (1.0 - alpha14)
            values["ST_ATR_10"] = true_range * 0.1 + float(previous["ST_ATR_10"]) * 0.9
            delta = close - prev_close
            gain, loss = max(delta, 0.0), max(-delta, 0.0)
            values["AVG_GAIN_14"] = gain * alpha14 + float(previous["AVG_GAIN_14"]) * (1.0 - alpha14)
            values["AVG_LOSS_14"] = loss * alpha14 + float(previous["AVG_LOSS_14"]) * (1.0 - alpha14)
            if values["AVG_LOSS_14"] == 0.0:
                values["RSI"] = 50.0 if values["AVG_GAIN_14"] == 0.0 else 100.0
            else:
                rs = values["AVG_GAIN_14"] / values["AVG_LOSS_14"]
                values["RSI"] = 100.0 - 100.0 / (1.0 + rs)

            up_move, down_move = high - prev_high, prev_low - low
            plus_dm = up_move if up_move > down_move and up_move > 0.0 else 0.0
            minus_dm = down_move if down_move > up_move and down_move > 0.0 else 0.0
            values["PLUS_DM_14"] = plus_dm * alpha14 + float(previous["PLUS_DM_14"]) * (1.0 - alpha14)
            values["MINUS_DM_14"] = minus_dm * alpha14 + float(previous["MINUS_DM_14"]) * (1.0 - alpha14)
            if values["ATR"] <= 0:
                return None
            plus_di = 100.0 * values["PLUS_DM_14"] / values["ATR"]
            minus_di = 100.0 * values["MINUS_DM_14"] / values["ATR"]
            denominator = plus_di + minus_di
            if denominator <= 0:
                return None
            dx = 100.0 * abs(plus_di - minus_di) / denominator
            values["ADX"] = dx * alpha14 + float(previous["ADX"]) * (1.0 - alpha14)

            price_volume = (
                (out["High"].iloc[i - 19:i + 1] + out["Low"].iloc[i - 19:i + 1]
                 + out["Close"].iloc[i - 19:i + 1]) / 3.0
                * out["Volume"].iloc[i - 19:i + 1].fillna(0.0)
            )
            volume_sum = float(out["Volume"].iloc[i - 19:i + 1].fillna(0.0).sum())
            values["VWAP20"] = float(price_volume.sum()) / volume_sum if volume_sum > 0 else np.nan

            midpoint = (high + low) / 2.0
            basic_upper = midpoint + 3.0 * values["ST_ATR_10"]
            basic_lower = midpoint - 3.0 * values["ST_ATR_10"]
            prev_upper, prev_lower = float(previous["ST_upper"]), float(previous["ST_lower"])
            final_upper = prev_upper if basic_upper >= prev_upper and prev_close <= prev_upper else basic_upper
            final_lower = prev_lower if basic_lower <= prev_lower and prev_close >= prev_lower else basic_lower
            previous_direction = float(previous["ST_direction"])
            if close > prev_upper:
                direction = 1.0
            elif close < prev_lower:
                direction = -1.0
            else:
                direction = previous_direction
                if direction > 0 and final_lower < prev_lower:
                    final_lower = prev_lower
                elif direction < 0 and final_upper > prev_upper:
                    final_upper = prev_upper
            values["ST_direction"] = direction
            values["ST_upper"], values["ST_lower"] = final_upper, final_lower

            for column, value in values.items():
                out.iat[i, out.columns.get_loc(column)] = value
        return out

    def _write(self, instrument_key: str, source: pd.DataFrame, enriched: pd.DataFrame, meta) -> str:
        current_hash = source_hash(source)
        prefix_hash = source_hash(source.iloc[:-1]) if len(source) > 1 else "empty"
        start_row = 0
        mode = "full_rebuild"
        if meta:
            old_hash, old_prefix_hash, old_count, _first_dt, _last_dt = meta
            old_count = int(old_count)
            if len(source) == old_count and prefix_hash == old_prefix_hash:
                start_row = max(len(source) - 1, 0)
                mode = "latest_bar_update"
            elif len(source) > old_count and source_hash(source.iloc[:old_count]) == old_hash:
                start_row = old_count
                mode = "append"

        subset = enriched.iloc[start_row:]
        iso_dates = self._iso_index(subset)
        rows = []
        for dt_value, (_, row) in zip(iso_dates, subset.iterrows()):
            values = []
            for column in FEATURE_COLUMNS:
                value = row.get(column)
                values.append(float(value) if pd.notna(value) and np.isfinite(float(value)) else None)
            rows.append((instrument_key, FEATURE_VERSION, dt_value, *values))

        conn = self._connect()
        try:
            if mode == "full_rebuild":
                conn.execute(
                    "DELETE FROM technical_features WHERE instrument_key=? AND feature_version=?",
                    (instrument_key, FEATURE_VERSION),
                )
            if rows:
                conn.executemany("""
                    INSERT INTO technical_features(
                        instrument_key, feature_version, dt, ema12, ema20, ema26, ema50, ema200,
                        macd, macd_signal, bb_lower, bb_upper, adx, rsi, atr, vwap20, st_direction
                        , avg_gain14, avg_loss14, plus_dm14, minus_dm14, st_atr10, st_upper, st_lower
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(instrument_key, feature_version, dt) DO UPDATE SET
                        ema12=excluded.ema12, ema20=excluded.ema20, ema26=excluded.ema26,
                        ema50=excluded.ema50, ema200=excluded.ema200,
                        macd=excluded.macd, macd_signal=excluded.macd_signal,
                        bb_lower=excluded.bb_lower, bb_upper=excluded.bb_upper,
                        adx=excluded.adx, rsi=excluded.rsi, atr=excluded.atr,
                        vwap20=excluded.vwap20, st_direction=excluded.st_direction,
                        avg_gain14=excluded.avg_gain14, avg_loss14=excluded.avg_loss14,
                        plus_dm14=excluded.plus_dm14, minus_dm14=excluded.minus_dm14,
                        st_atr10=excluded.st_atr10,
                        st_upper=excluded.st_upper, st_lower=excluded.st_lower
                """, rows)
            dates = self._iso_index(source)
            conn.execute("""
                INSERT INTO technical_feature_meta(
                    instrument_key, feature_version, source_hash, prefix_hash,
                    row_count, first_dt, last_dt, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(instrument_key, feature_version) DO UPDATE SET
                    source_hash=excluded.source_hash, prefix_hash=excluded.prefix_hash,
                    row_count=excluded.row_count, first_dt=excluded.first_dt,
                    last_dt=excluded.last_dt, updated_at=excluded.updated_at
            """, (
                instrument_key, FEATURE_VERSION, current_hash, prefix_hash, len(source),
                dates[0] if dates else None, dates[-1] if dates else None, time.time(),
            ))
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            raise
        finally:
            conn.close()
        return mode

    def enrich(self, instrument_key: str, source: pd.DataFrame, compute_fn):
        if source is None or source.empty:
            return source, "empty"
        started = time.perf_counter()
        current_hash = source_hash(source)
        meta = self._meta(instrument_key)
        if meta and meta[0] == current_hash and int(meta[2]) == len(source):
            cached = self._read(instrument_key, source)
            if cached is not None:
                self._metrics.record("calculation", "technical_features", time.perf_counter() - started, cache_hit=True)
                return cached, "hit"

        if meta:
            old_hash, old_prefix_hash, old_count, _first_dt, _last_dt = meta
            old_count = int(old_count)
            base_source = None
            start_row = None
            if len(source) == old_count and source_hash(source.iloc[:-1]) == old_prefix_hash:
                base_source, start_row = source.iloc[:-1], len(source) - 1
            elif len(source) > old_count and source_hash(source.iloc[:old_count]) == old_hash:
                base_source, start_row = source.iloc[:old_count], old_count
            if base_source is not None:
                base = self._read(instrument_key, base_source)
                incremental = self._incremental_features(source, base, start_row)
                if incremental is not None:
                    mode = self._write(instrument_key, source, incremental, meta)
                    self._metrics.record(
                        "calculation", "technical_features_incremental",
                        time.perf_counter() - started, cache_hit=True,
                    )
                    return incremental, mode

        enriched = compute_fn(source)
        mode = self._write(instrument_key, source, enriched, meta)
        self._metrics.record("calculation", "technical_features", time.perf_counter() - started, cache_hit=False)
        return enriched, mode
