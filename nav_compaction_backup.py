"""One-time surviving NAV backup; SELECT-only source, private Drive, offline rehearsal."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Callable, Protocol

from archive_maintenance import ArchiveRepository
from drive_archive import DriveArchive, MAX_BYTES, SPECS, credentials

FORMAT = 'nav-live-backup-v1'
EXPECTED_ROWS = 9424
EXPECTED_MD5 = '566e821aa5e6c28826d5b5532de895f8'
SQL = """WITH rows AS MATERIALIZED (
 SELECT scheme_code,to_jsonb(s)::text AS original FROM quant_app.mf_nav s
 ORDER BY scheme_code LIMIT 10001
) SELECT count(*),count(DISTINCT scheme_code),
 md5(string_agg(original,E'\\n' ORDER BY scheme_code)),
 array_agg(original ORDER BY scheme_code) FROM rows"""
# Fresh in-memory SQL instance ONLY. No database URL or persistent DB directory.
REHEARSAL = r"""
const {PGlite}=require(process.argv[1]);
let input='';process.stdin.setEncoding('utf8');
process.stdin.on('data',s=>{input+=s;});
process.stdin.on('end',async()=>{
 const db=new PGlite();
 try {
  await db.exec(`CREATE SCHEMA quant_app; CREATE TABLE quant_app.mf_nav (
    scheme_code text NOT NULL,nav_date date NOT NULL,isin_growth text,
    isin_reinvestment text,scheme_name text NOT NULL,amc text,category text,
    plan text,option_name text,nav numeric NOT NULL,source text NOT NULL,
    observed_at timestamptz NOT NULL,source_hash text NOT NULL,
    PRIMARY KEY(scheme_code,nav_date)); SET TIME ZONE 'UTC';`);
  await db.query('INSERT INTO quant_app.mf_nav SELECT * FROM jsonb_populate_recordset(NULL::quant_app.mf_nav,$1::jsonb)',[input]);
  const r=await db.query(`SELECT count(*)::int AS rows,
   md5(string_agg(to_jsonb(s)::text,E'\n' ORDER BY scheme_code)) AS fingerprint
   FROM quant_app.mf_nav s`);
  process.stdout.write(JSON.stringify(r.rows[0]));
 } catch (_) {process.exitCode=2;}
 finally {await db.close();}
});
"""


class BackupBlocked(RuntimeError):
    """Only fixed diagnostics; never payloads, secret values or raw driver errors."""


class Drive(Protocol):
    """Use the existing bounded, TLS-verified private archive transport."""
    def check_folder(self) -> None: ...
    def put(self, name: str, data: bytes, batch_id: str, kind: str, mime: str) -> str: ...
    def download(self, file_id: str) -> bytes: ...
    def close(self) -> None: ...


def sha(raw: bytes) -> str:
    """Identity of exact original PostgreSQL row text bytes."""
    return hashlib.sha256(raw).hexdigest()


def verify(raw: bytes, receipt: dict[str, Any]) -> list[str]:
    """Require the reviewed surviving-table identity, not just a self-consistent hash."""
    if (not raw or len(raw) > MAX_BYTES or receipt.get('format') != FORMAT
            or receipt.get('table') != 'quant_app.mf_nav'
            or type(receipt.get('rows')) is not int or receipt['rows'] != EXPECTED_ROWS
            or receipt.get('fingerprint') != EXPECTED_MD5
            or receipt.get('sha256') != sha(raw)
            or receipt.get('postgres_types') != SPECS['mf_nav']
            or receipt.get('source_sql_read_only') is not True
            or receipt.get('approval_authority') is not False
            or receipt.get('deleted') != 0 or type(receipt.get('deleted')) is not int):
        raise BackupBlocked('NAV_BACKUP_IDENTITY_MISMATCH')
    texts = raw.decode('utf-8').split('\n')
    # MD5 only compares the existing owner-reviewed SQL invariant; SHA256 secures bytes.
    if len(texts) != EXPECTED_ROWS or hashlib.md5(raw).hexdigest() != EXPECTED_MD5:
        raise BackupBlocked('NAV_BACKUP_ROWS_MISMATCH')
    schemes: set[str] = set()
    for text in texts:
        row = json.loads(text)
        if (not isinstance(row, dict) or set(row) != set(SPECS['mf_nav'])
                or not isinstance(row.get('scheme_code'), str)
                or row['scheme_code'] in schemes):
            raise BackupBlocked('NAV_BACKUP_SCHEMA_OR_KEYS_CHANGED')
        schemes.add(row['scheme_code'])
    return texts


def snapshot(repository: Any) -> tuple[bytes, dict[str, Any]]:
    """All row text and SQL fingerprint share one MVCC snapshot; no archive manifest write."""
    with repository.connection(readonly=True) as conn:
        result = conn.execute(SQL).fetchone()
    if (not result or type(result[0]) is not int or type(result[1]) is not int
            or result[0] != EXPECTED_ROWS or result[1] != EXPECTED_ROWS
            or result[2] != EXPECTED_MD5 or not isinstance(result[3], list)
            or any(not isinstance(row, str) for row in result[3])):
        raise BackupBlocked('NAV_SOURCE_CHANGED_REVIEW_REQUIRED')
    raw = '\n'.join(result[3]).encode('utf-8')
    receipt = {'format': FORMAT, 'table': 'quant_app.mf_nav', 'rows': EXPECTED_ROWS,
               'fingerprint': EXPECTED_MD5, 'sha256': sha(raw),
               'postgres_types': SPECS['mf_nav'], 'source_sql_read_only': True,
               'deleted': 0, 'approval_authority': False}
    verify(raw, receipt)
    return raw, receipt


def publish(drive: Drive, raw: bytes, receipt: dict[str, Any]) -> dict[str, Any]:
    """Remote acknowledgment follows BOTH exact data and manifest download checks."""
    verify(raw, receipt)
    drive.check_folder()
    identity = sha(FORMAT.encode() + b'\0' + raw)
    data_id = drive.put('mf-nav-live-' + identity + '.jsonl', raw, identity,
                        'data', 'application/x-ndjson')
    downloaded = drive.download(data_id)
    if downloaded != raw:
        raise BackupBlocked('NAV_DRIVE_DATA_MISMATCH')
    verify(downloaded, receipt)
    manifest = dict(receipt, drive_file_id=data_id)
    encoded = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode('utf-8')
    manifest_id = drive.put('mf-nav-live-' + identity + '.manifest.json', encoded,
                            identity, 'manifest', 'application/json')
    if drive.download(manifest_id) != encoded:
        raise BackupBlocked('NAV_DRIVE_MANIFEST_MISMATCH')
    return dict(manifest, status='NAV_LIVE_BACKUP_REMOTE_VERIFIED',
                drive_manifest_id=manifest_id)


def bounded_read(path: Path) -> bytes:
    """Never load an unbounded/corrupt owner-downloaded backup into memory."""
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise BackupBlocked('NAV_BACKUP_TOO_LARGE')
    return raw


def rehearse(raw: bytes, receipt: dict[str, Any], module: Path) -> dict[str, Any]:
    """Restore exact numeric JSON in disposable offline PostgreSQL; never hosted SQL."""
    texts = verify(raw, receipt)
    if not module.is_dir():
        raise BackupBlocked('LOCAL_POSTGRES_HARNESS_REQUIRED')
    result = subprocess.run(['node', '-e', REHEARSAL, str(module.resolve())],
                            input='[' + ','.join(texts) + ']', capture_output=True,
                            text=True, encoding='utf-8', timeout=60, check=False)
    if result.returncode != 0:
        raise BackupBlocked('NAV_OFFLINE_RESTORE_FAILED')
    actual = json.loads(result.stdout)
    if actual != {'rows': EXPECTED_ROWS, 'fingerprint': EXPECTED_MD5}:
        raise BackupBlocked('NAV_OFFLINE_RESTORE_MISMATCH')
    return {'status': 'NAV_OFFLINE_RESTORE_VERIFIED', 'rows': EXPECTED_ROWS,
            'fingerprint': EXPECTED_MD5, 'sha256': receipt['sha256'],
            'hosted_changes': 0, 'approval_authority': False}


def main(argv: list[str] | None = None) -> int:
    """Offline preview default; export is separately confirmed; all failures redacted."""
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--export', action='store_true')
    modes.add_argument('--rehearse', action='store_true')
    parser.add_argument('--data', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--pglite-module', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.export:
            if os.environ.get('NAV_BACKUP_AUTHORISED') != 'true':
                raise BackupBlocked('NAV_BACKUP_CONFIRMATION_REQUIRED')
            repository_factory: Callable[[str | None], Any] = ArchiveRepository
            repository = repository_factory(os.environ.get('ARCHIVE_DATABASE_URL'))
            raw, receipt = snapshot(repository)
            credential_factory: Callable[[Any], Any] = credentials
            drive_factory: Callable[[Any, str], Drive] = DriveArchive
            creds = credential_factory(json.loads(os.environ['DRIVE_OAUTH_TOKEN_JSON']))
            drive = drive_factory(creds, os.environ['DRIVE_ARCHIVE_FOLDER_ID'])
            try:
                result = publish(drive, raw, receipt)
            finally:
                drive.close()
        elif args.rehearse:
            if not args.data or not args.manifest or not args.pglite_module:
                raise BackupBlocked('NAV_REHEARSAL_INPUTS_REQUIRED')
            result = rehearse(bounded_read(args.data), json.loads(bounded_read(args.manifest)),
                              args.pglite_module)
        else:
            result = {'status': 'PREVIEW', 'network_calls': 0, 'deleted': 0,
                      'rows_required': EXPECTED_ROWS, 'fingerprint_required': EXPECTED_MD5}
    except Exception as error:
        allowed = {'NAV_BACKUP_CONFIRMATION_REQUIRED', 'NAV_SOURCE_CHANGED_REVIEW_REQUIRED',
                   'NAV_BACKUP_IDENTITY_MISMATCH', 'NAV_BACKUP_ROWS_MISMATCH',
                   'NAV_BACKUP_SCHEMA_OR_KEYS_CHANGED', 'NAV_DRIVE_DATA_MISMATCH',
                   'NAV_DRIVE_MANIFEST_MISMATCH', 'NAV_BACKUP_TOO_LARGE',
                   'LOCAL_POSTGRES_HARNESS_REQUIRED', 'NAV_OFFLINE_RESTORE_FAILED',
                   'NAV_OFFLINE_RESTORE_MISMATCH', 'NAV_REHEARSAL_INPUTS_REQUIRED'}
        code = str(error) if isinstance(error, BackupBlocked) and str(error) in allowed else 'NAV_BACKUP_UNAVAILABLE'
        print(json.dumps({'status': 'BLOCKED', 'code': code, 'deleted': 0}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
