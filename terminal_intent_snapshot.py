"""Inactive six-table detached recovery cut, not a live restore or sender.

The original five-table verifier is reused unchanged. Terminal intents are
copied eagerly from its SAME read transaction, not captured in a second cut.
Independent source witnesses and authenticated original remote proofs remain
caller responsibilities. No CLI, file discovery, credential or network access.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, cast

import finalization_intents as intents
import local_state_recovery as state
from operational_receipt_history import decode_request, request_identity

VERSION = 'terminal-intent-snapshot-v1'
MAX_FRAME_BYTES = 6 * intents.MAX_INTENT_BYTES + 6 * 900 + 1024


class IntentSnapshotError(ValueError):
    """Fixed redacted failures; missing history never becomes valid absence."""


@dataclass(frozen=True)
class IntentWitness:
    """Retain independently from the source before a future restore rehearsal."""
    version: str
    count: int
    sha256: str

    def __post_init__(self) -> None:
        if (self.version != VERSION or type(self.count) is not int
                or not 0 <= self.count <= intents.MAX_INTENTS
                or not isinstance(self.sha256, str)
                or re.fullmatch('[0-9a-f]{64}', self.sha256) is None):
            raise IntentSnapshotError('INTENT_WITNESS_INVALID')


@dataclass(frozen=True, repr=False)
class SixSnapshot:
    """Context-owned spools. This does not authenticate its own source witness."""
    primary: state.StateSnapshot = field(repr=False)
    intents: IntentWitness


def _finite(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    number = cast(int | float, value)
    return math.isfinite(number) and number >= 0


def _validate_row(row: tuple[Any, ...]) -> dict[str, Any]:
    run, token, encoded, queued, ack, digest = row
    request = decode_request('run', encoded)
    if request_identity('run', request) != (run, '', token) or type(token) is not int:
        raise IntentSnapshotError('INTENT_IDENTITY_MISMATCH')
    if not _finite(queued) or (ack is None) != (digest is None):
        raise IntentSnapshotError('INTENT_ACK_INVALID')
    canonical = json.dumps(request, sort_keys=True, separators=(',', ':'),
                           ensure_ascii=False, allow_nan=False)
    if encoded != canonical or len(encoded.encode()) > intents.MAX_INTENT_BYTES:
        raise IntentSnapshotError('INTENT_REQUEST_NONCANONICAL')
    if ack is not None and (not _finite(ack) or ack < queued
            or digest != hashlib.sha256(canonical.encode()).hexdigest()):
        raise IntentSnapshotError('INTENT_ACK_INVALID')
    return request


def capture_into(source: sqlite3.Connection, spool: sqlite3.Connection, deadline: float) -> None:
    """Internal eager extension: exact sixth schema, bounds before fetching JSON.

    Only local_state_recovery.capture invokes this in production library code.
    It cannot commit/rollback/close the source; query_only must already be set.
    Spool writes are ephemeral, not writes to the inspected source.
    """
    try:
        if not source.in_transaction or source.execute('PRAGMA query_only').fetchone() != (1,):
            raise IntentSnapshotError('INTENT_SAME_READ_TRANSACTION_REQUIRED')
        if time.monotonic() > deadline:
            raise IntentSnapshotError('INTENT_SOURCE_TIME_BOUND')
        metadata_bytes = source.execute('''SELECT coalesce(sum(length(CAST(coalesce(sql,'') AS BLOB))
            +length(CAST(name AS BLOB))),0) FROM sqlite_master WHERE tbl_name=?''',
            (intents.TABLE,)).fetchone()[0]
        if metadata_bytes > state.MAX_SCHEMA_BYTES:
            raise IntentSnapshotError('INTENT_SCHEMA_BOUND_EXCEEDED')
        intents._schema(source)
        count, size = source.execute(f'''SELECT count(*),coalesce(sum(length(CAST(request_json AS BLOB))),0)
            FROM {intents.TABLE}''').fetchone()
        if count > intents.MAX_INTENTS or size > intents.MAX_JOURNAL_BYTES:
            raise IntentSnapshotError('INTENT_SNAPSHOT_BOUND_EXCEEDED')
        spool.execute('CREATE TABLE terminal_intents(position INTEGER PRIMARY KEY,body TEXT NOT NULL)')
        size = 0
        query = f'''SELECT CASE WHEN length(CAST(run_id AS BLOB))<=900 THEN run_id ELSE NULL END,
            fencing_token,CASE WHEN length(CAST(request_json AS BLOB))<=?
            THEN request_json ELSE NULL END,queued_at,acknowledged_at,
            CASE WHEN length(CAST(remote_request_sha256 AS BLOB))<=64 OR remote_request_sha256 IS NULL
            THEN remote_request_sha256 ELSE 'INVALID_OVERSIZED_DIGEST' END
            FROM {intents.TABLE} ORDER BY run_id,fencing_token'''
        for position, row in enumerate(source.execute(query, (intents.MAX_INTENT_BYTES,)), 1):
            if time.monotonic() > deadline:
                raise IntentSnapshotError('INTENT_SOURCE_TIME_BOUND')
            _validate_row(row)
            body = json.dumps(row, ensure_ascii=True, separators=(',', ':'), allow_nan=False)
            size += len(body.encode())
            # Bound the actual spool representation, not just JSON payloads.
            if position > intents.MAX_INTENTS or size > intents.MAX_JOURNAL_BYTES:
                raise IntentSnapshotError('INTENT_SNAPSHOT_BOUND_EXCEEDED')
            spool.execute('INSERT INTO terminal_intents VALUES(?,?)', (position, body))
        if time.monotonic() > deadline:
            raise IntentSnapshotError('INTENT_SOURCE_TIME_BOUND')
    except Exception:
        raise state.StateRecoveryError('STATE_TERMINAL_INTENTS_UNVERIFIED') from None


def _witness(snapshot: state.StateSnapshot) -> IntentWitness:
    digest = hashlib.sha256((VERSION + ':' + intents.SCHEMA + '\n').encode())
    count, size = 0, 0
    for position, body in snapshot._spool.execute('''SELECT position,
            CASE WHEN length(CAST(body AS BLOB))<=? THEN body ELSE NULL END
            FROM terminal_intents ORDER BY position''', (MAX_FRAME_BYTES,)):
        if type(body) is not str:
            raise IntentSnapshotError('INTENT_SNAPSHOT_BOUND_EXCEEDED')
        count += 1
        size += len(body.encode())
        if position != count or count > intents.MAX_INTENTS or size > intents.MAX_JOURNAL_BYTES:
            raise IntentSnapshotError('INTENT_SNAPSHOT_BOUND_EXCEEDED')
        _validate_row(tuple(json.loads(body)))
        digest.update(body.encode() + b'\n')
    return IntentWitness(VERSION, count, digest.hexdigest())


def _detached_rows(snapshot: state.StateSnapshot) -> Iterator[tuple[Any, ...]]:
    """Bound every read, including after external proof callbacks returned."""
    count, size = 0, 0
    for body, in snapshot._spool.execute('''SELECT CASE WHEN length(CAST(body AS BLOB))<=?
            THEN body ELSE NULL END FROM terminal_intents ORDER BY position''', (MAX_FRAME_BYTES,)):
        if type(body) is not str:
            raise IntentSnapshotError('INTENT_SNAPSHOT_BOUND_EXCEEDED')
        count += 1
        size += len(body.encode())
        if count > intents.MAX_INTENTS or size > intents.MAX_JOURNAL_BYTES:
            raise IntentSnapshotError('INTENT_SNAPSHOT_BOUND_EXCEEDED')
        yield tuple(json.loads(body))


@contextmanager
def capture_six(connect: Callable[[], sqlite3.Connection], keys: Mapping[str, bytes], *,
                spool_parent: Path) -> Iterator[SixSnapshot]:
    """One source cut; source already closed before exposing either witness."""
    with state.capture(connect, keys, spool_parent=spool_parent,
                       include_terminal_intents=True) as primary:
        yield SixSnapshot(primary, _witness(primary))


def verify_six(snapshot: SixSnapshot, expected_primary: state.StateWitness,
               expected_intents: IntentWitness, *, evidence_lookup: Callable[[str], state.RemoteProof],
               checkpoint_lookup: Callable[[str, str, int], state.RemoteProof],
               run_lookup: Callable[[str, int], state.RemoteProof]) -> dict[str, object]:
    """Compare BOTH independently retained witnesses and exact remote requests.

    An acknowledged historical intent needs its original immutable remote proof,
    never the run's mutable current row. Old proofs never finalize a newer job.
    No sending, ACK mutations, restore, pruning or custody approval occurs here.
    """
    try:
        if _witness(snapshot.primary) != expected_intents:
            raise IntentSnapshotError('INTENT_SOURCE_WITNESS_MISMATCH')
        result = state.verify(snapshot.primary, expected_primary,
            evidence_lookup=evidence_lookup, checkpoint_lookup=checkpoint_lookup, run_lookup=run_lookup)
        if result['status'] != 'PASS':
            return result
        pending, committed = 0, 0
        for row in _detached_rows(snapshot.primary):
            request = _validate_row(row)
            run, token, _, _, ack, _ = row
            job = state._get(snapshot.primary._spool, 'durable_scan_jobs', [run])
            if token > job['fencing_token']:
                raise IntentSnapshotError('INTENT_FUTURE_FENCE_INVALID')
            if token == job['fencing_token']:
                current = dict(run_id=run, fencing_token=token, status=job['status'],
                    finished_at=job['finished_at'], error_kind=state._json(job['summary_json']).get('error'))
                if request != current:
                    raise IntentSnapshotError('INTENT_CURRENT_REQUEST_MISMATCH')
                if ack is not None and job['remote_finalized_token'] != token:
                    raise IntentSnapshotError('INTENT_CURRENT_FINALIZATION_MISMATCH')
            is_pending = ack is None
            # Reuses exact original request/fence authentication contract.
            found = state._remote(lambda: run_lookup(run, token), request, is_pending, token)
            pending += int(is_pending)
            committed += int(found)
        if (_witness(snapshot.primary) != expected_intents
                or state._rehash(snapshot.primary) != expected_primary):
            raise IntentSnapshotError('INTENT_DETACHED_CUT_CHANGED')
        return {'status': 'PASS', 'scope': 'SIX_TABLE_LOCAL_RECOVERY_CUT',
                'intent_rows': expected_intents.count, 'pending_intents': pending,
                'remote_committed_pending_intent_ack': committed,
                'application_recovery_verified': False, 'backup_custody_verified': False,
                'approval_authority': False}
    except Exception:
        return {'status': 'FAILED', 'reason': 'SIX_TABLE_RECOVERY_UNVERIFIED',
                'application_recovery_verified': False, 'approval_authority': False}
