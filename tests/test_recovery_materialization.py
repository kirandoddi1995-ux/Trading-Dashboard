"""Detached synthetic restores only. No installed state, market files or network."""
from __future__ import annotations

from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from typing import Any, cast

import pytest

import finalization_intents
import local_state_recovery as state
import recovery_materialization as restore
import recovery_export as export
from test_recovery_six_export import contract, initialize, prepare, source as _source_fixture
from test_recovery_export import AUTH
from test_local_state_recovery import KEY, KEY_ID

source = _source_fixture


def options(generation: export.PreparedGeneration, parent: Path) -> dict[str, Any]:
    return dict(checkpoint=generation.signed.checkpoint, contract=contract(),
        keys={'auth': AUTH}, original_keys={KEY_ID: KEY}, spool_parent=parent)


def checkpoint(run: str, instrument: str, token: int) -> state.RemoteProof:
    return state.RemoteProof(state.ProofState.PRESENT, dict(run_id=run, instrument=instrument,
        fencing_token=token, result=None, rejection={'category': 'Trend'},
        quote_observed_at=None, governance_decision_at=None, item='ABC'), token)


def lookups() -> restore.RemoteLookups:
    return restore.RemoteLookups(lambda _: state.RemoteProof(state.ProofState.ABSENT),
        checkpoint, lambda _, token: state.RemoteProof(state.ProofState.ABSENT, active_fence=token))


def test_restore_reopens_all_six_and_preserves_pending(source: Path, tmp_path: Path) -> None:
    initialize(source)
    generation = prepare(source, tmp_path / 'generation')
    before = {p.name: p.read_bytes() for p in generation.directory.iterdir()}
    target = restore.materialize(generation, tmp_path / 'restore', **options(generation, tmp_path))
    assert {p.name: p.read_bytes() for p in target.directory.iterdir()} == before
    with closing(sqlite3.connect(target.directory / export.IMAGE)) as conn:
        assert conn.execute(f'SELECT acknowledged_at FROM {finalization_intents.TABLE}').fetchone() == (None,)
    result = restore.review_remote_contract(target, **options(generation, tmp_path), lookups=lookups())
    assert result['status'] == 'RESTORED_SIX_TABLE_REMOTE_CONTRACT_REVIEWED'
    assert result['pending_intents'] == 1
    assert result['remote_adapter_authentication_verified'] is False
    assert result['application_recovery_verified'] is False
    assert result['hot_deletion_authority'] is False
    assert {p.name: p.read_bytes() for p in generation.directory.iterdir()} == before


@pytest.mark.parametrize('damage', ['image', 'witness', 'key', 'checkpoint'])
def test_authentication_before_target_creation(source: Path, tmp_path: Path, damage: str) -> None:
    initialize(source)
    generation = prepare(source, tmp_path / 'generation')
    args = options(generation, tmp_path)
    if damage in ('image', 'witness'):
        name = export.IMAGE if damage == 'image' else export.SIX_WITNESS
        (generation.directory / name).write_bytes(b'corrupt')
    elif damage == 'key':
        args['original_keys'] = {}
    else:
        args['checkpoint'] = replace(generation.signed.checkpoint, current=generation.signed.checkpoint.previous)
    with pytest.raises(restore.MaterializationError):
        restore.materialize(generation, tmp_path / 'restore', **args)
    assert not (tmp_path / 'restore').exists()


def test_existing_and_nested_target_never_overwritten(source: Path, tmp_path: Path) -> None:
    initialize(source)
    generation = prepare(source, tmp_path / 'generation')
    target = tmp_path / 'restore'
    target.mkdir()
    (target / 'keep').write_bytes(b'original')
    for location in (target, generation.directory / 'nested'):
        with pytest.raises(restore.MaterializationError):
            restore.materialize(generation, location, **options(generation, tmp_path))
    assert (target / 'keep').read_bytes() == b'original'


def test_failure_retains_partial_without_reset_or_retry(source: Path, tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    initialize(source)
    generation = prepare(source, tmp_path / 'generation')
    copy = restore._copy
    def fail(before: Path, after: Path, limit: int, deadline: float) -> None:
        if before.name == export.MANIFEST:
            raise OSError('PRIVATE driver detail not for output')
        copy(before, after, limit, deadline)
    monkeypatch.setattr(restore, '_copy', fail)
    with pytest.raises(restore.MaterializationError, match='STOP_RETAIN_PARTIAL_TARGET') as error:
        restore.materialize(generation, tmp_path / 'restore', **options(generation, tmp_path))
    assert 'PRIVATE' not in str(error.value)
    assert (tmp_path / 'restore' / export.IMAGE).exists()
    with pytest.raises(restore.MaterializationError, match='NEW_TARGET_REQUIRED'):
        restore.materialize(generation, tmp_path / 'restore', **options(generation, tmp_path))


@pytest.mark.parametrize('kind', ['unavailable', 'wrong_request', 'stale_fence', 'exception', 'bad_type'])
def test_remote_failure_never_mutates_restored_state(source: Path, tmp_path: Path, kind: str) -> None:
    initialize(source)
    generation = prepare(source, tmp_path / 'generation')
    target = restore.materialize(generation, tmp_path / 'restore', **options(generation, tmp_path))
    before = (target.directory / export.IMAGE).read_bytes()
    def bad(run: str, token: int) -> state.RemoteProof:
        if kind == 'exception':
            raise RuntimeError('PRIVATE provider message')
        if kind == 'bad_type':
            return cast(state.RemoteProof, None)
        return state.RemoteProof(state.ProofState.UNAVAILABLE if kind == 'unavailable'
            else state.ProofState.PRESENT, {} if kind == 'wrong_request' else None,
            token + 1 if kind == 'stale_fence' else token)
    with pytest.raises(restore.MaterializationError, match='REMOTE_CONTRACT_UNVERIFIED') as error:
        restore.review_remote_contract(target, **options(generation, tmp_path),
            lookups=replace(lookups(), run=bad))
    assert 'PRIVATE' not in str(error.value)
    assert (target.directory / export.IMAGE).read_bytes() == before


def test_unknown_commit_preserved_until_original_proof_and_atomic_ack(source: Path, tmp_path: Path) -> None:
    initialize(source)
    generation = prepare(source, tmp_path / 'generation')
    target = restore.materialize(generation, tmp_path / 'restore', **options(generation, tmp_path))
    with closing(sqlite3.connect(target.directory / export.IMAGE)) as conn:
        request = json.loads(conn.execute(f'SELECT request_json FROM {finalization_intents.TABLE}').fetchone()[0])
    callbacks = replace(lookups(), run=lambda _, token: state.RemoteProof(state.ProofState.PRESENT, request, token))
    result = restore.review_remote_contract(target, **options(generation, tmp_path), lookups=callbacks)
    assert result['remote_committed_pending_intent_ack'] == 1
    with closing(sqlite3.connect(target.directory / export.IMAGE)) as conn:
        assert conn.execute(f'SELECT acknowledged_at FROM {finalization_intents.TABLE}').fetchone() == (None,)
        assert conn.execute('SELECT remote_finalized_token FROM durable_scan_jobs').fetchone() == (None,)


def test_copy_deadline_and_size_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / 'source'
    source.write_bytes(b'1234')
    with pytest.raises(restore.MaterializationError, match='SIZE_BOUND'):
        restore._copy(source, tmp_path / 'large', 3, float('inf'))
    monkeypatch.setattr('recovery_materialization.time.monotonic', lambda: 2.0)
    with pytest.raises(restore.MaterializationError, match='TIME_BOUND'):
        restore._copy(source, tmp_path / 'late', 4, 1.0)
    assert (tmp_path / 'late').exists()


@pytest.mark.parametrize('kind', ['relative', 'missing_parent', 'five_tables'])
def test_explicit_restore_destination_and_six_tables_required(
        source: Path, tmp_path: Path, kind: str) -> None:
    initialize(source)
    generation = prepare(source, tmp_path / 'generation')
    args = options(generation, tmp_path)
    target = tmp_path / 'restore'
    if kind == 'relative':
        target = Path('relative-restore')
    elif kind == 'missing_parent':
        target = tmp_path / 'absent' / 'restore'
    else:
        args['contract'] = replace(contract(), bindings=contract().bindings[:1])
    with pytest.raises(restore.MaterializationError):
        restore.materialize(generation, target, **args)
    assert not (tmp_path / 'restore').exists()
    assert not (tmp_path / 'absent').exists()


@pytest.mark.parametrize('where', ['source', 'target'])
def test_mutation_during_copy_cannot_produce_success(
        source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str) -> None:
    initialize(source)
    generation = prepare(source, tmp_path / 'generation')
    copy = restore._copy
    def mutate(before: Path, after: Path, limit: int, deadline: float) -> None:
        copy(before, after, limit, deadline)
        if before.name == export.SIX_WITNESS:
            directory = before.parent if where == 'source' else after.parent
            (directory / export.IMAGE).write_bytes(b'changed during copy')
    monkeypatch.setattr(restore, '_copy', mutate)
    with pytest.raises(restore.MaterializationError):
        restore.materialize(generation, tmp_path / 'restore', **options(generation, tmp_path))
    assert (tmp_path / 'restore' / export.IMAGE).exists()


def test_callback_mutation_of_restored_image_blocks_review(source: Path, tmp_path: Path) -> None:
    initialize(source)
    generation = prepare(source, tmp_path / 'generation')
    target = restore.materialize(generation, tmp_path / 'restore', **options(generation, tmp_path))
    def mutate(_: str) -> state.RemoteProof:
        (target.directory / export.IMAGE).write_bytes(b'callback replaced image')
        return state.RemoteProof(state.ProofState.ABSENT)
    with pytest.raises(restore.MaterializationError):
        restore.review_remote_contract(target, **options(generation, tmp_path),
            lookups=replace(lookups(), evidence=mutate))


def test_delivered_checkpoint_cannot_be_reinterpreted_as_absent(source: Path, tmp_path: Path) -> None:
    initialize(source)
    generation = prepare(source, tmp_path / 'generation')
    absent = lambda _run, _instrument, token: state.RemoteProof(state.ProofState.ABSENT, active_fence=token)
    with pytest.raises(restore.MaterializationError, match='REMOTE_CONTRACT_UNVERIFIED'):
        restore.review_remote_contract(generation, **options(generation, tmp_path),
            lookups=replace(lookups(), checkpoint=absent))


def test_copy_refuses_overwrite_without_truncating(tmp_path: Path) -> None:
    source = tmp_path / 'source'
    target = tmp_path / 'target'
    source.write_bytes(b'new')
    target.write_bytes(b'keep')
    with pytest.raises(FileExistsError):
        restore._copy(source, target, 10, float('inf'))
    assert target.read_bytes() == b'keep'
