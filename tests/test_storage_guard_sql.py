"""Exact guard SQL on disposable PostgreSQL; not a multi-connection race proof."""
from __future__ import annotations

from datetime import datetime
import os
from typing import Any, Iterator

import pytest

import storage_write_guard as guard
from test_archive_maintenance_sql import Pg


@pytest.fixture
def guard_db() -> Iterator[Any]:
    if not os.environ.get('EQUITY_TEST_PGLITE_MODULE'):
        pytest.fail('Configure the existing offline PostgreSQL harness; do not skip guard SQL')
    factory: Any = Pg  # Public existing harness, not a network/credential fixture.
    db: Any = factory()
    try:
        yield db
    finally:
        db.send({'close': True})
        db.process.stdin.close()
        db.process.wait(timeout=10)


def test_exact_lock_fence_names_transaction_and_current_backend_lock(guard_db: Any) -> None:
    guard_db.execute('BEGIN')
    guard_db.execute("SET LOCAL statement_timeout='10s'")
    guard_db.execute("SET LOCAL lock_timeout='2s'")
    guard_db.execute("SET LOCAL transaction_timeout='30s'")
    assert guard_db.execute(guard.LOCK_SQL).fetchone() == (True,)
    first = guard_db.execute(guard.FENCE_SQL).fetchone()
    assert isinstance(first[0], str) and int(first[0]) > 0
    # PGlite has no real backend PID (0, pg_locks.pid NULL). Do NOT weaken the
    # production fence to accept an unowned lock merely to make WASM pass.
    pid = guard_db.execute('SELECT pg_catalog.pg_backend_pid()').fetchone()[0]
    assert pid == 0 and first[1] is False
    locks = guard_db.execute("""SELECT classid,objid,objsubid,granted FROM pg_catalog.pg_locks
        WHERE locktype='advisory'""").fetchall()
    assert locks == [(77261008, 1, 2, True)]
    assert guard_db.execute(guard.FENCE_SQL).fetchone() == first
    guard_db.execute('ROLLBACK')
    guard_db.execute('BEGIN')
    second = guard_db.execute(guard.FENCE_SQL).fetchone()
    assert second[0] != first[0] and second[1] is False
    guard_db.execute('ROLLBACK')


def test_exact_measurement_sql_exposes_owner_privilege_for_rejection(guard_db: Any) -> None:
    guard_db.execute('BEGIN READ ONLY')
    result = guard_db.execute(guard.MEASURE_SQL).fetchone()
    assert len(result) == 4 and datetime.fromisoformat(result[0]).utcoffset() is not None
    assert int(result[1]) > 0 and type(result[2]) is bool and type(result[3]) is bool
    assert result[2] is True  # Harness owner is NOT acceptable as a production writer.
    guard_db.execute('ROLLBACK')


def test_commit_releases_transaction_lock_without_explicit_unlock(guard_db: Any) -> None:
    guard_db.execute('BEGIN')
    guard_db.execute(guard.LOCK_SQL)
    assert guard_db.execute("SELECT count(*) FROM pg_catalog.pg_locks WHERE locktype='advisory'").fetchone() == (1,)
    guard_db.execute('COMMIT')
    guard_db.execute('BEGIN')
    assert guard_db.execute(guard.FENCE_SQL).fetchone()[1] is False
    assert guard_db.execute("SELECT count(*) FROM pg_catalog.pg_locks WHERE locktype='advisory'").fetchone() == (0,)
    guard_db.execute('ROLLBACK')
