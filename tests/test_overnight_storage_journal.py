"""Synthetic local durability, fault injection and isolated guard candidate."""
from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

import storage_write_guard as guard
from overnight_storage_contracts import ContractError, digest
from overnight_storage_factory_adapter import FactoryCoverage, guarded_candidate
from overnight_storage_harness import START, SyntheticConnection
from overnight_storage_journal import Journal, metadata_bytes


def test_restart_replay_conflict_revision_and_fencing(tmp_path: Path) -> None:
    path = tmp_path / 'overnight_storage_restart.sqlite'
    first = Journal(path, initialize=True)
    fence = first.claim(0)
    raw = metadata_bytes({'generation': 1})
    request = first.stage('operation', raw, fence=fence)
    reopened = Journal(path)
    assert reopened.stage('operation', raw, fence=fence) == request
    with pytest.raises(ContractError, match='CONFLICT'):
        reopened.stage('operation', metadata_bytes({'generation': 2}), fence=fence)
    reopened.advance('operation', request, fence=fence, expected_revision=0, stage='VERIFIED')
    with pytest.raises(ContractError, match='REVISION'):
        first.advance('operation', request, fence=fence, expected_revision=0, stage='VERIFIED')
    new_fence = reopened.claim(fence)
    with pytest.raises(ContractError, match='FENCE_LOST'):
        first.advance('operation', request, fence=fence, expected_revision=1, stage='REVIEWED')
    reopened.advance('operation', request, fence=new_fence, expected_revision=1, stage='REVIEWED')
    assert Journal(path).lookup('operation') == (request, 'REVIEWED', 2)


@pytest.mark.parametrize('phase', ['after_stage', 'before_commit', 'after_commit'])
def test_fault_commit_reconciliation(tmp_path: Path, phase: str) -> None:
    path = tmp_path / 'overnight_storage_fault.sqlite'
    original = Journal(path, initialize=True)
    fence = original.claim(0)
    def inject(point: str) -> None:
        if point == phase:
            raise OSError('synthetic failure')
    failing = Journal(path, inject=inject)
    raw = metadata_bytes({'test': 'failure'})
    with pytest.raises(ContractError, match='UNCONFIRMED'):
        failing.stage('operation', raw, fence=fence)
    row = Journal(path).lookup('operation')
    assert (row is not None) == (phase == 'after_commit')
    if row is not None:
        assert row == (digest(raw), 'STAGED', 0)
    assert Journal(path).stage('operation', raw, fence=fence) == digest(raw)


def test_full_disk_actual_sqlite_bound_and_corrupt_record(tmp_path: Path) -> None:
    path = tmp_path / 'overnight_storage_full.sqlite'
    journal = Journal(path, initialize=True)
    fence = journal.claim(0)
    import overnight_storage_journal as module
    # Enforce SQLite's allocator limit, not only an injected exception.
    old = module.MAX_PAGES
    module.MAX_PAGES = 4
    try:
        with pytest.raises(ContractError, match='UNCONFIRMED'):
            for index in range(10):
                journal.stage(f'operation_{index}', b'x' * 8192, fence=fence)
    finally:
        module.MAX_PAGES = old
    request = journal.stage('corrupt', b'synthetic', fence=fence)
    assert request == digest(b'synthetic')
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE records SET metadata=? WHERE identity='corrupt'", (b'changed',))
    with pytest.raises(ContractError, match='CORRUPT'):
        journal.lookup('corrupt')


def test_explicit_synthetic_path_and_format(tmp_path: Path) -> None:
    with pytest.raises(ContractError, match='SYNTHETIC_PATH'):
        Journal(tmp_path / 'real.sqlite', initialize=True)
    path = tmp_path / 'overnight_storage_format.sqlite'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE other (x INTEGER)')
    journal = Journal(path)
    with pytest.raises(ContractError, match='FORMAT'):
        journal.lookup('operation')
    with pytest.raises(ContractError, match='EXPLICIT'):
        Journal(path, initialize=True)


@pytest.mark.parametrize('fault', ['', 'busy', 'fencing', 'full_disk', 'overrun', 'commit_reply_lost'])
def test_guarded_factory_candidate(fault: str) -> None:
    connection = SyntheticConnection(START, fault=fault)
    coverage = FactoryCoverage(('synthetic_writer',), ('synthetic_writer',),
                               digest(b'inventory'), digest(b'migration'))
    def append(supplied: guard.Connection) -> int:
        assert supplied is connection
        return connection.append()
    if fault:
        with pytest.raises((guard.GuardError, OSError)):
            guarded_candidate(connection, guard.AppendBound('synthetic_writer', 500_000), append,
                              clock=lambda: START, coverage=coverage)
        assert connection.commits == int(fault == 'commit_reply_lost')
    else:
        result, receipt = guarded_candidate(connection, guard.AppendBound('synthetic_writer', 500_000),
                                            append, clock=lambda: START, coverage=coverage)
        assert result == 3 and receipt.status == 'COMMITTED'
        assert not receipt.global_enforcement_commissioned


@pytest.mark.parametrize('coverage', [
    FactoryCoverage(('synthetic_writer',), (), digest(b'inventory')),
    FactoryCoverage(('synthetic_writer',), ('synthetic_writer',), digest(b'inventory')),
    FactoryCoverage(('synthetic_writer',), ('synthetic_writer', 'extra'), digest(b'inventory'), digest(b'migration')),
])
def test_unreviewed_factory_never_calls_append(coverage: FactoryCoverage) -> None:
    connection = SyntheticConnection(START)
    def forbidden(_: guard.Connection) -> int:
        pytest.fail('unreviewed append called')
    with pytest.raises(ContractError, match='REVIEW_BLOCKED'):
        guarded_candidate(connection, guard.AppendBound('synthetic_writer', 500_000), forbidden,
                          clock=lambda: START, coverage=coverage)
    assert connection.commits == 0 and connection.info.transaction_status == 0
