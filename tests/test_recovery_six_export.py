"""Disposable six-table exports; no installed state, credentials or network."""
from __future__ import annotations

from contextlib import closing
from dataclasses import replace
from pathlib import Path
import shutil
import sqlite3
from typing import Any

import pytest

import finalization_intents
import recovery_bundle as bundle
import recovery_export as export
import recovery_six_binding as six
import recovery_proposal
import recovery_replica_audit as replica
from test_recovery_export import AUTH, prepare as prepare_five, source as _source_fixture
from test_local_state_recovery import KEY, KEY_ID

source = _source_fixture


def contract() -> bundle.BackupContract:
    return bundle.BackupContract('backup:synthetic_six_export', (
        bundle.Binding('primary_state', 'same_source', 'sqlite-image-v1'),
        bundle.Binding(six.NAME, 'same_source', 'derived-state-v1')))


def prepare(source: Path, directory: Path, **changes: Any) -> export.PreparedGeneration:
    selected = changes.pop('contract', contract())
    return prepare_five(source, directory, contract=selected,
                        previous=bundle.genesis(selected), **changes)


def initialize(path: Path) -> None:
    with closing(sqlite3.connect(path)) as conn:
        conn.execute('BEGIN IMMEDIATE')
        finalization_intents.initialize(conn)
        conn.execute('UPDATE checkpoint_outbox SET delivered_at=12')
        finalization_intents.queue_terminal(conn, run_id='run', fencing_token=1, at=13)
        conn.commit()


def verify(generation: export.PreparedGeneration, parent: Path, **changes: Any) -> bytes:
    args: dict[str, Any] = dict(checkpoint=generation.signed.checkpoint, contract=contract(),
        keys={'auth': AUTH}, original_keys={KEY_ID: KEY}, spool_parent=parent)
    args.update(changes)
    return export.verify_generation(generation.directory, **args)


def test_full_image_and_both_witnesses_survive_separate_copy(source: Path, tmp_path: Path) -> None:
    initialize(source)
    before = source.read_bytes()
    generation = prepare(source, tmp_path / 'generation', contract=contract())
    assert source.read_bytes() == before
    assert {p.name for p in generation.directory.iterdir()} == {
        export.IMAGE, export.MANIFEST, export.SIX_WITNESS}
    copied = tmp_path / 'separate-copy'
    shutil.copytree(generation.directory, copied)
    restored = replace(generation, directory=copied)
    assert verify(restored, tmp_path) == generation.signed.data
    head = tmp_path / 'custody.sqlite'
    export.create_custody(head, contract=contract())
    result = export.commit(head, restored, contract=contract(), keys={'auth': AUTH},
        original_keys={KEY_ID: KEY}, spool_parent=tmp_path)
    assert result['status'] == 'CUSTODY_LOCAL_CHECKPOINT_COMMITTED'
    assert result['independent_replica_verified'] is False
    assert result['application_recovery_verified'] is False
    assert result['approval_authority'] is False


@pytest.mark.parametrize('damage', ['sixth', 'metadata', 'manifest', 'extra', 'missing', 'key'])
def test_corruption_cannot_advance_custody(source: Path, tmp_path: Path, damage: str) -> None:
    initialize(source)
    generation = prepare(source, tmp_path / 'generation', contract=contract())
    head = tmp_path / 'custody.sqlite'
    export.create_custody(head, contract=contract())
    changes: dict[str, Any] = {}
    if damage == 'sixth':
        with closing(sqlite3.connect(generation.directory / export.IMAGE)) as conn:
            conn.execute(f'UPDATE {finalization_intents.TABLE} SET queued_at=14')
            conn.commit()
    elif damage == 'metadata':
        (generation.directory / export.SIX_WITNESS).write_bytes(b'{}')
    elif damage == 'manifest':
        (generation.directory / export.MANIFEST).write_bytes(b'{}')
    elif damage == 'extra':
        (generation.directory / 'primary.sqlite-wal').write_bytes(b'partial')
    elif damage == 'missing':
        (generation.directory / export.SIX_WITNESS).rename(generation.directory / 'wrong')
    else:
        changes['keys'] = {}
    with pytest.raises(export.ExportError):
        export.commit(head, generation, contract=contract(), keys=changes.get('keys', {'auth': AUTH}),
            original_keys={KEY_ID: KEY}, spool_parent=tmp_path)
    assert export.read_head(head, contract=contract()) == bundle.genesis(contract())


def test_missing_sixth_table_is_not_empty(source: Path, tmp_path: Path) -> None:
    with pytest.raises(export.ExportError):
        prepare(source, tmp_path / 'generation', contract=contract())
    assert not (tmp_path / 'generation' / export.MANIFEST).exists()


def test_unauthenticated_image_never_reaches_sqlite(source: Path, tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    initialize(source)
    generation = prepare(source, tmp_path / 'generation', contract=contract())
    (generation.directory / export.IMAGE).write_bytes(b'not SQLite')
    def forbidden(_: Path) -> None:
        pytest.fail('unauthenticated image opened')
    monkeypatch.setattr(export, '_integrity', forbidden)
    with pytest.raises(export.ExportError, match='IMAGE_DIGEST_MISMATCH'):
        verify(generation, tmp_path)


@pytest.mark.parametrize('change', ['source', 'format', 'extra'])
def test_cross_file_or_extra_contract_rejected_before_creation(source: Path, tmp_path: Path,
                                                               change: str) -> None:
    bindings = contract().bindings
    if change == 'source':
        bindings = (bindings[0], replace(bindings[1], source_id='different'))
    elif change == 'format':
        bindings = (bindings[0], replace(bindings[1], format='sqlite-image-v1'))
    else:
        bindings += (bundle.Binding('extra', 'same_source', 'derived-state-v1'),)
    with pytest.raises(export.ExportError, match='CROSS_FILE_ADAPTER_REQUIRED'):
        prepare(source, tmp_path / 'generation', contract=replace(contract(), bindings=bindings))
    assert not (tmp_path / 'generation').exists()


def test_wal_source_export_is_a_detached_generation(source: Path, tmp_path: Path) -> None:
    initialize(source)
    with closing(sqlite3.connect(source)) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        generation = prepare(source, tmp_path / 'generation', contract=contract())
        writer.execute(f'UPDATE {finalization_intents.TABLE} SET queued_at=14')
        writer.commit()
        assert verify(generation, tmp_path) == generation.signed.data
    with closing(sqlite3.connect(generation.directory / export.IMAGE)) as image:
        assert image.execute(f'SELECT queued_at FROM {finalization_intents.TABLE}').fetchone() == (13.0,)


def test_restart_and_two_extracted_copies_use_sixth_witness(source: Path, tmp_path: Path) -> None:
    initialize(source)
    generation = prepare(source, tmp_path / 'generation')
    custody = tmp_path / 'custody.sqlite'
    export.create_custody(custody, contract=contract())
    proposal = recovery_proposal.reload(generation.directory, custody,
        trusted_previous=bundle.genesis(contract()), contract=contract(), keys={'auth': AUTH},
        original_keys={KEY_ID: KEY}, spool_parent=tmp_path)
    assert proposal.status == 'PROPOSAL_READY_FOR_LOCAL_CAS'
    copies = tuple(replica.ExtractedCopy(name, tmp_path / name) for name in ('drive', 'external_disk'))
    for copy in copies:
        shutil.copytree(generation.directory, copy.directory)
    result = replica.verify_copies(generation, copies, checkpoint=generation.signed.checkpoint,
        contract=contract(), keys={'auth': AUTH}, original_keys={KEY_ID: KEY}, spool_parent=tmp_path)
    assert result['status'] == 'EXTRACTED_REPLICA_IDENTITIES_VERIFIED'
    assert result['physical_independence_verified'] is False
    assert result['encryption_verified'] is False
    (copies[1].directory / export.SIX_WITNESS).write_bytes(b'{}')
    with pytest.raises(replica.ReplicaError):
        replica.verify_copies(generation, copies, checkpoint=generation.signed.checkpoint,
            contract=contract(), keys={'auth': AUTH}, original_keys={KEY_ID: KEY}, spool_parent=tmp_path)
    assert export.read_head(custody, contract=contract()) == bundle.genesis(contract())


def test_interleaved_writer_cannot_mix_first_five_and_sixth(source: Path, tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    initialize(source)
    with closing(sqlite3.connect(source)) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
    original_connect = export._readonly
    changed = False
    class Connection(sqlite3.Connection):
        def backup(self, target: sqlite3.Connection, **kwargs: Any) -> None:
            original_progress = kwargs['progress']
            def progress(status: int, remaining: int, total: int) -> None:
                nonlocal changed
                if not changed:
                    with closing(sqlite3.connect(source)) as writer:
                        writer.execute('BEGIN IMMEDIATE')
                        writer.execute("UPDATE durable_scan_jobs SET owner='later'")
                        writer.execute(f'UPDATE {finalization_intents.TABLE} SET queued_at=14')
                        writer.commit()
                    changed = True
                original_progress(status, remaining, total)
            super().backup(target, **{**kwargs, 'pages': 1, 'progress': progress})
    def connect(path: Path) -> sqlite3.Connection:
        if path == source.resolve():
            return sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, factory=Connection)
        return original_connect(path)
    monkeypatch.setattr(export, '_readonly', connect)
    generation = prepare(source, tmp_path / 'generation')
    assert changed
    assert verify(generation, tmp_path) == generation.signed.data
    with closing(sqlite3.connect(generation.directory / export.IMAGE)) as image:
        assert image.execute('SELECT owner FROM durable_scan_jobs').fetchone() == ('owner',)
        assert image.execute(f'SELECT queued_at FROM {finalization_intents.TABLE}').fetchone() == (13.0,)
