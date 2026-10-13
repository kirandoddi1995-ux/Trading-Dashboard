"""Explicit Windows read-only diagnostics and optional owner-session notification."""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Callable, cast

from equity_runtime_health import clock_error, measure_clock
from nifty_session_calendar import cash_session

MIN_FREE_BYTES = 1024**3  # Local operational reserve, not a measured daily budget.


def task_name(value: str) -> str:
    """Accept task identities, never shell expressions or private argument values."""
    if re.fullmatch(r'[A-Za-z0-9_-]{1,160}', value) is None:
        raise ValueError('TASK_NAME_INVALID')
    return value


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
    bindings = ''.join(f"-and ($arg.IndexOf('{str(p).replace(chr(39), chr(39)*2)}', [StringComparison]::OrdinalIgnoreCase) -ge 0) "
                       for p in (root, ops) if p is not None)
    return powershell("$ErrorActionPreference='Stop'; $s=Get-CimInstance Win32_Service -Filter \"Name='w32time'\"; $r=@{"
        "time_service_running=($s.State -eq 'Running'); time_service_automatic=($s.StartMode -eq 'Auto')};"
        f"foreach($n in @('{poll}','{audit}')) {{"
        "$t=Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue;"
        "if($null -eq $t){$r[$n]=@{exists=$false};continue};"
        "$i=$t | Get-ScheduledTaskInfo; $a=@($t.Actions); $ok=$false;"
        "if($a.Count -eq 1){ $x=$a[0]; $arg=$x.Arguments.Replace('/','\\');"
        f"$ok=($arg.IndexOf('{wrapper}', [StringComparison]::OrdinalIgnoreCase) -ge 0) "
        f"-and ($arg.IndexOf('{python}', [StringComparison]::OrdinalIgnoreCase) -ge 0) "
        f"-and ($arg -match '(?:--session-date|-SessionDate)\\s+\"?{day.isoformat()}(?:\"|\\s|$)') "
        + bindings +
        f"-and (Test-Path -LiteralPath '{wrapper}' -PathType Leaf) "
        f"-and (Test-Path -LiteralPath '{python}' -PathType Leaf) "
        "-and (Test-Path -LiteralPath $x.Execute -PathType Leaf); };"
        f"$mode=if($n -eq '{poll}'){{'poll'}}else{{'audit'}};"
        "$ok=$ok -and ($a.Count -eq 1) -and ($a[0].Arguments -match ('(?:--mode|-Mode)\\s+\"?'+$mode+'(?:\"|\\s|$)'));"
        "$r[$n]=@{exists=$true; action_matches=$ok; disabled=($t.State -eq 'Disabled');"
        "running=($t.State -eq 'Running'); last_result=[long]$i.LastTaskResult}; };"
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
