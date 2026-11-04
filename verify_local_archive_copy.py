"""Offline check of a downloaded copy of the Drive archive folder. No network, no credentials.

Usage: python verify_local_archive_copy.py FOLDER --expect N

Every `<table>-<batch>.manifest.json` must have its `<table>-<batch>.parquet` beside it (anywhere
under FOLDER), the file's sha256 must equal the manifest, and the rows must recompute to the
content-addressed batch id. Exit 0 only when nothing is missing or wrong and at least N batches
were verified. Row contents are never printed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from archive_restore_check import archived_rows
from drive_archive import ArchiveError


def verify_folder(folder: Path) -> dict:
    manifests, data = {}, {}
    for path in sorted(folder.rglob('*')):
        if path.name.endswith('.manifest.json'):
            manifests.setdefault(path.name, []).append(path)
        elif path.name.endswith('.parquet'):
            data.setdefault(path.name, []).append(path)
    failures, verified = [], 0
    for name, paths in manifests.items():
        label = name[:40]
        if len(paths) > 1:
            failures.append(f'{label}:DUPLICATE_MANIFEST_FILE')
            continue
        try:
            record = json.loads(paths[0].read_bytes())
            data_name = name.removesuffix('.manifest.json') + '.parquet'
            files = data.get(data_name, [])
            if len(files) != 1:
                raise ArchiveError('DATA_FILE_MISSING_OR_DUPLICATE')
            archived_rows(files[0].read_bytes(), {
                'batch_id': record['batch_id'], 'source_table': record['source_table'],
                'row_count': record['rows'], 'file_sha256': record['sha256']})
            if data_name != f"{record['source_table']}-{record['batch_id']}.parquet":
                raise ArchiveError('FILE_NAME_DOES_NOT_MATCH_MANIFEST')
            verified += 1
        except ArchiveError as error:
            failures.append(f'{label}:{error}')
        except Exception as error:  # noqa: BLE001 - never print file contents
            failures.append(f'{label}:{type(error).__name__}')
    used = {name.removesuffix('.manifest.json') + '.parquet' for name in manifests}
    orphans = sorted(set(data) - used)
    return {'manifests': len(manifests), 'verified': verified, 'failures': failures,
            'data_files_without_manifest': len(orphans)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('folder', type=Path)
    parser.add_argument('--expect', type=int, required=True, help='batches the database records')
    args = parser.parse_args(argv)
    if not args.folder.is_dir():
        print(json.dumps({'status': 'FAILED', 'error': 'FOLDER_NOT_FOUND'}))
        return 1
    result = verify_folder(args.folder)
    ok = (not result['failures'] and result['verified'] >= args.expect
          and result['data_files_without_manifest'] == 0)
    print(json.dumps({'status': 'COPY_VERIFIED' if ok else 'COPY_NOT_VERIFIED', 'expected': args.expect,
                      **{k: v for k, v in result.items() if k != 'failures'},
                      'failure_count': len(result['failures']), 'first_failures': result['failures'][:10]}))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
