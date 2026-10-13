"""Durable local SYNTHETIC orchestration journal; never operations/alert state.

Explicit initialization only, no discovery. Durable replay identity is bounded
metadata; injected failures preserve staged evidence. SQLite is not native PG
concurrency acceptance nor proof of physical durability on faulty hardware.
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Iterator

from overnight_storage_contracts import ContractError, digest, hash_id, name

MAX_RECORDS = 4096
MAX_METADATA = 8192
MAX_PAGES = 4096
STAGES = ('STAGED', 'VERIFIED', 'REVIEWED')
APPLICATION_ID = 0x4F53544A


class Journal:
    """Caller-owned synthetic file; monotonically fenced compare-and-swap."""
    def __init__(self, path: Path, *, initialize: bool = False,
                 inject: Callable[[str], None] = lambda phase: None) -> None:
        if (not path.is_absolute() or not path.name.startswith('overnight_storage_')
                or path.suffix != '.sqlite'
                or any(p.is_symlink() or p.is_junction() for p in (path, *path.parents))):
            raise ContractError('JOURNAL_SYNTHETIC_PATH_REQUIRED')
        if initialize == path.exists():
            raise ContractError('JOURNAL_EXPLICIT_NEW_OR_EXISTING_REQUIRED')
        self.path = path
        self.inject = inject
        if initialize:
            with self._connect(new=True) as connection:
                connection.execute(f'PRAGMA application_id={APPLICATION_ID}')
                connection.execute('CREATE TABLE control (id INTEGER PRIMARY KEY CHECK(id=1), fence INTEGER NOT NULL)')
                connection.execute('INSERT INTO control VALUES (1, 0)')
                connection.execute('CREATE TABLE records (identity TEXT PRIMARY KEY, request TEXT NOT NULL, '
                                   'metadata BLOB NOT NULL, stage TEXT NOT NULL, revision INTEGER NOT NULL)')

    @contextmanager
    def _connect(self, *, new: bool = False) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            mode = 'rwc' if new else 'rw'
            connection = sqlite3.connect(self.path.as_uri() + '?mode=' + mode, uri=True, timeout=0)
            connection.execute('PRAGMA journal_mode=DELETE')
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute(f'PRAGMA max_page_count={MAX_PAGES}')
            if not new and connection.execute('PRAGMA application_id').fetchone() != (APPLICATION_ID,):
                raise ContractError('JOURNAL_FORMAT_INVALID')
            connection.execute('BEGIN IMMEDIATE')
            yield connection
            self.inject('before_commit')
            connection.commit()
            self.inject('after_commit')
        except ContractError:
            if connection is not None:
                connection.rollback()
            raise
        except Exception:
            if connection is not None:
                connection.rollback()
            raise ContractError('JOURNAL_UNCONFIRMED_RECONCILE') from None
        finally:
            if connection is not None:
                connection.close()

    def claim(self, expected_fence: int) -> int:
        if type(expected_fence) is not int or expected_fence < 0:
            raise ContractError('JOURNAL_FENCE_INVALID')
        with self._connect() as connection:
            changed = connection.execute('UPDATE control SET fence=fence+1 WHERE id=1 AND fence=?',
                                         (expected_fence,)).rowcount
            if changed != 1:
                raise ContractError('JOURNAL_FENCE_LOST')
        return expected_fence + 1

    def stage(self, identity: str, metadata: bytes, *, fence: int) -> str:
        name(identity)
        if type(metadata) is not bytes or not 0 < len(metadata) <= MAX_METADATA:
            raise ContractError('JOURNAL_METADATA_BOUND')
        request = digest(metadata)
        with self._connect() as connection:
            self._fence(connection, fence)
            row = connection.execute('SELECT request,metadata FROM records WHERE identity=?', (identity,)).fetchone()
            if row is not None:
                if row != (request, metadata):
                    raise ContractError('JOURNAL_IDEMPOTENCE_CONFLICT')
                return request
            if connection.execute('SELECT count(*) FROM records').fetchone()[0] >= MAX_RECORDS:
                raise ContractError('JOURNAL_RECORD_BOUND')
            connection.execute('INSERT INTO records VALUES (?,?,?,\'STAGED\',0)', (identity, request, metadata))
            self.inject('after_stage')
        return request

    def advance(self, identity: str, request: str, *, fence: int,
                expected_revision: int, stage: str) -> int:
        name(identity)
        hash_id(request)
        if type(expected_revision) is not int or not 0 <= expected_revision < 2 or stage != STAGES[expected_revision + 1]:
            raise ContractError('JOURNAL_TRANSITION_INVALID')
        with self._connect() as connection:
            self._fence(connection, fence)
            changed = connection.execute('UPDATE records SET stage=?, revision=revision+1 '
                'WHERE identity=? AND request=? AND revision=? AND stage=?',
                (stage, identity, request, expected_revision, STAGES[expected_revision])).rowcount
            if changed != 1:
                raise ContractError('JOURNAL_REVISION_OR_REQUEST_CHANGED')
            self.inject('after_advance')
        return expected_revision + 1

    def lookup(self, identity: str) -> tuple[str, str, int] | None:
        name(identity)
        with self._connect() as connection:
            row = connection.execute('SELECT request,metadata,stage,revision FROM records WHERE identity=?',
                                     (identity,)).fetchone()
            if row is None:
                return None
            request, metadata, stage, revision = row
            if (type(metadata) is not bytes or not 0 < len(metadata) <= MAX_METADATA
                    or digest(metadata) != request or type(revision) is not int
                    or not 0 <= revision < len(STAGES) or stage != STAGES[revision]):
                raise ContractError('JOURNAL_CORRUPT_RECORD')
            hash_id(request)
            return request, stage, revision

    @staticmethod
    def _fence(connection: sqlite3.Connection, fence: int) -> None:
        if type(fence) is not int or fence < 1 or connection.execute(
                'SELECT fence FROM control WHERE id=1').fetchone() != (fence,):
            raise ContractError('JOURNAL_FENCE_LOST')


def metadata_bytes(value: dict[str, object]) -> bytes:
    """Canonical deterministic request identity, no mutable source content."""
    try:
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    except (ValueError, TypeError):
        raise ContractError('JOURNAL_METADATA_INVALID') from None
    if len(raw) > MAX_METADATA:
        raise ContractError('JOURNAL_METADATA_BOUND')
    return raw
