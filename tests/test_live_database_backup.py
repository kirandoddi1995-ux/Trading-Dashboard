"""Synthetic pipes/files only; never connect to PostgreSQL or prompt for a secret."""
from __future__ import annotations

import hashlib
import errno
import io
import json
import os
from pathlib import Path
import sys
from typing import Any, NoReturn

import pytest

import live_database_backup as b


class SyntheticDirectory:
    """Disposable POSIX/Windows file fixture, not native-lock acceptance."""
    def __init__(self, root: Path, expected_identity: object = None) -> None:
        self.root = root
    def __enter__(self) -> SyntheticDirectory:
        return self
    def __exit__(self, *args: object) -> None:
        pass
    def validate(self) -> None:
        pass
    def open_new(self, name: str) -> Any:
        return (self.root / name).open('xb')
    def publish(self, name: str, raw: bytes) -> None:
        with self.open_new(name) as output:
            output.write(raw)


def environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items()
            if key.upper() in ('PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP')}


def child(source: str, sink: io.BytesIO | None = None, *, limit: int = 1024,
          seconds: float = 5) -> tuple[dict[str, Any], io.BytesIO]:
    output = sink if sink is not None else io.BytesIO()
    result = b.stream_process((sys.executable, '-I', '-B', '-c', source), env=environment(),
        sink=output, maximum=limit, seconds=seconds)
    return result, output


def test_native_binary_stdout_is_not_a_text_pipeline() -> None:
    result, output = child("import os; os.write(1,bytes(range(256)))")
    assert output.getvalue() == bytes(range(256))
    assert result == dict(bytes=256, sha256=hashlib.sha256(bytes(range(256))).hexdigest(),
                          stderr_bytes=0, native_exit=0, both_pipe_eof=True)


@pytest.mark.parametrize('source,code', [
    ("import os; os.write(2,b'private synthetic sentinel'); print('x')", 'NATIVE_WARNING_REVIEW'),
    ("import os; os.write(2,b'permission denied private sentinel'); print('x')", 'NATIVE_PERMISSION_REVIEW'),
    ("import os; os.write(2,b'password authentication failed private sentinel'); print('x')", 'NATIVE_AUTH_REVIEW'),
    ("import os; os.write(2,b'certificate private sentinel'); print('x')", 'NATIVE_TLS_REVIEW'),
    ("import os; os.write(2,b'server version private sentinel'); print('x')", 'NATIVE_VERSION_REVIEW'),
    ("import sys; print('partial'); sys.exit(3)", 'NATIVE_EXIT_REVIEW'),
    ("pass", 'NATIVE_EMPTY_OUTPUT'),
    ("import os; os.write(1,b'x'*2048)", 'NATIVE_OUTPUT_BOUND'),
    ("import os; os.write(2,b'x'*70000)", 'NATIVE_DIAGNOSTIC_BOUND'),
])
def test_native_failure_warning_or_bounds_do_not_leak(source: str, code: str,
        capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(ValueError, match=code):
        child(source)
    assert 'sentinel' not in str(capsys.readouterr())


def test_timeout_stops_only_new_child_and_preserves_partial_output() -> None:
    output = io.BytesIO()
    with pytest.raises(ValueError, match='NATIVE_TIMEOUT'):
        child("import os,time; os.write(1,b'partial'); time.sleep(5)", output, seconds=0.3)
    assert output.getvalue() == b'partial'


def test_stream_write_failure_is_not_success() -> None:
    class Broken(io.BytesIO):
        def write(self, data: bytes) -> int:  # type: ignore[override]
            raise OSError('synthetic disk-full private sentinel')
    with pytest.raises(OSError):
        child("print('x')", Broken())


def test_short_write_rejected() -> None:
    class Short(io.BytesIO):
        def write(self, data: bytes) -> int:  # type: ignore[override]
            return 0
    with pytest.raises(ValueError, match='NATIVE_STREAM_REVIEW'):
        child("print('x')", Short())


@pytest.mark.parametrize('name', ['pg_dump', 'pg_dumpall'])
def test_live_commands_are_fixed_and_never_partial_or_password_argv(name: str) -> None:
    arguments = b.command(name)
    assert '--password' in arguments
    assert '--port=5432' in arguments
    assert not any(x.startswith(('--exclude', '--schema', '--table', '--role=', '--no-acl', '--no-owner', '--enable-row-security')) for x in arguments)
    assert not any('://' in x or 'password=' in x for x in arguments)
    if name == 'pg_dump':
        assert '--format=custom' in arguments and '--lock-wait-timeout=5s' in arguments
    else:
        assert '--roles-only' in arguments and '--no-role-passwords' in arguments


def test_environment_has_no_secret_discovery_or_injection() -> None:
    inherited = {'PGPASSWORD': 'sentinel', 'PGHOST': 'evil', 'PGSERVICE': 'evil',
        'DOCKER_HOST': 'evil', 'DATABASE_URL': 'sentinel', 'PYTHONPATH': 'evil',
        'APPDATA': 'private', 'SystemRoot': 'C:/Windows', 'PATH': 'untrusted'}
    env = b.child_environment(inherited, Path('synthetic-tools'), Path('synthetic-ca'))
    assert 'sentinel' not in repr(env) and 'evil' not in repr(env)
    assert 'PGPASSWORD' not in env and 'PGSERVICE' not in env and 'APPDATA' not in env
    assert env['PGPASSFILE'] == os.devnull and env['PGSERVICEFILE'] == os.devnull
    assert env['PGSSLMODE'] == 'verify-full' and env['PGGSSENCMODE'] == 'disable'
    assert env['PGSSLCERTMODE'] == 'disable' and env['PGSSLKEY'] == os.devnull
    assert 'default_transaction_read_only=on' in env['PGOPTIONS']


def test_preview_zero_reads_processes_or_writes(monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    def forbidden(*args: object, **kwargs: object) -> Any:
        raise AssertionError('forbidden IO')
    monkeypatch.setattr(b, 'measure', forbidden)
    monkeypatch.setattr(b, '_console', forbidden)
    monkeypatch.setattr(b.subprocess, 'Popen', forbidden)
    assert b.main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'PREVIEW'
    assert all(report[name] == 0 for name in ('input_reads', 'native_invocations', 'credential_reads', 'writes', 'network_requests'))


def test_arbitrary_errors_and_invalid_args_are_fixed_projection(monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    assert b.public_code(ValueError('private sentinel')) == 'BACKUP_STOP_REVIEW_PRESERVE_PARTIALS'
    assert b.main(['--password=private-sentinel']) == 2
    report = capsys.readouterr().out
    assert 'private-sentinel' not in report and 'INVALID_ARGUMENTS' in report
    assert b.public_code(OSError(errno.ENOSPC, 'private-sentinel')) == 'LOCAL_STORAGE_FULL_REVIEW'
    assert b.public_code(OSError(errno.EACCES, 'private-sentinel')) == 'LOCAL_OUTPUT_PERMISSION_REVIEW'


def test_export_fake_native_process_is_exclusive_bounded_and_not_restore(tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / 'new-attempt'
    monkeypatch.setattr(b, '_new_root', lambda p: p.mkdir())
    monkeypatch.setattr(b, '_private_path', lambda *a, **k: None)
    monkeypatch.setattr(b, 'OutputDirectory', SyntheticDirectory)
    tool_records = {name: {'tool': name} for name in b.TOOLS}
    ca = {'ca': 'synthetic'}
    def measure(path: Path, maximum: int) -> dict[str, Any]:
        if path.name == 'ca':
            return ca
        if path.suffix == '.exe':
            return tool_records[path.stem]
        raw = path.read_bytes()
        info = path.stat()
        return dict(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
            binding=dict(device=info.st_dev, file_id=info.st_ino))
    monkeypatch.setattr(b, 'measure', measure)
    phases: list[str] = []
    def native(argv: tuple[str, ...], *, sink: Any, **kwargs: Any) -> dict[str, Any]:
        phases.append(Path(argv[0]).stem)
        raw = b'SYNTHETIC_OPAQUE_BYTES'
        sink.write(raw)
        return dict(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
    monkeypatch.setattr(b, 'stream_process', native)
    report = b.export(root, env={'PGSSLROOTCERT': 'ca'}, tool_records=tool_records, ca_record=ca)
    assert phases == ['pg_dump', 'pg_dumpall', 'pg_restore']
    assert report['status'] == 'OPAQUE_LOGICAL_EXPORT_NOT_RESTORE'
    receipt = json.loads((root / 'manifest.json').read_text())
    assert receipt['roles_same_snapshot'] is False and receipt['platform_complete'] is False
    assert receipt['restore_verified'] is False and receipt['deletion_authorised'] is False
    assert set(path.name for path in root.iterdir()) == {'attempt.json', 'database.dump', 'roles.sql', 'toc.list', 'manifest.json'}
    with pytest.raises(FileExistsError):
        b.export(root, env={'PGSSLROOTCERT': 'ca'}, tool_records=tool_records, ca_record=ca)


@pytest.mark.parametrize('phase', ['pg_dump', 'pg_dumpall', 'pg_restore'])
def test_failed_native_phase_retains_partial_files_no_success_manifest(tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, phase: str) -> None:
    root = tmp_path / 'private-synthetic-attempt'
    monkeypatch.setattr(b, '_new_root', lambda p: p.mkdir())
    monkeypatch.setattr(b, '_private_path', lambda *a, **k: None)
    monkeypatch.setattr(b, 'OutputDirectory', SyntheticDirectory)
    records = {name: {'tool': name} for name in b.TOOLS}
    ca = {'ca': 'synthetic'}
    def measure(path: Path, maximum: int) -> dict[str, Any]:
        if path.name == 'ca':
            return ca
        if path.suffix == '.exe':
            return records[path.stem]
        raw = path.read_bytes()
        info = path.stat()
        return dict(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
                    binding=dict(device=info.st_dev, file_id=info.st_ino))
    monkeypatch.setattr(b, 'measure', measure)
    def native(argv: tuple[str, ...], *, sink: Any, **kwargs: Any) -> dict[str, Any]:
        raw = b'SYNTHETIC_PARTIAL'
        sink.write(raw)
        if Path(argv[0]).stem == phase:
            raise ValueError('NATIVE_PERMISSION_REVIEW')
        return dict(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
    monkeypatch.setattr(b, 'stream_process', native)
    with pytest.raises(b.JobBlocked) as error:
        b.export(root, env={'PGSSLROOTCERT': 'ca'}, tool_records=records, ca_record=ca)
    assert error.value.phase == dict(pg_dump='DATABASE_DUMP', pg_dumpall='ROLES_EXPORT',
                                     pg_restore='ARCHIVE_LIST')[phase]
    assert error.value.code == 'NATIVE_PERMISSION_REVIEW'
    assert (root / 'attempt.json').exists()
    assert not (root / 'manifest.json').exists()
    assert (root / dict(pg_dump='database.dump', pg_dumpall='roles.sql', pg_restore='toc.list')[phase]).read_bytes() == b'SYNTHETIC_PARTIAL'


@pytest.mark.parametrize('value', [None, '', 'A' * 64, 'private-sentinel', 1])
def test_tool_pins_are_explicit_not_tofu(value: object) -> None:
    with pytest.raises(ValueError, match='PINNED_NATIVE_TOOLS_REQUIRED'):
        b._hash(value)


def test_console_restore_failure_and_fixed_job_failure_are_single_json(monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(b.sys, 'version_info', (3, 13, 9))
    monkeypatch.setattr(b, '_console', lambda: (None, 1, 2))
    monkeypatch.setattr(b, '_private_path', lambda *a, **k: None)
    monkeypatch.setattr(b, 'measure', lambda *a, **k: {'synthetic': True})
    monkeypatch.setattr(b, 'check_tools', lambda *a: {})
    monkeypatch.setattr(b, 'reviewed_source', lambda *a: None)
    def fail(*args: object, **kwargs: object) -> NoReturn:
        raise b.JobBlocked('ROLES_EXPORT', 'NATIVE_PERMISSION_REVIEW')
    monkeypatch.setattr(b, 'export', fail)
    args = ['--mode', 'export', '--confirm-run', '--ca-file', 'ca', '--run-root', 'new',
        '--confirm-no-capture-running', '--confirm-opaque-holdout-backup', '--confirm-native-acceptance',
        '--pin-pg-dump', 'a' * 64, '--pin-pg-dumpall', 'b' * 64, '--pin-pg-restore', 'c' * 64]
    monkeypatch.setattr(b, 'restore_console', lambda state: True)
    assert b.main(args) == 2
    report = json.loads(capsys.readouterr().out)
    assert report['stage'] == 'ROLES_EXPORT' and report['code'] == 'NATIVE_PERMISSION_REVIEW'
    monkeypatch.setattr(b, 'restore_console', lambda state: False)
    assert b.main(args) == 2
    report = json.loads(capsys.readouterr().out)
    assert report['code'] == 'CONSOLE_RESTORE_UNVERIFIED'


@pytest.mark.parametrize('failed_reader', [1, 2])
def test_reader_start_failure_always_kills_and_waits_new_child(monkeypatch: pytest.MonkeyPatch,
        failed_reader: int) -> None:
    class Pipe:
        closed = False
        def close(self) -> None:
            self.closed = True
    class Process:
        stdout, stderr = Pipe(), Pipe()
        killed, waited = False, False
        def poll(self) -> int | None:
            return -9 if self.killed else None
        def kill(self) -> None:
            self.killed = True
        def wait(self, **kwargs: object) -> int:
            self.waited = True
            return -9
    process = Process()
    count = 0
    class Thread:
        ident: int | None = None
        def __init__(self, **kwargs: object) -> None:
            pass
        def start(self) -> None:
            nonlocal count
            count += 1
            if count == failed_reader:
                raise RuntimeError('synthetic startup failure')
            self.ident = 1
        def join(self, **kwargs: object) -> None:
            assert self.ident is not None
        def is_alive(self) -> bool:
            return False
    monkeypatch.setattr(b.subprocess, 'Popen', lambda *a, **k: process)
    monkeypatch.setattr(b.threading, 'Thread', Thread)
    with pytest.raises(RuntimeError, match='startup failure'):
        b.stream_process(('synthetic',), env={}, sink=io.BytesIO(), maximum=1, seconds=1)
    assert process.killed and process.waited and process.stdout.closed and process.stderr.closed


def test_windows_directory_chain_locks_and_replacement_before_create(tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    import ctypes
    root = tmp_path / 'new-native-fixture'
    root.mkdir()
    identity = (root.stat().st_dev, root.stat().st_ino)
    opened: list[tuple[Any, ...]] = []
    closed: list[int] = []
    class Function:
        def __init__(self, fn: Any) -> None:
            self.fn = fn
        def __call__(self, *args: Any) -> Any:
            return self.fn(*args)
    def create(*args: Any) -> int:
        opened.append(args)
        return len(opened) if args[4] == 3 else ctypes.c_void_p(-1).value
    def tag(handle: int, kind: int, pointer: Any, size: int) -> int:
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32))[0] = 0x10
        return 1
    def final(handle: int, buffer: Any, size: int, flags: int) -> int:
        buffer.value = '\\\\?\\Volume{11111111-1111-1111-1111-111111111111}\\private'
        return len(buffer.value)
    class Kernel:
        CreateFileW = Function(create)
        GetFileInformationByHandleEx = Function(tag)
        GetFinalPathNameByHandleW = Function(final)
        CloseHandle = Function(lambda handle: closed.append(handle) or 1)
    with monkeypatch.context() as scope:
        scope.setattr(b.os, 'name', 'nt')
        scope.setattr(b.ctypes, 'WinDLL', lambda *a, **k: Kernel(), raising=False)
        scope.setattr(b, '_private_path', lambda *a, **k: None)
        with b.OutputDirectory(root, identity) as guard:
            with pytest.raises(ValueError, match='NEW_ATTEMPT_DIRECTORY_REQUIRED'):
                guard.open_new('attempt.json')
            assert opened[-1][0].startswith('\\\\?\\Volume{')
            assert opened[-1][2] == 1 and opened[-1][4] == 1
            count = len(opened)
            root.rename(tmp_path / 'preserved-old-root')
            root.mkdir()
            with pytest.raises(ValueError, match='NATIVE_FILE_CHANGED'):
                guard.open_new('database.dump')
            assert len(opened) == count  # No private bytes created in replacement.
    assert all(args[2] == 3 for args in opened[:-1])  # No delete sharing on ancestors.
    assert len(closed) == len(opened) - 1


@pytest.mark.parametrize('pin', [None, 'main', 'A' * 40, 'a' * 39])
def test_runtime_source_requires_external_commit_before_git_or_private_io(pin: str | None,
        monkeypatch: pytest.MonkeyPatch) -> None:
    import programme_next_upload_check as package
    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError('No git/private IO for malformed external pin')
    monkeypatch.setattr(package, 'git', forbidden)
    with pytest.raises(ValueError, match='REVIEWED_SOURCE_REQUIRED'):
        b.reviewed_source(pin)


@pytest.mark.parametrize('tamper', ['', 'head', 'dirty', 'payload', 'prerequisite', 'manifest'])
def test_runtime_source_binds_clean_external_head_and_entire_closure(tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, tamper: str) -> None:
    import live_backup_upload_check as c
    import programme_next_upload_check as package
    head = 'a' * 40
    data = {'new.py': b'public code', 'dependency.py': b'reviewed dependency'}
    pins = {'dependency.py': package.sha(data['dependency.py'])}
    value = dict(version=c.VERSION, base=c.BASE, files={'new.py': package.sha(data['new.py']),
        c.MANIFEST: None}, prerequisites=pins)
    if tamper == 'manifest':
        value['base'] = 'unreviewed'
    data[c.MANIFEST] = json.dumps(value).encode()
    monkeypatch.setattr(c, 'FILES', ('new.py', c.MANIFEST))
    monkeypatch.setattr(c, 'PREREQUISITES', pins)
    monkeypatch.setattr(b, '__file__', str(tmp_path / 'live_database_backup.py'))
    monkeypatch.setattr(package, 'safe_read', lambda path: b'tampered' if (
        path.name == 'new.py' and tamper == 'payload'
        or path.name == 'dependency.py' and tamper == 'prerequisite') else data[path.name])
    def git(root: Path, *args: str) -> bytes:
        if args == ('rev-parse', 'HEAD'):
            return ('b' * 40 if tamper == 'head' else head).encode()
        if args == ('rev-parse', '--show-toplevel'):
            return str(tmp_path).encode()
        if args == ('status', '--porcelain'):
            return b'M changed.py' if tamper == 'dirty' else b''
        return data[args[1].split(':', 1)[1]]
    monkeypatch.setattr(package, 'git', git)
    if tamper:
        with pytest.raises(ValueError, match='REVIEWED_SOURCE_REQUIRED'):
            b.reviewed_source(head)
    else:
        b.reviewed_source(head)


def test_queue_initialization_failure_never_launches_child(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> NoReturn:
        raise RuntimeError('synthetic queue startup failure')
    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError('Child must not be launched')
    monkeypatch.setattr(b.queue, 'Queue', fail)
    monkeypatch.setattr(b.subprocess, 'Popen', forbidden)
    with pytest.raises(RuntimeError, match='queue startup failure'):
        b.stream_process(('synthetic',), env={}, sink=io.BytesIO(), maximum=1, seconds=1)


@pytest.mark.parametrize('winerror,accepted', [(32, True), (5, False)])
def test_directory_drill_proves_file_root_and_only_new_ancestor(tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, winerror: int, accepted: bool) -> None:
    root = tmp_path / 'new-drill'
    monkeypatch.setattr(b, '_new_root', lambda p: p.mkdir())
    monkeypatch.setattr(b, 'OutputDirectory', SyntheticDirectory)
    monkeypatch.setattr(b, '_private_path', lambda *a, **k: None)
    attempts: list[Path] = []
    def deny(source: Path, destination: Path) -> NoReturn:
        attempts.append(source)
        error = OSError('synthetic denial')
        error.winerror = winerror  # type: ignore[attr-defined]
        raise error
    monkeypatch.setattr(type(root), 'rename', deny)
    if accepted:
        result = b.directory_drill(root)
        assert result['root_lock_verified'] and result['drill_owned_ancestor_lock_verified']
        assert attempts == [root / 'guarded/attempt.json', root / 'guarded', root]
    else:
        with pytest.raises(ValueError, match='NATIVE_FILE_CHANGED'):
            b.directory_drill(root)
        assert len(attempts) == 1
