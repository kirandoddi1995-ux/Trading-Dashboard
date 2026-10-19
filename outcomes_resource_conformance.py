"""Fixed synthetic-only child workloads under native resource limits. Default: no process IO."""
from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import ctypes as ct
import importlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from typing import Any, NoReturn, cast

MIB = 1024**2
WINDOWS_COMMIT = 768*MIB
LINUX_ADDRESS_SPACE = 3072*MIB
CPU_SECONDS = 15
WALL_SECONDS = 30
MAX_OUTPUT = 4096
CASES = ('small', 'large', 'dictionary', 'oversize', 'single_value', 'memory', 'hang', 'flood')
EXPECTED = dict(small='SYNTHETIC_CODEC_READBACK', large='SYNTHETIC_CODEC_READBACK',
    dictionary='SYNTHETIC_CODEC_READBACK', oversize='CANDIDATE_PROFILE_REJECTED',
    single_value='ROW_BOUND_REJECTED', memory='MEMORY_DENIED')


class _Basic(ct.Structure):
    _fields_ = [('process_time', ct.c_int64), ('job_time', ct.c_int64), ('flags', ct.c_uint32),
        ('min_working', ct.c_size_t), ('max_working', ct.c_size_t), ('active', ct.c_uint32),
        ('affinity', ct.c_size_t), ('priority', ct.c_uint32), ('scheduling', ct.c_uint32)]


class _Io(ct.Structure):
    _fields_ = [(name, ct.c_uint64) for name in ('reads', 'writes', 'other', 'read_bytes', 'write_bytes', 'other_bytes')]


class _Extended(ct.Structure):
    _fields_ = [('basic', _Basic), ('io', _Io), ('process_memory', ct.c_size_t),
        ('job_memory', ct.c_size_t), ('peak_process', ct.c_size_t), ('peak_job', ct.c_size_t)]


class _Accounting(ct.Structure):
    _fields_ = [(name, ct.c_int64) for name in ('user', 'kernel', 'period_user', 'period_kernel')] + [
        (name, ct.c_uint32) for name in ('faults', 'total', 'active', 'terminated')]


def _kernel() -> Any:
    kernel = ct.WinDLL('kernel32', use_last_error=True)
    definitions: dict[str, tuple[list[Any], Any]] = {
        'CreateJobObjectW': ([ct.c_void_p, ct.c_wchar_p], ct.c_void_p),
        'SetInformationJobObject': ([ct.c_void_p, ct.c_int, ct.c_void_p, ct.c_uint32], ct.c_int),
        'QueryInformationJobObject': ([ct.c_void_p, ct.c_int, ct.c_void_p, ct.c_uint32, ct.c_void_p], ct.c_int),
        'OpenProcess': ([ct.c_uint32, ct.c_int, ct.c_uint32], ct.c_void_p),
        'AssignProcessToJobObject': ([ct.c_void_p, ct.c_void_p], ct.c_int),
        'CloseHandle': ([ct.c_void_p], ct.c_int)}
    definitions.update({
        'OpenJobObjectW': ([ct.c_uint32, ct.c_int, ct.c_wchar_p], ct.c_void_p),
        'GetCurrentProcess': ([], ct.c_void_p),
        'IsProcessInJob': ([ct.c_void_p, ct.c_void_p, ct.c_void_p], ct.c_int),
        'ResumeThread': ([ct.c_void_p], ct.c_uint32),
        'WaitForSingleObject': ([ct.c_void_p, ct.c_uint32], ct.c_uint32),
        'GetExitCodeProcess': ([ct.c_void_p, ct.c_void_p], ct.c_int),
        'TerminateProcess': ([ct.c_void_p, ct.c_uint32], ct.c_int),
        'TerminateJobObject': ([ct.c_void_p, ct.c_uint32], ct.c_int),
        'InitializeProcThreadAttributeList': ([ct.c_void_p, ct.c_uint32, ct.c_uint32, ct.c_void_p], ct.c_int),
        'UpdateProcThreadAttribute': ([ct.c_void_p, ct.c_uint32, ct.c_size_t, ct.c_void_p, ct.c_size_t, ct.c_void_p, ct.c_void_p], ct.c_int),
        'DeleteProcThreadAttributeList': ([ct.c_void_p], None),
        'CreateProcessW': ([ct.c_wchar_p, ct.c_wchar_p, ct.c_void_p, ct.c_void_p, ct.c_int,
            ct.c_uint32, ct.c_void_p, ct.c_wchar_p, ct.c_void_p, ct.c_void_p], ct.c_int)})
    for name, (args, result) in definitions.items():
        getattr(kernel, name).argtypes = args
        getattr(kernel, name).restype = result
    return kernel


def _check_windows(kernel: Any, handle: Any) -> None:
    info = _Extended()
    if not kernel.QueryInformationJobObject(handle, 9, ct.byref(info), ct.sizeof(info), None):
        raise ValueError('JOB_READBACK_FAILED')
    flags = 0x2000 | 0x100 | 0x200 | 0x8 | 0x2  # kill-close,commit,job-memory,two processes,CPU
    if (info.basic.flags != flags or info.basic.active != 2 or info.process_memory != WINDOWS_COMMIT
            or info.job_memory != WINDOWS_COMMIT or info.basic.process_time != CPU_SECONDS*10000000):
        raise ValueError('JOB_LIMITS_MISMATCH')


class _WindowsJob:
    def __init__(self, pid: int) -> None:
        self.kernel = _kernel()
        self.name = 'Local\\ResearchOps_Outcomes_' + uuid.uuid4().hex
        ct.set_last_error(0)
        self.handle = self.kernel.CreateJobObjectW(None, self.name)
        if not self.handle or ct.get_last_error() == 183:
            self.close()
            raise ValueError('JOB_CREATE_FAILED')
        try:
            info = _Extended()
            info.basic.flags = 0x2000 | 0x100 | 0x200 | 0x8 | 0x2
            info.basic.active = 2  # pinned Windows venv redirector + Python worker; no arbitrary children
            info.basic.process_time = CPU_SECONDS*10000000
            info.process_memory = info.job_memory = WINDOWS_COMMIT
            if not self.kernel.SetInformationJobObject(self.handle, 9, ct.byref(info), ct.sizeof(info)):
                raise ValueError('JOB_SET_FAILED')
            process = self.kernel.OpenProcess(0x101, False, pid)  # set-quota + terminate,own child only
            if not process:
                raise ValueError('CHILD_HANDLE_FAILED')
            try:
                if not self.kernel.AssignProcessToJobObject(self.handle, process):
                    raise ValueError('JOB_ASSIGN_FAILED')
            finally:
                self.kernel.CloseHandle(process)
            _check_windows(self.kernel, self.handle)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None

    def stop_and_verify_empty(self) -> bool:
        if not self.kernel.TerminateJobObject(self.handle, 2):
            return False
        deadline = time.monotonic()+3
        while time.monotonic() < deadline:
            info = _Accounting()
            if not self.kernel.QueryInformationJobObject(self.handle, 1, ct.byref(info), ct.sizeof(info), None):
                return False
            if info.active == 0:
                return True
            time.sleep(0.01)
        return False


class _Startup(ct.Structure):
    _fields_ = [('cb', ct.c_uint32), ('reserved', ct.c_wchar_p), ('desktop', ct.c_wchar_p),
        ('title', ct.c_wchar_p), *[(n, ct.c_uint32) for n in ('x', 'y', 'cx', 'cy', 'chars_x',
        'chars_y', 'fill', 'flags')], ('show', ct.c_uint16), ('reserved_size', ct.c_uint16),
        ('reserved_bytes', ct.c_void_p), ('stdin', ct.c_void_p), ('stdout', ct.c_void_p), ('stderr', ct.c_void_p)]


class _StartupEx(ct.Structure):
    _fields_ = [('startup', _Startup), ('attributes', ct.c_void_p)]


class _ProcessInfo(ct.Structure):
    _fields_ = [('process', ct.c_void_p), ('thread', ct.c_void_p), ('pid', ct.c_uint32), ('tid', ct.c_uint32)]


class _WindowsChild:
    """Native suspended launch with ONLY its two explicit pipe handles inherited."""
    def __init__(self, args: list[str]) -> None:
        import msvcrt
        self.kernel = _kernel()
        self.info = _ProcessInfo()
        self.returncode: int | None = None
        self.stdin: Any = None
        self.stdout: Any = None
        owned_fds: set[int] = set()
        attributes: Any = None
        attributes_initialized = False
        succeeded = False
        try:
            in_read, in_write = os.pipe()
            owned_fds.update((in_read, in_write))
            out_read, out_write = os.pipe()
            owned_fds.update((out_read, out_write))
            os.set_inheritable(in_read, True)
            os.set_inheritable(out_write, True)
            handles = (ct.c_void_p*2)(msvcrt.get_osfhandle(in_read), msvcrt.get_osfhandle(out_write))
            size = ct.c_size_t()
            self.kernel.InitializeProcThreadAttributeList(None, 1, 0, ct.byref(size))
            if not 0 < size.value <= 65536:
                raise ValueError('PROCESS_ATTRIBUTES_BOUND')
            attributes = ct.create_string_buffer(size.value)
            if not self.kernel.InitializeProcThreadAttributeList(attributes, 1, 0, ct.byref(size)):
                raise ValueError('PROCESS_ATTRIBUTES_REJECTED')
            attributes_initialized = True
            if not self.kernel.UpdateProcThreadAttribute(attributes, 0, 0x20002, handles, ct.sizeof(handles), None, None):
                raise ValueError('EXPLICIT_PIPE_HANDLES_REJECTED')
            startup = _StartupEx()
            startup.startup.cb = ct.sizeof(startup)
            startup.startup.flags = 0x100
            startup.startup.stdin = handles[0]
            startup.startup.stdout = startup.startup.stderr = handles[1]
            startup.attributes = ct.cast(attributes, ct.c_void_p)
            command = ct.create_unicode_buffer(subprocess.list2cmdline(args))
            env = ct.create_unicode_buffer('\0'.join(k+'='+v for k,v in sorted(child_environment().items()))+'\0\0')
            flags = 0x4 | 0x80000 | 0x400 | 0x08000000  # suspended,extended startup,unicode env,no window
            if not self.kernel.CreateProcessW(args[0], command, None, None, True, flags, env,
                    str(Path(__file__).resolve().parent), ct.byref(startup), ct.byref(self.info)):
                raise ValueError('SUSPENDED_CHILD_CREATE_FAILED')
            self.pid = int(self.info.pid)
            self.stdin = os.fdopen(in_write, 'wb', buffering=0)
            owned_fds.remove(in_write)
            self.stdout = os.fdopen(out_read, 'rb', buffering=0)
            owned_fds.remove(out_read)
            succeeded = True
        finally:
            if attributes_initialized:
                self.kernel.DeleteProcThreadAttributeList(attributes)
            for fd in owned_fds:
                os.close(fd)
            if not succeeded:
                for stream in (self.stdin, self.stdout):
                    if stream is not None:
                        stream.close()
                if self.info.process:
                    self.kernel.TerminateProcess(self.info.process, 2)
                    self.kernel.WaitForSingleObject(self.info.process, 3000)
                self.close()

    def resume(self) -> None:
        if self.kernel.ResumeThread(self.info.thread) == 0xffffffff:
            raise ValueError('CHILD_RESUME_FAILED')
        self.kernel.CloseHandle(self.info.thread)
        self.info.thread = None

    def poll(self) -> int | None:
        if self.returncode is None and self.kernel.WaitForSingleObject(self.info.process, 0) == 0:
            code = ct.c_uint32()
            if not self.kernel.GetExitCodeProcess(self.info.process, ct.byref(code)):
                raise ValueError('CHILD_EXIT_QUERY_FAILED')
            self.returncode = int(code.value)
        return self.returncode

    def wait(self, timeout: float) -> int:
        result = self.kernel.WaitForSingleObject(self.info.process, int(timeout*1000))
        if result == 258:
            raise subprocess.TimeoutExpired('synthetic-child', timeout)
        if result != 0:
            raise ValueError('CHILD_WAIT_FAILED')
        code = self.poll()
        if code is None:
            raise ValueError('CHILD_EXIT_UNKNOWN')
        return code

    def kill(self) -> None:
        self.kernel.TerminateProcess(self.info.process, 2)

    def close(self) -> None:
        for field in ('thread', 'process'):
            handle = getattr(self.info, field)
            if handle:
                self.kernel.CloseHandle(handle)
                setattr(self.info, field, None)


def _linux_limits(pid: int) -> None:
    resource: Any = importlib.import_module('resource')
    for kind, amount in ((resource.RLIMIT_AS, LINUX_ADDRESS_SPACE), (resource.RLIMIT_CPU, CPU_SECONDS),
                         (resource.RLIMIT_CORE, 0), (resource.RLIMIT_FSIZE, 0)):
        soft, hard = resource.prlimit(pid, kind)
        if hard != resource.RLIM_INFINITY and hard < amount:
            raise ValueError('EXISTING_LIMIT_MORE_RESTRICTIVE')
        resource.prlimit(pid, kind, (amount, amount))
        if resource.prlimit(pid, kind) != (amount, amount):
            raise ValueError('RLIMIT_READBACK_FAILED')


def _child_limit_check(job_name: str) -> None:
    if os.name == 'nt':
        kernel = _kernel()
        handle = kernel.OpenJobObjectW(0x4, False, job_name)  # QUERY only,never inherit this handle
        if not handle:
            raise ValueError('CHILD_JOB_QUERY_FAILED')
        try:
            member = ct.c_int()
            if not kernel.IsProcessInJob(kernel.GetCurrentProcess(), handle, ct.byref(member)) or not member.value:
                raise ValueError('CHILD_JOB_MEMBERSHIP_FAILED')
            _check_windows(kernel, handle)
        finally:
            kernel.CloseHandle(handle)
    elif sys.platform == 'linux':
        resource: Any = importlib.import_module('resource')
        for kind, amount in ((resource.RLIMIT_AS, LINUX_ADDRESS_SPACE), (resource.RLIMIT_CPU, CPU_SECONDS),
                             (resource.RLIMIT_CORE, 0), (resource.RLIMIT_FSIZE, 0)):
            if resource.getrlimit(kind) != (amount, amount):
                raise ValueError('CHILD_RLIMIT_MISMATCH')
    else:
        raise ValueError('UNSUPPORTED_PLATFORM')


def child_environment() -> dict[str, str]:
    # No caller credential variables,HOME,proxy,Python startup flags or network configuration.
    result = {name: os.environ[name] for name in ('SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP') if name in os.environ}
    result.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', ARROW_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1')
    return result


def _synthetic_work(case: str) -> str:
    if case == 'memory':
        try:
            bytearray((WINDOWS_COMMIT if os.name == 'nt' else LINUX_ADDRESS_SPACE)+256*MIB)
        except MemoryError:
            return 'MEMORY_DENIED'
        return 'MEMORY_LIMIT_NOT_ENFORCED'
    if case == 'hang':
        time.sleep(10)
        return 'UNEXPECTED_COMPLETION'
    if case == 'flood':
        os.write(1, b'F'*8192)
        return 'UNEXPECTED_COMPLETION'
    # Trusted public helpers imported ONLY after native limits + parent GO + child readback.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import drive_archive as codec
    import archive_recovery_review as review
    from outcomes_footer_diagnostic import inspect_footer
    from outcomes_large_profile import candidate_matches, MAX_ROW_BYTES
    import hashlib
    rows = 1 if case == 'single_value' else 2 if case == 'small' else 100
    length = 20*MIB if case == 'single_value' else 350000 if case == 'oversize' else 300000 if case != 'small' else 1024
    texts = []
    for i in range(rows):
        payload = dict(synthetic_fixture=True, padding='S'*length)
        if case != 'dictionary':
            payload['synthetic_ordinal'] = i
        texts.append(json.dumps(dict(snapshot_id=f'synthetic-{i}', decision_id='synthetic',
            payload=payload, recorded_at='2022-01-03T00:00:00+00:00'), sort_keys=True, separators=(',', ':')))
    encode = cast(Callable[[str, list[str]], tuple[str, bytes, list[str]]], codec.parquet_bytes)
    decode = cast(Callable[[bytes, str, str, int, str], list[str]], codec.verify_parquet)
    batch, data, _ = encode('equity_research.outcomes', texts)
    receipt = review.Receipt(batch, 'equity_research.outcomes', rows, hashlib.sha256(data).hexdigest(),
                             'synthetic-data', 'synthetic-manifest', 0, '')
    observation = inspect_footer(data, receipt)
    if not candidate_matches('equity_research.outcomes', observation):
        return 'CANDIDATE_PROFILE_REJECTED'
    # Synthetic private-free codec readback is not Postgres or durable restore.
    restored = decode(data, 'equity_research.outcomes', batch, rows, receipt.file_sha256)
    if any(len(text.encode()) > MAX_ROW_BYTES for text in restored):
        return 'ROW_BOUND_REJECTED'
    if sorted(restored) != sorted(texts):
        raise ValueError('SYNTHETIC_READBACK_MISMATCH')
    return 'SYNTHETIC_CODEC_READBACK'


def _child(case: str) -> int:
    try:
        line = sys.stdin.buffer.readline(128)
        if not _reviewed_python() or case not in CASES or not line.startswith(b'SYNTHETIC_GO ') or not line.endswith(b'\n'):
            raise ValueError('PARENT_ADMISSION_REQUIRED')
        job_name = line[len(b'SYNTHETIC_GO '):-1].decode('ascii')
        if os.name == 'nt' and re.fullmatch(r'Local\\ResearchOps_Outcomes_[a-f0-9]{32}', job_name) is None:
            raise ValueError('PARENT_JOB_NAME_REJECTED')
        _child_limit_check(job_name)
        result = _synthetic_work(case)
        print(json.dumps(dict(case=case, result=result, limits_read_back=True)), flush=True)
        return 0
    except Exception:
        print(json.dumps(dict(case=case, result='SYNTHETIC_CHILD_REJECTED', raw_error_printed=False)), flush=True)
        return 2


def run_case(case: str) -> dict[str, Any]:
    if case not in CASES:
        raise ValueError('FIXED_SYNTHETIC_CASE_REQUIRED')
    if not _reviewed_python():
        raise ValueError('EXPLICIT_REVIEWED_PYTHON_3139_REQUIRED')
    process: Any = None
    job: _WindowsJob | None = None
    output = bytearray()
    overflow = threading.Event()
    read_failed = threading.Event()
    read_eof = threading.Event()
    reader: threading.Thread | None = None
    caps = released = timed_out = reaped = job_empty = False
    code = 'RESOURCE_SETUP_REJECTED'
    try:
        args = [sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--child', case]
        process = _WindowsChild(args) if os.name == 'nt' else subprocess.Popen(args,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=str(Path(__file__).resolve().parent), env=child_environment(), bufsize=0)
        child = process
        def collect() -> None:
            try:
                assert child.stdout is not None
                while len(output) <= MAX_OUTPUT:
                    block = child.stdout.read(min(1024, MAX_OUTPUT+1-len(output)))
                    if not block:
                        read_eof.set()
                        return
                    output.extend(block)
                overflow.set()
                if child.poll() is None:
                    child.kill()
            except Exception:
                read_failed.set()
        reader = threading.Thread(target=collect, daemon=True)
        reader.start()
        if os.name == 'nt':
            job = _WindowsJob(process.pid)
            process.resume()  # NO user Python code runs before the job is configured and assigned
        elif sys.platform == 'linux':
            _linux_limits(process.pid)
        else:
            raise ValueError('UNSUPPORTED_PLATFORM')
        caps = True
        assert process.stdin is not None
        process.stdin.write(('SYNTHETIC_GO '+(job.name if job is not None else '-')+'\n').encode())
        process.stdin.close()
        released = True
        try:
            process.wait(timeout=2 if case == 'hang' else WALL_SECONDS)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            process.wait(timeout=3)
        reaped = process.poll() is not None
        reader.join(timeout=2)
        if case == 'hang' and timed_out:
            code = 'WALL_TIMEOUT_ENFORCED'
        elif case == 'flood' and overflow.is_set():
            code = 'OUTPUT_BOUND_ENFORCED'
        elif not timed_out and not overflow.is_set() and not read_failed.is_set() and not reader.is_alive():
            value = json.loads(bytes(output))
            if (process.returncode == 0 and set(value) == {'case', 'result', 'limits_read_back'}
                    and value['case'] == case and value['limits_read_back'] is True
                    and value['result'] == EXPECTED.get(case)):
                code = 'EXPECTED_SYNTHETIC_RESULT'
            else:
                code = 'SYNTHETIC_RESULT_REJECTED'
        else:
            code = 'CHILD_OUTPUT_OR_TIMEOUT_REJECTED'
    except json.JSONDecodeError:
        code = 'CHILD_RESULT_NOT_JSON'
    except Exception:
        code = 'RESOURCE_SETUP_REJECTED' if not released else 'SYNTHETIC_RUN_REJECTED'
    finally:
        if job is not None:
            try:
                job_empty = job.stop_and_verify_empty()
            finally:
                job.close()  # parent-owned kill-on-close
        if process is not None:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=3)
                reaped = process.poll() is not None
            except subprocess.TimeoutExpired:
                reaped = False
            if reader is not None:
                reader.join(timeout=1)
            if process.stdin is not None:
                process.stdin.close()
            if process.stdout is not None and (reader is None or not reader.is_alive()):
                process.stdout.close()
            if isinstance(process, _WindowsChild):
                process.close()
    passed = (caps and released and reaped and not read_failed.is_set()
        and (overflow.is_set() or read_eof.is_set()) and (os.name != 'nt' or job_empty)
        and (reader is None or not reader.is_alive())
        and code in ('EXPECTED_SYNTHETIC_RESULT', 'WALL_TIMEOUT_ENFORCED', 'OUTPUT_BOUND_ENFORCED'))
    return dict(case=case, status='PASS' if passed else 'BLOCKED', code=code,
        native_limits_read_back=caps, synthetic_workload_released=released, child_reaped=reaped,
        windows_job_empty_verified=job_empty,
        output_limit_hit=overflow.is_set(), wall_timeout_hit=timed_out,
        platform='WINDOWS_JOB_COMMIT' if os.name == 'nt' else 'LINUX_RLIMIT_AS',
        private_inputs=0, credential_reads=0, database_writes=0, capture_changes=0,
        filesystem_network_sandbox_verified=False, private_decode_authorised=False, approval_authority=False)


def _reviewed_python() -> bool:
    return sys.version_info[:3] == (3, 13, 9)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError('SYNTHETIC_ARGUMENTS_REJECTED')


def main(argv: Sequence[str] | None = None) -> int:
    try:
        parser = _Parser(description=__doc__)
        parser.add_argument('--child', choices=CASES)
        parser.add_argument('--execute', action='store_true')
        parser.add_argument('--confirm-synthetic', action='store_true')
        args = parser.parse_args(argv)
        if args.child:
            return _child(args.child)
        if not args.execute or not args.confirm_synthetic:
            print(json.dumps(dict(status='PREVIEW', child_processes=0, private_inputs=0, writes=0, approval_authority=False)))
            return 0
        results = []
        for case in CASES:
            result = run_case(case)
            print(json.dumps(result), flush=True)
            results.append(result)
        passed = all(result['status'] == 'PASS' for result in results)
        print(json.dumps(dict(status='SYNTHETIC_RESOURCE_CONFORMANCE_PASSED' if passed else 'BLOCKED',
            cases=len(results), private_decode_authorised=False, full_catalog_byte_footer_coverage=False,
            independent_custody_verified=False, postgres_restore_verified=False, deletion_authorised=False,
            training_eligible=False, approval_authority=False)), flush=True)
        return 0 if passed else 2
    except Exception:
        print(json.dumps(dict(status='BLOCKED', code='SYNTHETIC_CONFORMANCE_REVIEW_REQUIRED', raw_error_printed=False,
                             private_decode_authorised=False, approval_authority=False)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
