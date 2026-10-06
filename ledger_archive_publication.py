"""Publish and re-read sealed ledger objects before any database mutation.

Injected private object transport only: no credentials, network, database or
runtime side effects at import. SQL guards trust the dedicated archiver; this
verification is therefore mandatory, not replaced by a caller-supplied checksum.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
from typing import Literal, Protocol

from catalog_receipts import RootAnchor, SignedReceipt, sign, verify
from cold_catalog import Catalog, PAGE_BYTES
from ledger_cold_store import ColdLedger, PreparedArchive, prepare
from ledger_segments import MAX_FILE_BYTES

Kind = Literal['ledger-segment', 'catalog-page', 'root-receipt']


class PrivateObjects(Protocol):
    """Private immutable namespace, with conflict detection in the transport."""

    def put(self, kind: Kind, digest: str, data: bytes) -> None:
        """Store pinned bytes; never overwrite a different object at this key."""

    def get(self, kind: Kind, digest: str) -> bytes | None:
        """Retrieve actual stored bytes; None means unavailable, not verified."""


class PublicationError(ValueError):
    """Stable error category without payload or credentials."""


@dataclass(frozen=True)
class PublishedLedger:
    """Proposed archive, not a database commit or deletion authorisation."""

    previous: RootAnchor
    prepared: PreparedArchive = field(repr=False)
    receipt: SignedReceipt = field(repr=False)
    published_at: datetime
    key_id: str


def _exact(objects: PrivateObjects, kind: Kind, digest: str, expected: bytes) -> bytes:
    data = objects.get(kind, digest)
    if data is None:
        raise PublicationError('ARCHIVE_OBJECT_UNAVAILABLE')
    if (not isinstance(data, bytes) or data != expected
            or hashlib.sha256(data).hexdigest() != digest):
        raise PublicationError('ARCHIVE_OBJECT_MISMATCH')
    return data


def verify_publication(publication: PublishedLedger, records: Sequence[Mapping[str, object]],
                       objects: PrivateObjects, event_keys: Mapping[str, bytes],
                       seal_key: bytes, receipt_keys: Mapping[str, bytes]) -> None:
    """Re-read pinned bytes and recover every original event through cold locators.

Re-check immediately before starting the SQL transaction; caches here are bounded
to one segment and its catalog pages. No broad history download/audit is needed.
"""
    prepared = publication.prepared
    receipt_bytes = _exact(objects, 'root-receipt', publication.receipt.anchor.receipt_sha256,
                           publication.receipt.data)
    anchor = verify(receipt_bytes, publication.receipt.anchor.receipt_sha256,
                    publication.previous, receipt_keys)
    if (publication.previous.scope != 'ledger' or anchor != publication.receipt.anchor
            or anchor.root != prepared.catalog.root):
        raise PublicationError('ARCHIVE_ROOT_MISMATCH')
    # Check receipt binds this exact segment, date and key, not merely the root.
    expected_receipt = sign(publication.previous, prepared.catalog.root,
                            prepared.segment.sha256, publication.published_at,
                            publication.key_id, receipt_keys[publication.key_id])
    if expected_receipt != publication.receipt:
        raise PublicationError('ARCHIVE_RECEIPT_MISMATCH')
    segment = _exact(objects, 'ledger-segment', prepared.segment.sha256, prepared.segment.data)
    if len(segment) > MAX_FILE_BYTES:
        raise PublicationError('ARCHIVE_OBJECT_TOO_LARGE')
    pages: dict[str, bytes | None] = {}
    for digest, data in prepared.catalog.pages.items():
        if len(data) > PAGE_BYTES:
            raise PublicationError('ARCHIVE_OBJECT_TOO_LARGE')
        pages[digest] = _exact(objects, 'catalog-page', digest, data)

    def fetch_page(digest: str) -> bytes | None:
        if digest not in pages:
            pages[digest] = objects.get('catalog-page', digest)
        return pages[digest]

    reader = ColdLedger(Catalog(anchor.root, fetch_page),
                        lambda digest: segment if digest == prepared.segment.sha256 else None,
                        event_keys, seal_key)
    # Authenticate once; a 900-row batch must not decompress the segment 900x.
    restored = reader.segment_records(prepared.segment.sha256)
    by_key = {row['idempotency_key']: row for row in restored}
    if (len(records) != len(restored)
            or len({row.get('idempotency_key') for row in records}) != len(records)
            or len({row.get('event_id') for row in records}) != len(records)):
        raise PublicationError('ARCHIVE_RECORD_COUNT_MISMATCH')
    for row in records:
        key = row.get('idempotency_key')
        original = by_key.get(key)
        if original is None or original != {k: v for k, v in row.items() if k != 'duplicate'}:
            raise PublicationError('ARCHIVE_ORIGINAL_RECORD_MISMATCH')
        locator = reader.catalog.lookup(f'idem:{key}')
        event_locator = reader.catalog.lookup(f"event:{row['event_id']}")
        expected = {'aggregate': row['aggregate_id'], 'sequence': row['sequence_no'],
                    'event_id': row['event_id'], 'hash': row['event_hash'],
                    'segment': prepared.segment.sha256}
        if locator != expected or event_locator != expected:
            raise PublicationError('ARCHIVE_LOCATOR_MISMATCH')


def publish(records: Sequence[Mapping[str, object]], previous: RootAnchor,
            objects: PrivateObjects, event_keys: Mapping[str, bytes], seal_key: bytes,
            receipt_keys: Mapping[str, bytes], key_id: str,
            published_at: datetime) -> PublishedLedger:
    """Prepare, upload and verify; any error leaves database/source untouched."""
    if previous.scope != 'ledger':
        raise PublicationError('ARCHIVE_SCOPE_INVALID')
    key = receipt_keys.get(key_id)
    if key is None:
        raise PublicationError('ARCHIVE_RECEIPT_KEY_UNAVAILABLE')
    catalog = Catalog(previous.root, lambda digest: objects.get('catalog-page', digest))
    prepared = prepare(records, catalog, event_keys, seal_key)
    receipt = sign(previous, prepared.catalog.root, prepared.segment.sha256,
                   published_at, key_id, key)
    objects.put('ledger-segment', prepared.segment.sha256, prepared.segment.data)
    for digest, data in prepared.catalog.pages.items():
        objects.put('catalog-page', digest, data)
    objects.put('root-receipt', receipt.anchor.receipt_sha256, receipt.data)
    result = PublishedLedger(previous, prepared, receipt, published_at, key_id)
    verify_publication(result, records, objects, event_keys, seal_key, receipt_keys)
    return result
