"""Versioned model registry with signed lifecycle transitions and rollback."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading
import uuid
from typing import Callable, Mapping, Sequence

import numpy as np

from artifact_security import ApprovalAuthority, validate_independent_approvals
from resilience_control_plane import canonical_hash


_ALLOWED_TRANSITIONS = {"SHADOW": "PAPER", "PAPER": "CANARY"}


class ModelRegistry:
    def __init__(self, connect_fn, db_path):
        self.connect_fn, self.db_path = connect_fn, db_path
        self._lock = threading.RLock()
        self.ensure_schema()

    def connect(self):
        return self.connect_fn(self.db_path)

    def ensure_schema(self):
        conn = self.connect()
        try:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS model_registry(
              model_id TEXT PRIMARY KEY, model_type TEXT NOT NULL, regime TEXT NOT NULL,
              version TEXT NOT NULL, role TEXT NOT NULL, status TEXT NOT NULL,
              artifact_json TEXT NOT NULL, metrics_json TEXT NOT NULL, trained_from TEXT,
              trained_to TEXT, created_at TEXT NOT NULL, registry_version INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS model_drift(
              model_id TEXT NOT NULL, measured_at TEXT NOT NULL, feature TEXT NOT NULL,
              psi REAL, mean_shift REAL, status TEXT NOT NULL,
              PRIMARY KEY(model_id, measured_at, feature));
            CREATE TABLE IF NOT EXISTS model_promotions(
              promotion_id TEXT PRIMARY KEY, model_id TEXT NOT NULL, previous_model_id TEXT,
              regime TEXT NOT NULL, action TEXT NOT NULL, approved_by TEXT NOT NULL,
              reason TEXT NOT NULL, attestation_hash TEXT NOT NULL, created_at TEXT NOT NULL,
              approvals_json TEXT NOT NULL DEFAULT '[]', artifact_hash TEXT,
              registry_version INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS model_stage_transitions(
              transition_id TEXT PRIMARY KEY, model_id TEXT NOT NULL, from_stage TEXT NOT NULL,
              to_stage TEXT NOT NULL, approved_by TEXT NOT NULL, reason TEXT NOT NULL,
              artifact_hash TEXT NOT NULL, attestation_hash TEXT NOT NULL,
              registry_version INTEGER NOT NULL, created_at TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS model_promotions_no_update BEFORE UPDATE ON model_promotions
              BEGIN SELECT RAISE(ABORT, 'model promotion history is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS model_promotions_no_delete BEFORE DELETE ON model_promotions
              BEGIN SELECT RAISE(ABORT, 'model promotion history is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS model_transitions_no_update BEFORE UPDATE ON model_stage_transitions
              BEGIN SELECT RAISE(ABORT, 'model stage history is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS model_transitions_no_delete BEFORE DELETE ON model_stage_transitions
              BEGIN SELECT RAISE(ABORT, 'model stage history is immutable'); END;
            """)
            registry_columns = {row[1] for row in conn.execute("PRAGMA table_info(model_registry)")}
            if "registry_version" not in registry_columns:
                conn.execute("ALTER TABLE model_registry ADD COLUMN registry_version INTEGER NOT NULL DEFAULT 0")
            promotion_columns = {row[1] for row in conn.execute("PRAGMA table_info(model_promotions)")}
            for column, definition in (
                ("approvals_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("artifact_hash", "TEXT"),
                ("registry_version", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if column not in promotion_columns:
                    conn.execute(f"ALTER TABLE model_promotions ADD COLUMN {column} {definition}")
            conn.commit()
        finally:
            conn.close()

    def register(self, model_id, model_type, regime, version, role, artifact, metrics,
                 status="SHADOW", trained_from=None, trained_to=None, *, bootstrap_active=False):
        if role not in {"champion", "challenger"}:
            raise ValueError("Invalid model role")
        stage = str(status).upper()
        if bootstrap_active:
            raise ValueError("bootstrap_active is forbidden; use bootstrap_champion with signed approvals")
        if stage in {"PAPER", "CANARY", "ACTIVE"}:
            raise ValueError("Direct PAPER/CANARY/ACTIVE registration is forbidden; use signed lifecycle transitions")
        allowed = {"AWAITING_VALIDATION", "SHADOW", "PAPER", "CANARY", "ROLLBACK", "ACTIVE"}
        if stage not in allowed:
            raise ValueError("Invalid model stage")
        conn = self.connect()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO model_registry(" 
                "model_id,model_type,regime,version,role,status,artifact_json,metrics_json," 
                "trained_from,trained_to,created_at,registry_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,0)",
                (model_id, model_type, regime, version, role, stage,
                 json.dumps(artifact, sort_keys=True), json.dumps(metrics, sort_keys=True),
                 trained_from, trained_to, dt.datetime.now(dt.timezone.utc).isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    def bootstrap_champion(self, model_id, model_type, regime, version, artifact, metrics, *,
                           approvals: Sequence[Mapping], artifact_authority,
                           approval_authority: ApprovalAuthority,
                           reason="initial champion authorization", trained_from=None,
                           trained_to=None):
        """Authorize the first champion; there is no unsigned initialization bypass."""
        if not str(reason).strip():
            raise ValueError("Bootstrap reason is required")
        package = dict(artifact or {})
        if not artifact_authority.verify(package):
            raise ValueError("Artifact signature verification failed")
        verified = validate_independent_approvals(
            approvals, artifact_hash=package["artifact_hash"], action="BOOTSTRAP",
            authority=approval_authority,
        )
        with self._lock:
            conn = self.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    "SELECT model_id FROM model_registry WHERE regime=? AND role='champion' "
                    "AND status='ACTIVE' LIMIT 1", (str(regime),),
                ).fetchone()
                if existing:
                    raise ValueError("An ACTIVE champion already exists for this regime")
                now = dt.datetime.now(dt.timezone.utc).isoformat()
                conn.execute(
                    "INSERT INTO model_registry(" 
                    "model_id,model_type,regime,version,role,status,artifact_json,metrics_json," 
                    "trained_from,trained_to,created_at,registry_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,0)",
                    (str(model_id), str(model_type), str(regime), str(version), "champion", "ACTIVE",
                     json.dumps(package, sort_keys=True), json.dumps(metrics, sort_keys=True),
                     trained_from, trained_to, now),
                )
                attestation = canonical_hash({
                    "action": "BOOTSTRAP", "model_id": str(model_id),
                    "artifact_hash": package["artifact_hash"], "approvals": verified,
                    "reason": str(reason), "registry_version": 0,
                })
                promotion_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO model_promotions(" 
                    "promotion_id,model_id,previous_model_id,regime,action,approved_by,reason," 
                    "attestation_hash,created_at,approvals_json,artifact_hash,registry_version) " 
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (promotion_id, str(model_id), None, str(regime), "BOOTSTRAP",
                     ",".join(row["approver"] for row in verified), str(reason), attestation,
                     now, json.dumps(verified, sort_keys=True), package["artifact_hash"], 0),
                )
                conn.commit()
            except Exception:
                conn.rollback(); raise
            finally:
                conn.close()
        return {"promotion_id": promotion_id, "model_id": str(model_id),
                "previous_model_id": None, "attestation_hash": attestation}

    def get_model(self, model_id) -> dict | None:
        conn = self.connect()
        try:
            row = conn.execute(
                "SELECT model_id,model_type,regime,version,role,status,artifact_json,metrics_json," 
                "trained_from,trained_to,created_at,registry_version FROM model_registry WHERE model_id=?",
                (str(model_id),),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return {
            "model_id": row[0], "model_type": row[1], "regime": row[2], "version": row[3],
            "role": row[4], "status": row[5], "artifact": json.loads(row[6]),
            "metrics": json.loads(row[7]), "trained_from": row[8], "trained_to": row[9],
            "created_at": row[10], "registry_version": int(row[11]),
        }

    def active_champion(self, *, regime="GLOBAL", strategy_id=None, target_version=None,
                        horizon_sessions=None) -> dict | None:
        conn = self.connect()
        try:
            rows = conn.execute(
                "SELECT model_id FROM model_registry WHERE regime=? AND role='champion' "
                "AND status='ACTIVE' ORDER BY created_at DESC", (str(regime),),
            ).fetchall()
        finally:
            conn.close()
        for row in rows:
            record = self.get_model(row[0])
            artifact = record["artifact"]
            checks = {
                "strategy_id": strategy_id, "target_version": target_version,
                "horizon_sessions": horizon_sessions,
            }
            if all(expected is None or str(artifact.get(key, "")) == str(expected)
                   for key, expected in checks.items()):
                return record
        return None

    def attach_signed_artifact(self, model_id, artifact, *, verify_artifact: Callable[[Mapping], bool],
                               expected_registry_version: int) -> dict:
        if not callable(verify_artifact) or not verify_artifact(artifact):
            raise ValueError("Artifact signature verification failed")
        with self._lock:
            conn = self.connect()
            try:
                cursor = conn.execute(
                    "UPDATE model_registry SET artifact_json=?,registry_version=registry_version+1 "
                    "WHERE model_id=? AND status='SHADOW' AND registry_version=?",
                    (json.dumps(dict(artifact), sort_keys=True), str(model_id), int(expected_registry_version)),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("Concurrent registry update or invalid model stage")
                conn.commit()
            except Exception:
                conn.rollback(); raise
            finally:
                conn.close()
        return self.get_model(model_id)

    def transition(self, model_id, to_stage, *, approved_by, reason,
                   verify_artifact: Callable[[Mapping], bool], expected_registry_version: int):
        destination = str(to_stage).upper()
        if not str(approved_by).strip() or not str(reason).strip():
            raise ValueError("Reviewer identity and transition reason are required")
        with self._lock:
            conn = self.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT status,artifact_json,registry_version FROM model_registry WHERE model_id=?",
                    (str(model_id),),
                ).fetchone()
                if not row:
                    raise ValueError("Model is not registered")
                source, artifact, version = row[0], json.loads(row[1]), int(row[2])
                if _ALLOWED_TRANSITIONS.get(source) != destination:
                    raise ValueError(f"Invalid model transition {source}->{destination}")
                if version != int(expected_registry_version):
                    raise RuntimeError("Concurrent registry update detected")
                if not callable(verify_artifact) or not verify_artifact(artifact):
                    raise ValueError("Artifact signature verification failed")
                next_version = version + 1
                cursor = conn.execute(
                    "UPDATE model_registry SET status=?,registry_version=? "
                    "WHERE model_id=? AND registry_version=?",
                    (destination, next_version, str(model_id), version),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("Concurrent registry update detected")
                attestation = canonical_hash({
                    "model_id": str(model_id), "from": source, "to": destination,
                    "artifact_hash": artifact["artifact_hash"], "registry_version": next_version,
                    "approved_by": str(approved_by), "reason": str(reason),
                })
                conn.execute(
                    "INSERT INTO model_stage_transitions VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (str(uuid.uuid4()), str(model_id), source, destination, str(approved_by),
                     str(reason), artifact["artifact_hash"], attestation, next_version,
                     dt.datetime.now(dt.timezone.utc).isoformat()),
                )
                conn.commit()
            except Exception:
                conn.rollback(); raise
            finally:
                conn.close()
        return self.get_model(model_id)

    def promote(self, model_id, gate_result, *, approvals: Sequence[Mapping],
                artifact_authority, approval_authority: ApprovalAuthority,
                reason="validated production promotion"):
        if not gate_result.get("promotion_allowed") or gate_result.get("status") != "APPROVED":
            raise ValueError("Model promotion gate has not approved this artifact")
        with self._lock:
            conn = self.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                candidate = conn.execute(
                    "SELECT model_id,regime,role,status,artifact_json,registry_version "
                    "FROM model_registry WHERE model_id=?", (str(model_id),),
                ).fetchone()
                if not candidate:
                    raise ValueError("Candidate model is not registered")
                artifact = json.loads(candidate[4])
                if candidate[2] != "challenger" or candidate[3] != "CANARY":
                    raise ValueError("Only a signed challenger in CANARY may be promoted")
                if not artifact_authority.verify(artifact):
                    raise ValueError("Artifact signature verification failed")
                verified = validate_independent_approvals(
                    approvals, artifact_hash=artifact["artifact_hash"], action="PROMOTE",
                    authority=approval_authority,
                )
                previous = conn.execute(
                    "SELECT model_id FROM model_registry WHERE regime=? AND role='champion' "
                    "AND status='ACTIVE' LIMIT 1", (candidate[1],),
                ).fetchone()
                previous_id = previous[0] if previous else None
                if previous_id:
                    conn.execute(
                        "UPDATE model_registry SET role='challenger',status='ROLLBACK'," 
                        "registry_version=registry_version+1 WHERE model_id=?", (previous_id,),
                    )
                next_version = int(candidate[5]) + 1
                cursor = conn.execute(
                    "UPDATE model_registry SET role='champion',status='ACTIVE',registry_version=? "
                    "WHERE model_id=? AND registry_version=?",
                    (next_version, str(model_id), int(candidate[5])),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("Concurrent registry update detected")
                promotion_id = str(uuid.uuid4())
                attestation = canonical_hash({
                    "gate": gate_result, "approvals": verified,
                    "artifact_hash": artifact["artifact_hash"], "registry_version": next_version,
                })
                conn.execute(
                    "INSERT INTO model_promotions(" 
                    "promotion_id,model_id,previous_model_id,regime,action,approved_by,reason," 
                    "attestation_hash,created_at,approvals_json,artifact_hash,registry_version) " 
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (promotion_id, str(model_id), previous_id, candidate[1], "PROMOTE",
                     ",".join(row["approver"] for row in verified), str(reason), attestation,
                     dt.datetime.now(dt.timezone.utc).isoformat(), json.dumps(verified, sort_keys=True),
                     artifact["artifact_hash"], next_version),
                )
                conn.commit()
                return {"promotion_id": promotion_id, "model_id": str(model_id),
                        "previous_model_id": previous_id, "attestation_hash": attestation}
            except Exception:
                conn.rollback(); raise
            finally:
                conn.close()

    def rollback(self, promotion_id, *, approvals: Sequence[Mapping], artifact_authority,
                 approval_authority: ApprovalAuthority, reason="canary rollback"):
        with self._lock:
            conn = self.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                promotion = conn.execute(
                    "SELECT model_id,previous_model_id,regime FROM model_promotions "
                    "WHERE promotion_id=? AND action='PROMOTE'", (str(promotion_id),),
                ).fetchone()
                if not promotion or not promotion[1]:
                    raise ValueError("Promotion has no rollback model")
                previous = conn.execute(
                    "SELECT artifact_json,registry_version,role,status FROM model_registry WHERE model_id=?",
                    (promotion[1],),
                ).fetchone()
                current = conn.execute(
                    "SELECT registry_version,role,status FROM model_registry WHERE model_id=?",
                    (promotion[0],),
                ).fetchone()
                if not previous or not current or previous[3] != "ROLLBACK" or current[2] != "ACTIVE":
                    raise ValueError("Rollback lineage is not in a recoverable state")
                artifact = json.loads(previous[0])
                if not artifact_authority.verify(artifact):
                    raise ValueError("Rollback artifact signature verification failed")
                verified = validate_independent_approvals(
                    approvals, artifact_hash=artifact["artifact_hash"], action="ROLLBACK",
                    authority=approval_authority,
                )
                conn.execute(
                    "UPDATE model_registry SET role='challenger',status='CANARY'," 
                    "registry_version=registry_version+1 WHERE model_id=?", (promotion[0],),
                )
                next_version = int(previous[1]) + 1
                conn.execute(
                    "UPDATE model_registry SET role='champion',status='ACTIVE',registry_version=? "
                    "WHERE model_id=?", (next_version, promotion[1]),
                )
                rollback_id = str(uuid.uuid4())
                attestation = canonical_hash({
                    "source_promotion": str(promotion_id), "approvals": verified,
                    "artifact_hash": artifact["artifact_hash"], "registry_version": next_version,
                })
                conn.execute(
                    "INSERT INTO model_promotions(" 
                    "promotion_id,model_id,previous_model_id,regime,action,approved_by,reason," 
                    "attestation_hash,created_at,approvals_json,artifact_hash,registry_version) " 
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rollback_id, promotion[1], promotion[0], promotion[2], "ROLLBACK",
                     ",".join(row["approver"] for row in verified), str(reason), attestation,
                     dt.datetime.now(dt.timezone.utc).isoformat(), json.dumps(verified, sort_keys=True),
                     artifact["artifact_hash"], next_version),
                )
                conn.commit()
                return {"promotion_id": rollback_id, "model_id": promotion[1],
                        "previous_model_id": promotion[0], "attestation_hash": attestation}
            except Exception:
                conn.rollback(); raise
            finally:
                conn.close()

    def record_drift(self, model_id, feature, reference, current, maximum_psi=0.20):
        psi = self.population_stability_index(reference, current)
        measured_at = dt.datetime.now(dt.timezone.utc).isoformat()
        ref = np.asarray(reference, dtype=float); cur = np.asarray(current, dtype=float)
        ref = ref[np.isfinite(ref)]; cur = cur[np.isfinite(cur)]
        mean_shift = float(np.mean(cur) - np.mean(ref)) if len(ref) and len(cur) else None
        status = "UNAVAILABLE" if psi is None else ("HALT" if psi > float(maximum_psi) else "PASS")
        conn = self.connect()
        try:
            conn.execute("INSERT INTO model_drift VALUES(?,?,?,?,?,?)",
                         (model_id, measured_at, str(feature), psi, mean_shift, status)); conn.commit()
        finally:
            conn.close()
        return {"model_id": model_id, "feature": str(feature), "psi": psi,
                "mean_shift": mean_shift, "status": status, "measured_at": measured_at}

    @staticmethod
    def population_stability_index(reference, current, bins=10):
        ref = np.asarray(reference, dtype=float); cur = np.asarray(current, dtype=float)
        ref = ref[np.isfinite(ref)]; cur = cur[np.isfinite(cur)]
        if len(ref) < 20 or len(cur) < 20:
            return None
        edges = np.unique(np.quantile(ref, np.linspace(0, 1, bins + 1)))
        if len(edges) < 3:
            return 0.0
        rp = np.histogram(ref, edges)[0] / len(ref); cp = np.histogram(cur, edges)[0] / len(cur)
        rp = np.clip(rp, 1e-6, None); cp = np.clip(cp, 1e-6, None)
        return float(np.sum((cp - rp) * np.log(cp / rp)))
