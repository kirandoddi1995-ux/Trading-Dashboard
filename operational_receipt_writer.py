"""Inactive fenced journal adapter. No live factories, connections or credentials.

Owns no transaction: caller must use a dedicated transaction and reconcile an
unknown COMMIT through exact signed readback, never resend on guessed absence.
SQL atomically updates this NEW namespace's operation and original receipt; it
does not yet write equity_operations or certify global storage admission.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from typing import Any, Protocol

from operational_receipt_history import decode_request, request_identity, seal_receipts


class Result(Protocol):
    """Minimal positional driver result."""
    def fetchone(self) -> Any: ...


class Connection(Protocol):
    """Dedicated caller-owned transaction; no commit capability exposed here."""
    def execute(self, query: str, params: tuple[object, ...] = ()) -> Result: ...


@dataclass(frozen=True)
class PreparedReceipt:
    """Exact canonical intent and original signature, prepared outside SQL locks."""
    kind: str
    run_id: str
    instrument: str
    fence: int
    request: str
    receipt: str


def prepare(kind: str, request: Mapping[str, Any], *, key_id: str,
            signing_key: bytes) -> PreparedReceipt:
    """Reuse the existing bounded validator and historical receipt signature."""
    run, instrument, fence = request_identity(kind, request)
    artifact = json.loads(seal_receipts([(kind, request)], signing_key=signing_key, key_id=key_id))
    row = artifact['receipts'][0]
    canonical = json.dumps(row['request'], sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    decode_request(kind, canonical)
    receipt = json.dumps(row, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return PreparedReceipt(kind, run, instrument, fence, canonical, receipt)


def claim(connection: Connection, run_id: str, owner_id: str, *, expected_fence: int,
          lease_seconds: int = 60) -> int:
    """Bootstrap (expected=0) or CAS takeover of an expired server-clock lease."""
    if (type(expected_fence) is not int or not 0 <= expected_fence < 2**63 - 1
            or type(lease_seconds) is not int or not 1 <= lease_seconds <= 300
            or any(type(x) is not str or not 1 <= len(x.encode()) <= 900 for x in (run_id, owner_id))):
        raise ValueError('OPERATIONAL_CLAIM_INVALID')
    row = connection.execute('SELECT quant_operational_receipts.claim(%s,%s,%s,%s)',
                             (run_id, owner_id, expected_fence, lease_seconds)).fetchone()
    if not isinstance(row, (tuple, list)) or list(row) != [expected_fence + 1]:
        raise ValueError('OPERATIONAL_CLAIM_RESULT_INVALID')
    return expected_fence + 1


def apply(connection: Connection, owner_id: str, prepared: PreparedReceipt) -> str:
    """Atomic fenced operation/receipt. No auto-commit, retry or ACK fabrication."""
    if type(owner_id) is not str or not 1 <= len(owner_id.encode()) <= 900:
        raise ValueError('OPERATIONAL_OWNER_INVALID')
    # Dataclass construction is public; validate identity rather than trusting it.
    request = decode_request(prepared.kind, prepared.request)
    if request_identity(prepared.kind, request) != (prepared.run_id, prepared.instrument, prepared.fence):
        raise ValueError('OPERATIONAL_PREPARED_IDENTITY_INVALID')
    row = connection.execute('SELECT quant_operational_receipts.apply(%s,%s,%s,%s,%s,%s,%s)',
        (owner_id, prepared.kind, prepared.run_id, prepared.instrument, prepared.fence,
         prepared.request, prepared.receipt)).fetchone()
    if not isinstance(row, (tuple, list)) or len(row) != 1 or row[0] not in ('NEW', 'IDEMPOTENT'):
        raise ValueError('OPERATIONAL_APPLY_RESULT_INVALID')
    return str(row[0])


def original(connection: Connection, prepared: PreparedReceipt) -> str | None:
    """Exact historical lookup. None means unavailable, NOT certified absence."""
    row = connection.execute('SELECT receipt_text FROM quant_operational_receipts.receipts '
        'WHERE kind=%s AND run_id=%s AND instrument=%s AND fence=%s',
        (prepared.kind, prepared.run_id, prepared.instrument, prepared.fence)).fetchone()
    if row is None:
        return None
    if not isinstance(row, (tuple, list)) or len(row) != 1 or row[0] != prepared.receipt:
        raise ValueError('OPERATIONAL_ORIGINAL_CONFLICT')
    return str(row[0])
