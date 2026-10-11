"""Inactive journal on synthetic SQLite; no installed sender or real state."""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

import pytest

import finalization_intents as journal
from local_state_recovery import ProofState, RemoteProof
from operational_receipt_history import receipt_history, seal_receipts

pytest_plugins = ('test_local_state_recovery',)
KEY = b'synthetic-operational-receipt-key-0000'


def initialized(source: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(source)
    conn.execute('BEGIN IMMEDIATE')
    journal.initialize(conn)
    conn.execute('UPDATE checkpoint_outbox SET delivered_at=12')
    conn.commit()
    return conn


def queue(conn: sqlite3.Connection, fence: int = 1) -> dict[str, Any]:
    conn.execute('BEGIN IMMEDIATE')
    request = journal.queue_terminal(conn, run_id='run', fencing_token=fence, at=13.0)
    conn.commit()
    return request


def proof(request: dict[str, Any]) -> RemoteProof:
    # Actual authenticated immutable artifact adapter, not a current-row proof.
    data = seal_receipts([('run', request)], signing_key=KEY, key_id='test')
    with receipt_history(data, independently_expected_sha256=hashlib.sha256(data).hexdigest(),
                         keyring={'test': KEY}) as lookup:
        return lookup.run(request['run_id'], request['fencing_token'])


def test_original_terminal_intent_and_ack_share_callers_transactions(source: Path) -> None:
    with closing(initialized(source)) as conn:
        conn.execute('BEGIN IMMEDIATE')
        request = journal.queue_terminal(conn, run_id='run', fencing_token=1, at=13)
        assert conn.in_transaction
        conn.rollback()
        assert journal.pending(conn) == []
        original = queue(conn)
        assert request == original
        conn.execute('BEGIN IMMEDIATE')
        assert journal.acknowledge(conn, run_id='run', fencing_token=1, proof=proof(original), at=14) is True
        assert conn.in_transaction
        conn.rollback()
        assert journal.pending(conn) == [original]
        conn.execute('BEGIN IMMEDIATE')
        journal.acknowledge(conn, run_id='run', fencing_token=1, proof=proof(original), at=14)
        conn.commit()
        assert journal.pending(conn) == []
        assert conn.execute('SELECT remote_finalized_token FROM durable_scan_jobs').fetchone() == (1,)


def test_old_intent_survives_takeover_and_ack_cannot_finalize_new_owner(source: Path) -> None:
    with closing(initialized(source)) as conn:
        old = queue(conn)
        conn.execute('UPDATE durable_scan_jobs SET fencing_token=2,remote_finalized_token=NULL,finished_at=15')
        conn.commit()
        new = queue(conn, 2)
        assert journal.pending(conn) == [old, new]
        conn.execute('BEGIN IMMEDIATE')
        assert journal.acknowledge(conn, run_id='run', fencing_token=1, proof=proof(old), at=16) is False
        conn.commit()
        assert conn.execute('SELECT fencing_token,remote_finalized_token FROM durable_scan_jobs').fetchone() == (2, None)
        assert journal.pending(conn) == [new]
        assert conn.execute(f'SELECT count(*) FROM {journal.TABLE}').fetchone() == (2,)


def test_repeated_queue_exact_intent_only(source: Path) -> None:
    with closing(initialized(source)) as conn:
        original = queue(conn)
        assert queue(conn) == original
        assert conn.execute(f'SELECT count(*) FROM {journal.TABLE}').fetchone() == (1,)
        conn.execute('UPDATE durable_scan_jobs SET finished_at=99')
        with pytest.raises(journal.FinalizationError, match='IMMUTABLE_INTENT_CONFLICT'):
            journal.queue_terminal(conn, run_id='run', fencing_token=1, at=14)
        conn.rollback()
        assert journal.pending(conn) == [original]


@pytest.mark.parametrize('state', [ProofState.ABSENT, ProofState.UNAVAILABLE])
def test_missing_remote_proof_never_acknowledged(source: Path, state: ProofState) -> None:
    with closing(initialized(source)) as conn:
        original = queue(conn)
        conn.execute('BEGIN IMMEDIATE')
        with pytest.raises(journal.FinalizationError, match='EXACT_REMOTE_PROOF_REQUIRED'):
            journal.acknowledge(conn, run_id='run', fencing_token=1,
                                proof=RemoteProof(state, active_fence=1), at=14)
        conn.rollback()
        assert journal.pending(conn) == [original]


@pytest.mark.parametrize('change', ['fence', 'payload', 'boolean_fence'])
def test_wrong_proof_fail_closed(source: Path, change: str) -> None:
    with closing(initialized(source)) as conn:
        original = queue(conn)
        altered = dict(original)
        fence: Any = 2 if change == 'fence' else True if change == 'boolean_fence' else 1
        if change == 'payload':
            altered['finished_at'] = 99
        conn.execute('BEGIN IMMEDIATE')
        with pytest.raises(journal.FinalizationError, match='EXACT_REMOTE_PROOF_REQUIRED'):
            journal.acknowledge(conn, run_id='run', fencing_token=1,
                                proof=RemoteProof(ProofState.PRESENT, altered, fence), at=14)
        conn.rollback()
        assert journal.pending(conn) == [original]


def test_pending_checkpoints_block_queue(source: Path) -> None:
    with closing(initialized(source)) as conn:
        conn.execute('UPDATE checkpoint_outbox SET delivered_at=NULL')
        with pytest.raises(journal.FinalizationError, match='CHECKPOINT_DELIVERY_PENDING'):
            journal.queue_terminal(conn, run_id='run', fencing_token=1, at=13)
        conn.rollback()
        assert journal.pending(conn) == []


@pytest.mark.parametrize('status', ['RUNNING', 'RECOVERING'])
def test_nonterminal_job_cannot_be_queued(source: Path, status: str) -> None:
    with closing(initialized(source)) as conn:
        conn.execute('UPDATE durable_scan_jobs SET status=?', (status,))
        with pytest.raises(journal.FinalizationError):
            journal.queue_terminal(conn, run_id='run', fencing_token=1, at=13)
        conn.rollback()


def test_original_intent_and_schema_missing_never_recreated(source: Path) -> None:
    with closing(sqlite3.connect(source)) as conn:
        with pytest.raises(journal.FinalizationError, match='SCHEMA_UNVERIFIED'):
            journal.pending(conn)
    with closing(initialized(source)) as conn:
        conn.execute('BEGIN IMMEDIATE')
        with pytest.raises(journal.FinalizationError, match='ORIGINAL_INTENT_MISSING'):
            journal.acknowledge(conn, run_id='run', fencing_token=1,
                                proof=RemoteProof(ProofState.PRESENT, {} , 1), at=14)
        conn.rollback()


def test_no_implicit_transaction_or_commit(source: Path) -> None:
    with closing(initialized(source)) as conn:
        with pytest.raises(journal.FinalizationError, match='CALLER_TRANSACTION_REQUIRED'):
            journal.queue_terminal(conn, run_id='run', fencing_token=1, at=13)
        with pytest.raises(journal.FinalizationError, match='CALLER_TRANSACTION_REQUIRED'):
            journal.initialize(conn)


@pytest.mark.parametrize('limit', [0, 51, True, 1.0])
def test_batch_limits_not_coerced(source: Path, limit: Any) -> None:
    with closing(initialized(source)) as conn:
        with pytest.raises(journal.FinalizationError, match='BATCH_LIMIT_INVALID'):
            journal.pending(conn, limit=limit)


def test_corrupt_intent_and_ack_digest_never_pass(source: Path) -> None:
    with closing(initialized(source)) as conn:
        original = queue(conn)
        conn.execute(f'UPDATE {journal.TABLE} SET request_json=?', (json.dumps(original),))
        conn.commit()
        with pytest.raises(journal.FinalizationError, match='PENDING_READ_BLOCKED'):
            journal.pending(conn)  # noncanonical original bytes
        conn.execute(f'UPDATE {journal.TABLE} SET request_json=?', (journal._json(original),))
        conn.execute(f'UPDATE {journal.TABLE} SET acknowledged_at=14,remote_request_sha256=?', ('0' * 64,))
        with pytest.raises(journal.FinalizationError, match='ACK_RECEIPT_CORRUPT'):
            journal.acknowledge(conn, run_id='run', fencing_token=1, proof=proof(original), at=15)
        conn.rollback()


def test_current_job_conflict_rolls_back_ack(source: Path) -> None:
    with closing(initialized(source)) as conn:
        original = queue(conn)
        conn.execute('UPDATE durable_scan_jobs SET summary_json=?', ('{"error":"changed"}',))
        with pytest.raises(journal.FinalizationError, match='CURRENT_JOB_CONFLICT'):
            journal.acknowledge(conn, run_id='run', fencing_token=1, proof=proof(original), at=14)
        conn.rollback()
        assert journal.pending(conn) == [original]


def test_new_intent_capacity_blocks_without_losing_old_one(source: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with closing(initialized(source)) as conn:
        original = queue(conn)
        monkeypatch.setattr(journal, 'MAX_INTENTS', 1)
        assert queue(conn) == original  # identical retry is not new allocation
        conn.execute('UPDATE durable_scan_jobs SET fencing_token=2')
        with pytest.raises(journal.FinalizationError, match='CAPACITY_BLOCKED'):
            journal.queue_terminal(conn, run_id='run', fencing_token=2, at=14)
        conn.rollback()
        assert journal.pending(conn) == [original]


def test_byte_capacity_and_time_fail_closed(source: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with closing(initialized(source)) as conn:
        monkeypatch.setattr(journal, 'MAX_JOURNAL_BYTES', 1)
        conn.execute('BEGIN IMMEDIATE')
        with pytest.raises(journal.FinalizationError, match='CAPACITY_BLOCKED'):
            journal.queue_terminal(conn, run_id='run', fencing_token=1, at=13)
        conn.rollback()
        monkeypatch.setattr(journal, 'MAX_JOURNAL_BYTES', 4096)
        original = queue(conn)
        conn.execute('BEGIN IMMEDIATE')
        with pytest.raises(journal.FinalizationError, match='ACK_BEFORE_INTENT'):
            journal.acknowledge(conn, run_id='run', fencing_token=1, proof=proof(original), at=12)
        conn.rollback()
        assert journal.pending(conn) == [original]


@pytest.mark.parametrize('at', [True, -1, float('inf'), float('nan')])
def test_invalid_queue_time(source: Path, at: Any) -> None:
    with closing(initialized(source)) as conn:
        conn.execute('BEGIN IMMEDIATE')
        with pytest.raises(journal.FinalizationError, match='TIME_INVALID'):
            journal.queue_terminal(conn, run_id='run', fencing_token=1, at=at)
        conn.rollback()


def test_oversized_stored_intent_not_fetched_into_python(source: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with closing(initialized(source)) as conn:
        queue(conn)
        conn.execute(f'UPDATE {journal.TABLE} SET request_json=?', ('x' * 5000,))
        conn.commit()
        seen: list[Any] = []
        def blocked(kind: str, data: Any) -> dict[str, Any]:
            seen.append(data)
            raise ValueError('blocked')
        monkeypatch.setattr(journal, 'decode_request', blocked)
        with pytest.raises(journal.FinalizationError, match='PENDING_READ_BLOCKED'):
            journal.pending(conn)
        assert seen == [None]


def test_repeated_ack_idempotent_and_original_time_preserved(source: Path) -> None:
    with closing(initialized(source)) as conn:
        original = queue(conn)
        remote = proof(original)
        for at in (14.0, 15.0):
            conn.execute('BEGIN IMMEDIATE')
            assert journal.acknowledge(conn, run_id='run', fencing_token=1, proof=remote, at=at)
            conn.commit()
        assert conn.execute(f'SELECT acknowledged_at FROM {journal.TABLE}').fetchone() == (14.0,)
        conn.execute('BEGIN IMMEDIATE')
        with pytest.raises(journal.FinalizationError, match='ACK_TIME_CONFLICT'):
            journal.acknowledge(conn, run_id='run', fencing_token=1, proof=remote, at=13.5)
        conn.rollback()


@pytest.mark.parametrize('summary', ['[]', '{"error":"one","error":"two"}', 'x' * 70000,
                                    '{"nested":' + '[' * 40 + '0' + ']' * 40 + '}',
                                    '{"unused":{"overflow":1e999}}', '{"unused":{"overflow":-1e999}}'],
                         ids=['array', 'duplicate-error', 'oversized', 'deep', 'positive-overflow', 'negative-overflow'])
def test_bad_source_summary_never_becomes_a_terminal_intent(source: Path, summary: str) -> None:
    with closing(initialized(source)) as conn:
        conn.execute('UPDATE durable_scan_jobs SET summary_json=?', (summary,))
        with pytest.raises(journal.FinalizationError, match='SUMMARY_INVALID'):
            journal.queue_terminal(conn, run_id='run', fencing_token=1, at=13)
        conn.rollback()
        assert journal.pending(conn) == []


def test_cross_run_substitution_after_takeover_is_not_an_ack(source: Path) -> None:
    with closing(initialized(source)) as conn:
        original = queue(conn)
        substituted = dict(original, run_id='other-run')
        conn.execute('UPDATE durable_scan_jobs SET fencing_token=2')
        conn.execute(f'UPDATE {journal.TABLE} SET request_json=?', (journal._json(substituted),))
        conn.commit()
        with pytest.raises(journal.FinalizationError, match='JOURNAL_IDENTITY_MISMATCH'):
            journal.pending(conn)
        conn.execute('BEGIN IMMEDIATE')
        with pytest.raises(journal.FinalizationError, match='JOURNAL_IDENTITY_MISMATCH'):
            journal.acknowledge(conn, run_id='run', fencing_token=1, proof=proof(substituted), at=14)
        conn.rollback()
        assert conn.execute(f'SELECT acknowledged_at FROM {journal.TABLE}').fetchone() == (None,)
