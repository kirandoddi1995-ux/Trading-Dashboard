"""Synthetic original receipt contracts; no claim of hosted writer commissioning."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator

import pytest

import operational_receipt_history as receipts
from local_state_recovery import ProofState
import local_state_recovery as state
from test_local_state_recovery import KEY, KEY_ID, absent

pytest_plugins = ('test_local_state_recovery',)
RECEIPT_KEY = b'synthetic-receipt-history-key-00000'
KEYRING = {'test-key': RECEIPT_KEY}


def checkpoint(fence: int = 1) -> dict[str, Any]:
    return dict(run_id='run', instrument='ABC', fencing_token=fence, result=None,
                rejection={'category': 'Trend'}, quote_observed_at=None,
                governance_decision_at=None, item='ABC')


def terminal(fence: int = 1) -> dict[str, Any]:
    return dict(run_id='run', fencing_token=fence, status='COMPLETE', finished_at=11.0, error_kind=None)


def seal(rows: list[tuple[str, dict[str, Any]]]) -> bytes:
    return receipts.seal_receipts(rows, signing_key=RECEIPT_KEY, key_id='test-key')


@contextmanager
def cut(data: bytes) -> Iterator[receipts.OperationalReceipts]:
    with receipts.receipt_history(data, independently_expected_sha256=hashlib.sha256(data).hexdigest(),
                                  keyring=KEYRING) as lookup:
        yield lookup


def test_old_and_new_fences_remain_distinct_and_exact() -> None:
    later = checkpoint(2)
    later['item'] = {'ticker': 'ABC', 'changed': True}
    with cut(seal([('checkpoint', checkpoint()), ('checkpoint', later),
                   ('run', terminal()), ('run', terminal(2))])) as lookup:
        assert lookup.checkpoint('run', 'ABC', 1).request == checkpoint()
        assert lookup.checkpoint('run', 'ABC', 2).request == later
        assert lookup.run('run', 1).active_fence == 1
        assert lookup.run('run', 2).active_fence == 2
        assert lookup.run('run', 3).state is ProofState.UNAVAILABLE
        assert lookup.checkpoint('run', 'UNKNOWN', 1).state is ProofState.UNAVAILABLE


def test_detached_nested_payload_and_closed_cut() -> None:
    with cut(seal([('checkpoint', checkpoint())])) as lookup:
        request = lookup.checkpoint('run', 'ABC', 1).request
        assert request is not None
        request['rejection']['category'] = 'tampered'
        assert lookup.checkpoint('run', 'ABC', 1).request == checkpoint()
    with pytest.raises(receipts.ReceiptHistoryError, match='LOOKUP_BLOCKED'):
        lookup.checkpoint('run', 'ABC', 1)


def test_empty_cut_cannot_prove_legacy_absence() -> None:
    with cut(seal([])) as lookup:
        assert lookup.run('run', 1).state is ProofState.UNAVAILABLE


@pytest.mark.parametrize('kind', ['checkpoint', 'run'])
def test_duplicate_original_identity_even_identical_is_blocked(kind: str) -> None:
    request = checkpoint() if kind == 'checkpoint' else terminal()
    with pytest.raises(receipts.ReceiptHistoryError, match='COLLISION'):
        seal([(kind, request), (kind, request)])
    document = json.loads(seal([(kind, request)]))
    document['receipts'] *= 2
    with pytest.raises(receipts.ReceiptHistoryError, match='COLLISION'):
        with cut(json.dumps(document).encode()):
            pytest.fail('duplicate yielded')


@pytest.mark.parametrize('change', ['payload', 'key', 'signature', 'schema', 'format', 'later_row'])
def test_entire_artifact_verified_before_exposure(change: str) -> None:
    document = json.loads(seal([('checkpoint', checkpoint()), ('run', terminal())]))
    row = document['receipts'][1 if change == 'later_row' else 0]
    if change == 'payload':
        row['request']['item'] = 'changed'
    elif change == 'key':
        row['key_id'] = 'unknown'
    elif change in ('signature', 'later_row'):
        row['signature'] = '0' * 64
    elif change == 'schema':
        row['unexpected'] = True
    else:
        row['format'] = 'other'
    with pytest.raises(receipts.ReceiptHistoryError):
        with cut(json.dumps(document).encode()):
            pytest.fail('bad cut yielded')


@pytest.mark.parametrize('fence', [True, 0, -1, 1.0, '1', 2**63])
def test_invalid_fences_not_coerced(fence: Any) -> None:
    request = checkpoint()
    request['fencing_token'] = fence
    with pytest.raises(receipts.ReceiptHistoryError, match='FENCE_INVALID'):
        seal([('checkpoint', request)])


@pytest.mark.parametrize('change', ['both', 'neither', 'extra', 'naive', 'boolean_time',
                                    'negative_time', 'nonfinite', 'integer_key', 'live_status'])
def test_request_failure_paths(change: str) -> None:
    request = terminal() if change in ('boolean_time', 'negative_time', 'live_status') else checkpoint()
    kind = 'run' if 'finished_at' in request else 'checkpoint'
    if change == 'both':
        request['result'] = {}
    elif change == 'neither':
        request['rejection'] = None
    elif change == 'extra':
        request['extra'] = None
    elif change == 'naive':
        request['quote_observed_at'] = '2026-01-01T09:15:00'
    elif change == 'boolean_time':
        request['finished_at'] = True
    elif change == 'negative_time':
        request['finished_at'] = -1
    elif change == 'nonfinite':
        request['rejection'] = {'n': float('nan')}
    elif change == 'integer_key':
        request['rejection'] = {1: 'lossy'}
    else:
        request['status'] = 'RUNNING'
    with pytest.raises(receipts.ReceiptHistoryError):
        seal([(kind, request)])


def test_timestamp_spelling_preserved_not_normalized() -> None:
    request = checkpoint()
    request['quote_observed_at'] = '2022-01-03T09:15:00+05:30'
    with cut(seal([('checkpoint', request)])) as lookup:
        assert lookup.checkpoint('run', 'ABC', 1).request == request


def test_digest_and_duplicate_json_keys_block() -> None:
    data = seal([])
    with pytest.raises(receipts.ReceiptHistoryError, match='DIGEST_MISMATCH'):
        with receipts.receipt_history(data, independently_expected_sha256='0' * 64, keyring=KEYRING):
            pytest.fail('wrong digest yielded')
    data = b'{"format":"operational-receipt-history-v1","receipts":[],"receipts":[]}'
    with pytest.raises(receipts.ReceiptHistoryError, match='DUPLICATE_JSON_KEY'):
        with cut(data):
            pytest.fail('duplicate keys yielded')


def test_limits_fail_before_exposure(monkeypatch: pytest.MonkeyPatch) -> None:
    data = seal([('checkpoint', checkpoint())])
    monkeypatch.setattr(receipts, 'MAX_BYTES', 100)
    with pytest.raises(receipts.ReceiptHistoryError, match='BYTE_LIMIT'):
        seal([('checkpoint', checkpoint())])
    with pytest.raises(receipts.ReceiptHistoryError, match='BYTE_LIMIT'):
        with cut(data):
            pytest.fail('too large yielded')
    monkeypatch.setattr(receipts, 'MAX_BYTES', 10000)
    monkeypatch.setattr(receipts, 'MAX_ROWS', 0)
    with pytest.raises(receipts.ReceiptHistoryError, match='ROW_LIMIT'):
        with cut(data):
            pytest.fail('too many yielded')


def test_actual_five_table_verifier_with_original_receipts(source: Path, tmp_path: Path) -> None:
    original = source.read_bytes()
    with state.capture(lambda: sqlite3.connect(source), {KEY_ID: KEY}, spool_parent=tmp_path) as local:
        with cut(seal([('checkpoint', checkpoint())])) as lookup:
            result = state.verify(local, local.witness, evidence_lookup=absent,
                                  checkpoint_lookup=lookup.checkpoint, run_lookup=lookup.run)
            assert result['status'] == 'PASS'
            assert result['remote_committed_pending_checkpoints'] == 1
            assert result['application_recovery_verified'] is False
    assert source.read_bytes() == original


def test_acknowledged_terminal_and_missing_proof_never_pass(source: Path, tmp_path: Path) -> None:
    with sqlite3.connect(source) as connection:
        connection.execute('UPDATE checkpoint_outbox SET delivered_at=12')
        connection.execute('UPDATE durable_scan_jobs SET remote_finalized_token=1')
    with state.capture(lambda: sqlite3.connect(source), {KEY_ID: KEY}, spool_parent=tmp_path) as local:
        for data, expected in [(seal([('checkpoint', checkpoint()), ('run', terminal())]), 'PASS'),
                               (seal([('checkpoint', checkpoint())]), 'FAILED')]:
            with cut(data) as lookup:
                result = state.verify(local, local.witness, evidence_lookup=absent,
                                      checkpoint_lookup=lookup.checkpoint, run_lookup=lookup.run)
                assert result['status'] == expected


def test_new_ownership_does_not_erase_acknowledged_old_checkpoint(source: Path, tmp_path: Path) -> None:
    later = checkpoint(2)
    later['rejection'] = {'category': 'New evaluation'}
    with sqlite3.connect(source) as connection:
        connection.execute('UPDATE checkpoint_outbox SET delivered_at=12')
        connection.execute('UPDATE durable_scan_jobs SET fencing_token=2')
        connection.execute('UPDATE durable_scan_candidates SET fencing_token=2,rejection_json=?',
                           (json.dumps(later['rejection']),))
        connection.execute('INSERT INTO checkpoint_outbox VALUES(?,?,?,?,?,?,?,?,?)',
                           ('run', 'ABC', '2', json.dumps(later), 13.0, None, 0, 0.0, None))
    before = source.read_bytes()
    with state.capture(lambda: sqlite3.connect(source), {KEY_ID: KEY}, spool_parent=tmp_path) as local:
        with cut(seal([('checkpoint', checkpoint()), ('checkpoint', later)])) as lookup:
            result = state.verify(local, local.witness, evidence_lookup=absent,
                                  checkpoint_lookup=lookup.checkpoint, run_lookup=lookup.run)
            assert result['status'] == 'PASS'
            assert result['remote_committed_pending_checkpoints'] == 1
        current_only = lambda *args: state.RemoteProof(ProofState.PRESENT, later, active_fence=2)
        result = state.verify(local, local.witness, evidence_lookup=absent,
                              checkpoint_lookup=current_only, run_lookup=absent)
        assert result['status'] == 'FAILED'
    assert source.read_bytes() == before


def test_unverified_constructor_and_short_key_rejected() -> None:
    with pytest.raises(receipts.ReceiptHistoryError, match='VERIFIED_ARTIFACT_REQUIRED'):
        receipts.OperationalReceipts({})
    with pytest.raises(receipts.ReceiptHistoryError, match='KEY_INVALID'):
        receipts.seal_receipts([], signing_key=b'short', key_id='test')


def test_oversize_request_rejected_before_full_json_dump(monkeypatch: pytest.MonkeyPatch) -> None:
    request = checkpoint()
    request['rejection'] = {'huge': 'x' * 5000}
    monkeypatch.setattr(receipts, 'MAX_REQUEST_BYTES', 1024)
    monkeypatch.setattr(json, 'dumps', lambda *args, **kwargs: pytest.fail('unbounded dump called'))
    with pytest.raises(receipts.ReceiptHistoryError, match='BYTE_LIMIT'):
        receipts.request_identity('checkpoint', request)
    with pytest.raises(receipts.ReceiptHistoryError, match='IDENTITY_INVALID'):
        receipts._text('x' * 5000)


def test_deep_and_wide_artifacts_rejected_before_json_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(json, 'loads', lambda *args, **kwargs: pytest.fail('unbounded parser called'))
    for data in (b'[' * 40 + b'0' + b']' * 40, b'[' + b'0,' * 50 + b'0]'):
        monkeypatch.setattr(receipts, 'MAX_NODES', 30)
        with pytest.raises(receipts.ReceiptHistoryError, match='COMPLEXITY_LIMIT'):
            with cut(data):
                pytest.fail('complex artifact yielded')


def test_deep_request_and_huge_integer_rejected() -> None:
    nested: Any = 0
    for _ in range(40):
        nested = [nested]
    for value, code in [(nested, 'COMPLEXITY_LIMIT'), (1 << 5000, 'NUMBER_LIMIT')]:
        request = checkpoint()
        request['rejection'] = {'value': value}
        with pytest.raises(receipts.ReceiptHistoryError, match=code):
            seal([('checkpoint', request)])


def test_json_preflight_ignores_escaped_structural_text() -> None:
    request = checkpoint()
    request['rejection'] = {'text': '[{,:' * 100 + '\\"\n'}
    with cut(seal([('checkpoint', request)])) as lookup:
        assert lookup.checkpoint('run', 'ABC', 1).request == request


def test_old_terminal_token_is_still_rejected_by_local_snapshot(source: Path, tmp_path: Path) -> None:
    # Remote history can retain this receipt, but the present five-table schema
    # cannot certify an older finalized token against a newly owned local job.
    with sqlite3.connect(source) as connection:
        connection.execute('UPDATE checkpoint_outbox SET delivered_at=12')
        connection.execute('UPDATE durable_scan_jobs SET fencing_token=2,remote_finalized_token=1')
    with pytest.raises(state.StateRecoveryError):
        with state.capture(lambda: sqlite3.connect(source), {KEY_ID: KEY}, spool_parent=tmp_path):
            pytest.fail('older terminal state accepted without a new local contract')


@pytest.mark.parametrize('encoding', ['utf-16', 'utf-16-le', 'utf-16-be', 'utf-32', 'utf-32-le', 'utf-32-be'])
def test_non_utf8_parser_encoding_cannot_bypass_preflight(
        monkeypatch: pytest.MonkeyPatch, encoding: str) -> None:
    document = '{"escaped":"\\\"","nested":' + '[' * 40 + '0' + ']' * 40 + '}'
    data = document.encode(encoding)
    monkeypatch.setattr(json, 'loads', lambda *args, **kwargs: pytest.fail('alternate-encoding parser called'))
    with pytest.raises(receipts.ReceiptHistoryError):
        with cut(data):
            pytest.fail('non-UTF8 cut yielded')


@pytest.mark.parametrize('data', ['{}', '[]', '{"run_id":"one","run_id":"two"}',
                                   '[' * 40 + '0' + ']' * 40, '\ufeff{}', '\x00{}'])
def test_original_intent_decoder_rejects_invalid_or_ambiguous_text(data: str) -> None:
    with pytest.raises(receipts.ReceiptHistoryError):
        receipts.decode_request('run', data)


def test_original_intent_decoder_exact_bytes_and_request_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    original = json.dumps(terminal(), sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    assert receipts.decode_request('run', original) == terminal()
    with pytest.raises(receipts.ReceiptHistoryError, match='CANONICAL_INTENT_REQUIRED'):
        receipts.decode_request('run', json.dumps(terminal()))
    monkeypatch.setattr(receipts, 'MAX_REQUEST_BYTES', 20)
    with pytest.raises(receipts.ReceiptHistoryError, match='BYTE_LIMIT'):
        receipts.decode_request('run', original)


@pytest.mark.parametrize('constant', ['NaN', 'Infinity', '-Infinity', '1e999', '-1e999'])
def test_object_decoder_rejects_nonfinite_json_even_unused_metadata(constant: str) -> None:
    with pytest.raises(receipts.ReceiptHistoryError, match='NONFINITE_JSON_INVALID'):
        receipts.decode_object('{"unused":' + constant + '}', max_bytes=1024)


def test_public_request_validation_redacts_invalid_timestamp() -> None:
    request = checkpoint()
    request['quote_observed_at'] = 'private-invalid-source-clock'
    with pytest.raises(receipts.ReceiptHistoryError, match='TIME_INVALID') as caught:
        receipts.request_identity('checkpoint', request)
    assert 'private' not in str(caught.value)
