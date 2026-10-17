"""Inactive legacy-row reconstruction and anchored witness codec.

Directory CLI is read-only and never decodes rows. Row rehearsal/signing are API
only, pending owner prerequisites and isolated acceptance. No keys are read here.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, NoReturn, cast
import zipfile

import archive_recovery_review as review
import catalog_receipts as receipts

SCOPES = frozenset({'legacy-archive:drive-rehearsal', 'legacy-archive:disk-rehearsal'})
MAX_ROW_BYTES = 1024 * 1024
MAX_BATCH_TEXT = 64 * 1024 * 1024
MAX_TOTAL_TEXT = 512 * 1024 * 1024
MAX_BODY = 128 * 1024


@dataclass(frozen=True)
class RowWitness:
    body: bytes = field(repr=False)


@dataclass(frozen=True)
class SealedWitness:
    body: bytes = field(repr=False)
    signed: receipts.SignedReceipt = field(repr=False)


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _pin(value: str) -> None:
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('EXPECTED_GENERATION_PIN_REQUIRED')


def _bind(inventory: bytes, bundle: bytes, inventory_sha256: str, bundle_sha256: str) -> None:
    for pin in (inventory_sha256, bundle_sha256):
        _pin(pin)
    if (type(inventory) is not bytes or not 0 < len(inventory) <= review.MAX_INDEX_BYTES
            or type(bundle) is not bytes or not 0 < len(bundle) <= review.MAX_ZIP_BYTES
            or hashlib.sha256(inventory).hexdigest() != inventory_sha256
            or hashlib.sha256(bundle).hexdigest() != bundle_sha256):
        raise ValueError('EXACT_GENERATION_BYTES_REQUIRED')


def directory_audit(inventory: bytes, bundle: bytes, *, inventory_sha256: str,
                    bundle_sha256: str) -> dict[str, object]:
    """Classify names only; outside-incident does NOT imply older or restorable."""
    _bind(inventory, bundle, inventory_sha256, bundle_sha256)
    expected = {r.batch_id: r.source_table for r in review.parse_inventory(inventory)}
    stream = io.BytesIO(bundle)
    review._zip_header(stream)
    stream.seek(0)
    with zipfile.ZipFile(stream) as archive:
        files, prefix = review._zip_index(archive)
        central_entries = len(archive.infolist())
        directory_entries = sum(info.is_dir() for info in archive.infolist())
        pairs: dict[tuple[str, str], set[str]] = {}
        nonstandard = other = 0
        for path in files:
            name = path[len(prefix):]
            match = re.fullmatch(r'([a-z_.]+)-([a-f0-9]{64})\.(parquet|manifest\.json)', name)
            if match is None or match[1] not in review.SPECS:
                if name.endswith(('.parquet', '.manifest.json')):
                    nonstandard += 1
                else:
                    other += 1
                continue
            pairs.setdefault((match[1], match[2]), set()).add(match[3])
        counts: dict[str, dict[str, int]] = {}
        for table in review.SPECS:
            selected = [(batch, kinds) for (t, batch), kinds in pairs.items() if t == table]
            counts[table] = dict(
                paired=sum(kinds == {'parquet', 'manifest.json'} for _, kinds in selected),
                incident_paired=sum(expected.get(batch) == table and kinds == {'parquet', 'manifest.json'}
                                    for batch, kinds in selected),
                outside_incident_paired=sum(expected.get(batch) != table and kinds == {'parquet', 'manifest.json'}
                                            for batch, kinds in selected),
                manifest_without_parquet=sum(kinds == {'manifest.json'} for _, kinds in selected),
                parquet_without_manifest=sum(kinds == {'parquet'} for _, kinds in selected))
    return dict(status='DIRECTORY_NAMES_CLASSIFIED_NOT_CONTENT_OR_DATE_VERIFIED', tables=counts,
        central_entries=central_entries, explicit_directory_entries=directory_entries,
        files=len(files), nonstandard_archive_names=nonstandard, other_files=other,
        inventory_sha256=inventory_sha256, bundle_sha256=bundle_sha256,
        row_pages_decoded=0, network_requests=0, credential_reads=0, writes=0,
        older_dates_verified=False, logical_restore_verified=False, independent_custody_verified=False,
        deletion_authorised=False, training_eligible=False, approval_authority=False)


def _journal_roundtrip(texts: list[str]) -> str:
    """Independent in-memory TEXT journal roundtrip, NOT PostgreSQL schema restore."""
    if not 0 < len(texts) <= 2000:
        raise ValueError('BATCH_ROW_BOUND')
    expected = hashlib.sha256()
    total = 0
    for text in texts:
        if type(text) is not str:
            raise ValueError('ROW_TEXT_REQUIRED')
        raw = text.encode('utf-8')
        total += len(raw)
        if len(raw) > MAX_ROW_BYTES or total > MAX_BATCH_TEXT:
            raise ValueError('ROW_TEXT_RESOURCE_BOUND')
        expected.update(len(raw).to_bytes(8, 'big') + raw)
    with sqlite3.connect(':memory:') as conn:
        conn.execute('PRAGMA temp_store=MEMORY')
        conn.execute('CREATE TABLE restored_rows(ordinal INTEGER PRIMARY KEY, original_json TEXT NOT NULL)')
        conn.executemany('INSERT INTO restored_rows VALUES (?,?)', enumerate(texts))
        conn.commit()
        actual = hashlib.sha256()
        count = 0
        for ordinal, text in conn.execute('SELECT ordinal,original_json FROM restored_rows ORDER BY ordinal'):
            if ordinal != count or type(text) is not str:
                raise ValueError('JOURNAL_READBACK_FAILED')
            raw = text.encode('utf-8')
            actual.update(len(raw).to_bytes(8, 'big') + raw)
            count += 1
        if count != len(texts) or actual.digest() != expected.digest():
            raise ValueError('JOURNAL_READBACK_FAILED')
    return actual.hexdigest()


def reconstruct(inventory: bytes, bundle: bytes, *, inventory_sha256: str,
                bundle_sha256: str) -> RowWitness:
    """Decode legacy incident rows operationally; NO owner CLI or real-data admission.

    Source uniqueness is checked WITHIN each archived batch by the existing codec.
    Cross-batch versions are retained separately, never overwritten/deduplicated.
    A trusted execution environment and sufficient RAM remain prerequisites.
    """
    _bind(inventory, bundle, inventory_sha256, bundle_sha256)
    checked = review.review_bytes(inventory, bundle)
    if not checked.full_planned_byte_footer_coverage:
        raise ValueError('COMPLETE_BYTE_FOOTER_REVIEW_REQUIRED')
    # Lazy import: production transport functions/credentials are never invoked.
    import drive_archive as codec
    verify_parquet = cast(Callable[[bytes, str, str, int, str], list[str]], codec.verify_parquet)
    batches: list[dict[str, object]] = []
    total = 0
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        files, prefix = review._zip_index(archive)
        for receipt in review.parse_inventory(inventory):
            stem = prefix + receipt.source_table + '-' + receipt.batch_id
            data = review._member(archive, files[stem + '.parquet'], review.MAX_PARQUET_BYTES)
            try:
                texts = verify_parquet(data, receipt.source_table,
                    receipt.batch_id, receipt.row_count, receipt.file_sha256)
            except Exception:
                raise ValueError('LEGACY_ROW_OR_ANALYTICAL_COLUMN_RECONSTRUCTION_FAILED') from None
            if type(texts) is not list or len(texts) != receipt.row_count:
                raise ValueError('LEGACY_ROW_COUNT_MISMATCH')
            total += sum(len(text.encode('utf-8')) for text in texts)
            if total > MAX_TOTAL_TEXT:
                raise ValueError('TOTAL_RECONSTRUCTION_BOUND')
            digest = _journal_roundtrip(texts)
            batches.append(dict(batch_id=receipt.batch_id, source_table=receipt.source_table,
                rows=receipt.row_count, parquet_sha256=receipt.file_sha256, journal_sha256=digest))
    body = _json(dict(format='legacy-row-rehearsal-v1', inventory_sha256=inventory_sha256,
        bundle_sha256=bundle_sha256, batches=batches, rows=review.EXPECTED_DELETED_ROWS,
        method='LEGACY_CODEC_AND_IN_MEMORY_SQLITE_TEXT_READBACK',
        archive_row_roundtrip_verified=True, cross_batch_versions_retained=True,
        postgres_restore_verified=False, persistent_target_verified=False,
        application_recovery_verified=False, encryption_verified=False,
        physical_independence_verified=False, historical_custody_verified=False,
        trusted_clock_verified=False, codec_runtime_identity_verified=False,
        deletion_authorised=False, training_eligible=False,
        approval_authority=False))
    if len(body) > MAX_BODY:
        raise ValueError('WITNESS_BODY_BOUND')
    return RowWitness(body)


def _body(witness: RowWitness, inventory_sha256: str, bundle_sha256: str) -> dict[str, Any]:
    if type(witness) is not RowWitness or type(witness.body) is not bytes or not 0 < len(witness.body) <= MAX_BODY:
        raise ValueError('WITNESS_BODY_INVALID')
    value = json.loads(witness.body, object_pairs_hook=review._pairs, parse_constant=review._constant)
    fields = {'format', 'inventory_sha256', 'bundle_sha256', 'batches', 'rows', 'method',
        'archive_row_roundtrip_verified', 'cross_batch_versions_retained', 'postgres_restore_verified',
        'persistent_target_verified', 'application_recovery_verified', 'encryption_verified',
        'physical_independence_verified', 'historical_custody_verified', 'trusted_clock_verified',
        'codec_runtime_identity_verified', 'deletion_authorised', 'training_eligible', 'approval_authority'}
    if (type(value) is not dict or set(value) != fields or _json(value) != witness.body
            or value.get('format') != 'legacy-row-rehearsal-v1'
            or value.get('method') != 'LEGACY_CODEC_AND_IN_MEMORY_SQLITE_TEXT_READBACK'
            or value.get('inventory_sha256') != inventory_sha256
            or value.get('bundle_sha256') != bundle_sha256
            or type(value.get('rows')) is not int or value['rows'] != review.EXPECTED_DELETED_ROWS
            or value.get('archive_row_roundtrip_verified') is not True
            or value.get('cross_batch_versions_retained') is not True):
        raise ValueError('WITNESS_GENERATION_INVALID')
    false_fields = ('postgres_restore_verified', 'persistent_target_verified', 'application_recovery_verified',
        'encryption_verified', 'physical_independence_verified', 'historical_custody_verified',
        'trusted_clock_verified', 'codec_runtime_identity_verified',
        'deletion_authorised', 'training_eligible', 'approval_authority')
    if any(value.get(name) is not False for name in false_fields):
        raise ValueError('UNSUPPORTED_WITNESS_AUTHORITY')
    batches = value.get('batches')
    if type(batches) is not list or len(batches) != review.EXPECTED_BATCHES:
        raise ValueError('WITNESS_DENOMINATOR_INVALID')
    seen: set[str] = set()
    totals: dict[str, tuple[int, int]] = {}
    for batch in batches:
        if (type(batch) is not dict or set(batch) != {'batch_id', 'source_table', 'rows', 'parquet_sha256', 'journal_sha256'}
                or type(batch['rows']) is not int or not 0 < batch['rows'] <= 2000):
            raise ValueError('WITNESS_BATCH_INVALID')
        for key in ('batch_id', 'parquet_sha256', 'journal_sha256'):
            _pin(batch[key])
        if batch['batch_id'] in seen or type(batch['source_table']) is not str:
            raise ValueError('WITNESS_BATCH_INVALID')
        seen.add(batch['batch_id'])
        count, rows = totals.get(batch['source_table'], (0, 0))
        totals[batch['source_table']] = (count+1, rows+batch['rows'])
    if totals != {table: (count, rows) for table, count, rows in review.INCIDENT_TABLE_TOTALS}:
        raise ValueError('WITNESS_DENOMINATOR_INVALID')
    return cast(dict[str, Any], value)


def seal(witness: RowWitness, previous: receipts.RootAnchor, *, at: datetime,
         key_id: str, key: bytes, inventory_sha256: str, bundle_sha256: str) -> SealedWitness:
    _pin(inventory_sha256)
    _pin(bundle_sha256)
    _body(witness, inventory_sha256, bundle_sha256)
    if previous.scope not in SCOPES:
        raise ValueError('DEDICATED_REHEARSAL_SCOPE_REQUIRED')
    signed = receipts.sign(previous, hashlib.sha256(witness.body).hexdigest(), bundle_sha256, at, key_id, key)
    return SealedWitness(witness.body, signed)


def verify(sealed: SealedWitness, previous: receipts.RootAnchor, trusted: receipts.RootAnchor, *,
           keys: Mapping[str, bytes], inventory_sha256: str, bundle_sha256: str) -> RowWitness:
    _pin(inventory_sha256)
    _pin(bundle_sha256)
    if previous.scope not in SCOPES or trusted.scope != previous.scope:
        raise ValueError('DEDICATED_REHEARSAL_SCOPE_REQUIRED')
    actual = receipts.verify(sealed.signed.data, trusted.receipt_sha256, previous, keys)
    if (actual != trusted or sealed.signed.anchor != trusted
            or actual.root != hashlib.sha256(sealed.body).hexdigest()):
        raise ValueError('EXTERNAL_WITNESS_ANCHOR_REQUIRED')
    witness = RowWitness(sealed.body)
    _body(witness, inventory_sha256, bundle_sha256)
    envelope = json.loads(sealed.signed.data)['message']
    if envelope['segment'] != bundle_sha256:
        raise ValueError('WITNESS_SEGMENT_MISMATCH')
    return witness


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError('DIRECTORY_ARGUMENTS_INVALID')


def main(argv: Sequence[str] | None = None) -> int:
    try:
        parser = _Parser(description='Directory-only review; row rehearsal API is inactive.')
        parser.add_argument('--inventory', type=Path)
        parser.add_argument('--bundle', type=Path)
        parser.add_argument('--inventory-sha256')
        parser.add_argument('--bundle-sha256')
        parser.add_argument('--confirm-directory-read', action='store_true')
        args = parser.parse_args(argv)
        if not args.confirm_directory_read:
            print(json.dumps(dict(status='PREVIEW', input_reads=0, writes=0, credential_reads=0, row_pages_decoded=0)))
            return 0
        if args.inventory is None or args.bundle is None or args.inventory_sha256 is None or args.bundle_sha256 is None:
            raise ValueError('EXPLICIT_PRIVATE_INPUTS_AND_PINS_REQUIRED')
        with review._private_file(args.inventory, review.MAX_INDEX_BYTES) as source:
            inventory = source.read(review.MAX_INDEX_BYTES+1)
        with review._private_file(args.bundle, review.MAX_ZIP_BYTES) as source:
            bundle = source.read(review.MAX_ZIP_BYTES+1)
        result = directory_audit(inventory, bundle, inventory_sha256=args.inventory_sha256,
                                 bundle_sha256=args.bundle_sha256)
        print(json.dumps(result))
        return 0
    except Exception:
        print(json.dumps(dict(status='BLOCKED', code='DIRECTORY_REVIEW_FAILED_RETAIN_INPUTS',
                              raw_error_printed=False, writes=0, approval_authority=False)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
