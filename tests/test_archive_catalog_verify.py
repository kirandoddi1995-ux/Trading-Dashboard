"""876 synthetic batches; opaque row pages deliberately cannot establish restore."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import io
import json
from typing import Any
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import archive_catalog_verify as subject


def encode(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def pack(files: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return stream.getvalue()


@pytest.fixture(scope='module')
def cohort() -> tuple[dict[str, Any], dict[str, bytes]]:
    rows: list[dict[str, Any]] = []
    files: dict[str, bytes] = {}
    for table, count in subject.EXPECTED.items():
        for n in range(count):
            batch = f'{len(rows) + 1:064x}'
            spec = subject.review.SPECS[table]
            fields = [pa.field(name, pa.date32() if kind == 'date' else
                pa.timestamp('us', tz='UTC') if kind == 'timestamptz' else pa.string())
                for name, kind in spec.items()]
            fields.append(pa.field('_row_json', pa.string(), nullable=False))
            schema = pa.schema(fields, metadata={b'quant_archive': encode(dict(format=subject.review.FORMAT,
                table=table, batch_id=batch, postgres_types=spec, numeric_encoding='decimal-string'))})
            values = {name: [None] for name in spec}
            values['_row_json'] = ['SYNTHETIC_OPAQUE_NOT_RECOVERABLE_JSON']
            stream = io.BytesIO()
            pq.write_table(pa.Table.from_pydict(values, schema=schema), stream, compression='zstd', write_statistics=False)
            data = stream.getvalue()
            digest = hashlib.sha256(data).hexdigest()
            no_delete = table in ('universe_membership', 'equity_research.outcomes') and n == 0
            row = dict(batch_id=batch, source_table=table, row_count=1, file_sha256=digest,
                drive_file_id='synthetic-data-' + batch, drive_manifest_id='synthetic-meta-' + batch,
                deleted_count=None if no_delete else 1, verified_at='2022-01-03T00:00:00Z',
                completed_at=None if no_delete else '2022-01-04T00:00:00Z')
            manifest = dict(format=subject.review.FORMAT, batch_id=batch, source_table=table, rows=1,
                sha256=digest, drive_file_id=row['drive_file_id'], postgres_types=spec,
                numeric_encoding='decimal-string')
            stem = table + '-' + batch
            files[stem + '.parquet'] = data
            files[stem + '.manifest.json'] = encode(manifest)
            rows.append(row)
    files.update({f'unknown-{n}.parquet': b'UNOPENED_SYNTHETIC' for n in range(5)})
    files['note.txt'] = b'UNOPENED_SYNTHETIC'
    return dict(format=subject.catalog.FORMAT, status='COMPLETE_METADATA_EXPORT',
        measured_at='2022-02-01T00:00:00Z', total_count=len(rows), truncated=False, records=rows), files


def run(value: dict[str, Any], files: dict[str, bytes]) -> dict[str, Any]:
    raw, data = encode(value), pack(files)
    return subject.verify_bytes(raw, data, catalog_sha256=hashlib.sha256(raw).hexdigest(),
                                 bundle_sha256=hashlib.sha256(data).hexdigest())


def test_all_876_bytes_and_footers_without_row_read_or_extra_member_open(
        cohort: tuple[dict[str, Any], dict[str, bytes]], monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError('NO_ROW_READER_ALLOWED')
    for name in ('read', 'read_row_group', 'read_row_groups', 'iter_batches', 'scan_contents'):
        monkeypatch.setattr(pq.ParquetFile, name, forbidden)
    monkeypatch.setattr(pq, 'read_table', forbidden)
    original = zipfile.ZipFile.open
    opened: list[str] = []
    def open_member(archive: zipfile.ZipFile, member: Any, *args: Any, **kwargs: Any) -> Any:
        name = member.filename if isinstance(member, zipfile.ZipInfo) else member
        assert 'unknown-' not in name and name != 'note.txt'
        opened.append(name)
        return original(archive, member, *args, **kwargs)
    monkeypatch.setattr(zipfile.ZipFile, 'open', open_member)
    # Pack before installing the read-only member wrapper, which rejects writes.
    value, files = cohort
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        monkeypatch.setattr(zipfile.ZipFile, 'open', original)
        for name, body in files.items():
            archive.writestr(name, body)
    monkeypatch.setattr(zipfile.ZipFile, 'open', open_member)
    raw, bundle = encode(value), data.getvalue()
    result = subject.verify_bytes(raw, bundle, catalog_sha256=hashlib.sha256(raw).hexdigest(),
                                  bundle_sha256=hashlib.sha256(bundle).hexdigest())
    assert result['full_catalog_byte_footer_coverage'] is True
    assert result['matched_batches'] == result['matched_footer_rows'] == 876
    assert len(opened) == result['zip_member_open_attempts'] == 1752
    assert sum(t['claimed_deleted_rows'] for t in result['tables'].values()) == 874
    assert all(result[key] is False for key in ('logical_restore_verified', 'postgres_restore_verified',
        'independent_custody_verified', 'historical_row_dates_verified', 'content_derived_batch_ids_verified',
        'receipt_claims_authenticated', 'manifest_drive_ids_authenticated', 'deletion_authorised',
        'training_eligible', 'approval_authority'))


@pytest.mark.parametrize('tamper,expected', [('manifest', 'DOWNLOADED_MANIFEST_MISMATCH'),
    ('bytes', 'PARQUET_BYTE_HASH_MISMATCH'), ('footer_rows', 'PARQUET_SCHEMA_OR_ROWS_MISMATCH')])
def test_one_failed_batch_blocks_full_coverage_and_preserves_denominators(
        cohort: tuple[dict[str, Any], dict[str, bytes]], tamper: str, expected: str) -> None:
    value, files = json.loads(encode(cohort[0])), dict(cohort[1])
    row = value['records'][0]
    stem = row['source_table'] + '-' + row['batch_id']
    if tamper == 'manifest':
        manifest = json.loads(files[stem + '.manifest.json'])
        manifest['rows'] = 7
        files[stem + '.manifest.json'] = encode(manifest)
    elif tamper == 'bytes':
        files[stem + '.parquet'] += b'corrupted'
    else:
        row['row_count'] = row['deleted_count'] = 2
        manifest = json.loads(files[stem + '.manifest.json'])
        manifest['rows'] = 2
        files[stem + '.manifest.json'] = encode(manifest)
    result = run(value, files)
    assert result['status'] == 'BLOCKED'
    assert result['expected_batches'] == result['catalog_receipts'] == 876
    assert result['matched_batches'] == 875
    assert result['failures'][0]['code'] == expected
    assert result['full_catalog_byte_footer_coverage'] is False
    assert 'synthetic-data' not in json.dumps(result)


@pytest.mark.parametrize('tamper', ['subset', 'partial', 'missing', 'unknown', 'row_bound'])
def test_cohort_cannot_be_weakened_or_filtered(
        cohort: tuple[dict[str, Any], dict[str, bytes]], tamper: str) -> None:
    value, files = json.loads(encode(cohort[0])), dict(cohort[1])
    if tamper == 'subset':
        value['records'].pop()
        value['total_count'] -= 1
    elif tamper == 'partial':
        value['records'][0]['row_count'] = 2
    elif tamper == 'missing':
        files.pop(next(iter(files)))
    elif tamper == 'unknown':
        value['records'][0]['source_table'] = 'private-unknown'
    else:
        value['records'][0]['row_count'] = value['records'][0]['deleted_count'] = 2001
    with pytest.raises(ValueError):
        run(value, files)


def test_resource_bound_never_yields_partial_success(
        cohort: tuple[dict[str, Any], dict[str, bytes]], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subject, 'MAX_DECLARED_EXPANDED', 1)
    result = run(*cohort)
    assert result['status'] == 'BLOCKED' and result['matched_batches'] == 0
    assert result['failures'][0]['code'] == 'TOTAL_DECLARED_EXPANSION_BOUND'
    assert sum(t['declared_rows'] for t in result['tables'].values()) == 876
    assert sum(t['checked_batches'] for t in result['tables'].values()) == 1


def test_preview_and_pin_rejection_have_zero_reads(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def forbidden(*args: Any) -> Any:
        raise AssertionError('NO_INPUT_READ')
    monkeypatch.setattr(subject.review, '_private_file', forbidden)
    assert subject.main(['--catalog', 'PRIVATE_PATH']) == 0
    assert json.loads(capsys.readouterr().out)['input_reads'] == 0
    assert subject.main(['--confirm-byte-footer-read', '--catalog', 'PRIVATE_PATH', '--bundle', 'OTHER_PRIVATE',
                         '--catalog-sha256', 'a' * 64, '--bundle-sha256', 'b' * 64]) == 2
    output = capsys.readouterr().out
    assert 'PRIVATE' not in output
    assert json.loads(output)['code'] == 'PRESERVED_GENERATION_PINS_REQUIRED'


def test_confirmed_cli_streams_guarded_files_no_persistent_writes(
        cohort: tuple[dict[str, Any], dict[str, bytes]], monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    raw, data = encode(cohort[0]), pack(cohort[1])
    pin = hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(subject, 'PRESERVED_BUNDLE_SHA256', pin)  # synthetic CLI only
    @contextmanager
    def source(path: Any, bound: int) -> Any:
        yield io.BytesIO(raw if path.name == 'PRIVATE_JSON' else data)
    monkeypatch.setattr(subject.review, '_private_file', source)
    assert subject.main(['--confirm-byte-footer-read', '--catalog', 'PRIVATE_JSON', '--bundle', 'PRIVATE_ZIP',
        '--catalog-sha256', hashlib.sha256(raw).hexdigest(), '--bundle-sha256', pin]) == 0
    output = capsys.readouterr().out
    assert 'PRIVATE_' not in output
    assert json.loads(output)['row_pages_decoded'] == 0
