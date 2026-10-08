"""Private-copy audit protocol with synthetic fixture folders only."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
from typing import Any

import pytest

import recovery_replica_audit as audit
import recovery_export as export
from test_recovery_export import prepare, contract, AUTH
from test_local_state_recovery import source as _source_fixture, KEY, KEY_ID

source = _source_fixture


def copies(generation: export.PreparedGeneration, parent: Path) -> tuple[audit.ExtractedCopy, ...]:
    for name in ('drive', 'external_disk'):
        shutil.copytree(generation.directory, parent / name)
    return tuple(audit.ExtractedCopy(name, parent / name) for name in ('drive', 'external_disk'))


def verify(generation: export.PreparedGeneration, replicas: tuple[audit.ExtractedCopy, ...],
           parent: Path, **changes: Any) -> dict[str, object]:
    args: dict[str, Any] = dict(checkpoint=generation.signed.checkpoint, contract=contract(),
        keys={'auth': AUTH}, original_keys={KEY_ID: KEY}, spool_parent=parent)
    args.update(changes)
    return audit.verify_copies(generation, replicas, **args)


def test_both_real_readbacks_but_not_commissioned_independence(source: Path, tmp_path: Path) -> None:
    generation = prepare(source, tmp_path / 'source_export')
    replicas = copies(generation, tmp_path)
    result = verify(generation, replicas, tmp_path)
    assert result['status'] == 'EXTRACTED_REPLICA_IDENTITIES_VERIFIED'
    assert result['original_signatures_verified'] is True
    for name in ('encryption_verified', 'physical_independence_verified',
                 'trusted_checkpoint_durability_verified', 'application_recovery_verified',
                 'hot_deletion_authority', 'approval_authority'):
        assert result[name] is False
    assert str(replicas[0].directory) not in repr(replicas[0])


@pytest.mark.parametrize('damage', ['missing', 'image', 'manifest', 'extra', 'keys', 'original_keys', 'checkpoint'])
def test_replica_damage_never_passes(source: Path, tmp_path: Path, damage: str) -> None:
    generation = prepare(source, tmp_path / 'source_export')
    replicas = copies(generation, tmp_path)
    changes: dict[str, Any] = {}
    target = replicas[1].directory
    if damage == 'missing':
        (target / export.IMAGE).unlink()
    elif damage == 'image':
        (target / export.IMAGE).write_bytes(b'corrupt synthetic image')
    elif damage == 'manifest':
        (target / export.MANIFEST).write_bytes(b'{}')
    elif damage == 'extra':
        (target / 'unexpected').write_bytes(b'x')
    elif damage in ('keys', 'original_keys'):
        changes[damage] = {}
    else:
        changes['checkpoint'] = replace(generation.signed.checkpoint,
                                        current=generation.signed.checkpoint.previous)
    with pytest.raises(audit.ReplicaError):
        verify(generation, replicas, tmp_path, **changes)
    assert generation.directory.is_dir() and target.is_dir()


@pytest.mark.parametrize('damage', ['one_copy', 'same_name', 'same_path', 'source_path', 'wrong_destination'])
def test_false_replica_topology_rejected(source: Path, tmp_path: Path, damage: str) -> None:
    generation = prepare(source, tmp_path / 'source_export')
    replicas = copies(generation, tmp_path)
    if damage == 'one_copy':
        replicas = replicas[:1]
    elif damage == 'same_name':
        replicas = (replicas[0], replace(replicas[1], name='drive'))
    elif damage == 'same_path':
        replicas = (replicas[0], replace(replicas[1], directory=replicas[0].directory))
    elif damage == 'source_path':
        replicas = (replace(replicas[0], directory=generation.directory), replicas[1])
    else:
        replicas = (replace(replicas[0], name='unreviewed'), replicas[1])
    with pytest.raises(audit.ReplicaError):
        verify(generation, replicas, tmp_path)


def test_other_generation_not_mistaken_for_same_content(source: Path, tmp_path: Path) -> None:
    generation = prepare(source, tmp_path / 'source_export')
    replicas = copies(generation, tmp_path)
    other = prepare(source, tmp_path / 'other', bundle_id='00000000-0000-4000-8000-000000000009')
    (replicas[1].directory / export.MANIFEST).write_bytes(other.signed.data)
    with pytest.raises(audit.ReplicaError):
        verify(generation, replicas, tmp_path)


def test_source_changed_during_audit_blocks(source: Path, tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    generation = prepare(source, tmp_path / 'source_export')
    replicas = copies(generation, tmp_path)
    real = export.verify_generation
    calls = 0
    def changed(*args: Any, **kwargs: Any) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 3:
            (generation.directory / export.MANIFEST).write_bytes(b'{}')
        return real(*args, **kwargs)
    monkeypatch.setattr(export, 'verify_generation', changed)
    with pytest.raises(audit.ReplicaError):
        verify(generation, replicas, tmp_path)
