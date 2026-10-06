"""Actual read-only reader snapshots and original history after atomic archival."""
from contextlib import contextmanager
import datetime as dt
import json
import os
import hashlib
import hmac

import pytest

from ledger_runtime_reader import LedgerRuntimeReader, LedgerReadError
from ledger_segments import FIELDS
from evidence_ledger import canonical_json
from production_repository import ProductionRepository
from ledger_archive_publication import publish
from ledger_archive_repository import LedgerArchiveRepository, SourceCapture
from catalog_receipts import genesis
from test_ledger_archive_guards_sql import commission
from test_ledger_archive_publication import RECEIPT_KEY, NOW
from test_ledger_cold_store import SEAL_KEY

pytest_plugins = ('test_ledger_archive_repository_sql',)
pytestmark = pytest.mark.skipif(not os.environ.get('EQUITY_TEST_PGLITE_MODULE'),
                                reason='Local SQL harness not configured')


@pytest.fixture
def reader(transaction, history):
    db, objects, publication, commit = transaction
    _, ring = history
    commission(db)
    db.execute('GRANT USAGE ON SCHEMA quant_app TO quant_app_runtime')
    db.execute('GRANT SELECT ON quant_app.evidence_ledger_events TO quant_app_runtime')
    active = {'sql': False}

    @contextmanager
    def connect():
        class Driver:
            def execute(self, query, params=()):
                return db.execute(query, params)

            def rollback(self):
                db.execute('ROLLBACK')

            def commit(self):
                raise AssertionError('Reader must not rely on commit')

        db.execute('SET ROLE quant_app_runtime')
        active['sql'] = True
        try:
            yield Driver()
        finally:
            active['sql'] = False
            db.execute('RESET ROLE')

    original_get = objects.get

    def get(kind, digest):
        assert not active['sql'], 'No Drive fetch during the SQL transaction'
        return original_get(kind, digest)

    objects.get = get
    runtime = LedgerRuntimeReader(connect, objects, ring, SEAL_KEY, {'fixture': RECEIPT_KEY})
    return db, objects, publication, commit, runtime


def hashes(rows):
    return [row['event_hash'] for row in rows]


def archive_current_source(db, objects, ring):
    """Publish and delete only the current synthetic disposable SQL source."""
    source = SourceCapture(tuple(row[0] for row in db.execute('''SELECT to_jsonb(e)::text
        FROM quant_app.evidence_ledger_events e ORDER BY aggregate_id,sequence_no''').fetchall()))
    publication = publish(source.records(), genesis('ledger'), objects, ring, SEAL_KEY,
                          {'fixture': RECEIPT_KEY}, 'fixture', NOW)
    @contextmanager
    def connect_archive():
        class Driver:
            def execute(self, query, params=()):
                return db.execute(query, params)
            def commit(self):
                db.execute('COMMIT')
            def rollback(self):
                db.execute('ROLLBACK')
        db.execute('SET ROLE quant_storage_archiver')
        try:
            yield Driver()
        finally:
            db.execute('RESET ROLE')
    assert LedgerArchiveRepository(connect_archive).commit(source, publication, objects,
        ring, SEAL_KEY, {'fixture': RECEIPT_KEY}, 'f'*64) == 'COMMITTED'
    return publication


def test_reader_preserves_originals_before_and_after_complete_archival(reader, history):
    db, objects, _, commit, runtime = reader
    originals, _ = history
    objects.reads.clear()
    assert hashes(runtime.events('one')) == hashes(originals['one'][:3])
    assert objects.reads == []  # Genesis root requires no cold network fetch.
    assert commit() == 'COMMITTED'
    assert db.execute('SELECT count(*) FROM quant_storage.ledger_hot_heads').fetchone() == (0,)
    assert hashes(runtime.events('one')) == hashes(originals['one'][:3])
    assert runtime.events('never-recorded') == []  # Verified catalog absence, not missing page.


def test_global_audit_counts_fully_archived_originals_not_empty_hot_sql(reader):
    _, _, _, commit, runtime = reader
    assert runtime.audit()['events'] == 3
    commit()
    assert runtime.audit() == {'verified': True, 'broken_links': 0,
        'duplicate_sequences': 0, 'events': 3, 'scope': 'ORIGINAL_HMAC_HOT_AND_COLD'}
    repo = ProductionRepository('', cold_ledger_reader=runtime)
    repo._schema_ready = True
    assert repo.verify_evidence_ledger_continuity()['events'] == 3


def test_global_audit_missing_cold_segment_never_reports_empty_success(reader):
    _, objects, publication, commit, runtime = reader
    commit()
    objects.data.pop(('ledger-segment', publication.prepared.segment.sha256))
    with pytest.raises(LedgerReadError, match='GLOBAL_ORIGINALS_UNVERIFIED'):
        runtime.audit()


def test_global_audit_stale_root_is_not_a_mixed_time_certificate(reader):
    _, _, _, commit, runtime = reader
    overview = runtime.overview
    calls = {'n': 0}
    def changed():
        result = overview()
        calls['n'] += 1
        if calls['n'] == 1:
            commit()
        return result
    runtime.overview = changed
    with pytest.raises(LedgerReadError, match='GLOBAL_SNAPSHOT_CHANGED'):
        runtime.audit()


def test_global_audit_detects_change_after_last_original_is_read(reader, history):
    db, _, _, _, runtime = reader
    iterator = runtime.verified_events()
    assert len([next(iterator) for _ in range(3)]) == 3
    insert_original(db, history[0]['one'][3])
    with pytest.raises(LedgerReadError, match='GLOBAL_SNAPSHOT_CHANGED'):
        list(iterator)


def test_global_overview_detects_entire_hot_tail_loss(reader):
    db, _, _, _, runtime = reader
    db.execute('TRUNCATE quant_app.evidence_ledger_events')
    with pytest.raises(LedgerReadError, match='HOT_TERMINAL_INCONSISTENT'):
        runtime.audit()


def test_training_and_readiness_sql_results_survive_verified_complete_archival(reader, history):
    """Synthetic originals only; compare actual legacy SQL to cold-aware results."""
    import pandas as pd
    db, objects, _, _, runtime = reader
    # Disposable fixture reset, NEVER production/owner bootstrap instructions.
    db.execute('UPDATE quant_storage.ledger_control SET pruning_enabled=false,heads_enabled=false')
    db.execute('TRUNCATE quant_app.evidence_ledger_events,quant_storage.ledger_hot_heads')
    originals = [{name: row[name] for name in FIELDS} for row in history[0]['one'][:3]]
    originals[0]['payload'] = {
        'decision_id': 'synthetic-only', 'decision_at': '2026-10-01T10:00:00+00:00',
        'identifiers': {'strategy_id': 'fixture', 'target_version': 'fixture', 'horizon_sessions': 1},
        'features': {'status': 'AVAILABLE', 'values': {'momentum': 2.0}},
        'universe': {'status': 'VERIFIED'}, 'quote': {'status': 'AVAILABLE', 'bid': 100, 'ask': 101},
        'costs': {'breakdown_complete': True}, 'action': 'RESEARCH_ONLY'}
    for index, row in enumerate(originals[1:], 1):
        row['event_type'] = 'OUTCOME_MATURED'
        row['payload'] = {'outcome': 'TARGET' if index == 1 else 'STOP',
                          'outcome_at': '2026-10-02T10:00:00+00:00',
                          'actual_forward_return': 0.5 if index == 1 else -0.3}
    preceding = '0'*64
    for row in originals:
        row['previous_hash'] = preceding
        material = {name: row[name] for name in FIELDS if name not in ('payload', 'event_hash')}
        material['payload_json'] = canonical_json(row['payload'])
        row['event_hash'] = hmac.new(next(iter(history[1].values())),
            canonical_json(material).encode(), hashlib.sha256).hexdigest()
        preceding = row['event_hash']
        insert_original(db, row)
    commission(db)
    legacy = ProductionRepository('')
    legacy._schema_ready = True
    legacy.connect = runtime.connect
    expected_records = legacy.decision_outcome_records()
    # psycopg returns aware datetimes; the JSON bridge intentionally keeps full
    # PostgreSQL precision rather than round through JavaScript Date.
    for record in expected_records:
        for field in ('decision_recorded_at', 'matured_at'):
            record[field] = dt.datetime.fromisoformat(record[field]).astimezone(dt.timezone.utc)
    expected_frame = legacy.matured_decision_dataset(strategy_id='fixture', target_version='fixture',
                                                    horizon_sessions=1)
    assert len(expected_frame) == 2 and len(expected_records) == 1
    archive_current_source(db, objects, history[1])
    repo = ProductionRepository('', cold_ledger_reader=runtime)
    repo._schema_ready = True
    assert repo.decision_outcome_records() == expected_records
    actual_frame = repo.matured_decision_dataset(strategy_id='fixture', target_version='fixture',
                                               horizon_sessions=1)
    pd.testing.assert_frame_equal(actual_frame, expected_frame)
    assert actual_frame.attrs['ledger_verified'] is True
    assert actual_frame.attrs['ledger_audit']['events'] == 3


def test_decision_consumers_cannot_return_plausible_empty_data_when_cold_is_missing(reader):
    _, objects, publication, commit, runtime = reader
    commit()
    objects.data.pop(('ledger-segment', publication.prepared.segment.sha256))
    repo = ProductionRepository('', cold_ledger_reader=runtime)
    repo._schema_ready = True
    for call in (repo.decision_outcome_records,
                 lambda: repo.matured_decision_dataset(strategy_id='fixture',
                     target_version='fixture', horizon_sessions=1)):
        with pytest.raises(LedgerReadError, match='GLOBAL_ORIGINALS_UNVERIFIED'):
            call()


def pending_source(reader, history, *, matured=False, horizon=15):
    """Real SQL pending join fixture; all values synthetic and not market evidence."""
    db, objects, _, _, runtime = reader
    db.execute('UPDATE quant_storage.ledger_control SET pruning_enabled=false,heads_enabled=false')
    db.execute('TRUNCATE quant_app.evidence_ledger_events,quant_storage.ledger_hot_heads')
    originals = [{name: row[name] for name in FIELDS} for row in history[0]['one'][:3]]
    preceding = '0'*64
    for index, row in enumerate(originals):
        row['aggregate_id'] = 'decision:fixture-observation'
        row['event_type'] = ('DECISION_EVALUATED' if index == 0 else
                             'OUTCOME_MATURED' if matured and index == 2 else 'HEALTH_CHECK')
        row['payload'] = {'identifiers': {'target_version': 'fixture', 'horizon_sessions': horizon}}
        row['previous_hash'] = preceding
        material = {name: row[name] for name in FIELDS if name not in ('payload', 'event_hash')}
        material['payload_json'] = canonical_json(row['payload'])
        row['event_hash'] = hmac.new(next(iter(history[1].values())),
            canonical_json(material).encode(), hashlib.sha256).hexdigest()
        preceding = row['event_hash']
        insert_original(db, row)
    commission(db)
    db.execute('''CREATE TABLE quant_app.scanner_observations (
        observation_id text PRIMARY KEY,as_of_date date,observed_at timestamptz,
        instrument_key text,trading_symbol text,entry numeric,stop numeric,target numeric,
        feature_json jsonb,stage2_pass boolean)''')
    db.execute('''INSERT INTO quant_app.scanner_observations VALUES
        ('fixture-observation','2026-10-01','2026-10-01Z','fixture-key','FIXTURE',
         100,99,102,'{"frozen":true}',true)''')
    db.execute('GRANT SELECT ON quant_app.scanner_observations TO quant_app_runtime')
    legacy = ProductionRepository('')
    legacy._schema_ready = True
    legacy.connect = runtime.connect
    repo = ProductionRepository('', cold_ledger_reader=runtime)
    repo._schema_ready = True
    return db, objects, runtime, legacy, repo


@pytest.mark.parametrize('matured', [False, True])
def test_pending_observations_matches_actual_sql_after_full_archival(reader, history, matured):
    db, objects, _, legacy, repo = pending_source(reader, history, matured=matured)
    expected = legacy.pending_observations(target_version='fixture')
    assert len(expected) == (0 if matured else 1)
    assert repo.pending_observations(target_version='fixture') == expected
    archive_current_source(db, objects, history[1])
    assert repo.pending_observations(target_version='fixture') == expected
    assert repo.pending_observations(target_version='other') == []
    assert repo.pending_observations(target_version='fixture', limit=0) == []


@pytest.mark.parametrize('horizon', [True, '1.5', 'not-a-number', 2**31])
def test_pending_invalid_original_horizon_is_not_silently_skipped(reader, history, horizon):
    _, _, _, _, repo = pending_source(reader, history, horizon=horizon)
    with pytest.raises(LedgerReadError, match='PENDING_IDENTIFIERS_INVALID'):
        repo.pending_observations(target_version='fixture')


@pytest.mark.parametrize('horizon', [None, 0, -1, ' +2 '])
def test_pending_nullable_and_signed_horizons_preserve_actual_sql(reader, history, horizon):
    _, _, _, legacy, repo = pending_source(reader, history, horizon=horizon)
    assert repo.pending_observations(target_version='fixture') == legacy.pending_observations(
        target_version='fixture')


@pytest.mark.parametrize('column', ['entry', 'stop', 'target'])
def test_pending_missing_execution_levels_stay_excluded(reader, history, column):
    db, _, _, legacy, repo = pending_source(reader, history)
    db.execute('UPDATE quant_app.scanner_observations SET '+column+'=NULL')
    assert legacy.pending_observations(target_version='fixture') == []
    assert repo.pending_observations(target_version='fixture') == []


@pytest.mark.parametrize('count,aggregate', [(10_001, 'decision:fixture'), (3000, 'x'*900)])
def test_pending_bounded_staging_refuses_to_truncate_original_facts(reader, count, aggregate):
    repo = ProductionRepository('', cold_ledger_reader=reader[-1])
    repo._schema_ready = True
    repo._cold_decision_pairs = lambda **kwargs: [({'aggregate_id': aggregate, 'payload': {
        'identifiers': {'target_version': 'fixture', 'horizon_sessions': 15}}}, None)]*count
    with pytest.raises(LedgerReadError, match='PENDING_REQUIRES_PAGINATION'):
        repo.pending_observations(target_version='fixture')


def test_pending_null_target_never_matches_literal_none(reader):
    repo = ProductionRepository('', cold_ledger_reader=reader[-1])
    repo._schema_ready = True
    # No scanner table exists: NULL target is excluded but the actual read still
    # checks dependencies instead of returning a misleading early empty result.
    repo._cold_decision_pairs = lambda **kwargs: [({'aggregate_id': 'decision:fixture', 'payload': {
        'identifiers': {'target_version': None, 'horizon_sessions': True}}}, None)]
    with pytest.raises(LedgerReadError, match='PENDING_READ_FAILED'):
        repo.pending_observations(target_version='None')


def test_pending_missing_cold_originals_cannot_look_like_finished_collection(reader, history):
    db, objects, _, _, repo = pending_source(reader, history)
    publication = archive_current_source(db, objects, history[1])
    objects.data.pop(('ledger-segment', publication.prepared.segment.sha256))
    with pytest.raises(LedgerReadError, match='GLOBAL_ORIGINALS_UNVERIFIED'):
        repo.pending_observations(target_version='fixture')


def test_pending_sql_error_is_sanitized_and_rolled_back(reader, history):
    db, _, _, _, repo = pending_source(reader, history)
    db.execute('REVOKE SELECT ON quant_app.scanner_observations FROM quant_app_runtime')
    with pytest.raises(LedgerReadError, match='^LEDGER_PENDING_READ_FAILED$'):
        repo.pending_observations(target_version='fixture')
    db.execute('GRANT SELECT ON quant_app.scanner_observations TO quant_app_runtime')
    assert len(repo.pending_observations(target_version='fixture')) == 1


def test_pending_reader_detects_outcome_state_change_during_join(reader, history):
    _, _, runtime, _, repo = pending_source(reader, history)
    original = runtime.overview
    calls = {'count': 0}
    def changed():
        result = original()
        calls['count'] += 1
        if calls['count'] == 4:
            # The fourth overview is the final pending-consumer fence.
            from dataclasses import replace
            return replace(result, heads={**result.heads, 'synthetic-concurrent': (1, 'a'*64)})
        return result
    runtime.overview = changed
    with pytest.raises(LedgerReadError, match='GLOBAL_SNAPSHOT_CHANGED'):
        repo.pending_observations(target_version='fixture')


def test_production_events_routes_to_verified_reader(reader, history):
    _, _, _, commit, runtime = reader
    commit()
    repository = ProductionRepository('', cold_ledger_reader=runtime)
    repository._schema_ready = True
    rows = repository.events('one')
    assert hashes(rows) == hashes(history[0]['one'][:3])
    assert all(row['duplicate'] is False for row in rows)
    assert all('.123400+' in row['recorded_at'] for row in rows)


def test_append_preparation_hot_and_cold_frontiers(reader, history):
    _, objects, _, commit, runtime = reader
    originals = history[0]['one']
    objects.reads.clear()
    prepared = runtime.prepare_append('one', 'not-recorded')
    assert prepared.cold_head == (0, '0'*64)
    assert prepared.terminal == (3, originals[2]['event_hash'])
    assert prepared.duplicate is None
    assert objects.reads == []
    commit()
    prepared = runtime.prepare_append('one', originals[0]['idempotency_key'])
    assert prepared.snapshot.terminal is None
    assert prepared.cold_head == prepared.terminal == (3, originals[2]['event_hash'])
    assert prepared.duplicate == {name: originals[0][name] for name in FIELDS}


def test_append_preparation_checks_global_cold_duplicate(reader, history):
    _, _, _, commit, runtime = reader
    commit()
    prepared = runtime.prepare_append('new-aggregate', history[0]['one'][0]['idempotency_key'])
    assert prepared.terminal == (0, '0'*64)
    assert prepared.duplicate['aggregate_id'] == 'one'


@pytest.mark.parametrize('key', ['', None, False, 'x'*901, '\u20b9'*301])
def test_append_preparation_rejects_invalid_identity_before_sql(reader, key):
    runtime = reader[-1]
    runtime.snapshot = lambda aggregate: pytest.fail('Must validate before SQL')
    with pytest.raises(LedgerReadError, match='IDEMPOTENCY_INVALID'):
        runtime.prepare_append('one', key)


def test_append_preparation_missing_original_is_not_new_identity(reader, history):
    _, objects, publication, commit, runtime = reader
    commit()
    objects.data.pop(('ledger-segment', publication.prepared.segment.sha256))
    with pytest.raises(LedgerReadError, match='APPEND_EVIDENCE_UNVERIFIED'):
        runtime.prepare_append('one', history[0]['one'][0]['idempotency_key'])


def test_append_preparation_unrecorded_aggregate_proves_genesis(reader):
    prepared = reader[-1].prepare_append('new-aggregate', 'new-identity')
    assert prepared.cold_head == prepared.terminal == (0, '0'*64)
    assert prepared.duplicate is None


def test_append_preparation_unknown_signature_key_fails_closed(reader):
    runtime = reader[-1]
    runtime.event_keys = {}
    with pytest.raises(LedgerReadError, match='APPEND_EVIDENCE_UNVERIFIED'):
        runtime.prepare_append('one', 'new-identity')


@pytest.fixture
def writer(reader, history, monkeypatch):
    """Faithful owned/shared connections: per-event commit, no context commit."""
    db, objects, _, _, runtime = reader
    active = {'sql': False, 'commits': 0, 'rollbacks': 0}
    assert db.execute("SELECT has_table_privilege('quant_app_runtime',"
                      "'quant_storage.catalog_roots','UPDATE')").fetchone() == (False,)
    db.execute('GRANT INSERT ON quant_app.evidence_ledger_events TO quant_app_runtime')
    original_get = objects.get

    def get(kind, digest):
        assert not active['sql'], 'No Drive fetch while writer transaction is open'
        return original_get(kind, digest)

    objects.get = get

    @contextmanager
    def connect():
        class Driver:
            def execute(self, query, params=()):
                if not active['sql']:
                    db.execute('BEGIN')
                    db.execute('SET LOCAL ROLE quant_app_runtime')
                    active['sql'] = True
                return db.execute(query, params)

            def commit(self):
                db.execute('COMMIT')
                active['sql'] = False
                active['commits'] += 1

            def rollback(self):
                db.execute('ROLLBACK')
                active['sql'] = False
                active['rollbacks'] += 1

        driver = Driver()
        try:
            yield driver
        finally:
            if active['sql']:
                driver.rollback()

    monkeypatch.setattr('production_repository._json', json.dumps)
    repo = ProductionRepository('', evidence_signing_key=next(iter(history[1].values())),
                                cold_ledger_reader=runtime, cold_ledger_fingerprint='f'*64)
    repo._schema_ready = True
    repo.connect = connect
    return repo, active


def request(row):
    return {key: row[key] for key in ('aggregate_id', 'event_type', 'payload',
                                     'source', 'actor_id', 'idempotency_key')}


def test_actual_writer_reappends_after_full_archival(reader, writer, history):
    db, _, _, commit, runtime = reader
    repo, active = writer
    commit()
    result = repo.append_evidence_event(aggregate_id='one', event_type='NEXT',
                                        payload={'verified': True}, idempotency_key='next-event')
    assert result['sequence_no'] == 4 and result['duplicate'] is False
    rows = runtime.events('one')
    assert hashes(rows[:3]) == hashes(history[0]['one'][:3])
    assert rows[3]['previous_hash'] == history[0]['one'][2]['event_hash']
    assert active['commits'] == 1 and active['sql'] is False
    assert db.execute('SELECT sequence_no FROM quant_storage.ledger_hot_heads').fetchone() == (4,)


@pytest.mark.parametrize('archived', [False, True])
def test_actual_writer_returns_original_hot_or_cold_retry(reader, writer, history, archived):
    _, _, _, commit, _ = reader
    repo, active = writer
    if archived:
        commit()
    row = history[0]['one'][0]
    result = repo.append_evidence_event(**request(row))
    assert result == {'event_id': row['event_id'], 'aggregate_id': 'one',
                      'sequence_no': 1, 'event_hash': row['event_hash'], 'duplicate': True}
    assert active['commits'] == 1


@pytest.mark.parametrize('changed', ['aggregate_id', 'event_type', 'payload', 'source', 'actor_id'])
def test_actual_writer_rejects_conflicting_cold_retry(reader, writer, history, changed):
    db, _, _, commit, _ = reader
    repo, _ = writer
    commit()
    args = request(history[0]['one'][0])
    args[changed] = {} if changed == 'payload' else 'different'
    with pytest.raises(ValueError, match='Idempotency key'):
        repo.append_evidence_event(**args)
    assert db.execute('SELECT count(*) FROM quant_app.evidence_ledger_events').fetchone() == (0,)


def test_actual_writer_shared_connection_commits_and_reuses_after_failure(reader, writer):
    _, _, _, commit, runtime = reader
    repo, active = writer
    commit()
    with repo.connect() as conn:
        for number in range(2):
            result = repo.append_evidence_event(aggregate_id='one', event_type='NEXT',
                payload={'n': number}, idempotency_key='shared-'+str(number), _connection=conn)
            assert result['sequence_no'] == 4+number
        with pytest.raises(ValueError, match='Idempotency key'):
            repo.append_evidence_event(aggregate_id='one', event_type='NEXT', payload={},
                                      idempotency_key='shared-0', _connection=conn)
        result = repo.append_evidence_event(aggregate_id='one', event_type='NEXT', payload={},
                                          idempotency_key='after-failure', _connection=conn)
        assert result['sequence_no'] == 6
    assert active['commits'] == 3 and active['rollbacks'] == 1
    assert len(runtime.events('one')) == 6


def test_writer_stale_root_rolls_back_without_append(reader, writer):
    db, _, _, commit, runtime = reader
    repo, _ = writer
    prepare = runtime.prepare_append

    def stale(*args):
        proof = prepare(*args)
        commit()
        return proof

    runtime.prepare_append = stale
    with pytest.raises(LedgerReadError, match='APPEND_ROOT_CHANGED'):
        repo.append_evidence_event(aggregate_id='one', event_type='NEXT', payload={},
                                  idempotency_key='stale-root')
    assert db.execute('SELECT count(*) FROM quant_app.evidence_ledger_events').fetchone() == (0,)


def test_writer_wrong_commissioned_fingerprint_blocks(reader, writer):
    db = reader[0]
    repo, _ = writer
    repo._cold_ledger_fingerprint = 'e'*64
    with pytest.raises(LedgerReadError, match='STAGE_INVALID'):
        repo.append_evidence_event(aggregate_id='one', event_type='NEXT', payload={})
    assert db.execute('SELECT count(*) FROM quant_app.evidence_ledger_events').fetchone() == (3,)


@pytest.mark.parametrize('key', [b'', b'unknown-new-signing-key'])
def test_writer_unverified_key_never_inserts(reader, writer, key):
    db = reader[0]
    repo, active = writer
    repo._evidence_signing_key = key
    repo._evidence_key_id = hashlib.sha256(key).hexdigest()[:16]
    with pytest.raises(LedgerReadError, match='WRITER_KEY_UNVERIFIED'):
        repo.append_evidence_event(aggregate_id='new-aggregate', event_type='NEXT', payload={})
    assert active['commits'] == 0 and active['sql'] is False
    assert db.execute('SELECT count(*) FROM quant_app.evidence_ledger_events').fetchone() == (3,)


def test_writer_stale_hot_terminal_rolls_back(reader, writer, history):
    db, _, _, _, runtime = reader
    repo, _ = writer
    prepare = runtime.prepare_append

    def stale(*args):
        proof = prepare(*args)
        insert_original(db, history[0]['one'][3])
        return proof

    runtime.prepare_append = stale
    with pytest.raises(LedgerReadError, match='APPEND_TERMINAL_CHANGED'):
        repo.append_evidence_event(aggregate_id='one', event_type='NEXT', payload={})
    assert db.execute('SELECT count(*) FROM quant_app.evidence_ledger_events').fetchone() == (4,)


@pytest.mark.parametrize('role', ['quant_storage_archiver', 'equity_research_collector'])
def test_append_lock_boundary_denies_other_workers(reader, role):
    db = reader[0]
    if role == 'equity_research_collector':
        db.execute('CREATE ROLE equity_research_collector NOSUPERUSER NOBYPASSRLS')
        db.execute('GRANT USAGE ON SCHEMA quant_storage TO equity_research_collector')
    db.execute('SET ROLE '+role)
    try:
        with pytest.raises(RuntimeError, match='permission denied'):
            db.execute('SELECT quant_storage.lock_ledger_append(NULL,NULL)')
    finally:
        db.execute('RESET ROLE')


def test_append_lock_boundary_rejects_caller_view_before_reading_it(reader):
    db = reader[0]
    with db.connect():
        db.execute('SET LOCAL ROLE quant_app_runtime')
        db.execute('''CREATE TEMP VIEW quant_storage_append_stage AS SELECT
            0::bigint AS generation,repeat('0',64)::text AS root,
            repeat('0',64)::text AS receipt_sha256,'one'::text AS aggregate_id,
            repeat('f',64)::text AS reader_fingerprint,0::bigint AS cold_sequence,
            repeat('0',64)::text AS cold_hash''')
        with pytest.raises(RuntimeError, match='TEMP_STAGE_UNSAFE'):
            db.execute('SELECT quant_storage.lock_ledger_append(NULL,NULL)')


def test_writer_unknown_driver_failure_never_exposes_details(reader, writer):
    repo, _ = writer
    @contextmanager
    def failed_connect():
        raise RuntimeError('private-connection-and-payload-sentinel')
        yield  # Make an actual context manager; the body never yields.
    repo.connect = failed_connect
    with pytest.raises(LedgerReadError, match='^LEDGER_APPEND_TRANSACTION_FAILED$') as error:
        repo.append_evidence_event(aggregate_id='one', event_type='NEXT', payload={})
    assert 'sentinel' not in str(error.value)


def insert_original(db, row):
    values = [row[name] for name in FIELDS]
    values[9] = json.dumps(values[9])
    db.execute('INSERT INTO quant_app.evidence_ledger_events ('+','.join(FIELDS)+') VALUES ('
               +','.join(['%s']*15)+')', values)


def test_reader_merges_signed_cold_prefix_with_later_original_hot_event(reader, history):
    db, _, publication, commit, runtime = reader
    commit()
    originals = history[0]['one']
    with db.connect():
        db.execute('''CREATE TEMP TABLE quant_storage_append_stage (
            generation bigint,root text,receipt_sha256 text,aggregate_id text,
            reader_fingerprint text,cold_sequence bigint,cold_hash text) ON COMMIT DROP''')
        anchor = publication.receipt.anchor
        db.execute('INSERT INTO quant_storage_append_stage VALUES(%s,%s,%s,%s,%s,%s,%s)',
                   (anchor.generation, anchor.root, anchor.receipt_sha256, 'one', 'f'*64,
                    3, originals[2]['event_hash']))
        insert_original(db, originals[3])
    assert hashes(runtime.events('one')) == hashes(originals[:4])


@pytest.mark.parametrize('kind', ['root-receipt', 'ledger-segment', 'catalog-page'])
def test_missing_cold_object_never_returns_shorter_valid_history(reader, kind):
    _, objects, publication, commit, runtime = reader
    commit()
    target = {'root-receipt': publication.receipt.anchor.receipt_sha256,
              'ledger-segment': publication.prepared.segment.sha256,
              'catalog-page': publication.receipt.anchor.root}[kind]
    objects.data.pop((kind, target))
    with pytest.raises(LedgerReadError):
        runtime.events('one')


@pytest.mark.parametrize('kind', ['root-receipt', 'ledger-segment', 'catalog-page'])
def test_corrupt_cold_bytes_are_not_ignored(reader, kind):
    _, objects, _, commit, runtime = reader
    commit()
    objects.corrupt_kind = kind
    with pytest.raises(LedgerReadError, match='ORIGINAL_HISTORY_UNVERIFIED'):
        runtime.events('one')


def test_unknown_original_signing_key_blocks(reader):
    _, _, _, commit, runtime = reader
    commit()
    runtime.event_keys = {}
    with pytest.raises(LedgerReadError, match='ORIGINAL_HISTORY_UNVERIFIED'):
        runtime.events('one')


def test_missing_protected_head_cannot_claim_hot_ledger_is_complete(reader):
    db, _, _, _, runtime = reader
    db.execute('DELETE FROM quant_storage.ledger_hot_heads')
    with pytest.raises(LedgerReadError, match='PROTECTED_TERMINAL_MISSING'):
        runtime.events('one')


def test_disappeared_hot_tail_is_detected_by_independent_head(reader):
    db, _, _, _, runtime = reader
    db.execute('TRUNCATE quant_app.evidence_ledger_events')
    with pytest.raises(LedgerReadError, match='HOT_TAIL_MISSING'):
        runtime.events('one')


def test_hot_hash_change_does_not_redefine_the_expected_head(reader):
    db, _, _, _, runtime = reader
    db.execute("UPDATE quant_storage.ledger_hot_heads SET event_hash=repeat('d',64)")
    with pytest.raises(LedgerReadError, match='ORIGINAL_HISTORY_UNVERIFIED'):
        runtime.events('one')


def test_uncommissioned_heads_are_not_assumed(reader):
    db, _, _, _, runtime = reader
    db.execute('UPDATE quant_storage.ledger_control SET pruning_enabled=false,heads_enabled=false')
    with pytest.raises(LedgerReadError, match='HEADS_NOT_COMMISSIONED'):
        runtime.events('one')


def test_hot_read_limit_blocks_instead_of_truncating(reader, monkeypatch):
    _, _, _, _, runtime = reader
    monkeypatch.setattr('ledger_runtime_reader.MAX_HOT_ROWS', 2)
    with pytest.raises(LedgerReadError, match='REQUIRES_PAGINATION'):
        runtime.events('one')


def test_sql_permission_failure_is_safe_and_not_an_empty_history(reader):
    db, _, _, _, runtime = reader
    db.execute('REVOKE SELECT ON quant_storage.ledger_hot_heads FROM quant_app_runtime')
    with pytest.raises(LedgerReadError, match='SQL_SNAPSHOT_FAILED'):
        runtime.events('one')


def test_missing_root_never_bootstraps_a_fresh_ledger(reader):
    db, _, _, _, runtime = reader
    db.execute('TRUNCATE quant_storage.catalog_roots')
    with pytest.raises(LedgerReadError, match='ROOT_MISSING'):
        runtime.events('one')


def test_long_chain_exceeds_one_capture_and_one_signature_chunk(reader, history):
    db, _, _, _, runtime = reader
    db.execute('UPDATE quant_storage.ledger_control SET pruning_enabled=false,heads_enabled=false')
    db.execute('TRUNCATE quant_app.evidence_ledger_events,quant_storage.ledger_hot_heads')
    template = {name: history[0]['one'][0][name] for name in FIELDS}
    key = next(iter(runtime.event_keys.values()))
    previous = '0'*64
    rows = []
    for number in range(1, 2475):
        row = {**template, 'event_id': '00000000-0000-0000-0000-'+str(number).zfill(12),
               'sequence_no': number, 'idempotency_key': 'long-'+str(number),
               'previous_hash': previous, 'payload': {'fixture': number}}
        material = {name: row[name] for name in FIELDS if name not in ('payload', 'event_hash')}
        material['payload_json'] = canonical_json(row['payload'])
        row['event_hash'] = hmac.new(key, canonical_json(material).encode(), hashlib.sha256).hexdigest()
        previous = row['event_hash']
        rows.append(row)
    for start in range(0, len(rows), 900):
        batch = rows[start:start+900]
        values = [json.dumps(row[name]) if name == 'payload' else row[name]
                  for row in batch for name in FIELDS]
        db.execute('INSERT INTO quant_app.evidence_ledger_events ('+','.join(FIELDS)+') VALUES '
                   +','.join(['('+','.join(['%s']*15)+')']*len(batch)), values)
    commission(db)
    assert hashes(runtime.events('one')) == hashes(rows)


@pytest.mark.parametrize('aggregate', ['', None, 'a'*901])
def test_invalid_aggregate_is_not_sent_to_sql(reader, aggregate):
    with pytest.raises(LedgerReadError, match='AGGREGATE_INVALID'):
        reader[-1].events(aggregate)
