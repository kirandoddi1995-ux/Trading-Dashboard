"""Bounded, authenticated immutable-fence receipts for offline recovery.

No database, credential discovery, live factory, ACK, resend or deletion. The
independently retained digest must identify receipts produced atomically with
the operational commit by a separately commissioned writer. Signing an export
of current mutable rows cannot establish that provenance. Missing receipts are
UNAVAILABLE, never authenticated absence (including pre-commission history).
"""
from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
import datetime as dt
import hashlib
import hmac
import json
import math
from typing import Any

from local_state_recovery import CHECKPOINT, ProofState, RemoteProof

FORMAT = 'operational-receipt-history-v1'
MAX_BYTES = 32 * 1024 * 1024
MAX_ROWS = 20_000
MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 32
MAX_NODES = 1_000_000
RUN = ('run_id', 'fencing_token', 'status', 'finished_at', 'error_kind')
_VERIFIED = object()


class ReceiptHistoryError(ValueError):
    """Stable redacted error; source text, paths and keys are never included."""


def _encode(value: object, *, limit: int = MAX_BYTES) -> bytes:
    _json_value(value, limit=limit)
    result = json.dumps(value, sort_keys=True, separators=(',', ':'),
                        ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(result) > limit:
        raise ReceiptHistoryError('RECEIPT_BYTE_LIMIT')
    return result


def _json_value(value: object, *, limit: int) -> None:
    """Budget before full serialization; reject lossy keys/deep/wide objects."""
    nodes, size = 0, 0
    def visit(item: Any, depth: int) -> None:
        nonlocal nodes, size
        nodes += 1
        if depth > MAX_DEPTH or nodes > MAX_NODES:
            raise ReceiptHistoryError('RECEIPT_COMPLEXITY_LIMIT')
        if type(item) is str:
            # Check characters first: UTF-8 conversion is then itself bounded.
            if len(item) > limit:
                raise ReceiptHistoryError('RECEIPT_BYTE_LIMIT')
            size += 2 + len(item.encode('utf-8'))
            size += sum(1 if char in '"\\\b\f\n\r\t' else 5 if ord(char) < 32 else 0 for char in item)
        elif type(item) in (bool, type(None)):
            size += 5  # safe upper bound
        elif type(item) in (int, float):
            if type(item) is int and item.bit_length() > 4096:
                raise ReceiptHistoryError('RECEIPT_NUMBER_LIMIT')
            size += len(str(item))
        elif type(item) is list:
            size += 2 + len(item)
            if len(item) > MAX_NODES:
                raise ReceiptHistoryError('RECEIPT_COMPLEXITY_LIMIT')
            for child in item:
                visit(child, depth + 1)
        elif type(item) is dict:
            size += 2 + 2 * len(item)
            if len(item) > MAX_NODES:
                raise ReceiptHistoryError('RECEIPT_COMPLEXITY_LIMIT')
            for key, child in item.items():
                if type(key) is not str:
                    raise ReceiptHistoryError('RECEIPT_JSON_KEY_INVALID')
                visit(key, depth + 1)
                visit(child, depth + 1)
        else:
            raise ReceiptHistoryError('RECEIPT_JSON_VALUE_INVALID')
        if size > limit:
            raise ReceiptHistoryError('RECEIPT_BYTE_LIMIT')
    visit(value, 0)


def _preflight(data: bytes) -> None:
    """Bound nesting/container tokens BEFORE the JSON parser allocates objects."""
    quoted, escaped = False, False
    depth, nodes = 0, 0
    for byte in data:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (123, 91):
            depth += 1
            nodes += 1
        elif byte in (125, 93):
            depth -= 1
        elif byte in (44, 58):
            nodes += 1
        if depth > MAX_DEPTH or nodes > MAX_NODES:
            raise ReceiptHistoryError('RECEIPT_COMPLEXITY_LIMIT')


def _text(value: object) -> str:
    if (not isinstance(value, str) or not 1 <= len(value) <= 900
            or len(value.encode()) > 900):
        raise ReceiptHistoryError('RECEIPT_IDENTITY_INVALID')
    return value


def _token(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise ReceiptHistoryError('RECEIPT_FENCE_INVALID')
    return value


def _stamp(value: object) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        raise ReceiptHistoryError('RECEIPT_TIME_INVALID')
    try:
        stamp = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except Exception:
        raise ReceiptHistoryError('RECEIPT_TIME_INVALID') from None
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ReceiptHistoryError('RECEIPT_TIME_INVALID')


def request_identity(kind: str, request: Mapping[str, Any]) -> tuple[str, str, int]:
    """Validate bounded exact original intent and return its immutable identity."""
    fields = CHECKPOINT if kind == 'checkpoint' else RUN if kind == 'run' else ()
    if not fields or set(request) != set(fields):
        raise ReceiptHistoryError('RECEIPT_REQUEST_INVALID')
    run, fence = _text(request['run_id']), _token(request['fencing_token'])
    if kind == 'checkpoint':
        instrument = _text(request['instrument'])
        if (request['result'] is None) == (request['rejection'] is None):
            raise ReceiptHistoryError('RECEIPT_REQUEST_INVALID')
        for name in ('result', 'rejection'):
            if request[name] is not None and not isinstance(request[name], dict):
                raise ReceiptHistoryError('RECEIPT_REQUEST_INVALID')
        _stamp(request['quote_observed_at'])
        _stamp(request['governance_decision_at'])
    else:
        instrument = ''
        if request['status'] not in ('COMPLETE', 'INTERRUPTED', 'CANCELLED'):
            raise ReceiptHistoryError('RECEIPT_TERMINAL_STATUS_INVALID')
        finished = request['finished_at']
        if finished is not None and (type(finished) not in (int, float)
                                     or not math.isfinite(finished) or finished < 0):
            raise ReceiptHistoryError('RECEIPT_TIME_INVALID')
        if request['error_kind'] is not None:
            _text(request['error_kind'])
    _encode(request, limit=MAX_REQUEST_BYTES)
    return run, instrument, fence


def seal_receipts(receipts: Sequence[tuple[str, Mapping[str, Any]]], *,
                  signing_key: bytes, key_id: str) -> bytes:
    """Encode synthetic fixtures or ALREADY proven original commit receipts.

    This helper does not establish atomic commit provenance. Never use it to
    backfill proof from current operational rows or to authorise restoration.
    Identity collisions fail even if their payloads happen to be identical.
    """
    try:
        if type(signing_key) is not bytes or len(signing_key) < 32:
            raise ReceiptHistoryError('RECEIPT_KEY_INVALID')
        _text(key_id)
        if len(receipts) > MAX_ROWS:
            raise ReceiptHistoryError('RECEIPT_ROW_LIMIT')
        seen: set[tuple[str, str, str, int]] = set()
        rows: list[dict[str, Any]] = []
        size = len(_encode(dict(format=FORMAT, receipts=[])))
        for kind, request in receipts:
            identity = (kind, *request_identity(kind, request))
            if identity in seen:
                raise ReceiptHistoryError('RECEIPT_IDENTITY_COLLISION')
            seen.add(identity)
            body = dict(format=FORMAT, kind=kind, key_id=key_id, request=request)
            signature = hmac.new(signing_key, _encode(body), hashlib.sha256).hexdigest()
            signed = dict(body, signature=signature)
            size += len(_encode(signed)) + int(bool(rows))
            if size > MAX_BYTES:
                raise ReceiptHistoryError('RECEIPT_BYTE_LIMIT')
            rows.append(signed)
        result = _encode(dict(format=FORMAT, receipts=rows))
        if len(result) > MAX_BYTES:
            raise ReceiptHistoryError('RECEIPT_BYTE_LIMIT')
        return result
    except ReceiptHistoryError:
        raise
    except Exception:
        raise ReceiptHistoryError('RECEIPT_ENCODING_BLOCKED') from None


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReceiptHistoryError('RECEIPT_DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def _nonfinite(value: str) -> Any:
    raise ReceiptHistoryError('RECEIPT_NONFINITE_JSON_INVALID')


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ReceiptHistoryError('RECEIPT_NONFINITE_JSON_INVALID')
    return number


def decode_object(data: str, *, max_bytes: int) -> dict[str, Any]:
    """Bound UTF-8, lexical depth/nodes and duplicate keys before object parsing."""
    try:
        if (type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES
                or type(data) is not str or len(data) > max_bytes):
            raise ReceiptHistoryError('RECEIPT_BYTE_LIMIT')
        raw = data.encode('utf-8')
        if len(raw) > max_bytes or '\x00' in data or data.startswith('\ufeff'):
            raise ReceiptHistoryError('RECEIPT_UTF8_REQUIRED')
        _preflight(raw)
        request = json.loads(data, object_pairs_hook=_unique, parse_constant=_nonfinite,
                             parse_float=_finite_float)
        if not isinstance(request, dict):
            raise ReceiptHistoryError('RECEIPT_REQUEST_INVALID')
        return request
    except ReceiptHistoryError:
        raise
    except Exception:
        raise ReceiptHistoryError('RECEIPT_INTENT_DECODE_BLOCKED') from None


def decode_request(kind: str, data: str) -> dict[str, Any]:
    """Budgeted canonical original intent decoder for an inactive local journal."""
    request = decode_object(data, max_bytes=MAX_REQUEST_BYTES)
    request_identity(kind, request)
    if _encode(request, limit=MAX_REQUEST_BYTES).decode() != data:
        raise ReceiptHistoryError('RECEIPT_CANONICAL_INTENT_REQUIRED')
    return request


class OperationalReceipts:
    """Verified pinned artifact; historical fence is NOT the current live fence.

    Returning the original receipt's fence satisfies the recovery verifier's
    equality check without pretending newer mutable run ownership never exists.
    No authenticated absence or authority to retry an old fence is provided.
    """

    def __init__(self, rows: dict[tuple[str, str, str, int], bytes], *, _verified: object = None):
        if _verified is not _VERIFIED:
            raise ReceiptHistoryError('RECEIPT_VERIFIED_ARTIFACT_REQUIRED')
        self._rows: dict[tuple[str, str, str, int], bytes] | None = rows

    def _lookup(self, kind: str, run: str, instrument: str, fence: int) -> RemoteProof:
        try:
            if self._rows is None:
                raise ReceiptHistoryError('RECEIPT_CUT_CLOSED')
            key = (kind, _text(run), _text(instrument) if kind == 'checkpoint' else '', _token(fence))
            original = self._rows.get(key)
            if original is None:
                return RemoteProof(ProofState.UNAVAILABLE)
            return RemoteProof(ProofState.PRESENT, json.loads(original), active_fence=fence)
        except Exception:
            raise ReceiptHistoryError('RECEIPT_LOOKUP_BLOCKED') from None

    def checkpoint(self, run_id: str, instrument: str, fencing_token: int) -> RemoteProof:
        """Exact immutable original request, including item and timestamp spelling."""
        return self._lookup('checkpoint', run_id, instrument, fencing_token)

    def run(self, run_id: str, fencing_token: int) -> RemoteProof:
        """Exact original terminal request, not a later mutable heartbeat row."""
        return self._lookup('run', run_id, '', fencing_token)


@contextmanager
def receipt_history(data: bytes, *, independently_expected_sha256: str,
                    keyring: Mapping[str, bytes]) -> Iterator[OperationalReceipts]:
    """Verify the ENTIRE artifact before exposing any lookup; invalidate on exit.

    Caller retains the digest independently under the existing custody contract.
    Readback digest, every original signature and unique identity must all match.
    Self-reported digest or a current-row export is not independent provenance.
    """
    try:
        if type(data) is not bytes or len(data) > MAX_BYTES:
            raise ReceiptHistoryError('RECEIPT_BYTE_LIMIT')
        if (not isinstance(independently_expected_sha256, str)
                or len(independently_expected_sha256) != 64
                or any(c not in '0123456789abcdef' for c in independently_expected_sha256)
                or hashlib.sha256(data).hexdigest() != independently_expected_sha256):
            raise ReceiptHistoryError('RECEIPT_INDEPENDENT_DIGEST_MISMATCH')
        # json.loads(bytes) auto-detects UTF-16/32, which our ASCII-byte lexical
        # budget must NOT scan as though it were UTF-8. Parse exactly decoded text.
        text = data.decode('utf-8', errors='strict')
        if '\x00' in text or text.startswith('\ufeff'):
            raise ReceiptHistoryError('RECEIPT_UTF8_REQUIRED')
        _preflight(data)
        document = json.loads(text, object_pairs_hook=_unique, parse_constant=_nonfinite,
                              parse_float=_finite_float)
        if (not isinstance(document, dict) or set(document) != {'format', 'receipts'}
                or document['format'] != FORMAT or not isinstance(document['receipts'], list)):
            raise ReceiptHistoryError('RECEIPT_SCHEMA_INVALID')
        if len(document['receipts']) > MAX_ROWS:
            raise ReceiptHistoryError('RECEIPT_ROW_LIMIT')
        rows: dict[tuple[str, str, str, int], bytes] = {}
        for row in document['receipts']:
            if (not isinstance(row, dict)
                    or set(row) != {'format', 'kind', 'key_id', 'request', 'signature'}
                    or row['format'] != FORMAT or not isinstance(row['request'], dict)):
                raise ReceiptHistoryError('RECEIPT_SCHEMA_INVALID')
            key = keyring.get(_text(row['key_id']))
            if type(key) is not bytes or len(key) < 32:
                raise ReceiptHistoryError('RECEIPT_ORIGINAL_KEY_UNAVAILABLE')
            body = {name: row[name] for name in ('format', 'kind', 'key_id', 'request')}
            signature = row['signature']
            if (not isinstance(signature, str) or not hmac.compare_digest(signature,
                    hmac.new(key, _encode(body), hashlib.sha256).hexdigest())):
                raise ReceiptHistoryError('RECEIPT_ORIGINAL_SIGNATURE_INVALID')
            identity = (row['kind'], *request_identity(row['kind'], row['request']))
            if identity in rows:
                raise ReceiptHistoryError('RECEIPT_IDENTITY_COLLISION')
            rows[identity] = _encode(row['request'])
        lookup = OperationalReceipts(rows, _verified=_VERIFIED)
    except ReceiptHistoryError:
        raise
    except Exception:
        raise ReceiptHistoryError('RECEIPT_VERIFICATION_BLOCKED') from None
    try:
        yield lookup
    finally:
        lookup._rows = None
