"""Exhaustively verified, bounded adapters for original-ledger consumers.

Explicitly injected source and protected spool directory only. No live factory,
credential discovery, SQL writes, network setup, training or trading authority.
Every call pins its own source cut; related reads should share history() instead.
"""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Protocol

from evidence_ledger import canonical_json
from ledger_history_stream import VerifiedHistory

MAX_RESULT_ROWS = 20_000
MAX_RESULT_BYTES = 32 * 1024 * 1024


class ConsumerReadError(ValueError):
    """Redacted consumer failures; never shorter hot-only results on error."""


class StagedSource(Protocol):
    """A source must exhaust originals and its final root/head fence first."""

    def staged_history(self, private_parent: Path) -> AbstractContextManager[VerifiedHistory]: ...


def audit_history(history: VerifiedHistory) -> dict[str, object]:
    """Derive audit metadata from an already verified cut, never re-read its source.

    This does not authenticate a caller-constructed witness or authorize trading.
    Consumers must obtain history through the complete staging contract.
    """
    witness = history.witness
    return {'verified': True, 'broken_links': 0, 'duplicate_sequences': 0,
            'events': witness.rows, 'history_sha256': witness.sha256,
            'hmac_events': witness.hmac_events,
            'unsigned_events': witness.unsigned_events,
            'signature_coverage_complete': witness.rows > 0 and witness.unsigned_events == 0,
            'scope': 'ORIGINAL_HOT_AND_COLD_CONTINUITY',
            'approval_authority': False}


class LedgerHistoryConsumers:
    """History, continuity, retry and pair APIs over the SAME staged contract."""

    def __init__(self, source: StagedSource, private_parent: Path):
        if not isinstance(private_parent, Path):
            raise ConsumerReadError('CONSUMER_PRIVATE_PARENT_REQUIRED')
        self._source = source
        self._private_parent = private_parent

    @contextmanager
    def history(self) -> Iterator[VerifiedHistory]:
        """One verified cut for related operations; no partial history exposure."""
        body_error: BaseException | None = None
        try:
            with self._source.staged_history(self._private_parent) as history:
                try:
                    yield history
                except BaseException as error:
                    # Some source context managers redact exceptions raised by
                    # their caller too. Preserve our caller's own exception;
                    # source acquisition/verification failures remain redacted.
                    body_error = error
                    raise
        except BaseException as source_error:
            if body_error is not None:
                raise body_error from None
            if not isinstance(source_error, Exception) or isinstance(source_error, ConsumerReadError):
                raise
            raise ConsumerReadError('CONSUMER_HISTORY_UNAVAILABLE') from None
        # A misbehaving source __exit__ must not turn a reader bound, projection
        # error or interruption into an apparently successful shorter result.
        if body_error is not None:
            raise body_error from None

    def verified_events(self) -> Iterator[dict[str, object]]:
        """Stream all originals, but only AFTER the complete cut is verified."""
        with self.history() as history:
            yield from history.rows()

    def events(self, aggregate: str) -> list[dict[str, object]]:
        """Compatibility list for one aggregate with explicit memory bounds."""
        self._identity(aggregate)
        rows: list[dict[str, object]] = []
        total = 0
        with self.history() as history:
            for row in history.rows():
                if row['aggregate_id'] != aggregate:
                    continue
                total += len(canonical_json(row).encode())
                if len(rows) >= MAX_RESULT_ROWS or total > MAX_RESULT_BYTES:
                    raise ConsumerReadError('CONSUMER_RESULT_REQUIRES_STREAMING')
                rows.append(row)
        return rows

    def duplicate(self, idempotency_key: str) -> Mapping[str, object] | None:
        """Original retry or authenticated absence, never unavailable-as-absent."""
        self._identity(idempotency_key)
        with self.history() as history:
            # Global uniqueness and the complete cut already passed the stage.
            return history.duplicate(idempotency_key)

    def decision_pairs(self, *, include_unmatured: bool = False,
                       first_outcome: bool = False) -> Iterator[
                           tuple[dict[str, object], dict[str, object] | None]]:
        """Original SQL join semantics without accumulating all payloads."""
        if type(include_unmatured) is not bool or type(first_outcome) is not bool:
            raise ConsumerReadError('CONSUMER_PAIR_FLAGS_INVALID')
        with self.history() as history:
            yield from history.decision_pairs(include_unmatured=include_unmatured,
                                              first_outcome=first_outcome)

    def audit(self) -> dict[str, object]:
        """Separate verified continuity from complete original HMAC coverage."""
        with self.history() as history:
            return audit_history(history)

    @staticmethod
    def _identity(value: str) -> None:
        """Reject malformed caller identifiers, including non-string booleans."""
        if not isinstance(value, str) or not 1 <= len(value.encode()) <= 900:
            raise ConsumerReadError('CONSUMER_IDENTITY_INVALID')
