"""Explicit read-only historical repository factory; no automatic live activation.

Caller owns private paths, licensed GET transport, original keys and protected SQL
commissioning. No environment/credential discovery, database connect at construction,
schema installation, signing-key lookup, archive deletion or order placement.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import cast

from ledger_historical_views import LedgerHistoricalViews
from ledger_history_consumers import LedgerHistoryConsumers
from ledger_history_stream import VerifiedHistory
from ledger_read_contract import ColdObjects, Connection
from ledger_runtime_reader import LedgerRuntimeReader
from production_repository import ProductionRepository


class HistoricalFactoryError(ValueError):
    """Explicit configuration failure, never a fallback to a hot-only factory."""


class _BoundSource:
    """Break construction's callback cycle without exposing an unbound reader."""

    def __init__(self) -> None:
        self.reader: LedgerRuntimeReader | None = None

    @contextmanager
    def staged_history(self, private_parent: Path) -> Iterator[VerifiedHistory]:
        if self.reader is None:
            raise HistoricalFactoryError('HISTORICAL_SOURCE_NOT_BOUND')
        with self.reader.staged_history(private_parent) as history:
            yield history


def read_only_repository(*, database_url: str, objects: ColdObjects,
                         event_keys: Mapping[str, bytes], seal_key: bytes,
                         receipt_keys: Mapping[str, bytes],
                         private_parent: Path) -> ProductionRepository:
    """Construct views whose reader validates the SAME repository database.

    No independent second URL/source can be paired with another repository's
    health check. Both source snapshots and schema/role checks use repo.connect,
    which the staged public candidate makes read-only in this explicit mode.
    Current app/collector factories remain unchanged and do NOT call this function.
    This requires the separately reviewed candidate ProductionRepository interface;
    it is not compatible with the old public hot-only constructor.
    """
    if (not isinstance(database_url, str) or not database_url.strip()
            or not isinstance(private_parent, Path) or not private_parent.is_absolute()
            or not private_parent.is_dir()
            or any(item.is_symlink() or item.is_junction() for item in (private_parent, *private_parent.parents))):
        raise HistoricalFactoryError('HISTORICAL_EXPLICIT_PRIVATE_CONFIG_REQUIRED')
    source = _BoundSource()
    views = LedgerHistoricalViews(LedgerHistoryConsumers(source, private_parent))
    repository = ProductionRepository(database_url, evidence_signing_key=b'', schema_mode='validate',
                                      enforce_restricted_role=True, historical_views=views)
    # psycopg connections implement the small read-only positional driver contract.
    connect = cast(Callable[[], AbstractContextManager[Connection]], repository.connect)
    source.reader = LedgerRuntimeReader(connect, objects, dict(event_keys), seal_key, dict(receipt_keys))
    return repository
