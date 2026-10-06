"""Bounded SELECT-only SQLite recovery proof; never repair, prune or send.

Local and remote envelopes differ. Remote lookup must independently authenticate
originals and verified absence; this module compares the original request only.
No live factory imports this module until commissioning is reviewed.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import hmac
import json
import re
import sqlite3
from typing import Any

from evidence_ledger import ImmutableEvidenceLedger, canonical_json, GENESIS_HASH

MAX_ROWS = 20_000
MAX_BYTES = 32 * 1024 * 1024
REQUEST = ('aggregate_id', 'event_type', 'payload', 'effective_at', 'source',
           'actor_id', 'idempotency_key')
FIELDS = ('event_id', 'aggregate_id', 'sequence_no', 'event_type', 'recorded_at',
          'effective_at', 'source', 'actor_id', 'idempotency_key', 'payload_json',
          'previous_hash', 'event_hash', 'hash_algorithm', 'schema_version', 'key_id')


class LocalRecoveryError(ValueError):
    """Stable errors without rows, keys, paths or driver details."""


@dataclass(frozen=True)
class LocalWitness:
    """Reviewed source snapshot, including pending and acknowledged transport."""
    events: int
    deliveries: int
    pending: int
    sha256: str

    def __post_init__(self) -> None:
        if (any(type(value) is not int for value in (self.events, self.deliveries, self.pending))
                or not 1 <= self.events <= MAX_ROWS or not 0 <= self.pending <= self.deliveries <= MAX_ROWS
                or not isinstance(self.sha256, str) or re.fullmatch('[0-9a-f]{64}', self.sha256) is None):
            raise LocalRecoveryError('LOCAL_RECOVERY_WITNESS_INVALID')


@dataclass(frozen=True)
class LocalSnapshot:
    """Bounded detached evidence: no SQLite transaction remains during lookup."""
    witness: LocalWitness
    deliveries: tuple[tuple[str, bool], ...]


def capture(connect: Callable[[], sqlite3.Connection],
            keys: Mapping[str, bytes]) -> LocalSnapshot:
    """Read one consistent local snapshot and verify every original HMAC chain.

    The injected connection is fresh, caller-owned by this function and closed.
    PRAGMA query_only blocks accidental mutation; no schema initialization runs.
    Unsigned or unknown-key history cannot certify authenticated recovery.
    """
    conn: sqlite3.Connection | None = None
    try:
        conn = connect()
        if conn.in_transaction:
            raise LocalRecoveryError('LOCAL_RECOVERY_FRESH_CONNECTION_REQUIRED')
        conn.execute('PRAGMA query_only=ON')
        conn.execute('PRAGMA busy_timeout=2000')
        conn.execute('BEGIN')
        digest = hashlib.sha256()
        identities: dict[str, dict[str, Any]] = {}
        event_ids: set[str] = set()
        previous_aggregate: str | None = None
        previous_hash, sequence = GENESIS_HASH, 0
        total_bytes = 0
        for raw in conn.execute('SELECT '+','.join(FIELDS)+
                                ' FROM evidence_ledger_events ORDER BY aggregate_id,sequence_no'):
            if len(identities) >= MAX_ROWS:
                raise LocalRecoveryError('LOCAL_RECOVERY_REQUIRES_SPOOLING')
            row = dict(zip(FIELDS, raw))
            if any(not isinstance(row[name], str) or not row[name] for name in
                   ('event_id', 'aggregate_id', 'idempotency_key', 'event_hash', 'previous_hash')):
                raise LocalRecoveryError('LOCAL_RECOVERY_ORIGINAL_INVALID')
            encoded = canonical_json(row).encode()
            total_bytes += len(encoded)
            if total_bytes > MAX_BYTES:
                raise LocalRecoveryError('LOCAL_RECOVERY_REQUIRES_SPOOLING')
            if row['aggregate_id'] != previous_aggregate:
                previous_aggregate = row['aggregate_id']
                previous_hash, sequence = GENESIS_HASH, 0
            key = keys.get(row['key_id'])
            if (row['hash_algorithm'] != 'HMAC-SHA256' or not isinstance(key, bytes)
                    or not key or type(row['schema_version']) is not int
                    or row['schema_version'] not in (1, 2)):
                raise LocalRecoveryError('LOCAL_RECOVERY_SIGNING_KEY_UNVERIFIED')
            material = ImmutableEvidenceLedger._material(**{name: row[name] for name in FIELDS
                if name != 'event_hash'})
            expected = hmac.new(key, material.encode(), hashlib.sha256).hexdigest()
            if (type(row['sequence_no']) is not int or row['sequence_no'] != sequence + 1
                    or row['previous_hash'] != previous_hash
                    or not hmac.compare_digest(row['event_hash'], expected)):
                raise LocalRecoveryError('LOCAL_RECOVERY_ORIGINAL_INVALID')
            payload = json.loads(row['payload_json'])
            if not isinstance(payload, dict) or canonical_json(payload) != row['payload_json']:
                raise LocalRecoveryError('LOCAL_RECOVERY_ORIGINAL_INVALID')
            request = {name: (payload if name == 'payload' else row[name]) for name in REQUEST}
            retry = row['idempotency_key']
            if retry in identities or row['event_id'] in event_ids:
                raise LocalRecoveryError('LOCAL_RECOVERY_IDENTITY_REUSED')
            event_ids.add(row['event_id'])
            identities[retry] = request
            previous_hash, sequence = row['event_hash'], row['sequence_no']
            digest.update(b'E'+encoded+b'\n')
        if not identities:
            raise LocalRecoveryError('LOCAL_RECOVERY_SOURCE_EMPTY')
        deliveries: list[tuple[str, bool]] = []
        pending = 0
        for raw in conn.execute('''SELECT idempotency_key,event_json,attempts,last_error,
                next_attempt_at,created_at,delivered_at,delivery_lane
                FROM evidence_delivery_outbox ORDER BY idempotency_key'''):
            if len(deliveries) >= MAX_ROWS:
                raise LocalRecoveryError('LOCAL_RECOVERY_REQUIRES_SPOOLING')
            encoded = json.dumps(list(raw), ensure_ascii=True, allow_nan=False,
                                 separators=(',', ':')).encode()
            total_bytes += len(encoded)
            if total_bytes > MAX_BYTES:
                raise LocalRecoveryError('LOCAL_RECOVERY_REQUIRES_SPOOLING')
            request = json.loads(raw[1])
            original = identities.get(raw[0])
            # Equity queue stores exactly the request, not the signed envelope.
            if (raw[7] != 'equity' or not isinstance(request, dict) or original is None
                    or set(request) != set(REQUEST)
                    or canonical_json(request) != canonical_json(original)
                    or type(raw[2]) is not int or raw[2] < 0):
                raise LocalRecoveryError('LOCAL_RECOVERY_OUTBOX_UNVERIFIED')
            is_pending = raw[6] is None
            pending += int(is_pending)
            deliveries.append((canonical_json(request), is_pending))
            digest.update(b'O'+encoded+b'\n')
        return LocalSnapshot(LocalWitness(len(identities), len(deliveries), pending,
                                         digest.hexdigest()), tuple(deliveries))
    except LocalRecoveryError:
        raise
    except Exception:
        raise LocalRecoveryError('LOCAL_RECOVERY_SNAPSHOT_UNVERIFIED') from None
    finally:
        if conn is not None:
            try:
                try:
                    conn.rollback()
                finally:
                    conn.close()
            except Exception:
                raise LocalRecoveryError('LOCAL_RECOVERY_CONNECTION_CLEANUP_FAILED') from None


def verify(snapshot: LocalSnapshot, expected: LocalWitness,
           verified_remote_request: Callable[[str], Mapping[str, Any] | None]) -> dict[str, object]:
    """Compare reviewed snapshot and authenticated remote receipts, never resend.

    None must mean authenticated absence, not an unavailable feed or lookup error.
    Pending-but-remotely-committed is the legitimate crash-before-ACK boundary.
    Non-equity legacy transport is intentionally blocked pending its own adapter.
    No application recovery certificate is issued from this scoped check.
    """
    try:
        if snapshot.witness != expected:
            raise LocalRecoveryError('LOCAL_RECOVERY_SOURCE_MISMATCH')
        committed_pending = 0
        for encoded_request, pending in snapshot.deliveries:
            request = json.loads(encoded_request)
            try:
                remote = verified_remote_request(request['idempotency_key'])
            except Exception:
                raise LocalRecoveryError('LOCAL_RECOVERY_REMOTE_UNVERIFIED') from None
            if remote is None:
                if not pending:
                    raise LocalRecoveryError('LOCAL_RECOVERY_ACK_WITHOUT_REMOTE')
            elif (set(remote) != set(REQUEST)
                  or canonical_json(remote) != canonical_json(request)):
                raise LocalRecoveryError('LOCAL_RECOVERY_REMOTE_REQUEST_MISMATCH')
            else:
                committed_pending += int(pending)
        return {'status': 'PASS', 'scope': 'LOCAL_ORIGINALS_AND_EQUITY_OUTBOX',
                'events_checked': snapshot.witness.events,
                'pending': snapshot.witness.pending,
                'remote_committed_pending_ack': committed_pending,
                'application_recovery_verified': False, 'approval_authority': False}
    except LocalRecoveryError as error:
        return {'status': 'FAILED', 'reason': str(error), 'approval_authority': False,
                'application_recovery_verified': False}
    except Exception:
        return {'status': 'FAILED', 'reason': 'LOCAL_RECOVERY_REMOTE_UNVERIFIED',
                'approval_authority': False, 'application_recovery_verified': False}
