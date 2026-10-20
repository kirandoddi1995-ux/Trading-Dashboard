"""Inactive owner-run opaque native PostgreSQL export; never a restore command.

Preview is zero IO. Confirmed Windows execution uses native console prompting:
this wrapper never accepts a password, reads a credential store or discovers a
database URL. Native stderr is bounded/classified, never echoed. Rows are copied
as opaque bytes, not decoded. No transport, encryption, deletion or scheduling.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import ctypes
from datetime import datetime, timezone
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
from contextlib import AbstractContextManager
from typing import BinaryIO, Any, NoReturn

from archive_preservation_inventory import measure
from archive_preservation_witness import _private_path

VERSION = 'live-logical-backup-v1'
TOOLS = ('pg_dump', 'pg_dumpall', 'pg_restore')
PG_BIN = Path(r'C:\Program Files\PostgreSQL\17\bin')
SOURCE_HOST = 'aws-0-ap-northeast-1.pooler.supabase.com'
SOURCE_USER = 'postgres.jocpxonpjegfvaseshgd'
MAX_DUMP = 4 * 1024**3
MAX_ROLES = 16 * 1024**2
MAX_TOC = 16 * 1024**2
MIN_FREE = 12 * 1024**3
SAFE_CODES = ('NATIVE_TIMEOUT', 'NATIVE_OUTPUT_BOUND', 'NATIVE_DIAGNOSTIC_BOUND',
    'NATIVE_PERMISSION_REVIEW', 'NATIVE_AUTH_REVIEW', 'NATIVE_TLS_REVIEW',
    'NATIVE_VERSION_REVIEW', 'NATIVE_EXIT_REVIEW', 'NATIVE_WARNING_REVIEW',
    'NATIVE_STREAM_REVIEW', 'NATIVE_EXIT_UNKNOWN', 'NATIVE_EMPTY_OUTPUT',
    'NATIVE_EOF_UNVERIFIED', 'SOURCE_PROFILE_REQUIRED', 'INVALID_ARGUMENTS',
    'REVIEWED_NORMAL_WINDOWS_CONSOLE_REQUIRED', 'REVIEWED_PYTHON_REQUIRED',
    'PINNED_NATIVE_TOOLS_REQUIRED', 'TOOL_VERSION_REVIEW', 'NATIVE_FILE_CHANGED',
    'OWNER_CONFIRMATIONS_REQUIRED', 'NATIVE_CA_REQUIRED', 'PRIVATE_OUTPUT_REQUIRED',
    'NEW_ATTEMPT_DIRECTORY_REQUIRED', 'LOCAL_SPACE_FLOOR_NOT_MET', 'REVIEWED_SOURCE_REQUIRED',
    'LOCAL_STORAGE_FULL_REVIEW', 'LOCAL_OUTPUT_PERMISSION_REVIEW')


def blocked(code: str) -> NoReturn:
    raise ValueError(code)


def windows_library(name: str) -> Any:
    """Explicit Windows-only FFI boundary; no absent Linux-stub API references."""
    if os.name != 'nt' or name not in ('kernel32', 'shell32'):
        blocked('REVIEWED_NORMAL_WINDOWS_CONSOLE_REQUIRED')
    return getattr(ctypes, 'WinDLL')(name, use_last_error=True)


def public_code(error: BaseException) -> str:
    if isinstance(error, OSError):
        if error.errno in (errno.ENOSPC, getattr(errno, 'EDQUOT', -1)) or getattr(error, 'winerror', None) in (39, 112):
            return 'LOCAL_STORAGE_FULL_REVIEW'
        if error.errno in (errno.EPERM, errno.EACCES):
            return 'LOCAL_OUTPUT_PERMISSION_REVIEW'
    return next((item for item in SAFE_CODES if type(error) is ValueError and error.args == (item,)),
                'BACKUP_STOP_REVIEW_PRESERVE_PARTIALS')


class JobBlocked(ValueError):
    def __init__(self, phase: str, code: str) -> None:
        self.phase = phase
        self.code = code
        super().__init__('OPAQUE_JOB_BLOCKED')


def command(tool: str) -> tuple[str, ...]:
    """Fixed project/session-pooler; no URI, filter, role switch or arbitrary SQL."""
    common = ('--host=' + SOURCE_HOST, '--port=5432', '--username=' + SOURCE_USER, '--password')
    if tool == 'pg_dump':
        return (*common, '--dbname=postgres', '--format=custom', '--lock-wait-timeout=5s')
    if tool == 'pg_dumpall':
        return (*common, '--database=postgres', '--roles-only', '--no-role-passwords')
    blocked('SOURCE_PROFILE_REQUIRED')


def child_environment(inherited: Mapping[str, str], tools: Path, ca: Path | None) -> dict[str, str]:
    """No inherited PG*, service settings, passfile, proxy or Python injection."""
    result = {name: inherited[name] for name in ('SystemRoot', 'WINDIR', 'TEMP', 'TMP')
              if name in inherited}
    system_root = inherited.get('SystemRoot', r'C:\Windows')
    result.update(PATH=str(tools) + os.pathsep + str(Path(system_root) / 'System32'),
        PGPASSFILE=os.devnull, PGSERVICEFILE=os.devnull, PGCONNECT_TIMEOUT='10',
        PGGSSENCMODE='disable', PGSSLMODE='verify-full', PGSSLMINPROTOCOLVERSION='TLSv1.2',
        PGSSLCERTMODE='disable', PGSSLCERT=os.devnull, PGSSLKEY=os.devnull,
        PGOPTIONS='-c default_transaction_read_only=on -c lock_timeout=5s',
        PGAPPNAME='reviewed-owner-logical-backup', PG_COLOR='never')
    if ca is not None:
        result['PGSSLROOTCERT'] = str(ca)
    return result


def _diagnostic(prefix: bytes, *, returncode: int, count: int) -> str | None:
    text = prefix.lower()
    for pattern, code in ((b'password authentication failed', 'NATIVE_AUTH_REVIEW'),
            (b'permission denied', 'NATIVE_PERMISSION_REVIEW'),
            (b'certificate', 'NATIVE_TLS_REVIEW'), (b'server version', 'NATIVE_VERSION_REVIEW')):
        if pattern in text:
            return code
    if returncode != 0:
        return 'NATIVE_EXIT_REVIEW'
    return 'NATIVE_WARNING_REVIEW' if count else None


def stream_process(argv: Sequence[str], *, env: Mapping[str, str], sink: BinaryIO,
                   maximum: int, seconds: float) -> dict[str, Any]:
    """Bound pipes/time, require both EOFs and native success; never echo stderr.

    The cooperative watchdog cannot interrupt a hung OS disk write. This is not
    an autonomous resource sandbox. Only the newly launched child is terminated.
    Synthetic conformance may inject argv; the live CLI always uses fixed argv.
    """
    if type(maximum) is not int or maximum < 1 or not 0 < seconds <= 1800:
        blocked('NATIVE_OUTPUT_BOUND')
    events: queue.Queue[tuple[int, bytes | None]] = queue.Queue(maxsize=8)
    stop = threading.Event()
    def pump(number: int, pipe: BinaryIO) -> None:
        try:
            while not stop.is_set():
                data = os.read(pipe.fileno(), 65536)
                event = (number, data if data else None)
                while not stop.is_set():
                    try:
                        events.put(event, timeout=0.1)
                        break
                    except queue.Full:
                        continue
                if not data:
                    return
        except (OSError, ValueError):
            while not stop.is_set():
                try:
                    events.put((2, None), timeout=0.1)
                    return
                except queue.Full:
                    continue
    readers: list[threading.Thread] = []
    end = time.monotonic() + seconds
    done: set[int] = set()
    count, diagnostics = 0, 0
    prefix = bytearray()
    digest = hashlib.sha256()
    process = subprocess.Popen(list(argv), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(env),
        bufsize=0, close_fds=True)
    try:
        assert process.stdout is not None and process.stderr is not None
        for number, pipe in enumerate((process.stdout, process.stderr)):
            reader = threading.Thread(target=pump, args=(number, pipe), daemon=True)
            readers.append(reader)
            reader.start()
        while len(done) < 2 or process.poll() is None:
            if time.monotonic() >= end:
                blocked('NATIVE_TIMEOUT')
            try:
                number, data = events.get(timeout=min(0.1, max(0.001, end - time.monotonic())))
            except queue.Empty:
                continue
            if number == 2:
                blocked('NATIVE_STREAM_REVIEW')
            if data is None:
                done.add(number)
            elif number == 0:
                count += len(data)
                if count > maximum:
                    blocked('NATIVE_OUTPUT_BOUND')
                if sink.write(data) != len(data):
                    blocked('NATIVE_STREAM_REVIEW')
                digest.update(data)
            else:
                diagnostics += len(data)
                if diagnostics > 65536:
                    blocked('NATIVE_DIAGNOSTIC_BOUND')
                prefix.extend(data[:max(0, 4096 - len(prefix))])
        code = _diagnostic(bytes(prefix), returncode=process.returncode, count=diagnostics)
        if code is not None:
            blocked(code)
        if count == 0:
            blocked('NATIVE_EMPTY_OUTPUT')
        return dict(bytes=count, sha256=digest.hexdigest(), stderr_bytes=0,
                    native_exit=0, both_pipe_eof=True)
    finally:
        stop.set()
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            blocked('NATIVE_EXIT_UNKNOWN')
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        for reader in readers:
            if reader.ident is not None:
                reader.join(timeout=1)
        if any(reader.is_alive() for reader in readers):
            blocked('NATIVE_EOF_UNVERIFIED')


def _console() -> tuple[Any, int, int]:
    if os.name != 'nt' or not sys.stdin.isatty() or not sys.stdout.isatty() or os.environ.get('OSTYPE') == 'msys':
        blocked('REVIEWED_NORMAL_WINDOWS_CONSOLE_REQUIRED')
    kernel = windows_library('kernel32')
    kernel.GetStdHandle.argtypes = [ctypes.c_uint32]
    kernel.GetStdHandle.restype = ctypes.c_void_p
    kernel.GetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    kernel.GetConsoleMode.restype = ctypes.c_int
    kernel.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.SetConsoleMode.restype = ctypes.c_int
    handle = kernel.GetStdHandle(0xfffffff6)
    mode = ctypes.c_uint32()
    if not handle or not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
        blocked('REVIEWED_NORMAL_WINDOWS_CONSOLE_REQUIRED')
    output_mode = ctypes.c_uint32()
    output_handle = kernel.GetStdHandle(0xfffffff5)
    if not output_handle or not kernel.GetConsoleMode(output_handle, ctypes.byref(output_mode)):
        blocked('REVIEWED_NORMAL_WINDOWS_CONSOLE_REQUIRED')
    shell = windows_library('shell32')
    shell.IsUserAnAdmin.restype = ctypes.c_int
    if shell.IsUserAnAdmin():
        blocked('REVIEWED_NORMAL_WINDOWS_CONSOLE_REQUIRED')
    return kernel, handle, mode.value


def restore_console(console: tuple[Any, int, int]) -> bool:
    kernel, handle, mode = console
    try:
        observed = ctypes.c_uint32()
        return bool(kernel.SetConsoleMode(handle, mode)
            and kernel.GetConsoleMode(handle, ctypes.byref(observed)) and observed.value == mode)
    except Exception:
        return False


def _hash(value: object) -> str:
    if type(value) is not str or re.fullmatch('[a-f0-9]{64}', value) is None:
        blocked('PINNED_NATIVE_TOOLS_REQUIRED')
    return value


def reviewed_source(expected_sha: str | None) -> None:
    """Require an externally approved exact clean commit AND package closure.

    Not the pre-commit upload check: this runs only from the owner's merged clean
    tools checkout. Never derive the approved SHA from the tree being checked.
    """
    from live_backup_upload_check import BASE, FILES, MANIFEST, PREREQUISITES, VERSION
    from programme_next_upload_check import git, safe_read, sha, unique
    if type(expected_sha) is not str or re.fullmatch('[a-f0-9]{40}', expected_sha) is None:
        blocked('REVIEWED_SOURCE_REQUIRED')
    root = Path(__file__).resolve().parent
    if (git(root, 'rev-parse', 'HEAD').decode().strip() != expected_sha
            or Path(git(root, 'rev-parse', '--show-toplevel').decode().strip()).resolve() != root
            or git(root, 'status', '--porcelain').strip()):
        blocked('REVIEWED_SOURCE_REQUIRED')
    raw = safe_read(root / MANIFEST)
    value = json.loads(raw, object_pairs_hook=unique)
    if (type(value) is not dict or set(value) != {'version', 'base', 'files', 'prerequisites'}
            or value['version'] != VERSION or value['base'] != BASE
            or value['prerequisites'] != PREREQUISITES or set(value['files']) != set(FILES)
            or value['files'][MANIFEST] is not None or git(root, 'show', expected_sha + ':' + MANIFEST) != raw):
        blocked('REVIEWED_SOURCE_REQUIRED')
    for name, digest in {**value['files'], **PREREQUISITES}.items():
        if name != MANIFEST and (sha(safe_read(root / name)) != digest
                or sha(git(root, 'show', expected_sha + ':' + name)) != digest):
            blocked('REVIEWED_SOURCE_REQUIRED')


def check_tools(expected: Mapping[str, str], env: Mapping[str, str]) -> dict[str, Any]:
    if set(expected) != set(TOOLS):
        blocked('PINNED_NATIVE_TOOLS_REQUIRED')
    observed: dict[str, Any] = {}
    for name in TOOLS:
        tool = PG_BIN / (name + '.exe')
        record = measure(tool, 128 * 1024**2)
        if record['sha256'] != _hash(expected[name]):
            blocked('PINNED_NATIVE_TOOLS_REQUIRED')
        version = io.BytesIO()
        stream_process((str(tool), '--version'), env=env, sink=version, maximum=256, seconds=5)
        if version.getvalue().strip() != (name + ' (PostgreSQL) 17.11').encode('ascii'):
            blocked('TOOL_VERSION_REVIEW')
        if measure(tool, 128 * 1024**2) != record:
            blocked('NATIVE_FILE_CHANGED')
        observed[name] = record
    return observed


def _new_root(root: Path) -> tuple[int, int]:
    _private_path(root, output=True)
    # A clean clone is not the only sensitive source location: refuse source
    # ancestors even when a working source folder itself has no .git directory.
    if any((part / 'archive_preservation_witness.py').exists() or (part / '.git').exists()
           for part in root.parents):
        blocked('PRIVATE_OUTPUT_REQUIRED')
    import shutil
    if shutil.disk_usage(root.parent).free < MIN_FREE:
        blocked('LOCAL_SPACE_FLOOR_NOT_MET')
    root.mkdir(exist_ok=False)
    created = root.stat()
    return created.st_dev, created.st_ino


class OutputDirectory(AbstractContextManager['OutputDirectory']):
    """Windows stable directory chain; CREATE_NEW uses the native volume path.

    Holding EVERY ancestor without delete sharing prevents namespace replacement.
    No ACL mutation, permission change or persistent drive mapping is performed.
    Non-Windows use is rejected; tests inject a disposable synthetic adapter.
    """
    def __init__(self, root: Path, expected_identity: tuple[int, int]) -> None:
        if os.name != 'nt':
            blocked('REVIEWED_NORMAL_WINDOWS_CONSOLE_REQUIRED')
        self.root = root
        self.handles: list[int] = []
        self.kernel = windows_library('kernel32')
        self.kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        self.kernel.CreateFileW.restype = ctypes.c_void_p
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self.kernel.CloseHandle.restype = ctypes.c_int
        self.kernel.GetFinalPathNameByHandleW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
            ctypes.c_uint32, ctypes.c_uint32]
        self.kernel.GetFinalPathNameByHandleW.restype = ctypes.c_uint32
        self.kernel.GetFileInformationByHandleEx.argtypes = [ctypes.c_void_p, ctypes.c_int,
            ctypes.c_void_p, ctypes.c_uint32]
        self.kernel.GetFileInformationByHandleEx.restype = ctypes.c_int
        try:
            _private_path(root / 'unused-output-name', output=True)
            for part in reversed((root, *root.parents)):
                handle = self.kernel.CreateFileW(str(part), 0x80, 3, None, 3, 0x02200000, None)
                if not handle or handle == ctypes.c_void_p(-1).value:
                    blocked('NATIVE_FILE_CHANGED')
                self.handles.append(handle)
                # FILE_ATTRIBUTE_TAG_INFO: directory, never a junction/reparse.
                tag = (ctypes.c_uint32 * 2)()
                if (not self.kernel.GetFileInformationByHandleEx(handle, 9, ctypes.byref(tag), ctypes.sizeof(tag))
                        or not tag[0] & 0x10 or tag[0] & 0x400):
                    blocked('NATIVE_FILE_CHANGED')
            buffer = ctypes.create_unicode_buffer(32768)
            length = self.kernel.GetFinalPathNameByHandleW(self.handles[-1], buffer, len(buffer), 1)
            if not 0 < length < len(buffer) or re.match(r'^\\\\\?\\Volume\{[0-9a-fA-F-]{36}\}\\', buffer.value) is None:
                blocked('NATIVE_FILE_CHANGED')
            self.native_root = buffer.value.rstrip('\\')
            self.root_id = expected_identity
            self.validate()
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def validate(self) -> None:
        _private_path(self.root / 'unused-output-name', output=True)
        if (self.root.stat().st_dev, self.root.stat().st_ino) != self.root_id:
            blocked('NATIVE_FILE_CHANGED')

    def open_new(self, name: str) -> BinaryIO:
        if name not in ('attempt.json', 'database.dump', 'roles.sql', 'toc.list', 'manifest.json'):
            blocked('PRIVATE_OUTPUT_REQUIRED')
        self.validate()
        handle = self.kernel.CreateFileW(self.native_root + '\\' + name,
            0xc0000000, 1, None, 1, 0x00200000, None)  # CREATE_NEW, share-read only.
        if not handle or handle == ctypes.c_void_p(-1).value:
            blocked('NEW_ATTEMPT_DIRECTORY_REQUIRED')
        import msvcrt
        try:
            descriptor = getattr(msvcrt, 'open_osfhandle')(handle, os.O_RDWR | getattr(os, 'O_BINARY'))
            if type(descriptor) is not int:
                blocked('NATIVE_FILE_CHANGED')
        except BaseException:
            self.kernel.CloseHandle(handle)
            raise
        return os.fdopen(descriptor, 'wb')

    def publish(self, name: str, raw: bytes) -> None:
        with self.open_new(name) as output:
            if output.write(raw) != len(raw):
                blocked('NATIVE_STREAM_REVIEW')
            output.flush()
            os.fsync(output.fileno())

    def __exit__(self, *args: object) -> None:
        for handle in reversed(self.handles):
            self.kernel.CloseHandle(handle)
        self.handles.clear()


def export(root: Path, *, env: Mapping[str, str], tool_records: Mapping[str, Any],
           ca_record: Mapping[str, Any]) -> dict[str, Any]:
    """Caller already admitted console, tools, CA and owner confirmations."""
    identity = _new_root(root)
    with OutputDirectory(root, identity) as guard:
        return _export_locked(root, env=env, tool_records=tool_records,
                              ca_record=ca_record, guard=guard)


def _export_locked(root: Path, *, env: Mapping[str, str], tool_records: Mapping[str, Any],
                   ca_record: Mapping[str, Any], guard: OutputDirectory) -> dict[str, Any]:
    root_id = (root.stat().st_dev, root.stat().st_ino)
    guard.publish('attempt.json', b'{"attempt_consumed":true,"retry_authorised":false}')
    artifacts: dict[str, Any] = {}
    jobs = (('database.dump', 'pg_dump', command('pg_dump'), MAX_DUMP, 900),
            ('roles.sql', 'pg_dumpall', command('pg_dumpall'), MAX_ROLES, 120),
            ('toc.list', 'pg_restore', ('--list', str(root / 'database.dump')), MAX_TOC, 60))
    for name, tool_name, arguments, maximum, seconds in jobs:
        if measure(Path(env['PGSSLROOTCERT']), 65536) != ca_record:
            blocked('NATIVE_FILE_CHANGED')
        tool = PG_BIN / (tool_name + '.exe')
        if measure(tool, 128 * 1024**2) != tool_records[tool_name]:
            blocked('NATIVE_FILE_CHANGED')
        path = root / name
        _private_path(path, output=True)
        started = datetime.now(timezone.utc).isoformat()
        with guard.open_new(name) as output:
            created = os.fstat(output.fileno())
            try:
                result = stream_process((str(tool), *arguments), env=env, sink=output,
                                        maximum=maximum, seconds=seconds)
            except BaseException as error:
                phase = {'pg_dump': 'DATABASE_DUMP', 'pg_dumpall': 'ROLES_EXPORT',
                         'pg_restore': 'ARCHIVE_LIST'}[tool_name]
                raise JobBlocked(phase, public_code(error)) from None
            output.flush()
            os.fsync(output.fileno())
            after = os.fstat(output.fileno())
        reopened = measure(path, maximum)
        if (reopened['sha256'] != result['sha256'] or reopened['bytes'] != result['bytes']
                or (created.st_dev, created.st_ino) != (after.st_dev, after.st_ino)
                or (after.st_dev, after.st_ino) != (reopened['binding']['device'], reopened['binding']['file_id'])
                or (root.stat().st_dev, root.stat().st_ino) != root_id):
            blocked('NATIVE_FILE_CHANGED')
        if measure(Path(env['PGSSLROOTCERT']), 65536) != ca_record:
            blocked('NATIVE_FILE_CHANGED')
        artifacts[name] = dict(measured=reopened, started_at=started,
            finished_at=datetime.now(timezone.utc).isoformat(), native=result)
    receipt = dict(version=VERSION, status='OPAQUE_LOGICAL_EXPORT_NOT_RESTORE',
        artifacts=artifacts, tools=tool_records, ca=ca_record, roles_same_snapshot=False,
        local_clock_verified=False, native_acceptance_is_owner_attestation=True,
        platform_complete=False, independent_custody_verified=False,
        restore_verified=False, deletion_authorised=False, training_eligible=False)
    guard.validate()
    guard.publish('manifest.json', json.dumps(receipt, sort_keys=True).encode('utf-8'))
    return dict(status=receipt['status'], files=3, manifest_written=True,
        wrapper_credential_reads=0, native_password_prompt=True, source_write_commands_requested=0,
        restore_verified=False, custody_verified=False, deletion_authorised=False)


def directory_drill(root: Path) -> dict[str, Any]:
    """Only a NEW synthetic directory/file; never an existing backup or capture.

    A sharing violation is required, not a generic access/ACL denial. Successful
    unexpected moves are preserved; no rename-back, cleanup or retry is attempted.
    """
    _new_root(root)
    child = root / 'guarded'
    child.mkdir(exist_ok=False)
    identity = (child.stat().st_dev, child.stat().st_ino)
    def require_sharing_denial(source: Path, destination: Path) -> None:
        _private_path(destination, output=True)
        try:
            source.rename(destination)
        except OSError as error:
            if getattr(error, 'winerror', None) != 32:
                blocked('NATIVE_FILE_CHANGED')
        else:
            blocked('NATIVE_FILE_CHANGED')
    with OutputDirectory(child, identity) as guard:
        with guard.open_new('attempt.json') as output:
            output.write(b'{"synthetic_only":true}')
            output.flush()
            require_sharing_denial(child / 'attempt.json', child / 'synthetic-moved.json')
        # Child file is CLOSED: these must prove the directory guards themselves.
        require_sharing_denial(child, root / 'guarded-moved')
        require_sharing_denial(root, root.parent / (root.name + '-synthetic-moved'))
        guard.validate()
    return dict(status='SYNTHETIC_WINDOWS_DIRECTORY_LOCK_PASSED', source_connections=0,
        credential_reads=0, native_pg_invocations=0, synthetic_files_written=1,
        file_lock_verified=True, root_lock_verified=True, drill_owned_ancestor_lock_verified=True,
        archive_custody_verified=False, restore_verified=False)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        blocked('INVALID_ARGUMENTS')


def main(argv: Sequence[str] | None = None) -> int:
    stage = 'PREVIEW'
    console: tuple[Any, int, int] | None = None
    result: dict[str, Any]
    exit_code = 0
    try:
        parser = _Parser(description=__doc__)
        parser.add_argument('--mode', choices=('preview', 'directory-drill', 'check-local', 'export'), default='preview')
        parser.add_argument('--confirm-run', action='store_true')
        parser.add_argument('--confirm-no-capture-running', action='store_true')
        parser.add_argument('--confirm-opaque-holdout-backup', action='store_true')
        parser.add_argument('--confirm-native-acceptance', action='store_true')
        parser.add_argument('--run-root')
        parser.add_argument('--reviewed-source')
        parser.add_argument('--ca-file')
        for name in TOOLS:
            parser.add_argument('--pin-' + name.replace('_', '-'), dest='pin_' + name)
        args = parser.parse_args(argv)
        if args.mode == 'preview' or not args.confirm_run:
            print(json.dumps(dict(status='PREVIEW', input_reads=0, native_invocations=0,
                credential_reads=0, writes=0, network_requests=0, run_authorised=False)))
            return 0
        stage = 'LOCAL_ADMISSION'
        if sys.version_info[:3] != (3, 13, 9):
            blocked('REVIEWED_PYTHON_REQUIRED')
        stage = 'REVIEWED_SOURCE'
        reviewed_source(args.reviewed_source)
        stage = 'LOCAL_ADMISSION'
        console = _console()
        if args.mode == 'directory-drill':
            if not args.confirm_no_capture_running or not args.run_root:
                blocked('OWNER_CONFIRMATIONS_REQUIRED')
            result = directory_drill(Path(args.run_root))
            result.update(approval_authority=False, retry_authorised=False)
            # Report only after console restoration below.
            if not restore_console(console):
                blocked('REVIEWED_NORMAL_WINDOWS_CONSOLE_REQUIRED')
            console = None
            print(json.dumps(result, sort_keys=True))
            return 0
        pins = {name: _hash(getattr(args, 'pin_' + name.replace('-', '_'))) for name in TOOLS}
        if not args.ca_file:
            blocked('NATIVE_CA_REQUIRED')
        ca = Path(args.ca_file)
        _private_path(ca)
        certificate = measure(ca, 65536)
        env = child_environment(os.environ, PG_BIN, ca)
        tools = check_tools(pins, env)
        if args.mode == 'check-local':
            result = dict(status='LOCAL_NATIVE_TOOLS_CHECKED_NOT_SOURCE_OR_RESTORE',
                source_connections=0, credential_reads=0, writes=0)
        else:
            if not (args.confirm_no_capture_running and args.confirm_opaque_holdout_backup
                    and args.confirm_native_acceptance and args.run_root):
                blocked('OWNER_CONFIRMATIONS_REQUIRED')
            if measure(ca, 65536) != certificate:
                blocked('NATIVE_FILE_CHANGED')
            stage = 'OPAQUE_NATIVE_EXPORT'
            result = export(Path(args.run_root), env=env, tool_records=tools, ca_record=certificate)
        result.update(approval_authority=False, training_eligible=False, same_slot_retry_allowed=False)
    except BaseException as error:
        code = public_code(error)
        if type(error) is JobBlocked:
            code, stage = error.code, error.phase
        result = dict(status='BLOCKED', code=code, stage=stage,
            raw_error_printed=False, retry_authorised=False, restore_verified=False,
            deletion_authorised=False, approval_authority=False)
        exit_code = 2
    finally:
        if console is not None and not restore_console(console):
            result = dict(status='BLOCKED', code='CONSOLE_RESTORE_UNVERIFIED',
                stage='CONSOLE_RESTORE', raw_error_printed=False, retry_authorised=False,
                restore_verified=False, deletion_authorised=False, approval_authority=False)
            exit_code = 2
    print(json.dumps(result, sort_keys=True))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
