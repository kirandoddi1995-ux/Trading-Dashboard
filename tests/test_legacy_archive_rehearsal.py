"""Only generated, explicitly synthetic 2022 rows; never real archives or keys."""
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import io
import json
from typing import Any
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import archive_recovery_review as review
import catalog_receipts as receipts
import drive_archive as codec
import legacy_archive_rehearsal as legacy


def enc(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def pack(files: dict[str, bytes]) -> bytes:
    sink = io.BytesIO()
    with zipfile.ZipFile(sink, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr('Synthetic archive/'+name, data)
    return sink.getvalue()


@pytest.fixture(scope='module')
def generation() -> tuple[dict[str, Any], dict[str, bytes]]:
    records: list[dict[str, Any]] = []
    files: dict[str, bytes] = {}
    for table, batches, total in review.INCIDENT_TABLE_TOTALS:
        for batch in range(batches):
            count = total//batches if batch < batches-1 else total-(total//batches)*(batches-1)
            texts = []
            for row in range(count):
                item = dict.fromkeys(codec.SPECS[table])
                for key in codec.KEYS[table]:
                    item[key] = ('2022-01-03' if key == 'snapshot_date' else
                        '2022-01-03T09:15:00+00:00' if key == 'observed_at' else f'SYNTHETIC_{batch}_{row}')
                texts.append(json.dumps(item))
            identity, data, _ = codec.parquet_bytes(table, texts)
            sha = hashlib.sha256(data).hexdigest()
            manifest = dict(format=codec.FORMAT_VERSION, batch_id=identity, source_table=table,
                rows=count, sha256=sha, drive_file_id='synthetic_data_'+identity,
                postgres_types=codec.SPECS[table], numeric_encoding='decimal-string')
            files[table+'-'+identity+'.parquet'] = data
            files[table+'-'+identity+'.manifest.json'] = enc(manifest)
            records.append(dict(batch_id=identity, source_table=table, row_count=count, file_sha256=sha,
                drive_file_id=manifest['drive_file_id'], drive_manifest_id='synthetic_manifest_'+identity,
                deleted_count=count, completed_at='2026-10-12T00:00:00+00:00'))
    inventory = dict(format=review.INVENTORY_FORMAT, window_start=review.WINDOW_START,
                     window_end=review.WINDOW_END, measured_at='2026-10-18T00:00:00+00:00', batches=records)
    return inventory, files


@pytest.fixture(scope='module')
def measured(generation: tuple[dict[str, Any], dict[str, bytes]]) -> tuple[legacy.RowWitness, str, str]:
    inventory, files = generation
    raw, bundle = enc(inventory), pack(files)
    ip, bp = hashlib.sha256(raw).hexdigest(), hashlib.sha256(bundle).hexdigest()
    return legacy.reconstruct(raw, bundle, inventory_sha256=ip, bundle_sha256=bp), ip, bp


def test_directory_only_names_never_opens_a_member(generation: tuple[dict[str, Any], dict[str, bytes]],
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    inventory, files = generation
    files = {**files, 'market_quotes-'+'f'*64+'.manifest.json': b'NOT_JSON',
             'special-backup.manifest.json': b'NOT_JSON'}
    raw, bundle = enc(inventory), pack(files)
    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError('NO_MEMBER_DECOMPRESSION')
    monkeypatch.setattr(zipfile.ZipFile, 'open', forbidden)
    result = legacy.directory_audit(raw, bundle, inventory_sha256=hashlib.sha256(raw).hexdigest(),
                                    bundle_sha256=hashlib.sha256(bundle).hexdigest())
    tables = result['tables']
    assert isinstance(tables, dict)
    assert sum(v['incident_paired'] for v in tables.values()) == 122
    assert tables['market_quotes']['manifest_without_parquet'] == 1
    assert result['nonstandard_archive_names'] == 1
    assert result['central_entries'] == result['files'] == 246
    assert result['explicit_directory_entries'] == 0  # prefix is not an explicit ZIP directory entry
    assert result['older_dates_verified'] is result['logical_restore_verified'] is False


def test_complete_legacy_rows_roundtrip_without_promoting_to_postgres_or_custody(
        measured: tuple[legacy.RowWitness, str, str]) -> None:
    witness, ip, bp = measured
    body = json.loads(witness.body)
    assert len(body['batches']) == 122
    assert body['rows'] == sum(b['rows'] for b in body['batches']) == 98755
    assert body['archive_row_roundtrip_verified'] is True
    assert body['inventory_sha256'] == ip and body['bundle_sha256'] == bp
    for flag in ('postgres_restore_verified', 'physical_independence_verified', 'encryption_verified',
                 'historical_custody_verified', 'codec_runtime_identity_verified',
                 'deletion_authorised', 'training_eligible', 'approval_authority'):
        assert body[flag] is False
    assert 'original_json' not in body and 'texts' not in body


def test_footer_success_with_invalid_row_json_cannot_become_a_logical_witness(
        generation: tuple[dict[str, Any], dict[str, bytes]]) -> None:
    inventory, files = generation
    inventory = json.loads(enc(inventory))
    files = dict(files)
    row = inventory['batches'][0]
    stem = row['source_table']+'-'+row['batch_id']
    table = pq.read_table(io.BytesIO(files[stem+'.parquet']))
    index = table.schema.get_field_index('_row_json')
    table = table.set_column(index, table.schema.field(index), pa.array(['SYNTHETIC_NOT_JSON']*table.num_rows))
    sink = io.BytesIO()
    pq.write_table(table, sink, compression='zstd')
    data = sink.getvalue()
    row['file_sha256'] = hashlib.sha256(data).hexdigest()
    manifest = json.loads(files[stem+'.manifest.json'])
    manifest['sha256'] = row['file_sha256']
    files[stem+'.parquet'], files[stem+'.manifest.json'] = data, enc(manifest)
    raw, bundle = enc(inventory), pack(files)
    assert review.review_bytes(raw, bundle).full_planned_byte_footer_coverage
    with pytest.raises(ValueError, match='LEGACY_ROW_OR_ANALYTICAL_COLUMN_RECONSTRUCTION_FAILED'):
        legacy.reconstruct(raw, bundle, inventory_sha256=hashlib.sha256(raw).hexdigest(),
                           bundle_sha256=hashlib.sha256(bundle).hexdigest())


def test_exact_pretty_printed_input_bytes_are_not_silently_canonicalised(
        generation: tuple[dict[str, Any], dict[str, bytes]]) -> None:
    inventory, files = generation
    compact, bundle = enc(inventory), pack(files)
    pretty = json.dumps(inventory, indent=2).encode()
    with pytest.raises(ValueError, match='EXACT_GENERATION_BYTES_REQUIRED'):
        legacy.directory_audit(pretty, bundle, inventory_sha256=hashlib.sha256(compact).hexdigest(),
                               bundle_sha256=hashlib.sha256(bundle).hexdigest())


@pytest.mark.parametrize('change', ['', 'key', 'anchor', 'body', 'generation', 'scope'])
def test_authentication_needs_external_anchor_and_never_authenticates_physical_custody(
        measured: tuple[legacy.RowWitness, str, str], change: str) -> None:
    witness, ip, bp = measured
    previous = receipts.genesis('legacy-archive:drive-rehearsal')
    key = b'SYNTHETIC_TEST_KEY_NOT_A_CREDENTIAL_000'
    sealed = legacy.seal(witness, previous, at=datetime(2026, 10, 18, tzinfo=timezone.utc),
                         key_id='synthetic', key=key, inventory_sha256=ip, bundle_sha256=bp)
    trusted = sealed.signed.anchor
    if change == 'key':
        key = b'OTHER_SYNTHETIC_TEST_KEY_NOT_REAL_000'
    elif change == 'anchor':
        trusted = previous
    elif change == 'body':
        sealed = replace(sealed, body=sealed.body+b' ')
    elif change == 'generation':
        bp = '0'*64
    elif change == 'scope':
        previous = receipts.genesis('legacy-archive:disk-rehearsal')
    if change:
        with pytest.raises(ValueError):
            legacy.verify(sealed, previous, trusted, keys={'synthetic': key}, inventory_sha256=ip, bundle_sha256=bp)
    else:
        assert legacy.verify(sealed, previous, trusted, keys={'synthetic': key},
                             inventory_sha256=ip, bundle_sha256=bp) == witness


@pytest.mark.parametrize('field', ['deletion_authorised', 'extra_authority', 'method', 'batches'])
def test_signer_rejects_expanded_authority_or_incomplete_scope(
        measured: tuple[legacy.RowWitness, str, str], field: str) -> None:
    witness, ip, bp = measured
    body = json.loads(witness.body)
    body[field] = body['batches'][:-1] if field == 'batches' else True
    with pytest.raises(ValueError):
        legacy.seal(legacy.RowWitness(enc(body)), receipts.genesis('legacy-archive:drive-rehearsal'),
            at=datetime(2026, 10, 18, tzinfo=timezone.utc), key_id='synthetic',
            key=b'SYNTHETIC_TEST_KEY_NOT_A_CREDENTIAL_000', inventory_sha256=ip, bundle_sha256=bp)


def test_journal_has_resource_and_empty_input_bounds() -> None:
    for texts in ([], ['x']*2001, ['x'*(legacy.MAX_ROW_BYTES+1)]):
        with pytest.raises(ValueError):
            legacy._journal_roundtrip(texts)


@pytest.mark.parametrize('args,status', [([], 'PREVIEW'),
    (['--inventory', 'PRIVATE_SENTINEL'], 'PREVIEW'), (['--unknown', 'PRIVATE_SENTINEL'], 'BLOCKED'),
    (['--confirm-directory-read'], 'BLOCKED')])
def test_directory_cli_preview_and_errors_are_redacted(args: list[str], status: str,
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError('NO_IO_OR_KEYS')
    monkeypatch.setattr(review, '_private_file', forbidden)
    result = legacy.main(args)
    text = capsys.readouterr().out
    assert 'PRIVATE_SENTINEL' not in text
    assert json.loads(text)['status'] == status
    assert result == (0 if status == 'PREVIEW' else 2)
