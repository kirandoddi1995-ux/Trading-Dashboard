"""Deterministic sealed-ledger verification, real local append format, no network."""
import copy
import datetime as dt
import hashlib
import hmac
import sqlite3
import zlib
import uuid

import pytest

from evidence_ledger import GENESIS_HASH, ImmutableEvidenceLedger, canonical_json
from ledger_segments import LEGACY_KEY_ID, SegmentError, restore, seal, verify_records

KEY = b"fixture-event-key-not-production"
SEAL_KEY = b"fixture-archive-sealing-key-only!"


@pytest.fixture
def events(tmp_path, monkeypatch):
    monkeypatch.setattr("evidence_ledger._utcnow", lambda: dt.datetime(
        2026, 10, 5, 0, 0, tzinfo=dt.timezone.utc))
    ledger = ImmutableEvidenceLedger(sqlite3.connect, str(tmp_path / "ledger.sqlite"), KEY)
    for i in range(4):
        ledger.append(aggregate_id="fixture", event_type="DECISION_EVALUATED",
                      payload={"fixture": i, "nested": {"value": "original"}},
                      idempotency_key=f"test-{i}")
    rows = ledger.events("fixture")
    return rows, {rows[0]["key_id"]: KEY}


def test_round_trip_matches_real_ledger_and_is_deterministic(events):
    rows, ring = events
    segment = seal(rows, {}, ring, SEAL_KEY)
    assert segment == seal(rows, {}, ring, SEAL_KEY)
    restored, heads = restore(segment.data, segment.sha256, {}, ring, SEAL_KEY)
    expected = [{k: v for k, v in row.items() if k != "duplicate"} for row in rows]
    assert restored == expected
    assert heads["fixture"] == (4, rows[-1]["event_hash"])
    with pytest.raises(TypeError):
        segment.heads["fixture"] = (0, GENESIS_HASH)


def test_native_postgres_uuid_round_trips_without_rehashing(events):
    rows, ring = events
    native = [dict(row, event_id=uuid.UUID(row['event_id'])) for row in rows]
    original = seal(rows, {}, ring, SEAL_KEY)
    assert seal(native, {}, ring, SEAL_KEY) == original


def test_event_id_does_not_stringify_arbitrary_objects(events):
    rows, ring = events
    with pytest.raises(SegmentError, match='INVALID_EVENT_FIELD'):
        seal([dict(rows[0], event_id=object())], {}, ring, SEAL_KEY)


def test_archive_live_boundary_and_later_segment(events):
    rows, ring = events
    first = seal(rows[:2], {}, ring, SEAL_KEY)
    second = seal(rows[2:], first.heads, ring, SEAL_KEY)
    restored, heads = restore(second.data, second.sha256, first.heads, ring, SEAL_KEY)
    assert restored[0]["sequence_no"] == 3 and heads["fixture"][0] == 4
    with pytest.raises(SegmentError, match="BROKEN_EVENT_CHAIN"):
        restore(second.data, second.sha256, {}, ring, SEAL_KEY)


@pytest.mark.parametrize("mutation,code", [
    (lambda r: r[0]["payload"].update(fixture=999), "EVENT_SIGNATURE_MISMATCH"),
    (lambda r: r[1].update(sequence_no=3), "BROKEN_EVENT_CHAIN"),
    (lambda r: r[0].update(previous_hash="a"*64), "BROKEN_EVENT_CHAIN"),
    (lambda r: r[0].update(key_id="unknown"), "SIGNING_KEY_UNAVAILABLE"),
    (lambda r: r[0].update(recorded_at="2026-10-05T00:00:00"), "NAIVE_TIMESTAMP"),
    (lambda r: r[0].update(schema_version=3), "UNSUPPORTED_LEDGER_VERSION"),
    (lambda r: r[0].update(sequence_no=True), "INVALID_SEQUENCE"),
    (lambda r: r[0].update(hash_algorithm="MD5"), "UNSUPPORTED_HASH_ALGORITHM"),
    (lambda r: r[0].update(extra="lost evidence"), "EVENT_SCHEMA_MISMATCH"),
])
def test_original_evidence_is_never_rehashed_to_hide_failure(events, mutation, code):
    rows, ring = events
    changed = copy.deepcopy(rows)
    mutation(changed)
    with pytest.raises(SegmentError, match=code):
        seal(changed, {}, ring, SEAL_KEY)


def test_missing_old_signature_key_does_not_fall_back(events):
    rows, _ring = events
    with pytest.raises(SegmentError, match="SIGNING_KEY_UNAVAILABLE"):
        seal(rows, {}, {}, SEAL_KEY)


def test_legacy_v1_matches_existing_material_not_v2(events):
    rows, ring = events
    row = dict(rows[0], schema_version=1)
    kwargs = {k: row[k] for k in (
        "event_id", "aggregate_id", "sequence_no", "event_type", "recorded_at",
        "effective_at", "source", "actor_id", "idempotency_key", "previous_hash",
        "hash_algorithm", "schema_version", "key_id")}
    kwargs["payload_json"] = canonical_json(row["payload"])
    row["event_hash"] = hmac.new(KEY, ImmutableEvidenceLedger._material(
        **kwargs).encode(), hashlib.sha256).hexdigest()
    segment = seal([row], {}, ring, SEAL_KEY)
    assert restore(segment.data, segment.sha256, {}, ring, SEAL_KEY)[0][0]["event_hash"] == row["event_hash"]


def test_unsigned_history_retains_explicit_integrity_mode(events):
    rows, _ring = events
    row = dict(rows[0], hash_algorithm="SHA256 hash chain", key_id="unsigned")
    kwargs = {k: row[k] for k in (
        "event_id", "aggregate_id", "sequence_no", "event_type", "recorded_at",
        "effective_at", "source", "actor_id", "idempotency_key", "previous_hash",
        "hash_algorithm", "schema_version", "key_id")}
    kwargs["payload_json"] = canonical_json(row["payload"])
    row["event_hash"] = hashlib.sha256(ImmutableEvidenceLedger._material(**kwargs).encode()).hexdigest()
    segment = seal([row], {}, {}, SEAL_KEY)
    assert restore(segment.data, segment.sha256, {}, {}, SEAL_KEY)[0][0]["hash_algorithm"] == "SHA256 hash chain"


def test_legacy_missing_key_id_requires_explicit_legacy_binding(events):
    rows, current_ring = events
    row = dict(rows[0], schema_version=1, key_id=None)
    kwargs = {k: row[k] for k in (
        "event_id", "aggregate_id", "sequence_no", "event_type", "recorded_at",
        "effective_at", "source", "actor_id", "idempotency_key", "previous_hash",
        "hash_algorithm", "schema_version", "key_id")}
    kwargs["payload_json"] = canonical_json(row["payload"])
    row["event_hash"] = hmac.new(KEY, ImmutableEvidenceLedger._material(**kwargs).encode(),
                                 hashlib.sha256).hexdigest()
    with pytest.raises(SegmentError, match="SIGNING_KEY_UNAVAILABLE"):
        seal([row], {}, current_ring, SEAL_KEY)
    ring = {LEGACY_KEY_ID: KEY}
    segment = seal([row], {}, ring, SEAL_KEY)
    assert restore(segment.data, segment.sha256, {}, ring, SEAL_KEY)[0][0]["key_id"] is None


def test_tampered_or_wrongly_pinned_file_is_rejected(events):
    rows, ring = events
    segment = seal(rows, {}, ring, SEAL_KEY)
    with pytest.raises(SegmentError, match="SEGMENT_DIGEST_MISMATCH"):
        restore(segment.data + b"x", segment.sha256, {}, ring, SEAL_KEY)
    with pytest.raises(SegmentError, match="ARCHIVE_SEAL_MISMATCH"):
        restore(segment.data, segment.sha256, {}, ring, b"x"*32)


def test_invalid_envelope_even_with_matching_file_digest(events):
    _rows, ring = events
    data = zlib.compress(b"not JSON")
    with pytest.raises(SegmentError, match="INVALID_COMPRESSION"):
        restore(data, hashlib.sha256(data).hexdigest(), {}, ring, SEAL_KEY)


def test_bounds_and_no_concatenated_gzip(events, monkeypatch):
    rows, ring = events
    segment = seal(rows, {}, ring, SEAL_KEY)
    doubled = segment.data + segment.data
    with pytest.raises(SegmentError, match="UNBOUNDED_OR_TRAILING_SEGMENT"):
        restore(doubled, hashlib.sha256(doubled).hexdigest(), {}, ring, SEAL_KEY)
    monkeypatch.setattr("ledger_segments.MAX_RAW_BYTES", 32)
    with pytest.raises(SegmentError, match="UNBOUNDED_OR_TRAILING_SEGMENT"):
        restore(segment.data, segment.sha256, {}, ring, SEAL_KEY)
    with pytest.raises(SegmentError, match="SEGMENT_TOO_LARGE"):
        seal(rows, {}, ring, SEAL_KEY)


@pytest.mark.parametrize("rows", [[], [{}]*2001])
def test_empty_or_excess_rows_block(rows):
    with pytest.raises(SegmentError):
        seal(rows, {}, {}, SEAL_KEY)


def test_duplicate_identity_across_aggregates_blocks(events):
    rows, ring = events
    second = dict(rows[0], aggregate_id="other")
    kwargs = {k: second[k] for k in (
        "event_id", "aggregate_id", "sequence_no", "event_type", "recorded_at",
        "effective_at", "source", "actor_id", "idempotency_key", "previous_hash",
        "hash_algorithm", "schema_version", "key_id")}
    kwargs["payload_json"] = canonical_json(second["payload"])
    second["event_hash"] = hmac.new(KEY, ImmutableEvidenceLedger._material(**kwargs).encode(),
                                  hashlib.sha256).hexdigest()
    with pytest.raises(SegmentError, match="DUPLICATE_EVENT_IDENTITY"):
        verify_records([rows[0], second], {}, ring)


@pytest.mark.parametrize("head", [(-1, GENESIS_HASH), (True, GENESIS_HASH), (0, "a"*64)])
def test_invalid_predecessor_anchor_blocks(events, head):
    rows, ring = events
    with pytest.raises(SegmentError, match="INVALID_HEAD|INVALID_GENESIS"):
        verify_records(rows, {"fixture": head}, ring)


def test_short_sealing_key_rejected(events):
    rows, ring = events
    with pytest.raises(SegmentError, match="ARCHIVE_SEAL_KEY_TOO_SHORT"):
        seal(rows, {}, ring, b"short")


def test_seal_rejects_oversized_input_before_copying_or_parsing(monkeypatch):
    import ledger_segments
    from collections.abc import Sequence
    class Oversized(Sequence):
        def __len__(self):
            return ledger_segments.MAX_ROWS + 1
        def __getitem__(self, index):
            raise AssertionError('Oversized input must not be traversed')
    with pytest.raises(SegmentError, match='INVALID_ROW_COUNT'):
        seal(Oversized(), {}, {}, SEAL_KEY)

