"""Synthetic offline chain, atomic visibility and resource-bound regressions."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import sqlite3
from typing import Any, cast

import pytest

from cold_catalog import Catalog, EMPTY_ROOT
from evidence_ledger import GENESIS_HASH, ImmutableEvidenceLedger
from ledger_cold_store import ColdLedger, ColdLedgerError, prepare
import ledger_history_stream as stream
from ledger_segments import FIELDS, Head
from test_ledger_cold_store import SEAL_KEY

pytest_plugins = ('test_ledger_cold_store',)


def staged(rows: list[dict[str, Any]], ring: dict[str, bytes], parent: Path,
           fence: Any = lambda: None) -> Any:
    """Construct the fully exhausted private-stage context for one aggregate."""
    return stream.stage(iter(rows), expected_heads={'one': (6, rows[-1]['event_hash'])},
                        keyring=ring, private_parent=parent, end_fence=fence)


def cold_fixture(value: Any) -> tuple[ColdLedger, list[dict[str, Any]], dict[str, bytes],
                                      dict[str, bytes]]:
    """Publish three synthetic segments into in-memory immutable object stores."""
    rows, ring = value
    pages: dict[str, bytes] = {}
    segments: dict[str, bytes] = {}
    catalog = Catalog(EMPTY_ROOT, pages.get)
    for start in (0, 2, 4):
        proposal = prepare(rows['one'][start:start + 2], catalog, ring, SEAL_KEY)
        pages.update(proposal.catalog.pages)
        segments[proposal.segment.sha256] = proposal.segment.data
        catalog = Catalog(proposal.catalog.root, pages.get)
    originals = [{key: value for key, value in row.items() if key != 'duplicate'}
                 for row in rows['one']]
    return ColdLedger(catalog, segments.get, ring, SEAL_KEY), originals, ring, segments


def test_stream_matches_original_and_repeats_detached_reads(history: Any, tmp_path: Path) -> None:
    cold, rows, ring, _ = cold_fixture(history)
    expected = {'one': (6, rows[-1]['event_hash'])}
    fences: list[str] = []
    with stream.stage(cold.iter_merged('one', [], expected['one']), expected_heads=expected,
            keyring=ring, private_parent=tmp_path, end_fence=lambda: fences.append('checked')) as result:
        assert fences == ['checked']
        assert list(result.rows()) == rows
        assert result.witness.rows == 6
        assert result.witness.hmac_events == 6 and result.witness.unsigned_events == 0
        first = next(result.rows())
        first['payload'] = {'mutated': True}
        assert list(result.rows()) == rows
        assert result.witness.heads == expected
        assert list(tmp_path.glob('verified-ledger-*'))
    assert not list(tmp_path.glob('verified-ledger-*'))
    with pytest.raises(stream.HistoryStreamError, match='UNAVAILABLE'):
        list(result.rows())


def test_later_missing_segment_never_exposes_stage(history: Any, tmp_path: Path) -> None:
    cold, rows, ring, segments = cold_fixture(history)
    segments.pop(next(reversed(segments)))
    exposed = False
    with pytest.raises(stream.HistoryStreamError, match='BLOCKED'):
        with stream.stage(cold.iter_events('one'), expected_heads={'one': (6, rows[-1]['event_hash'])},
                keyring=ring, private_parent=tmp_path, end_fence=lambda: None):
            exposed = True
    assert not exposed
    assert not list(tmp_path.glob('verified-ledger-*'))


def test_end_fence_failure_blocks_every_row(history: Any, tmp_path: Path) -> None:
    rows, ring = history
    def changed() -> None:
        raise ValueError('private driver secret must not escape')
    with pytest.raises(stream.HistoryStreamError, match='^HISTORY_STAGE_BLOCKED$'):
        with staged(rows['one'], ring, tmp_path, changed):
            pytest.fail('mixed-time history exposed')


@pytest.mark.parametrize('kind', ['gap', 'wrong_terminal', 'unknown_key', 'changed_payload',
                                  'missing_aggregate', 'unobserved_aggregate', 'duplicate_key'])
def test_invalid_history_fails_closed(history: Any, tmp_path: Path, kind: str) -> None:
    source, ring = history
    rows = [dict(row) for row in source['one']]
    expected: dict[str, Head] = {'one': (6, rows[-1]['event_hash'])}
    if kind == 'gap':
        rows.pop(2)
    elif kind == 'wrong_terminal':
        expected['one'] = (7, 'a' * 64)
    elif kind == 'unknown_key':
        ring = {}
    elif kind == 'changed_payload':
        rows[-1]['payload'] = {'fabricated': True}
    elif kind == 'missing_aggregate':
        expected = {}
    elif kind == 'unobserved_aggregate':
        expected['unobserved'] = (1, 'a' * 64)
    else:
        rows.append(rows[0])
    with pytest.raises(stream.HistoryStreamError):
        with stream.stage(rows, expected_heads=expected, keyring=ring,
                          private_parent=tmp_path, end_fence=lambda: None):
            pytest.fail('invalid history exposed')


def test_empty_history_requires_explicit_zero_heads(tmp_path: Path) -> None:
    with stream.stage([], expected_heads={'empty': (0, GENESIS_HASH)}, keyring={},
            private_parent=tmp_path, end_fence=lambda: None) as result:
        assert result.witness.rows == 0
        assert list(result.rows()) == []


@pytest.mark.parametrize('head', [(True, GENESIS_HASH), (0, 'a' * 64), (-1, GENESIS_HASH),
                                  (1, 'A' * 64), (1, 'short')])
def test_invalid_terminal_types(tmp_path: Path, head: Any) -> None:
    with pytest.raises(stream.HistoryStreamError, match='TERMINAL_INVALID'):
        with stream.stage([], expected_heads={'one': head}, keyring={},
                          private_parent=tmp_path, end_fence=lambda: None):
            pytest.fail('invalid head exposed')


@pytest.mark.parametrize('bound', ['MAX_ROWS', 'MAX_BYTES', 'MAX_SECONDS'])
def test_limits_block_and_remove_only_ephemeral_spool(history: Any, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, bound: str) -> None:
    rows, ring = history
    monkeypatch.setattr(stream, bound, 0)
    keep = tmp_path / 'owner-file'
    keep.write_bytes(b'unchanged')
    with pytest.raises(stream.HistoryStreamError):
        with staged(rows['one'], ring, tmp_path):
            pytest.fail('bound bypassed')
    assert keep.read_bytes() == b'unchanged'
    assert not list(tmp_path.glob('verified-ledger-*'))


def test_source_iterator_error_is_redacted(history: Any, tmp_path: Path) -> None:
    rows, ring = history
    def broken() -> Iterator[dict[str, Any]]:
        yield rows['one'][0]
        raise OSError('private credential details')
    with pytest.raises(stream.HistoryStreamError, match='^HISTORY_STAGE_BLOCKED$'):
        with stream.stage(broken(), expected_heads={'one': (6, rows['one'][-1]['event_hash'])},
                keyring=ring, private_parent=tmp_path, end_fence=lambda: None):
            pytest.fail('prefix exposed')


def test_stream_does_not_call_list_materializer(history: Any,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    cold, rows, _, _ = cold_fixture(history)
    def forbidden(_aggregate: str) -> Any:
        pytest.fail('full-history materialization')
    monkeypatch.setattr(cold, 'events', forbidden)
    assert list(cold.iter_merged('one', [], (6, rows[-1]['event_hash']))) == rows


def test_cold_hot_stream_matches_existing_list(history: Any) -> None:
    source, ring = history
    rows = [{key: value for key, value in row.items() if key != 'duplicate'}
            for row in source['one']]
    pages: dict[str, bytes] = {}
    segments: dict[str, bytes] = {}
    proposal = prepare(rows[:4], Catalog(EMPTY_ROOT, pages.get), ring, SEAL_KEY)
    pages.update(proposal.catalog.pages)
    segments[proposal.segment.sha256] = proposal.segment.data
    cold = ColdLedger(Catalog(proposal.catalog.root, pages.get), segments.get, ring, SEAL_KEY)
    assert list(cold.iter_merged('one', rows[4:], (6, rows[-1]['event_hash']))) == rows
    with pytest.raises(ColdLedgerError):
        list(cold.iter_merged('one', rows[3:], (6, rows[-1]['event_hash'])))


def test_segment_walk_limit_does_not_return_partial(history: Any,
        monkeypatch: pytest.MonkeyPatch) -> None:
    cold, _, _, _ = cold_fixture(history)
    monkeypatch.setattr('ledger_cold_store.MAX_READ_SEGMENTS', 2)
    with pytest.raises(ColdLedgerError, match='REQUIRES_PAGINATION'):
        list(cold.iter_events('one'))


def test_missing_parent_is_not_created(tmp_path: Path) -> None:
    missing = tmp_path / 'unapproved'
    with pytest.raises(stream.HistoryStreamError, match='PARENT_INVALID'):
        with stream.stage([], expected_heads={}, keyring={}, private_parent=missing,
                          end_fence=lambda: None):
            pytest.fail('missing parent created')
    assert not missing.exists()


@pytest.mark.parametrize('include,first,expected_count', [(False, False, 4),
    (False, True, 2), (True, False, 5), (True, True, 3)])
def test_decision_pair_join_semantics(tmp_path: Path, include: bool, first: bool,
                                      expected_count: int) -> None:
    ledger = ImmutableEvidenceLedger(sqlite3.connect, str(tmp_path / 'synthetic.sqlite'),
                                    b'fixture-only-history-key')
    for aggregate, event_types in [('one', ['DECISION_EVALUATED', 'DECISION_EVALUATED',
            'OUTCOME_MATURED', 'OUTCOME_MATURED']), ('two', ['DECISION_EVALUATED'])]:
        for number, event_type in enumerate(event_types):
            ledger.append(aggregate_id=aggregate, event_type=event_type,
                          payload={'ordinal': number}, idempotency_key=f'{aggregate}:{number}')
    rows = ledger.events('one') + ledger.events('two')
    expected = {name: (part[-1]['sequence_no'], part[-1]['event_hash'])
                for name in ('one', 'two') if (part := ledger.events(name))}
    ring = {rows[0]['key_id']: b'fixture-only-history-key'}
    with stream.stage(rows, expected_heads=expected, keyring=ring, private_parent=tmp_path,
                      end_fence=lambda: None) as verified:
        pairs = list(verified.decision_pairs(include_unmatured=include, first_outcome=first))
        assert len(pairs) == expected_count
        assert sum(outcome is None for _, outcome in pairs) == int(include)
        if first:
            assert all(outcome is None or outcome['sequence_no'] == 3 for _, outcome in pairs)
        with pytest.raises(stream.HistoryStreamError, match='PAIR_FLAGS_INVALID'):
            list(verified.decision_pairs(first_outcome=cast(Any, 'false')))


def test_unsigned_originals_remain_explicitly_unsigned(tmp_path: Path) -> None:
    ledger = ImmutableEvidenceLedger(sqlite3.connect, str(tmp_path / 'unsigned-fixture.sqlite'), b'')
    ledger.append(aggregate_id='unsigned', event_type='DECISION_EVALUATED',
                  payload={}, idempotency_key='unsigned:one')
    rows = ledger.events('unsigned')
    with stream.stage(rows, expected_heads={'unsigned': (1, rows[0]['event_hash'])},
            keyring={}, private_parent=tmp_path, end_fence=lambda: None) as result:
        assert result.witness.hmac_events == 0
        assert result.witness.unsigned_events == 1
        assert list(result.rows())[0]['hash_algorithm'] == 'SHA256 hash chain'


def test_pair_queries_use_indexes_not_external_payload_sort(history: Any, tmp_path: Path) -> None:
    source, ring = history
    with staged(source['one'], ring, tmp_path) as verified:
        queries = [('''SELECT body,aggregate_id FROM history INDEXED BY history_decision_order_idx
            WHERE event_type='DECISION_EVALUATED' ORDER BY effective_utc,aggregate_id,sequence_no''', ()),
            ('''SELECT body FROM history INDEXED BY history_pair_idx
            WHERE aggregate_id=? AND event_type='OUTCOME_MATURED' ORDER BY sequence_no''', ('one',))]
        for query, arguments in queries:
            plans = verified._connection.execute('EXPLAIN QUERY PLAN ' + query, arguments).fetchall()
            assert all('TEMP' not in str(part).upper() for part in plans)


def test_retry_lookup_is_detached_indexed_and_context_scoped(history: Any, tmp_path: Path) -> None:
    source, ring = history
    with staged(source['one'], ring, tmp_path) as verified:
        retry = str(source['one'][0]['idempotency_key'])
        first = verified.duplicate(retry)
        assert first is not None
        first['payload'] = {'not-original': True}
        assert verified.duplicate(retry) == {name: source['one'][0][name] for name in FIELDS}
        assert verified.duplicate('not-created') is None
        plan = verified._connection.execute('EXPLAIN QUERY PLAN SELECT body FROM history WHERE retry_key=?',
                                            (retry,)).fetchall()
        assert any('INDEX' in str(row).upper() for row in plan)
        assert not any('SCAN HISTORY' in str(row).upper() for row in plan)
    with pytest.raises(stream.HistoryStreamError, match='RETRY_READ_BLOCKED'):
        verified.duplicate('not-created')


@pytest.mark.parametrize('retry', ['', True, 'x' * 901])
def test_retry_lookup_rejects_invalid_identity(history: Any, tmp_path: Path, retry: Any) -> None:
    source, ring = history
    with staged(source['one'], ring, tmp_path) as verified:
        with pytest.raises(stream.HistoryStreamError, match='RETRY_IDENTITY_INVALID'):
            verified.duplicate(retry)
