"""Restricted PostgreSQL repository for equity scan recovery and manual checks."""
from __future__ import annotations

import json
from collections.abc import Mapping


SCHEMA = "equity_operations"


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False)


class EquityScanRepository:
    """Uses an injected restricted connection; it never creates or migrates schema."""

    def __init__(self, connect=None):
        self._connect = connect

    @property
    def configured(self):
        return callable(self._connect)

    def _connection(self):
        if not self.configured:
            raise RuntimeError("Equity operational repository is not configured")
        return self._connect()

    def create_run(self, run: Mapping, items):
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO {SCHEMA}.scan_runs
                      (run_id,owner_id,signature,scan_mode,horizon_sessions,status,
                       fencing_token,started_at,heartbeat_at,metadata)
                    VALUES (%s,%s,%s,%s,%s,'RUNNING',%s,to_timestamp(%s),clock_timestamp(),%s::jsonb)
                    ON CONFLICT (run_id) DO NOTHING
                """, (run["id"], run["owner"], run["signature"],
                      str((run.get("metadata") or {}).get("scan_mode") or "unknown"),
                      int((run.get("metadata") or {}).get("horizon_sessions") or 1),
                      int(run.get("fencing_token", 1)), float(run["started_at"]),
                      _json(run.get("metadata") or {})))
                for item in items:
                    instrument = str(item.get("ticker") if isinstance(item, Mapping) else item)
                    cur.execute(f"""
                        INSERT INTO {SCHEMA}.scan_candidates
                          (run_id,instrument,item,status,attempt_no,updated_at)
                        VALUES (%s,%s,%s::jsonb,'PENDING',0,clock_timestamp())
                        ON CONFLICT (run_id,instrument) DO NOTHING
                    """, (run["id"], instrument, _json(item)))
            conn.commit()

    def heartbeat(self, run_id, fencing_token, *, status="RUNNING", finished_at=None, error_kind=None):
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    UPDATE {SCHEMA}.scan_runs SET status=%s,heartbeat_at=clock_timestamp(),
                      finished_at=CASE WHEN %s IS NULL THEN finished_at ELSE to_timestamp(%s) END,
                      error_kind=%s
                    WHERE run_id=%s AND fencing_token=%s
                """, (status, finished_at, finished_at, error_kind, run_id, int(fencing_token)))
                updated = cur.rowcount
            conn.commit()
        return updated == 1

    def checkpoint_candidate(self, *, run_id, instrument, fencing_token, result=None, rejection=None,
                             quote_observed_at=None, governance_decision_at=None):
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    UPDATE {SCHEMA}.scan_candidates c
                    SET status='COMPLETE',attempt_no=attempt_no+1,result=%s::jsonb,
                        rejection=%s::jsonb,quote_observed_at=%s,
                        governance_decision_at=%s,updated_at=clock_timestamp()
                    FROM {SCHEMA}.scan_runs r
                    WHERE c.run_id=r.run_id AND c.run_id=%s AND c.instrument=%s
                      AND r.fencing_token=%s AND c.status<>'COMPLETE'
                """, (_json(result) if result is not None else None,
                      _json(rejection) if rejection is not None else None,
                      quote_observed_at, governance_decision_at,
                      run_id, str(instrument), int(fencing_token)))
                updated = cur.rowcount
            conn.commit()
        return updated == 1

    def latest_recoverable(self, owner_id, signature):
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT run_id,status,fencing_token,metadata,
                           ARRAY(SELECT c.instrument FROM {SCHEMA}.scan_candidates c
                                 WHERE c.run_id=r.run_id AND c.status<>'COMPLETE'
                                 ORDER BY c.instrument),
                           (SELECT count(*) FROM {SCHEMA}.scan_candidates c
                            WHERE c.run_id=r.run_id AND c.status='COMPLETE')
                    FROM {SCHEMA}.scan_runs r
                    WHERE owner_id=%s AND signature=%s
                      AND status IN ('RUNNING','INTERRUPTED','CANCELLED','RECOVERING')
                      AND EXISTS (SELECT 1 FROM {SCHEMA}.scan_candidates c
                                  WHERE c.run_id=r.run_id AND c.status<>'COMPLETE')
                    ORDER BY started_at DESC LIMIT 1
                """, (owner_id, signature))
                row = cur.fetchone()
        if not row:
            return None
        return {"id": str(row[0]), "status": str(row[1]), "fencing_token": int(row[2]),
                "metadata": dict(row[3] or {}), "unfinished": list(row[4] or []),
                "archived_completed": int(row[5] or 0)}

    def claim_recovery(self, run_id, owner_id):
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    UPDATE {SCHEMA}.scan_runs
                    SET fencing_token=fencing_token+1,status='RECOVERING',
                        heartbeat_at=clock_timestamp(),error_kind=NULL
                    WHERE run_id=%s AND owner_id=%s
                      AND status IN ('RUNNING','INTERRUPTED','CANCELLED','RECOVERING')
                    RETURNING fencing_token,metadata
                """, (run_id, owner_id))
                row = cur.fetchone()
                if not row:
                    conn.rollback()
                    return None
                cur.execute(f"""
                    SELECT item FROM {SCHEMA}.scan_candidates
                    WHERE run_id=%s AND status<>'COMPLETE' ORDER BY instrument
                """, (run_id,))
                items = [candidate[0] for candidate in cur.fetchall()]
            conn.commit()
        return {"fencing_token": int(row[0]), "metadata": dict(row[1] or {}), "items": items}

    def save_manual_review(self, review: Mapping):
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO {SCHEMA}.manual_quote_reviews
                      (review_id,decision_id,decision_digest,scan_run_id,instrument,reviewer,
                       attested_at,secondary_platform,secondary_price,source_quote_observed_at,
                       primary_price,difference_bps,status,payload)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                    ON CONFLICT (review_id) DO NOTHING
                """, (review["review_id"], review["decision_id"], review["decision_digest"],
                      review.get("scan_run_id"), review["instrument"], review["reviewer"],
                      review["attested_at"], review["secondary_platform"], review["secondary_price"],
                      review.get("source_quote_observed_at"), review["primary_price"],
                      review["difference_bps"], review["status"], _json(review)))
                inserted = cur.rowcount
            conn.commit()
        return inserted == 1

    def latest_manual_review(self, decision_id):
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT payload FROM {SCHEMA}.manual_quote_reviews
                    WHERE decision_id=%s ORDER BY attested_at DESC,review_id DESC LIMIT 1
                """, (decision_id,))
                row = cur.fetchone()
        return dict(row[0]) if row else None
