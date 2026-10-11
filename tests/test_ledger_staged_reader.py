"""Actual reader API with injected SQL snapshots and synthetic private objects."""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any
import datetime as dt
import json

import pytest

from catalog_receipts import RootAnchor, genesis
from ledger_archive_publication import publish
from ledger_read_contract import Kind, Connection
from ledger_runtime_reader import LedgerReadError, LedgerRuntimeReader
from ledger_segments import FIELDS
from test_ledger_cold_store import SEAL_KEY

pytest_plugins = ('test_ledger_cold_store',)

RECEIPT_KEY = b'fixture-receipt-key-thirty-two-bytes!'


class Objects:
    """No network: exact synthetic content-addressed bytes only."""
    def __init__(self) -> None:
        self.data: dict[tuple[Kind, str], bytes] = {}
        self.sql_active = False

    def put(self, kind: Kind, digest: str, data: bytes) -> None:
        self.data[kind, digest] = data

    def get(self, kind: Kind, digest: str) -> bytes | None:
        assert not self.sql_active, 'cold fetch under SQL snapshot'
        return self.data.get((kind, digest))


class Result:
    def __init__(self, rows: Sequence[Sequence[object]]) -> None:
        self.values = rows

    def fetchone(self) -> Sequence[object] | None:
        return self.values[0] if self.values else None

    def fetchall(self) -> Sequence[Sequence[object]]:
        return self.values


@pytest.fixture
def runtime(history: Any) -> tuple[LedgerRuntimeReader, Objects, dict[str, Any]]:
    """Model commissioned SQL control and cold prefix + independently pinned tail."""
    sources, ring = history
    rows = [{key: row[key] for key in FIELDS} for row in sources['one']]
    objects = Objects()
    receipt = publish(rows[:4], genesis('ledger'), objects, ring, SEAL_KEY,
                      {'fixture': RECEIPT_KEY}, 'fixture', dt.datetime(2026, 10, 8, tzinfo=dt.timezone.utc))
    state: dict[str, Any] = {'rows': rows, 'anchor': receipt.receipt.anchor,
        'previous': receipt.previous, 'terminal': (6, rows[-1]['event_hash']), 'rollbacks': 0}

    class Driver:
        def execute(self, query: str, params: Sequence[object] = ()) -> Result:
            if 'FROM quant_storage.ledger_control' in query:
                return Result([(True, 'f' * 64)])
            if 'FROM quant_storage.catalog_roots' in query:
                anchor: RootAnchor = state['anchor']
                previous: RootAnchor = state['previous']
                return Result([(anchor.scope, anchor.generation, anchor.root,
                                anchor.receipt_sha256, previous.root, previous.receipt_sha256)])
            if 'FULL JOIN' in query:
                sequence, digest = state['terminal']
                return Result([('one', sequence, digest, sequence, digest)])
            if 'FROM quant_storage.ledger_hot_heads' in query:
                return Result([state['terminal']])
            if 'to_jsonb(e)::text' in query:
                return Result([(json.dumps(row),) for row in state['rows'][4:]])
            return Result([])

        def rollback(self) -> None:
            state['rollbacks'] += 1

        def commit(self) -> None:
            pytest.fail('reader committed')

    @contextmanager
    def connect() -> Iterator[Connection]:
        objects.sql_active = True
        try:
            yield Driver()
        finally:
            objects.sql_active = False

    return LedgerRuntimeReader(connect, objects, ring, SEAL_KEY,
                               {'fixture': RECEIPT_KEY}), objects, state


def test_staged_real_reader_cold_hot_originals(runtime: Any, tmp_path: Path) -> None:
    reader, objects, state = runtime
    with reader.staged_history(tmp_path) as verified:
        assert list(verified.rows()) == state['rows']
        assert verified.witness.rows == 6
        assert not objects.sql_active
    assert state['rollbacks'] == 3  # initial overview, aggregate, final overview


@pytest.mark.parametrize('kind', ['ledger-segment', 'root-receipt', 'catalog-page'])
def test_every_missing_cold_kind_blocks_stage(runtime: Any, tmp_path: Path, kind: str) -> None:
    reader, objects, _ = runtime
    for key in list(objects.data):
        if key[0] == kind:
            objects.data.pop(key)
    with pytest.raises(LedgerReadError):
        with reader.staged_history(tmp_path):
            pytest.fail('incomplete originals exposed')


def test_final_head_change_blocks_atomic_exposure(runtime: Any, tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    reader, _, state = runtime
    original = reader.overview
    calls = 0
    def overview() -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            state['terminal'] = (7, 'b' * 64)
        return original()
    monkeypatch.setattr(reader, 'overview', overview)
    with pytest.raises(LedgerReadError, match='STAGED_HISTORY_UNVERIFIED'):
        with reader.staged_history(tmp_path):
            pytest.fail('concurrent append hidden')


def test_no_private_spool_parent_is_inferred(runtime: Any, tmp_path: Path) -> None:
    reader, _, _ = runtime
    missing = tmp_path / 'not-provisioned'
    with pytest.raises(LedgerReadError):
        with reader.staged_history(missing):
            pytest.fail('parent provisioned automatically')
    assert not missing.exists()


def test_staging_does_not_use_unbounded_global_materializer(runtime: Any, tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    reader, _, _ = runtime
    def forbidden() -> Any:
        pytest.fail('legacy iterator used')
    monkeypatch.setattr(reader, 'verified_events', forbidden)
    with reader.staged_history(tmp_path) as verified:
        assert verified.witness.rows == 6
