"""Point-in-time market data archive.

The archive is intentionally observation based: it records what the provider
published on a date and never substitutes today's universe for an earlier date.
That rule prevents survivorship bias in scanner validation.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
import threading
from typing import Iterable, Mapping

import pandas as pd


PIT_SCHEMA_VERSION = 2


def _text(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    value = str(value).strip()
    return value or None


def _utc_text(value) -> str:
    """Canonical UTC timestamp used for storage and lexical SQLite ordering."""
    parsed = pd.Timestamp(value)
    if pd.isna(parsed):
        raise ValueError("Timestamp is invalid")
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    return parsed.tz_convert("UTC").isoformat()


def _date_text(value) -> str:
    parsed = pd.Timestamp(value)
    if pd.isna(parsed):
        raise ValueError("Date is invalid")
    return parsed.date().isoformat()


class PointInTimeStore:
    """SQLite-backed append-only evidence store for market membership and scans."""

    def __init__(self, connect_fn, db_path: str, minimum_complete_universe: int = 1000):
        self._connect_fn = connect_fn
        self._db_path = db_path
        self.minimum_complete_universe = int(minimum_complete_universe)
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self):
        return self._connect_fn(self._db_path)

    @staticmethod
    def scanner_observation_id(scan_run_id, instrument_key, strategy_version) -> str:
        run_id = _text(scan_run_id)
        if not run_id:
            raise ValueError("scan_run_id is required for an immutable observation identity")
        key = _text(instrument_key)
        strategy = _text(strategy_version)
        if not key or not strategy:
            raise ValueError("instrument_key and strategy_version are required")
        return hashlib.sha256("|".join((run_id, key, strategy)).encode()).hexdigest()

    def _ensure_schema(self):
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS pit_universe_snapshots (
                        snapshot_date TEXT PRIMARY KEY,
                        observed_at TEXT NOT NULL,
                        source TEXT NOT NULL,
                        instrument_count INTEGER NOT NULL,
                        payload_hash TEXT NOT NULL,
                        is_complete INTEGER NOT NULL,
                        schema_version INTEGER NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS pit_universe_membership (
                        snapshot_date TEXT NOT NULL,
                        instrument_key TEXT NOT NULL,
                        trading_symbol TEXT NOT NULL,
                        isin TEXT,
                        name TEXT,
                        exchange TEXT,
                        segment TEXT,
                        instrument_type TEXT,
                        security_type TEXT,
                        sector TEXT,
                        source TEXT NOT NULL,
                        observed_at TEXT NOT NULL,
                        PRIMARY KEY (snapshot_date, instrument_key),
                        FOREIGN KEY (snapshot_date) REFERENCES pit_universe_snapshots(snapshot_date)
                    );
                    CREATE INDEX IF NOT EXISTS idx_pit_membership_symbol_date
                        ON pit_universe_membership(trading_symbol, snapshot_date);
                    CREATE INDEX IF NOT EXISTS idx_pit_membership_isin_date
                        ON pit_universe_membership(isin, snapshot_date);

                    CREATE TABLE IF NOT EXISTS pit_universe_snapshot_versions (
                        snapshot_id TEXT PRIMARY KEY,
                        snapshot_date TEXT NOT NULL,
                        observed_at TEXT NOT NULL,
                        source TEXT NOT NULL,
                        instrument_count INTEGER NOT NULL,
                        payload_hash TEXT NOT NULL,
                        is_complete INTEGER NOT NULL,
                        schema_version INTEGER NOT NULL,
                        UNIQUE(snapshot_date, payload_hash)
                    );
                    CREATE INDEX IF NOT EXISTS idx_pit_snapshot_version_time
                        ON pit_universe_snapshot_versions(snapshot_date, observed_at);
                    CREATE TABLE IF NOT EXISTS pit_universe_membership_versions (
                        snapshot_id TEXT NOT NULL,
                        instrument_key TEXT NOT NULL,
                        trading_symbol TEXT NOT NULL,
                        isin TEXT,
                        name TEXT,
                        exchange TEXT,
                        segment TEXT,
                        instrument_type TEXT,
                        security_type TEXT,
                        sector TEXT,
                        source TEXT NOT NULL,
                        observed_at TEXT NOT NULL,
                        PRIMARY KEY(snapshot_id, instrument_key),
                        FOREIGN KEY(snapshot_id) REFERENCES pit_universe_snapshot_versions(snapshot_id)
                    );

                    CREATE TABLE IF NOT EXISTS pit_feature_observations (
                        feature_id TEXT PRIMARY KEY,
                        instrument_key TEXT NOT NULL,
                        feature_name TEXT NOT NULL,
                        effective_at TEXT NOT NULL,
                        available_at TEXT NOT NULL,
                        observed_at TEXT NOT NULL,
                        source TEXT NOT NULL,
                        value_json TEXT NOT NULL,
                        payload_hash TEXT NOT NULL,
                        UNIQUE(instrument_key, feature_name, effective_at, available_at, payload_hash)
                    );
                    CREATE INDEX IF NOT EXISTS idx_pit_feature_available
                        ON pit_feature_observations(instrument_key, feature_name, available_at);

                    CREATE TABLE IF NOT EXISTS pit_sector_history (
                        isin TEXT NOT NULL,
                        effective_from TEXT NOT NULL,
                        effective_to TEXT,
                        sector TEXT NOT NULL,
                        source TEXT NOT NULL,
                        observed_at TEXT NOT NULL,
                        payload_hash TEXT NOT NULL,
                        PRIMARY KEY (isin, effective_from, sector)
                    );
                    CREATE TABLE IF NOT EXISTS pit_corporate_actions (
                        isin TEXT NOT NULL,
                        action_type TEXT NOT NULL,
                        ex_date TEXT NOT NULL,
                        record_date TEXT,
                        announcement_date TEXT,
                        amount REAL,
                        ratio TEXT,
                        details_json TEXT NOT NULL,
                        source TEXT NOT NULL,
                        observed_at TEXT NOT NULL,
                        payload_hash TEXT NOT NULL,
                        PRIMARY KEY (isin, action_type, ex_date, payload_hash)
                    );
                    CREATE INDEX IF NOT EXISTS idx_pit_actions_isin_date
                        ON pit_corporate_actions(isin, ex_date);
                    CREATE TABLE IF NOT EXISTS pit_enrichment_sync (
                        isin TEXT NOT NULL,
                        resource TEXT NOT NULL,
                        checked_date TEXT NOT NULL,
                        status TEXT NOT NULL,
                        observed_at TEXT NOT NULL,
                        PRIMARY KEY (isin, resource)
                    );

                    CREATE TABLE IF NOT EXISTS scanner_observations (
                        observation_id TEXT PRIMARY KEY,
                        scan_run_id TEXT,
                        as_of_date TEXT NOT NULL,
                        observed_at TEXT NOT NULL,
                        instrument_key TEXT NOT NULL,
                        trading_symbol TEXT NOT NULL,
                        strategy_version TEXT NOT NULL,
                        universe_snapshot_date TEXT NOT NULL,
                        stage1_pass INTEGER NOT NULL,
                        stage2_pass INTEGER NOT NULL,
                        rejection_reason TEXT,
                        score REAL,
                        entry REAL,
                        stop REAL,
                        target REAL,
                        feature_json TEXT NOT NULL,
                        FOREIGN KEY (universe_snapshot_date) REFERENCES pit_universe_snapshots(snapshot_date)
                    );
                    CREATE INDEX IF NOT EXISTS idx_scanner_observations_date
                        ON scanner_observations(as_of_date, strategy_version);
                """)
                columns = {row[1] for row in conn.execute("PRAGMA table_info(scanner_observations)")}
                if "scan_run_id" not in columns:
                    conn.execute("ALTER TABLE scanner_observations ADD COLUMN scan_run_id TEXT")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_scanner_run ON scanner_observations(scan_run_id)")
                conn.commit()
            finally:
                conn.close()

    @staticmethod
    def _normalize_records(records: pd.DataFrame | Iterable[Mapping]) -> list[dict]:
        source = records.to_dict("records") if isinstance(records, pd.DataFrame) else list(records)
        normalized = []
        for row in source:
            key = _text(row.get("instrument_key"))
            symbol = _text(row.get("tradingsymbol") or row.get("trading_symbol"))
            if not key or not symbol:
                continue
            normalized.append({
                "instrument_key": key,
                "trading_symbol": symbol.upper(),
                "isin": _text(row.get("isin")),
                "name": _text(row.get("name")),
                "exchange": _text(row.get("source_exchange") or row.get("exchange")),
                "segment": _text(row.get("segment") or row.get("exchange")),
                "instrument_type": _text(row.get("instrument_type")),
                "security_type": _text(row.get("security_type")),
                "sector": _text(row.get("sector")),
            })
        # Provider payloads can contain duplicates. Last occurrence wins, but
        # completeness and hashes count unique instruments only.
        deduplicated = {item["instrument_key"]: item for item in normalized}
        return sorted(deduplicated.values(), key=lambda item: (item["instrument_key"], item["trading_symbol"]))

    def archive_universe(self, records, snapshot_date=None, source="Upstox BOD NSE JSON") -> dict:
        snapshot_date = _date_text(snapshot_date or dt.date.today())
        rows = self._normalize_records(records)
        canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        observed_at = dt.datetime.now(dt.timezone.utc).isoformat()
        complete = len(rows) >= self.minimum_complete_universe
        snapshot_id = hashlib.sha256(f"{snapshot_date}|{digest}".encode()).hexdigest()
        conn = self._connect()
        try:
            existing = conn.execute(
                "SELECT payload_hash, instrument_count, is_complete FROM pit_universe_snapshots WHERE snapshot_date=?",
                (snapshot_date,),
            ).fetchone()
            if existing and existing[0] == digest:
                version_exists = conn.execute(
                    "SELECT 1 FROM pit_universe_snapshot_versions WHERE snapshot_id=?", (snapshot_id,)
                ).fetchone()
                if version_exists:
                    return {"date": snapshot_date, "count": int(existing[1]), "complete": bool(existing[2]), "changed": False}
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                INSERT OR IGNORE INTO pit_universe_snapshot_versions(
                    snapshot_id,snapshot_date,observed_at,source,instrument_count,payload_hash,
                    is_complete,schema_version
                ) VALUES (?,?,?,?,?,?,?,?)
            """, (snapshot_id, snapshot_date, observed_at, source, len(rows), digest,
                  int(complete), PIT_SCHEMA_VERSION))
            conn.executemany("""
                INSERT OR IGNORE INTO pit_universe_membership_versions(
                    snapshot_id,instrument_key,trading_symbol,isin,name,exchange,segment,
                    instrument_type,security_type,sector,source,observed_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, [(
                snapshot_id, row["instrument_key"], row["trading_symbol"], row["isin"], row["name"],
                row["exchange"], row["segment"], row["instrument_type"], row["security_type"],
                row["sector"], source, observed_at,
            ) for row in rows])
            preserve_canonical = bool(existing and existing[2] and not complete)
            if not preserve_canonical:
                conn.execute("DELETE FROM pit_universe_membership WHERE snapshot_date=?", (snapshot_date,))
                conn.execute("""
                    INSERT INTO pit_universe_snapshots(snapshot_date, observed_at, source, instrument_count,
                        payload_hash, is_complete, schema_version) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(snapshot_date) DO UPDATE SET observed_at=excluded.observed_at, source=excluded.source,
                        instrument_count=excluded.instrument_count, payload_hash=excluded.payload_hash,
                        is_complete=excluded.is_complete, schema_version=excluded.schema_version
                """, (snapshot_date, observed_at, source, len(rows), digest, int(complete), PIT_SCHEMA_VERSION))
                conn.executemany("""
                    INSERT INTO pit_universe_membership(snapshot_date, instrument_key, trading_symbol, isin, name,
                        exchange, segment, instrument_type, security_type, sector, source, observed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [(
                    snapshot_date, row["instrument_key"], row["trading_symbol"], row["isin"], row["name"],
                    row["exchange"], row["segment"], row["instrument_type"], row["security_type"],
                    row["sector"], source, observed_at,
                ) for row in rows])
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            raise
        finally:
            conn.close()
        return {"date": snapshot_date, "count": len(rows), "complete": complete, "changed": True,
                "canonical_preserved": bool(existing and existing[2] and not complete)}

    def universe_as_known_at(self, as_of_date, known_at, require_complete=True) -> pd.DataFrame:
        """Universe effective by ``as_of_date`` and actually observed by ``known_at``."""
        known_text = _utc_text(known_at)
        conn = self._connect()
        try:
            clause = "AND is_complete=1" if require_complete else ""
            row = conn.execute(
                f"SELECT snapshot_id FROM pit_universe_snapshot_versions "
                f"WHERE snapshot_date<=? AND observed_at<=? {clause} "
                "ORDER BY snapshot_date DESC, observed_at DESC LIMIT 1",
                (_date_text(as_of_date), known_text),
            ).fetchone()
            if not row:
                return pd.DataFrame()
            return pd.read_sql_query(
                "SELECT * FROM pit_universe_membership_versions WHERE snapshot_id=? ORDER BY trading_symbol",
                conn, params=(row[0],),
            )
        finally:
            conn.close()

    def universe_lineage_as_known_at(self, as_of_date, known_at, *, instrument_key=None,
                                     require_complete=True) -> dict | None:
        """Return the exact archived universe version available at ``known_at``.

        When an instrument key is supplied, membership in that version is
        required. No current-universe or future-snapshot fallback is allowed.
        """
        known_text = _utc_text(known_at)
        clause = "AND is_complete=1" if require_complete else ""
        conn = self._connect()
        try:
            row = conn.execute(
                f"SELECT snapshot_id,snapshot_date,observed_at,source,payload_hash,is_complete "
                f"FROM pit_universe_snapshot_versions "
                f"WHERE snapshot_date<=? AND observed_at<=? {clause} "
                "ORDER BY snapshot_date DESC, observed_at DESC LIMIT 1",
                (_date_text(as_of_date), known_text),
            ).fetchone()
            if not row:
                return None
            if instrument_key is not None:
                member = conn.execute(
                    "SELECT 1 FROM pit_universe_membership_versions WHERE snapshot_id=? AND instrument_key=?",
                    (row[0], str(instrument_key)),
                ).fetchone()
                if not member:
                    return None
        finally:
            conn.close()
        effective = pd.Timestamp(row[1]).tz_localize("Asia/Kolkata").tz_convert("UTC")
        return {
            "snapshot_id": row[0], "snapshot_date": row[1],
            "effective_at": effective.isoformat(), "observed_at": _utc_text(row[2]),
            "source": row[3], "payload_hash": row[4], "complete": bool(row[5]),
            "member": True if instrument_key is not None else None,
            "instrument_key": str(instrument_key) if instrument_key is not None else None,
        }

    def record_feature_observation(self, *, instrument_key, feature_name, value,
                                   effective_at, available_at, source) -> str:
        effective_text = _utc_text(effective_at)
        available_text = _utc_text(available_at)
        payload = {
            "instrument_key": str(instrument_key), "feature_name": str(feature_name),
            "value": value, "effective_at": effective_text,
            "available_at": available_text, "source": str(source),
        }
        canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
        payload_hash = hashlib.sha256(canonical.encode()).hexdigest()
        feature_id = hashlib.sha256(
            f"{instrument_key}|{feature_name}|{effective_text}|{available_text}|{payload_hash}".encode()
        ).hexdigest()
        observed_at = dt.datetime.now(dt.timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute("""
                INSERT OR IGNORE INTO pit_feature_observations(
                    feature_id,instrument_key,feature_name,effective_at,available_at,observed_at,
                    source,value_json,payload_hash
                ) VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                feature_id, str(instrument_key), str(feature_name), effective_text, available_text,
                observed_at, str(source), json.dumps(value, default=str, sort_keys=True), payload_hash,
            ))
            conn.commit()
        finally:
            conn.close()
        return feature_id

    def features_as_of(self, instrument_key, decision_at) -> dict:
        """Return the latest feature values available no later than decision_at."""
        decision = pd.Timestamp(_utc_text(decision_at))
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT feature_name,value_json,effective_at,available_at,observed_at,source,feature_id
                FROM pit_feature_observations WHERE instrument_key=?
            """, (str(instrument_key),)).fetchall()
        finally:
            conn.close()
        eligible = []
        for row in rows:
            try:
                effective = pd.Timestamp(_utc_text(row[2]))
                available = pd.Timestamp(_utc_text(row[3]))
                observed = pd.Timestamp(_utc_text(row[4]))
            except (TypeError, ValueError):
                continue
            if effective <= decision and available <= decision:
                eligible.append((row, effective, available, observed))
        eligible.sort(key=lambda item: (item[0][0], item[2], item[1], item[3], item[0][6]))
        latest = {}
        for row, effective, available, observed in eligible:
            latest[row[0]] = {
                "value": json.loads(row[1]), "effective_at": effective.isoformat(),
                "available_at": available.isoformat(), "observed_at": observed.isoformat(), "source": row[5],
            }
        return latest

    def universe_as_of(self, as_of_date, require_complete=True) -> pd.DataFrame:
        """Return the latest genuinely observed snapshot on/before a date.

        Empty is returned when no qualifying snapshot exists. There is no
        fallback to a future or current snapshot.
        """
        conn = self._connect()
        try:
            clause = "AND is_complete=1" if require_complete else ""
            row = conn.execute(
                f"SELECT snapshot_date FROM pit_universe_snapshots WHERE snapshot_date<=? {clause} "
                "ORDER BY snapshot_date DESC LIMIT 1", (_date_text(as_of_date),),
            ).fetchone()
            if not row:
                return pd.DataFrame()
            return pd.read_sql_query(
                "SELECT * FROM pit_universe_membership WHERE snapshot_date=? ORDER BY trading_symbol",
                conn, params=(row[0],),
            )
        finally:
            conn.close()

    def coverage(self) -> dict:
        conn = self._connect()
        try:
            row = conn.execute("""
                SELECT MIN(snapshot_date), MAX(snapshot_date), COUNT(*),
                       SUM(CASE WHEN is_complete=1 THEN 1 ELSE 0 END)
                FROM pit_universe_snapshots
            """).fetchone()
            observations = conn.execute("SELECT COUNT(*) FROM scanner_observations").fetchone()[0]
        finally:
            conn.close()
        return {
            "first_date": row[0], "last_date": row[1], "snapshot_days": int(row[2] or 0),
            "complete_days": int(row[3] or 0), "scanner_observations": int(observations or 0),
        }

    def enrichment_candidates(self, resource: str, limit=10, checked_date=None) -> list[dict]:
        resource = str(resource)
        if resource not in {"profile", "corporate_actions"}:
            raise ValueError("Unsupported enrichment resource")
        checked_date = str(checked_date or dt.date.today())
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT DISTINCT m.isin, m.trading_symbol
                FROM pit_universe_membership m
                JOIN pit_universe_snapshots u ON u.snapshot_date=m.snapshot_date AND u.is_complete=1
                LEFT JOIN pit_enrichment_sync s ON s.isin=m.isin AND s.resource=?
                WHERE m.snapshot_date=(SELECT MAX(snapshot_date) FROM pit_universe_snapshots WHERE is_complete=1)
                  AND m.isin IS NOT NULL AND (s.checked_date IS NULL OR s.checked_date<?)
                ORDER BY m.trading_symbol LIMIT ?
            """, (resource, checked_date, int(limit))).fetchall()
        finally:
            conn.close()
        return [{"isin": row[0], "trading_symbol": row[1]} for row in rows]

    def mark_enrichment_checked(self, isin, resource, status, checked_date=None):
        checked_date = str(checked_date or dt.date.today())
        conn = self._connect()
        try:
            conn.execute("""
                INSERT INTO pit_enrichment_sync(isin, resource, checked_date, status, observed_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(isin, resource) DO UPDATE SET checked_date=excluded.checked_date,
                    status=excluded.status, observed_at=excluded.observed_at
            """, (str(isin), str(resource), checked_date, str(status),
                  dt.datetime.now(dt.timezone.utc).isoformat()))
            conn.commit()
        finally:
            conn.close()

    def record_sector(self, isin, sector, effective_from, source="Upstox company profile", effective_to=None):
        payload = {"isin": str(isin), "sector": str(sector), "effective_from": str(effective_from), "effective_to": effective_to}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        conn = self._connect()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO pit_sector_history(isin, effective_from, effective_to, sector,
                    source, observed_at, payload_hash) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (str(isin), str(effective_from), _text(effective_to), str(sector), source,
                  dt.datetime.now(dt.timezone.utc).isoformat(), digest))
            conn.commit()
        finally:
            conn.close()

    def record_corporate_actions(self, isin, actions, source="Upstox corporate actions") -> int:
        inserted = 0
        conn = self._connect()
        try:
            for action in actions or []:
                details = json.dumps(action, sort_keys=True, default=str, separators=(",", ":"))
                digest = hashlib.sha256(details.encode()).hexdigest()
                action_type = _text(action.get("type") or action.get("action_type") or action.get("corporate_action_type"))
                ex_date = _text(action.get("ex_date") or action.get("exDate"))
                if not action_type or not ex_date:
                    continue
                cursor = conn.execute("""
                    INSERT OR IGNORE INTO pit_corporate_actions(isin, action_type, ex_date, record_date,
                        announcement_date, amount, ratio, details_json, source, observed_at, payload_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (str(isin), action_type, ex_date, _text(action.get("record_date")),
                      _text(action.get("announcement_date")), action.get("amount"),
                      _text(action.get("ratio")), details, source,
                      dt.datetime.now(dt.timezone.utc).isoformat(), digest))
                inserted += cursor.rowcount
            conn.commit()
        finally:
            conn.close()
        return inserted

    def record_scanner_observation(self, *, as_of_date, instrument_key, trading_symbol,
                                   strategy_version, universe_snapshot_date, stage1_pass,
                                   stage2_pass, features, rejection_reason=None, score=None,
                                   entry=None, stop=None, target=None, scan_run_id=None) -> str:
        as_of_date = _date_text(as_of_date)
        universe_snapshot_date = _date_text(universe_snapshot_date)
        run_id = _text(scan_run_id) or hashlib.sha256(
            f"legacy|{as_of_date}|{strategy_version}".encode()
        ).hexdigest()
        observation_id = self.scanner_observation_id(run_id, instrument_key, strategy_version)
        feature_json = json.dumps(features or {}, sort_keys=True, default=str, separators=(",", ":"))
        conn = self._connect()
        try:
            conn.execute("""
                INSERT INTO scanner_observations(observation_id, scan_run_id, as_of_date, observed_at, instrument_key,
                    trading_symbol, strategy_version, universe_snapshot_date, stage1_pass, stage2_pass,
                    rejection_reason, score, entry, stop, target, feature_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(observation_id) DO UPDATE SET observed_at=excluded.observed_at,
                    stage1_pass=excluded.stage1_pass,
                    stage2_pass=MAX(scanner_observations.stage2_pass, excluded.stage2_pass),
                    rejection_reason=CASE WHEN scanner_observations.stage2_pass=1 AND excluded.stage2_pass=0
                                          THEN scanner_observations.rejection_reason
                                          ELSE excluded.rejection_reason END,
                    score=CASE WHEN scanner_observations.stage2_pass=1 AND excluded.stage2_pass=0
                               THEN scanner_observations.score
                               ELSE COALESCE(excluded.score, scanner_observations.score) END,
                    entry=COALESCE(excluded.entry, scanner_observations.entry),
                    stop=COALESCE(excluded.stop, scanner_observations.stop),
                    target=COALESCE(excluded.target, scanner_observations.target),
                    feature_json=CASE WHEN scanner_observations.stage2_pass=1 AND excluded.stage2_pass=0
                                      THEN scanner_observations.feature_json
                                      WHEN excluded.feature_json='{}' THEN scanner_observations.feature_json
                                      ELSE excluded.feature_json END
            """, (observation_id, run_id, str(as_of_date), dt.datetime.now(dt.timezone.utc).isoformat(),
                  str(instrument_key), str(trading_symbol), str(strategy_version), str(universe_snapshot_date),
                  int(bool(stage1_pass)), int(bool(stage2_pass)), _text(rejection_reason), score, entry, stop,
                  target, feature_json))
            conn.commit()
        finally:
            conn.close()
        return observation_id

    def record_stage1_batch(self, *, as_of_date, strategy_version, universe_snapshot_date,
                            evidence: Iterable[Mapping], scan_run_id=None) -> int:
        """Persist the complete quote funnel in one transaction."""
        observed_at = dt.datetime.now(dt.timezone.utc).isoformat()
        run_id = _text(scan_run_id) or hashlib.sha256(
            f"legacy|{_date_text(as_of_date)}|{strategy_version}".encode()
        ).hexdigest()
        as_of_date = _date_text(as_of_date)
        universe_snapshot_date = _date_text(universe_snapshot_date)
        rows = []
        for item in evidence:
            key = _text(item.get("instrument_key"))
            symbol = _text(item.get("trading_symbol"))
            if not key or not symbol:
                continue
            observation_id = self.scanner_observation_id(run_id, key, strategy_version)
            passed = bool(item.get("stage1_pass"))
            features = item.get("features") or {}
            rows.append((
                observation_id, run_id, str(as_of_date), observed_at, key, symbol, str(strategy_version),
                str(universe_snapshot_date), int(passed), 0,
                None if passed else _text(item.get("rejection_reason") or "Not selected by Stage 1"),
                item.get("score"), None, None, None,
                json.dumps(features, sort_keys=True, default=str, separators=(",", ":")),
            ))
        conn = self._connect()
        try:
            conn.executemany("""
                INSERT INTO scanner_observations(observation_id, scan_run_id, as_of_date, observed_at, instrument_key,
                    trading_symbol, strategy_version, universe_snapshot_date, stage1_pass, stage2_pass,
                    rejection_reason, score, entry, stop, target, feature_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(observation_id) DO UPDATE SET observed_at=excluded.observed_at,
                    universe_snapshot_date=excluded.universe_snapshot_date,
                    stage1_pass=excluded.stage1_pass,
                    stage2_pass=MAX(scanner_observations.stage2_pass, excluded.stage2_pass),
                    rejection_reason=CASE WHEN scanner_observations.stage2_pass=1
                                          THEN scanner_observations.rejection_reason
                                          ELSE excluded.rejection_reason END,
                    score=CASE WHEN scanner_observations.stage2_pass=1 THEN scanner_observations.score
                               ELSE excluded.score END,
                    entry=scanner_observations.entry, stop=scanner_observations.stop,
                    target=scanner_observations.target,
                    feature_json=CASE WHEN scanner_observations.stage2_pass=1
                                      THEN scanner_observations.feature_json
                                      ELSE excluded.feature_json END
            """, rows)
            conn.commit()
        finally:
            conn.close()
        return len(rows)
