"""Offline sealed ledger segments; no database writes, network or secret loading.

A segment digest must be pinned independently in a committed archive catalog.
Checksums alone do not authenticate a mutable Drive file. Unknown keys and missing
predecessor evidence fail closed; existing event hashes are never recomputed for storage.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import re
import zlib
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast
from types import MappingProxyType

from evidence_ledger import GENESIS_HASH, canonical_json

FORMAT = "ledger-segment-v1"
LEGACY_KEY_ID = "legacy-schema-v1"
MAX_RAW_BYTES = 32 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_ROWS = 2000
HASH = re.compile(r"[0-9a-f]{64}")
FIELDS = ("event_id", "aggregate_id", "sequence_no", "event_type", "recorded_at",
          "effective_at", "source", "actor_id", "idempotency_key", "payload",
          "previous_hash", "event_hash", "hash_algorithm", "schema_version", "key_id")
Head = tuple[int, str]


class SegmentError(ValueError):
    """Stable, payload-free archive failure category."""


@dataclass(frozen=True)
class SealedSegment:
    """Bytes and independent catalog digest; neither contains signing material."""

    data: bytes = field(repr=False)
    sha256: str
    rows: int
    heads: Mapping[str, Head]


def _json(value: Mapping[str, object]) -> bytes:
    return canonical_json(value).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _head(value: Head) -> Head:
    sequence, digest = value
    if type(sequence) is not int or sequence < 0 or not HASH.fullmatch(digest):
        raise SegmentError("INVALID_HEAD")
    if sequence == 0 and digest != GENESIS_HASH:
        raise SegmentError("INVALID_GENESIS")
    return sequence, digest


def _record(value: Mapping[str, object]) -> dict[str, object]:
    if set(value) - {"duplicate"} != set(FIELDS):
        raise SegmentError("EVENT_SCHEMA_MISMATCH")
    row = {name: value[name] for name in FIELDS}
    # psycopg returns PostgreSQL UUID values as UUID objects. Normalize only that
    # native type, never arbitrary objects whose __str__ could conceal bad input.
    if isinstance(row['event_id'], uuid.UUID):
        row['event_id'] = str(row['event_id'])
    for name in ("recorded_at", "effective_at"):
        stamp = row[name]
        if isinstance(stamp, dt.datetime):
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise SegmentError("NAIVE_TIMESTAMP")
            stamp = stamp.astimezone(dt.timezone.utc).isoformat()
            row[name] = stamp
        if not isinstance(stamp, str):
            raise SegmentError("INVALID_TIMESTAMP")
        try:
            parsed = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            raise SegmentError("INVALID_TIMESTAMP") from None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise SegmentError("NAIVE_TIMESTAMP")
    for name in ("event_id", "aggregate_id", "event_type", "source", "actor_id",
                 "idempotency_key", "previous_hash", "event_hash", "hash_algorithm"):
        if not isinstance(row[name], str) or not row[name]:
            raise SegmentError("INVALID_EVENT_FIELD")
    for name in ("event_hash", "previous_hash"):
        if not HASH.fullmatch(cast(str, row[name])):
            raise SegmentError("INVALID_EVENT_HASH")
    if type(row["sequence_no"]) is not int or row["sequence_no"] < 1:
        raise SegmentError("INVALID_SEQUENCE")
    if type(row["schema_version"]) is not int or row["schema_version"] not in (1, 2):
        raise SegmentError("UNSUPPORTED_LEDGER_VERSION")
    if not isinstance(row["payload"], dict):
        raise SegmentError("INVALID_PAYLOAD")
    if row["key_id"] is not None and not isinstance(row["key_id"], str):
        raise SegmentError("INVALID_KEY_ID")
    return row


def _material(row: Mapping[str, object]) -> bytes:
    fields = {name: row[name] for name in FIELDS if name not in ("payload", "event_hash")}
    fields["payload_json"] = canonical_json(cast(Mapping[str, object], row["payload"]))
    if row["schema_version"] == 2:
        return _json(fields)
    # Legacy version 1 uses its original pipe-separated material, not v2 JSON.
    order = ("event_id", "aggregate_id", "sequence_no", "event_type", "recorded_at",
             "effective_at", "source", "actor_id", "idempotency_key", "payload_json",
             "previous_hash", "hash_algorithm", "schema_version")
    return "|".join(str(fields[name]) for name in order).encode("utf-8")


def verify_records(records: Sequence[Mapping[str, object]], predecessors: Mapping[str, Head],
                   keyring: Mapping[str, bytes]) -> dict[str, Head]:
    """Verify exact event signatures and contiguous per-aggregate sequencing.

    Predecessors come from a verified catalog, never from the untrusted segment.
    Entirely new aggregates must start at genesis; sequence gaps are errors.
    """
    if not 1 <= len(records) <= MAX_ROWS:
        raise SegmentError("INVALID_ROW_COUNT")
    heads = {name: _head(value) for name, value in predecessors.items()}
    seen_events: set[str] = set()
    seen_keys: set[str] = set()
    for value in records:
        row = _record(value)
        aggregate = cast(str, row["aggregate_id"])
        preceding = heads.get(aggregate, (0, GENESIS_HASH))
        sequence = cast(int, row["sequence_no"])
        if sequence != preceding[0] + 1 or row["previous_hash"] != preceding[1]:
            raise SegmentError("BROKEN_EVENT_CHAIN")
        event_id, idem = cast(str, row["event_id"]), cast(str, row["idempotency_key"])
        if event_id in seen_events or idem in seen_keys:
            raise SegmentError("DUPLICATE_EVENT_IDENTITY")
        seen_events.add(event_id)
        seen_keys.add(idem)
        algorithm = row["hash_algorithm"]
        material = _material(row)
        if algorithm == "HMAC-SHA256":
            # Schema v1 predates key IDs. Only an explicit legacy key binding is
            # permitted; never silently substitute the current signing key.
            lookup_id = (LEGACY_KEY_ID if row["schema_version"] == 1 and row["key_id"] is None
                         else cast(str, row["key_id"]))
            key = keyring.get(lookup_id)
            if not key:
                raise SegmentError("SIGNING_KEY_UNAVAILABLE")
            digest = hmac.new(key, material, hashlib.sha256).hexdigest()
        elif algorithm == "SHA256 hash chain" and row["key_id"] in (None, "unsigned"):
            digest = _sha(material)
        else:
            raise SegmentError("UNSUPPORTED_HASH_ALGORITHM")
        if not hmac.compare_digest(digest, cast(str, row["event_hash"])):
            raise SegmentError("EVENT_SIGNATURE_MISMATCH")
        heads[aggregate] = (sequence, digest)
    return heads


def seal(records: Sequence[Mapping[str, object]], predecessors: Mapping[str, Head],
         keyring: Mapping[str, bytes], seal_key: bytes) -> SealedSegment:
    """Build a bounded deterministic HMAC-sealed segment, retaining original hashes."""
    if len(seal_key) < 32:
        raise SegmentError("ARCHIVE_SEAL_KEY_TOO_SHORT")
    if not 1 <= len(records) <= MAX_ROWS:
        raise SegmentError("INVALID_ROW_COUNT")
    rows = [_record(row) for row in records]
    heads = verify_records(rows, predecessors, keyring)
    content = {"format": FORMAT, "records": rows}
    material = _json(content)
    if len(material) > MAX_RAW_BYTES:
        raise SegmentError("SEGMENT_TOO_LARGE")
    encoded = _json({"content": content, "seal": hmac.new(
        seal_key, material, hashlib.sha256).hexdigest()})
    if len(encoded) > MAX_RAW_BYTES:
        raise SegmentError("SEGMENT_TOO_LARGE")
    compressor = zlib.compressobj(level=9, wbits=31)
    data = compressor.compress(encoded) + compressor.flush()
    if len(data) > MAX_FILE_BYTES:
        raise SegmentError("SEGMENT_TOO_LARGE")
    return SealedSegment(data, _sha(data), len(rows), MappingProxyType(heads))


def restore(data: bytes, trusted_sha256: str, predecessors: Mapping[str, Head],
            keyring: Mapping[str, bytes], seal_key: bytes) -> tuple[list[dict[str, object]], dict[str, Head]]:
    """Bounded offline restoration; verify pinned bytes, seal, schema and original chain."""
    if len(seal_key) < 32:
        raise SegmentError("ARCHIVE_SEAL_KEY_TOO_SHORT")
    if not HASH.fullmatch(trusted_sha256) or not 1 <= len(data) <= MAX_FILE_BYTES:
        raise SegmentError("INVALID_SEGMENT")
    if not hmac.compare_digest(_sha(data), trusted_sha256):
        raise SegmentError("SEGMENT_DIGEST_MISMATCH")
    inflater = zlib.decompressobj(wbits=31)
    try:
        raw = inflater.decompress(data, MAX_RAW_BYTES + 1)
    except zlib.error:
        raise SegmentError("INVALID_COMPRESSION") from None
    if len(raw) > MAX_RAW_BYTES or not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
        raise SegmentError("UNBOUNDED_OR_TRAILING_SEGMENT")
    try:
        envelope = json.loads(raw)
    except (ValueError, UnicodeError):
        raise SegmentError("INVALID_SEGMENT_JSON") from None
    if not isinstance(envelope, dict) or set(envelope) != {"content", "seal"}:
        raise SegmentError("INVALID_ENVELOPE")
    content = envelope["content"]
    signature = envelope["seal"]
    if (not isinstance(content, dict) or set(content) != {"format", "records"}
            or content["format"] != FORMAT or not isinstance(signature, str)):
        raise SegmentError("INVALID_ENVELOPE")
    try:
        material = _json(content)
    except (TypeError, ValueError):
        raise SegmentError("INVALID_SEGMENT_JSON") from None
    if not hmac.compare_digest(hmac.new(seal_key, material, hashlib.sha256).hexdigest(), signature):
        raise SegmentError("ARCHIVE_SEAL_MISMATCH")
    records = content["records"]
    if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
        raise SegmentError("EVENT_SCHEMA_MISMATCH")
    rows = [_record(row) for row in records]
    return rows, verify_records(rows, predecessors, keyring)

