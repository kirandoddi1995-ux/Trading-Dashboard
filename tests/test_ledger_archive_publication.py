"""Private-object publication/readback tests; no network or secrets."""
import datetime as dt
from dataclasses import replace

import pytest

from catalog_receipts import genesis, sign
from ledger_archive_publication import PublicationError, publish, verify_publication
from test_ledger_cold_store import SEAL_KEY

pytest_plugins = ('test_ledger_cold_store',)

RECEIPT_KEY = b'fixture-root-signing-key-not-real!'
NOW = dt.datetime(2026, 10, 6, tzinfo=dt.timezone.utc)


class MemoryObjects:
    def __init__(self, fail_kind=None, corrupt_kind=None):
        self.data = {}
        self.fail_kind = fail_kind
        self.corrupt_kind = corrupt_kind
        self.reads = []

    def put(self, kind, digest, data):
        if self.fail_kind == kind:
            return
        if (kind, digest) in self.data and self.data[kind, digest] != data:
            raise ValueError('OBJECT_CONFLICT')
        self.data[kind, digest] = data

    def get(self, kind, digest):
        self.reads.append((kind, digest))
        data = self.data.get((kind, digest))
        return b'corrupted' if data is not None and self.corrupt_kind == kind else data


def publication(history, objects=None):
    rows, ring = history
    records = [{k: v for k, v in row.items() if k != 'duplicate'}
               for row in rows['one'][:3] + rows['two'][:3]]
    objects = objects or MemoryObjects()
    prepared = publish(records, genesis('ledger'), objects, ring, SEAL_KEY,
                       {'fixture': RECEIPT_KEY}, 'fixture', NOW)
    return records, ring, objects, prepared


def test_readback_restores_every_original_and_reads_segment_once(history):
    records, ring, objects, result = publication(history)
    assert len([kind for kind, _ in objects.reads if kind == 'ledger-segment']) == 1
    assert result.receipt.anchor.generation == 1
    verify_publication(result, records, objects, ring, SEAL_KEY, {'fixture': RECEIPT_KEY})


@pytest.mark.parametrize('kind', ['ledger-segment', 'catalog-page', 'root-receipt'])
@pytest.mark.parametrize('corrupt', [False, True])
def test_each_missing_or_corrupt_remote_object_blocks(history, kind, corrupt):
    objects = MemoryObjects(corrupt_kind=kind) if corrupt else MemoryObjects(fail_kind=kind)
    with pytest.raises(PublicationError, match='ARCHIVE_OBJECT_'):
        publication(history, objects)


def test_remote_object_removed_after_publication_cannot_be_used_as_proof(history):
    records, ring, objects, result = publication(history)
    objects.data.pop(('ledger-segment', result.prepared.segment.sha256))
    with pytest.raises(PublicationError, match='UNAVAILABLE'):
        verify_publication(result, records, objects, ring, SEAL_KEY, {'fixture': RECEIPT_KEY})


def test_wrong_original_rows_block_even_when_every_object_is_valid(history):
    records, ring, objects, result = publication(history)
    records[0] = dict(records[0], source='different')
    with pytest.raises(PublicationError, match='ORIGINAL_RECORD_MISMATCH'):
        verify_publication(result, records, objects, ring, SEAL_KEY, {'fixture': RECEIPT_KEY})


def test_repeated_original_cannot_stand_in_for_an_omitted_event(history):
    records, ring, objects, result = publication(history)
    records[1] = dict(records[0])
    with pytest.raises(PublicationError, match='RECORD_COUNT_MISMATCH'):
        verify_publication(result, records, objects, ring, SEAL_KEY, {'fixture': RECEIPT_KEY})


def test_valid_receipt_for_wrong_segment_cannot_authorise_delete(history):
    records, ring, objects, result = publication(history)
    wrong = sign(result.previous, result.prepared.catalog.root, 'e'*64, NOW,
                 'fixture', RECEIPT_KEY)
    objects.put('root-receipt', wrong.anchor.receipt_sha256, wrong.data)
    with pytest.raises(PublicationError, match='RECEIPT_MISMATCH'):
        verify_publication(replace(result, receipt=wrong), records, objects, ring,
                           SEAL_KEY, {'fixture': RECEIPT_KEY})


def test_unknown_receipt_key_and_wrong_scope_fail_before_upload(history):
    rows, ring = history
    objects = MemoryObjects()
    with pytest.raises(PublicationError, match='KEY_UNAVAILABLE'):
        publish(rows['one'][:2], genesis('ledger'), objects, ring, SEAL_KEY,
                {}, 'fixture', NOW)
    with pytest.raises(PublicationError, match='SCOPE_INVALID'):
        publish(rows['one'][:2], genesis('relations'), objects, ring, SEAL_KEY,
                {'fixture': RECEIPT_KEY}, 'fixture', NOW)
    assert not objects.data


def test_original_signature_failure_precedes_upload(history):
    rows, ring = history
    records = [dict(rows['one'][0], payload={'fabricated': True})]
    objects = MemoryObjects()
    with pytest.raises(ValueError, match='SIGNATURE_MISMATCH'):
        publish(records, genesis('ledger'), objects, ring, SEAL_KEY,
                {'fixture': RECEIPT_KEY}, 'fixture', NOW)
    assert not objects.data
