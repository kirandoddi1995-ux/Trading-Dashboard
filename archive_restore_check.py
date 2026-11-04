"""Restore proof for the Drive archive. Read-only: no Drive writes, no database writes.

Deletion of hot rows is allowed only after this proof passes in the same process:

1. Presence and bytes, every batch: one paged Drive folder listing must show each
   recorded data and manifest file, untrashed, with the batch's appProperties and
   (for data) Drive's own sha256Checksum equal to the recorded file_sha256. A batch
   whose checksum Drive does not report is deep-checked the same night instead.
2. Deep restore, a rotating seventh of all batches each night plus every batch
   verified in the last DEEP_RECENT_DAYS: download, re-hash, read the Parquet,
   recompute the content-addressed batch id from the archived rows, compare the
   archived manifest file, and load every archived row into the live table's row
   type (jsonb_populate_record) inside a read-only transaction. A row must come
   back identical, or identical apart from columns added later (null).

`restore-check` mode deep-checks every batch. Any failure blocks deletion; the
proof object is created only here, never from a flag or environment variable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import datetime as dt
from decimal import Decimal
import io
import json
import time
from typing import Any

import pyarrow.parquet as pq

from drive_archive import API, FORMAT_VERSION, KEYS, RELATIONS, SPECS, ArchiveError, digest, exact_json

DEEP_RECENT_DAYS = 8
DEEP_ROTATION = 7
PROOF_MAX_AGE_SECONDS = 6 * 3600
LISTING_PAGE = 1000
MAX_LISTING_PAGES = 200

RESTORE_SQL = """
WITH x AS (
    SELECT j, to_jsonb(jsonb_populate_record(NULL::{relation}, j)) AS r
    FROM unnest(%(rows)s::jsonb[]) AS j),
y AS (
    SELECT j, r, ARRAY(SELECT k FROM jsonb_object_keys(r) AS k WHERE NOT j ? k) AS added FROM x)
SELECT count(*) FILTER (WHERE r = j) AS exact_rows,
       count(*) FILTER (WHERE r <> j AND (r - added) = j
                        AND NOT EXISTS (SELECT 1 FROM unnest(added) AS k WHERE r -> k <> 'null'::jsonb)) AS added_column_rows,
       count(*) AS total_rows
FROM y"""


@dataclass(frozen=True)
class RestoreProof:
    manifests: int
    presence_verified: int
    deep_batches: int
    deep_rows: int
    exact_rows: int
    added_column_rows: int
    failures: tuple[str, ...]
    created: float = field(default_factory=time.monotonic)

    def valid_now(self) -> bool:
        return (not self.failures and self.presence_verified == self.manifests
                and time.monotonic() - self.created < PROOF_MAX_AGE_SECONDS)

    def summary(self) -> dict[str, Any]:
        return {'manifests': self.manifests, 'presence_verified': self.presence_verified,
                'deep_batches': self.deep_batches, 'deep_rows': self.deep_rows,
                'exact_rows': self.exact_rows, 'added_column_rows': self.added_column_rows,
                'failures': len(self.failures), 'first_failures': list(self.failures[:20])}


def load_manifests(repo) -> list[dict[str, Any]]:
    with repo.connection(readonly=True) as conn:
        rows = conn.execute("""SELECT batch_id,source_table,row_count,file_sha256,drive_file_id,
                drive_manifest_id,verified_at FROM quant_app.archive_manifests
                ORDER BY verified_at,batch_id""").fetchall()
    names = ('batch_id', 'source_table', 'row_count', 'file_sha256', 'drive_file_id',
             'drive_manifest_id', 'verified_at')
    return [dict(zip(names, row)) for row in rows]


def list_folder(drive) -> dict[str, dict[str, Any]]:
    """All untrashed files in the archive folder, with Drive's own checksums."""
    files: dict[str, dict[str, Any]] = {}
    token = None
    for _ in range(MAX_LISTING_PAGES):
        params = {'q': f"'{drive.folder_id}' in parents and trashed=false", 'pageSize': LISTING_PAGE,
                  'fields': 'nextPageToken,files(id,size,sha256Checksum,appProperties)'}
        if token:
            params['pageToken'] = token
        with drive.request('GET', API, params=params) as response:
            page = response.json()
        for item in page.get('files', []):
            files[item['id']] = item
        token = page.get('nextPageToken')
        if not token:
            return files
    raise ArchiveError('ARCHIVE_LISTING_TOO_LARGE')


def presence_failures(manifest: dict[str, Any], listing: dict[str, dict[str, Any]]) -> list[str]:
    batch = manifest['batch_id']
    problems = []
    data = listing.get(manifest['drive_file_id'])
    record = listing.get(manifest['drive_manifest_id'])
    if data is None:
        problems.append('DATA_FILE_MISSING')
    else:
        if (data.get('appProperties') or {}) != {'batch': batch, 'kind': 'data'}:
            problems.append('DATA_FILE_IDENTITY')
        checksum = data.get('sha256Checksum')
        if checksum is not None and checksum != manifest['file_sha256']:
            problems.append('DATA_FILE_CHECKSUM')
    if record is None:
        problems.append('MANIFEST_FILE_MISSING')
    elif (record.get('appProperties') or {}) != {'batch': batch, 'kind': 'manifest'}:
        problems.append('MANIFEST_FILE_IDENTITY')
    return [f'{batch[:12]}:{problem}' for problem in problems]


def archived_rows(data: bytes, manifest: dict[str, Any]) -> list[str]:
    """Verify one downloaded batch against its database record; return canonical row texts."""
    table = manifest['source_table']
    if table not in SPECS:
        raise ArchiveError('UNSUPPORTED_TABLE')
    if digest(data) != manifest['file_sha256']:
        raise ArchiveError('ARCHIVE_CHECKSUM_MISMATCH')
    parsed = pq.read_table(io.BytesIO(data))
    metadata = json.loads((parsed.schema.metadata or {}).get(b'quant_archive', b'{}'))
    if (parsed.num_rows != manifest['row_count'] or metadata.get('batch_id') != manifest['batch_id']
            or metadata.get('table') != table or metadata.get('format') != FORMAT_VERSION):
        raise ArchiveError('ARCHIVE_METADATA_MISMATCH')
    texts = parsed.column('_row_json').to_pylist()
    rows, seen = [], set()
    for text in texts:
        row = json.loads(text, parse_float=Decimal)
        key = tuple(row.get(name) for name in KEYS[table])
        if None in key or key in seen:
            raise ArchiveError('ARCHIVE_KEY_INVALID_OR_DUPLICATE')
        seen.add(key)
        rows.append(row)
    rows.sort(key=lambda row: tuple(str(row[name]) for name in KEYS[table]))
    identity = exact_json({'version': metadata['format'], 'table': table, 'rows': rows})
    if digest(identity.encode()) != manifest['batch_id']:
        raise ArchiveError('ARCHIVE_CONTENT_MISMATCH')
    return texts


def manifest_matches(raw: bytes, manifest: dict[str, Any]) -> bool:
    try:
        record = json.loads(raw)
    except ValueError:
        return False
    return (record.get('format') == FORMAT_VERSION and record.get('batch_id') == manifest['batch_id']
            and record.get('source_table') == manifest['source_table']
            and record.get('rows') == manifest['row_count'] and record.get('sha256') == manifest['file_sha256']
            and record.get('drive_file_id') == manifest['drive_file_id'])


def restore_counts(repo, table: str, texts: list[str]) -> tuple[int, int, int]:
    """(exact, identical-apart-from-later-null-columns, total) for the live row type."""
    with repo.connection(readonly=True) as conn:
        row = conn.execute(RESTORE_SQL.format(relation=RELATIONS[table]), {'rows': texts}).fetchone()
    return int(row[0]), int(row[1]), int(row[2])


def select_deep(manifests: list[dict[str, Any]], today: dt.date, everything: bool) -> list[dict[str, Any]]:
    if everything:
        return list(manifests)
    recent = dt.datetime.combine(today - dt.timedelta(days=DEEP_RECENT_DAYS), dt.time(), dt.timezone.utc)
    turn = today.toordinal() % DEEP_ROTATION
    return [m for index, m in enumerate(manifests)
            if index % DEEP_ROTATION == turn or (m['verified_at'] is not None and m['verified_at'] >= recent)]


def prove(repo, drive, *, today: dt.date, everything: bool = False,
          progress: Any = None) -> RestoreProof:
    manifests = load_manifests(repo)
    listing = list_folder(drive)
    failures: list[str] = []
    present = 0
    for manifest in manifests:
        problems = presence_failures(manifest, listing)
        failures.extend(problems)
        present += not problems
    deep = select_deep(manifests, today, everything)
    chosen = {manifest['batch_id'] for manifest in deep}
    deep += [manifest for manifest in manifests if manifest['batch_id'] not in chosen
             and (listing.get(manifest['drive_file_id']) or {}).get('sha256Checksum') is None]
    deep_rows = exact = added = 0
    for index, manifest in enumerate(deep, 1):
        label = manifest['batch_id'][:12]
        try:
            texts = archived_rows(drive.download(manifest['drive_file_id']), manifest)
            if not manifest_matches(drive.download(manifest['drive_manifest_id']), manifest):
                raise ArchiveError('ARCHIVE_MANIFEST_FILE_MISMATCH')
            same, later_null, total = restore_counts(repo, manifest['source_table'], texts)
            if total != len(texts) or same + later_null != total:
                raise ArchiveError('ARCHIVE_ROWS_NOT_RESTORABLE')
            deep_rows += total
            exact += same
            added += later_null
        except ArchiveError as error:
            failures.append(f'{label}:{error}')
        except Exception as error:  # noqa: BLE001 - parser/driver errors become safe codes
            failures.append(f'{label}:{type(error).__name__}')
        if progress is not None and index % 100 == 0:
            progress({'deep_checked': index, 'deep_total': len(deep), 'failures': len(failures)})
    return RestoreProof(manifests=len(manifests), presence_verified=present, deep_batches=len(deep),
                        deep_rows=deep_rows, exact_rows=exact, added_column_rows=added,
                        failures=tuple(failures))
