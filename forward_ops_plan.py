"""Pure disabled date-pinned Windows plans. Never registers/enables/retires tasks."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import json
from pathlib import PureWindowsPath
import re
import subprocess
import xml.etree.ElementTree as ET
from typing import Any, Callable, cast
from zoneinfo import ZoneInfo
from nifty_session_calendar import cash_session


def plans(day: date, *, sid: str, code: str, python: str, state: str, ops: str) -> dict[str, str]:
    """Generate three one-day least-privilege plans; no recurrence across dates."""
    paths = [PureWindowsPath(s) for s in (code, python, state, ops)]
    if cast(Callable[[date], dict[str, Any]], cash_session)(day)['kind'] != 'REGULAR':
        raise ValueError('REVIEWED_REGULAR_SESSION_REQUIRED')
    if (re.fullmatch(r'S-1-5-(?:\d+-)*\d+', sid) is None
            or any(not p.is_absolute() or '..' in p.parts for p in paths)
            or any(any(c in s for c in '\r\n"') or s.endswith('\\') for s in (code, python, state, ops))
            or not paths[1].is_relative_to(paths[0])
            or paths[2].is_relative_to(paths[0]) or paths[3].is_relative_to(paths[0])
            or paths[2].is_relative_to(paths[3]) or paths[3].is_relative_to(paths[2])):
        raise ValueError('PLAN_IDENTITY_OR_PATHS_INVALID')
    namespace = 'KiranTrading-Versioned-' + day.strftime('%Y%m%d')
    names = {mode: namespace + '-' + mode for mode in ('preflight', 'poll', 'audit')}
    result = {}
    # First two slots are supervised manually; enable recurrence BEFORE its future start.
    for mode, time in (('preflight', (8, 50, 0)), ('poll', (9, 30, 30)), ('audit', (15, 40, 0))):
        at = datetime.combine(day, datetime.min.time(), tzinfo=ZoneInfo('Asia/Kolkata')).replace(
            hour=time[0], minute=time[1], second=time[2])
        node = ET.Element('Task', version='1.2', xmlns='http://schemas.microsoft.com/windows/2004/02/mit/task')
        trigger = ET.SubElement(ET.SubElement(node, 'Triggers'), 'TimeTrigger')
        if mode == 'poll':
            repeat = ET.SubElement(trigger, 'Repetition')
            ET.SubElement(repeat, 'Interval').text = 'PT5M'
            ET.SubElement(repeat, 'Duration').text = 'PT6H1M'
            ET.SubElement(repeat, 'StopAtDurationEnd').text = 'false'
        ET.SubElement(trigger, 'StartBoundary').text = at.isoformat()
        # End prevents accidental late launch; no catch-up or next-day scheduling.
        ET.SubElement(trigger, 'EndBoundary').text = at.replace(hour=15, minute=32).isoformat() if mode == 'poll' else (at + timedelta(minutes=2)).isoformat()
        ET.SubElement(trigger, 'Enabled').text = 'true'
        principal = ET.SubElement(ET.SubElement(node, 'Principals'), 'Principal', id='Owner')
        for key, value in (('UserId', sid), ('LogonType', 'InteractiveToken'), ('RunLevel', 'LeastPrivilege')):
            ET.SubElement(principal, key).text = value
        settings = ET.SubElement(node, 'Settings')
        for key, value in (('MultipleInstancesPolicy', 'IgnoreNew'), ('StartWhenAvailable', 'false'),
                           ('Enabled', 'false'), ('WakeToRun', 'false'), ('ExecutionTimeLimit', 'PT2M'),
                           ('DisallowStartIfOnBatteries', 'false'), ('StopIfGoingOnBatteries', 'false')):
            ET.SubElement(settings, key).text = value
        action = ET.SubElement(ET.SubElement(node, 'Actions', Context='Owner'), 'Exec')
        ET.SubElement(action, 'Command').text = r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
        arguments = ['-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-File', str(paths[0] / 'forward_ops_task.ps1'),
            '-PythonExecutable', str(paths[1]), '-CodeDirectory', str(paths[0]),
            '-StateRoot', str(paths[2]), '-OpsRoot', str(paths[3]),
            '-SessionDate', day.isoformat(), '-Mode', mode, '-PollTask', names['poll'], '-AuditTask', names['audit']]
        ET.SubElement(action, 'Arguments').text = subprocess.list2cmdline(arguments)
        ET.SubElement(action, 'WorkingDirectory').text = str(paths[0])
        result[names[mode]] = ET.tostring(node, encoding='unicode')  # No XML encoding declaration.
    return result


def main(argv: list[str] | None = None) -> int:
    """Explicit owner paths/SID only; print review XML, never inspect the computer."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session-date', required=True, type=date.fromisoformat)
    parser.add_argument('--owner-sid', required=True)
    parser.add_argument('--code-directory', required=True)
    parser.add_argument('--python-executable', required=True)
    parser.add_argument('--state-root', required=True)
    parser.add_argument('--ops-root', required=True)
    args = parser.parse_args(argv)
    try:
        value = plans(args.session_date, sid=args.owner_sid, code=args.code_directory,
                      python=args.python_executable, state=args.state_root, ops=args.ops_root)
        print(json.dumps({'status': 'REVIEW_ONLY_DISABLED', 'plans': value, 'tasks_changed': 0}))
        return 0
    except Exception:
        print(json.dumps({'status': 'BLOCKED', 'code': 'PLAN_IDENTITY_OR_PATHS_INVALID'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
