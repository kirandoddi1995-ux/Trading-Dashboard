"""Synthetic operational metadata only; no historical market values."""
from __future__ import annotations

import hashlib
import io
import json
from contextlib import contextmanager
from typing import Any
import zipfile

import pytest

import archive_catalog_reconcile as subject


def receipt(n: int, **changes: Any) -> dict[str, Any]:
    return dict(dict(batch_id=f'{n:064x}', source_table='mf_nav', row_count=10,
        file_sha256='e' * 64, drive_file_id=f'data-{n}', drive_manifest_id=f'meta-{n}',
        deleted_count=None, verified_at='2022-01-03T00:00:00+00:00', completed_at=None), **changes)


def catalog(rows: list[dict[str, Any]], **changes: Any) -> bytes:
    return json.dumps(dict(dict(format=subject.FORMAT, status='COMPLETE_METADATA_EXPORT',
        measured_at='2022-02-01T00:00:00+00:00', total_count=len(rows),
        truncated=False, records=rows), **changes)).encode()


def bundle(names: list[str]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for name in names:
            archive.writestr(name, b'SYNTHETIC_UNREAD_MEMBER_NOT_MARKET_DATA')
    return stream.getvalue()


def names(n: int) -> list[str]:
    return [f'mf_nav-{n:064x}.{suffix}' for suffix in ('parquet', 'manifest.json')]


def run(raw: bytes, zip_bytes: bytes) -> dict[str, Any]:
    return subject.reconcile(raw, zip_bytes, catalog_sha256=hashlib.sha256(raw).hexdigest(),
                             bundle_sha256=hashlib.sha256(zip_bytes).hexdigest())


def test_all_history_join_opens_no_members_and_preserves_denominators(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = catalog([receipt(1), receipt(2, deleted_count=10, completed_at='2022-01-04T00:00:00Z'),
        receipt(3, deleted_count=4, completed_at='2022-01-05T00:00:00Z'), receipt(4)])
    data = bundle(names(1) + names(2) + names(3)[:1] + names(5) + ['unknown.parquet', 'readme.txt'])
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError('ZIP_MEMBER_OPEN_FORBIDDEN')
    monkeypatch.setattr(zipfile.ZipFile, 'open', forbidden)
    result = run(raw, data)
    assert result['catalog_receipts'] == 4
    table = result['tables']['mf_nav']
    assert table['NO_DELETION_RECORDED'] == 2
    assert table['DELETION_RECORDED_FULL'] == table['DELETION_RECORDED_PARTIAL'] == 1
    assert [table['receipt_' + key] for key in ('paired', 'missing_both', 'missing_parquet', 'missing_manifest')] == [2, 1, 0, 1]
    assert table['zip_without_receipt_paired'] == 1
    assert result['files'] == 9
    assert 2 * result['standard_pairs'] + result['standard_orphan_sides'] + result['nonstandard_archive_names'] + result['other_files'] == result['files']
    assert sum(item['receipts'] for item in result['date_summary']) == 4
    for key in ('logical_restore_verified', 'independent_custody_verified', 'deletion_authorised',
                'training_eligible', 'approval_authority', 'archive_file_hashes_verified',
                'receipt_claims_authenticated', 'historical_row_dates_verified'):
        assert result[key] is False
    assert result['zip_members_opened'] == result['row_pages_decoded'] == 0


@pytest.mark.parametrize('changes', [dict(deleted_count=1), dict(deleted_count=-1),
    dict(deleted_count=True), dict(deleted_count=11), dict(row_count=0), dict(row_count='10'),
    dict(verified_at=None), dict(completed_at='bad'), dict(verified_at='2022-03-01T00:00:00Z'),
    dict(completed_at='2022-01-04T00:00:00Z'), dict(verified_at='2022-01-03'),
    dict(deleted_count=1, completed_at='2022-01-02T00:00:00Z')])
def test_inconsistent_receipts_remain_in_denominator(changes: dict[str, Any]) -> None:
    result = run(catalog([receipt(1, **changes)]), bundle(names(1)))
    assert result['tables']['mf_nav']['INCONSISTENT_RECEIPT'] == 1
    assert result['tables']['mf_nav']['receipt_paired'] == 1
    assert result['catalog_receipts'] == 1


def test_unknown_source_is_redacted_not_dropped() -> None:
    result = run(catalog([receipt(1, source_table='private-unknown-source')]), bundle(names(1)))
    assert result['tables']['UNKNOWN_SOURCE']['receipts'] == 1
    assert result['tables']['mf_nav']['zip_without_receipt_paired'] == 1
    assert 'private-unknown-source' not in json.dumps(result)
    assert 'data-1' not in json.dumps(result)


@pytest.mark.parametrize('changes', [dict(total_count=2), dict(total_count=True), dict(truncated=True),
    dict(status='BOUND_EXCEEDED_REVIEW_REQUIRED'), dict(measured_at='bad'), dict(format='old')])
def test_incomplete_catalog_or_time_is_blocked(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        run(catalog([receipt(1)], **changes), bundle(names(1)))


@pytest.mark.parametrize('rows,code', [([receipt(1), receipt(1)], 'CATALOG_DUPLICATE_BATCH'),
    ([receipt(1), receipt(2, drive_manifest_id='data-1')], 'CATALOG_DUPLICATE_DRIVE_REFERENCE'),
    ([receipt(1, file_sha256='bad')], 'CATALOG_RECEIPT_SHAPE_INVALID'),
    ([receipt(1, drive_file_id='private/path')], 'CATALOG_DRIVE_REFERENCE_INVALID')])
def test_duplicate_or_invalid_identifiers_block(rows: list[dict[str, Any]], code: str) -> None:
    with pytest.raises(ValueError, match=code):
        run(catalog(rows), bundle(names(1)))


def test_empty_and_orphan_catalogs_are_reported_not_successful_custody() -> None:
    result = run(catalog([]), bundle(names(1)[1:]))
    assert result['catalog_receipts'] == 0
    assert result['tables']['mf_nav']['zip_without_receipt_orphan_side'] == 1


def test_duplicate_json_keys_and_pin_mismatch_block() -> None:
    raw = catalog([])
    data = bundle([])
    with pytest.raises(ValueError, match='DUPLICATE_JSON_KEY'):
        run(raw.replace(b'"records":', b'"records": [], "records":'), data)
    with pytest.raises(ValueError, match='EXACT_GENERATION_BYTES_REQUIRED'):
        subject.reconcile(raw + b' ', data, catalog_sha256=hashlib.sha256(raw).hexdigest(),
                          bundle_sha256=hashlib.sha256(data).hexdigest())


def test_utc_date_buckets_are_receipt_dates_not_market_dates() -> None:
    result = run(catalog([receipt(1, verified_at='2022-01-03T01:00:00+05:30', deleted_count=0)]), bundle(names(1)))
    assert result['date_summary'][0]['verified_day'] == '2022-01-02'
    assert result['date_summary'][0]['completed_day'] == 'NOT_RECORDED'


def test_cli_preview_zero_io_and_errors_redacted(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError('PRIVATE_PATH_NOT_READ')
    monkeypatch.setattr(subject.review, '_private_file', forbidden)
    assert subject.main(['--catalog', 'SECRET_PRIVATE_PATH']) == 0
    assert json.loads(capsys.readouterr().out)['input_reads'] == 0
    assert subject.main(['--confirm-metadata-read']) == 2
    result = capsys.readouterr().out
    assert 'EXACT_GENERATION_PINS_REQUIRED' in result
    assert 'SECRET_PRIVATE_PATH' not in result
    assert subject.main(['--SECRET_PRIVATE_PATH']) == 2
    assert 'SECRET_PRIVATE_PATH' not in capsys.readouterr().out


def test_streaming_hash_is_chunk_bounded_before_directory_inspection(monkeypatch: pytest.MonkeyPatch) -> None:
    class Stream(io.BytesIO):
        reads: list[int] = []
        def read(self, size: int = -1) -> bytes:
            self.reads.append(size)
            return super().read(size)
    raw = catalog([])
    data = bundle(['opaque.txt'])
    stream = Stream(data)
    original = subject.review._zip_header
    def header(handle: Any) -> None:
        assert all(0 < size <= 65536 for size in stream.reads)
        assert sum(size for size in stream.reads[:-1]) == len(data)
        original(handle)
    monkeypatch.setattr(subject.review, '_zip_header', header)
    result = subject.reconcile_stream(raw, stream, catalog_sha256=hashlib.sha256(raw).hexdigest(),
                                      bundle_sha256=hashlib.sha256(data).hexdigest())
    assert result['files'] == 1


def test_byte_bounds_precede_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subject.review, 'MAX_ZIP_BYTES', 1)
    with pytest.raises(ValueError, match='ZIP_SIZE_BOUND'):
        subject.reconcile(catalog([]), b'xx', catalog_sha256='a' * 64, bundle_sha256='b' * 64)
    monkeypatch.setattr(subject, 'MAX_CATALOG', 1)
    with pytest.raises(ValueError, match='CATALOG_SIZE_BOUND'):
        subject.reconcile_stream(b'xx', io.BytesIO(b'x'), catalog_sha256='a' * 64, bundle_sha256='b' * 64)


def test_streaming_zip_pin_is_raw_not_normalized() -> None:
    raw, data = catalog([]), bundle([])
    with pytest.raises(ValueError, match='EXACT_GENERATION_BYTES_REQUIRED'):
        subject.reconcile_stream(raw, io.BytesIO(data), catalog_sha256=hashlib.sha256(raw).hexdigest(),
                                  bundle_sha256='a' * 64)


def test_confirmed_cli_streams_guarded_inputs_and_redacts_paths(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    raw, data = catalog([receipt(1)]), bundle(names(1))
    reads: list[str] = []
    @contextmanager
    def private_file(path: Any, bound: int) -> Any:
        reads.append(path.name)
        assert bound > 0
        yield io.BytesIO(raw if path.name == 'SECRET_CATALOG' else data)
    monkeypatch.setattr(subject.review, '_private_file', private_file)
    assert subject.main(['--confirm-metadata-read', '--catalog', 'SECRET_CATALOG', '--bundle', 'SECRET_ZIP',
        '--catalog-sha256', hashlib.sha256(raw).hexdigest(), '--bundle-sha256', hashlib.sha256(data).hexdigest()]) == 0
    output = capsys.readouterr().out
    assert reads == ['SECRET_CATALOG', 'SECRET_ZIP']
    assert 'SECRET_' not in output
    assert json.loads(output)['zip_members_opened'] == 0


def test_cli_os_error_is_not_echoed(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def private_file(*args: Any) -> Any:
        raise OSError('SECRET_PRIVATE_PATH_AND_CONNECTION_VALUE')
    monkeypatch.setattr(subject.review, '_private_file', private_file)
    assert subject.main(['--confirm-metadata-read', '--catalog', 'SECRET_PATH', '--bundle', 'SECRET_ZIP',
                         '--catalog-sha256', 'a' * 64, '--bundle-sha256', 'b' * 64]) == 2
    output = capsys.readouterr().out
    assert 'SECRET_' not in output
    assert json.loads(output)['code'] == 'ALL_CATALOG_REVIEW_REQUIRED'
