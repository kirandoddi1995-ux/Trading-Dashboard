"""Synthetic authenticated query-result routing into unchanged repository readers.

This is an exact materialized-query fixture adapter, not a SQL engine or a proof
that arbitrary historical/business queries are covered. No hot fallback, network,
DSN discovery or production admission. One signed generation for the whole call.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime
import json
from typing import cast
import storage_write_guard as guard

from overnight_storage_contracts import Candidate, CatalogCut, ContractError, Tier, digest
from overnight_storage_harness import SyntheticConnection
from overnight_storage_repository_routes import RepositoryRoute
from overnight_storage_sources import SourceRouter
from overnight_storage_staged_factories import validate_result


def query_key(sql: str, parameters: Sequence[object] | Mapping[str, object] | None) -> str:
    validate_result(parameters)
    try:
        raw = json.dumps([' '.join(sql.split()), parameters], sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode()
    except (ValueError, TypeError):
        raise ContractError('COLD_QUERY_PARAMETER_CODEC_UNSUPPORTED') from None
    return digest(raw)


def rowset_bytes(sql: str, parameters: Sequence[object] | Mapping[str, object] | None,
                 rows: Sequence[Sequence[object]]) -> bytes:
    validate_result(list(rows))
    try:
        return json.dumps({'query': query_key(sql, parameters), 'rows': rows},
                          sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    except (ValueError, TypeError):
        raise ContractError('COLD_ROW_CODEC_UNSUPPORTED') from None


class ColdMethodDriver(SyntheticConnection):
    """Only guarded offline acceptance; all SELECT rows come from signed storage."""
    synthetic_fixture = True

    def __init__(self, now: datetime, route: RepositoryRoute,
                 candidates: Mapping[str, Candidate], cut: CatalogCut,
                 keys: Mapping[str, bytes], pages: Callable[[str], bytes | None],
                 tiers: Sequence[Tier]) -> None:
        super().__init__(now)
        if route.access != 'READ' or not tiers or len(candidates) > 128:
            raise ContractError('COLD_METHOD_READ_ONLY_BOUND')
        self.route = route
        self.candidates = dict(candidates)
        self.cut, self.keys, self.pages, self.tiers = cut, keys, pages, tuple(tiers)
        self.rows: list[list[object]] = []
        self.reads = 0
        self.cursor_depth = 0
        self.repository_query = False

    @contextmanager
    def cursor(self) -> Iterator[ColdMethodDriver]:
        self.cursor_depth += 1
        try:
            yield self
        finally:
            self.cursor_depth -= 1
            self.rows = []

    def execute(self, query: str,
                parameters: Sequence[object] | Mapping[str, object] | None = None) -> None:
        # Only guard's exact control statements reach its synthetic simulator.
        if query not in self.route.profile.sql:
            if parameters is not None or query not in {
                    'BEGIN', "SET LOCAL statement_timeout='10s'", "SET LOCAL lock_timeout='2s'",
                    "SET LOCAL transaction_timeout='30s'", guard.LOCK_SQL, guard.MEASURE_SQL, guard.FENCE_SQL}:
                raise ContractError('COLD_SQL_NOT_PINNED')
            self.repository_query = False
            super().execute(query)
            return
        if self.cursor_depth < 2 or not query.lstrip().upper().startswith('SELECT '):
            raise ContractError('COLD_CURSOR_OR_READ_ONLY')
        key = query_key(query, parameters)
        candidate = self.candidates.get(key)
        if candidate is None or candidate.source.replace('__', '.') not in self.route.profile.tables:
            raise ContractError('COLD_EXACT_QUERY_SOURCE_MISSING')
        SourceRouter({candidate.source: digest}).recover(candidate, self.cut, self.keys,
                                                        self.pages, self.tiers)
        raw = self.tiers[0].read(candidate.sha256, candidate.size)
        if raw is None or digest(raw) != candidate.sha256 or len(raw) != candidate.size:
            raise ContractError('COLD_SECOND_READ_CHANGED')
        try:
            value: object = json.loads(raw)
            validate_result(value)
            if not isinstance(value, dict) or set(value) != {'query', 'rows'} or value['query'] != key:
                raise ValueError
            rows = value['rows']
            if not isinstance(rows, list) or any(not isinstance(row, list) for row in rows):
                raise ValueError
        except (ValueError, TypeError, UnicodeError):
            raise ContractError('COLD_EXACT_ROWSET_INVALID') from None
        self.rows = cast(list[list[object]], rows)
        self.repository_query = True
        self.reads += 1

    def fetchone(self) -> object:
        if self.rows:
            return self.rows.pop(0)
        # Guard queries run outside the repository cursor; empty SELECT is None.
        return None if self.repository_query else super().fetchone()

    def fetchall(self) -> object:
        rows, self.rows = self.rows, []
        return rows

    def executemany(self, query: str, parameters: Sequence[Sequence[object]]) -> object:
        raise ContractError('COLD_METHOD_WRITE_FORBIDDEN')
