"""Verified research-only Drive files. No SQL, deletion or promotion operations."""
import io
import json
from datetime import date

import pyarrow as pa
import pyarrow.parquet as pq

from drive_archive import API, ArchiveError, digest
from option_capture import MAX_BYTES, VERSION, canonical, CaptureError, timing_evidence

FIELDS = ('instrument_key', 'underlying', 'role', 'source_at', 'received_at',
          'bid', 'ask', 'bid_size', 'ask_size', 'reference', 'iv_raw', 'oi', 'volume')


def encode(report):
    rows = report['rows']
    if len(rows) > 150:
        raise CaptureError('ROW_BUDGET_EXCEEDED')
    schema = pa.schema([pa.field(k, pa.string()) for k in (*FIELDS, '_row_json')],
                       metadata={b'option_capture': canonical({k:v for k,v in report.items() if k != 'rows'})})
    columns = {k: [None if row.get(k) is None else str(row[k]) for row in rows] for k in FIELDS}
    columns['_row_json'] = [canonical(row).decode() for row in rows]
    sink = io.BytesIO()
    pq.write_table(pa.Table.from_pydict(columns, schema=schema), sink, compression='zstd')
    data = sink.getvalue()
    if len(data) > MAX_BYTES:
        raise CaptureError('ARCHIVE_BYTE_BUDGET_EXCEEDED')
    return data


def verify(data, sample_id, policy_hash):
    if not data or len(data) > MAX_BYTES:
        raise CaptureError('INVALID_ARCHIVE_SIZE')
    # Bound decompression using Parquet metadata before materializing the table.
    meta = pq.ParquetFile(io.BytesIO(data)).metadata
    if meta.num_rows > 150 or sum(meta.row_group(i).total_byte_size for i in range(meta.num_row_groups)) > 16*1024*1024:
        raise CaptureError('ARCHIVE_EXPANSION_BUDGET_EXCEEDED')
    table = pq.read_table(io.BytesIO(data))
    header = json.loads((table.schema.metadata or {})[b'option_capture'])
    if (header.get('sample_id') != sample_id or header.get('policy_hash') != policy_hash
            or header.get('format') != VERSION or header.get('mode') != 'RESEARCH_ONLY'
            or header.get('approval_eligible') is not False):
        raise CaptureError('ARCHIVE_IDENTITY_MISMATCH')
    rows = [json.loads(s) for s in table.column('_row_json').to_pylist()]
    if len({r['instrument_key'] for r in rows}) != len(rows):
        raise CaptureError('ARCHIVE_DUPLICATE_KEYS')
    report = dict(header, rows=rows)
    if 'timing_quality' in report:
        expected_timing = timing_evidence(report, date.fromisoformat(report['trading_date']), report['slot'])
        if any(report.get(k) != v for k, v in expected_timing.items()):
            raise CaptureError('ARCHIVE_TIMING_MISMATCH')
    # Check every analytical column, not just the recovery JSON.
    reconstructed = pq.read_table(io.BytesIO(encode(report)))
    if not table.equals(reconstructed, check_metadata=True):
        raise CaptureError('ARCHIVE_COLUMN_MISMATCH')
    return report


def lookup(drive, sample_id, kind):
    if len(sample_id) != 64 or any(c not in '0123456789abcdef' for c in sample_id) or kind not in {'data', 'manifest'}:
        raise CaptureError('INVALID_SAMPLE_ID')
    query = (f"'{drive.folder_id}' in parents and trashed=false and "
             f"appProperties has {{ key='batch' and value='{sample_id}' }} and "
             f"appProperties has {{ key='kind' and value='{kind}' }}")
    with drive.request('GET', API, params={'q': query, 'fields': 'files(id),nextPageToken', 'pageSize': 100}) as response:
        body = response.json()
    files = body.get('files', [])
    if body.get('nextPageToken') or len(files) > 1:
        raise ArchiveError('DUPLICATE_DRIVE_BATCH_REVIEW_REQUIRED')
    return files[0]['id'] if files else None


def manifest_for(data_id, data, report):
    manifest = dict(format=VERSION, sample_id=report['sample_id'], policy_hash=report['policy_hash'],
                    sha256=digest(data), rows=len(report['rows']), data_file_id=data_id,
                    status=report['status'], captured_at=report['captured_at'],
                    mode='RESEARCH_ONLY', approval_eligible=False)
    for field in ('scheduled_at', 'capture_delay_seconds', 'timing_quality',
                  'comparison_tolerance_seconds', 'same_time_comparison_eligible'):
        if field in report:
            manifest[field] = report[field]
    return manifest


def finish(drive, data_id, data, report):
    manifest = manifest_for(data_id, data, report)
    content = canonical(manifest)
    ident = drive.put('options-'+report['sample_id']+'.manifest.json', content,
                      report['sample_id'], 'manifest', 'application/json')
    if drive.download(ident) != content:
        raise CaptureError('MANIFEST_VERIFICATION_FAILED')
    return manifest


def resume(drive, sample_id, policy_hash):
    """Recover an acknowledged or orphan data upload without recapturing a new cut.

    First verified sample wins for a policy/date/slot. Duplicate files cause an
    explicit failure, never arbitrary selection. No overwrite or deletion.
    """
    data_id = lookup(drive, sample_id, 'data')
    manifest_id = lookup(drive, sample_id, 'manifest')
    if manifest_id and not data_id:
        raise CaptureError('MANIFEST_WITHOUT_DATA')
    if not data_id:
        return None
    data = drive.download(data_id)
    report = verify(data, sample_id, policy_hash)
    return finish(drive, data_id, data, report)


def publish(drive, report):
    data = encode(report)
    name = f"options-{report['trading_date']}-{report['slot']}-{report['sample_id']}.parquet"
    ident = drive.put(name, data, report['sample_id'], 'data', 'application/vnd.apache.parquet')
    downloaded = drive.download(ident)
    if digest(downloaded) != digest(data):
        raise CaptureError('ARCHIVE_CHECKSUM_CONFLICT')
    verified = verify(downloaded, report['sample_id'], report['policy_hash'])
    if canonical(verified) != canonical(report):
        raise CaptureError('ARCHIVE_ROW_MISMATCH')
    return finish(drive, ident, downloaded, verified)


def inspect_sample(drive, sample_id, policy_hash, *, details=False):
    """Read-only end-of-day completeness check, including downloaded checksum."""
    data_id = lookup(drive, sample_id, 'data')
    manifest_id = lookup(drive, sample_id, 'manifest')
    if not data_id or not manifest_id:
        return {'status': 'MISSING_OR_UNVERIFIED'} if details else 'MISSING_OR_UNVERIFIED'
    data = drive.download(data_id)
    report = verify(data, sample_id, policy_hash)
    manifest = json.loads(drive.download(manifest_id))
    expected = manifest_for(data_id, data, report)
    if manifest != expected:
        raise CaptureError('MANIFEST_VERIFICATION_FAILED')
    if details:
        return dict(status=report['status'], timing_quality=report.get('timing_quality', 'UNVERIFIED'),
                    capture_delay_seconds=report.get('capture_delay_seconds'),
                    same_time_comparison_eligible=report.get('same_time_comparison_eligible', False))
    return report['status']
