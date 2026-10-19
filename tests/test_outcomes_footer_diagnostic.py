"""Synthetic footer observations; no private data and no recovery authority."""
from __future__ import annotations

from contextlib import contextmanager
import ast
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import outcomes_footer_diagnostic as subject


def encode(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def parquet(batch: str, *, big: bool = False) -> bytes:
    spec = subject.review.SPECS['equity_research.outcomes']
    fields = [pa.field(name, pa.timestamp('us', tz='UTC') if kind == 'timestamptz' else pa.string())
              for name, kind in spec.items()]
    fields.append(pa.field('_row_json', pa.string(), nullable=False))
    schema = pa.schema(fields, metadata={b'quant_archive': encode(dict(format=subject.review.FORMAT,
        table='equity_research.outcomes', batch_id=batch, postgres_types=spec, numeric_encoding='decimal-string'))})
    text = ('SYNTHETIC_NOT_MARKET_JSON_' * (800000 if big else 1))
    data = dict(snapshot_id=['synthetic'], decision_id=['synthetic'], payload=[text],
                recorded_at=[None], _row_json=[text])
    stream = io.BytesIO()
    pq.write_table(pa.Table.from_pydict(data, schema=schema), stream, compression='zstd',
                   write_statistics=False, use_dictionary=False)
    return stream.getvalue()


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
    for table, count in subject.verifier.EXPECTED.items():
        for n in range(count):
            batch = f'{len(rows)+1:064x}'
            data = parquet(batch, big=n == 0) if table == 'equity_research.outcomes' else b'UNOPENED_SYNTHETIC'
            no_delete = table in ('equity_research.outcomes', 'universe_membership') and n == 0
            row = dict(batch_id=batch, source_table=table, row_count=1,
                file_sha256=hashlib.sha256(data).hexdigest(), drive_file_id=f'synthetic_data_{batch}',
                drive_manifest_id=f'synthetic_meta_{batch}', deleted_count=None if no_delete else 1,
                verified_at='2022-01-03T00:00:00Z', completed_at=None if no_delete else '2022-01-04T00:00:00Z')
            files[table + '-' + batch + '.parquet'] = data
            files[table + '-' + batch + '.manifest.json'] = encode(dict(format=subject.review.FORMAT,
                batch_id=batch, source_table=table, rows=1, sha256=row['file_sha256'], drive_file_id=row['drive_file_id'],
                postgres_types=subject.review.SPECS[table], numeric_encoding='decimal-string'))
            rows.append(row)
    files.update({f'unknown-{n}.parquet': b'UNOPENED_SYNTHETIC' for n in range(5)})
    files['note.txt'] = b'UNOPENED_SYNTHETIC'
    return dict(format=subject.verifier.catalog.FORMAT, status='COMPLETE_METADATA_EXPORT',
        measured_at='2022-02-01T00:00:00Z', total_count=len(rows), truncated=False, records=rows), files


def run(value: dict[str, Any], files: dict[str, bytes]) -> dict[str, Any]:
    raw, data = encode(value), pack(files)
    return subject.diagnose_stream(raw, io.BytesIO(data), catalog_sha256=hashlib.sha256(raw).hexdigest(),
                                    bundle_sha256=hashlib.sha256(data).hexdigest())


def test_actual_large_json_shape_is_diagnosed_not_accepted_and_no_rows_read(
        cohort: tuple[dict[str, Any], dict[str, bytes]], monkeypatch: pytest.MonkeyPatch) -> None:
    raw, data = encode(cohort[0]), pack(cohort[1])
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError('ROW_OR_STATS_READER_FORBIDDEN')
    for name in ('read', 'read_row_group', 'read_row_groups', 'iter_batches', 'scan_contents'):
        monkeypatch.setattr(pq.ParquetFile, name, forbidden)
    monkeypatch.setattr(pq, 'read_table', forbidden)
    original = zipfile.ZipFile.open
    opened: list[str] = []
    def open_member(archive: zipfile.ZipFile, member: Any, *args: Any, **kwargs: Any) -> Any:
        name = member.filename
        assert name.startswith('equity_research.outcomes-')
        opened.append(name)
        return original(archive, member, *args, **kwargs)
    monkeypatch.setattr(zipfile.ZipFile, 'open', open_member)
    result = subject.diagnose_stream(raw, io.BytesIO(data), catalog_sha256=hashlib.sha256(raw).hexdigest(),
                                      bundle_sha256=hashlib.sha256(data).hexdigest())
    assert result['status'] == 'OUTCOMES_FOOTER_DIAGNOSTIC_ONLY_NOT_ACCEPTANCE'
    assert result['inspected_batches'] == 18
    assert len(opened) == result['zip_member_open_attempts'] == 36
    assert result['original_guard_passed'] == 17 and result['original_guard_blocked'] == 1
    assert result['all_observed_original_rejections_size_only'] is True
    first = result['observations'][0]
    assert first['original_guard_result'] == 'PARQUET_COLUMN_EXPANSION_BOUND'
    for name in ('payload', '_row_json'):
        assert first['columns'][name]['max_uncompressed_bytes'] > 16 * 1024**2
        assert first['columns'][name]['predicate_failures']['uncompressed_within_16mib'] == 1
    assert result['selected_declared_expanded_bytes'] > result['blocked_declared_expanded_bytes'] > 0
    assert result['prior_eight_failure_pattern_reproduced'] is False
    for key in ('full_catalog_byte_footer_coverage', 'bounds_changed', 'verification_authorised',
                'logical_restore_verified', 'independent_custody_verified', 'receipt_claims_authenticated',
                'historical_row_dates_verified', 'deletion_authorised', 'training_eligible', 'approval_authority'):
        assert result[key] is False
    assert result['row_pages_decoded'] == result['writes'] == result['network_requests'] == 0
    assert 'SYNTHETIC_NOT_MARKET_JSON' not in json.dumps(result)


@pytest.mark.parametrize('field,value,check', [
    ('file_path','SECRET_EXTERNAL_PATH','no_external_file'),
    ('compression','SECRET_CODEC','zstd_codec'), ('num_values',2,'value_count_matches'),
    ('total_uncompressed_size',0,'uncompressed_positive'),
    ('total_uncompressed_size',16*1024**2+1,'uncompressed_within_16mib'),
    ('total_compressed_size',0,'compressed_positive'),
    ('total_compressed_size',200,'compressed_within_file'),
    ('data_page_offset',-1,'offsets_within_file'),
    ('dictionary_page_offset',1,'offsets_within_file')])
def test_each_shared_guard_predicate_is_separately_named(field: str, value: Any, check: str) -> None:
    facts = dict(file_path='', compression='ZSTD', num_values=1, total_uncompressed_size=50,
        total_compressed_size=20, data_page_offset=4, dictionary_page_offset=None)
    facts[field] = value
    result = subject._column_checks(SimpleNamespace(**facts), 1, 100, 20)
    assert result[check] is False
    assert 'SECRET_' not in json.dumps(result)


def test_exact_16mib_limit_is_still_unchanged_and_inclusive() -> None:
    facts = SimpleNamespace(file_path='', compression='ZSTD', num_values=1, total_uncompressed_size=16*1024**2,
        total_compressed_size=20, data_page_offset=4, dictionary_page_offset=None)
    assert all(subject._column_checks(facts, 1, 100, 20).values())
    assert subject.review.MAX_COLUMN_EXPANDED == 16 * 1024**2


@pytest.mark.parametrize('tamper', ['manifest', 'bytes', 'footer', 'subset'])
def test_malformed_inputs_do_not_produce_complete_diagnostic(
        cohort: tuple[dict[str, Any], dict[str, bytes]], tamper: str) -> None:
    value, files = json.loads(encode(cohort[0])), dict(cohort[1])
    row = next(r for r in value['records'] if r['source_table'] == 'equity_research.outcomes')
    stem = row['source_table'] + '-' + row['batch_id']
    if tamper == 'subset':
        value['records'].pop()
        value['total_count'] -= 1
        with pytest.raises(ValueError):
            run(value, files)
        return
    if tamper == 'manifest':
        manifest = json.loads(files[stem+'.manifest.json'])
        manifest['rows'] = 100
        files[stem+'.manifest.json'] = encode(manifest)
    elif tamper == 'bytes':
        files[stem+'.parquet'] += b'CORRUPT'
    else:
        files[stem+'.parquet'] = b'NOT_PARQUET'
        row['file_sha256'] = hashlib.sha256(files[stem+'.parquet']).hexdigest()
        manifest = json.loads(files[stem+'.manifest.json'])
        manifest['sha256'] = row['file_sha256']
        files[stem+'.manifest.json'] = encode(manifest)
    result = run(value, files)
    assert result['status'] == 'BLOCKED' and result['inspected_batches'] == 17
    assert result['failures'][0]['catalog_ordinal'] == 859
    assert result['verification_authorised'] is False


def test_preview_and_bad_pins_have_zero_input_reads(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def forbidden(*args: Any) -> Any:
        raise OSError('SECRET_PRIVATE_FILE')
    monkeypatch.setattr(subject.review, '_private_file', forbidden)
    assert subject.main(['--catalog', 'SECRET_PRIVATE']) == 0
    assert json.loads(capsys.readouterr().out)['input_reads'] == 0
    assert subject.main(['--confirm-footer-diagnostic', '--catalog', 'SECRET_PRIVATE', '--bundle', 'SECRET_ZIP',
        '--catalog-sha256', 'a'*64, '--bundle-sha256', 'b'*64]) == 2
    assert 'SECRET_' not in capsys.readouterr().out


def test_confirmed_cli_reports_diagnostic_not_acceptance(
        cohort: tuple[dict[str, Any], dict[str, bytes]], monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    raw, data = encode(cohort[0]), pack(cohort[1])
    digest = hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(subject.verifier, 'PRESERVED_BUNDLE_SHA256', digest)
    @contextmanager
    def source(path: Any, bound: int) -> Any:
        yield io.BytesIO(raw if path.name == 'PRIVATE_CATALOG' else data)
    monkeypatch.setattr(subject.review, '_private_file', source)
    assert subject.main(['--confirm-footer-diagnostic', '--catalog', 'PRIVATE_CATALOG', '--bundle', 'PRIVATE_ZIP',
        '--catalog-sha256', hashlib.sha256(raw).hexdigest(), '--bundle-sha256', digest]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['original_guard_blocked'] == 1 and result['verification_authorised'] is False


def test_different_original_guard_error_cannot_be_named_size_only_or_reproduction(
        cohort: tuple[dict[str, Any], dict[str, bytes]], monkeypatch: pytest.MonkeyPatch) -> None:
    def parse_failed(*args: Any) -> None:
        raise subject.review.ReviewError('PARQUET_FOOTER_PARSE_FAILED')
    monkeypatch.setattr(subject.review, '_footer', parse_failed)
    monkeypatch.setattr(subject, 'PRIOR_FAILURE_ORDINALS', frozenset(range(859, 877)))
    result = run(*cohort)
    assert result['original_guard_blocked'] == 18
    assert result['observations'][0]['columns']['payload']['predicate_failures']['uncompressed_within_16mib'] == 1
    assert result['observations'][0]['only_column_size_predicate_failed'] is False
    assert result['all_observed_original_rejections_size_only'] is False
    assert result['prior_eight_failure_pattern_reproduced'] is False


def test_no_stats_raw_metadata_dump_or_row_reader_in_diagnostic_source() -> None:
    tree = ast.parse(Path(subject.__file__).read_text(encoding='utf-8'))
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not attributes.intersection({'statistics', 'to_dict', 'path_in_schema', 'read_table',
        'read_row_group', 'read_row_groups', 'iter_batches', 'scan_contents'})
