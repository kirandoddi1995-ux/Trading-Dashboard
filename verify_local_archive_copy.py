"""Offline check of a downloaded copy of the Drive archive folder. No network, no credentials.

Usage (qualifying a copy):
    python verify_local_archive_copy.py FOLDER --inventory INVENTORY.json --inventory-sha256 HASH

INVENTORY.json is a frozen, read-only export of quant_app.archive_manifests (exact batch ids, row
counts and hashes); HASH is its sha256, recorded somewhere independent of the copy (the anchor).
The copy matches only when, for EVERY inventory batch, exactly one data file and one manifest file
exist under FOLDER; the manifest is byte-for-byte the manifest the record implies (so format, types,
extra or duplicate keys are all rejected); the data file's sha256 equals the record and its rows
recompute to the content-addressed batch id; and FOLDER holds no archive file outside the inventory.
Reading the files from FOLDER is the readback. Physical independence (a separate external disk, not
a cloud-sync folder) is the owner's evidence; a path inside a known sync folder is refused.

Usage (qualifying a copy against a database fingerprint, no inventory file to move):
    python verify_local_archive_copy.py FOLDER --expect-batches N --expect-set-sha256 HASH

N and HASH come from INVENTORY_SET_SQL run read-only on the database at copy time: HASH is the
sha256 of every batch's (batch_id, table, row_count, file_sha256, drive_file_id) line, sorted by
batch id. The copy matches only when every manifest is exact, every data file matches it, no file
is orphaned, and the lines rebuilt from the copy give exactly N batches and the same HASH.

Usage (self-consistency only, never custody or deletion authority):
    python verify_local_archive_copy.py FOLDER --self-check-only

Row contents are never printed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from archive_restore_check import archived_rows, expected_manifest_bytes
from drive_archive import MAX_BYTES, ArchiveError, SPECS

INVENTORY_FORMAT = 'archive-inventory-v1'
ENTRY_FIELDS = frozenset({'batch_id', 'source_table', 'row_count', 'file_sha256', 'drive_file_id',
                          'drive_manifest_id'})
HEX64 = re.compile(r'[0-9a-f]{64}')
DRIVE_ID = re.compile(r'[A-Za-z0-9_-]+')
SYNC_FOLDERS = ('my drive', 'google drive', 'googledrive', 'onedrive', 'dropbox', 'icloud drive',
                'shared drives')


# Run read-only on the database; must stay byte-compatible with inventory_line() below.
INVENTORY_SET_SQL = """SELECT count(*) AS batches, encode(sha256(convert_to(string_agg(
  batch_id||E'\\t'||source_table||E'\\t'||row_count::text||E'\\t'||file_sha256||E'\\t'||drive_file_id||E'\\n',
  '' ORDER BY batch_id COLLATE "C"), 'UTF8')), 'hex') AS set_sha256 FROM quant_app.archive_manifests"""


def inventory_line(entry: dict[str, Any]) -> str:
    return (f"{entry['batch_id']}\t{entry['source_table']}\t{entry['row_count']}\t"
            f"{entry['file_sha256']}\t{entry['drive_file_id']}\n")


def inventory_set_sha256(entries: list[dict[str, Any]]) -> str:
    lines = sorted(inventory_line(entry) for entry in entries)  # batch_id leads each line
    return hashlib.sha256(''.join(lines).encode()).hexdigest()


class InventoryError(ValueError):
    pass


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise InventoryError('INVENTORY_DUPLICATE_KEY')
        value[key] = item
    return value


def _no_constants(_: str) -> Any:
    raise InventoryError('INVENTORY_NONFINITE')  # NaN / Infinity


def load_inventory(raw: bytes) -> list[dict[str, Any]]:
    """Strict: exact format, exact fields, typed values, unique batches, at least one batch."""
    try:
        document = json.loads(raw, object_pairs_hook=_unique, parse_constant=_no_constants)
    except InventoryError:
        raise
    except ValueError:
        raise InventoryError('INVENTORY_NOT_JSON') from None
    if not isinstance(document, dict) or set(document) != {'format', 'batches'}:
        raise InventoryError('INVENTORY_SHAPE')
    if document['format'] != INVENTORY_FORMAT:
        raise InventoryError('INVENTORY_FORMAT')
    batches = document['batches']
    if not isinstance(batches, list) or not batches:
        raise InventoryError('INVENTORY_EMPTY')
    seen = set()
    for entry in batches:
        if not isinstance(entry, dict) or set(entry) != ENTRY_FIELDS:
            raise InventoryError('INVENTORY_ENTRY_FIELDS')
        rows = entry['row_count']
        if (not isinstance(entry['batch_id'], str) or not HEX64.fullmatch(entry['batch_id'])
                or not isinstance(entry['file_sha256'], str) or not HEX64.fullmatch(entry['file_sha256'])
                or entry['source_table'] not in SPECS
                or type(rows) is not int or rows < 1
                or not all(isinstance(entry[k], str) and DRIVE_ID.fullmatch(entry[k])
                           for k in ('drive_file_id', 'drive_manifest_id'))):
            raise InventoryError('INVENTORY_ENTRY_VALUE')
        if entry['batch_id'] in seen:
            raise InventoryError('INVENTORY_DUPLICATE_BATCH')
        seen.add(entry['batch_id'])
    return batches


MAX_MANIFEST_BYTES = 1024 * 1024


def _inside(path: Path, root: Path) -> bool:
    try:
        return path.resolve(strict=True).is_relative_to(root)
    except (OSError, RuntimeError):
        return False


def _index(folder: Path) -> tuple[dict[str, list[Path]], dict[str, list[Path]], list[str]]:
    """Archive files physically under FOLDER. Links (symlinks, junctions, or anything resolving
    outside FOLDER) are never counted as part of the copy; they are recorded as failures."""
    root = folder.resolve()
    manifests: dict[str, list[Path]] = {}
    data: dict[str, list[Path]] = {}
    links: list[str] = []
    for path in sorted(folder.rglob('*')):
        if not path.name.endswith(('.manifest.json', '.parquet')):
            if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
                links.append(path.name)
            continue
        if path.is_symlink() or not _inside(path, root) or not path.is_file():
            links.append(path.name)
            continue
        target = manifests if path.name.endswith('.manifest.json') else data
        target.setdefault(path.name, []).append(path)
    return manifests, data, links


def _link_failures(links: list[str]) -> list[str]:
    return [f'{name[:40]}:LINK_NOT_ALLOWED' for name in links]


def _check_batch(entry: dict[str, Any], manifests, data) -> str | None:
    stem = f"{entry['source_table']}-{entry['batch_id']}"
    manifest_files = manifests.get(stem + '.manifest.json', [])
    data_files = data.get(stem + '.parquet', [])
    if not manifest_files or not data_files:
        return 'MISSING'
    if len(manifest_files) > 1 or len(data_files) > 1:
        return 'DUPLICATE_FILE'
    if (manifest_files[0].stat().st_size > MAX_MANIFEST_BYTES
            or data_files[0].stat().st_size > MAX_BYTES):
        return 'FILE_TOO_LARGE'  # checked before reading anything into memory
    expected = expected_manifest_bytes(entry['batch_id'], entry['source_table'], entry['row_count'],
                                       entry['file_sha256'], entry['drive_file_id'])
    if manifest_files[0].read_bytes() != expected:
        return 'MANIFEST_NOT_EXPECTED_BYTES'
    try:
        archived_rows(data_files[0].read_bytes(), {
            'batch_id': entry['batch_id'], 'source_table': entry['source_table'],
            'row_count': entry['row_count'], 'file_sha256': entry['file_sha256']})
    except ArchiveError as error:
        return str(error)
    except Exception as error:  # noqa: BLE001 - never print file contents
        return type(error).__name__
    return None


def verify_against_inventory(folder: Path, batches: list[dict[str, Any]]) -> dict[str, Any]:
    manifests, data, links = _index(folder)
    failures, matched, missing = [], 0, 0
    expected_names = set()
    for entry in batches:
        stem = f"{entry['source_table']}-{entry['batch_id']}"
        expected_names.update({stem + '.manifest.json', stem + '.parquet'})
        problem = _check_batch(entry, manifests, data)
        if problem is None:
            matched += 1
        else:
            missing += problem == 'MISSING'
            failures.append(f"{stem[:40]}:{problem}")
    extra_files = (set(manifests) | set(data)) - expected_names
    extras = sorted({name.removesuffix('.manifest.json').removesuffix('.parquet') for name in extra_files})
    failures.extend(f'{stem[:40]}:NOT_IN_INVENTORY' for stem in extras)
    failures.extend(_link_failures(links))
    return {'inventory_batches': len(batches), 'matched': matched, 'missing': missing,
            'not_in_inventory': len(extras), 'failures': failures}


def self_check(folder: Path) -> dict[str, Any]:
    """Each manifest is the exact bytes its own fields imply and its data file matches it."""
    manifests, data, links = _index(folder)
    failures, consistent, entries = [], 0, []
    for name, paths in manifests.items():
        label = name[:40]
        try:
            if len(paths) > 1:
                raise ArchiveError('DUPLICATE_FILE')
            if paths[0].stat().st_size > MAX_MANIFEST_BYTES:
                raise ArchiveError('FILE_TOO_LARGE')
            record = json.loads(paths[0].read_bytes(), object_pairs_hook=_unique)
            entry = {'batch_id': record['batch_id'], 'source_table': record['source_table'],
                     'row_count': record['rows'], 'file_sha256': record['sha256'],
                     'drive_file_id': record['drive_file_id'], 'drive_manifest_id': 'self-check'}
            problem = _check_batch(entry, manifests, data)
            if problem:
                raise ArchiveError(problem)
            if type(entry['row_count']) is not int or entry['row_count'] < 1:
                raise ArchiveError('MANIFEST_ROW_COUNT')
            consistent += 1
            entries.append(entry)
        except ArchiveError as error:
            failures.append(f'{label}:{error}')
        except Exception as error:  # noqa: BLE001 - never print file contents
            failures.append(f'{label}:{type(error).__name__}')
    used = {name.removesuffix('.manifest.json') + '.parquet' for name in manifests}
    orphans = sorted(set(data) - used)
    failures.extend(f'{name[:40]}:DATA_WITHOUT_MANIFEST' for name in orphans)
    failures.extend(_link_failures(links))
    if not manifests:
        failures.append('EMPTY_FOLDER')
    return {'manifests': len(manifests), 'consistent': consistent, 'failures': failures,
            'entries': entries}


def _per_table(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry['source_table']] = counts.get(entry['source_table'], 0) + 1
    return dict(sorted(counts.items()))


def _report(status: str, result: dict[str, Any], **extra: Any) -> None:
    print(json.dumps({'status': status, **extra,
                      **{k: v for k, v in result.items() if k not in ('failures', 'entries')},
                      'failure_count': len(result['failures']),
                      'first_failures': result['failures'][:10]}))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('folder', type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--inventory', type=Path, help='frozen inventory exported from the database')
    mode.add_argument('--expect-set-sha256', help='database fingerprint from INVENTORY_SET_SQL')
    mode.add_argument('--self-check-only', action='store_true',
                      help='self-consistency only; never qualifies a copy for deletion')
    parser.add_argument('--inventory-sha256', help='sha256 of the inventory file, recorded independently')
    parser.add_argument('--expect-batches', type=int, help='batch count from INVENTORY_SET_SQL')
    args = parser.parse_args(argv)
    folder = args.folder
    if not folder.is_dir():
        print(json.dumps({'status': 'FAILED', 'error': 'FOLDER_NOT_FOUND'}))
        return 1
    if args.self_check_only:
        result = self_check(folder)
        ok = not result['failures']
        _report('SELF_CONSISTENT_ONLY' if ok else 'NOT_SELF_CONSISTENT', result, deletion_authority=False)
        return 0 if ok else 1
    parts = {part.lower() for part in folder.resolve().parts}
    if parts & set(SYNC_FOLDERS):
        print(json.dumps({'status': 'FAILED', 'error': 'DESTINATION_LOOKS_LIKE_A_SYNC_FOLDER'}))
        return 1
    destination = folder.resolve().anchor or str(folder.resolve().parts[0])
    if args.expect_set_sha256:
        wanted = args.expect_set_sha256.lower()
        if not HEX64.fullmatch(wanted) or args.expect_batches is None or args.expect_batches < 1:
            print(json.dumps({'status': 'FAILED', 'error': 'FINGERPRINT_AND_POSITIVE_COUNT_REQUIRED'}))
            return 1
        result = self_check(folder)
        seen = inventory_set_sha256(result['entries'])
        ok = (not result['failures'] and len(result['entries']) == args.expect_batches
              and seen == wanted)
        _report('COPY_MATCHES_INVENTORY' if ok else 'COPY_DOES_NOT_MATCH_INVENTORY', result,
                destination=destination, expected_batches=args.expect_batches,
                fingerprint_matches=seen == wanted, per_table=_per_table(result['entries']))
        return 0 if ok else 1
    raw = args.inventory.read_bytes()
    if not args.inventory_sha256 or hashlib.sha256(raw).hexdigest() != args.inventory_sha256.lower():
        print(json.dumps({'status': 'FAILED', 'error': 'INVENTORY_NOT_ANCHORED'}))
        return 1
    try:
        batches = load_inventory(raw)
    except InventoryError as error:
        print(json.dumps({'status': 'FAILED', 'error': str(error)}))
        return 1
    result = verify_against_inventory(folder, batches)
    ok = not result['failures'] and result['matched'] == len(batches)
    _report('COPY_MATCHES_INVENTORY' if ok else 'COPY_DOES_NOT_MATCH_INVENTORY', result,
            destination=destination)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
