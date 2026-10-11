"""Create-only local publication with synthetic original keys and rows."""
from __future__ import annotations

from pathlib import Path
from typing import Any
import datetime as dt
import hashlib
import os

import pytest

from catalog_receipts import genesis, verify
from cold_catalog import Catalog
from cold_local_objects import LocalObjectError, LocalObjects
from ledger_archive_publication import publish, verify_publication
from ledger_cold_store import ColdLedger
from test_ledger_cold_store import SEAL_KEY

pytest_plugins = ('test_ledger_cold_store',)


def test_local_seal_publish_restart_and_original_restore(history: Any, tmp_path: Path) -> None:
    rows, ring = history
    records = [{key: value for key, value in row.items() if key != 'duplicate'}
               for row in rows['one'][:3]]
    receipt_key = b'fixture-root-receipt-key-not-real!'
    proposal = publish(records, genesis('ledger'), LocalObjects(tmp_path, writable=True), ring,
                       SEAL_KEY, {'fixture': receipt_key}, 'fixture',
                       dt.datetime(2026, 10, 8, tzinfo=dt.timezone.utc))
    restarted = LocalObjects(tmp_path)
    verify_publication(proposal, records, restarted, ring, SEAL_KEY, {'fixture': receipt_key})
    receipt = restarted.get('root-receipt', proposal.receipt.anchor.receipt_sha256)
    assert receipt is not None
    anchor = verify(receipt, proposal.receipt.anchor.receipt_sha256,
                    genesis('ledger'), {'fixture': receipt_key})
    reader = ColdLedger(Catalog(anchor.root, lambda digest: restarted.get('catalog-page', digest)),
                        lambda digest: restarted.get('ledger-segment', digest), ring, SEAL_KEY)
    assert list(reader.iter_events('one')) == records


def test_writes_default_disabled(tmp_path: Path) -> None:
    with pytest.raises(LocalObjectError, match='WRITES_DISABLED'):
        LocalObjects(tmp_path).put('catalog-page', 'a' * 64, b'anything')
    assert list(tmp_path.iterdir()) == []


def test_exact_retry_and_damaged_existing_object_are_distinct(tmp_path: Path) -> None:
    store = LocalObjects(tmp_path, writable=True)
    data = b'synthetic-only'
    digest = hashlib.sha256(data).hexdigest()
    store.put('catalog-page', digest, data)
    path = tmp_path / f'catalog-page-{digest}'
    before = path.stat().st_mtime_ns
    store.put('catalog-page', digest, data)
    assert path.stat().st_mtime_ns == before
    path.write_bytes(b'partial')
    with pytest.raises(LocalObjectError, match='DIGEST_MISMATCH'):
        store.put('catalog-page', digest, data)
    assert path.read_bytes() == b'partial'


@pytest.mark.parametrize('kind,digest,data', [('catalog-page', '../bad', b'x'),
    ('catalog-page', 'a' * 64, b'wrong-hash'), ('catalog-page', 'a' * 64, b''),
    ('invalid-kind', 'a' * 64, b'x')])
def test_invalid_identity_or_input_never_creates_file(tmp_path: Path, kind: Any,
                                                    digest: str, data: bytes) -> None:
    with pytest.raises(LocalObjectError):
        LocalObjects(tmp_path, writable=True).put(kind, digest, data)
    assert list(tmp_path.iterdir()) == []


def test_missing_parent_not_created(tmp_path: Path) -> None:
    missing = tmp_path / 'new'
    with pytest.raises(LocalObjectError, match='PARENT_INVALID'):
        LocalObjects(missing)
    assert not missing.exists()


def test_empty_and_oversized_existing_are_not_absence(tmp_path: Path) -> None:
    store = LocalObjects(tmp_path)
    digest = 'a' * 64
    assert store.get('root-receipt', digest) is None
    path = tmp_path / f'root-receipt-{digest}'
    for data in (b'', b'x' * 8193):
        path.write_bytes(data)
        with pytest.raises(LocalObjectError, match='SIZE_INVALID'):
            store.get('root-receipt', digest)


def test_hard_link_is_rejected(tmp_path: Path) -> None:
    data = b'synthetic-original'
    digest = hashlib.sha256(data).hexdigest()
    path = tmp_path / f'catalog-page-{digest}'
    path.write_bytes(data)
    os.link(path, tmp_path / 'alias')
    with pytest.raises(LocalObjectError, match='LINK_REJECTED'):
        LocalObjects(tmp_path).get('catalog-page', digest)


def test_fsync_failure_retains_file_and_redacts_error(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    data = b'synthetic-original'
    digest = hashlib.sha256(data).hexdigest()
    def failed(_fd: int) -> None:
        raise OSError('private path and credentials')
    monkeypatch.setattr('cold_local_objects.os.fsync', failed)
    with pytest.raises(LocalObjectError, match='^LOCAL_OBJECT_WRITE_UNCERTAIN_RETAIN_FILE$'):
        LocalObjects(tmp_path, writable=True).put('catalog-page', digest, data)
    assert (tmp_path / f'catalog-page-{digest}').read_bytes() == data


def test_kind_specific_size_bound(tmp_path: Path) -> None:
    data = b'x' * 8193
    digest = hashlib.sha256(data).hexdigest()
    with pytest.raises(LocalObjectError, match='INPUT_INVALID'):
        LocalObjects(tmp_path, writable=True).put('root-receipt', digest, data)


@pytest.mark.parametrize('value', ['false', 1, None])
def test_string_false_never_enables_writes(tmp_path: Path, value: Any) -> None:
    with pytest.raises(LocalObjectError, match='MODE_INVALID'):
        LocalObjects(tmp_path, writable=value)
