"""Versioned regime models, shadow challengers and drift measurements."""
from __future__ import annotations
import datetime as dt, hashlib, json, sqlite3, threading, uuid
import numpy as np
from resilience_control_plane import canonical_hash


class ModelRegistry:
    def __init__(self, connect_fn, db_path):
        self.connect_fn, self.db_path = connect_fn, db_path
        self._lock = threading.RLock()
        self.ensure_schema()
    def connect(self): return self.connect_fn(self.db_path)
    def ensure_schema(self):
        conn=self.connect()
        try:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS model_registry(model_id TEXT PRIMARY KEY, model_type TEXT NOT NULL,
              regime TEXT NOT NULL, version TEXT NOT NULL, role TEXT NOT NULL, status TEXT NOT NULL,
              artifact_json TEXT NOT NULL, metrics_json TEXT NOT NULL, trained_from TEXT, trained_to TEXT,
              created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS model_drift(model_id TEXT NOT NULL, measured_at TEXT NOT NULL,
              feature TEXT NOT NULL, psi REAL, mean_shift REAL, status TEXT NOT NULL,
              PRIMARY KEY(model_id, measured_at, feature));
            CREATE TABLE IF NOT EXISTS model_promotions(
              promotion_id TEXT PRIMARY KEY, model_id TEXT NOT NULL, previous_model_id TEXT,
              regime TEXT NOT NULL, action TEXT NOT NULL, approved_by TEXT NOT NULL,
              reason TEXT NOT NULL, attestation_hash TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS model_promotions_no_update BEFORE UPDATE ON model_promotions
              BEGIN SELECT RAISE(ABORT, 'model promotion history is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS model_promotions_no_delete BEFORE DELETE ON model_promotions
              BEGIN SELECT RAISE(ABORT, 'model promotion history is immutable'); END;
            """); conn.commit()
        finally: conn.close()
    def register(self, model_id, model_type, regime, version, role, artifact, metrics, status="SHADOW", trained_from=None, trained_to=None):
        if role not in {"champion","challenger"}: raise ValueError("Invalid model role")
        conn=self.connect()
        try:
            conn.execute("INSERT OR IGNORE INTO model_registry VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              (model_id,model_type,regime,version,role,status,json.dumps(artifact,sort_keys=True),
               json.dumps(metrics,sort_keys=True),trained_from,trained_to,dt.datetime.now(dt.timezone.utc).isoformat())); conn.commit()
        finally: conn.close()
    def record_drift(self, model_id, feature, reference, current, maximum_psi=0.20):
        psi = self.population_stability_index(reference, current)
        measured_at = dt.datetime.now(dt.timezone.utc).isoformat()
        ref = np.asarray(reference, dtype=float); cur = np.asarray(current, dtype=float)
        ref = ref[np.isfinite(ref)]; cur = cur[np.isfinite(cur)]
        mean_shift = (float(np.mean(cur) - np.mean(ref)) if len(ref) and len(cur) else None)
        status = "UNAVAILABLE" if psi is None else ("HALT" if psi > float(maximum_psi) else "PASS")
        conn = self.connect()
        try:
            conn.execute("INSERT INTO model_drift VALUES(?,?,?,?,?,?)",
                         (model_id, measured_at, str(feature), psi, mean_shift, status))
            conn.commit()
        finally: conn.close()
        return {"model_id": model_id, "feature": str(feature), "psi": psi,
                "mean_shift": mean_shift, "status": status, "measured_at": measured_at}

    def promote(self, model_id, gate_result, *, approved_by, reason="validated promotion"):
        """Atomically promote an approved challenger and retain immutable rollback lineage."""
        if not gate_result.get("promotion_allowed") or gate_result.get("status") != "APPROVED":
            raise ValueError("Model promotion gate has not approved this artifact")
        if not str(approved_by).strip():
            raise ValueError("Independent approver identity is required")
        with self._lock:
            conn = self.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                candidate = conn.execute(
                    "SELECT model_id,regime,role,status,artifact_json FROM model_registry WHERE model_id=?",
                    (str(model_id),),
                ).fetchone()
                if not candidate:
                    raise ValueError("Candidate model is not registered")
                if candidate[2] != "challenger" or candidate[3] not in {"SHADOW", "PAPER", "CANARY"}:
                    raise ValueError("Only a validated challenger in SHADOW/PAPER/CANARY may be promoted")
                previous = conn.execute(
                    "SELECT model_id FROM model_registry WHERE regime=? AND role='champion' AND status='ACTIVE' LIMIT 1",
                    (candidate[1],),
                ).fetchone()
                previous_id = previous[0] if previous else None
                if previous_id:
                    conn.execute("UPDATE model_registry SET role='challenger',status='ROLLBACK' WHERE model_id=?", (previous_id,))
                conn.execute("UPDATE model_registry SET role='champion',status='ACTIVE' WHERE model_id=?", (str(model_id),))
                promotion_id = str(uuid.uuid4())
                attestation = str(gate_result.get("attestation_hash") or canonical_hash(gate_result))
                conn.execute(
                    "INSERT INTO model_promotions VALUES(?,?,?,?,?,?,?,?,?)",
                    (promotion_id, str(model_id), previous_id, candidate[1], "PROMOTE",
                     str(approved_by), str(reason), attestation,
                     dt.datetime.now(dt.timezone.utc).isoformat()),
                )
                conn.commit()
                return {"promotion_id": promotion_id, "model_id": str(model_id),
                        "previous_model_id": previous_id, "attestation_hash": attestation}
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
    @staticmethod
    def population_stability_index(reference, current, bins=10):
        ref=np.asarray(reference,dtype=float); cur=np.asarray(current,dtype=float)
        ref=ref[np.isfinite(ref)]; cur=cur[np.isfinite(cur)]
        if len(ref)<20 or len(cur)<20: return None
        edges=np.unique(np.quantile(ref,np.linspace(0,1,bins+1)))
        if len(edges)<3: return 0.0
        rp=np.histogram(ref,edges)[0]/len(ref); cp=np.histogram(cur,edges)[0]/len(cur)
        rp=np.clip(rp,1e-6,None); cp=np.clip(cp,1e-6,None)
        return float(np.sum((cp-rp)*np.log(cp/rp)))
