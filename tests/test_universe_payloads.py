"""Synthetic byte-equivalence, identity and bounds for shadow normalization."""
from __future__ import annotations

from dataclasses import replace
from collections.abc import Iterator
import hashlib
from typing import Any, cast

import pytest

import universe_payloads as codec

HEADER = b'{"snapshot_date":"2024-01-02","observed_at":"2024-01-02T04:00:00Z"}'
RAW = b'{"lot_size":1,"name":"synthetic"}'
ROWS = (codec.Member('synthetic_a', b'{"symbol":"A"}', RAW),
        codec.Member('synthetic_b', b'{"symbol":"B"}', RAW))


def rebuild(snapshot: codec.ShadowSnapshot, **changes: Any) -> tuple[codec.Member, ...]:
    pool = {item.sha256: item.data for item in snapshot.payloads}
    args: dict[str, Any] = dict(get_payload=pool.__getitem__, expected_source_sha256=snapshot.source_sha256)
    args.update(changes)
    return codec.reconstruct(snapshot.header, snapshot.references, **args)


def test_lossless_round_trip_and_real_change() -> None:
    snapshot = codec.normalize(HEADER, ROWS)
    assert rebuild(snapshot) == ROWS
    assert len(snapshot.references) == 2 and len(snapshot.payloads) == 1
    assert snapshot.source_raw_bytes == 2 * len(RAW)
    assert snapshot.unique_raw_bytes == len(RAW)
    assert RAW.decode() not in repr(snapshot)
    assert 'synthetic_a' not in repr(snapshot)
    changed = codec.normalize(HEADER, (ROWS[0], replace(ROWS[1], raw=b'{"lot_size":2}')))
    assert len(changed.payloads) == 2
    assert changed.source_sha256 != snapshot.source_sha256


def test_payload_identity_shared_but_snapshot_identity_not_collapsed() -> None:
    first = codec.normalize(HEADER, ROWS)
    later = codec.normalize(b'{"snapshot_date":"2024-01-03"}', ROWS)
    assert first.payloads == later.payloads
    assert first.source_sha256 != later.source_sha256
    assert rebuild(later) == ROWS


def test_equivalent_json_is_not_silently_reformatted() -> None:
    rows = (ROWS[0], replace(ROWS[1], raw=b'{ "name":"synthetic", "lot_size":1 }'))
    snapshot = codec.normalize(HEADER, rows)
    assert len(snapshot.payloads) == 2
    assert rebuild(snapshot) == rows


@pytest.mark.parametrize('rows', [(), (ROWS[0], ROWS[0]),
    (replace(ROWS[0], instrument_key=''),), (replace(ROWS[0], instrument_key='x' * 257),),
    (replace(ROWS[0], fields=b''),), (replace(ROWS[0], raw=b''),),
    (replace(ROWS[0], raw=cast(Any, 'bad')),), (replace(ROWS[0], instrument_key='\ud800'),)])
def test_invalid_input(rows: Any) -> None:
    with pytest.raises(codec.PayloadError):
        codec.normalize(HEADER, rows)


@pytest.mark.parametrize('damage', ['missing', 'corrupt', 'fields', 'key', 'order', 'header', 'digest', 'missing_row'])
def test_bad_shadow_never_returns_partial_universe(damage: str) -> None:
    snapshot = codec.normalize(HEADER, ROWS)
    references = snapshot.references
    header = HEADER
    pool = {item.sha256: item.data for item in snapshot.payloads}
    if damage == 'missing':
        pool.clear()
    elif damage == 'corrupt':
        pool[references[0].raw_sha256] = b'bad'
    elif damage == 'fields':
        references = (replace(references[0], fields=b'changed'), references[1])
    elif damage == 'key':
        references = (replace(references[0], instrument_key='changed'), references[1])
    elif damage == 'order':
        references = references[::-1]
    elif damage == 'header':
        header = b'changed'
    elif damage == 'digest':
        references = (replace(references[0], raw_sha256='not a digest'), references[1])
    else:
        references = references[:1]
    with pytest.raises(codec.PayloadError):
        codec.reconstruct(header, references, get_payload=pool.__getitem__,
                          expected_source_sha256=snapshot.source_sha256)


def test_bounds_before_full_iterator_consumption(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(codec, 'MAX_ROWS', 1)
    with pytest.raises(codec.PayloadError, match='ROW_BOUND'):
        codec.normalize(HEADER, ROWS)
    monkeypatch.setattr(codec, 'MAX_ROWS', 10_000)
    monkeypatch.setattr(codec, 'MAX_VALUE_BYTES', len(RAW) - 1)
    with pytest.raises(codec.PayloadError, match='VALUE_BOUND'):
        codec.normalize(b'h', ROWS)
    monkeypatch.setattr(codec, 'MAX_VALUE_BYTES', 1024 * 1024)
    monkeypatch.setattr(codec, 'MAX_SNAPSHOT_BYTES', len(HEADER) + 1)
    with pytest.raises(codec.PayloadError, match='SNAPSHOT_BOUND'):
        codec.normalize(HEADER, ROWS)
    snapshot = codec.normalize(b'h', (codec.Member('a', b'f', b'r'),))
    monkeypatch.setattr(codec, 'MAX_SNAPSHOT_BYTES', 1)
    with pytest.raises(codec.PayloadError, match='SNAPSHOT_BOUND'):
        rebuild(snapshot)


def test_unicode_and_nul_are_preserved_not_logged() -> None:
    rows = (codec.Member('test_é', b'\x00column', '名字'.encode()),)
    assert rebuild(codec.normalize(b'header\x00', rows)) == rows


def test_ambiguous_concatenations_have_distinct_fingerprints() -> None:
    a = codec.normalize(b'h', (codec.Member('k', b'ab', b'c'),))
    b = codec.normalize(b'h', (codec.Member('k', b'a', b'bc'),))
    assert a.source_sha256 != b.source_sha256


def test_duplicate_reference_rejected() -> None:
    snapshot = codec.normalize(HEADER, ROWS)
    pool = {item.sha256: item.data for item in snapshot.payloads}
    with pytest.raises(codec.PayloadError, match='DUPLICATE'):
        codec.reconstruct(HEADER, (snapshot.references[0], snapshot.references[0]),
                          get_payload=pool.__getitem__, expected_source_sha256=snapshot.source_sha256)


def test_source_iterator_error_is_redacted() -> None:
    def failed() -> Iterator[codec.Member]:
        yield ROWS[0]
        raise RuntimeError('synthetic private provider detail')
    with pytest.raises(codec.PayloadError, match='SOURCE_UNAVAILABLE') as caught:
        codec.normalize(HEADER, failed())
    assert 'private' not in str(caught.value)


def test_hash_collision_is_not_assumed_impossible(monkeypatch: pytest.MonkeyPatch) -> None:
    class Collision:
        def hexdigest(self) -> str:
            return 'a' * 64
    monkeypatch.setattr(hashlib, 'sha256', lambda value: Collision())
    with pytest.raises(codec.PayloadError, match='DIGEST_COLLISION'):
        codec.normalize(HEADER, (ROWS[0], replace(ROWS[1], raw=b'changed')))
