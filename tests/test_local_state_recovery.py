"""Synthetic five-table source/restore and remote-receipt failures, offline."""
from contextlib import closing
from dataclasses import replace
from datetime import datetime
import hashlib
import json
import shutil
import sqlite3

import pytest

from evidence_ledger import ImmutableEvidenceLedger
import local_state_recovery as recovery
import recovery_bundle

KEY = b'synthetic-local-state-key-not-production'
KEY_ID = hashlib.sha256(KEY).hexdigest()[:16]
AT = '2026-10-07T09:15:00+05:30'


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'source.sqlite'
    ledger = ImmutableEvidenceLedger(sqlite3.connect, str(path), signing_key=KEY)
    ledger.append(aggregate_id='equity:a', event_type='DECISION_EVALUATED',
        payload={'asset_class': 'equity', 'n': 1}, effective_at=AT,
        idempotency_key='one', queue_remote_delivery=True)
    ledger.append(aggregate_id='equity:b', event_type='DECISION_EVALUATED',
        payload={'asset_class': 'equity', 'n': 2}, effective_at=AT,
        idempotency_key='two', queue_remote_delivery=True)
    with sqlite3.connect(path) as conn:
        conn.executescript('''
        CREATE TABLE durable_scan_jobs(
            job_id TEXT PRIMARY KEY,owner TEXT NOT NULL,signature TEXT NOT NULL,
            started_at REAL NOT NULL,finished_at REAL,status TEXT NOT NULL,
            processed INTEGER NOT NULL,total INTEGER NOT NULL,eta_seconds REAL,
            summary_json TEXT NOT NULL,updated_at REAL NOT NULL,
            fencing_token INTEGER NOT NULL DEFAULT 1,metadata_json TEXT NOT NULL DEFAULT '{}',
            recovered INTEGER NOT NULL DEFAULT 0,remote_finalized_token INTEGER);
        CREATE TABLE durable_scan_candidates(
            job_id TEXT NOT NULL,instrument TEXT NOT NULL,item_json TEXT NOT NULL,status TEXT NOT NULL,
            fencing_token INTEGER NOT NULL,result_json TEXT,rejection_json TEXT,
            quote_observed_at TEXT,governance_decision_at TEXT,updated_at REAL NOT NULL,
            PRIMARY KEY(job_id,instrument));
        CREATE TABLE checkpoint_outbox(
            scan_id TEXT NOT NULL,candidate TEXT NOT NULL,fencing_token TEXT NOT NULL,
            checkpoint_json TEXT NOT NULL,created_at REAL NOT NULL,delivered_at REAL,
            attempts INTEGER NOT NULL DEFAULT 0,next_attempt_at REAL NOT NULL DEFAULT 0,
            last_error TEXT,PRIMARY KEY(scan_id,candidate,fencing_token));
        ''')
        conn.execute('INSERT INTO durable_scan_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            ('run', 'owner', 'sig', 10.0, 11.0, 'COMPLETE', 1, 1, 0.0,
             '{"error":null}', 11.0, 1, '{}', 0, None))
        conn.execute('INSERT INTO durable_scan_candidates VALUES(?,?,?,?,?,?,?,?,?,?)',
            ('run', 'ABC', '"ABC"', 'COMPLETE', 1, None, '{"category":"Trend"}', None, None, 11.0))
        request = dict(run_id='run', instrument='ABC', fencing_token=1,
            result=None, rejection={'category': 'Trend'}, quote_observed_at=None,
            governance_decision_at=None, item='ABC')
        conn.execute('INSERT INTO checkpoint_outbox VALUES(?,?,?,?,?,?,?,?,?)',
            ('run', 'ABC', '1', json.dumps(request), 11.0, None, 0, 0.0, None))
    return path


def capture(path, parent, keys=None):
    return recovery.capture(lambda: sqlite3.connect(path),
        {KEY_ID: KEY} if keys is None else keys, spool_parent=parent)


def absent(*args):
    return recovery.RemoteProof(recovery.ProofState.ABSENT, active_fence=1)


def verify(snapshot, expected=None, **callbacks):
    defaults = dict(evidence_lookup=absent, checkpoint_lookup=absent, run_lookup=absent)
    defaults.update(callbacks)
    return recovery.verify(snapshot, snapshot.witness if expected is None else expected, **defaults)


def update(path, query, args=()):
    with sqlite3.connect(path) as conn:
        conn.execute(query, args)


def test_consistent_source_and_restore_witness(source, tmp_path):
    with capture(source, tmp_path) as original:
        expected = original.witness
        assert expected.counts == (2, 2, 1, 1, 1)
        assert verify(original)['status'] == 'PASS'
        assert verify(original)['application_recovery_verified'] is False
        assert 'private detached spool' in repr(original)
    target = tmp_path / 'restore.sqlite'
    with closing(sqlite3.connect(source)) as before, closing(sqlite3.connect(target)) as after:
        before.backup(after)
    with capture(target, tmp_path) as restored:
        assert verify(restored, expected)['status'] == 'PASS'
    assert list(tmp_path.glob('local-recovery-*')) == []


def test_source_connection_closes_before_receipts_and_never_writes(source, tmp_path):
    seen = []
    connections = []
    def connect():
        conn = sqlite3.connect(source)
        conn.set_trace_callback(seen.append)
        connections.append(conn)
        return conn
    with recovery.capture(connect, {KEY_ID: KEY}, spool_parent=tmp_path) as snapshot:
        with pytest.raises(sqlite3.ProgrammingError):
            connections[0].execute('SELECT 1')
        with sqlite3.connect(source) as conn:
            conn.execute('BEGIN EXCLUSIVE')
            conn.rollback()
        assert verify(snapshot)['status'] == 'PASS'
    assert 'PRAGMA query_only=ON' in seen
    assert 'BEGIN' in seen and 'ROLLBACK' in seen
    assert not any(q.startswith(('INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP')) for q in seen)


def test_detached_snapshot_rejects_spool_tampering(source, tmp_path):
    with capture(source, tmp_path) as snapshot:
        snapshot._spool.execute("DELETE FROM records WHERE kind='checkpoint_outbox'")
        assert verify(snapshot)['reason'] == 'STATE_SOURCE_MISMATCH'


def test_closed_snapshot_cannot_pass(source, tmp_path):
    with capture(source, tmp_path) as snapshot:
        expected = snapshot.witness
    assert verify(snapshot, expected)['status'] == 'FAILED'


@pytest.mark.parametrize('table', list(recovery.TABLES))
def test_missing_tables_never_mean_empty_state(source, tmp_path, table):
    update(source, 'DROP TABLE ' + table)
    with pytest.raises(recovery.StateRecoveryError, match='STATE_SCHEMA_UNSUPPORTED'):
        with capture(source, tmp_path):
            pytest.fail('unsupported schema yielded')


@pytest.mark.parametrize('change', [
    "DELETE FROM evidence_delivery_outbox WHERE idempotency_key='one'",
    "DELETE FROM checkpoint_outbox",
    "DELETE FROM durable_scan_jobs",
    "UPDATE evidence_delivery_outbox SET event_json='{}'",
    "UPDATE evidence_delivery_outbox SET delivery_lane='legacy'",
    "UPDATE durable_scan_candidates SET fencing_token=2",
    "UPDATE checkpoint_outbox SET fencing_token='01'",
    "UPDATE durable_scan_jobs SET remote_finalized_token=2",
    "UPDATE durable_scan_jobs SET remote_finalized_token=1",
    "UPDATE checkpoint_outbox SET scan_id='orphan'",
    "UPDATE durable_scan_candidates SET result_json='{}'",
    "UPDATE durable_scan_candidates SET item_json='invalid'",
    "UPDATE durable_scan_jobs SET metadata_json='{""x"":NaN}'",
    "UPDATE durable_scan_jobs SET total=-1",
    "UPDATE checkpoint_outbox SET attempts=-1",
    "UPDATE checkpoint_outbox SET checkpoint_json='{}'",
    "UPDATE evidence_delivery_outbox SET created_at='2026-10-07T00:00:00'",
    "UPDATE durable_scan_candidates SET quote_observed_at='2026-10-07T00:00:00'",
    "UPDATE durable_scan_jobs SET status='INVENTED'",
    "UPDATE durable_scan_candidates SET status='INVENTED'",
    "UPDATE checkpoint_outbox SET created_at=-1",
    "UPDATE durable_scan_jobs SET processed=2",
])
def test_damaged_state_fails_and_removes_spool(source, tmp_path, change):
    update(source, change)
    with pytest.raises(recovery.StateRecoveryError):
        with capture(source, tmp_path):
            pytest.fail('damaged state yielded')
    assert list(tmp_path.glob('local-recovery-*')) == []


def test_changed_restore_without_intrinsic_damage_requires_source_witness(source, tmp_path):
    with capture(source, tmp_path) as original:
        expected = original.witness
    update(source, "UPDATE durable_scan_jobs SET owner='other'")
    with capture(source, tmp_path) as target:
        assert verify(target, expected)['reason'] == 'STATE_SOURCE_MISMATCH'


def test_missing_entire_valid_run_is_caught_by_source_witness(source, tmp_path):
    with capture(source, tmp_path) as original:
        expected = original.witness
    for table in ('checkpoint_outbox', 'durable_scan_candidates', 'durable_scan_jobs'):
        update(source, 'DELETE FROM ' + table)
    with capture(source, tmp_path) as target:
        assert verify(target, expected)['reason'] == 'STATE_SOURCE_MISMATCH'


def test_unknown_column_and_schema_change_fail(source, tmp_path):
    update(source, 'ALTER TABLE durable_scan_jobs ADD COLUMN extra TEXT')
    with pytest.raises(recovery.StateRecoveryError, match='SCHEMA_UNSUPPORTED'):
        with capture(source, tmp_path):
            pytest.fail('extra column yielded')


def test_schema_fingerprint_includes_triggers(source, tmp_path):
    with capture(source, tmp_path) as original:
        expected = original.witness
    update(source, 'DROP TRIGGER evidence_ledger_no_delete')
    with capture(source, tmp_path) as target:
        assert target.witness.schema_sha256 != expected.schema_sha256
        assert verify(target, expected)['reason'] == 'STATE_SOURCE_MISMATCH'


def test_unknown_and_wrong_keys_and_changed_signatures_block(source, tmp_path):
    for keys in ({}, {KEY_ID: b'wrong'}):
        with pytest.raises(recovery.StateRecoveryError):
            with capture(source, tmp_path, keys):
                pytest.fail('bad key yielded')
    update(source, 'DROP TRIGGER evidence_ledger_no_update')
    update(source, "UPDATE evidence_ledger_events SET event_hash=? WHERE idempotency_key='one'", ('a' * 64,))
    with pytest.raises(recovery.StateRecoveryError, match='ORIGINAL_INVALID'):
        with capture(source, tmp_path):
            pytest.fail('bad signature yielded')


def test_legacy_schema_requires_explicit_binding_not_current_key(source, tmp_path):
    update(source, 'DROP TRIGGER evidence_ledger_no_update')
    with sqlite3.connect(source) as conn:
        columns = ','.join(recovery.EVENT_FIELDS)
        raw = conn.execute('SELECT ' + columns + " FROM evidence_ledger_events WHERE idempotency_key='one'").fetchone()
        row = dict(zip(recovery.EVENT_FIELDS, raw))
        row['schema_version'], row['key_id'] = 1, None
        material = ImmutableEvidenceLedger._material(**{k: row[k] for k in recovery.EVENT_FIELDS if k != 'event_hash'})
        import hmac
        signature = hmac.new(KEY, material.encode(), hashlib.sha256).hexdigest()
        conn.execute("UPDATE evidence_ledger_events SET schema_version=1,key_id=NULL,event_hash=? WHERE idempotency_key='one'",
                     (signature,))
    with pytest.raises(recovery.StateRecoveryError, match='SIGNING_KEY_UNVERIFIED'):
        with capture(source, tmp_path):
            pytest.fail('implicit legacy key yielded')
    with capture(source, tmp_path, {KEY_ID: KEY, recovery.LEGACY_KEY_ID: KEY}) as snapshot:
        assert verify(snapshot)['status'] == 'PASS'


def test_pending_remote_commits_are_not_replayed_or_acknowledged(source, tmp_path):
    with capture(source, tmp_path) as snapshot:
        def evidence(key):
            return recovery.RemoteProof(recovery.ProofState.PRESENT,
                json.loads(recovery._request(snapshot._spool, key)))
        def checkpoint(run, instrument, fence):
            row = recovery._get(snapshot._spool, 'checkpoint_outbox', [run, instrument, str(fence)])
            return recovery.RemoteProof(recovery.ProofState.PRESENT,
                json.loads(row['checkpoint_json']), active_fence=fence)
        result = verify(snapshot, evidence_lookup=evidence, checkpoint_lookup=checkpoint)
        assert result['status'] == 'PASS'
        assert result['remote_committed_pending_evidence'] == 2
        assert result['remote_committed_pending_checkpoints'] == 1
    with sqlite3.connect(source) as conn:
        assert conn.execute('SELECT count(*) FROM checkpoint_outbox WHERE delivered_at IS NULL').fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM evidence_delivery_outbox WHERE delivered_at IS NULL').fetchone()[0] == 2


@pytest.mark.parametrize('table,stamp', [('evidence_delivery_outbox', "'2026-10-07T05:00:00+00:00'"),
                                     ('checkpoint_outbox', '12.0')])
def test_ack_without_remote_is_not_pass(source, tmp_path, table, stamp):
    update(source, 'UPDATE ' + table + ' SET delivered_at=' + stamp)
    with capture(source, tmp_path) as snapshot:
        assert verify(snapshot)['reason'] == 'STATE_ACK_WITHOUT_REMOTE'


@pytest.mark.parametrize('proof', [None, {}, True,
    recovery.RemoteProof('AUTHENTICATED_ABSENT'),
    recovery.RemoteProof(recovery.ProofState.UNAVAILABLE),
    recovery.RemoteProof(recovery.ProofState.ABSENT, {'invented': True})])
def test_unverified_remote_is_not_absence(source, tmp_path, proof):
    with capture(source, tmp_path) as snapshot:
        assert verify(snapshot, evidence_lookup=lambda key: proof)['reason'] == 'STATE_REMOTE_UNVERIFIED'


def test_remote_mismatch_and_exception_are_sanitized(source, tmp_path):
    with capture(source, tmp_path) as snapshot:
        assert verify(snapshot, evidence_lookup=lambda key:
            recovery.RemoteProof(recovery.ProofState.PRESENT, {}))['reason'] == 'STATE_REMOTE_REQUEST_MISMATCH'
        def fail(key):
            raise OSError('synthetic-private-password')
        result = verify(snapshot, evidence_lookup=fail)
        assert result['reason'] == 'STATE_REMOTE_UNVERIFIED'
        assert 'password' not in json.dumps(result)
        def misleading(key):
            raise recovery.StateRecoveryError('synthetic-private-key')
        assert verify(snapshot, evidence_lookup=misleading)['reason'] == 'STATE_REMOTE_UNVERIFIED'


@pytest.mark.parametrize('fence', [None, True, 0, 2])
def test_remote_stale_or_unknown_fence_blocks(source, tmp_path, fence):
    with capture(source, tmp_path) as snapshot:
        assert verify(snapshot, checkpoint_lookup=lambda *args:
            recovery.RemoteProof(recovery.ProofState.ABSENT, active_fence=fence))['reason'] == 'STATE_REMOTE_FENCE_MISMATCH'


def test_conflict_quarantine_is_preserved(source, tmp_path):
    update(source, "UPDATE checkpoint_outbox SET last_error='CONFLICT'")
    with capture(source, tmp_path) as snapshot:
        assert verify(snapshot)['reason'] == 'STATE_CHECKPOINT_QUARANTINED'


def test_pending_old_fence_blocks_capture(source, tmp_path):
    update(source, 'UPDATE durable_scan_jobs SET fencing_token=2')
    with pytest.raises(recovery.StateRecoveryError, match='STALE_PENDING_CHECKPOINT'):
        with capture(source, tmp_path):
            pytest.fail('stale pending yielded')


def test_finalization_receipt_is_independent_and_required(source, tmp_path):
    update(source, 'UPDATE checkpoint_outbox SET delivered_at=12')
    update(source, 'UPDATE durable_scan_jobs SET remote_finalized_token=1')
    with capture(source, tmp_path) as snapshot:
        def checkpoint(*args):
            row = recovery._get(snapshot._spool, 'checkpoint_outbox', ['run', 'ABC', '1'])
            return recovery.RemoteProof(recovery.ProofState.PRESENT, json.loads(row['checkpoint_json']), 1)
        assert verify(snapshot, checkpoint_lookup=checkpoint)['reason'] == 'STATE_ACK_WITHOUT_REMOTE'
        def run(run_id, fence):
            return recovery.RemoteProof(recovery.ProofState.PRESENT,
                dict(run_id=run_id, fencing_token=fence, status='COMPLETE', finished_at=11.0, error_kind=None), fence)
        assert verify(snapshot, checkpoint_lookup=checkpoint, run_lookup=run)['finalized_receipts_checked'] == 1


@pytest.mark.parametrize('name', ['MAX_ROWS', 'MAX_ROW_BYTES', 'MAX_BYTES', 'MAX_SCHEMA_BYTES'])
def test_bounds_never_return_a_truncated_pass(source, tmp_path, monkeypatch, name):
    monkeypatch.setattr(recovery, name, 1)
    with pytest.raises(recovery.StateRecoveryError):
        with capture(source, tmp_path):
            pytest.fail('bound yielded')
    assert list(tmp_path.glob('local-recovery-*')) == []


def test_more_than_old_in_memory_bound_streams_offline(source, tmp_path):
    # No ledger original list or MAX_ROWS-sized Python identity dictionary is used.
    with sqlite3.connect(source) as conn:
        conn.executemany('INSERT INTO durable_scan_jobs SELECT ?,owner,signature,started_at,'
            'finished_at,status,0,0,eta_seconds,summary_json,updated_at,'
            'fencing_token,metadata_json,recovered,remote_finalized_token FROM durable_scan_jobs WHERE job_id=?',
            ((f'extra-{n:05}', 'run') for n in range(20_001)))
    with capture(source, tmp_path) as snapshot:
        assert snapshot.witness.counts[2] == 20_002
        assert verify(snapshot)['status'] == 'PASS'


def test_missing_directory_and_connection_errors_are_redacted(source, tmp_path):
    with pytest.raises(recovery.StateRecoveryError, match='PRIVATE_SPOOL_REQUIRED'):
        with capture(source, tmp_path / 'not-created'):
            pytest.fail('missing directory yielded')
    def fail():
        raise OSError('synthetic-secret-source-url')
    with pytest.raises(recovery.StateRecoveryError, match='STATE_SNAPSHOT_UNVERIFIED') as error:
        with recovery.capture(fail, {KEY_ID: KEY}, spool_parent=tmp_path):
            pytest.fail('connection failure yielded')
    assert 'secret' not in str(error.value)


def test_preexisting_transaction_cannot_be_used(source, tmp_path):
    def connect():
        conn = sqlite3.connect(source)
        conn.execute('BEGIN')
        return conn
    with pytest.raises(recovery.StateRecoveryError, match='FRESH_CONNECTION_REQUIRED'):
        with recovery.capture(connect, {KEY_ID: KEY}, spool_parent=tmp_path):
            pytest.fail('existing transaction yielded')


@pytest.mark.parametrize('change', [dict(version='wrong'), dict(counts=(1,)),
    dict(counts=(True, 0, 0, 0, 0)), dict(counts=(0, 1, 0, 0, 0)), dict(state_sha256='wrong')])
def test_invalid_witness(change):
    values = dict(version=recovery.VERSION, counts=(1, 0, 0, 0, 0),
                  schema_sha256='a' * 64, state_sha256='b' * 64)
    values.update(change)
    with pytest.raises(recovery.StateRecoveryError, match='WITNESS_INVALID'):
        recovery.StateWitness(**values)


def test_changed_expected_counts_cannot_pass(source, tmp_path):
    with capture(source, tmp_path) as snapshot:
        expected = replace(snapshot.witness, counts=(2, 2, 0, 1, 1))
        assert verify(snapshot, expected)['reason'] == 'STATE_SOURCE_MISMATCH'


def test_single_snapshot_is_not_a_mix_of_two_source_times(source, tmp_path, monkeypatch):
    with sqlite3.connect(source) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
    with capture(source, tmp_path) as before:
        expected = before.witness
    original_schema = recovery._schema
    def schema_then_write(conn):
        fingerprint = original_schema(conn)
        # A separate WAL writer commits after the snapshot has already begun.
        update(source, "UPDATE durable_scan_jobs SET owner='later-owner'")
        return fingerprint
    monkeypatch.setattr(recovery, '_schema', schema_then_write)
    with capture(source, tmp_path) as snapshot:
        assert snapshot.witness == expected
    monkeypatch.setattr(recovery, '_schema', original_schema)
    with capture(source, tmp_path) as after:
        assert after.witness != expected


def test_source_time_bound_fails_without_partial_snapshot(source, tmp_path, monkeypatch):
    monkeypatch.setattr(recovery, 'MAX_SOURCE_SECONDS', -1.0)
    with pytest.raises(recovery.StateRecoveryError):
        with capture(source, tmp_path):
            pytest.fail('time-bound source yielded')
    assert list(tmp_path.glob('local-recovery-*')) == []


def test_historical_finalization_is_not_misrepresented_as_current(source, tmp_path):
    update(source, 'UPDATE checkpoint_outbox SET delivered_at=12')
    update(source, 'UPDATE durable_scan_jobs SET fencing_token=2,remote_finalized_token=1')
    with pytest.raises(recovery.StateRecoveryError, match='HISTORICAL_FINALIZATION_REQUIRES_ADAPTER'):
        with capture(source, tmp_path):
            pytest.fail('historical finalized fence yielded')


@pytest.mark.parametrize('damage', ["DELETE FROM durable_scan_candidates",
    "UPDATE durable_scan_candidates SET status='PENDING'",
    "UPDATE durable_scan_jobs SET processed=0"])
def test_complete_job_requires_real_completed_candidates(source, tmp_path, damage):
    update(source, damage)
    with pytest.raises(recovery.StateRecoveryError, match='JOB_COMPLETENESS_UNPROVEN'):
        with capture(source, tmp_path):
            pytest.fail('phantom complete job yielded')


def test_empty_originals_cannot_certify_state(source, tmp_path):
    update(source, 'DROP TRIGGER evidence_ledger_no_delete')
    update(source, 'DELETE FROM evidence_ledger_events')
    update(source, 'DELETE FROM evidence_delivery_outbox')
    with pytest.raises(recovery.StateRecoveryError):
        with capture(source, tmp_path):
            pytest.fail('empty originals yielded')


def test_cleanup_failure_is_redacted(source, tmp_path):
    class Connection(sqlite3.Connection):
        def close(self):
            super().close()
            raise OSError('synthetic-private-source-path')
    with pytest.raises(recovery.StateRecoveryError) as error:
        with recovery.capture(lambda: sqlite3.connect(source, factory=Connection),
                              {KEY_ID: KEY}, spool_parent=tmp_path):
            pytest.fail('cleanup-failing connection yielded')
    assert 'private-source-path' not in str(error.value)
    assert list(tmp_path.glob('local-recovery-*')) == []


def test_spool_creation_failure_is_redacted(source, tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise PermissionError('synthetic-private-directory')
    monkeypatch.setattr(recovery.tempfile, 'TemporaryDirectory', fail)
    with pytest.raises(recovery.StateRecoveryError, match='PRIVATE_SPOOL_UNAVAILABLE') as error:
        with capture(source, tmp_path):
            pytest.fail('unavailable spool yielded')
    assert 'private-directory' not in str(error.value)


def test_json_duplicate_keys_and_nonfinite_fail():
    for value in ('{"a":1,"a":2}', 'NaN', 'Infinity', None):
        with pytest.raises(recovery.StateRecoveryError, match='JSON_INVALID'):
            recovery._json(value)


@pytest.mark.parametrize('damage', ['none', 'outside_witness', 'delete_intent'])
def test_authenticated_disposable_image_restore(source, tmp_path, damage):
    """Bind an original source witness and full image; never infer it from restore."""
    update(source, 'CREATE TABLE auxiliary_metadata(value TEXT)')
    update(source, "INSERT INTO auxiliary_metadata VALUES('original')")
    with capture(source, tmp_path) as snapshot:
        original_witness = snapshot.witness
    image = tmp_path / 'backup.sqlite'
    with closing(sqlite3.connect(source)) as before, closing(sqlite3.connect(image)) as after:
        before.backup(after)
    contract = recovery_bundle.BackupContract('backup:synthetic_restore', (
        recovery_bundle.Binding('primary_state', 'local_store', 'sqlite-image-v1'),))
    with image.open('rb') as stream:
        identities = (recovery_bundle.measure('primary_state', stream),)
    custody_key = b'synthetic-separate-custody-key-32bytes'
    sealed = recovery_bundle.seal(contract, original_witness, identities,
        bundle_id='00000000-0000-4000-8000-000000000001',
        cut_id='00000000-0000-4000-8000-000000000002', at=datetime.fromisoformat(AT),
        previous=recovery_bundle.genesis(contract), key_id='custody', key=custody_key)
    target = tmp_path / 'restored.sqlite'
    shutil.copyfile(image, target)  # Closed, disposable test image, never a live DB.
    if damage == 'delete_intent':
        update(target, 'DELETE FROM evidence_delivery_outbox')
        with pytest.raises(recovery.StateRecoveryError):
            with capture(target, tmp_path):
                pytest.fail('missing original intent accepted')
        return
    if damage == 'outside_witness':
        update(target, "UPDATE auxiliary_metadata SET value='changed'")
    with capture(target, tmp_path) as restored:
        restored_witness = restored.witness
    assert restored_witness == original_witness
    with target.open('rb') as stream:
        observed = (recovery_bundle.measure('primary_state', stream),)
    arguments = dict(checkpoint=sealed.checkpoint, contract=contract,
        keyring={'custody': custody_key}, observed=observed, restored_witness=restored_witness)
    if damage == 'outside_witness':
        with pytest.raises(recovery_bundle.BundleError, match='RESTORED_ARTIFACT_MISMATCH'):
            recovery_bundle.verify_restore(sealed.data, **arguments)
    else:
        result = recovery_bundle.verify_restore(sealed.data, **arguments)
        assert result['status'] == 'BACKUP_IDENTITIES_VERIFIED'
        assert result['application_recovery_verified'] is False
