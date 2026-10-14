"""Explicit Windows read-only diagnostics and optional owner-session notification."""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import subprocess
import sys
from typing import Any, Callable, Mapping, cast

from equity_runtime_health import clock_error, measure_clock
from nifty_session_calendar import cash_session

MIN_FREE_BYTES = 1024**3  # Local operational reserve, not a measured daily budget.


def task_name(value: str) -> str:
    """Accept task identities, never shell expressions or private argument values."""
    if re.fullmatch(r'[A-Za-z0-9_-]{1,160}', value) is None:
        raise ValueError('TASK_NAME_INVALID')
    return value


def expected_task_actions(day: date, poll: str, audit: str, *, code: str, python: str,
                          root: str, ops: str, system_root: str) -> dict[str, dict[str, str]]:
    """Pure exact forward_ops_plan arguments; no calendar, paths or host reads."""
    if type(day) is not date:
        raise ValueError('TASK_BINDING_IDENTITY_INVALID')
    namespace = 'KiranTrading-Versioned-' + day.strftime('%Y%m%d')
    if poll != namespace + '-poll' or audit != namespace + '-audit':
        raise ValueError('TASK_BINDING_IDENTITY_INVALID')
    values = (code, python, root, ops, system_root)
    if any(not PureWindowsPath(value).is_absolute() or '..' in PureWindowsPath(value).parts
           or any(c in value for c in '\r\n"') or value.endswith(('\\', '/')) for value in values):
        raise ValueError('TASK_BINDING_PATH_INVALID')
    code_path, python_path, root_path, ops_path, windows = map(PureWindowsPath, values)
    if (not python_path.is_relative_to(code_path) or root_path.is_relative_to(code_path)
            or ops_path.is_relative_to(code_path) or root_path.is_relative_to(ops_path)
            or ops_path.is_relative_to(root_path)):
        raise ValueError('TASK_BINDING_PATH_INVALID')
    result: dict[str, dict[str, str]] = {}
    for mode, identity in (('poll', poll), ('audit', audit)):
        arguments = ['-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-File',
            str(code_path / 'forward_ops_task.ps1'), '-PythonExecutable', str(python_path),
            '-CodeDirectory', str(code_path), '-StateRoot', str(root_path), '-OpsRoot', str(ops_path),
            '-SessionDate', day.isoformat(), '-Mode', mode, '-PollTask', poll, '-AuditTask', audit]
        result[identity] = {'Execute': str(windows / 'System32/WindowsPowerShell/v1.0/powershell.exe'),
            'WorkingDirectory': str(code_path), 'Arguments': subprocess.list2cmdline(arguments)}
    return result


def exact_action_matches(action: Mapping[str, object], expected: Mapping[str, str]) -> bool:
    """Normalize separators/case only; extra/reordered arguments are not accepted."""
    return all(type(action.get(key)) is str and str(action[key]).replace('/', '\\').casefold()
               == value.replace('/', '\\').casefold() for key, value in expected.items()) and set(expected) == {
                   'Execute', 'WorkingDirectory', 'Arguments'}


def powershell(script: str) -> dict[str, Any]:
    """Fixed read-only commands only; discard raw OS output on every failure."""
    if os.name != 'nt':
        raise ValueError('WINDOWS_DIAGNOSTICS_UNAVAILABLE')
    executable = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(executable), '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, text=True, timeout=12,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode or len(result.stdout) > 16384:
        raise ValueError('WINDOWS_DIAGNOSTICS_UNAVAILABLE')
    value: Any = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError('WINDOWS_DIAGNOSTICS_UNAVAILABLE')
    return value


def inspect_tasks(day: date, poll: str, audit: str, root: Path | None = None,
                  ops: Path | None = None) -> dict[str, Any]:
    """Report booleans/status only; never print task arguments or path values."""
    poll, audit = task_name(poll), task_name(audit)
    code = Path(__file__).resolve().parent
    wrapper = str(code / 'forward_ops_task.ps1').replace("'", "''")
    python = str(Path(sys.executable).resolve()).replace("'", "''")
    expected: dict[str, dict[str, str]] = {}
    if root is not None and ops is not None:
        try:
            expected = expected_task_actions(day, poll, audit, code=str(code),
                python=str(Path(sys.executable).resolve()), root=str(root), ops=str(ops),
                system_root=os.environ['SystemRoot'])
        except (ValueError, KeyError):
            pass  # Missing exact bindings can never produce action_matches=True.
    declarations = '$expected=@{};'
    for identity, fields in expected.items():
        declarations += "$expected['" + identity + "']=@{" + ';'.join(
            key + "='" + value.replace("'", "''") + "'" for key, value in fields.items()) + '};'
    return powershell("$ErrorActionPreference='Stop'; $s=Get-CimInstance Win32_Service -Filter \"Name='w32time'\"; $r=@{"
        "time_service_running=($s.State -eq 'Running'); time_service_automatic=($s.StartMode -eq 'Auto')};"
        + declarations + f"foreach($n in @('{poll}','{audit}')) {{"
        "$t=Get-ScheduledTask -TaskPath '\\' -TaskName $n -ErrorAction SilentlyContinue;"
        "if($null -eq $t){$r[$n]=@{exists=$false};continue};"
        "$i=$t | Get-ScheduledTaskInfo; $a=@($t.Actions); $ok=$false;"
        "if($a.Count -eq 1 -and $expected.ContainsKey($n)){ $x=$a[0]; $e=$expected[$n]; $ok=$true;"
        "foreach($field in @('Execute','WorkingDirectory','Arguments')){"
        "$ok=$ok -and [String]::Equals(([string]$x.$field).Replace('/','\\'),"
        "([string]$e[$field]).Replace('/','\\'),[StringComparison]::OrdinalIgnoreCase); };"
        "$ok=$ok -and (Test-Path -LiteralPath $x.Execute -PathType Leaf) "
        f"-and (Test-Path -LiteralPath '{wrapper}' -PathType Leaf) "
        f"-and (Test-Path -LiteralPath '{python}' -PathType Leaf); }};"
        "$r[$n]=@{exists=$true; action_matches=$ok; disabled=($t.State -eq 'Disabled');"
        "running=($t.State -eq 'Running'); enabled=($t.Settings.Enabled -eq $true); "
        "state=[string]$t.State; last_result=[long]$i.LastTaskResult}; };"
        "$r | ConvertTo-Json -Depth 4 -Compress")


def preflight(day: date, poll: str, audit: str, disk_parent: Path, *,
              root: Path | None = None, ops: Path | None = None) -> dict[str, Any]:
    """Independent NTP measurement plus service/tasks/disk; no repair or credentials."""
    blockers: list[str] = []
    facts: dict[str, Any] = {}
    if cast(Callable[[date], dict[str, Any]], cash_session)(day)['kind'] != 'REGULAR':
        blockers.append('REVIEWED_REGULAR_SESSION_REQUIRED')
    try:
        facts = inspect_tasks(day, poll, audit, root, ops)
        if facts.get('time_service_running') is not True:
            blockers.append('WINDOWS_TIME_SERVICE_NOT_RUNNING')
        if facts.get('time_service_automatic') is False:
            blockers.append('WINDOWS_TIME_SERVICE_NOT_AUTOMATIC')
        for name, mode in ((poll, 'POLL'), (audit, 'AUDIT')):
            entry = facts.get(name, {})
            if entry.get('exists') is not True or entry.get('action_matches') is not True:
                blockers.append(mode + '_TASK_ACTION_MISMATCH')
    except Exception:
        blockers.append('WINDOWS_DIAGNOSTICS_UNAVAILABLE')
    try:
        free = shutil.disk_usage(disk_parent).free
        facts['free_bytes'] = free
        if free < MIN_FREE_BYTES:
            blockers.append('LOCAL_DISK_RESERVE_NOT_MET')
        if root is not None:
            facts['capture_volume_free_bytes'] = shutil.disk_usage(root.parent).free
            if facts['capture_volume_free_bytes'] < MIN_FREE_BYTES:
                blockers.append('CAPTURE_DISK_RESERVE_NOT_MET')
    except OSError:
        blockers.append('LOCAL_DISK_CHECK_UNAVAILABLE')
    probe = cast(Callable[[], dict[str, Any]], measure_clock)()
    problem = cast(Callable[..., str | None], clock_error)(probe, now=datetime.now(timezone.utc), maximum_offset=1.0)
    facts['clock_check'] = problem or 'PASS'
    if problem:
        blockers.append(problem)
    # NTP success is not proof of Upstox/Drive reachability or source availability.
    return {'status': 'PREOPEN_HOST_CHECK_PASSED' if not blockers else 'BLOCKED',
            'blockers': blockers, 'facts': facts, 'credentials_checked': False,
            'provider_and_drive_health': 'NOT_CHECKED', 'repairs_performed': 0,
            'approval_authority': False, 'training_eligible': False}


def notify(category: str) -> bool:
    """Nonblocking local message box; no network, interactive owner session required."""
    if re.fullmatch('[A-Z_]{1,80}', category) is None or os.name != 'nt':
        return False
    script = ("Add-Type -AssemblyName System.Windows.Forms;"
              f"[void][System.Windows.Forms.MessageBox]::Show('Capture needs review: {category.replace('_', ' ').lower()}. "
              "Open the latest operations report. No missed slot will be retried.', 'NIFTY capture alert')")
    try:
        executable = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        subprocess.Popen([str(executable), '-NoProfile', '-WindowStyle', 'Hidden', '-Command', script],
                         creationflags=subprocess.CREATE_NO_WINDOW,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True  # Launch only, not proof that the owner saw it.
    except OSError:
        return False
