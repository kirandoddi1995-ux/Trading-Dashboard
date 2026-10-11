"""Actual synthetic local outbox verification against staged remote originals."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Any

import pytest

from evidence_ledger import ImmutableEvidenceLedger
import ledger_delivery_proofs as proofs
from ledger_history_consumers import ConsumerReadError, LedgerHistoryConsumers
from ledger_history_stream import VerifiedHistory, stage
from ledger_segments import FIELDS
import local_state_recovery as state
from test_local_state_recovery import KEY, KEY_ID, absent

pytest_plugins = ('test_local_state_recovery',)


class Source:
    def __init__(self, rows: list[dict[str, Any]], keys: dict[str, bytes]) -> None:
        self.rows, self.keys = rows, keys
        self.calls = 0
        self.fail = False
        self.heads = {str(row['aggregate_id']): (int(row['sequence_no']), str(row['event_hash'])) for row in rows}

    @contextmanager
    def staged_history(self, private_parent: Path) -> Iterator[VerifiedHistory]:
        self.calls += 1
        def fence() -> None:
            if self.fail:
                raise RuntimeError('private endpoint detail')
        with stage(self.rows, expected_heads=self.heads, keyring=self.keys,
                   private_parent=private_parent, end_fence=fence) as history:
            yield history


def remote(source: Path, parent: Path) -> tuple[LedgerHistoryConsumers, Source]:
    ledger = ImmutableEvidenceLedger(sqlite3.connect, str(source), KEY)
    rows = [{name: event[name] for name in FIELDS}
            for aggregate in ('equity:a', 'equity:b') for event in ledger.events(aggregate)]
    original = Source(rows, {KEY_ID: KEY})
    return LedgerHistoryConsumers(original, parent), original


def test_committed_but_locally_unacknowledged_evidence_verified_without_resend_or_ack(
        source: Path, tmp_path: Path) -> None:
    adapter, original = remote(source, tmp_path)
    unchanged = source.read_bytes()
    with state.capture(lambda: sqlite3.connect(source), {KEY_ID: KEY}, spool_parent=tmp_path) as local:
        independently_retained = local.witness
        with proofs.evidence_receipts(adapter) as lookup:
            result = state.verify(local, independently_retained, evidence_lookup=lookup.lookup,
                                  checkpoint_lookup=absent, run_lookup=absent)
    assert result['status'] == 'PASS'
    assert result['remote_committed_pending_evidence'] == 2
    assert result['application_recovery_verified'] is False and result['approval_authority'] is False
    assert original.calls == 1 and source.read_bytes() == unchanged


def test_exact_original_request_and_detached_payload(source: Path, tmp_path: Path) -> None:
    adapter, original = remote(source, tmp_path)
    with proofs.evidence_receipts(adapter) as lookup:
        receipt = lookup.lookup('one')
        assert receipt.state is state.ProofState.PRESENT and receipt.request is not None
        assert set(receipt.request) == set(state.REQUEST)
        receipt.request['payload']['n'] = 999
        again = lookup.lookup('one').request
        assert again is not None and again['payload']['n'] == 1
        assert lookup.lookup('never-created').state is state.ProofState.ABSENT
        assert lookup.lookup('never-created').request is None
    assert original.calls == 1
    with pytest.raises(proofs.DeliveryProofError, match='RECEIPT_UNAVAILABLE'):
        lookup.lookup('never-created')  # closed stage never becomes authenticated absence


@pytest.mark.parametrize('failure', ['key_missing', 'last_fence', 'corrupt'])
def test_failed_full_cut_never_yields_a_receipt_or_absence(
        source: Path, tmp_path: Path, failure: str) -> None:
    adapter, original = remote(source, tmp_path)
    if failure == 'key_missing':
        original.keys.clear()
    elif failure == 'last_fence':
        original.fail = True
    else:
        original.rows[-1]['payload']['n'] = 999
    with pytest.raises(ConsumerReadError) as caught:
        with proofs.evidence_receipts(adapter):
            pytest.fail('unverified source yielded')
    assert 'private' not in str(caught.value)


def test_unsigned_history_cannot_certify_presence_or_absence(tmp_path: Path) -> None:
    ledger = ImmutableEvidenceLedger(sqlite3.connect, str(tmp_path / 'unsigned.sqlite'))
    ledger.append(aggregate_id='one', event_type='DECISION_EVALUATED', payload={}, idempotency_key='one')
    original = Source([{name: row[name] for name in FIELDS} for row in ledger.events('one')], {})
    with proofs.evidence_receipts(LedgerHistoryConsumers(original, tmp_path)) as lookup:
        for retry in ('one', 'absent'):
            with pytest.raises(proofs.DeliveryProofError, match='RECEIPT_UNAVAILABLE'):
                lookup.lookup(retry)


@pytest.mark.parametrize('retry', ['', True, 'x' * 901])
def test_malformed_identity_not_coerced_to_absence(source: Path, tmp_path: Path, retry: Any) -> None:
    adapter, _ = remote(source, tmp_path)
    with proofs.evidence_receipts(adapter) as lookup:
        with pytest.raises(proofs.DeliveryProofError, match='RECEIPT_UNAVAILABLE'):
            lookup.lookup(retry)


def test_current_row_or_unverified_callback_cannot_be_a_source() -> None:
    with pytest.raises(proofs.DeliveryProofError, match='STAGED_CONSUMER_REQUIRED'):
        with proofs.evidence_receipts(object()):  # type: ignore[arg-type]
            pytest.fail('unverified source accepted')
