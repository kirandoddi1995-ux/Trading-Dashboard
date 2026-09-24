"""Restricted PostgreSQL repository for equity scan recovery and manual checks."""
from __future__ import annotations

import json
from contextlib import contextmanager, nullcontext
from enum import Enum
from collections.abc import Mapping


SCHEMA = "equity_operations"


class CheckpointOutcome(Enum):
    NEW = "NEW"
    IDEMPOTENT_SUCCESS = "IDEMPOTENT_SUCCESS"
    CONFLICT = "CONFLICT"

    def __bool__(self):
        return self is not CheckpointOutcome.CONFLICT


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

    def recovery_health(self):
        """Read-only inspection of durable tables and a real committed checkpoint."""
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT current_setting('synchronous_commit') <> 'off' AS synchronous_commit,
                           current_setting('fsync') = 'on' AS fsync,
                           (SELECT count(*) = 2 AND bool_and(c.relpersistence = 'p')
                            FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n
                              ON n.oid=c.relnamespace
                            WHERE n.nspname='equity_operations'
                              AND c.relname IN ('scan_runs','scan_candidates')) AS logged_tables,
                           (SELECT bool_and(has_table_privilege(current_user,'equity_operations.scan_runs',p))
                            FROM unnest(ARRAY['SELECT','INSERT','UPDATE']) p) AS run_permissions,
                           (SELECT bool_and(has_table_privilege(current_user,'equity_operations.scan_candidates',p))
                            FROM unnest(ARRAY['SELECT','INSERT','UPDATE']) p) AS candidate_permissions
                """)
                storage = cur.fetchone()
                cur.execute("""
                    SELECT c.run_id,c.instrument,c.result,c.rejection
                    FROM equity_operations.scan_candidates c
                    JOIN equity_operations.scan_runs r ON r.run_id=c.run_id
                    WHERE c.status='COMPLETE' AND c.attempt_no > 0
                      AND (c.result IS NOT NULL OR c.rejection IS NOT NULL)
                    ORDER BY c.updated_at DESC LIMIT 1
                """)
                checkpoint = cur.fetchone()
        valid = bool(storage and len(storage) == 5 and all(value is True for value in storage)
                     and checkpoint and (isinstance(checkpoint[2], Mapping)
                                         or isinstance(checkpoint[3], Mapping)))
        return {"status": "PASS" if valid else "UNAVAILABLE",
                "durable_tables_verified": bool(storage and all(value is True for value in storage)),
                "committed_checkpoint_read": bool(checkpoint),
                "scope": "existing_checkpoint_readback_not_disaster_recovery"}

    def create_run(self, run: Mapping, items):
        with self._connection() as conn:
            with conn.cursor() as cur:
                # Fail initialization explicitly if the manually reviewed migration
                # has not run. Never silently collect an undeliverable queue.
                cur.execute(f"SELECT checkpoint_fencing_token FROM {SCHEMA}.scan_candidates LIMIT 0")
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
                      finished_at=CASE WHEN %s::double precision IS NULL THEN finished_at ELSE to_timestamp(%s) END,
                      error_kind=%s
                    WHERE run_id=%s AND fencing_token=%s
                      AND (%s <> 'COMPLETE' OR NOT EXISTS (
                        SELECT 1 FROM equity_operations.scan_candidates c
                        WHERE c.run_id=scan_runs.run_id AND
                          (c.status<>'COMPLETE' OR c.checkpoint_fencing_token IS NULL
                           OR c.checkpoint_fencing_token > scan_runs.fencing_token)))
                """, (status, finished_at, finished_at, error_kind, run_id, int(fencing_token), status))
                updated = cur.rowcount
            conn.commit()
        return updated == 1

    @contextmanager
    def checkpoint_delivery_session(self):
        """One connection per batch; checkpoint_candidate commits each receipt."""
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = '30s'")
            conn.commit()
            yield lambda **kwargs: self.checkpoint_candidate(_connection=conn, **kwargs)

    def checkpoint_candidate(self, *, run_id, instrument, fencing_token, result=None, rejection=None,
                             quote_observed_at=None, governance_decision_at=None,
                             item=None, _connection=None):
        token = int(fencing_token)
        payload = (_json(result) if result is not None else None,
                   _json(rejection) if rejection is not None else None,
                   quote_observed_at, governance_decision_at)
        if token <= 0 or (result is None) == (rejection is None):
            return CheckpointOutcome.CONFLICT
        with (nullcontext(_connection) if _connection is not None else self._connection()) as conn:
            try:
                with conn.cursor() as cur:
                    # Serialize delivery and recovery on the same run row. Never accept
                    # an old fence, even when its old payload happens to match.
                    cur.execute(f"SELECT fencing_token FROM {SCHEMA}.scan_runs WHERE run_id=%s FOR UPDATE", (run_id,))
                    active = cur.fetchone()
                    if not active or int(active[0]) != token:
                        conn.rollback()
                        return CheckpointOutcome.CONFLICT
                    cur.execute(f"""SELECT checkpoint_fencing_token,status,
                        (result IS NOT DISTINCT FROM %s::jsonb AND rejection IS NOT DISTINCT FROM %s::jsonb
                         AND quote_observed_at IS NOT DISTINCT FROM %s::timestamptz
                         AND governance_decision_at IS NOT DISTINCT FROM %s::timestamptz)
                        FROM {SCHEMA}.scan_candidates WHERE run_id=%s AND instrument=%s FOR UPDATE""",
                        (*payload, run_id, str(instrument)))
                    prior = cur.fetchone()
                    if prior and prior[0] == token:
                        outcome = (CheckpointOutcome.IDEMPOTENT_SUCCESS
                                   if prior[1] == 'COMPLETE' and prior[2] is True
                                   else CheckpointOutcome.CONFLICT)
                        conn.rollback()
                        return outcome
                    if prior and prior[0] is not None and int(prior[0]) > token:
                        conn.rollback()
                        return CheckpointOutcome.CONFLICT
                    if prior:
                        # A genuinely new evaluation under the active fence may
                        # supersede an older receipt or an unverifiable legacy row.
                        cur.execute(f"""UPDATE {SCHEMA}.scan_candidates SET
                            result=%s::jsonb,rejection=%s::jsonb,quote_observed_at=%s,
                            governance_decision_at=%s,status='COMPLETE',attempt_no=attempt_no+1,
                            checkpoint_fencing_token=%s,updated_at=clock_timestamp()
                            WHERE run_id=%s AND instrument=%s""", (*payload, token, run_id, str(instrument)))
                    else:
                        if item is None:
                            conn.rollback()
                            return CheckpointOutcome.CONFLICT
                        cur.execute(f"""INSERT INTO {SCHEMA}.scan_candidates
                            (result,rejection,quote_observed_at,governance_decision_at,
                             checkpoint_fencing_token,run_id,instrument,item,status,attempt_no,updated_at)
                            VALUES (%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,%s::jsonb,'COMPLETE',1,clock_timestamp())""",
                            (*payload, token, run_id, str(instrument), _json(item)))
                conn.commit()
                return CheckpointOutcome.NEW
            except Exception:
                conn.rollback()
                raise

    def latest_recoverable(self, owner_id, signature):
        # Non-NULL completed receipts from prior fences remain archived completed
        # work, not fresh/actionable results. Legacy NULL receipts require re-evaluation.
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT run_id,status,fencing_token,metadata,
                           ARRAY(SELECT c.instrument FROM {SCHEMA}.scan_candidates c
                                 WHERE c.run_id=r.run_id AND (c.status<>'COMPLETE' OR c.checkpoint_fencing_token IS NULL)
                                 ORDER BY c.instrument),
                           (SELECT count(*) FROM {SCHEMA}.scan_candidates c
                            WHERE c.run_id=r.run_id AND c.status='COMPLETE' AND c.checkpoint_fencing_token IS NOT NULL)
                    FROM {SCHEMA}.scan_runs r
                    WHERE owner_id=%s AND signature=%s
                      AND status IN ('RUNNING','INTERRUPTED','CANCELLED','RECOVERING','COMPLETE')
                      AND EXISTS (SELECT 1 FROM {SCHEMA}.scan_candidates c
                                  WHERE c.run_id=r.run_id AND (c.status<>'COMPLETE' OR c.checkpoint_fencing_token IS NULL))
                    ORDER BY started_at DESC LIMIT 1
                """, (owner_id, signature))
                row = cur.fetchone()
        if not row:
            return None
        return {"id": str(row[0]), "status": str(row[1]), "fencing_token": int(row[2]),
                "metadata": dict(row[3] or {}), "unfinished": list(row[4] or []),
                "archived_completed": int(row[5] or 0)}

    def claim_recovery(self, run_id, owner_id):
        # Compare-and-set in one UPDATE: competing callers must not replace an
        # active recovery's fence. No timeout takeover without a proven lease.
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    UPDATE {SCHEMA}.scan_runs
                    SET fencing_token=fencing_token+1,status='RECOVERING',
                        heartbeat_at=clock_timestamp(),error_kind=NULL
                    WHERE run_id=%s AND owner_id=%s
                      AND status IN ('RUNNING','INTERRUPTED','CANCELLED','COMPLETE')
                      AND EXISTS (SELECT 1 FROM equity_operations.scan_candidates c
                        WHERE c.run_id=scan_runs.run_id
                          AND (c.status<>'COMPLETE' OR c.checkpoint_fencing_token IS NULL))
                    RETURNING fencing_token,metadata
                """, (run_id, owner_id))
                row = cur.fetchone()
                if not row:
                    conn.rollback()
                    return None
                cur.execute(f"""
                    SELECT item FROM {SCHEMA}.scan_candidates
                    WHERE run_id=%s AND (status<>'COMPLETE' OR checkpoint_fencing_token IS NULL) ORDER BY instrument
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

    def unresolved_orders(self, owner_id):
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT i.payload FROM {SCHEMA}.order_intents i
                    WHERE i.owner_id=%s AND NOT EXISTS
                      (SELECT 1 FROM {SCHEMA}.order_results r WHERE r.intent_id=i.intent_id)
                    ORDER BY i.created_at,i.intent_id
                """, (owner_id,))
                return [dict(row[0]) for row in cur.fetchall()]

    def save_order_intent(self, signal, review, *, owner_id, now):
        from equity_order_records import build_order_intent
        intent = build_order_intent(signal, review, owner_id=owner_id, now=now)
        with self._connection() as conn:
            with conn.cursor() as cur:
                # Serialize all confirmations for this owner, not just one tab.
                cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (owner_id,))
                cur.execute(f"""SELECT 1 FROM {SCHEMA}.order_intents i WHERE owner_id=%s
                    AND NOT EXISTS (SELECT 1 FROM {SCHEMA}.order_results r WHERE r.intent_id=i.intent_id)
                    LIMIT 1""", (owner_id,))
                if cur.fetchone():
                    raise ValueError("Reconcile the previous order before confirming another")
                cur.execute(f"SELECT payload FROM {SCHEMA}.manual_quote_reviews WHERE review_id=%s",
                            (review["review_id"],))
                stored = cur.fetchone()
                if not stored or dict(stored[0]) != dict(review):
                    raise ValueError("The exact manual review must be durably stored first")
                cur.execute(f"""INSERT INTO {SCHEMA}.order_intents
                    (intent_id,owner_id,review_id,created_at,payload) VALUES (%s,%s,%s,%s,%s::jsonb)""",
                            (intent["intent_id"], owner_id, intent["review_id"], intent["created_at"], _json(intent)))
            conn.commit()
        return intent

    def reconcile_order(self, intent_id, *, owner_id, **actuals):
        from equity_order_records import build_order_result
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (owner_id,))
                cur.execute(f"SELECT payload FROM {SCHEMA}.order_intents WHERE intent_id=%s AND owner_id=%s",
                            (intent_id, owner_id))
                stored = cur.fetchone()
                if not stored:
                    raise ValueError("Unknown order intent for this owner")
                result = build_order_result(dict(stored[0]), **actuals)
                cur.execute(f"SELECT payload FROM {SCHEMA}.order_results WHERE intent_id=%s", (intent_id,))
                prior = cur.fetchone()
                if prior:
                    ignored = {"result_id", "recorded_at"}
                    if {k:v for k,v in prior[0].items() if k not in ignored} != {
                        k:v for k,v in result.items() if k not in ignored
                    }:
                        raise ValueError("Order already reconciled differently; existing record is immutable")
                    return dict(prior[0])
                cur.execute(f"""INSERT INTO {SCHEMA}.order_results
                    (result_id,intent_id,owner_id,payload) VALUES (%s,%s,%s,%s::jsonb)""",
                            (result["result_id"], intent_id, owner_id, _json(result)))
            conn.commit()
        return result
