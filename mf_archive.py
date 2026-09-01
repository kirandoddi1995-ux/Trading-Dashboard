"""Point-in-time archive for mutual-fund disclosures and category membership."""
from __future__ import annotations
import datetime as dt, hashlib, json


class MutualFundArchive:
    def __init__(self, connect_fn, db_path): self.connect_fn,self.db_path=connect_fn,db_path; self.ensure_schema()
    def connect(self): return self.connect_fn(self.db_path)
    def ensure_schema(self):
        conn=self.connect()
        try:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS mf_point_in_time(scheme_code TEXT NOT NULL, snapshot_date TEXT NOT NULL,
              scheme_name TEXT, category TEXT, ter REAL, benchmark TEXT, riskometer TEXT, aum REAL,
              status TEXT, merger_into TEXT, source TEXT NOT NULL, payload_hash TEXT NOT NULL,
              observed_at TEXT NOT NULL, PRIMARY KEY(scheme_code,snapshot_date));
            CREATE INDEX IF NOT EXISTS idx_mf_pit_category_date ON mf_point_in_time(category,snapshot_date);
            """); conn.commit()
        finally: conn.close()
    def archive(self, records, snapshot_date=None, source="official disclosures"):
        date=str(snapshot_date or dt.date.today()); now=dt.datetime.now(dt.timezone.utc).isoformat(); rows=[]
        for r in records or []:
            code=str(r.get("scheme_code") or r.get("schemeCode") or "").strip()
            if not code: continue
            payload=json.dumps(r,sort_keys=True,default=str); digest=hashlib.sha256(payload.encode()).hexdigest()
            rows.append((code,date,r.get("scheme_name") or r.get("schemeName"),r.get("category"),r.get("ter"),
                         r.get("benchmark_name") or r.get("benchmark"),r.get("riskometer"),r.get("aum"),
                         r.get("status","active"),r.get("merger_into"),source,digest,now))
        conn=self.connect()
        try:
            conn.executemany("INSERT OR REPLACE INTO mf_point_in_time VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",rows); conn.commit()
        finally: conn.close()
        return len(rows)

