"""Offline receipt chain, rotation, rollback and malformed-input regressions."""
import datetime as dt
import hashlib
import json

import pytest

from catalog_receipts import (MAX_BYTES, MAX_GENERATION, ReceiptError, RootAnchor,
                              genesis, sign, verify)

NOW = dt.datetime(2026, 10, 6, tzinfo=dt.timezone.utc)
KEY = b"receipt-fixture-key-not-production" * 2
OTHER_KEY = b"rotated-receipt-fixture-key-only!" * 2


def receipt(previous=None, root="a" * 64, key_id="first", key=KEY):
    return sign(previous or genesis("ledger"), root, "b" * 64, NOW, key_id, key)


def test_two_generations_preserve_root_chain_and_explicit_rotation():
    initial = genesis("ledger")
    first = receipt(initial)
    anchor = verify(first.data, first.anchor.receipt_sha256, initial, {"first": KEY})
    second = receipt(anchor, "c" * 64, "rotated", OTHER_KEY)
    assert verify(second.data, second.anchor.receipt_sha256, anchor,
                  {"first": KEY, "rotated": OTHER_KEY}) == second.anchor
    assert second.anchor.generation == 2
    assert receipt(initial).data == first.data
    assert KEY not in first.data and OTHER_KEY not in second.data


def test_signed_old_root_is_not_accepted_against_latest_anchor():
    first = receipt()
    with pytest.raises(ReceiptError, match="PREDECESSOR_MISMATCH"):
        verify(first.data, first.anchor.receipt_sha256, first.anchor, {"first": KEY})


@pytest.mark.parametrize("previous", [genesis("other"),
    RootAnchor("ledger", 7, "a" * 64, "d" * 64)])
def test_wrong_scope_and_skipped_generation_block(previous):
    first = receipt()
    with pytest.raises(ReceiptError, match="PREDECESSOR_MISMATCH"):
        verify(first.data, first.anchor.receipt_sha256, previous, {"first": KEY})


def test_same_generation_competing_roots_need_exact_predecessor_receipt():
    first, competing = receipt(), receipt(root="e" * 64)
    next_receipt = receipt(first.anchor, "c" * 64)
    with pytest.raises(ReceiptError, match="PREDECESSOR_MISMATCH"):
        verify(next_receipt.data, next_receipt.anchor.receipt_sha256,
               competing.anchor, {"first": KEY})


def test_same_root_but_different_predecessor_receipt_cannot_substitute():
    first = receipt()
    competing = receipt(key_id="rotated", key=OTHER_KEY)
    assert first.anchor.root == competing.anchor.root
    assert first.anchor.receipt_sha256 != competing.anchor.receipt_sha256
    successor = receipt(first.anchor, "c" * 64)
    with pytest.raises(ReceiptError, match="PREDECESSOR_MISMATCH"):
        verify(successor.data, successor.anchor.receipt_sha256, competing.anchor, {"first": KEY})


@pytest.mark.parametrize("generation", [True, -1, MAX_GENERATION + 1])
def test_invalid_anchor_generation_is_never_coerced(generation):
    with pytest.raises(ReceiptError, match="ANCHOR_INVALID"):
        receipt(RootAnchor("ledger", generation, "a" * 64, "d" * 64), root="c" * 64)


def test_generation_cannot_overflow_database_bigint():
    with pytest.raises(ReceiptError, match="PREDECESSOR_MISMATCH"):
        receipt(RootAnchor("ledger", MAX_GENERATION, "a" * 64, "d" * 64), root="c" * 64)


def test_digest_signature_and_missing_key_are_distinct_failures():
    first = receipt()
    with pytest.raises(ReceiptError, match="DIGEST_MISMATCH"):
        verify(first.data + b" ", first.anchor.receipt_sha256, genesis("ledger"), {"first": KEY})
    with pytest.raises(ReceiptError, match="KEY_UNAVAILABLE"):
        verify(first.data, first.anchor.receipt_sha256, genesis("ledger"), {})
    with pytest.raises(ReceiptError, match="SIGNATURE_MISMATCH"):
        verify(first.data, first.anchor.receipt_sha256, genesis("ledger"), {"first": OTHER_KEY})


def test_rehashed_changed_message_still_needs_signature():
    first = receipt()
    envelope = json.loads(first.data)
    envelope["message"]["root"] = "f" * 64
    data = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(ReceiptError, match="SIGNATURE_MISMATCH"):
        verify(data, hashlib.sha256(data).hexdigest(), genesis("ledger"), {"first": KEY})


@pytest.mark.parametrize("data", [b"{}", b"null", b"\xff", b"[]", b"x" * (MAX_BYTES + 1)])
def test_malformed_and_oversized_bytes_block(data):
    with pytest.raises(ReceiptError):
        verify(data, hashlib.sha256(data).hexdigest(), genesis("ledger"), {"first": KEY})


def test_noop_naive_clock_weak_keys_and_invalid_bootstrap_block():
    with pytest.raises(ReceiptError, match="NO_CHANGE"):
        receipt(root=genesis("ledger").root)
    with pytest.raises(ReceiptError, match="CLOCK_INVALID"):
        sign(genesis("ledger"), "a" * 64, "b" * 64, NOW.replace(tzinfo=None), "first", KEY)
    with pytest.raises(ReceiptError, match="KEY_UNAVAILABLE"):
        receipt(key=b"short")
    with pytest.raises(ReceiptError, match="ANCHOR_INVALID"):
        receipt(RootAnchor("ledger", 0, "a" * 64, "0" * 64))
