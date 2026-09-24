"""Lossless Parquet batches and narrowly scoped Drive transport.

No source deletion lives here. JSON/numeric text preserves PostgreSQL precision;
columnar fields remain directly usable in pandas, with types declared in metadata.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
import hashlib
import io
import json
import re

import pyarrow as pa
import pyarrow.parquet as pq
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SCOPE = 'https://www.googleapis.com/auth/drive.file'
TOKEN_URI = 'https://oauth2.googleapis.com/token'
API = 'https://www.googleapis.com/drive/v3/files'
MAX_BYTES = 32 * 1024 * 1024
FORMAT_VERSION = 'quant-archive-v1'
SPECS = {
    'equity_research.outcomes': {
        'snapshot_id': 'text', 'decision_id': 'text', 'payload': 'jsonb',
        'recorded_at': 'timestamptz',
    },
    'mf_nav': {
        'scheme_code': 'text', 'nav_date': 'date', 'isin_growth': 'text',
        'isin_reinvestment': 'text', 'scheme_name': 'text', 'amc': 'text',
        'category': 'text', 'plan': 'text', 'option_name': 'text', 'nav': 'numeric',
        'source': 'text', 'observed_at': 'timestamptz', 'source_hash': 'text',
    },
    'market_quotes': {
        'observed_at': 'timestamptz', 'trade_date': 'date', 'instrument_key': 'text',
        'source': 'text', 'last_price': 'numeric', 'open': 'numeric', 'high': 'numeric',
        'low': 'numeric', 'previous_close': 'numeric', 'volume': 'numeric',
        'open_interest': 'numeric', 'raw': 'jsonb',
    },
    'universe_membership_versions': {
        'snapshot_id': 'text', 'instrument_key': 'text', 'trading_symbol': 'text',
        'isin': 'text', 'name': 'text', 'exchange': 'text', 'segment': 'text',
        'instrument_type': 'text', 'security_type': 'text', 'sector': 'text',
        'source': 'text', 'observed_at': 'timestamptz', 'raw': 'jsonb',
    },
    'scanner_observations': {
        'observation_id': 'text', 'as_of_date': 'date', 'observed_at': 'timestamptz',
        'instrument_key': 'text', 'trading_symbol': 'text', 'strategy_version': 'text',
        'universe_snapshot_date': 'date', 'stage1_pass': 'boolean', 'stage2_pass': 'boolean',
        'rejection_reason': 'text', 'score': 'double precision', 'entry': 'double precision',
        'stop': 'double precision', 'target': 'double precision', 'feature_json': 'jsonb',
    },
}
KEYS = {'mf_nav': ('scheme_code', 'nav_date'),
        'equity_research.outcomes': ('snapshot_id',),
        'market_quotes': ('observed_at', 'instrument_key'),
        'universe_membership_versions': ('snapshot_id', 'instrument_key'),
        'scanner_observations': ('observation_id',)}

# Schema routing is fixed, never derived from user-supplied SQL identifiers.
RELATIONS = {key: ('equity_research.outcomes' if key == 'equity_research.outcomes'
                   else 'quant_app.' + key) for key in SPECS}


class ArchiveError(RuntimeError):
    """Safe error codes only: do not put credentials, payloads or HTTP bodies here."""


def credentials(token_info):
    """Build OAuth credentials locally; never trust token-provided endpoints/scopes."""
    if not isinstance(token_info, dict):
        raise ArchiveError('INVALID_OAUTH_CONFIGURATION')
    if (token_info.get('type') != 'authorized_user'
            or token_info.get('token_uri') != TOKEN_URI
            or token_info.get('scopes') != [SCOPE]
            or any(not isinstance(token_info.get(key), str)
                   or not token_info[key].strip()
                   for key in ('client_id', 'client_secret', 'refresh_token'))):
        raise ArchiveError('INVALID_OAUTH_CONFIGURATION')
    # Ignore any supplied access token: refresh using the validated configuration.
    return Credentials(
        token=None, refresh_token=token_info['refresh_token'],
        token_uri=TOKEN_URI, client_id=token_info['client_id'],
        client_secret=token_info['client_secret'], scopes=[SCOPE],
    )


def digest(data):
    return hashlib.sha256(data).hexdigest()


def exact_json(value):
    """Canonical JSON without converting arbitrary-precision numeric to float."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ArchiveError('NONFINITE_JSON_NUMBER')
        return str(value)
    if isinstance(value, dict):
        return '{' + ','.join(json.dumps(k) + ':' + exact_json(v)
                              for k, v in sorted(value.items())) + '}'
    if isinstance(value, list):
        return '[' + ','.join(exact_json(v) for v in value) + ']'
    return json.dumps(value, ensure_ascii=True, allow_nan=False)


def normalize_rows(table, texts):
    if table not in SPECS or not texts:
        raise ArchiveError('EMPTY_OR_UNSUPPORTED_BATCH')
    rows, seen = [], set()
    for text in texts:
        row = json.loads(text, parse_float=Decimal)
        if set(row) != set(SPECS[table]):
            raise ArchiveError('SOURCE_SCHEMA_CHANGED')
        key = tuple(row[k] for k in KEYS[table])
        if None in key or key in seen:
            raise ArchiveError('INVALID_OR_DUPLICATE_KEY')
        seen.add(key)
        rows.append(row)
    rows.sort(key=lambda row: tuple(str(row[k]) for k in KEYS[table]))
    return rows


def batch_identity(table, texts):
    rows = normalize_rows(table, texts)
    identity = exact_json({'version': FORMAT_VERSION, 'table': table, 'rows': rows})
    return digest(identity.encode()), rows


def parquet_bytes(table, texts):
    batch_id, rows = batch_identity(table, texts)
    fields, columns = [], {}
    for name, kind in SPECS[table].items():
        arrow_type = {'date': pa.date32(), 'timestamptz': pa.timestamp('us', tz='UTC')}.get(kind, pa.string())
        fields.append(pa.field(name, arrow_type))
        values = []
        for row in rows:
            value = row[name]
            if value is not None:
                if kind == 'date':
                    value = dt.date.fromisoformat(value)
                elif kind == 'timestamptz':
                    value = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
                    if value.tzinfo is None:
                        raise ArchiveError('NAIVE_TIMESTAMP')
                    value = value.astimezone(dt.timezone.utc)
                elif kind == 'jsonb':
                    value = exact_json(value)
                else:
                    value = str(value)  # NUMERIC uses lossless strings, never binary floats.
            values.append(value)
        columns[name] = values
    # Exact full row for restore and optimistic DELETE, including nested JSON.
    fields.append(pa.field('_row_json', pa.string(), nullable=False))
    columns['_row_json'] = [exact_json(row) for row in rows]
    metadata = {'format': FORMAT_VERSION, 'table': table, 'batch_id': batch_id,
                'postgres_types': SPECS[table], 'numeric_encoding': 'decimal-string'}
    schema = pa.schema(fields, metadata={b'quant_archive': exact_json(metadata).encode()})
    sink = io.BytesIO()
    pq.write_table(pa.Table.from_pydict(columns, schema=schema), sink, compression='zstd')
    result = sink.getvalue()
    if len(result) > MAX_BYTES:
        raise ArchiveError('BATCH_TOO_LARGE_REDUCE_BATCH_SIZE')
    return batch_id, result, columns['_row_json']


def verify_parquet(data, table, expected_id, expected_rows, expected_sha):
    if len(data) > MAX_BYTES or digest(data) != expected_sha:
        raise ArchiveError('ARCHIVE_CHECKSUM_MISMATCH')
    parsed = pq.read_table(io.BytesIO(data))
    metadata = json.loads((parsed.schema.metadata or {}).get(b'quant_archive', b'{}'))
    if (parsed.num_rows != expected_rows or metadata.get('batch_id') != expected_id
            or metadata.get('table') != table or metadata.get('format') != FORMAT_VERSION
            or metadata.get('postgres_types') != SPECS[table]):
        raise ArchiveError('ARCHIVE_METADATA_MISMATCH')
    texts = parsed.column('_row_json').to_pylist()
    actual_id, _ = batch_identity(table, texts)
    if actual_id != expected_id:
        raise ArchiveError('ARCHIVE_CONTENT_MISMATCH')
    # Compare all analytical columns too; the recovery copy alone is not enough.
    _, reconstructed, _ = parquet_bytes(table, texts)
    if not parsed.equals(pq.read_table(io.BytesIO(reconstructed)), check_metadata=True):
        raise ArchiveError('ARCHIVE_COLUMN_MISMATCH')
    return texts


class DriveArchive:
    def __init__(self, creds, folder_id):
        if not re.fullmatch(r'[A-Za-z0-9_-]+', folder_id):
            raise ArchiveError('INVALID_DRIVE_FOLDER')
        self.folder_id = folder_id
        self.session = AuthorizedSession(creds)
        # Retry reads only. An uncertain upload is discovered by batch identity
        # on the next run, not blindly POSTed repeatedly.
        retries = Retry(total=3, backoff_factor=1, allowed_methods={'GET'},
                        status_forcelist=(429, 500, 502, 503, 504))
        self.session.mount('https://', HTTPAdapter(max_retries=retries))

    def close(self):
        self.session.close()

    def request(self, method, url, **kwargs):
        response = self.session.request(method, url, timeout=(10, 90),
                                        allow_redirects=False, **kwargs)
        if not 200 <= response.status_code < 300:
            response.close()
            raise ArchiveError('DRIVE_HTTP_' + str(response.status_code))
        return response

    def check_folder(self):
        with self.request('GET', f'{API}/{self.folder_id}',
                          params={'fields': 'id,mimeType,trashed,capabilities(canAddChildren)'}) as response:
            info = response.json()
        if (info.get('trashed') or info.get('mimeType') != 'application/vnd.google-apps.folder'
                or not info.get('capabilities', {}).get('canAddChildren')):
            raise ArchiveError('DRIVE_FOLDER_NOT_WRITABLE')

    def download(self, file_id):
        if not re.fullmatch(r'[A-Za-z0-9_-]+', file_id):
            raise ArchiveError('INVALID_DRIVE_FILE_ID')
        with self.request('GET', f'{API}/{file_id}', params={'alt': 'media'}, stream=True) as response:
            output = io.BytesIO()
            for chunk in response.iter_content(65536):
                output.write(chunk)
                if output.tell() > MAX_BYTES:
                    raise ArchiveError('REMOTE_ARCHIVE_TOO_LARGE')
            return output.getvalue()

    def put(self, name, data, batch_id, kind, mime):
        if not re.fullmatch(r'[a-f0-9]{64}', batch_id) or kind not in ('data', 'manifest'):
            raise ArchiveError('INVALID_ARCHIVE_IDENTITY')
        q = (f"'{self.folder_id}' in parents and trashed=false and "
             f"appProperties has {{ key='batch' and value='{batch_id}' }} and "
             f"appProperties has {{ key='kind' and value='{kind}' }}")
        with self.request('GET', API, params={'q': q, 'fields': 'files(id),nextPageToken',
                                              'pageSize': 100}) as response:
            existing = response.json()
        files = existing.get('files', [])
        if existing.get('nextPageToken') or len(files) > 1:
            raise ArchiveError('DUPLICATE_DRIVE_BATCH_REVIEW_REQUIRED')
        if files:
            return files[0]['id']
        metadata = {'name': name, 'parents': [self.folder_id],
                    'appProperties': {'batch': batch_id, 'kind': kind}}
        # Drive multipart uses multipart/related (not requests' form-data).
        boundary = 'quant_' + batch_id
        body = (f'--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'.encode()
                + json.dumps(metadata).encode()
                + f'\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n'.encode()
                + data + f'\r\n--{boundary}--\r\n'.encode())
        with self.request('POST', 'https://www.googleapis.com/upload/drive/v3/files',
                          params={'uploadType': 'multipart', 'fields': 'id'}, data=body,
                          headers={'Content-Type': f'multipart/related; boundary={boundary}'}) as response:
            return response.json()['id']


def upload_verified(drive, table, texts):
    batch_id, data, canonical = parquet_bytes(table, texts)
    sha = digest(data)
    data_id = drive.put(f'{table}-{batch_id}.parquet', data, batch_id, 'data',
                        'application/vnd.apache.parquet')
    downloaded = drive.download(data_id)
    # Includes retry-after-crash: never overwrite an existing file. A writer
    # upgrade that changes bytes requires review, not relaxed verification.
    verified = verify_parquet(downloaded, table, batch_id, len(canonical), sha)
    if verified != canonical:
        raise ArchiveError('ARCHIVE_ROWS_DIFFER')
    manifest = {'format': FORMAT_VERSION, 'batch_id': batch_id, 'source_table': table,
                'rows': len(verified), 'sha256': sha, 'drive_file_id': data_id,
                'postgres_types': SPECS[table], 'numeric_encoding': 'decimal-string'}
    manifest_bytes = exact_json(manifest).encode()
    manifest_id = drive.put(f'{table}-{batch_id}.manifest.json', manifest_bytes,
                            batch_id, 'manifest', 'application/json')
    if drive.download(manifest_id) != manifest_bytes:
        raise ArchiveError('MANIFEST_MISMATCH')
    return {**manifest, 'drive_manifest_id': manifest_id}, verified
