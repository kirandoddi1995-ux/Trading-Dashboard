"""Synthetic CSV/ZIP admission: no historical files, downloads or licences assumed."""
from datetime import date, datetime, timezone
import hashlib
import io
import json
import zipfile

import pytest

import overnight_history_admission as history

NOW = datetime(2024, 1, 1, 12, tzinfo=timezone.utc)
COLUMNS = ('Date', 'Close')
RAW = b'Date,Close\n2024-01-01,100\n'


def permission(**updates: object) -> history.Permission:
    record: dict[str, object] = {'version': 'history-usage-permission-v1', 'source': 'nse_index_daily',
        'purpose': 'PRIVATE_DEVELOPMENT_RESEARCH', 'schema_sha256': hashlib.sha256(
            json.dumps(list(COLUMNS), separators=(',', ':')).encode()).hexdigest(),
        'fee_rupees': '0', 'start': '2022-01-01', 'end': '2024-12-31', 'max_original_bytes': 4096,
        'storage_allowed': True, 'revoked': False}
    record.update(updates)
    return history.Permission(json.dumps(record, sort_keys=True, separators=(',', ':')).encode(), b'synthetic')


def admit(raw: bytes = RAW, *, permit: history.Permission | None = None, zipped: bool = False,
          session: date = date(2024, 1, 1)) -> history.AdmittedOriginal:
    return history.admit_csv(raw, source='nse_index_daily', session=session, available_at=NOW,
        received_at=NOW, columns=COLUMNS, permission=permit, verify_permission=lambda _r, _s: True, zipped=zipped)


def test_exact_original_manifest_not_fill_evidence() -> None:
    result = admit(permit=permission())
    body = json.loads(result.manifest)
    assert result.original == RAW and result.rows == (('2024-01-01', '100'),)
    assert body['original_sha256'] == hashlib.sha256(RAW).hexdigest()
    assert not result.intraday_fill_evidence and not body['training_eligible']
    assert not body['source_authenticity_verified'] and not body['row_date_reconciliation_verified']
    assert '100' not in repr(result)


def test_permission_missing_not_implicitly_free() -> None:
    with pytest.raises(history.HistoryError, match='PERMISSION_MISSING'):
        admit()


@pytest.mark.parametrize('updates', [{'fee_rupees': '20'}, {'source': 'unknown'},
    {'purpose': 'SPECULATION'}, {'end': '2025-01-01'}, {'schema_sha256': 'a' * 64},
    {'max_original_bytes': True}, {'max_original_bytes': 1}])
def test_permission_restrictions(updates: dict[str, object]) -> None:
    with pytest.raises(history.HistoryError, match='PERMISSION_UNVERIFIED'):
        admit(permit=permission(**updates))


@pytest.mark.parametrize('session', [date(2025, 1, 1), date(2026, 1, 1), date(2021, 12, 31)])
def test_sealed_period_never_admitted(session: date) -> None:
    with pytest.raises(history.HistoryError, match='DEVELOPMENT_SCOPE'):
        admit(permit=permission(), session=session)


@pytest.mark.parametrize('raw', [b'', b'Date,Close\n', b'Wrong,Close\nx,1\n',
                               b'Date,Close\nx\n', b'Date,Close\nx,1,2\n', b'\xff'])
def test_empty_or_bad_csv(raw: bytes) -> None:
    with pytest.raises(history.HistoryError):
        admit(raw, permit=permission())


def zipped(name: str, data: bytes = RAW) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr(name, data)
    return stream.getvalue()


def test_zip_preserves_original_and_parses_content() -> None:
    raw = zipped('report.csv')
    result = admit(raw, permit=permission(), zipped=True)
    assert result.original == raw and result.rows == (('2024-01-01', '100'),)


@pytest.mark.parametrize('name', ['../data.csv', 'dir/data.csv', 'report.exe', '..csv', '/data.csv'])
def test_zip_paths_not_extracted(name: str) -> None:
    with pytest.raises(history.HistoryError, match='ARCHIVE_INVALID'):
        admit(zipped(name), permit=permission(), zipped=True)


def test_untrusted_signature_before_csv_parse() -> None:
    with pytest.raises(history.HistoryError, match='PERMISSION_UNVERIFIED'):
        history.admit_csv(RAW, source='nse_index_daily', session=date(2024, 1, 1), available_at=NOW,
            received_at=NOW, columns=COLUMNS, permission=permission(), verify_permission=lambda _r, _s: False)


@pytest.mark.parametrize('updates', [{'storage_allowed': False}, {'revoked': True}, {'extra': True}])
def test_revoked_or_unlicensed_storage(updates: dict[str, object]) -> None:
    with pytest.raises(history.HistoryError, match='PERMISSION_UNVERIFIED'):
        admit(permit=permission(**updates))


def test_impossible_availability_before_session() -> None:
    with pytest.raises(history.HistoryError, match='AVAILABILITY_INVALID'):
        history.admit_csv(RAW, source='nse_index_daily', session=date(2024, 1, 1),
            available_at=datetime(2023, 1, 1, tzinfo=timezone.utc), received_at=NOW,
            columns=COLUMNS, permission=permission(), verify_permission=lambda _r, _s: True)


def test_mutable_permission_rejected() -> None:
    from typing import cast
    bad = history.Permission(cast(bytes, bytearray(permission().record)), b'synthetic')
    with pytest.raises(history.HistoryError, match='PERMISSION_UNVERIFIED'):
        admit(permit=bad)


def test_bad_columns_redacted() -> None:
    from typing import cast
    with pytest.raises(history.HistoryError, match='SCHEMA_INVALID'):
        history.admit_csv(RAW, source='nse_index_daily', session=date(2024, 1, 1),
            available_at=NOW, received_at=NOW, columns=cast(tuple[str, ...], ([], 'Close')),
            permission=permission(), verify_permission=lambda _r, _s: True)


def test_nonboolean_zip_rejected() -> None:
    from typing import cast
    with pytest.raises(history.HistoryError, match='TYPE_INVALID'):
        admit(permit=permission(), zipped=cast(bool, 'false'))
