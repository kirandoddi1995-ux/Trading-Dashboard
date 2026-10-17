"""Synthetic Parquet/ZIP only; deliberately NOT recoverable logical source rows."""
from __future__ import annotations

import ast
from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path
import stat
import struct
from typing import BinaryIO, Literal, cast
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import archive_recovery_review as review


def encode(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def parquet(table: str, batch: str, rows: int, *, wrong_rows: bool = False) -> bytes:
    spec = review.SPECS[table]
    fields = [pa.field(name, pa.date32() if kind == 'date' else
                       pa.timestamp('us', tz='UTC') if kind == 'timestamptz' else pa.string())
              for name, kind in spec.items()]
    fields.append(pa.field('_row_json', pa.string(), nullable=False))
    metadata = dict(format='quant-archive-v1', table=table, batch_id=batch,
                    postgres_types=spec, numeric_encoding='decimal-string')
    schema = pa.schema(fields, metadata={b'quant_archive': encode(metadata)})
    size = rows-1 if wrong_rows else rows
    columns: dict[str, list[object]] = {name: [None]*size for name in spec}
    # Deliberately not valid JSON/recoverable rows. A footer-only check MUST NOT
    # mistake this accepted structural fixture for logical restore evidence.
    columns['_row_json'] = ['SYNTHETIC_OPAQUE_NOT_A_MARKET_ROW']*size
    sink = io.BytesIO()
    pq.write_table(pa.Table.from_pydict(columns, schema=schema), sink,  # type: ignore[no-untyped-call]
                   compression='zstd', write_statistics=False)
    return sink.getvalue()


def pack(files: dict[str, bytes], prefix: str = '') -> bytes:
    sink = io.BytesIO()
    with zipfile.ZipFile(sink, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        if prefix:
            archive.writestr(prefix, b'')
        for name, data in files.items():
            archive.writestr(prefix+name, data)
    return sink.getvalue()


@pytest.fixture(scope='module')
def incident() -> tuple[dict[str, object], dict[str, bytes]]:
    batches: list[dict[str, object]] = []
    files: dict[str, bytes] = {}
    planned: list[tuple[str, int]] = []
    for table, count, total in review.INCIDENT_TABLE_TOTALS:
        base = total//count
        planned.extend((table, base if i < count-1 else total-base*(count-1)) for i in range(count))
    for index, (table, rows) in enumerate(planned):
        batch = f'{index+1:064x}'
        data = parquet(table, batch, rows)
        sha = hashlib.sha256(data).hexdigest()
        receipt: dict[str, object] = dict(batch_id=batch, source_table=table, row_count=rows,
            file_sha256=sha, drive_file_id=f'synthetic_data_{index}',
            drive_manifest_id=f'synthetic_manifest_{index}', deleted_count=rows,
            completed_at='2026-10-12T00:00:00+00:00')
        manifest = dict(format='quant-archive-v1', batch_id=batch, source_table=table,
            rows=rows, sha256=sha, drive_file_id=receipt['drive_file_id'],
            postgres_types=review.SPECS[table], numeric_encoding='decimal-string')
        files[table+'-'+batch+'.parquet'] = data
        files[table+'-'+batch+'.manifest.json'] = encode(manifest)
        batches.append(receipt)
    inventory: dict[str, object] = dict(format='archive-recovery-inventory-v1',
        window_start=review.WINDOW_START, window_end=review.WINDOW_END,
        measured_at='2026-10-18T00:00:00+00:00', batches=batches)
    return inventory, files


def receipts(inventory: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], inventory['batches'])


def clone(inventory: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], json.loads(encode(inventory)))


def replace_data(inventory: dict[str, object], files: dict[str, bytes], data: bytes) -> tuple[dict[str, object], dict[str, bytes]]:
    inventory, files = clone(inventory), dict(files)
    receipt = receipts(inventory)[0]
    stem = str(receipt['source_table'])+'-'+str(receipt['batch_id'])
    sha = hashlib.sha256(data).hexdigest()
    receipt['file_sha256'] = sha
    manifest = json.loads(files[stem+'.manifest.json'])
    manifest['sha256'] = sha
    files[stem+'.manifest.json'] = encode(manifest)
    files[stem+'.parquet'] = data
    return inventory, files


@pytest.mark.parametrize('prefix', ['', 'Synthetic Download/'])
def test_full_denominator_bytes_footer_only_never_claims_restore_or_custody(
        incident: tuple[dict[str, object], dict[str, bytes]], prefix: str,
        monkeypatch: pytest.MonkeyPatch) -> None:
    inventory, files = incident
    def forbidden(*args: object, **kwargs: object) -> object:
        pytest.fail('Parquet row reader invoked')
    monkeypatch.setattr(pq, 'read_table', forbidden)
    monkeypatch.setattr(pq.ParquetFile, 'read', forbidden)
    monkeypatch.setattr(pq.ParquetFile, 'read_row_group', forbidden)
    monkeypatch.setattr(pq.ParquetFile, 'iter_batches', forbidden)
    result = review.review_bytes(encode(inventory), pack(files, prefix))
    assert result.failures == () and result.full_planned_byte_footer_coverage
    assert result.verified_batches == result.expected_batches == 122
    assert result.verified_footer_rows == result.expected_deleted_rows == 98755
    assert result.row_values_read == 0
    assert all(flag is False for flag in (result.logical_restore_verified, result.independent_custody_verified,
        result.inventory_completeness_authenticated, result.zip_provenance_authenticated,
        result.manifest_drive_id_authenticated, result.current_db_state_checked))
    public = json.dumps(asdict(result))
    assert 'synthetic_data_' not in public and 'SYNTHETIC_OPAQUE' not in public
    assert str(receipts(inventory)[0]['batch_id']) not in public


@pytest.mark.parametrize('kind', ['batch_missing', 'batch_duplicate', 'rows', 'partial_deleted', 'table',
                                 'window', 'completed', 'measured', 'drive_duplicate', 'bool'])
def test_inventory_exact_scope_and_denominator_never_shrink(
        incident: tuple[dict[str, object], dict[str, bytes]], kind: str) -> None:
    inventory, files = incident
    inventory = clone(inventory)
    batches = receipts(inventory)
    if kind == 'batch_missing':
        batches.pop()
    elif kind == 'batch_duplicate':
        batches[1] = batches[0]
    elif kind == 'rows':
        batches[0]['row_count'] = batches[0]['deleted_count'] = 799
    elif kind == 'partial_deleted':
        batches[0]['deleted_count'] = 799
    elif kind == 'table':
        batches[0]['source_table'] = 'arbitrary.private_table'
    elif kind == 'window':
        inventory['window_start'] = '2026-10-12T00:00:00+00:00'
    elif kind == 'completed':
        batches[0]['completed_at'] = '2026-10-18T00:00:00+00:00'
    elif kind == 'measured':
        inventory['measured_at'] = '2026-10-17T00:00:00+00:00'
    elif kind == 'drive_duplicate':
        batches[0]['drive_manifest_id'] = batches[0]['drive_file_id']
    else:
        batches[0]['row_count'] = True
    result = review.review_bytes(encode(inventory), pack(files))
    assert result.status == 'BLOCKED' and result.expected_batches == 122
    assert result.expected_deleted_rows == 98755 and not result.full_planned_byte_footer_coverage


def test_aware_export_time_normalized_and_duplicate_json_keys_rejected(
        incident: tuple[dict[str, object], dict[str, bytes]]) -> None:
    inventory, _ = incident
    changed = clone(inventory)
    changed['measured_at'] = '2026-10-18T05:30:00+05:30'
    assert len(review.parse_inventory(encode(changed))) == 122
    with pytest.raises(review.ReviewError, match='DUPLICATE_JSON_KEY'):
        review.parse_inventory(b'{"format":"one","format":"two"}')


def test_missing_pairs_fail_and_extraneous_history_is_counted_not_opened(
        incident: tuple[dict[str, object], dict[str, bytes]], monkeypatch: pytest.MonkeyPatch) -> None:
    inventory, original = incident
    files = dict(original)
    removed = next(name for name in files if name.endswith('.parquet'))
    del files[removed]
    files['older-history.parquet'] = b'not parsed, not a row or valid Parquet'
    original_open = zipfile.ZipFile.open
    bundle = pack(files)
    def only_expected(self: zipfile.ZipFile, name: str | zipfile.ZipInfo, mode: Literal['r', 'w'] = 'r',
                      pwd: bytes | None = None, *, force_zip64: bool = False) -> BinaryIO:
        actual = name.filename if isinstance(name, zipfile.ZipInfo) else name
        assert 'older-history' not in actual
        return cast(BinaryIO, original_open(self, name, mode, pwd, force_zip64=force_zip64))
    monkeypatch.setattr(zipfile.ZipFile, 'open', only_expected)
    result = review.review_bytes(encode(inventory), bundle)
    assert result.missing_expected_entries == result.extraneous_entries == 1
    assert result.verified_batches == 121 and not result.full_planned_byte_footer_coverage


@pytest.mark.parametrize('kind', ['table', 'hash', 'data_id', 'rows', 'types', 'own_manifest_id'])
def test_original_downloaded_manifest_schema_and_receipt_binding(
        incident: tuple[dict[str, object], dict[str, bytes]], kind: str) -> None:
    inventory, original = incident
    files = dict(original)
    name = next(n for n in files if n.endswith('.manifest.json'))
    manifest = json.loads(files[name])
    if kind == 'table':
        manifest['source_table'] = 'mf_nav'
    elif kind == 'hash':
        manifest['sha256'] = 'f'*64
    elif kind == 'data_id':
        manifest['drive_file_id'] = 'wrong_private_id'
    elif kind == 'rows':
        manifest['rows'] = True
    elif kind == 'types':
        manifest['postgres_types'] = {}
    else:
        manifest['drive_manifest_id'] = 'not_a_real_manifest_field'
    files[name] = encode(manifest)
    result = review.review_bytes(encode(inventory), pack(files))
    assert 'DOWNLOADED_MANIFEST_MISMATCH' in result.failures
    assert not result.full_planned_byte_footer_coverage


@pytest.mark.parametrize('kind', ['bytes', 'footer', 'rows', 'expansion'])
def test_raw_byte_hash_footer_and_expansion_fail_closed(
        incident: tuple[dict[str, object], dict[str, bytes]], kind: str,
        monkeypatch: pytest.MonkeyPatch) -> None:
    inventory, original = incident
    files = dict(original)
    first = receipts(inventory)[0]
    name = str(first['source_table'])+'-'+str(first['batch_id'])+'.parquet'
    if kind == 'bytes':
        files[name] = files[name][:-1]+b'X'
    elif kind == 'footer':
        data = files[name][:-8]+struct.pack('<I', review.MAX_FOOTER_BYTES+1)+b'PAR1'
        inventory, files = replace_data(inventory, files, data)
    elif kind == 'rows':
        data = parquet(str(first['source_table']), str(first['batch_id']), cast(int, first['row_count']), wrong_rows=True)
        inventory, files = replace_data(inventory, files, data)
    else:
        monkeypatch.setattr(review, 'MAX_COLUMN_EXPANDED', 1)
    result = review.review_bytes(encode(inventory), pack(files))
    assert result.status == 'BLOCKED' and result.failures
    assert not result.full_planned_byte_footer_coverage


@pytest.mark.parametrize('name', ['../bad', '/absolute', 'folder/../bad', 'C:/bad', 'folder\\bad',
                                'a/b/c', 'trailing.'])
def test_zip_names_rejected_before_any_data_read(
        incident: tuple[dict[str, object], dict[str, bytes]], name: str) -> None:
    inventory, _ = incident
    if '\\' in name:
        placeholder = name.replace('\\', 'X')
        bundle = pack({placeholder: b'x'}).replace(placeholder.encode(), name.encode())
    else:
        bundle = pack({name: b'x'})
    result = review.review_bytes(encode(inventory), bundle)
    assert result.status == 'BLOCKED' and 'UNSAFE_ZIP_NAME' in result.failures


def test_duplicate_names_symlink_encryption_and_bomb_directory_rejected(
        incident: tuple[dict[str, object], dict[str, bytes]]) -> None:
    inventory, _ = incident
    sink = io.BytesIO()
    with zipfile.ZipFile(sink, 'w') as archive:
        archive.writestr('same', b'a')
        with pytest.warns(UserWarning):
            archive.writestr('same', b'b')
    assert 'DUPLICATE_ZIP_NAME' in review.review_bytes(encode(inventory), sink.getvalue()).failures
    sink = io.BytesIO()
    with zipfile.ZipFile(sink, 'w') as archive:
        link = zipfile.ZipInfo('link')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, b'target')
    assert 'ZIP_LINK_ENCRYPTION_OR_COMPRESSION_FORBIDDEN' in review.review_bytes(encode(inventory), sink.getvalue()).failures
    encrypted = bytearray(pack({'ordinary': b'x'}))
    local = encrypted.index(b'PK\x03\x04')
    central = encrypted.index(b'PK\x01\x02')
    encrypted[local+6] |= 1
    encrypted[central+8] |= 1
    assert 'ZIP_LINK_ENCRYPTION_OR_COMPRESSION_FORBIDDEN' in review.review_bytes(encode(inventory), bytes(encrypted)).failures
    bomb = pack({'bomb': b'x'*(1024*1024)})
    assert 'ZIP_MEMBER_EXPANSION_BOUND' in review.review_bytes(encode(inventory), bomb).failures


def test_preview_zero_input_io_and_redacted_argument_errors(monkeypatch: pytest.MonkeyPatch,
                                                          capsys: pytest.CaptureFixture[str]) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        pytest.fail('preview touched input filesystem')
    with monkeypatch.context() as patch:
        patch.setattr(review, 'review_paths', forbidden)
        patch.setattr(Path, 'resolve', forbidden)
        assert review.main(['--inventory', 'private-secret.json', '--bundle', 'private-secret.zip']) == 0
    output = capsys.readouterr().out
    assert json.loads(output)['input_reads'] == 0 and 'private-secret' not in output
    assert review.main(['--unknown-private-argument']) == 2
    assert 'unknown-private' not in capsys.readouterr().out


def test_confirmed_private_paths_read_only_and_detect_bundle_change(
        incident: tuple[dict[str, object], dict[str, bytes]], tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    inventory, files = incident
    index = tmp_path/'inventory.json'
    bundle = tmp_path/'bundle.zip'
    index.write_bytes(encode(inventory))
    raw = pack(files)
    bundle.write_bytes(raw)
    assert review.review_paths(index, bundle).full_planned_byte_footer_coverage
    original = review._review
    def changed(raw_index: bytes, stream: BinaryIO) -> review.ReviewReport:
        result = original(raw_index, stream)
        bundle.write_bytes(raw+b'changed')
        return result
    monkeypatch.setattr(review, '_review', changed)
    assert review.review_paths(index, bundle).status == 'BLOCKED'


def test_linked_private_input_is_rejected_without_permission_changes(
        incident: tuple[dict[str, object], dict[str, bytes]], tmp_path: Path) -> None:
    inventory, files = incident
    target, index, bundle = tmp_path/'target', tmp_path/'index', tmp_path/'bundle'
    target.write_bytes(encode(inventory))
    bundle.write_bytes(pack(files))
    try:
        index.symlink_to(target)
    except OSError:
        pytest.skip('Symlink permission unavailable; no privilege/ACL changes')
    assert not review.review_paths(index, bundle).full_planned_byte_footer_coverage


def test_table_substitution_with_unchanged_global_counts_is_rejected(
        incident: tuple[dict[str, object], dict[str, bytes]]) -> None:
    inventory, _ = incident
    inventory = clone(inventory)
    batches = receipts(inventory)
    batches[0]['source_table'] = 'scanner_observations'
    assert len(batches) == 122 and sum(cast(int, b['deleted_count']) for b in batches) == 98755
    with pytest.raises(review.ReviewError, match='INCIDENT_TABLE_DENOMINATOR_REQUIRED'):
        review.parse_inventory(encode(inventory))


def test_exact_input_hashes_bind_even_unopened_extraneous_zip_bytes(
        incident: tuple[dict[str, object], dict[str, bytes]]) -> None:
    inventory, files = incident
    raw = encode(inventory)
    left = pack({**files, 'older-unopened.txt': b'one synthetic note'})
    right = pack({**files, 'older-unopened.txt': b'a different synthetic note'})
    first = review.review_bytes(raw, left)
    second = review.review_bytes(raw, right)
    assert first.full_planned_byte_footer_coverage and second.full_planned_byte_footer_coverage
    assert first.extraneous_entries == second.extraneous_entries == 1
    assert first.inventory_sha256 == second.inventory_sha256 == hashlib.sha256(raw).hexdigest()
    assert first.bundle_sha256 == hashlib.sha256(left).hexdigest()
    assert second.bundle_sha256 == hashlib.sha256(right).hexdigest()
    assert first.bundle_sha256 != second.bundle_sha256


def test_fixed_schema_copy_matches_actual_public_literal_and_field_order() -> None:
    # Read public SOURCE only; never import drive_archive or its transport stack.
    source = Path(__file__).resolve().parents[1]/'drive_archive.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    definitions = [node.value for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == 'SPECS' for target in node.targets)]
    assert len(definitions) == 1
    public = cast(dict[str, dict[str, str]], ast.literal_eval(definitions[0]))
    assert review.SPECS == public
    for table, fields in public.items():
        assert tuple(review.SPECS[table].items()) == tuple(fields.items())
