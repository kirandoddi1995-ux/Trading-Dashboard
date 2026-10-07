"""Offline disposable exports/checkpoint restart, never installed private state."""
from __future__ import annotations

from contextlib import closing
from dataclasses import replace
import datetime as dt
from pathlib import Path
import sqlite3
from typing import Any

import pytest

import recovery_bundle as bundle
import recovery_export as export
from test_local_state_recovery import source as _source_fixture, KEY, KEY_ID

source = _source_fixture

AUTH = b'synthetic-separate-export-custody-key'
AT = dt.datetime(2026, 10, 8, tzinfo=dt.timezone.utc)


def contract() -> bundle.BackupContract:
    return bundle.BackupContract('backup:synthetic_export', (
        bundle.Binding('primary_state', 'sqlite_source', 'sqlite-image-v1'),))


def prepare(source: Path, directory: Path, **changes: Any) -> export.PreparedGeneration:
    args: dict[str, Any] = dict(contract=contract(), previous=bundle.genesis(contract()),
        original_keys={KEY_ID: KEY}, key_id='auth', key=AUTH,
        bundle_id='00000000-0000-4000-8000-000000000001',
        cut_id='00000000-0000-4000-8000-000000000002', at=AT)
    args.update(changes)
    return export.prepare(source, directory, **args)


def commit(path: Path, generation: export.PreparedGeneration, parent: Path,
           **changes: Any) -> dict[str, object]:
    args: dict[str, Any] = dict(contract=contract(), keys={'auth': AUTH},
        original_keys={KEY_ID: KEY}, spool_parent=parent)
    args.update(changes)
    return export.commit(path, generation, **args)


def test_export_commit_restart_and_exact_retry(source: Path, tmp_path: Path) -> None:
    original = source.read_bytes()
    generation = prepare(source, tmp_path / 'generation')
    assert source.read_bytes() == original
    assert {p.name for p in generation.directory.iterdir()} == {export.IMAGE, export.MANIFEST}
    assert not list(tmp_path.glob('local-recovery-*'))
    assert str(generation.directory) not in repr(generation)
    store = tmp_path / 'independent.sqlite'
    export.create_custody(store, contract=contract())
    result = commit(store, generation, tmp_path)
    assert result['status'] == 'CUSTODY_LOCAL_CHECKPOINT_COMMITTED'
    assert result['generation'] == 1
    for name in ('approval_authority', 'independent_replica_verified',
                 'power_loss_recovery_verified', 'application_recovery_verified'):
        assert result[name] is False
    assert export.read_head(store, contract=contract()) == generation.signed.checkpoint.current
    assert commit(store, generation, tmp_path)['status'] == 'CUSTODY_EXACT_RETRY'


def test_second_generation_rejects_rollback_and_competing_successor(source: Path, tmp_path: Path) -> None:
    store = tmp_path / 'custody.sqlite'
    export.create_custody(store, contract=contract())
    first = prepare(source, tmp_path / 'first')
    commit(store, first, tmp_path)
    second = prepare(source, tmp_path / 'second', previous=first.signed.checkpoint.current,
        bundle_id='00000000-0000-4000-8000-000000000003')
    competing = prepare(source, tmp_path / 'competing', previous=first.signed.checkpoint.current,
        bundle_id='00000000-0000-4000-8000-000000000004')
    commit(store, second, tmp_path)
    for old in (first, competing):
        with pytest.raises(export.ExportError, match='STALE_PREDECESSOR'):
            commit(store, old, tmp_path)
    assert export.read_head(store, contract=contract()) == second.signed.checkpoint.current


@pytest.mark.parametrize('damage', ['manifest', 'image', 'missing', 'extra', 'key', 'original_key'])
def test_verification_failure_does_not_advance_head(source: Path, tmp_path: Path, damage: str) -> None:
    store = tmp_path / 'custody.sqlite'
    export.create_custody(store, contract=contract())
    generation = prepare(source, tmp_path / 'generation')
    changes: dict[str, Any] = {}
    if damage == 'manifest':
        (generation.directory / export.MANIFEST).write_bytes(b'{}')
    elif damage == 'image':
        with closing(sqlite3.connect(generation.directory / export.IMAGE)) as conn:
            conn.execute('CREATE TABLE not_in_witness(value TEXT)')
            conn.commit()
    elif damage == 'missing':
        (generation.directory / export.IMAGE).rename(generation.directory / 'wrong_name')
    elif damage == 'extra':
        (generation.directory / 'unfinished').write_bytes(b'partial')
    elif damage == 'key':
        changes['keys'] = {}
    else:
        changes['original_keys'] = {}
    with pytest.raises(export.ExportError):
        commit(store, generation, tmp_path, **changes)
    assert export.read_head(store, contract=contract()) == bundle.genesis(contract())


@pytest.mark.parametrize('changes', [{'original_keys': {}}, {'key': b'short'},
    {'at': dt.datetime(2026, 10, 8)}, {'bundle_id': 'bad'}, {'cut_id': 'bad'}])
def test_partial_generation_is_retained_and_never_reused(source: Path, tmp_path: Path,
                                                        changes: dict[str, Any]) -> None:
    directory = tmp_path / 'generation'
    with pytest.raises(export.ExportError):
        prepare(source, directory, **changes)
    assert directory.is_dir()
    assert not (directory / export.MANIFEST).exists()
    with pytest.raises(export.ExportError, match='NEW_GENERATION_REQUIRED'):
        prepare(source, directory)


def test_existing_targets_and_missing_sources_are_not_created_or_overwritten(source: Path, tmp_path: Path) -> None:
    directory = tmp_path / 'existing'
    directory.mkdir()
    (directory / 'keep').write_bytes(b'original')
    with pytest.raises(export.ExportError):
        prepare(source, directory)
    assert (directory / 'keep').read_bytes() == b'original'
    with pytest.raises(export.ExportError):
        prepare(tmp_path / 'missing.sqlite', tmp_path / 'new')
    assert not (tmp_path / 'missing.sqlite').exists()
    assert not (tmp_path / 'new').exists()
    store = tmp_path / 'store.sqlite'
    export.create_custody(store, contract=contract())
    before = store.read_bytes()
    with pytest.raises(export.ExportError, match='BOOTSTRAP_FAILED'):
        export.create_custody(store, contract=contract())
    assert store.read_bytes() == before


def test_multi_file_contract_is_blocked_before_export(source: Path, tmp_path: Path) -> None:
    extra = replace(contract(), bindings=(*contract().bindings,
        bundle.Binding('roots', 'catalog_source', 'catalog-roots-v1')))
    with pytest.raises(export.ExportError, match='CROSS_FILE_ADAPTER_REQUIRED'):
        prepare(source, tmp_path / 'generation', contract=extra)
    assert not (tmp_path / 'generation').exists()


@pytest.mark.parametrize('damage', ['missing', 'corrupt', 'contract', 'generation', 'root', 'genesis', 'schema', 'trigger'])
def test_custody_read_never_recreates_or_accepts_malformed_head(tmp_path: Path, damage: str) -> None:
    store = tmp_path / 'store.sqlite'
    if damage == 'missing':
        with pytest.raises(export.ExportError):
            export.read_head(store, contract=contract())
        assert not store.exists()
        return
    export.create_custody(store, contract=contract())
    if damage == 'corrupt':
        store.write_bytes(b'synthetic corrupt store')
    elif damage == 'schema':
        with closing(sqlite3.connect(store)) as conn:
            conn.execute('CREATE TABLE unexpected(value TEXT)')
    elif damage == 'trigger':
        with closing(sqlite3.connect(store)) as conn:
            conn.execute('CREATE TRIGGER sqlitex_unexpected AFTER UPDATE ON custody BEGIN SELECT 1; END')
    else:
        field, value = {'contract': ('contract', '{}'), 'generation': ('generation', -1),
            'root': ('root', 'bad'), 'genesis': ('root', 'a' * 64)}[damage]
        with closing(sqlite3.connect(store)) as conn:
            conn.execute(f'UPDATE custody SET {field}=?', (value,))  # Fixed test-only fields.
            conn.commit()
    before = store.read_bytes()
    with pytest.raises(export.ExportError):
        export.read_head(store, contract=contract())
    assert store.read_bytes() == before


def test_export_size_time_and_private_connection_failure(source: Path, tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bundle, 'MAX_ARTIFACT_BYTES', 1)
    with pytest.raises(export.ExportError, match='SIZE_BOUND'):
        prepare(source, tmp_path / 'size')
    monkeypatch.setattr(bundle, 'MAX_ARTIFACT_BYTES', 1024 * 1024 * 1024)
    monkeypatch.setattr(export, 'MAX_EXPORT_SECONDS', -1)
    with pytest.raises(export.ExportError, match='TIME_BOUND'):
        prepare(source, tmp_path / 'time')
    def fail(path: Path) -> sqlite3.Connection:
        raise OSError('PRIVATE_PATH_NEVER_PRINT')
    monkeypatch.setattr(export, '_readonly', fail)
    with pytest.raises(export.ExportError) as error:
        prepare(source, tmp_path / 'driver')
    assert 'PRIVATE' not in str(error.value)
    assert error.value.__suppress_context__


def test_failed_sync_keeps_partial_and_custody_genesis(source: Path, tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / 'store.sqlite'
    export.create_custody(store, contract=contract())
    def fail(path: Path) -> None:
        raise OSError('private filesystem failure')
    monkeypatch.setattr(export, '_sync', fail)
    with pytest.raises(export.ExportError):
        prepare(source, tmp_path / 'generation')
    assert export.read_head(store, contract=contract()) == bundle.genesis(contract())


def test_wal_writer_does_not_mix_pinned_snapshot(source: Path, tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    with closing(sqlite3.connect(source)) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
    readonly = export._readonly
    changed = False
    class Connection(sqlite3.Connection):
        def backup(self, target: sqlite3.Connection, **kwargs: Any) -> None:
            nonlocal changed
            original = kwargs['progress']
            def progress(status: int, remaining: int, total: int) -> None:
                nonlocal changed
                if not changed:
                    with closing(sqlite3.connect(source)) as writer:
                        writer.execute("UPDATE durable_scan_jobs SET owner='later'")
                        writer.commit()
                    changed = True
                original(status, remaining, total)
            super().backup(target, **{**kwargs, 'pages': 1, 'progress': progress})
    def connect(path: Path) -> sqlite3.Connection:
        if path == source.resolve():
            return sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, factory=Connection)
        return readonly(path)
    monkeypatch.setattr(export, '_readonly', connect)
    generation = prepare(source, tmp_path / 'generation')
    assert changed
    with closing(sqlite3.connect(generation.directory / export.IMAGE)) as conn:
        assert conn.execute('SELECT owner FROM durable_scan_jobs').fetchone()[0] == 'owner'
    with closing(sqlite3.connect(source)) as conn:
        assert conn.execute('SELECT owner FROM durable_scan_jobs').fetchone()[0] == 'later'


def test_lock_refuses_commit_without_changing_head(source: Path, tmp_path: Path) -> None:
    store = tmp_path / 'store.sqlite'
    export.create_custody(store, contract=contract())
    generation = prepare(source, tmp_path / 'generation')
    with closing(sqlite3.connect(store)) as locker:
        locker.execute('BEGIN IMMEDIATE')
        with pytest.raises(export.ExportError, match='COMMIT_UNCERTAIN'):
            commit(store, generation, tmp_path)
    assert export.read_head(store, contract=contract()) == bundle.genesis(contract())


def test_lost_commit_response_exact_retry_is_safe(source: Path, tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / 'store.sqlite'
    export.create_custody(store, contract=contract())
    generation = prepare(source, tmp_path / 'generation')
    read = export.read_head
    def unavailable(path: Path, *, contract: bundle.BackupContract) -> Any:
        raise OSError('private post-commit read failure')
    monkeypatch.setattr(export, 'read_head', unavailable)
    with pytest.raises(export.ExportError, match='COMMIT_UNCERTAIN'):
        commit(store, generation, tmp_path)
    monkeypatch.setattr(export, 'read_head', read)
    assert read(store, contract=contract()) == generation.signed.checkpoint.current
    assert commit(store, generation, tmp_path)['status'] == 'CUSTODY_EXACT_RETRY'


def test_custody_inside_generation_is_not_independent(source: Path, tmp_path: Path) -> None:
    generation = prepare(source, tmp_path / 'generation')
    store = generation.directory / 'custody.sqlite'
    export.create_custody(store, contract=contract())
    with pytest.raises(export.ExportError, match='NOT_SEPARATE'):
        commit(store, generation, tmp_path)


def test_directory_link_refused_without_following(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Deterministic Windows reparse guard without admin symlink creation.
    monkeypatch.setattr(Path, 'is_junction', lambda self: True)
    with pytest.raises(export.ExportError, match='BOOTSTRAP_FAILED'):
        export.create_custody(tmp_path / 'store.sqlite', contract=contract())


@pytest.mark.parametrize('damage', ['oversize', 'duplicate', 'false_receipt'])
def test_bounded_custody_rows_and_anchor_validation(tmp_path: Path, damage: str,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / 'store.sqlite'
    export.create_custody(store, contract=contract())
    if damage == 'oversize':
        monkeypatch.setattr(export, 'MAX_CUSTODY_BYTES', 1)
    else:
        with closing(sqlite3.connect(store)) as conn:
            if damage == 'duplicate':
                conn.execute('PRAGMA ignore_check_constraints=ON')
                conn.execute('INSERT INTO custody SELECT 2,contract,generation,root,receipt_sha FROM custody')
            else:
                conn.execute('UPDATE custody SET generation=1')
            conn.commit()
    with pytest.raises(export.ExportError):
        export.read_head(store, contract=contract())


def test_integrity_outside_five_tables_is_required(source: Path, tmp_path: Path) -> None:
    with closing(sqlite3.connect(source)) as conn:
        conn.execute('CREATE TABLE auxiliary(value INTEGER CHECK(value>0))')
        conn.execute('PRAGMA ignore_check_constraints=ON')
        conn.execute('INSERT INTO auxiliary VALUES(-1)')
        conn.commit()
    with pytest.raises(export.ExportError, match='INTEGRITY_UNVERIFIED'):
        prepare(source, tmp_path / 'generation')
    assert not (tmp_path / 'generation' / export.MANIFEST).exists()


def test_wrong_proposed_metadata_never_advances_head(source: Path, tmp_path: Path) -> None:
    store = tmp_path / 'store.sqlite'
    export.create_custody(store, contract=contract())
    generation = prepare(source, tmp_path / 'generation')
    different = replace(generation, signed=replace(generation.signed, data=b'{}'))
    with pytest.raises(export.ExportError, match='GENERATION_MISMATCH'):
        commit(store, different, tmp_path)
    assert export.read_head(store, contract=contract()) == bundle.genesis(contract())
