"""Disconnected guarded factory integration candidate; no production wiring.

A callback is an explicit caller-supplied bounded append on the SAME connection.
This adapter is not an arbitrary factory replacement or automatic retry engine.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TypeVar

import storage_write_guard as guard
from overnight_storage_contracts import ContractError, hash_id, name

T = TypeVar('T')


@dataclass(frozen=True)
class FactoryCoverage:
    expected: tuple[str, ...]
    verified: tuple[str, ...]
    inventory_sha256: str
    migration_sha256: str | None = None

    def blockers(self) -> tuple[str, ...]:
        hash_id(self.inventory_sha256)
        for writer in (*self.expected, *self.verified):
            name(writer)
        reasons: list[str] = []
        if (not self.expected or len(set(self.expected)) != len(self.expected)
                or len(set(self.verified)) != len(self.verified)
                or set(self.expected) != set(self.verified)):
            reasons.append('ALL_WRITER_INVENTORY_UNPROVEN')
        if self.migration_sha256 is None:
            reasons.append('FULL_FACTORY_MIGRATION_UNVERIFIED')
        else:
            hash_id(self.migration_sha256)
        return tuple(reasons)


def guarded_candidate(connection: guard.Connection, bound: guard.AppendBound,
                      append: Callable[[guard.Connection], T], *,
                      clock: Callable[[], datetime], coverage: FactoryCoverage) -> tuple[T, guard.GuardReceipt]:
    """Explicit isolated candidate only, never discovers or replaces a factory.

    Migration/inventory hashes are review references, not authentication or global
    commissioning. Success remains a single cooperating transaction receipt.
    """
    if coverage.blockers() or bound.writer not in coverage.verified:
        raise ContractError('FACTORY_INTEGRATION_REVIEW_BLOCKED')
    with guard.append_transaction(connection, bound, clock=clock) as receipt:
        result = append(connection)
    if receipt.status != 'COMMITTED':
        raise ContractError('FACTORY_COMMIT_UNCONFIRMED')
    return result, receipt
