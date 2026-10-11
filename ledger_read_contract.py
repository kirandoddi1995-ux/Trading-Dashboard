"""Small SQL/immutable-object read contracts, without archive or delete code."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol

Kind = Literal['ledger-segment', 'catalog-page', 'root-receipt']


class Result(Protocol):
    """Minimal positional readback interface, shared with disposable SQL tests."""
    def fetchone(self) -> Sequence[object] | None: ...

    def fetchall(self) -> Sequence[Sequence[object]]: ...


class Connection(Protocol):
    """Injected driver lifecycle; no credentials or connection creation here."""
    def execute(self, query: str, params: Sequence[object] = ()) -> Result: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class ColdObjects(Protocol):
    """Read-only content-addressed namespace; unavailable is never verified absence."""
    def get(self, kind: Kind, digest: str) -> bytes | None: ...


def begin_read_snapshot(connection: Connection) -> None:
    """Use bounded repeatable-read isolation; always roll back in caller finally.

    An already-queried transaction cannot silently retain weaker isolation: SET
    TRANSACTION must succeed. Finish the snapshot before external object requests.
    """
    for query in ('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY',
                  'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY',
                  "SET LOCAL transaction_timeout='15s'",
                  "SET LOCAL statement_timeout='10s'", "SET LOCAL lock_timeout='2s'",
                  "SET LOCAL TimeZone='UTC'"):
        connection.execute(query)
