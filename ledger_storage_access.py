"""Consistent legacy reads: archived history must never silently look hot-only.

No writes, schema setup, credential discovery or cached admission decisions.
The root check and source query share one repeatable-read snapshot so an archive
commit between them cannot produce a shortened apparently complete dataset.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager

from catalog_receipts import genesis
from ledger_archive_repository import Connection, begin_read_snapshot
from ledger_runtime_reader import LedgerReadError


def require_hot_only(connection: Connection) -> None:
    """Allow absence of storage, or the exact unarchived genesis; nothing else."""
    exists = connection.execute("""SELECT EXISTS(SELECT 1 FROM pg_namespace
        WHERE nspname='quant_storage')""").fetchone()
    if exists is None or len(exists) != 1 or type(exists[0]) is not bool:
        raise LedgerReadError('LEDGER_STORAGE_STATE_INVALID')
    if not exists[0]:
        return
    row = connection.execute("""SELECT scope,generation,root,receipt_sha256,
        previous_root,previous_receipt FROM quant_storage.catalog_roots
        WHERE scope='ledger'""").fetchone()
    if row is None or len(row) != 6 or type(row[1]) is not int or row[1] < 0:
        raise LedgerReadError('LEDGER_STORAGE_STATE_INVALID')
    if row[1] > 0:
        raise LedgerReadError('LEDGER_COLD_READER_REQUIRED')
    anchor = genesis('ledger')
    if tuple(row) != (anchor.scope, anchor.generation, anchor.root,
                     anchor.receipt_sha256, None, None):
        raise LedgerReadError('LEDGER_STORAGE_STATE_INVALID')


@contextmanager
def hot_read(connect: Callable[[], AbstractContextManager[Connection]]) -> Iterator[Connection]:
    """Bounded, read-only legacy snapshot; never HTTP, commit or fall through."""
    try:
        with connect() as connection:
            try:
                begin_read_snapshot(connection)
                require_hot_only(connection)
                yield connection
            finally:
                connection.rollback()
    except LedgerReadError:
        raise
    except Exception:
        raise LedgerReadError('LEDGER_HOT_SNAPSHOT_UNVERIFIED') from None
