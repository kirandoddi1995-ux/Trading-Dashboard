"""Versioned regime models, shadow challengers and drift measurements."""
from __future__ import annotations
import datetime as dt, json, sqlite3
import numpy as np


class ModelRegistry:
    def __init__(self, connect_fn, db_path):
        self.connect_fn, self.db_path = connect_fn, db_path; self.ensure_schema()
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
            """); conn.commit()
        finally: conn.close()
    def register(self, model_id, model_type, regime, version, role, artifact, metrics, status="SHADOW", trained_from=None, trained_to=None):
        if role not in {"champion","challenger"}: raise ValueError("Invalid model role")
        conn=self.connect()
        try:
            conn.execute("INSERT OR REPLACE INTO model_registry VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              (model_id,model_type,regime,version,role,status,json.dumps(artifact,sort_keys=True),
               json.dumps(metrics,sort_keys=True),trained_from,trained_to,dt.datetime.now(dt.timezone.utc).isoformat())); conn.commit()
        finally: conn.close()
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

