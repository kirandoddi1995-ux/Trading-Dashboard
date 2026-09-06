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


LEDGER_SCHEMA_VERSION = 2
GENESIS_HASH = "0" * 64
_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[str, threading.RLock] = {}
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
    "DECISION_EVALUATED",
    "DECISION_BATCH_EVALUATED",
    "OUTCOME_MATURED",
    "FEATURE_DEFINITION_REGISTERED",
    "FEATURE_QUALITY_OBSERVED",
    "EXPERIMENT_REGISTERED",
    "EXPERIMENT_RETRIED",
    "EXPERIMENT_RESULT_RECORDED",
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

    def __init__(self, connect_fn, db_path: str, signing_key: str | bytes | None = None,
                 previous_signing_keys: Mapping[str, str | bytes] | None = None):
        self._connect_fn = connect_fn
        self._db_path = db_path
        if isinstance(signing_key, str):
            signing_key = signing_key.encode("utf-8")
        self._signing_key = signing_key or b""
        self._key_id = (hashlib.sha256(self._signing_key).hexdigest()[:16]
                        if self._signing_key else "unsigned")
        self._keyring = {self._key_id: self._signing_key}
        for key_id, key in dict(previous_signing_keys or {}).items():
            self._keyring[str(key_id)] = key.encode("utf-8") if isinstance(key, str) else bytes(key)
        with _LOCKS_GUARD:
            self._lock = _PATH_LOCKS.setdefault(str(db_path), threading.RLock())
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
                        key_id TEXT,
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
                    CREATE TABLE IF NOT EXISTS evidence_delivery_outbox (
                        idempotency_key TEXT PRIMARY KEY,
                        event_json TEXT NOT NULL,
                        attempts INTEGER NOT NULL DEFAULT 0,
                        last_error TEXT,
                        next_attempt_at TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        delivered_at TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_evidence_outbox_pending
                        ON evidence_delivery_outbox(delivered_at,next_attempt_at);
                """)
                columns = {row[1] for row in conn.execute("PRAGMA table_info(evidence_ledger_events)")}
                if "key_id" not in columns:
                    conn.execute("ALTER TABLE evidence_ledger_events ADD COLUMN key_id TEXT")
                conn.commit()
            finally:
                conn.close()

    def _digest(self, material: str, key_id: str | None = None) -> str:
        encoded = material.encode("utf-8")
        key = self._keyring.get(str(key_id), self._signing_key) if key_id else self._signing_key
        if key:
            return hmac.new(key, encoded, hashlib.sha256).hexdigest()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _material(*, event_id, aggregate_id, sequence_no, event_type, recorded_at,
                  effective_at, source, actor_id, idempotency_key, payload_json,
                  previous_hash, hash_algorithm, schema_version, key_id=None) -> str:
        if int(schema_version) >= 2:
            return canonical_json({
                "event_id": event_id, "aggregate_id": aggregate_id, "sequence_no": sequence_no,
                "event_type": event_type, "recorded_at": recorded_at, "effective_at": effective_at,
                "source": source, "actor_id": actor_id, "idempotency_key": idempotency_key,
                "payload_json": payload_json, "previous_hash": previous_hash,
                "hash_algorithm": hash_algorithm, "schema_version": schema_version, "key_id": key_id,
            })
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
                    existing_event = self._row(existing, duplicate=True)
                    same_request = (
                        existing_event["aggregate_id"] == aggregate_id
                        and existing_event["event_type"] == event_type
                        and existing_event["source"] == source
                        and existing_event["actor_id"] == actor_id
                        and canonical_json(existing_event["payload"]) == payload_json
                    )
                    if not same_request:
                        raise ValueError("Idempotency key is already bound to different evidence")
                    return existing_event
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
                    key_id=self._key_id,
                )
                event_hash = self._digest(material, self._key_id)
                conn.execute("""
                    INSERT INTO evidence_ledger_events(
                        event_id,aggregate_id,sequence_no,event_type,recorded_at,effective_at,
                        source,actor_id,idempotency_key,payload_json,previous_hash,event_hash,
                        hash_algorithm,schema_version,key_id
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    event_id, aggregate_id, sequence_no, event_type, recorded_at, effective_at,
                    source, actor_id, idempotency_key, payload_json, previous_hash, event_hash,
                    algorithm, LEDGER_SCHEMA_VERSION, self._key_id,
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
            "key_id",
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

    def aggregate_ids(self, prefix: str | None = None) -> list[str]:
        """List aggregate identifiers without exposing event payloads."""
        conn = self._connect()
        try:
            if prefix is None:
                rows = conn.execute(
                    "SELECT DISTINCT aggregate_id FROM evidence_ledger_events ORDER BY aggregate_id"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT DISTINCT aggregate_id FROM evidence_ledger_events "
                    "WHERE aggregate_id LIKE ? ORDER BY aggregate_id",
                    (f"{str(prefix)}%",),
                ).fetchall()
        finally:
            conn.close()
        return [str(row[0]) for row in rows]

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
                        key_id=row.get("key_id"),
                    )
                    valid = (
                        row["sequence_no"] == expected_sequence
                        and row["previous_hash"] == previous_hash
                        and (row.get("key_id") in self._keyring or not row.get("key_id"))
                        and hmac.compare_digest(row["event_hash"], self._digest(material, row.get("key_id")))
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

    def queue_delivery(self, event: Mapping, error: str = "") -> None:
        """Persist a durable-delivery retry without mutating ledger evidence."""
        payload = canonical_json(event)
        now_dt = _utcnow()
        now = _iso(now_dt)
        with self._lock:
            conn = self._connect()
            try:
                existing = conn.execute(
                    "SELECT attempts FROM evidence_delivery_outbox WHERE idempotency_key=?",
                    (str(event["idempotency_key"]),),
                ).fetchone()
                attempt_number = int(existing[0]) + 1 if existing else 1
                delay_seconds = min(3600, 30 * (2 ** min(attempt_number - 1, 7)))
                next_attempt = _iso(now_dt + dt.timedelta(seconds=delay_seconds))
                conn.execute("""
                    INSERT INTO evidence_delivery_outbox(
                        idempotency_key,event_json,attempts,last_error,next_attempt_at,created_at,delivered_at
                    ) VALUES (?,?,1,?,?,?,NULL)
                    ON CONFLICT(idempotency_key) DO UPDATE SET
                        attempts=evidence_delivery_outbox.attempts+1,
                        last_error=excluded.last_error,next_attempt_at=excluded.next_attempt_at,
                        delivered_at=NULL
                """, (str(event["idempotency_key"]), payload, str(error)[:500], next_attempt, now))
                conn.commit()
            finally:
                conn.close()

    def pending_deliveries(self, limit=100) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT event_json FROM evidence_delivery_outbox
                WHERE delivered_at IS NULL AND next_attempt_at<=?
                ORDER BY created_at LIMIT ?
            """, (_iso(), max(int(limit), 1))).fetchall()
        finally:
            conn.close()
        return [json.loads(row[0]) for row in rows]

    def mark_delivered(self, idempotency_key: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE evidence_delivery_outbox SET delivered_at=?,last_error=NULL WHERE idempotency_key=?",
                    (_iso(), str(idempotency_key)),
                )
                conn.commit()
            finally:
                conn.close()

    def outbox_stats(self, *, now=None) -> dict:
        """Return bounded reconciliation telemetry without exposing event payloads."""
        observed_at = _iso(now)
        conn = self._connect()
        try:
            row = conn.execute("""
                SELECT COUNT(*), MIN(created_at), MAX(attempts)
                FROM evidence_delivery_outbox WHERE delivered_at IS NULL
            """).fetchone()
        finally:
            conn.close()
        pending = int(row[0] or 0)
        oldest_seconds = 0.0
        if pending and row[1]:
            oldest_seconds = max(
                (_utc_datetime_for_outbox(observed_at) - _utc_datetime_for_outbox(row[1])).total_seconds(),
                0.0,
            )
        return {
            "pending": pending,
            "oldest_pending_seconds": oldest_seconds,
            "maximum_attempts": int(row[2] or 0),
            "observed_at": observed_at,
        }


def _utc_datetime_for_outbox(value) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)
