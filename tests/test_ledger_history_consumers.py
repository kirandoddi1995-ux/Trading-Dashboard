"""Consumer APIs against the actual staged reader; synthetic originals only."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import pytest

import ledger_history_consumers as consumers
from ledger_history_stream import VerifiedHistory, stage
from ledger_segments import FIELDS

pytest_plugins = ('test_ledger_staged_reader',)


def test_all_consumer_apis_share_verified_contract(runtime: Any, tmp_path: Path) -> None:
    reader, _, state = runtime
    adapter = consumers.LedgerHistoryConsumers(reader, tmp_path)
    assert adapter.events('one') == state['rows']
    assert list(adapter.verified_events()) == state['rows']
    assert adapter.duplicate('one-0') == state['rows'][0]
    assert adapter.duplicate('never-created') is None
    assert adapter.events('absent') == []
    assert list(adapter.decision_pairs()) == []
    assert len(list(adapter.decision_pairs(include_unmatured=True))) == 6
    audit = adapter.audit()
    assert audit['verified'] and audit['signature_coverage_complete']
    assert audit['events'] == audit['hmac_events'] == 6
    assert audit['unsigned_events'] == 0 and audit['approval_authority'] is False
    assert not list(tmp_path.glob('verified-ledger-*'))


@pytest.mark.parametrize('operation', ['events', 'verified_events', 'duplicate', 'decision_pairs', 'audit'])
def test_late_source_fence_blocks_every_consumer(operation: str, runtime: Any,
                                               tmp_path: Path, monkeypatch: Any) -> None:
    reader, _, _ = runtime
    original = reader.overview
    calls = 0

    def changed() -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError('private source/path/token must not appear')
        return original()

    monkeypatch.setattr(reader, 'overview', changed)
    adapter = consumers.LedgerHistoryConsumers(reader, tmp_path)
    with pytest.raises(consumers.ConsumerReadError, match='^CONSUMER_HISTORY_UNAVAILABLE$'):
        if operation == 'events':
            adapter.events('one')
        elif operation == 'duplicate':
            adapter.duplicate('never-created')
        elif operation == 'verified_events':
            next(adapter.verified_events())
        elif operation == 'decision_pairs':
            next(adapter.decision_pairs(include_unmatured=True))
        else:
            adapter.audit()
    assert not list(tmp_path.glob('verified-ledger-*'))


@pytest.mark.parametrize('limit', ['rows', 'bytes'])
def test_compatibility_list_is_bounded(limit: str, runtime: Any, tmp_path: Path,
                                     monkeypatch: Any) -> None:
    reader, _, _ = runtime
    monkeypatch.setattr(consumers, 'MAX_RESULT_ROWS' if limit == 'rows' else 'MAX_RESULT_BYTES', 1)
    adapter = consumers.LedgerHistoryConsumers(reader, tmp_path)
    with pytest.raises(consumers.ConsumerReadError, match='CONSUMER_RESULT_REQUIRES_STREAMING'):
        adapter.events('one')
    assert not list(tmp_path.glob('verified-ledger-*'))


@pytest.mark.parametrize('value', ['', 'a' * 901, True])
def test_invalid_identity_never_fetches(value: Any, runtime: Any, tmp_path: Path) -> None:
    reader, _, state = runtime
    adapter = consumers.LedgerHistoryConsumers(reader, tmp_path)
    with pytest.raises(consumers.ConsumerReadError, match='CONSUMER_IDENTITY_INVALID'):
        adapter.events(value)
    with pytest.raises(consumers.ConsumerReadError, match='CONSUMER_IDENTITY_INVALID'):
        adapter.duplicate(value)
    assert state['rollbacks'] == 0


def test_string_false_does_not_enable_pair_flag(runtime: Any, tmp_path: Path) -> None:
    reader, _, state = runtime
    with pytest.raises(consumers.ConsumerReadError, match='CONSUMER_PAIR_FLAGS_INVALID'):
        next(consumers.LedgerHistoryConsumers(reader, tmp_path).decision_pairs(
            include_unmatured=cast(bool, 'false')))
    assert state['rollbacks'] == 0


def test_missing_private_parent_is_not_created(runtime: Any, tmp_path: Path) -> None:
    reader, _, _ = runtime
    parent = tmp_path / 'missing'
    with pytest.raises(consumers.ConsumerReadError, match='CONSUMER_HISTORY_UNAVAILABLE'):
        consumers.LedgerHistoryConsumers(reader, parent).audit()
    assert not parent.exists()


def test_repeated_reads_are_detached(runtime: Any, tmp_path: Path) -> None:
    reader, _, state = runtime
    adapter = consumers.LedgerHistoryConsumers(reader, tmp_path)
    row = adapter.events('one')[0]
    row['payload'] = {'not-original': True}
    assert adapter.events('one') == state['rows']


def test_unsigned_history_is_not_hmac_evidence(tmp_path: Path) -> None:
    import sqlite3
    from evidence_ledger import ImmutableEvidenceLedger
    ledger = ImmutableEvidenceLedger(sqlite3.connect, str(tmp_path / 'synthetic.sqlite'))
    ledger.append(aggregate_id='unsigned', event_type='DECISION_EVALUATED',
                  payload={}, idempotency_key='retry')
    originals = [{key: row[key] for key in FIELDS} for row in ledger.events('unsigned')]

    class Source:
        @contextmanager
        def staged_history(self, private_parent: Path) -> Iterator[VerifiedHistory]:
            with stage(originals, expected_heads={'unsigned': (1, str(originals[-1]['event_hash']))},
                       keyring={}, private_parent=private_parent, end_fence=lambda: None) as result:
                yield result

    audit = consumers.LedgerHistoryConsumers(Source(), tmp_path).audit()
    assert audit['verified'] and audit['unsigned_events'] == 1
    assert audit['hmac_events'] == 0 and audit['signature_coverage_complete'] is False


def test_empty_history_does_not_claim_signature_coverage(tmp_path: Path) -> None:
    class Source:
        @contextmanager
        def staged_history(self, private_parent: Path) -> Iterator[VerifiedHistory]:
            with stage([], expected_heads={}, keyring={}, private_parent=private_parent,
                       end_fence=lambda: None) as result:
                yield result
    audit = consumers.LedgerHistoryConsumers(Source(), tmp_path).audit()
    assert audit['verified'] and audit['events'] == 0
    assert audit['signature_coverage_complete'] is False


@pytest.mark.parametrize('mode', ['suppress', 'replace', 'consumer_replace'])
@pytest.mark.parametrize('error_type', [ValueError, consumers.ConsumerReadError, KeyboardInterrupt])
def test_source_cannot_suppress_or_replace_a_callers_error(
        mode: str, error_type: type[BaseException], runtime: Any, tmp_path: Path) -> None:
    reader, _, _ = runtime
    class Source:
        @contextmanager
        def staged_history(self, private_parent: Path) -> Iterator[VerifiedHistory]:
            with reader.staged_history(private_parent) as history:
                try:
                    yield history
                except BaseException:
                    if mode == 'replace':
                        raise RuntimeError('private transport diagnostic') from None
                    if mode == 'consumer_replace':
                        raise consumers.ConsumerReadError('replacement') from None
                    # Deliberately broken transport wrapper; the adapter must
                    # recover the original error even when it was suppressed.
    original = error_type('synthetic reader failure')
    adapter = consumers.LedgerHistoryConsumers(Source(), tmp_path)
    with pytest.raises(error_type) as caught:
        with adapter.history():
            raise original
    assert caught.value is original


def test_suppressed_result_bound_never_returns_a_shorter_history(
        runtime: Any, tmp_path: Path, monkeypatch: Any) -> None:
    reader, _, _ = runtime
    class Source:
        @contextmanager
        def staged_history(self, private_parent: Path) -> Iterator[VerifiedHistory]:
            with reader.staged_history(private_parent) as history:
                try:
                    yield history
                except Exception:
                    pass
    monkeypatch.setattr(consumers, 'MAX_RESULT_ROWS', 1)
    adapter = consumers.LedgerHistoryConsumers(Source(), tmp_path)
    with pytest.raises(consumers.ConsumerReadError, match='CONSUMER_RESULT_REQUIRES_STREAMING'):
        adapter.events('one')
