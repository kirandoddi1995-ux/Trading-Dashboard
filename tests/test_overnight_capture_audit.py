"""Synthetic replay/readback coverage; no installed state or provider calls."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
from typing import Any, Callable, cast

import pytest

from forward_nifty_producer import prepare_config
from forward_versioned_producer import Producer, recipe
from overnight_capture_audit import (
    audit_bytes, audit_file, audit_lineage, audit_remote, audit_signed_remote,
    journal_bytes, restore_logical,
)
from research_integrity import IntegrityError, canonical, digest, hash_value


def make(tmp_path: Path) -> Producer:
    config = prepare_config('2022-01-03', 24900, 'a' * 64, '2022-01-03T08:45:00+05:30')
    return Producer(config, recipe(config, '2022-01-03T09:00:00+05:30'),
                    tmp_path / 'versioned-v1' / 'journal.sqlite')


def poll(producer: Producer, count: int, *, missing_prefix: bool = False) -> dict[str, Any]:
    opening = datetime.fromisoformat(producer.config['session_open'])
    at = opening + timedelta(minutes=count * 5, seconds=30)
    bars = [[(opening + timedelta(minutes=i * 5)).isoformat(), 25000 + i,
             25003 + i, 24998 + i, 25001 + i, 0, 0] for i in range(count)]
    if missing_prefix:
        bars = bars[1:]
    return cast(dict[str, Any], producer.record_poll(bars, received_at=at.isoformat(),
                                computed_clock=lambda: at + timedelta(seconds=1))['_versioned_bundle'])


class MemoryDownload:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.calls: list[str] = []

    def download(self, file_id: str) -> bytes:
        self.calls.append(file_id)
        return self.objects[file_id]


def remote(raw: bytes) -> MemoryDownload:
    generation = audit_bytes(raw)
    manifest = {'format': 'forward-versioned-manifest-v1', 'status': 'REMOTE_VERIFIED',
                'sha256': generation.sha256, 'spec_hash': generation.recipe_sha256,
                'data_file_id': 'data', 'recorded_decisions': generation.recorded_decisions,
                'training_eligible': False, 'approval_authority': False, 'fill_evidence': False}
    return MemoryDownload({'manifest': canonical(manifest), 'data': raw})


def test_local_journal_readback_and_logical_restore(tmp_path: Path) -> None:
    producer = make(tmp_path)
    bundle = poll(producer, 1)
    before = producer.path.read_bytes()
    raw = journal_bytes(producer.path, producer.config, producer.frozen)
    assert raw == canonical(bundle)
    assert producer.path.read_bytes() == before
    result = audit_bytes(raw)
    assert (result.raw_polls, result.recorded_decisions, result.missing_decisions) == (1, 1, 74)
    restored = restore_logical(raw, digest(raw))
    assert restored.original_bytes == raw and restored.writes == 0
    assert not restored.operational_resume_supported
    assert not restored.generation.training_eligible
    assert not restored.generation.approval_authority
    assert '25000' not in repr(restored)
    with pytest.raises(IntegrityError):
        restore_logical(raw, '0' * 64)


def test_missing_decisions_remain_missing(tmp_path: Path) -> None:
    bundle = poll(make(tmp_path), 3, missing_prefix=True)
    result = audit_bytes(canonical(bundle))
    assert result.raw_polls == 1 and result.recorded_decisions == 0 and result.missing_decisions == 75


@cast(Callable[[Callable[[Path, str], None]], Callable[[Path, str], None]],
      pytest.mark.parametrize('field', ['recorded_decisions', 'missing_decisions', 'approval_authority',
                                       'training_eligible', 'recipe', 'polls']))
def test_tampering_blocks(tmp_path: Path, field: str) -> None:
    bundle = deepcopy(poll(make(tmp_path), 1))
    if field == 'recipe':
        bundle[field]['sources']['forward_versioned_producer.py'] = '0' * 64
    elif field == 'polls':
        bundle[field][0]['source']['closed_bars'][0]['values'][3] += 1
    else:
        bundle[field] = True if 'authority' in field or 'eligible' in field else 10
    with pytest.raises(IntegrityError):
        audit_bytes(canonical(bundle))


def test_injected_readback_is_not_custody(tmp_path: Path) -> None:
    raw = canonical(poll(make(tmp_path), 1))
    transport = remote(raw)
    result = audit_remote(transport, 'manifest', digest(raw))
    assert transport.calls == ['manifest', 'data']
    assert result.scope == 'INJECTED_TRANSPORT_BYTES_REPLAYED'
    assert not result.remote_custody_verified and not result.independent_custody_verified
    assert result.policy_sha256 == hash_value(make(tmp_path).frozen['policy'])


@cast(Callable[[Callable[[Path, str], None]], Callable[[Path, str], None]],
      pytest.mark.parametrize('kind', ['wrong_pin', 'missing', 'data_tamper', 'count', 'spec', 'flags', 'duplicate_json']))
def test_remote_fail_closed(tmp_path: Path, kind: str) -> None:
    raw = canonical(poll(make(tmp_path), 1))
    transport = remote(raw)
    pin = digest(raw)
    if kind == 'wrong_pin':
        pin = '0' * 64
    elif kind == 'missing':
        del transport.objects['data']
    elif kind == 'data_tamper':
        transport.objects['data'] = raw + b' '
    elif kind == 'duplicate_json':
        transport.objects['manifest'] = b'{"sha256":1,"sha256":2}'
    else:
        import json
        manifest = json.loads(transport.objects['manifest'])
        if kind == 'count':
            manifest['recorded_decisions'] = True
        elif kind == 'spec':
            manifest['spec_hash'] = '0' * 64
        else:
            manifest['training_eligible'] = True
        transport.objects['manifest'] = canonical(manifest)
    with pytest.raises(IntegrityError, match='OVERNIGHT_REMOTE_READBACK_FAILED'):
        audit_remote(transport, 'manifest', pin)


def test_journal_missing_lock_and_hash_corruption(tmp_path: Path) -> None:
    producer = make(tmp_path)
    poll(producer, 1)
    with pytest.raises(IntegrityError):
        journal_bytes(tmp_path / 'missing.sqlite', producer.config, producer.frozen)
    assert not (tmp_path / 'missing.sqlite').exists()
    lock = producer.path.with_suffix('.producer-lock')
    lock.touch()
    with pytest.raises(IntegrityError):
        journal_bytes(producer.path, producer.config, producer.frozen)
    lock.unlink()
    with sqlite3.connect(producer.path) as conn:
        conn.execute('DROP TRIGGER polls_no_update')
        conn.execute("UPDATE polls SET sha='bad'")
        conn.execute("CREATE TRIGGER polls_no_update BEFORE UPDATE ON polls BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;")
    with pytest.raises(IntegrityError, match='CORRUPT'):
        journal_bytes(producer.path, producer.config, producer.frozen)


def test_explicit_file_adapter(tmp_path: Path) -> None:
    raw = canonical(make(tmp_path).bundle())
    path = tmp_path / 'overnight_capture_fixture.json'
    path.write_bytes(raw)
    assert audit_file(path).sha256 == digest(raw)
    path.write_bytes(b'{"format":"x","format":"y"}')
    with pytest.raises(IntegrityError):
        audit_file(path)


def test_append_only_generation_lineage(tmp_path: Path) -> None:
    producer = make(tmp_path)
    first = canonical(poll(producer, 1))
    second = canonical(poll(producer, 2))
    results = audit_lineage((first, second))
    assert [g.raw_polls for g in results] == [1, 2]
    assert results[0].sha256 != results[1].sha256
    for invalid in ((second, first), (first, first), ()):
        with pytest.raises(IntegrityError):
            audit_lineage(invalid)


def test_signed_exact_generation_custody_attestation(tmp_path: Path) -> None:
    """Fixed synthetic signing key, never a credential or trust anchor for production."""
    import json
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    raw = canonical(poll(make(tmp_path), 1))
    transport = remote(raw)
    manifest = json.loads(transport.objects['manifest'])
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = key.public_key().public_bytes_raw()
    checked_at = datetime.fromisoformat('2026-10-13T18:00:00+05:30')
    body = {'format': 'overnight-capture-custody-attestation-v1', 'manifest_id': 'manifest',
            'data_id': 'data', 'manifest_sha256': digest(transport.objects['manifest']),
            'generation_sha256': digest(raw), 'recipe_sha256': manifest['spec_hash'],
            'recorded_decisions': 1, 'signed_at': '2026-10-13T17:59:00+05:30',
            'expires_at': '2026-10-13T19:00:00+05:30', 'acl_evidence_sha256': 'e' * 64,
            'retention_evidence_sha256': 'f' * 64}

    def signed(value: dict[str, Any]) -> bytes:
        return canonical({'body': value, 'signature_hex': key.sign(canonical(value)).hex()})

    report = signed(body)
    result = audit_signed_remote(transport, 'manifest', digest(raw), report, public, checked_at=checked_at)
    assert result.signature_verified and result.report_sha256 == digest(report)
    assert result.signer_public_key_sha256 == digest(public)
    assert not result.generation.remote_custody_verified
    assert not result.generation.independent_custody_verified
    assert not result.generation.training_eligible and not result.generation.approval_authority
    assert transport.calls[-2:] == ['manifest', 'data']
    # Valid signature on incorrect claims still fails exact-generation binding.
    for field, wrong in (('generation_sha256', '0' * 64), ('manifest_sha256', '0' * 64),
                         ('recipe_sha256', '0' * 64), ('recorded_decisions', 2),
                         ('manifest_id', 'other'), ('data_id', 'other'),
                         ('expires_at', '2026-10-13T17:59:30+05:30')):
        altered = dict(body, **{field: wrong})
        with pytest.raises(IntegrityError, match='SIGNED_CUSTODY'):
            audit_signed_remote(transport, 'manifest', digest(raw), signed(altered), public, checked_at=checked_at)
    with pytest.raises(IntegrityError):
        audit_signed_remote(transport, 'manifest', digest(raw), report, bytes(32), checked_at=checked_at)
    envelope = json.loads(report)
    envelope['body']['acl_evidence_sha256'] = '0' * 64
    with pytest.raises(IntegrityError):
        audit_signed_remote(transport, 'manifest', digest(raw), canonical(envelope), public, checked_at=checked_at)
    with pytest.raises(IntegrityError):
        audit_signed_remote(transport, 'manifest', digest(raw), b'{"signature_verified":true}',
                            public, checked_at=checked_at)
