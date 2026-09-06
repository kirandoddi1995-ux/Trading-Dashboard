"""Persistence for signed conformal, fill-model, and portfolio evidence."""
from __future__ import annotations

import datetime as dt
import json
import math
import threading
import uuid
from typing import Callable, Mapping

import pandas as pd

from live_evidence import aware_utc


EVIDENCE_KINDS = {"CONFORMAL", "FILL", "PORTFOLIO"}


class RuntimeEvidenceStore:
    def __init__(self, connect_fn, db_path):
        self._connect_fn, self._db_path = connect_fn, db_path
        self._lock = threading.RLock()
        self.ensure_schema()

    def _connect(self):
        return self._connect_fn(self._db_path)

    def ensure_schema(self):
        conn = self._connect()
        try:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS runtime_evidence_artifacts(
              evidence_id TEXT PRIMARY KEY, kind TEXT NOT NULL, strategy_id TEXT NOT NULL,
              asset_class TEXT NOT NULL, target_version TEXT NOT NULL,
              horizon_sessions INTEGER NOT NULL, feature_schema_hash TEXT NOT NULL,
              artifact_json TEXT NOT NULL, artifact_hash TEXT NOT NULL,
              created_at TEXT NOT NULL, valid_until TEXT NOT NULL, status TEXT NOT NULL,
              UNIQUE(kind,strategy_id,asset_class,target_version,horizon_sessions,
                     feature_schema_hash,artifact_hash));
            CREATE TRIGGER IF NOT EXISTS runtime_evidence_no_update
              BEFORE UPDATE ON runtime_evidence_artifacts
              BEGIN SELECT RAISE(ABORT, 'runtime evidence is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS runtime_evidence_no_delete
              BEFORE DELETE ON runtime_evidence_artifacts
              BEGIN SELECT RAISE(ABORT, 'runtime evidence is immutable'); END;
            """)
            conn.commit()
        finally:
            conn.close()

    def save(self, kind: str, artifact: Mapping, *, verify_signature: Callable[[Mapping], bool]) -> str:
        evidence_kind = str(kind).upper()
        if evidence_kind not in EVIDENCE_KINDS:
            raise ValueError("Unsupported runtime evidence kind")
        row = dict(artifact or {})
        if not callable(verify_signature) or not verify_signature(row):
            raise ValueError("Runtime evidence signature verification failed")
        required = {
            "strategy_id", "asset_class", "target_version", "horizon_sessions",
            "feature_schema_hash", "artifact_hash", "created_at", "valid_until", "status",
        }
        missing = sorted(required - set(row))
        if missing:
            raise ValueError(f"Runtime evidence is missing: {', '.join(missing)}")
        created = aware_utc(row["created_at"], name="created_at")
        valid_until = aware_utc(row["valid_until"], name="valid_until")
        if valid_until <= created:
            raise ValueError("Runtime evidence validity window is invalid")
        if str(row["status"]).upper() != "VALIDATED":
            raise ValueError("Only VALIDATED runtime evidence can be stored")
        evidence_id = str(uuid.uuid4())
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO runtime_evidence_artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (evidence_id, evidence_kind, str(row["strategy_id"]), str(row["asset_class"]),
                 str(row["target_version"]), int(row["horizon_sessions"]),
                 str(row["feature_schema_hash"]), json.dumps(row, sort_keys=True),
                 str(row["artifact_hash"]), created.isoformat(), valid_until.isoformat(),
                 str(row["status"]).upper()),
            )
            conn.commit()
        finally:
            conn.close()
        return evidence_id

    def latest(self, kind: str, context: Mapping, *, verify_signature: Callable[[Mapping], bool],
               now=None) -> dict | None:
        evidence_kind = str(kind).upper()
        current = aware_utc(now or dt.datetime.now(dt.timezone.utc), name="now")
        keys = ("strategy_id", "asset_class", "target_version", "horizon_sessions", "feature_schema_hash")
        if any(context.get(key) in (None, "") for key in keys):
            return None
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT artifact_json FROM runtime_evidence_artifacts WHERE kind=? AND strategy_id=? "
                "AND asset_class=? AND target_version=? AND horizon_sessions=? AND feature_schema_hash=? "
                "AND status='VALIDATED' ORDER BY created_at DESC",
                (evidence_kind, str(context["strategy_id"]), str(context["asset_class"]),
                 str(context["target_version"]), int(context["horizon_sessions"]),
                 str(context["feature_schema_hash"])),
            ).fetchall()
        finally:
            conn.close()
        for raw in rows:
            artifact = json.loads(raw[0])
            try:
                unexpired = aware_utc(artifact["valid_until"], name="valid_until") >= current
            except (KeyError, ValueError):
                continue
            if unexpired and callable(verify_signature) and verify_signature(artifact):
                return artifact
        return None

    def portfolio(self, context: Mapping, *, verify_signature: Callable[[Mapping], bool],
                  now=None) -> dict | None:
        artifact = self.latest("PORTFOLIO", context, verify_signature=verify_signature, now=now)
        if not artifact:
            return None
        data = artifact.get("returns")
        try:
            frame = pd.DataFrame(data["data"], index=pd.to_datetime(data["index"]), columns=data["columns"])
            frame = frame.apply(pd.to_numeric, errors="coerce")
        except (KeyError, TypeError, ValueError):
            return None
        if len(frame) < 60 or frame.isna().mean().max() > 0.05:
            return None
        weights = {str(key): float(value) for key, value in dict(artifact.get("weights") or {}).items()}
        if not weights or any(not math.isfinite(value) for value in weights.values()):
            return None
        return {"returns": frame, "weights": weights,
                "stress_scenarios": dict(artifact.get("stress_scenarios") or {}),
                "artifact_hash": artifact["artifact_hash"]}
