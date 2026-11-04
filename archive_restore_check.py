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
Before every deletion batch, recheck_presence() repeats step 1 against a fresh
listing, so a file trashed or changed after the proof stops deletion at once.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import datetime as dt
from decimal import Decimal
import hashlib
import io
import json
import time
from typing import Any

import pyarrow.parquet as pq

from drive_archive import (API, FORMAT_VERSION, KEYS, RELATIONS, SPECS, ArchiveError, digest, exact_json,
                           manifest_record)

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


_ISSUER = object()  # Only prove() holds this; a hand-built proof is rejected.


def context_key(repo, drive) -> str:
    """Identity of the database and Drive folder a proof was made for (never printed)."""
    text = f"{getattr(repo, 'url', '')}|{getattr(drive, 'folder_id', '')}"
    return hashlib.sha256(text.encode()).hexdigest()


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
    issuer: object = field(default=None, repr=False, compare=False)
    context: str = field(default='', repr=False)
    # Manifest file id -> sha256 of the bytes seen at proof time; later rechecks must still match.
    manifest_pins: dict = field(default_factory=dict, repr=False, compare=False)

    def valid_now(self, context: str | None = None) -> bool:
        return (self.issuer is _ISSUER and not self.failures and self.presence_verified == self.manifests
                and time.monotonic() - self.created < PROOF_MAX_AGE_SECONDS
                and (context is None or self.context == context))

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


def expected_manifest_bytes(batch_id: str, table: str, rows: int, sha: str, data_id: str) -> bytes:
    return exact_json(manifest_record(batch_id, table, rows, sha, data_id)).encode()


class _RolledBack(Exception):
    pass


def rehearse_insert(repo, table: str, texts: list[str]) -> int:
    """Insert the archived rows into an empty temporary copy of the live table, then roll back.

    The copy carries the live defaults, CHECK/NOT NULL constraints and unique indexes, so a row
    or a pair of versions the live table would refuse is found here. Nothing persists. Foreign
    keys, triggers and row-level security are NOT exercised; a full disposable-database restore
    drill remains the only proof of those.
    """
    relation = RELATIONS[table]
    try:
        with repo.connection() as conn:
            conn.execute(f'CREATE TEMP TABLE restore_rehearsal (LIKE {relation} INCLUDING DEFAULTS '
                         'INCLUDING CONSTRAINTS INCLUDING INDEXES) ON COMMIT DROP')
            inserted = conn.execute(
                f'WITH put AS (INSERT INTO restore_rehearsal SELECT (jsonb_populate_record('
                f'NULL::{relation}, j)).* FROM unnest(%(rows)s::jsonb[]) AS j RETURNING 1) '
                'SELECT count(*) FROM put', {'rows': texts}).fetchone()[0]
            # Deferred constraints would otherwise be skipped by the rollback below.
            conn.execute('SET CONSTRAINTS ALL IMMEDIATE')
            raise _RolledBack  # leaving the transaction by exception rolls everything back
    except _RolledBack:
        pass
    except ArchiveError:
        raise
    except Exception:  # noqa: BLE001 - any refusal means the rows would not come back
        raise ArchiveError('ARCHIVE_ROWS_NOT_INSERTABLE') from None
    if inserted != len(texts):
        raise ArchiveError('ARCHIVE_ROWS_NOT_INSERTABLE')
    return inserted


def confirm_custody(drive, manifest: dict[str, Any], *, check_bytes: bool = True) -> None:
    """Fresh proof that both files of one just-uploaded batch exist, are untrashed and unchanged.

    Takes the upload record (batch_id, source_table, rows, sha256, drive_file_id, drive_manifest_id).
    check_bytes=False is the quick form used while database locks are held: identity, trashed flag and
    Drive's own sha256 (a missing checksum fails closed). The full download runs before any lock.
    """
    batch = manifest['batch_id']
    manifest_bytes = expected_manifest_bytes(batch, manifest['source_table'], manifest['rows'],
                                             manifest['sha256'], manifest['drive_file_id'])
    for key, kind in (('drive_file_id', 'data'), ('drive_manifest_id', 'manifest')):
        try:
            meta = drive.metadata(manifest[key])
            raw = drive.download(manifest[key]) if check_bytes else None
        except ArchiveError:
            raise ArchiveError('ARCHIVE_CUSTODY_LOST') from None
        expected = manifest['sha256'] if kind == 'data' else digest(manifest_bytes)
        wanted = (digest(raw) == manifest['sha256'] if kind == 'data' else raw == manifest_bytes) \
            if check_bytes else meta.get('sha256Checksum') == expected  # quick: Drive's own checksum
        if (meta.get('trashed') or (meta.get('appProperties') or {}) != {'batch': batch, 'kind': kind}
                or not wanted):
            raise ArchiveError('ARCHIVE_CUSTODY_LOST')


class CustodyCheck:
    """The only custody callback acknowledge() accepts: bound to one batch, one database and folder."""

    def __init__(self, repo, drive, manifest: dict[str, Any]):
        self.context = context_key(repo, drive)
        self.batch_id = manifest['batch_id']
        self.sha256 = manifest['sha256']
        self._drive = drive
        self._manifest = dict(manifest)

    def __call__(self) -> None:
        confirm_custody(self._drive, self._manifest, check_bytes=False)


def valid_custody(custody: Any, manifest: dict[str, Any]) -> bool:
    return (isinstance(custody, CustodyCheck) and custody.batch_id == manifest['batch_id']
            and custody.sha256 == manifest['sha256'])


def _row_key(table: str, text: str) -> tuple[str, str]:
    row = json.loads(text, parse_float=Decimal)
    return tuple(str(row.get(name)) for name in KEYS[table]), hashlib.sha256(text.encode()).hexdigest()


def prove(repo, drive, *, today: dt.date, everything: bool = False,
          progress: Any = None) -> RestoreProof:
    manifests = load_manifests(repo)
    listing = list_folder(drive)
    failures: list[str] = []
    present = 0
    pins: dict[str, str] = {}
    for manifest in manifests:
        problems = presence_failures(manifest, listing)
        failures.extend(problems)
        present += not problems
    # Every manifest file is read and matched to its database record, so a pin is never taken
    # from bytes nobody has checked (a corrupt unsampled manifest cannot become the baseline).
    for manifest in manifests:
        label = manifest['batch_id'][:12]
        try:
            raw_manifest = drive.download(manifest['drive_manifest_id'])
            stated = (listing.get(manifest['drive_manifest_id']) or {}).get('sha256Checksum')
            if not manifest_matches(raw_manifest, manifest) or (
                    stated is not None and stated != digest(raw_manifest)):
                raise ArchiveError('ARCHIVE_MANIFEST_FILE_MISMATCH')
            pins[manifest['drive_manifest_id']] = digest(raw_manifest)
        except ArchiveError as error:
            failures.append(f'{label}:{error}')
        except Exception as error:  # noqa: BLE001
            failures.append(f'{label}:{type(error).__name__}')
    deep = select_deep(manifests, today, everything)
    chosen = {manifest['batch_id'] for manifest in deep}
    # Anything whose bytes Drive cannot vouch for is downloaded and compared tonight.
    deep += [manifest for manifest in manifests if manifest['batch_id'] not in chosen
             and (listing.get(manifest['drive_file_id']) or {}).get('sha256Checksum') is None]
    deep_rows = exact = added = 0
    seen_keys: dict[tuple[str, tuple[str, ...]], str] = {}
    for index, manifest in enumerate(deep, 1):
        label = manifest['batch_id'][:12]
        try:
            texts = archived_rows(drive.download(manifest['drive_file_id']), manifest)
            same, later_null, total = restore_counts(repo, manifest['source_table'], texts)
            if total != len(texts) or same + later_null != total:
                raise ArchiveError('ARCHIVE_ROWS_NOT_RESTORABLE')
            rehearse_insert(repo, manifest['source_table'], texts)
            if everything:
                for text in texts:
                    key, fingerprint = _row_key(manifest['source_table'], text)
                    if seen_keys.setdefault((manifest['source_table'], key), fingerprint) != fingerprint:
                        raise ArchiveError('CROSS_BATCH_KEY_CONFLICT')
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
                        failures=tuple(failures), issuer=_ISSUER, context=context_key(repo, drive),
                        manifest_pins=pins)


def recheck_presence(repo, drive, proof: RestoreProof) -> int:
    """Fresh listing of every recorded batch against what the proof saw; raise on any difference.

    Data files are held to the database checksum, downloaded when Drive reports none. Manifest
    files are held to the checksum pinned at proof time, or for batches recorded since the
    proof to the exact bytes their record implies (downloaded when Drive reports no checksum).
    """
    manifests = load_manifests(repo)
    listing = list_folder(drive)
    for manifest in manifests:
        if presence_failures(manifest, listing):
            raise ArchiveError('ARCHIVE_PRESENCE_CHANGED_SINCE_PROOF')
        data_item = listing[manifest['drive_file_id']]
        record_item = listing[manifest['drive_manifest_id']]
        pinned = proof.manifest_pins.get(manifest['drive_manifest_id'])
        if pinned is None:
            pinned = digest(expected_manifest_bytes(manifest['batch_id'], manifest['source_table'],
                                                    manifest['row_count'], manifest['file_sha256'],
                                                    manifest['drive_file_id']))
        try:
            if data_item.get('sha256Checksum') is None and digest(
                    drive.download(manifest['drive_file_id'])) != manifest['file_sha256']:
                raise ArchiveError('ARCHIVE_PRESENCE_CHANGED_SINCE_PROOF')
            seen = record_item.get('sha256Checksum')
            if seen is None:
                seen = digest(drive.download(manifest['drive_manifest_id']))
        except ArchiveError:
            raise ArchiveError('ARCHIVE_PRESENCE_CHANGED_SINCE_PROOF') from None
        if seen != pinned:
            raise ArchiveError('ARCHIVE_PRESENCE_CHANGED_SINCE_PROOF')
    return len(manifests)
