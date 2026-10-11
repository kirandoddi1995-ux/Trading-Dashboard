"""Inactive SQLite terminal-intent journal; caller owns every transaction.

Preserves exact original finalization intent across newer local run ownership.
No live imports, file discovery, network, secret access, sender or remote signing.
RemoteProof is an adapter assertion: authentication/atomic remote provenance must
be separately commissioned. This module never converts a missing proof to ACK.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import math
import sqlite3
from typing import Any, cast

from local_state_recovery import ProofState, RemoteProof
from operational_receipt_history import decode_object, decode_request, request_identity

TABLE = 'scan_finalization_intents'
MAX_INTENTS = 20_000
MAX_INTENT_BYTES = 4096
MAX_JOURNAL_BYTES = 32 * 1024 * 1024
MAX_SUMMARY_BYTES = 64 * 1024
SCHEMA = '''CREATE TABLE scan_finalization_intents(
    run_id TEXT NOT NULL,fencing_token INTEGER NOT NULL CHECK(fencing_token>0),
    request_json TEXT NOT NULL,queued_at REAL NOT NULL,
    acknowledged_at REAL,remote_request_sha256 TEXT,
    PRIMARY KEY(run_id,fencing_token),
    CHECK((acknowledged_at IS NULL)=(remote_request_sha256 IS NULL)),
    CHECK(remote_request_sha256 IS NULL OR
      (length(remote_request_sha256)=64 AND remote_request_sha256 NOT GLOB '*[^0-9a-f]*')))'''


class FinalizationError(ValueError):
    """Redacted failure; uncertain outer commits require reconciliation."""


def _transaction(connection: sqlite3.Connection) -> None:
    if type(connection) is not sqlite3.Connection or not connection.in_transaction:
        raise FinalizationError('FINALIZATION_CALLER_TRANSACTION_REQUIRED')


def _time(value: float) -> None:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise FinalizationError('FINALIZATION_TIME_INVALID')


def _json(request: Mapping[str, Any]) -> str:
    request_identity('run', request)
    encoded = json.dumps(request, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    if len(encoded.encode()) > MAX_INTENT_BYTES:
        raise FinalizationError('FINALIZATION_INTENT_SIZE_LIMIT')
    return encoded


def _summary_error(summary: object) -> object:
    """Reject oversized/duplicate source metadata without exposing its contents."""
    if type(summary) is not str or len(summary) > MAX_SUMMARY_BYTES:
        raise FinalizationError('FINALIZATION_SUMMARY_INVALID')
    if len(summary.encode()) > MAX_SUMMARY_BYTES:
        raise FinalizationError('FINALIZATION_SUMMARY_INVALID')
    try:
        parsed = decode_object(summary, max_bytes=MAX_SUMMARY_BYTES)
    except Exception:
        raise FinalizationError('FINALIZATION_SUMMARY_INVALID') from None
    return parsed.get('error')


def _job(connection: sqlite3.Connection, run_id: str, token: int) -> Any:
    return connection.execute('''SELECT status,finished_at,
        CASE WHEN length(CAST(summary_json AS BLOB))<=? THEN summary_json ELSE NULL END
        FROM durable_scan_jobs WHERE job_id=? AND fencing_token=?''',
        (MAX_SUMMARY_BYTES, run_id, token)).fetchone()


def initialize(connection: sqlite3.Connection) -> None:
    """Explicit NEW journal only; never repair/recreate an existing schema.

    Caller must stop live writers, back up and rehearse before future installation.
    Caller controls commit/rollback; no startup or public CLI invokes this.
    """
    try:
        _transaction(connection)
        required = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('durable_scan_jobs','checkpoint_outbox')")}
        if required != {'durable_scan_jobs', 'checkpoint_outbox'}:
            raise FinalizationError('FINALIZATION_SOURCE_SCHEMA_MISSING')
        connection.execute(SCHEMA)
    except FinalizationError:
        raise
    except Exception:
        raise FinalizationError('FINALIZATION_INITIALIZATION_BLOCKED') from None


def _schema(connection: sqlite3.Connection) -> None:
    objects = connection.execute(
        "SELECT type,name,sql FROM sqlite_master WHERE tbl_name=? ORDER BY type,name", (TABLE,)).fetchall()
    # SQLite adds its automatic primary-key index. No alternate schema/trigger is
    # accepted; this is exact contract validation, not an upgrade fallback.
    expected = [('index', 'sqlite_autoindex_scan_finalization_intents_1', None), ('table', TABLE, SCHEMA)]
    if objects != expected:
        raise FinalizationError('FINALIZATION_JOURNAL_SCHEMA_UNVERIFIED')


def queue_terminal(connection: sqlite3.Connection, *, run_id: str, fencing_token: int,
                   at: float) -> dict[str, Any]:
    """Record CURRENT terminal intent exactly, before any network delivery.

    The same local transaction must also own the terminal job change. All current
    fence checkpoints must be acknowledged first. Duplicate identity accepts only
    exact request bytes; a newer fence gets a separate retained immutable intent.
    Return is pending OUTER commit, not a successful durable queue assertion.
    """
    try:
        _transaction(connection)
        _schema(connection)
        _time(at)
        request_identity('run', dict(run_id=run_id, fencing_token=fencing_token,
                                    status='COMPLETE', finished_at=None, error_kind=None))
        row = _job(connection, run_id, fencing_token)
        if row is None:
            raise FinalizationError('FINALIZATION_ACTIVE_JOB_MISSING')
        request = dict(run_id=run_id, fencing_token=fencing_token, status=row[0],
                       finished_at=row[1], error_kind=_summary_error(row[2]))
        encoded = _json(request)
        if connection.execute('''SELECT 1 FROM checkpoint_outbox
                WHERE scan_id=? AND fencing_token=CAST(? AS TEXT) AND delivered_at IS NULL LIMIT 1''',
                (run_id, fencing_token)).fetchone() is not None:
            raise FinalizationError('FINALIZATION_CHECKPOINT_DELIVERY_PENDING')
        prior = connection.execute(f'''SELECT CASE WHEN length(CAST(request_json AS BLOB))<=?
            THEN request_json ELSE NULL END FROM {TABLE} WHERE run_id=? AND fencing_token=?''',
                                   (MAX_INTENT_BYTES, run_id, fencing_token)).fetchone()
        if prior is not None:
            if prior[0] != encoded:
                raise FinalizationError('FINALIZATION_IMMUTABLE_INTENT_CONFLICT')
        else:
            count, size = connection.execute(f'''SELECT count(*),coalesce(sum(length(CAST(request_json AS BLOB))),0)
                FROM {TABLE}''').fetchone()
            if count >= MAX_INTENTS or size + len(encoded.encode()) > MAX_JOURNAL_BYTES:
                raise FinalizationError('FINALIZATION_JOURNAL_CAPACITY_BLOCKED')
            connection.execute(f'INSERT INTO {TABLE} VALUES(?,?,?,?,NULL,NULL)',
                               (run_id, fencing_token, encoded, at))
        return cast(dict[str, Any], json.loads(encoded))
    except FinalizationError:
        raise
    except Exception:
        raise FinalizationError('FINALIZATION_QUEUE_BLOCKED') from None


def pending(connection: sqlite3.Connection, *, limit: int = 50) -> list[dict[str, Any]]:
    """Bounded detached original requests; does not mark delivery or send."""
    try:
        _schema(connection)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise FinalizationError('FINALIZATION_BATCH_LIMIT_INVALID')
        rows = connection.execute(f'''SELECT run_id,fencing_token,CASE WHEN length(CAST(request_json AS BLOB))<=?
            THEN request_json ELSE NULL END FROM {TABLE}
            WHERE acknowledged_at IS NULL ORDER BY queued_at,run_id,fencing_token LIMIT ?''',
            (MAX_INTENT_BYTES, limit)).fetchall()
        result = []
        for run_id, token, encoded in rows:
            request = decode_request('run', encoded)
            if request_identity('run', request) != (run_id, '', token):
                raise FinalizationError('FINALIZATION_JOURNAL_IDENTITY_MISMATCH')
            result.append(request)
        return result
    except FinalizationError:
        raise
    except Exception:
        raise FinalizationError('FINALIZATION_PENDING_READ_BLOCKED') from None


def acknowledge(connection: sqlite3.Connection, *, run_id: str, fencing_token: int,
                proof: RemoteProof, at: float) -> bool:
    """ACK only an authenticated adapter's exact original remote request.

    Returns whether this is still the current local terminal request. Old intent
    ACK is retained but NEVER writes a finalized token into a newer owned job.
    Missing/ABSENT/wrong-fence/wrong-payload proof blocks, and nothing sends here.
    Caller must roll back on exceptions; this module never commits or rolls back.
    """
    try:
        _transaction(connection)
        _schema(connection)
        _time(at)
        request_identity('run', dict(run_id=run_id, fencing_token=fencing_token,
                                    status='COMPLETE', finished_at=None, error_kind=None))
        row = connection.execute(f'''SELECT CASE WHEN length(CAST(request_json AS BLOB))<=?
            THEN request_json ELSE NULL END,acknowledged_at,queued_at,remote_request_sha256 FROM {TABLE}
            WHERE run_id=? AND fencing_token=?''', (MAX_INTENT_BYTES, run_id, fencing_token)).fetchone()
        if row is None:
            raise FinalizationError('FINALIZATION_ORIGINAL_INTENT_MISSING')
        original_request = decode_request('run', row[0])
        if request_identity('run', original_request) != (run_id, '', fencing_token):
            raise FinalizationError('FINALIZATION_JOURNAL_IDENTITY_MISMATCH')
        _time(row[2])
        if at < row[2]:
            raise FinalizationError('FINALIZATION_ACK_BEFORE_INTENT')
        if row[1] is not None:
            _time(row[1])
            if row[1] < row[2] or at < row[1]:
                raise FinalizationError('FINALIZATION_ACK_TIME_CONFLICT')
        if (type(proof) is not RemoteProof or proof.state is not ProofState.PRESENT
                or type(proof.active_fence) is not int or proof.active_fence != fencing_token
                or proof.request is None or _json(proof.request) != row[0]):
            raise FinalizationError('FINALIZATION_EXACT_REMOTE_PROOF_REQUIRED')
        digest = hashlib.sha256(row[0].encode()).hexdigest()
        if row[1] is not None and row[3] != digest:
            raise FinalizationError('FINALIZATION_ACK_RECEIPT_CORRUPT')
        current = _job(connection, run_id, fencing_token)
        if current is not None:
            request = dict(run_id=run_id, fencing_token=fencing_token, status=current[0],
                           finished_at=current[1], error_kind=_summary_error(current[2]))
            if _json(request) != row[0]:
                raise FinalizationError('FINALIZATION_CURRENT_JOB_CONFLICT')
        if row[1] is None:
            connection.execute(f'''UPDATE {TABLE} SET acknowledged_at=?,remote_request_sha256=?
                WHERE run_id=? AND fencing_token=? AND acknowledged_at IS NULL''',
                (at, digest, run_id, fencing_token))
        if current is None:
            return False
        connection.execute('''UPDATE durable_scan_jobs SET remote_finalized_token=?
            WHERE job_id=? AND fencing_token=?''', (fencing_token, run_id, fencing_token))
        return True
    except FinalizationError:
        raise
    except Exception:
        raise FinalizationError('FINALIZATION_ACK_BLOCKED') from None
