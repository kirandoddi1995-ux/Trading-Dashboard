"""Signed cold-catalog generations, pinned to an independently trusted anchor.

Pure codec: signatures alone cannot reject rollback. Callers MUST supply the last
committed anchor from protected durable state, not one read from the same Drive
object. This module neither commits an anchor nor authorizes source deletion.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import hmac
import json
import re
from typing import cast

from cold_catalog import EMPTY_ROOT
from evidence_ledger import GENESIS_HASH

FORMAT = "cold-root-receipt-v1"
MAX_BYTES = 8192
MAX_GENERATION = (1 << 63) - 1
HEX = re.compile(r"[0-9a-f]{64}")
FIELDS = {"format", "scope", "generation", "root", "previous_root",
          "previous_receipt", "segment", "published_at", "key_id"}


class ReceiptError(ValueError):
    """Stable error codes without credentials or archive payloads."""


@dataclass(frozen=True)
class RootAnchor:
    """Expected predecessor from independently protected committed state."""

    scope: str
    generation: int
    root: str
    receipt_sha256: str


@dataclass(frozen=True)
class SignedReceipt:
    """Publication bytes and proposed successor, not an SQL commit receipt."""

    data: bytes = field(repr=False)
    anchor: RootAnchor


def _hash(value: object) -> str:
    if not isinstance(value, str) or not HEX.fullmatch(value):
        raise ReceiptError("ROOT_RECEIPT_INVALID")
    return value


def _name(value: object) -> str:
    if (not isinstance(value, str) or not 1 <= len(value) <= 128
            or not re.fullmatch(r"[A-Za-z0-9_.:-]+", value)):
        raise ReceiptError("ROOT_RECEIPT_INVALID")
    return value


def _anchor(value: RootAnchor) -> None:
    _name(value.scope)
    _hash(value.root)
    _hash(value.receipt_sha256)
    if (type(value.generation) is not int
            or not 0 <= value.generation <= MAX_GENERATION):
        raise ReceiptError("ROOT_ANCHOR_INVALID")
    if value.generation == 0:
        if value.root != EMPTY_ROOT or value.receipt_sha256 != GENESIS_HASH:
            raise ReceiptError("ROOT_ANCHOR_INVALID")
    elif value.receipt_sha256 == GENESIS_HASH:
        raise ReceiptError("ROOT_ANCHOR_INVALID")


def genesis(scope: str) -> RootAnchor:
    """Explicit empty bootstrap; never substitute this for a missing SQL anchor."""
    result = RootAnchor(scope, 0, EMPTY_ROOT, GENESIS_HASH)
    _anchor(result)
    return result


def _json(value: Mapping[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _key(key: object) -> bytes:
    if not isinstance(key, bytes) or len(key) < 32:
        raise ReceiptError("ROOT_RECEIPT_KEY_UNAVAILABLE")
    return key


def _validate(message: Mapping[str, object], previous: RootAnchor) -> None:
    _anchor(previous)
    if set(message) != FIELDS or message["format"] != FORMAT:
        raise ReceiptError("ROOT_RECEIPT_INVALID")
    _name(message["scope"])
    _name(message["key_id"])
    for name in ("root", "previous_root", "previous_receipt", "segment"):
        _hash(message[name])
    if (type(message["generation"]) is not int
            or message["generation"] > MAX_GENERATION
            or message["generation"] != previous.generation + 1
            or message["scope"] != previous.scope
            or message["previous_root"] != previous.root
            or message["previous_receipt"] != previous.receipt_sha256):
        raise ReceiptError("ROOT_PREDECESSOR_MISMATCH")
    if message["root"] == previous.root:
        raise ReceiptError("ROOT_GENERATION_NO_CHANGE")
    try:
        timestamp = datetime.fromisoformat(cast(str, message["published_at"]))
    except (TypeError, ValueError):
        raise ReceiptError("ROOT_RECEIPT_CLOCK_INVALID") from None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ReceiptError("ROOT_RECEIPT_CLOCK_INVALID")


def sign(previous: RootAnchor, root: str, segment: str, published_at: datetime,
         key_id: str, key: bytes) -> SignedReceipt:
    """Seal one proposed generation; archive/root CAS remains mandatory."""
    message: dict[str, object] = {
        "format": FORMAT, "scope": previous.scope, "generation": previous.generation + 1,
        "root": root, "previous_root": previous.root,
        "previous_receipt": previous.receipt_sha256, "segment": segment,
        "published_at": published_at.isoformat(), "key_id": key_id}
    _validate(message, previous)
    signature = hmac.new(_key(key), _json(message), hashlib.sha256).hexdigest()
    data = _json({"message": message, "signature": signature})
    if len(data) > MAX_BYTES:
        raise ReceiptError("ROOT_RECEIPT_SIZE_LIMIT")
    anchor = RootAnchor(previous.scope, previous.generation + 1, root,
                        hashlib.sha256(data).hexdigest())
    return SignedReceipt(data, anchor)


def verify(data: bytes, trusted_sha256: str, previous: RootAnchor,
           keyring: Mapping[str, bytes]) -> RootAnchor:
    """Reject missing keys, altered bytes, wrong scope, replay and skipped generations."""
    _hash(trusted_sha256)
    if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_BYTES:
        raise ReceiptError("ROOT_RECEIPT_SIZE_LIMIT")
    if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), trusted_sha256):
        raise ReceiptError("ROOT_RECEIPT_DIGEST_MISMATCH")
    try:
        envelope = json.loads(data)
        if (not isinstance(envelope, dict) or set(envelope) != {"message", "signature"}
                or _json(envelope) != data or not isinstance(envelope["message"], dict)):
            raise ReceiptError("ROOT_RECEIPT_INVALID")
    except (UnicodeError, ValueError, TypeError):
        raise ReceiptError("ROOT_RECEIPT_INVALID") from None
    message: dict[str, object] = envelope["message"]
    _validate(message, previous)
    signature = _hash(envelope["signature"])
    key = _key(keyring.get(_name(message["key_id"])))
    expected = hmac.new(key, _json(message), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ReceiptError("ROOT_RECEIPT_SIGNATURE_MISMATCH")
    return RootAnchor(previous.scope, previous.generation + 1,
                      _hash(message["root"]), trusted_sha256)
