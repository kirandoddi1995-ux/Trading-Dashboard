"""Disjoint future diagnostics. Import/preview never touches capture or host state."""
from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from importlib import metadata
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable

IST = timezone(timedelta(hours=5, minutes=30))
IMPORT_DISTRIBUTIONS = {
    'cryptography': 'cryptography', 'google': 'google-auth', 'numpy': 'numpy',
    'pandas': 'pandas', 'pyarrow': 'pyarrow', 'requests': 'requests', 'urllib3': 'urllib3',
}
# Direct imports plus their publicly pinned runtime dependencies and Windows zone data.
PINS = {
    'cryptography': '50.0.1', 'cffi': '2.1.1', 'pycparser': '3.0',
    'google-auth': '2.57.0', 'pyasn1_modules': '0.4.2', 'pyasn1': '0.6.4',
    'numpy': '2.4.6', 'pandas': '2.3.3', 'python-dateutil': '2.9.0.post0',
    'six': '1.17.0', 'pytz': '2026.3.post1', 'tzdata': '2026.3',
    'pyarrow': '24.0.0', 'requests': '2.34.2', 'urllib3': '2.8.0',
    'certifi': '2026.10.19', 'charset-normalizer': '3.5.1', 'idna': '3.19',
}


@dataclass(frozen=True)
class Result:
    status: str
    code: str
    blockers: tuple[str, ...] = ()
    writes: int = 0
    credential_reads: int = 0
    capture_reads: int = 0
    approval_authority: bool = False
    capture_clock_verified: bool = False


def classify_exception(error: Exception) -> str:
    """Pure allowlist; never include exception strings, paths or OS output."""
    if isinstance(error, metadata.PackageNotFoundError):
        return 'DEPENDENCY_MISSING'
    if isinstance(error, subprocess.TimeoutExpired):
        return 'DIAGNOSTIC_TIMEOUT'
    if isinstance(error, PermissionError):
        return 'DIAGNOSTIC_ACCESS_DENIED'
    if isinstance(error, FileNotFoundError):
        return 'DIAGNOSTIC_EXECUTABLE_MISSING'
    if isinstance(error, (ValueError, TypeError, json.JSONDecodeError)):
        return 'DIAGNOSTIC_INPUT_INVALID'
    return 'DIAGNOSTIC_UNAVAILABLE'


def task_result(value: int) -> str:
    """Windows results are 32-bit codes, not inferred capture commit evidence."""
    if type(value) is not int or not -(2**31) <= value <= 0xFFFFFFFF:
        return 'TASK_RESULT_REVIEW_REQUIRED'
    return {
        0: 'PROCESS_EXIT_ZERO_NOT_CAPTURE_PROOF', 1: 'PROCESS_EXIT_ONE',
        2: 'PROCESS_EXIT_TWO', 0x41301: 'TASK_RUNNING',
        0x41302: 'TASK_DISABLED', 0x41303: 'TASK_NEVER_RUN',
        0x80070002: 'ACTION_FILE_NOT_FOUND',
        0xC000013A: 'PROCESS_TERMINATED_COMMIT_UNKNOWN',
    }.get(value & 0xFFFFFFFF, 'TASK_RESULT_REVIEW_REQUIRED')


def dependencies(version: Callable[[str], str] = metadata.version) -> Result:
    """Check distributions without importing operations/capture/provider code."""
    blockers: list[str] = []
    for name, expected in PINS.items():
        try:
            if version(name) != expected:
                blockers.append('DEPENDENCY_VERSION_MISMATCH:' + name)
        except Exception as error:
            blockers.append(classify_exception(error) + ':' + name)
    return Result('BLOCKED' if blockers else 'CHECKED',
                  'DEPENDENCY_REVIEW_REQUIRED' if blockers else 'METADATA_MATCH_NOT_IMPORT_PROOF',
                  tuple(blockers))


def package_check(public: Path) -> Result:
    """Static public-source closure check; never imports the existing operations."""
    try:
        expected: dict[str, str] = {}
        for name in ('requirements.txt', 'requirements-archive.txt', 'constraints.txt'):
            for line in (public / name).read_text(encoding='utf-8-sig').splitlines():
                match = re.fullmatch(r'([A-Za-z0-9_.-]+)(?:\[binary\])?==([^\s]+)', line)
                if match:
                    expected[match[1]] = match[2]
        manifest = (public / 'requirements-forward-operations.txt').read_text(encoding='utf-8')
        lines = {line.strip() for line in manifest.splitlines() if not line.startswith('#')}
        blockers = ['PUBLIC_PIN_MISMATCH:' + name for name, pin in PINS.items()
                    if expected.get(name) != pin or name + '==' + pin not in lines]
        pending = ['forward_session_ops']
        seen: set[str] = set()
        external: set[str] = set()
        while pending:
            module = pending.pop()
            if module in seen:
                continue
            seen.add(module)
            tree = ast.parse((public / (module + '.py')).read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                imports = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                           else [node.module or ''] if isinstance(node, ast.ImportFrom) else [])
                for imported in imports:
                    top = imported.split('.')[0]
                    if not top or top in sys.stdlib_module_names:
                        continue
                    if (public / (top + '.py')).is_file():
                        pending.append(top)
                    else:
                        external.add(top)
        blockers.extend('UNMAPPED_IMPORT:' + name for name in sorted(external - IMPORT_DISTRIBUTIONS.keys()))
        return Result('BLOCKED' if blockers else 'CHECKED',
                      'PACKAGE_REVIEW_REQUIRED' if blockers else 'PUBLIC_IMPORT_CLOSURE_PINNED', tuple(blockers))
    except Exception as error:
        return Result('BLOCKED', classify_exception(error))


def run_command(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(arguments, capture_output=True, text=True, timeout=12, check=False)


def clock_query(run: Callable[[list[str]], subprocess.CompletedProcess[str]] = run_command) -> Result:
    """Query only. A successful W32Time query cannot satisfy the capture NTP gate."""
    try:
        response = run(['w32tm.exe', '/query', '/status'])
        return Result('CHECKED' if response.returncode == 0 else 'BLOCKED',
                      'WINDOWS_TIME_QUERY_OK_CAPTURE_UNVERIFIED' if response.returncode == 0
                      else 'WINDOWS_TIME_QUERY_FAILED')
    except Exception as error:
        return Result('BLOCKED', classify_exception(error))


def task_query(name: str, run: Callable[[list[str]], subprocess.CompletedProcess[str]] = run_command) -> Result:
    """Owner-authorized future identity only; do not return actions/arguments/principal."""
    if re.fullmatch(r'KiranFuture-[A-Za-z0-9_-]{1,80}', name) is None:
        return Result('BLOCKED', 'FUTURE_TASK_NAME_REQUIRED')
    script = ("$ErrorActionPreference='Stop';"
              f"$t=Get-ScheduledTask -TaskPath '\\' -TaskName '{name}';"
              "$i=$t | Get-ScheduledTaskInfo;"
              "@{state=[string]$t.State;result=[long]$i.LastTaskResult} | ConvertTo-Json -Compress")
    try:
        response = run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script])
        if response.returncode != 0 or len(response.stdout) > 1024:
            return Result('BLOCKED', 'FUTURE_TASK_QUERY_FAILED')
        payload: object = json.loads(response.stdout)
        if not isinstance(payload, dict):
            return Result('BLOCKED', 'FUTURE_TASK_RESPONSE_INVALID')
        state, value = payload.get('state'), payload.get('result')
        if state not in ('Ready', 'Running', 'Disabled', 'Queued') or type(value) is not int:
            return Result('BLOCKED', 'FUTURE_TASK_RESPONSE_INVALID')
        # Disabled and running are review states, never operational acceptance.
        return Result('CHECKED' if state == 'Ready' and value == 0 else 'BLOCKED',
                      task_result(value), ('TASK_STATE_' + str(state).upper(),))
    except Exception as error:
        return Result('BLOCKED', classify_exception(error))


def rehearsal(day: date, now: datetime, *, exit_code: int, notify: bool,
              notification: Callable[[], bool]) -> tuple[Result, int]:
    """Synthetic launcher/notification only. No preflight, poll, audit or state paths."""
    if (now.tzinfo is None or now.utcoffset() is None or
            now.astimezone(IST).date() != day or
            now.astimezone(IST).hour * 60 + now.astimezone(IST).minute < 555 or
            exit_code not in (0, 1, 2)):
        return Result('BLOCKED', 'SAME_DAY_AFTER_OPEN_REHEARSAL_REQUIRED'), 2
    if notify:
        try:
            if notification() is not True:
                return Result('BLOCKED', 'NOTIFICATION_LAUNCH_FAILED'), 2
        except Exception as error:
            return Result('BLOCKED', classify_exception(error)), 2
    return Result('REHEARSAL_ONLY', 'NOTIFICATION_LAUNCHED_NOT_DELIVERED' if notify
                  else 'SYNTHETIC_CHILD_EXIT'), exit_code


def notify_local() -> bool:
    """Owner's optional local UI, no provider/network or capture imports."""
    script = ("Add-Type -AssemblyName System.Windows.Forms;"
              "[void][System.Windows.Forms.MessageBox]::Show("
              "'Future operations rehearsal only. No capture ran.', 'Future rehearsal')")
    subprocess.Popen(['powershell.exe', '-NoProfile', '-WindowStyle', 'Hidden', '-Command', script],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('package', 'dependencies', 'clock', 'task', 'rehearsal'), default='package')
    parser.add_argument('--allow-read-only', action='store_true')
    parser.add_argument('--allow-rehearsal', action='store_true')
    parser.add_argument('--task-name', default='')
    parser.add_argument('--session-date', default='')
    parser.add_argument('--synthetic-exit', type=int, choices=(0, 1, 2), default=0)
    parser.add_argument('--notify-local', action='store_true')
    args = parser.parse_args(argv)
    # Permission gates precede paths, metadata, wall clock, subprocesses and callbacks.
    if not (args.allow_rehearsal if args.mode == 'rehearsal' else args.allow_read_only):
        print(json.dumps(asdict(Result('PREVIEW', 'ZERO_IO_NO_CHECKS_PERFORMED'))))
        return 0
    code = 0
    try:
        if args.mode == 'package':
            result = package_check(Path(__file__).resolve().parent)
        elif args.mode == 'dependencies':
            result = dependencies()
        elif args.mode == 'clock':
            result = clock_query()
        elif args.mode == 'task':
            result = task_query(args.task_name)
        else:
            result, code = rehearsal(date.fromisoformat(args.session_date), datetime.now(timezone.utc),
                                     exit_code=args.synthetic_exit, notify=args.notify_local,
                                     notification=notify_local)
    except Exception as error:
        result = Result('BLOCKED', classify_exception(error))
    print(json.dumps(asdict(result)))
    return 2 if result.status == 'BLOCKED' else code


if __name__ == '__main__':
    raise SystemExit(main())
