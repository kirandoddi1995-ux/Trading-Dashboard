"""Read-only original-evidence receipts for five-table local recovery.

One fully verified hot/cold cut, no source discovery, resend, local ACK or restore.
Checkpoint/run receipts require SEPARATE authenticated immutable-fence adapters.
No current-row-only substitute or whole-application recovery approval is offered.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json

from evidence_ledger import canonical_json
from ledger_history_consumers import LedgerHistoryConsumers
from ledger_history_stream import VerifiedHistory
from local_state_recovery import ProofState, RemoteProof, REQUEST


class DeliveryProofError(ValueError):
    """Stable failures without source payloads, private paths or driver text."""


class EvidenceReceipts:
    """Context-scoped original request receipts, not delivery permission."""

    def __init__(self, history: VerifiedHistory):
        if not isinstance(history, VerifiedHistory):
            raise DeliveryProofError('DELIVERY_VERIFIED_CUT_REQUIRED')
        self._history = history

    def lookup(self, idempotency_key: str) -> RemoteProof:
        """Original HMAC-covered request or fully verified cut's absence.

        Never prove an unavailable/corrupt/unsigned history as absent. A detached
        receipt is historical at this cut, not a guarantee that no later writer
        can append. Recovery verifier compares it with the ORIGINAL local intent;
        subsequent resends need normal idempotency and append transaction fences.
        """
        try:
            witness = self._history.witness
            if witness.unsigned_events != 0 or witness.hmac_events != witness.rows:
                raise DeliveryProofError('DELIVERY_ORIGINAL_SIGNATURE_COVERAGE_REQUIRED')
            row = self._history.duplicate(idempotency_key)
            if row is None:
                return RemoteProof(ProofState.ABSENT)
            if row['hash_algorithm'] != 'HMAC-SHA256':
                raise DeliveryProofError('DELIVERY_ORIGINAL_SIGNATURE_COVERAGE_REQUIRED')
            request = {name: row[name] for name in REQUEST}
            # Detach nested payloads too; callbacks cannot mutate the staged cut.
            return RemoteProof(ProofState.PRESENT, json.loads(canonical_json(request)))
        except Exception:
            # All source/projection errors are unavailable, never missing.
            raise DeliveryProofError('DELIVERY_EVIDENCE_RECEIPT_UNAVAILABLE') from None


@contextmanager
def evidence_receipts(source: LedgerHistoryConsumers) -> Iterator[EvidenceReceipts]:
    """Pin one remote original-history cut for all outbox evidence lookups.

    Caller still needs a separately verified local source witness, checkpoint
    receipt history and run-finalization receipt history. This does not invoke
    the recovery verifier, mutate restored state or initialise missing custody.
    """
    if not isinstance(source, LedgerHistoryConsumers):
        raise DeliveryProofError('DELIVERY_STAGED_CONSUMER_REQUIRED')
    with source.history() as history:
        yield EvidenceReceipts(history)
