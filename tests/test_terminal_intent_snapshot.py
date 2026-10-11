"""Synthetic same-cut sixth-table tests; no real state, secrets or network."""
from __future__ import annotations

from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from typing import Any

import pytest

import finalization_intents as intents
import local_state_recovery as state
import terminal_intent_snapshot as six
from test_local_state_recovery import KEY, KEY_ID

pytest_plugins = ('test_local_state_recovery',)


def prepare(path: Path) -> None:
    with closing(sqlite3.connect(path)) as conn:
        conn.execute('BEGIN IMMEDIATE')
        intents.initialize(conn)
        conn.execute('UPDATE checkpoint_outbox SET delivered_at=12')
        intents.queue_terminal(conn, run_id='run', fencing_token=1, at=13)
        conn.commit()


def checkpoint(run: str, instrument: str, token: int) -> state.RemoteProof:
    return state.RemoteProof(state.ProofState.PRESENT, dict(run_id=run, instrument=instrument,
        fencing_token=token, result=None, rejection={'category': 'Trend'},
        quote_observed_at=None, governance_decision_at=None, item='ABC'), token)


def absent_run(run: str, token: int) -> state.RemoteProof:
    return state.RemoteProof(state.ProofState.ABSENT, active_fence=token)


def verify(snapshot: six.SixSnapshot, **overrides: Any) -> dict[str, object]:
    kwargs: dict[str, Any] = dict(expected_primary=snapshot.primary.witness, expected_intents=snapshot.intents,
                  evidence_lookup=lambda _: state.RemoteProof(state.ProofState.ABSENT),
                  checkpoint_lookup=checkpoint, run_lookup=absent_run)
    kwargs.update(overrides)
    return six.verify_six(snapshot, **kwargs)


def capture(path: Path, parent: Path) -> Any:
    return six.capture_six(lambda: sqlite3.connect(path), {KEY_ID: KEY}, spool_parent=parent)


def test_same_cut_pending_and_restore_identity(source: Path, tmp_path: Path) -> None:
    prepare(source)
    with capture(source, tmp_path) as snapshot:
        assert verify(snapshot)['status'] == 'PASS'
        assert verify(snapshot)['pending_intents'] == 1
        assert verify(snapshot)['application_recovery_verified'] is False
        expected_primary, expected_intents = snapshot.primary.witness, snapshot.intents
    restored = tmp_path / 'restored.sqlite'
    with closing(sqlite3.connect(source)) as original, closing(sqlite3.connect(restored)) as target:
        original.backup(target)
    with capture(restored, tmp_path) as snapshot:
        assert verify(snapshot, expected_primary=expected_primary,
                      expected_intents=expected_intents)['status'] == 'PASS'


def test_source_closed_before_either_witness_exposed(source: Path, tmp_path: Path) -> None:
    prepare(source)
    opened: list[sqlite3.Connection] = []
    queries: list[str] = []
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(source)
        opened.append(conn)
        conn.set_trace_callback(queries.append)
        return conn
    with six.capture_six(connect, {KEY_ID: KEY}, spool_parent=tmp_path) as snapshot:
        with pytest.raises(sqlite3.ProgrammingError):
            opened[0].execute('SELECT 1')
        assert verify(snapshot)['status'] == 'PASS'
    assert queries.count('BEGIN') == 1 and queries.count('ROLLBACK') == 1
    assert not any(query.startswith(('CREATE', 'INSERT', 'UPDATE', 'DELETE')) for query in queries)
    assert list(tmp_path.glob('local-recovery-*')) == []


def test_interleaved_writer_cannot_change_journal_cut(source: Path, tmp_path: Path) -> None:
    prepare(source)
    with closing(sqlite3.connect(source)) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
    changed = False
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(source)
        def trace(query: str) -> None:
            nonlocal changed
            if not changed and query.startswith('SELECT') and 'FROM evidence_ledger_events ORDER' in query:
                changed = True
                with closing(sqlite3.connect(source)) as other:
                    other.execute(f'UPDATE {intents.TABLE} SET queued_at=14')
                    other.commit()
        conn.set_trace_callback(trace)
        return conn
    with six.capture_six(connect, {KEY_ID: KEY}, spool_parent=tmp_path) as snapshot:
        body = snapshot.primary._spool.execute('SELECT body FROM terminal_intents').fetchone()[0]
        assert changed and json.loads(body)[3] == 13
    with closing(sqlite3.connect(source)) as conn:
        assert conn.execute(f'SELECT queued_at FROM {intents.TABLE}').fetchone() == (14.0,)


def test_missing_sixth_table_not_treated_as_empty(source: Path, tmp_path: Path) -> None:
    with pytest.raises(state.StateRecoveryError, match='TERMINAL_INTENTS_UNVERIFIED'):
        with capture(source, tmp_path):
            pytest.fail('missing journal accepted')


def test_existing_five_table_capture_remains_unchanged(source: Path, tmp_path: Path) -> None:
    with state.capture(lambda: sqlite3.connect(source), {KEY_ID: KEY}, spool_parent=tmp_path) as before:
        expected = before.witness
    prepare(source)
    with state.capture(lambda: sqlite3.connect(source), {KEY_ID: KEY}, spool_parent=tmp_path) as after:
        # Preparing intentionally changed a checkpoint ACK; journal is still not
        # included in the original witness, which remains explicitly five-table.
        assert len(after.witness.counts) == len(expected.counts) == 5
        assert after._spool.execute("SELECT count(*) FROM sqlite_master WHERE name='terminal_intents'").fetchone() == (0,)


@pytest.mark.parametrize('damage', [
    "UPDATE scan_finalization_intents SET request_json='{}'",
    "UPDATE scan_finalization_intents SET request_json='not json'",
    "UPDATE scan_finalization_intents SET fencing_token=2",
    "UPDATE scan_finalization_intents SET queued_at=-1",
    "UPDATE scan_finalization_intents SET run_id='orphan'",
    "CREATE TRIGGER alternate_journal AFTER INSERT ON scan_finalization_intents BEGIN SELECT 1; END",
])
def test_corrupt_schema_or_rows_block(source: Path, tmp_path: Path, damage: str) -> None:
    prepare(source)
    with closing(sqlite3.connect(source)) as conn:
        conn.execute(damage)
        conn.commit()
    # Some corruption is syntactically valid but requires cross-table/proof
    # validation; both outcomes must fail, not expose a passing partial cut.
    try:
        with capture(source, tmp_path) as snapshot:
            assert verify(snapshot)['status'] == 'FAILED'
    except state.StateRecoveryError:
        pass


@pytest.mark.parametrize('bound', ['MAX_INTENTS', 'MAX_JOURNAL_BYTES', 'MAX_INTENT_BYTES'])
def test_bounds_never_truncate(source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bound: str) -> None:
    prepare(source)
    monkeypatch.setattr(intents, bound, 0)
    with pytest.raises(state.StateRecoveryError):
        with capture(source, tmp_path):
            pytest.fail('truncated bound accepted')


def test_detached_witness_and_closed_spool_fail(source: Path, tmp_path: Path) -> None:
    prepare(source)
    with capture(source, tmp_path) as snapshot:
        assert verify(snapshot, expected_intents=replace(snapshot.intents, sha256='0' * 64))['status'] == 'FAILED'
        snapshot.primary._spool.execute('DELETE FROM terminal_intents')
        assert verify(snapshot)['status'] == 'FAILED'
    assert verify(snapshot)['status'] == 'FAILED'


def test_remote_committed_pending_ack_and_unavailable(source: Path, tmp_path: Path) -> None:
    prepare(source)
    with capture(source, tmp_path) as snapshot:
        body = snapshot.primary._spool.execute('SELECT body FROM terminal_intents').fetchone()[0]
        request = json.loads(json.loads(body)[2])
        def committed(run: str, token: int) -> state.RemoteProof:
            return state.RemoteProof(state.ProofState.PRESENT, request, token)
        assert verify(snapshot, run_lookup=committed)['remote_committed_pending_intent_ack'] == 1
        assert verify(snapshot, run_lookup=lambda *_: state.RemoteProof(state.ProofState.UNAVAILABLE))['status'] == 'FAILED'


def test_old_ack_needs_original_proof_and_never_finalizes_new_job(source: Path, tmp_path: Path) -> None:
    prepare(source)
    with closing(sqlite3.connect(source)) as conn:
        request = intents.pending(conn)[0]
        conn.execute('BEGIN')
        intents.acknowledge(conn, run_id='run', fencing_token=1,
                           proof=state.RemoteProof(state.ProofState.PRESENT, request, 1), at=14)
        conn.execute('UPDATE durable_scan_jobs SET fencing_token=2,remote_finalized_token=NULL,recovered=1,total=0,processed=0')
        conn.commit()
    with capture(source, tmp_path) as snapshot:
        def lookup(run: str, token: int) -> state.RemoteProof:
            return state.RemoteProof(state.ProofState.PRESENT, request, 1) if token == 1 else absent_run(run, token)
        assert verify(snapshot, run_lookup=lookup)['status'] == 'PASS'
        assert verify(snapshot)['status'] == 'FAILED'
    with closing(sqlite3.connect(source)) as conn:
        assert conn.execute('SELECT remote_finalized_token FROM durable_scan_jobs').fetchone() == (None,)


@pytest.mark.parametrize('value', [True, -1, 20_001, 1.0])
def test_bad_witness_count(value: Any) -> None:
    with pytest.raises(six.IntentSnapshotError):
        six.IntentWitness(six.VERSION, value, '0' * 64)


def test_proof_callback_cannot_remove_journal_and_report_pass(source: Path, tmp_path: Path) -> None:
    prepare(source)
    with capture(source, tmp_path) as snapshot:
        def remove(run: str, token: int) -> state.RemoteProof:
            snapshot.primary._spool.execute('DELETE FROM terminal_intents')
            return absent_run(run, token)
        assert verify(snapshot, run_lookup=remove)['status'] == 'FAILED'


def test_current_ack_without_atomic_job_marker_fails(source: Path, tmp_path: Path) -> None:
    prepare(source)
    with closing(sqlite3.connect(source)) as conn:
        request = intents.pending(conn)[0]
        conn.execute('BEGIN')
        intents.acknowledge(conn, run_id='run', fencing_token=1,
            proof=state.RemoteProof(state.ProofState.PRESENT, request, 1), at=14)
        conn.execute('UPDATE durable_scan_jobs SET remote_finalized_token=NULL')
        conn.commit()
    with capture(source, tmp_path) as snapshot:
        assert verify(snapshot, run_lookup=lambda *_: state.RemoteProof(state.ProofState.PRESENT, request, 1))['status'] == 'FAILED'


def test_overlarge_digest_never_becomes_missing(source: Path, tmp_path: Path) -> None:
    prepare(source)
    with closing(sqlite3.connect(source)) as conn:
        conn.execute('PRAGMA ignore_check_constraints=ON')
        conn.execute(f'UPDATE {intents.TABLE} SET remote_request_sha256=?', ('a' * 10_000,))
        conn.commit()
    with pytest.raises(state.StateRecoveryError):
        with capture(source, tmp_path):
            pytest.fail('oversized digest accepted as NULL')
