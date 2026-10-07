"""Offline, disk-spooled proof of five-table local recovery, never a repair.

The caller owns the independent source witness and authenticated remote adapters.
This library is deliberately not imported by live factories and has no CLI.
It writes only an ephemeral spool under an explicitly supplied private directory.
It never initializes, changes, sends from, or prunes the inspected source.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
import datetime as dt
from enum import Enum
import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import sqlite3
import tempfile
import time
from typing import Any, cast

from evidence_ledger import GENESIS_HASH, ImmutableEvidenceLedger, canonical_json

VERSION = 'local-state-recovery-v1'
MAX_ROWS = 1_000_000
MAX_ROW_BYTES = 2 * 1024 * 1024
MAX_BYTES = 512 * 1024 * 1024
MAX_SCHEMA_BYTES = 64 * 1024
MAX_SOURCE_SECONDS = 30.0
LEGACY_KEY_ID = 'legacy-schema-v1'
EVENT_FIELDS = ('event_id', 'aggregate_id', 'sequence_no', 'event_type', 'recorded_at',
                'effective_at', 'source', 'actor_id', 'idempotency_key', 'payload_json',
                'previous_hash', 'event_hash', 'hash_algorithm', 'schema_version', 'key_id')
REQUEST = ('aggregate_id', 'event_type', 'payload', 'effective_at', 'source',
           'actor_id', 'idempotency_key')
CHECKPOINT = ('run_id', 'instrument', 'fencing_token', 'result', 'rejection',
              'quote_observed_at', 'governance_decision_at', 'item')
TABLES: dict[str, tuple[str, ...]] = {
    'evidence_ledger_events': EVENT_FIELDS,
    'evidence_delivery_outbox': ('idempotency_key', 'event_json', 'attempts', 'last_error',
        'next_attempt_at', 'created_at', 'delivered_at', 'delivery_lane'),
    'durable_scan_jobs': ('job_id', 'owner', 'signature', 'started_at', 'finished_at',
        'status', 'processed', 'total', 'eta_seconds', 'summary_json', 'updated_at',
        'fencing_token', 'metadata_json', 'recovered', 'remote_finalized_token'),
    'durable_scan_candidates': ('job_id', 'instrument', 'item_json', 'status',
        'fencing_token', 'result_json', 'rejection_json', 'quote_observed_at',
        'governance_decision_at', 'updated_at'),
    'checkpoint_outbox': ('scan_id', 'candidate', 'fencing_token', 'checkpoint_json',
        'created_at', 'delivered_at', 'attempts', 'next_attempt_at', 'last_error'),
}
ORDER = {
    'evidence_ledger_events': 'aggregate_id,sequence_no',
    'evidence_delivery_outbox': 'idempotency_key',
    'durable_scan_jobs': 'job_id',
    'durable_scan_candidates': 'job_id,instrument',
    'checkpoint_outbox': 'scan_id,candidate,fencing_token',
}
IDENTITY = {
    'evidence_ledger_events': ('event_id',),
    'evidence_delivery_outbox': ('idempotency_key',),
    'durable_scan_jobs': ('job_id',),
    'durable_scan_candidates': ('job_id', 'instrument'),
    'checkpoint_outbox': ('scan_id', 'candidate', 'fencing_token'),
}


class StateRecoveryError(ValueError):
    """Stable failure codes without keys, payloads, paths or driver messages."""


class ProofState(Enum):
    """States returned ONLY by the eventual independent authenticated adapters."""
    PRESENT = 'AUTHENTICATED_PRESENT'
    ABSENT = 'AUTHENTICATED_ABSENT'
    UNAVAILABLE = 'UNAVAILABLE'


@dataclass(frozen=True)
class RemoteProof:
    """An adapter assertion, not authentication performed by this offline module."""
    state: ProofState
    request: Mapping[str, Any] | None = field(default=None, repr=False)
    active_fence: int | None = None


@dataclass(frozen=True)
class StateWitness:
    """Keep this from the source independently, before attempting a restore."""
    version: str
    counts: tuple[int, ...]
    schema_sha256: str
    state_sha256: str

    def __post_init__(self) -> None:
        if (self.version != VERSION or not isinstance(self.counts, tuple)
                or len(self.counts) != len(TABLES)
                or any(type(n) is not int or n < 0 for n in self.counts)
                or not 1 <= sum(self.counts) <= MAX_ROWS or self.counts[0] == 0
                or any(not isinstance(v, str) or re.fullmatch('[0-9a-f]{64}', v) is None
                       for v in (self.schema_sha256, self.state_sha256))):
            raise StateRecoveryError('STATE_WITNESS_INVALID')


@dataclass(frozen=True, repr=False)
class StateSnapshot:
    """Context-scoped detached spool; invalid once capture's context exits."""
    witness: StateWitness
    _spool: sqlite3.Connection

    def __repr__(self) -> str:
        return 'StateSnapshot(<private detached spool>)'


def _encode(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False)


def _json(encoded: object) -> Any:
    if not isinstance(encoded, str):
        raise StateRecoveryError('STATE_JSON_INVALID')
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise StateRecoveryError('STATE_JSON_INVALID')
            result[key] = value
        return result
    def reject(value: str) -> None:
        raise StateRecoveryError('STATE_JSON_INVALID')
    try:
        return json.loads(encoded, object_pairs_hook=unique, parse_constant=reject)
    except StateRecoveryError:
        raise
    except Exception:
        raise StateRecoveryError('STATE_JSON_INVALID') from None


def _integer(value: object, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise StateRecoveryError('STATE_INTEGER_INVALID')
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise StateRecoveryError('STATE_IDENTITY_INVALID')
    return value


def _timestamp(value: object, *, numeric: bool = False, optional: bool = False) -> None:
    if optional and value is None:
        return
    try:
        if numeric:
            if type(value) not in (int, float):
                raise ValueError
            number = cast(int | float, value)
            if not math.isfinite(number) or number < 0:
                raise ValueError
        else:
            instant = dt.datetime.fromisoformat(_text(value).replace('Z', '+00:00'))
            if instant.tzinfo is None or instant.utcoffset() is None:
                raise ValueError
    except Exception:
        raise StateRecoveryError('STATE_TIMESTAMP_INVALID') from None


def _identity(row: Mapping[str, Any], names: tuple[str, ...]) -> str:
    return _encode([_text(row[name]) for name in names])


def _schema(conn: sqlite3.Connection) -> str:
    schema = []
    for table, fields in TABLES.items():
        metadata_size = conn.execute('SELECT COALESCE(sum(COALESCE(length(CAST(sql AS BLOB)),0)'
            '+length(CAST(name AS BLOB))+length(CAST(type AS BLOB))),0) '
            'FROM sqlite_master WHERE tbl_name=?', (table,)).fetchone()[0]
        if metadata_size > MAX_SCHEMA_BYTES:
            raise StateRecoveryError('STATE_SCHEMA_LIMIT')
        info = conn.execute(f'PRAGMA table_info({table})').fetchall()
        if {r[1] for r in info} != set(fields) or len(info) != len(fields):
            raise StateRecoveryError('STATE_SCHEMA_UNSUPPORTED')
        objects = conn.execute('SELECT type,name,sql FROM sqlite_master WHERE tbl_name=? '
                               'ORDER BY type,name', (table,)).fetchall()
        if not any(r[0] == 'table' and r[1] == table for r in objects):
            raise StateRecoveryError('STATE_SCHEMA_UNSUPPORTED')
        schema.append((table, info, objects))
    encoded = _encode(schema)
    if len(encoded.encode()) > MAX_SCHEMA_BYTES:
        raise StateRecoveryError('STATE_SCHEMA_LIMIT')
    return hashlib.sha256(encoded.encode()).hexdigest()


def _event(row: Mapping[str, Any], keys: Mapping[str, bytes],
           previous: tuple[str | None, int, str]) -> tuple[tuple[str, int, str], str]:
    aggregate = _text(row['aggregate_id'])
    for name in ('event_id', 'event_type', 'source', 'actor_id', 'idempotency_key'):
        _text(row[name])
    _timestamp(row['recorded_at'])
    _timestamp(row['effective_at'])
    sequence = _integer(row['sequence_no'], 1)
    version = _integer(row['schema_version'], 1)
    key_id = (LEGACY_KEY_ID if version == 1 and row['key_id'] is None else row['key_id'])
    key = keys.get(key_id) if isinstance(key_id, str) else None
    if version not in (1, 2) or row['hash_algorithm'] != 'HMAC-SHA256' or not isinstance(key, bytes) or not key:
        raise StateRecoveryError('STATE_SIGNING_KEY_UNVERIFIED')
    old_sequence, old_hash = ((previous[1], previous[2]) if previous[0] == aggregate
                              else (0, GENESIS_HASH))
    material = ImmutableEvidenceLedger._material(**{k: row[k] for k in EVENT_FIELDS if k != 'event_hash'})
    digest = hmac.new(key, material.encode(), hashlib.sha256).hexdigest()
    if (sequence != old_sequence + 1 or row['previous_hash'] != old_hash
            or not isinstance(row['event_hash'], str) or not hmac.compare_digest(row['event_hash'], digest)):
        raise StateRecoveryError('STATE_ORIGINAL_INVALID')
    payload = _json(row['payload_json'])
    if not isinstance(payload, dict) or canonical_json(payload) != row['payload_json']:
        raise StateRecoveryError('STATE_ORIGINAL_INVALID')
    request = {name: payload if name == 'payload' else row[name] for name in REQUEST}
    return (aggregate, sequence, digest), _encode(request)


def _rows(spool: sqlite3.Connection, table: str) -> Iterator[dict[str, Any]]:
    for body, in spool.execute('SELECT body FROM records WHERE kind=? ORDER BY position', (table,)):
        yield json.loads(body)


def _get(spool: sqlite3.Connection, table: str, identity: list[str]) -> dict[str, Any]:
    found = spool.execute('SELECT body FROM records WHERE kind=? AND identity=?',
                          (table, _encode(identity))).fetchone()
    if found is None:
        raise StateRecoveryError('STATE_ORPHAN')
    return cast(dict[str, Any], json.loads(found[0]))


def _request(spool: sqlite3.Connection, retry: str) -> str:
    found = spool.execute('SELECT body FROM requests WHERE retry=?', (retry,)).fetchone()
    if found is None:
        raise StateRecoveryError('STATE_ORPHAN')
    return str(found[0])


def _validate(spool: sqlite3.Connection) -> None:
    """Fail closed when delivery intent cannot be proven, rather than invent it."""
    for row in _rows(spool, 'evidence_delivery_outbox'):
        request = _json(row['event_json'])
        if (row['delivery_lane'] != 'equity' or not isinstance(request, dict)
                or set(request) != set(REQUEST)
                or _encode(request) != _request(spool, row['idempotency_key'])):
            raise StateRecoveryError('STATE_OUTBOX_REQUEST_INVALID')
        _integer(row['attempts'])
        for name in ('created_at', 'next_attempt_at', 'delivered_at'):
            _timestamp(row[name], optional=name == 'delivered_at')
    if spool.execute("SELECT 1 FROM requests q WHERE NOT EXISTS (SELECT 1 FROM records r "
                     "WHERE r.kind='evidence_delivery_outbox' AND r.identity=q.identity) LIMIT 1").fetchone():
        raise StateRecoveryError('STATE_DELIVERY_INTENT_UNPROVEN')
    for row in _rows(spool, 'durable_scan_jobs'):
        fence = _integer(row['fencing_token'], 1)
        for name in ('job_id', 'owner', 'signature'):
            _text(row[name])
        if row['status'] not in ('RUNNING', 'RECOVERING', 'COMPLETE', 'INTERRUPTED', 'CANCELLED'):
            raise StateRecoveryError('STATE_JOB_INVALID')
        if _integer(row['processed']) > _integer(row['total']) or row['recovered'] not in (0, 1):
            raise StateRecoveryError('STATE_JOB_INVALID')
        for name in ('summary_json', 'metadata_json'):
            if not isinstance(_json(row[name]), dict):
                raise StateRecoveryError('STATE_JOB_INVALID')
        for name in ('started_at', 'updated_at', 'finished_at', 'eta_seconds'):
            _timestamp(row[name], numeric=True, optional=name in ('finished_at', 'eta_seconds'))
        finalized = row['remote_finalized_token']
        if finalized is not None and (_integer(finalized, 1) > fence or row['status'] not in
                ('COMPLETE', 'INTERRUPTED', 'CANCELLED')):
            raise StateRecoveryError('STATE_FINALIZATION_INVALID')
        if finalized is not None and finalized != fence:
            raise StateRecoveryError('STATE_HISTORICAL_FINALIZATION_REQUIRES_ADAPTER')
        counts = spool.execute("SELECT count(*),sum(CASE WHEN json_extract(body,'$.fencing_token')=? "
            "THEN 1 ELSE 0 END),sum(CASE WHEN json_extract(body,'$.status')<>'COMPLETE' THEN 1 ELSE 0 END) "
            "FROM records WHERE kind='durable_scan_candidates' AND json_extract(body,'$.job_id')=?",
            (fence, row['job_id'])).fetchone()
        generation_count = (counts[1] or 0) if row['recovered'] == 1 else counts[0]
        if (generation_count != row['total'] or (row['status'] == 'COMPLETE' and
                (row['processed'] != row['total'] or (counts[2] or 0) != 0))):
            raise StateRecoveryError('STATE_JOB_COMPLETENESS_UNPROVEN')
    for row in _rows(spool, 'durable_scan_candidates'):
        job = _get(spool, 'durable_scan_jobs', [row['job_id']])
        fence = _integer(row['fencing_token'], 1)
        if fence > job['fencing_token'] or row['status'] not in ('PENDING', 'RUNNING', 'COMPLETE'):
            raise StateRecoveryError('STATE_CANDIDATE_INVALID')
        _json(row['item_json'])
        _timestamp(row['updated_at'], numeric=True)
        for name in ('quote_observed_at', 'governance_decision_at'):
            _timestamp(row[name], optional=True)
        for name in ('result_json', 'rejection_json'):
            if row[name] is not None and not isinstance(_json(row[name]), dict):
                raise StateRecoveryError('STATE_CANDIDATE_INVALID')
        if row['status'] == 'COMPLETE':
            if (row['result_json'] is None) == (row['rejection_json'] is None):
                raise StateRecoveryError('STATE_CANDIDATE_INVALID')
            _get(spool, 'checkpoint_outbox', [row['job_id'], row['instrument'], str(fence)])
    for row in _rows(spool, 'checkpoint_outbox'):
        job = _get(spool, 'durable_scan_jobs', [row['scan_id']])
        candidate = _get(spool, 'durable_scan_candidates', [row['scan_id'], row['candidate']])
        request = _json(row['checkpoint_json'])
        _integer(row['attempts'])
        for name in ('created_at', 'next_attempt_at', 'delivered_at'):
            _timestamp(row[name], numeric=True, optional=name == 'delivered_at')
        if not isinstance(request, dict) or set(request) != set(CHECKPOINT):
            raise StateRecoveryError('STATE_CHECKPOINT_REQUEST_INVALID')
        token = _integer(request['fencing_token'], 1)
        if (str(token) != row['fencing_token'] or token > job['fencing_token']
                or request['run_id'] != row['scan_id'] or request['instrument'] != row['candidate']):
            raise StateRecoveryError('STATE_CHECKPOINT_FENCE_INVALID')
        if (request['result'] is None) == (request['rejection'] is None):
            raise StateRecoveryError('STATE_CHECKPOINT_REQUEST_INVALID')
        for name in ('result', 'rejection'):
            if request[name] is not None and not isinstance(request[name], dict):
                raise StateRecoveryError('STATE_CHECKPOINT_REQUEST_INVALID')
        for name in ('quote_observed_at', 'governance_decision_at'):
            _timestamp(request[name], optional=True)
        if candidate['fencing_token'] == token:
            expected = dict(run_id=row['scan_id'], instrument=row['candidate'], fencing_token=token,
                result=_json(candidate['result_json']) if candidate['result_json'] is not None else None,
                rejection=_json(candidate['rejection_json']) if candidate['rejection_json'] is not None else None,
                quote_observed_at=candidate['quote_observed_at'],
                governance_decision_at=candidate['governance_decision_at'], item=_json(candidate['item_json']))
            if candidate['status'] != 'COMPLETE' or _encode(expected) != _encode(request):
                raise StateRecoveryError('STATE_CHECKPOINT_REQUEST_INVALID')
        if row['delivered_at'] is None and token != job['fencing_token']:
            raise StateRecoveryError('STATE_STALE_PENDING_CHECKPOINT')
        if (job['remote_finalized_token'] == token and row['delivered_at'] is None):
            raise StateRecoveryError('STATE_FINALIZATION_INVALID')


def _rehash(snapshot: StateSnapshot) -> StateWitness:
    digest = hashlib.sha256((VERSION + ':' + snapshot.witness.schema_sha256 + '\n').encode())
    counts = dict.fromkeys(TABLES, 0)
    size = 0
    for kind, identity, body in snapshot._spool.execute('SELECT kind,identity,body FROM records ORDER BY position'):
        encoded = _encode([kind, identity, body]).encode()
        size += len(encoded)
        if kind not in counts or len(encoded) > MAX_ROW_BYTES or size > MAX_BYTES:
            raise StateRecoveryError('STATE_SPOOL_INVALID')
        counts[kind] += 1
        if sum(counts.values()) > MAX_ROWS:
            raise StateRecoveryError('STATE_SPOOL_INVALID')
        digest.update(encoded + b'\n')
    return StateWitness(VERSION, tuple(counts.values()), snapshot.witness.schema_sha256, digest.hexdigest())


@contextmanager
def _temporary_spool(parent: Path) -> Iterator[Path]:
    """Redact private directory creation and cleanup failures too."""
    try:
        with tempfile.TemporaryDirectory(prefix='local-recovery-', dir=parent) as temporary:
            yield Path(temporary)
    except StateRecoveryError:
        raise
    except Exception:
        raise StateRecoveryError('STATE_PRIVATE_SPOOL_UNAVAILABLE') from None


@contextmanager
def capture(connect: Callable[[], sqlite3.Connection], keys: Mapping[str, bytes], *,
            spool_parent: Path) -> Iterator[StateSnapshot]:
    """Copy five tables in one SELECT-only transaction; close it before yielding.

    A private existing spool directory is explicitly required. The caller must
    establish its ACL/disk capacity; this is not a live deployment mechanism.
    Bounds never truncate to a passing prefix. All originals must have a proved
    equity delivery intent; legacy/local-only intent needs a later adapter.
    """
    source: sqlite3.Connection | None = None
    spool: sqlite3.Connection | None = None
    if not spool_parent.is_dir() or spool_parent.is_symlink() or spool_parent.is_junction():
        raise StateRecoveryError('STATE_PRIVATE_SPOOL_REQUIRED')
    with _temporary_spool(spool_parent) as temporary:
        try:
            source = connect()
            if source.in_transaction:
                raise StateRecoveryError('STATE_FRESH_CONNECTION_REQUIRED')
            source.execute('PRAGMA query_only=ON')
            source.execute('PRAGMA busy_timeout=2000')
            source.execute('PRAGMA cache_size=-2048')
            source.execute('PRAGMA temp_store=FILE')
            source.execute('BEGIN')
            deadline = time.monotonic() + MAX_SOURCE_SECONDS
            source.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
            schema = _schema(source)
            spool = sqlite3.connect(str(Path(temporary) / 'spool.sqlite'))
            spool.execute('PRAGMA cache_size=-2048')
            spool.execute('PRAGMA temp_store=FILE')
            spool.execute(f'PRAGMA max_page_count={MAX_BYTES // 4096}')
            spool.execute('CREATE TABLE records(position INTEGER PRIMARY KEY,kind TEXT NOT NULL,'
                          'identity TEXT NOT NULL,body TEXT NOT NULL,UNIQUE(kind,identity))')
            spool.execute('CREATE TABLE requests(retry TEXT PRIMARY KEY,identity TEXT UNIQUE,body TEXT NOT NULL)')
            previous: tuple[str | None, int, str] = (None, 0, GENESIS_HASH)
            position, size = 0, 0
            for table, fields in TABLES.items():
                # Check byte sizes before asking the driver to materialize a row.
                lengths = '+'.join(f'COALESCE(length(CAST({f} AS BLOB)),0)' for f in fields)
                if source.execute(f'SELECT 1 FROM {table} WHERE ({lengths})>? LIMIT 1',
                                  (MAX_ROW_BYTES,)).fetchone():
                    raise StateRecoveryError('STATE_REQUIRES_LARGER_BOUND_REVIEW')
                for raw in source.execute(f'SELECT {",".join(fields)} FROM {table} ORDER BY {ORDER[table]}'):
                    if time.monotonic() > deadline:
                        raise StateRecoveryError('STATE_SOURCE_TIME_BOUND')
                    row = dict(zip(fields, raw))
                    body = _encode(row)
                    identity = _identity(row, IDENTITY[table])
                    frame = _encode([table, identity, body]).encode()
                    size += len(frame)
                    position += 1
                    if position > MAX_ROWS or len(frame) > MAX_ROW_BYTES or size > MAX_BYTES:
                        raise StateRecoveryError('STATE_REQUIRES_LARGER_BOUND_REVIEW')
                    if table == 'evidence_ledger_events':
                        previous, request = _event(row, keys, previous)
                        spool.execute('INSERT INTO requests VALUES(?,?,?)',
                                      (row['idempotency_key'], _encode([row['idempotency_key']]), request))
                    spool.execute('INSERT INTO records VALUES(?,?,?,?)', (position, table, identity, body))
            source.rollback()
            source.close()
            source = None
            spool.commit()
            spool.execute("CREATE INDEX candidates_job ON records(json_extract(body,'$.job_id'),"
                "json_extract(body,'$.fencing_token'),json_extract(body,'$.status')) "
                "WHERE kind='durable_scan_candidates'")
            _validate(spool)
            provisional = StateWitness(VERSION, (1, 0, 0, 0, 0), schema, '0' * 64)
            result = StateSnapshot(_rehash(StateSnapshot(provisional, spool)), spool)
            yield result
        except StateRecoveryError:
            raise
        except Exception:
            raise StateRecoveryError('STATE_SNAPSHOT_UNVERIFIED') from None
        finally:
            cleanup_failed = False
            for connection in (source, spool):
                if connection is None:
                    continue
                if connection is source:
                    try:
                        connection.rollback()
                    except Exception:
                        cleanup_failed = True
                try:
                    connection.close()
                except Exception:
                    cleanup_failed = True
            if cleanup_failed:
                raise StateRecoveryError('STATE_CLEANUP_UNVERIFIED') from None


def _remote(call: Callable[[], RemoteProof], request: Mapping[str, Any], pending: bool,
            fence: int | None = None) -> bool:
    try:
        proof = call()
    except Exception:
        # Adapter exceptions may contain private details, including our error type.
        raise StateRecoveryError('STATE_REMOTE_UNVERIFIED') from None
    try:
        if not isinstance(proof, RemoteProof) or type(proof.state) is not ProofState:
            raise ValueError
        if proof.state is ProofState.UNAVAILABLE:
            raise ValueError
        if fence is not None and (type(proof.active_fence) is not int or proof.active_fence != fence):
            raise StateRecoveryError('STATE_REMOTE_FENCE_MISMATCH')
        if proof.state is ProofState.ABSENT:
            if proof.request is not None:
                raise ValueError
            if not pending:
                raise StateRecoveryError('STATE_ACK_WITHOUT_REMOTE')
            return False
        if not isinstance(proof.request, Mapping) or _encode(dict(proof.request)) != _encode(dict(request)):
            raise StateRecoveryError('STATE_REMOTE_REQUEST_MISMATCH')
        return pending
    except StateRecoveryError:
        raise
    except Exception:
        raise StateRecoveryError('STATE_REMOTE_UNVERIFIED') from None


def verify(snapshot: StateSnapshot, expected: StateWitness, *,
           evidence_lookup: Callable[[str], RemoteProof],
           checkpoint_lookup: Callable[[str, str, int], RemoteProof],
           run_lookup: Callable[[str, int], RemoteProof]) -> dict[str, object]:
    """Compare independent source witness and detached authenticated receipts.

    No resend, ACK, repair or approval is performed. These injected callbacks
    MUST authenticate receipt presence/absence externally; none are wired here.
    A current-row-only remote adapter may not certify overwritten older fences.
    """
    try:
        if not isinstance(expected, StateWitness) or not isinstance(snapshot, StateSnapshot):
            raise StateRecoveryError('STATE_WITNESS_INVALID')
        if snapshot.witness != expected or _rehash(snapshot) != expected:
            raise StateRecoveryError('STATE_SOURCE_MISMATCH')
        evidence_pending, checkpoint_pending = 0, 0
        for row in _rows(snapshot._spool, 'evidence_delivery_outbox'):
            request = _json(row['event_json'])
            evidence_pending += int(_remote(lambda: evidence_lookup(row['idempotency_key']),
                                           request, row['delivered_at'] is None))
        for row in _rows(snapshot._spool, 'checkpoint_outbox'):
            if row['delivered_at'] is None and row['last_error'] == 'CONFLICT':
                raise StateRecoveryError('STATE_CHECKPOINT_QUARANTINED')
            request = _json(row['checkpoint_json'])
            token = request['fencing_token']
            checkpoint_pending += int(_remote(lambda: checkpoint_lookup(row['scan_id'], row['candidate'], token),
                                              request, row['delivered_at'] is None, token))
        finalized = 0
        for row in _rows(snapshot._spool, 'durable_scan_jobs'):
            token = row['remote_finalized_token']
            if token is not None:
                request = dict(run_id=row['job_id'], fencing_token=token, status=row['status'],
                    finished_at=row['finished_at'], error_kind=_json(row['summary_json']).get('error'))
                _remote(lambda: run_lookup(row['job_id'], token), request, False, token)
                finalized += 1
        return {'status': 'PASS', 'scope': 'FIVE_LOCAL_TABLES_STRICT_EQUITY_DELIVERY',
                'counts': list(expected.counts), 'remote_committed_pending_evidence': evidence_pending,
                'remote_committed_pending_checkpoints': checkpoint_pending,
                'finalized_receipts_checked': finalized, 'approval_authority': False,
                'application_recovery_verified': False}
    except StateRecoveryError as error:
        return {'status': 'FAILED', 'reason': str(error), 'approval_authority': False,
                'application_recovery_verified': False}
    except Exception:
        return {'status': 'FAILED', 'reason': 'STATE_PROOF_UNVERIFIED', 'approval_authority': False,
                'application_recovery_verified': False}
