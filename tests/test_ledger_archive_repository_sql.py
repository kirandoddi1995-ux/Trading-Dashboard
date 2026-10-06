"""Actual exact-row archive repository SQL, disposable PostgreSQL only."""
from contextlib import contextmanager
import json
import os
import uuid
from types import SimpleNamespace

import pytest

from catalog_receipts import genesis
from ledger_archive_publication import publish, PublicationError
from ledger_archive_repository import ArchiveTransactionError, LedgerArchiveRepository, SourceCapture
from ledger_segments import FIELDS
from test_ledger_archive_guards_sql import commission, state
from test_ledger_archive_publication import MemoryObjects, NOW, RECEIPT_KEY
from test_ledger_cold_store import SEAL_KEY

pytest_plugins = ('test_ledger_archive_guards_sql', 'test_ledger_cold_store')

pytestmark = pytest.mark.skipif(not os.environ.get('EQUITY_TEST_PGLITE_MODULE'),
                                reason='Local SQL harness not configured')


@pytest.fixture
def transaction(ledger_db, history):
    db = ledger_db
    rows, ring = history
    # Fixture only. Production deletes must use the guarded verified transaction.
    db.execute('TRUNCATE quant_app.evidence_ledger_events')
    for row in rows['one'][:3]:
        values = [row[name] for name in FIELDS]
        values[9] = json.dumps(values[9])
        db.execute('INSERT INTO quant_app.evidence_ledger_events (' + ','.join(FIELDS)
                   + ') VALUES (' + ','.join(['%s']*15) + ')', values)
    texts = tuple(row[0] for row in db.execute("""SELECT to_jsonb(e)::text
        FROM quant_app.evidence_ledger_events e ORDER BY aggregate_id,sequence_no""").fetchall())
    source = SourceCapture(texts)
    assert '.1234+' in texts[0]  # Actual PostgreSQL strips trailing microsecond zeroes.
    assert '.123400+' in source.records()[0]['recorded_at']
    objects = MemoryObjects()
    result = publish(source.records(), genesis('ledger'), objects, ring, SEAL_KEY,
                     {'fixture': RECEIPT_KEY}, 'fixture', NOW)

    @contextmanager
    def connect():
        class Driver:
            def execute(self, query, params=()):
                return db.execute(query, params)

            def commit(self):
                db.execute('COMMIT')

            def rollback(self):
                db.execute('ROLLBACK')

        # Faithful to ProductionRepository.connect: context does NOT commit.
        db.execute('SET ROLE quant_storage_archiver')
        try:
            yield Driver()
        finally:
            db.execute('RESET ROLE')

    repo = LedgerArchiveRepository(connect)

    def commit():
        return repo.commit(source, result, objects, ring, SEAL_KEY,
                           {'fixture': RECEIPT_KEY}, 'f'*64)

    return db, objects, result, commit


def test_repository_commits_exact_originals_then_safe_idempotent_retry(transaction):
    db, objects, result, commit = transaction
    commission(db)
    assert commit() == 'COMMITTED'
    assert state(db) == (0, 1)
    assert commit() == 'ALREADY_COMMITTED'
    assert state(db) == (0, 1)
    assert objects.data['ledger-segment', result.prepared.segment.sha256]


def test_uncommissioned_repository_rolls_back(transaction):
    db, _, _, commit = transaction
    with pytest.raises(ArchiveTransactionError, match='TRANSACTION_FAILED'):
        commit()
    assert state(db) == (3, 0)


def test_remote_failure_blocks_before_database_transaction(transaction):
    db, objects, result, commit = transaction
    commission(db)
    objects.data.pop(('root-receipt', result.receipt.anchor.receipt_sha256))
    with pytest.raises(PublicationError, match='UNAVAILABLE'):
        commit()
    assert state(db) == (3, 0)


def test_source_missing_or_changed_is_not_deleted(transaction):
    db, _, _, commit = transaction
    commission(db)
    # Simulate external operator damage in fixture; runtime UPDATE is immutable.
    db.execute('ALTER TABLE quant_app.evidence_ledger_events DISABLE TRIGGER evidence_ledger_no_update')
    db.execute("UPDATE quant_app.evidence_ledger_events SET payload='{}' WHERE sequence_no=1")
    db.execute('ALTER TABLE quant_app.evidence_ledger_events ENABLE TRIGGER evidence_ledger_no_update')
    with pytest.raises(ArchiveTransactionError, match='SOURCE_CHANGED'):
        commit()
    assert state(db) == (3, 0)


def test_trigger_skipped_delete_rolls_back_exact_count(transaction):
    db, _, _, commit = transaction
    commission(db)
    db.send({'script': """CREATE FUNCTION quant_app.fixture_skip() RETURNS trigger
      LANGUAGE plpgsql AS $$BEGIN IF OLD.sequence_no=2 THEN RETURN NULL; END IF;
      RETURN OLD; END;$$;
      CREATE TRIGGER z_fixture_skip BEFORE DELETE ON quant_app.evidence_ledger_events
      FOR EACH ROW EXECUTE FUNCTION quant_app.fixture_skip();"""})
    with pytest.raises(ArchiveTransactionError, match='DELETE_COUNT_MISMATCH'):
        commit()
    assert state(db) == (3, 0)


def test_wrong_reader_fingerprint_rolls_back(transaction):
    db, _, _, commit = transaction
    commission(db)
    db.execute("UPDATE quant_storage.ledger_control SET reader_fingerprint=repeat('e',64)")
    with pytest.raises(ArchiveTransactionError, match='TRANSACTION_FAILED'):
        commit()
    assert state(db) == (3, 0)


@pytest.mark.parametrize('texts,code', [
    ((), 'SOURCE_LIMIT'), (('{}',), 'SOURCE_INVALID'),
    (('not json',), 'SOURCE_INVALID'), ((42,), 'SOURCE_LIMIT'),
])
def test_invalid_source_envelopes_are_rejected(texts, code):
    with pytest.raises(ArchiveTransactionError, match=code):
        SourceCapture(texts).records()


def test_maximum_batch_stages_in_one_bounded_insert():
    calls = []

    class Recorder:
        def execute(self, query, params=()):
            calls.append((query, params))

    records = [{'event_id': str(uuid.UUID(int=i+1)), 'event_hash': 'd'*64,
                'aggregate_id': 'fixture', 'sequence_no': i+1} for i in range(900)]
    # Stage helper does not sign/authorise these synthetic row proofs.
    publication = SimpleNamespace(previous=genesis('ledger'), receipt=SimpleNamespace(
        anchor=SimpleNamespace(generation=1, root='a'*64, receipt_sha256='b'*64)),
        prepared=SimpleNamespace(segment=SimpleNamespace(sha256='c'*64)))
    LedgerArchiveRepository._stage(Recorder(), records,
                                  SourceCapture(tuple('{}' for _ in records)),
                                  publication, 'f'*64)
    inserts = [(query, params) for query, params in calls
               if query.startswith('INSERT INTO quant_storage_ledger_rows')]
    assert len(inserts) == 1 and len(inserts[0][1]) == 4500
    assert inserts[0][0].count('(%s,%s,%s,%s,%s)') == 900


@pytest.mark.parametrize('stamp', [None, 'not-a-timestamp', '2026-10-06T00:00:00'])
def test_native_clock_is_never_guessed_or_defaulted(history, stamp):
    rows, _ = history
    row = {name: rows['one'][0][name] for name in FIELDS}
    row['recorded_at'] = stamp
    with pytest.raises(ArchiveTransactionError, match='SOURCE_CLOCK_INVALID'):
        SourceCapture((json.dumps(row),)).records()
