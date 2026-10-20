"""Inactive opaque preservation inventory. No archive decoding or custody authority."""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, NoReturn, cast

MAX_FILE_BYTES = 1024 * 1024 * 1024
MAX_SELECTION_BYTES = 65536
# Native identifiers are opaque exact integers, never signed generation numbers.
# Python >=3.12 can return a 128-bit Windows st_ino (including ReFS).
MAX_DEVICE_ID = 2**64 - 1
MAX_FILE_ID = 2**128 - 1
HASH = re.compile(r'[0-9a-f]{64}')
ROLES = frozenset({'inventory', 'catalog', 'bundle', 'reconcile', 'verify', 'footer', 'other'})
CIPHER_SHA256 = '9c9b22afbbc0e027e12ad4c5fe81bf184614ca9aea7aa535a525bf5cb115519e'
CIPHER_BYTES = 161194257
SAFE_CODES = frozenset({'DUPLICATE_KEY', 'AWARE_TIMESTAMP_REQUIRED', 'LOCAL_NATIVE_PATH_REQUIRED',
    'ABSOLUTE_NONLINK_PATH_REQUIRED', 'PRIVATE_PATH_OUTSIDE_TOOLS_REQUIRED',
    'SINGLE_LINK_REGULAR_FILE_REQUIRED', 'NATIVE_HANDLE_VOLUME_UNVERIFIED',
    'NATIVE_READ_HANDLE_UNAVAILABLE', 'FILE_SIZE_BOUND', 'FILE_CHANGED', 'CONFIG_SIZE_BOUND',
    'CONFIG_CHANGED', 'NONFINITE_JSON', 'OBJECT_REQUIRED', 'ENTRY_CONTRACT', 'ANCHOR_REQUIRED',
    'COLLECTOR_HASH_REQUIRED', 'SELECTION_CONTRACT', 'EXACT_SEVEN_REQUIRED',
    'ANCHOR_PROVENANCE_REQUIRED', 'EXACT_ROLES_REQUIRED', 'ORIGINAL_ANCHOR_MISMATCH',
    'DUPLICATE_FILE_IDENTITY', 'CIPHER_PATH_REQUIRED', 'CIPHER_ANCHOR_MISMATCH',
    'DESTINATION_VOLUME_MISMATCH', 'DESTINATION_NOT_SEPARATE_VOLUME', 'OWNER_REPORT_CONTRACT',
    'PUBLICATION_INCOMPLETE', 'ONE_EXPLICIT_OPERATION_REQUIRED', 'SELECTION_AND_NEW_OUTPUT_REQUIRED',
    'ORIGINAL_AGGREGATE_BOUND', 'NATIVE_ID_INTEGER_BOUND'})


def reject(code: str) -> NoReturn:
    raise ValueError(code)


def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            reject('DUPLICATE_KEY')
        value[key] = item
    return value


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('ascii')


def timestamp(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 40:
        reject('AWARE_TIMESTAMP_REQUIRED')
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        reject('AWARE_TIMESTAMP_REQUIRED')
    return str(value)


def check_path(path: Path) -> None:
    # Reject UNC/device namespaces before any filesystem query (including is_symlink).
    text = str(path)
    if text.startswith(('\\\\', '//')):
        reject('LOCAL_NATIVE_PATH_REQUIRED')
    if os.name == 'nt':
        if re.match(r'^[A-Za-z]:[\\/]', text) is None:
            reject('LOCAL_NATIVE_PATH_REQUIRED')
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        drive_type = kernel.GetDriveTypeW
        drive_type.argtypes = [ctypes.c_wchar_p]
        drive_type.restype = ctypes.c_uint32
        if drive_type(path.anchor) not in {2, 3}:
            reject('LOCAL_NATIVE_PATH_REQUIRED')
    if not path.is_absolute() or any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        reject('ABSOLUTE_NONLINK_PATH_REQUIRED')


def private_path(path: Path) -> None:
    check_path(path)
    if path.resolve().is_relative_to(Path(__file__).resolve().parent):
        reject('PRIVATE_PATH_OUTSIDE_TOOLS_REQUIRED')


def identity(fd: int) -> dict[str, Any]:
    """Identity of this open descriptor; Windows volume GUID, never cached PSDrive."""
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        reject('SINGLE_LINK_REGULAR_FILE_REQUIRED')
    if (type(info.st_dev) is not int or not 0 <= info.st_dev <= MAX_DEVICE_ID
            or type(info.st_ino) is not int or not 0 <= info.st_ino <= MAX_FILE_ID):
        reject('NATIVE_ID_INTEGER_BOUND')
    result: dict[str, Any] = {'device': info.st_dev, 'file_id': info.st_ino,
                              'volume': 'posix-device:' + str(info.st_dev)}
    if os.name == 'nt':
        import msvcrt
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        final = kernel.GetFinalPathNameByHandleW
        final.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32]
        final.restype = ctypes.c_uint32
        buffer = ctypes.create_unicode_buffer(32768)
        length = final(msvcrt.get_osfhandle(fd), buffer, len(buffer), 1)
        if not 0 < length < len(buffer):
            reject('NATIVE_HANDLE_VOLUME_UNVERIFIED')
        match = re.match(r'^\\\\\?\\Volume\{[0-9a-fA-F-]{36}\}\\', buffer.value)
        if match is None:
            reject('NATIVE_HANDLE_VOLUME_UNVERIFIED')
        result['volume'] = match[0].lower()
        result['final_path'] = buffer.value
    return result


def open_read(path: Path) -> int:
    if os.name != 'nt':
        return os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    import msvcrt
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                       ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    create.restype = ctypes.c_void_p
    # Read sharing only: existing writers/deleters block admission; no new write/delete.
    handle = create(str(path), 0x80000000, 1, None, 3, 0x00200000, None)
    if handle is None or handle == ctypes.c_void_p(-1).value:
        reject('NATIVE_READ_HANDLE_UNAVAILABLE')
    try:
        return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except Exception:
        close = kernel.CloseHandle
        close.argtypes = [ctypes.c_void_p]
        close.restype = ctypes.c_int
        close(handle)
        raise


def measure(path: Path, max_bytes: int = MAX_FILE_BYTES) -> dict[str, Any]:
    """Hash the SAME bounded open file as native identity; reject replacement/mutation."""
    check_path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= max_bytes:
        reject('FILE_SIZE_BOUND')
    fd = open_read(path)
    try:
        opened = os.fstat(fd)
        binding = identity(fd)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns):
            reject('FILE_CHANGED')
        digest = hashlib.sha256()
        count = 0
        while True:
            block = os.read(fd, min(1024 * 1024, max_bytes + 1 - count))
            if not block:
                break
            count += len(block)
            if count > max_bytes:
                reject('FILE_SIZE_BOUND')
            digest.update(block)
        after = os.fstat(fd)
        check_path(path)
        named = path.lstat()
        def fields(s: os.stat_result) -> tuple[int, int, int, int]:
            return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns
        # Windows pathname lstat and CRT fstat can expose different ctime semantics
        # (creation vs change time). Compare ctime WITHIN each API, never between.
        if (count != opened.st_size or fields(opened) != fields(after) or fields(after) != fields(named)
                or opened.st_ctime_ns != after.st_ctime_ns or before.st_ctime_ns != named.st_ctime_ns
                or binding != identity(fd)):
            reject('FILE_CHANGED')
        return {'sha256': digest.hexdigest(), 'bytes': count, 'binding': binding}
    finally:
        os.close(fd)


def read_json(path: Path) -> dict[str, Any]:
    check_path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_SELECTION_BYTES:
        reject('CONFIG_SIZE_BOUND')
    fd = open_read(path)
    try:
        opened = os.fstat(fd)
        binding = identity(fd)
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
            reject('CONFIG_CHANGED')
        raw = bytearray()
        while len(raw) <= MAX_SELECTION_BYTES:
            block = os.read(fd, min(65536, MAX_SELECTION_BYTES + 1 - len(raw)))
            if not block:
                break
            raw.extend(block)
        check_path(path)
        after = os.fstat(fd)
        named = path.lstat()
        if (len(raw) != opened.st_size or len(raw) > MAX_SELECTION_BYTES or
                binding != identity(fd) or (after.st_size, after.st_mtime_ns) != (opened.st_size, opened.st_mtime_ns)
                or opened.st_ctime_ns != after.st_ctime_ns or before.st_ctime_ns != named.st_ctime_ns
                or (named.st_dev, named.st_ino, named.st_size, named.st_mtime_ns) != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)):
            reject('CONFIG_CHANGED')
    finally:
        os.close(fd)
    value = json.loads(raw, object_pairs_hook=unique,
                       parse_constant=lambda _: reject('NONFINITE_JSON'))
    if not isinstance(value, dict):
        reject('OBJECT_REQUIRED')
    return cast(dict[str, Any], value)


def expected(entry: Any) -> None:
    if not isinstance(entry, dict) or set(entry) != {'role', 'path', 'bytes', 'sha256', 'anchor_kind', 'observed_at'}:
        reject('ENTRY_CONTRACT')
    if type(entry['bytes']) is not int or not 0 < entry['bytes'] <= MAX_FILE_BYTES or not isinstance(entry['sha256'], str) or HASH.fullmatch(entry['sha256']) is None:
        reject('ANCHOR_REQUIRED')
    timestamp(entry['observed_at'])
    if not isinstance(entry['path'], str):
        reject('ENTRY_CONTRACT')


def collect(selection: dict[str, Any], collector_sha256: str) -> dict[str, Any]:
    if HASH.fullmatch(collector_sha256) is None:
        reject('COLLECTOR_HASH_REQUIRED')
    if set(selection) != {'version', 'originals', 'source_cipher', 'destination_cipher', 'expected_destination_volume', 'owner_reports'} or selection['version'] != 'preservation-selection-v1':
        reject('SELECTION_CONTRACT')
    entries = selection['originals']
    if not isinstance(entries, list) or len(entries) != 7:
        reject('EXACT_SEVEN_REQUIRED')
    for item in entries:
        expected(item)
        if item['anchor_kind'] != ('ORIGINAL_RETAINED_PIN' if item['role'] in {'catalog', 'bundle'} else 'FIRST_OBSERVED'):
            reject('ANCHOR_PROVENANCE_REQUIRED')
    if {item['role'] for item in entries} != ROLES:
        reject('EXACT_ROLES_REQUIRED')
    if sum(item['bytes'] for item in entries) > MAX_FILE_BYTES:
        reject('ORIGINAL_AGGREGATE_BOUND')
    measured: list[dict[str, Any]] = []
    identities: set[tuple[int, int]] = set()
    for item in entries:
        private_path(Path(item['path']))
        result = measure(Path(item['path']), item['bytes'])
        if (result['bytes'], result['sha256']) != (item['bytes'], item['sha256']):
            reject('ORIGINAL_ANCHOR_MISMATCH')
        binding = result['binding']
        pair = (binding['device'], binding['file_id'])
        if pair in identities:
            reject('DUPLICATE_FILE_IDENTITY')
        identities.add(pair)
        measured.append({**item, 'measured': result})
    copies: list[dict[str, Any]] = []
    for field in ('source_cipher', 'destination_cipher'):
        path = selection[field]
        if not isinstance(path, str):
            reject('CIPHER_PATH_REQUIRED')
        private_path(Path(path))
        result = measure(Path(path), CIPHER_BYTES)
        if (result['bytes'], result['sha256']) != (CIPHER_BYTES, CIPHER_SHA256):
            reject('CIPHER_ANCHOR_MISMATCH')
        copies.append(result)
    source, destination = copies
    volume = selection['expected_destination_volume']
    if not isinstance(volume, str) or not volume or destination['binding']['volume'] != volume:
        reject('DESTINATION_VOLUME_MISMATCH')
    if source['binding']['volume'] == volume or any(item['measured']['binding']['volume'] == volume for item in measured):
        reject('DESTINATION_NOT_SEPARATE_VOLUME')
    reports = selection['owner_reports']
    if not isinstance(reports, dict) or set(reports) != {'external_disk', 'disconnected_storage', 'extraction_rehearsal', 'drive_readback', 'superseded_stale_attempt'} or any(type(v) is not bool for v in reports.values()):
        reject('OWNER_REPORT_CONTRACT')
    return {'version': 'preservation-inventory-v1', 'measured_at': datetime.now(timezone.utc).isoformat(),
            'time_source': 'LOCAL_CLOCK_NOT_INDEPENDENTLY_VERIFIED',
            'collector_sha256': collector_sha256, 'originals': measured,
            'cipher_copies': copies, 'owner_reports': reports,
            'native_fact': 'DESTINATION_VOLUME_AND_BYTES_BOUND_TO_OPEN_HANDLE',
            'physical_disk_independence': 'NOT_VERIFIED', 'remote_provider_identity': 'NOT_VERIFIED',
            'legacy_receipt_authenticity': 'NOT_VERIFIED', 'restore_verified': False,
            'custody_verified': False, 'deletion_authorised': False, 'training_eligible': False}


def publish(path: Path, raw: bytes) -> None:
    """New-file only. A partial/failed write is retained and must not be reset."""
    check_path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                reject('PUBLICATION_INCOMPLETE')
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        reject('INVALID_ARGUMENTS')


def main() -> int:
    parser = _Parser(description=__doc__)
    parser.add_argument('--selection', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--confirm-measure', action='store_true')
    parser.add_argument('--probe-destination', type=Path)
    parser.add_argument('--confirm-probe', action='store_true')
    try:
        args = parser.parse_args()
    except ValueError:
        print(json.dumps({'status': 'BLOCKED', 'reason': 'INVALID_ARGUMENTS',
                          'raw_error_printed': False, 'retry_authorised': False}))
        return 2
    if not args.confirm_measure and not args.confirm_probe:
        print(json.dumps({'status': 'PREVIEW', 'private_reads': 0, 'writes': 0, 'network_calls': 0, 'credential_reads': 0}))
        return 0
    stage = 'PRIVATE_SELECTION'
    try:
        if args.confirm_probe:
            stage = 'DESTINATION_PROBE'
            if args.confirm_measure or args.probe_destination is None or args.output is None:
                reject('ONE_EXPLICIT_OPERATION_REQUIRED')
            private_path(args.probe_destination)
            private_path(args.output)
            fd = open_read(args.probe_destination)
            try:
                binding = identity(fd)
            finally:
                os.close(fd)
            stage = 'NEW_REPORT_PUBLICATION'
            publish(args.output, canonical({'version': 'preservation-volume-probe-v1',
                    'binding': binding, 'identity_enrolled': False, 'custody_verified': False,
                    'physical_disk_independence': 'NOT_VERIFIED'}))
            print(json.dumps({'status': 'DESTINATION_PROBED_NOT_ENROLLED', 'file_content_reads': 0,
                              'custody_verified': False, 'raw_values_printed': False}))
            return 0
        if args.selection is None or args.output is None:
            reject('SELECTION_AND_NEW_OUTPUT_REQUIRED')
        private_path(args.selection)
        private_path(args.output)
        code_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        selection = read_json(args.selection)
        stage = 'OPAQUE_MEASUREMENT'
        report = collect(selection, code_hash)
        stage = 'NEW_REPORT_PUBLICATION'
        publish(args.output, canonical(report))
        print(json.dumps({'status': 'PRESERVATION_MEASURED_NOT_CUSTODY', 'originals': 7,
                          'custody_verified': False, 'deletion_authorised': False, 'network_calls': 0}))
        return 0
    except Exception as error:
        code = str(error) if type(error) is ValueError and str(error) in SAFE_CODES else 'PRESERVATION_IO_OR_FORMAT_REVIEW_REQUIRED'
        print(json.dumps({'status': 'BLOCKED', 'code': 'PRESERVATION_MEASUREMENT_REVIEW_REQUIRED',
                          'stage': stage, 'reason': code,
                          'raw_error_printed': False, 'retry_authorised': False, 'deletion_authorised': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
