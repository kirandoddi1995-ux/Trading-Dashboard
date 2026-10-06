"""Synthetic local originals and independently signed remote requests, offline."""
from dataclasses import replace
from contextlib import closing
import hashlib
import json
import sqlite3

import pytest

from evidence_ledger import ImmutableEvidenceLedger
import local_ledger_recovery as recovery

KEY = b'local-synthetic-signing-key-32-bytes'
KEY_ID = hashlib.sha256(KEY).hexdigest()[:16]


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'source.sqlite'
    connect = lambda: sqlite3.connect(path)
    ledger = ImmutableEvidenceLedger(lambda name: sqlite3.connect(name), str(path), signing_key=KEY)
    for number in range(3):
        ledger.append(aggregate_id='equity:fixture', event_type='DECISION_EVALUATED',
                      payload={'asset_class': 'equity', 'number': number},
                      effective_at='2026-10-01T04:00:00+00:00',
                      idempotency_key=str(number), queue_remote_delivery=True)
    return path, connect, ledger


def snapshot(source):
    return recovery.capture(source[1], {KEY_ID: KEY})


def test_pending_absence_and_independent_remote_envelopes(source, tmp_path):
    local = snapshot(source)
    remote = ImmutableEvidenceLedger(lambda name: sqlite3.connect(name),
        str(tmp_path / 'remote.sqlite'), signing_key=b'different-remote-key')
    first_request = json.loads(local.deliveries[0][0])
    remote_event = remote.append(**first_request)
    assert remote_event['event_hash'] != source[2].events('equity:fixture')[0]['event_hash']
    result = recovery.verify(local, local.witness,
        lambda key: first_request if key == '0' else None)
    assert result['status'] == 'PASS'
    assert result['remote_committed_pending_ack'] == 1
    assert result['application_recovery_verified'] is False
    # A replay retries the original key without adding an original remote event.
    assert remote.append(**first_request)['duplicate'] is True
    assert len(remote.events('equity:fixture')) == 1


def test_ack_requires_authenticated_remote_receipt(source):
    source[2].mark_delivered('0')
    local = snapshot(source)
    assert local.witness.pending == 2
    result = recovery.verify(local, local.witness, lambda key: None)
    assert result['reason'] == 'LOCAL_RECOVERY_ACK_WITHOUT_REMOTE'


def test_snapshot_restore_preserves_reviewed_witness(source, tmp_path):
    expected = snapshot(source)
    target = tmp_path / 'restored.sqlite'
    with closing(source[1]()) as original, closing(sqlite3.connect(target)) as restored:
        original.backup(restored)
    actual = recovery.capture(lambda: sqlite3.connect(target), {KEY_ID: KEY})
    assert actual.witness == expected.witness
    assert recovery.verify(actual, expected.witness, lambda key: None)['status'] == 'PASS'
    assert recovery.verify(actual, replace(expected.witness, pending=0), lambda key: None)[
        'reason'] == 'LOCAL_RECOVERY_SOURCE_MISMATCH'


@pytest.mark.parametrize('damage', ['payload', 'orphan', 'predecessor', 'legacy'])
def test_damaged_or_unconfigured_dependency_blocks(source, damage):
    with source[1]() as conn:
        if damage == 'payload':
            conn.execute("UPDATE evidence_delivery_outbox SET event_json='{}' WHERE idempotency_key='0'")
        elif damage == 'orphan':
            conn.execute("UPDATE evidence_delivery_outbox SET idempotency_key='orphan' WHERE idempotency_key='0'")
        elif damage == 'legacy':
            conn.execute("UPDATE evidence_delivery_outbox SET delivery_lane='legacy' WHERE idempotency_key='0'")
        else:
            conn.execute('DROP TRIGGER evidence_ledger_no_delete')
            conn.execute('DELETE FROM evidence_ledger_events WHERE sequence_no=1')
    with pytest.raises(recovery.LocalRecoveryError):
        snapshot(source)


def test_unknown_key_and_changed_original_fail(source):
    with pytest.raises(recovery.LocalRecoveryError, match='SIGNING_KEY_UNVERIFIED'):
        recovery.capture(source[1], {})
    with source[1]() as conn:
        conn.execute('DROP TRIGGER evidence_ledger_no_update')
        conn.execute("UPDATE evidence_ledger_events SET payload_json='{}' WHERE sequence_no=2")
    with pytest.raises(recovery.LocalRecoveryError, match='ORIGINAL_INVALID'):
        snapshot(source)


@pytest.mark.parametrize('limit', ['MAX_ROWS', 'MAX_BYTES'])
def test_limits_never_truncate_to_valid_prefix(source, monkeypatch, limit):
    monkeypatch.setattr(recovery, limit, 1)
    with pytest.raises(recovery.LocalRecoveryError, match='REQUIRES_SPOOLING'):
        snapshot(source)


def test_lookup_failure_and_mismatch_are_not_missing_evidence(source):
    local = snapshot(source)
    assert recovery.verify(local, local.witness, lambda key: {})['reason'] == 'LOCAL_RECOVERY_REMOTE_REQUEST_MISMATCH'
    def fail(key):
        raise OSError('synthetic-private-credential')
    result = recovery.verify(local, local.witness, fail)
    assert result['reason'] == 'LOCAL_RECOVERY_REMOTE_UNVERIFIED'
    assert 'credential' not in json.dumps(result)
    def misleading(key):
        raise recovery.LocalRecoveryError('synthetic-private-password')
    assert recovery.verify(local, local.witness, misleading)['reason'] == 'LOCAL_RECOVERY_REMOTE_UNVERIFIED'


def test_read_is_query_only_and_closes_before_remote_access(source):
    seen = []
    def connect():
        conn = source[1]()
        conn.set_trace_callback(seen.append)
        return conn
    local = recovery.capture(connect, {KEY_ID: KEY})
    assert 'PRAGMA query_only=ON' in seen and 'BEGIN' in seen and 'ROLLBACK' in seen
    assert not any(query.startswith(('INSERT', 'UPDATE', 'DELETE', 'CREATE')) for query in seen)
    def remote(key):
        # No open source read transaction; exclusive lock is available.
        with source[1]() as conn:
            conn.execute('BEGIN EXCLUSIVE')
            conn.rollback()
        return None
    assert recovery.verify(local, local.witness, remote)['status'] == 'PASS'


def test_empty_unsigned_and_preexisting_transaction_cannot_certify(tmp_path):
    path = tmp_path / 'empty.sqlite'
    ledger = ImmutableEvidenceLedger(lambda name: sqlite3.connect(name), str(path))
    connect = lambda: sqlite3.connect(path)
    with pytest.raises(recovery.LocalRecoveryError, match='SOURCE_EMPTY'):
        recovery.capture(connect, {})
    ledger.append(aggregate_id='fixture', event_type='SIGNAL_CREATED', payload={}, idempotency_key='one')
    with pytest.raises(recovery.LocalRecoveryError, match='SIGNING_KEY_UNVERIFIED'):
        recovery.capture(connect, {})
    def used():
        conn = connect()
        conn.execute('BEGIN')
        return conn
    with pytest.raises(recovery.LocalRecoveryError, match='FRESH_CONNECTION_REQUIRED'):
        recovery.capture(used, {})


@pytest.mark.parametrize('values', [(True, 0, 0, 'a'*64), (1, 1, 2, 'a'*64), (1, 0, 0, 'bad')])
def test_invalid_witness(values):
    with pytest.raises(recovery.LocalRecoveryError, match='WITNESS_INVALID'):
        recovery.LocalWitness(*values)
