"""Append-only, tamper-evident evidence ledger for trading decisions.

The ledger stores immutable events rather than mutable signal rows.  Every event
is chained to the preceding event for the same aggregate.  If a server-side
signing key is configured, HMAC-SHA256 makes undetected rewriting materially
harder even for somebody with database write access.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import sqlite3
import threading
import uuid
from dataclasses import asdict, is_dataclass
from typing import Iterable, Mapping


LEDGER_SCHEMA_VERSION = 1
GENESIS_HASH = "0" * 64
ALLOWED_EVENT_TYPES = {
    "SIGNAL_CREATED",
    "SIGNAL_REJECTED",
    "SIGNAL_AMENDED",
    "SIMULATED_FILL",
    "PARTIAL_FILL",
    "EXIT_TARGET",
    "EXIT_STOP",
    "EXIT_TIME",
    "EXIT_MANUAL",
    "SIGNAL_INVALIDATED",
    "MODEL_DECISION",
    "RISK_DECISION",
}


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(value=None) -> str:
    if value is None:
        value = _utcnow()
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        value = dt.datetime.combine(value, dt.time.min, tzinfo=dt.timezone.utc)
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc).isoformat()
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc).isoformat()


def _json_default(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Unsupported ledger value: {type(value).__name__}")


def canonical_json(payload: Mapping | None) -> str:
    return json.dumps(
        dict(payload or {}), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False, default=_json_default,
    )


class ImmutableEvidenceLedger:
    """SQLite evidence ledger with per-signal hash chains and write-once rows."""

    def __init__(self, connect_fn, db_path: str, signing_key: str | bytes | None = None):
        self._connect_fn = connect_fn
        self._db_path = db_path
        if isinstance(signing_key, str):
            signing_key = signing_key.encode("utf-8")
        self._signing_key = signing_key or b""
        self._lock = threading.Lock()
        self._ensure_schema()

    @property
    def integrity_mode(self) -> str:
        return "HMAC-SHA256" if self._signing_key else "SHA256 hash chain"

    def _connect(self):
        conn = self._connect_fn(self._db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS evidence_ledger_events (
                        event_id TEXT PRIMARY KEY,
                        aggregate_id TEXT NOT NULL,
                        sequence_no INTEGER NOT NULL,
                        event_type TEXT NOT NULL,
                        recorded_at TEXT NOT NULL,
                        effective_at TEXT NOT NULL,
                        source TEXT NOT NULL,
                        actor_id TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL UNIQUE,
                        payload_json TEXT NOT NULL,
                        previous_hash TEXT NOT NULL,
                        event_hash TEXT NOT NULL UNIQUE,
                        hash_algorithm TEXT NOT NULL,
                        schema_version INTEGER NOT NULL,
                        UNIQUE(aggregate_id, sequence_no)
                    );
                    CREATE INDEX IF NOT EXISTS idx_evidence_ledger_aggregate
                        ON evidence_ledger_events(aggregate_id, sequence_no);
                    CREATE INDEX IF NOT EXISTS idx_evidence_ledger_recorded
                        ON evidence_ledger_events(recorded_at);
                    CREATE TRIGGER IF NOT EXISTS evidence_ledger_no_update
                    BEFORE UPDATE ON evidence_ledger_events
                    BEGIN
                        SELECT RAISE(ABORT, 'evidence ledger events are immutable');
                    END;
                    CREATE TRIGGER IF NOT EXISTS evidence_ledger_no_delete
                    BEFORE DELETE ON evidence_ledger_events
                    BEGIN
                        SELECT RAISE(ABORT, 'evidence ledger events are immutable');
                    END;
                """)
                conn.commit()
            finally:
                conn.close()

    def _digest(self, material: str) -> str:
        encoded = material.encode("utf-8")
        if self._signing_key:
            return hmac.new(self._signing_key, encoded, hashlib.sha256).hexdigest()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _material(*, event_id, aggregate_id, sequence_no, event_type, recorded_at,
                  effective_at, source, actor_id, idempotency_key, payload_json,
                  previous_hash, hash_algorithm, schema_version) -> str:
        return "|".join(map(str, (
            event_id, aggregate_id, sequence_no, event_type, recorded_at,
            effective_at, source, actor_id, idempotency_key, payload_json,
            previous_hash, hash_algorithm, schema_version,
        )))

    def append(
        self,
        *,
        aggregate_id: str,
        event_type: str,
        payload: Mapping,
        effective_at=None,
        source="quant-terminal",
        actor_id="system",
        idempotency_key: str | None = None,
    ) -> dict:
        aggregate_id = str(aggregate_id).strip()
        event_type = str(event_type).strip().upper()
        if not aggregate_id:
            raise ValueError("aggregate_id is required")
        if event_type not in ALLOWED_EVENT_TYPES:
            raise ValueError(f"Unsupported evidence event type: {event_type}")
        payload_json = canonical_json(payload)
        recorded_at = _iso()
        effective_at = _iso(effective_at or recorded_at)
        source = str(source).strip() or "unknown"
        actor_id = str(actor_id).strip() or "unknown"
        idempotency_key = str(idempotency_key or uuid.uuid4())
        algorithm = self.integrity_mode

        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    "SELECT * FROM evidence_ledger_events WHERE idempotency_key=?",
                    (idempotency_key,),
                ).fetchone()
                if existing:
                    conn.rollback()
                    return self._row(existing, duplicate=True)
                preceding = conn.execute(
                    "SELECT sequence_no,event_hash FROM evidence_ledger_events "
                    "WHERE aggregate_id=? ORDER BY sequence_no DESC LIMIT 1",
                    (aggregate_id,),
                ).fetchone()
                sequence_no = int(preceding[0]) + 1 if preceding else 1
                previous_hash = str(preceding[1]) if preceding else GENESIS_HASH
                event_id = str(uuid.uuid4())
                material = self._material(
                    event_id=event_id, aggregate_id=aggregate_id, sequence_no=sequence_no,
                    event_type=event_type, recorded_at=recorded_at, effective_at=effective_at,
                    source=source, actor_id=actor_id, idempotency_key=idempotency_key,
                    payload_json=payload_json, previous_hash=previous_hash,
                    hash_algorithm=algorithm, schema_version=LEDGER_SCHEMA_VERSION,
                )
                event_hash = self._digest(material)
                conn.execute("""
                    INSERT INTO evidence_ledger_events(
                        event_id,aggregate_id,sequence_no,event_type,recorded_at,effective_at,
                        source,actor_id,idempotency_key,payload_json,previous_hash,event_hash,
                        hash_algorithm,schema_version
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    event_id, aggregate_id, sequence_no, event_type, recorded_at, effective_at,
                    source, actor_id, idempotency_key, payload_json, previous_hash, event_hash,
                    algorithm, LEDGER_SCHEMA_VERSION,
                ))
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM evidence_ledger_events WHERE event_id=?", (event_id,)
                ).fetchone()
                return self._row(row, duplicate=False)
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    @staticmethod
    def _row(row, *, duplicate=False) -> dict:
        names = [
            "event_id", "aggregate_id", "sequence_no", "event_type", "recorded_at",
            "effective_at", "source", "actor_id", "idempotency_key", "payload_json",
            "previous_hash", "event_hash", "hash_algorithm", "schema_version",
        ]
        result = dict(zip(names, row))
        result["payload"] = json.loads(result.pop("payload_json"))
        result["duplicate"] = bool(duplicate)
        return result

    def events(self, aggregate_id: str) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM evidence_ledger_events WHERE aggregate_id=? ORDER BY sequence_no",
                (str(aggregate_id),),
            ).fetchall()
        finally:
            conn.close()
        return [self._row(row) for row in rows]

    def verify(self, aggregate_id: str | None = None) -> dict:
        conn = self._connect()
        try:
            if aggregate_id is None:
                aggregates = [row[0] for row in conn.execute(
                    "SELECT DISTINCT aggregate_id FROM evidence_ledger_events ORDER BY aggregate_id"
                ).fetchall()]
            else:
                aggregates = [str(aggregate_id)]
            checked = 0
            failures = []
            for aggregate in aggregates:
                rows = conn.execute(
                    "SELECT * FROM evidence_ledger_events WHERE aggregate_id=? ORDER BY sequence_no",
                    (aggregate,),
                ).fetchall()
                previous_hash = GENESIS_HASH
                expected_sequence = 1
                for raw in rows:
                    row = self._row(raw)
                    payload_json = canonical_json(row["payload"])
                    material = self._material(
                        event_id=row["event_id"], aggregate_id=row["aggregate_id"],
                        sequence_no=row["sequence_no"], event_type=row["event_type"],
                        recorded_at=row["recorded_at"], effective_at=row["effective_at"],
                        source=row["source"], actor_id=row["actor_id"],
                        idempotency_key=row["idempotency_key"], payload_json=payload_json,
                        previous_hash=row["previous_hash"], hash_algorithm=row["hash_algorithm"],
                        schema_version=row["schema_version"],
                    )
                    valid = (
                        row["sequence_no"] == expected_sequence
                        and row["previous_hash"] == previous_hash
                        and hmac.compare_digest(row["event_hash"], self._digest(material))
                    )
                    checked += 1
                    if not valid:
                        failures.append({"aggregate_id": aggregate, "event_id": row["event_id"]})
                    previous_hash = row["event_hash"]
                    expected_sequence += 1
        finally:
            conn.close()
        return {
            "valid": not failures,
            "events_checked": checked,
            "aggregates_checked": len(aggregates),
            "failures": failures,
            "integrity_mode": self.integrity_mode,
        }

    def append_many(self, events: Iterable[Mapping]) -> list[dict]:
        return [self.append(**dict(event)) for event in events]
