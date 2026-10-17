"""Synthetic alert-route drill only. No capture, clock, credentials or orders.

Runs pinned production function bodies with isolated globals, not module imports.
Native Scheduler commissioning is exclusively the reviewed PowerShell owner's step.
"""
from __future__ import annotations

import argparse
import ast
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Any, Callable
import uuid

SOURCES = {
    'forward_session_ops.py': 'e2acaed4856bf215e64507dcd1ea45bef538de4fde9a7e18f96438b6b478490c',
    'forward_ops_host.py': '41e17a6d94ba90c19607a14d35949a555356df732f033d9e0c70996300e34885',
    'automated_development_checks.py': '54d4530d75bf61fc4e7c9a01e797a4734bd6db5a9cd740ab0b314078200d2cd7',
    'research_integrity.py': '37a2c4b372bee7f989ab196efe7020d5c39585486d9ec8e3c35709e7dbead689',
}
IST = timezone(timedelta(hours=5, minutes=30))


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest()


def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('DUPLICATE_KEY')
        value[key] = item
    return value


def safe(path: Path) -> Path:
    if not path.is_absolute() or str(path).startswith(('\\\\', '//')):
        raise ValueError('LOCAL_ABSOLUTE_PATH_REQUIRED')
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise ValueError('LINK_REJECTED')
    return path


def read(path: Path) -> bytes:
    safe(path)
    # Files are private owner-created drill state or fixed reviewed public sources.
    # This is not a hostile-process sandbox. Refuse links and oversized inputs.
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > 1024*1024:
        raise ValueError('BOUNDED_REGULAR_FILE_REQUIRED')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError('READ_IDENTITY_CHANGED')
        safe(path)
        raw = bytearray()
        while len(raw) <= 1024*1024:
            chunk = os.read(fd, min(65536, 1024*1024+1-len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(fd)
        if len(raw) != opened.st_size or (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('READ_IDENTITY_CHANGED')
        return bytes(raw)
    finally:
        os.close(fd)


def root_for(identifier: str) -> Path:
    if re.fullmatch('[0-9a-f]{32}', identifier) is None:
        raise ValueError('DRILL_ID_INVALID')
    return safe(Path(os.environ['LOCALAPPDATA']) / 'KiranTrading/AlertDrills' / identifier)


def correlation_code(identifier: str) -> str:
    if re.fullmatch('[0-9a-f]{32}', identifier) is None:
        raise ValueError('DRILL_ID_INVALID')
    return ''.join(chr(ord('a') + int(value, 16)) for value in identifier[:8])


def write_new(path: Path, item: object) -> None:
    safe(path)
    with path.open('xb') as stream:
        stream.write(canonical(item)); stream.flush(); os.fsync(stream.fileno())


def allowed(now: datetime) -> bool:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('AWARE_TIME_REQUIRED')
    local = now.astimezone(IST)
    return local.weekday() >= 5 or local.hour >= 16


def load_functions() -> dict[str, Any]:
    namespace: dict[str, Any] = dict(Path=Path, Any=Any, datetime=datetime, timezone=timezone,
        json=json, os=os, tempfile=tempfile, hashlib=hashlib, uuid=uuid, re=re, subprocess=subprocess)
    for name, functions in (
            ('research_integrity.py', ('canonical', 'digest')),
            ('automated_development_checks.py', ('write_once',)),
            ('forward_ops_host.py', ('notify',)),
            ('forward_session_ops.py', ('save',))):
        raw = read(Path(__file__).resolve().parent / name)
        if sha(raw) != SOURCES[name]:
            raise ValueError('REVIEWED_SOURCE_PIN_MISMATCH')
        tree = ast.parse(raw)
        selected: list[ast.stmt] = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in functions]
        if len(selected) != len(functions):
            raise ValueError('REVIEWED_FUNCTION_MISSING')
        exec(compile(ast.Module(body=selected, type_ignores=[]), name, 'exec'), namespace)
    return namespace


def setup(identifier: str, now: datetime) -> dict[str, Any]:
    if not allowed(now):
        raise ValueError('POSTSESSION_OR_WEEKEND_REQUIRED')
    load_functions()  # Verify source pins before creating any drill state.
    root = root_for(identifier)
    root.mkdir(parents=True, exist_ok=False)
    write_new(root / 'recipe.json', dict(schema='isolated-alert-drill-v1', identifier=identifier,
        session_date=now.astimezone(IST).date().isoformat(), sources=SOURCES,
        worker_sha256=sha(read(Path(__file__).resolve())), synthetic=True))
    return dict(status='ISOLATED_DRILL_STATE_PREPARED_NOT_TASK_REGISTRATION', synthetic=True,
                correlation_code=correlation_code(identifier))


def recipe(identifier: str, now: datetime, *, current: bool = False) -> tuple[Path, dict[str, Any]]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('AWARE_TIME_REQUIRED')
    root = root_for(identifier)
    value = json.loads(read(root / 'recipe.json'), object_pairs_hook=unique)
    if (value.get('schema') != 'isolated-alert-drill-v1' or value.get('identifier') != identifier
            or value.get('sources') != SOURCES or value.get('synthetic') is not True
            or value.get('worker_sha256') != sha(read(Path(__file__).resolve()))
            or date.fromisoformat(value['session_date']) > now.astimezone(IST).date()
            or (current and (value['session_date'] != now.astimezone(IST).date().isoformat() or not allowed(now)))):
        raise ValueError('ISOLATED_DRILL_RECIPE_REVIEW_REQUIRED')
    return root, value


def worker(identifier: str, now: datetime, notifier: Callable[[str], bool] | None = None) -> dict[str, Any]:
    root, value = recipe(identifier, now, current=True)
    controller = json.loads(read(root / 'controller-attempt.json'), object_pairs_hook=unique)
    if controller.get('identifier') != identifier or controller.get('retry_allowed') is not False:
        raise ValueError('CONTROLLER_ATTEMPT_REQUIRED')
    write_new(root / 'attempt.json', dict(identifier=identifier, attempted_at=now.isoformat(), retry_allowed=False))
    functions = load_functions()
    actual_notify = functions['notify'] if notifier is None else notifier
    functions['notify'] = lambda category: actual_notify('SYNTHETIC_' + correlation_code(identifier).upper() + '_' + category)
    # Deliberate fixture failure, NOT a time query or actual failed capture.
    blocked = dict(status='BLOCKED', code='CLOCK_UNVERIFIED', stage='CLOCK_CHECK',
                   category='SYNTHETIC_FAILURE_ONLY', synthetic=True, approval_authority=False,
                   training_eligible=False, capture_writes=0)
    functions['save'](root / 'reports', date.fromisoformat(value['session_date']), blocked, visible=True)
    return dict(status='SYNTHETIC_FAILURE_ROUTED_EXPECTED_EXIT_2', synthetic=True,
                correlation_code=correlation_code(identifier),
                production_failure_verified=False, popup_seen=None, owner_acknowledged=False, capture_writes=0)


def inspect(identifier: str, now: datetime) -> dict[str, Any]:
    root, value = recipe(identifier, now)
    day = value['session_date']
    controller = json.loads(read(root / 'controller-attempt.json'), object_pairs_hook=unique)
    attempt = json.loads(read(root / 'attempt.json'), object_pairs_hook=unique)
    if (controller.get('identifier') != identifier or controller.get('retry_allowed') is not False
            or attempt.get('identifier') != identifier or attempt.get('retry_allowed') is not False):
        raise ValueError('EXACT_ATTEMPT_RECORDS_REQUIRED')
    for item, key in ((controller, 'at'), (attempt, 'attempted_at')):
        at = datetime.fromisoformat(item[key])
        if at.utcoffset() is None or at.astimezone(IST).date().isoformat() != day:
            raise ValueError('ATTEMPT_DATE_REQUIRED')
    reports: list[dict[str, Any]] = []
    report_root = safe(root / 'reports')
    with os.scandir(report_root) as entries:
        for number, entry in enumerate(entries):
            if number >= 16:
                raise ValueError('REPORT_BOUND_EXCEEDED')
            if re.fullmatch(re.escape(day) + '-[0-9a-f]{32}\\.json', entry.name):
                reports.append(json.loads(read(report_root / entry.name), object_pairs_hook=unique))
    if (len(reports) != 1 or reports[0].get('status') != 'BLOCKED'
            or reports[0].get('code') != 'CLOCK_UNVERIFIED' or reports[0].get('stage') != 'CLOCK_CHECK'
            or reports[0].get('synthetic') is not True or reports[0].get('approval_authority') is not False
            or reports[0].get('training_eligible') is not False):
        raise ValueError('EXACT_SYNTHETIC_REPORT_REQUIRED')
    # Identity is exactly the same reviewed production branch, never a capture marker.
    tokens = ['CLOCK_UNVERIFIED', 'CLOCK_CHECK', 'SYNTHETIC_FAILURE_ONLY']
    identity = hashlib.sha256(json.dumps(tokens).encode()).hexdigest()[:16]
    launch = root / 'reports' / f'{day}-v2-CLOCK_REVIEW_REQUIRED-{identity}-1.launch'
    if read(launch.with_suffix('.alert')).strip() != b'LOCAL_NOTIFICATION_LAUNCH_PENDING_NOT_DELIVERY_PROOF':
        raise ValueError('EXACT_ALERT_MARKER_REQUIRED')
    state = read(launch).strip()
    if state != b'LAUNCHED_NOT_DELIVERY_PROOF':
        raise ValueError('SYNTHETIC_LAUNCH_NOT_ACKNOWLEDGED')
    witness = json.loads(read(root / 'task-witness.json'), object_pairs_hook=unique)
    if (witness.get('identifier') != identifier or witness.get('binding_verified') is not True
            or witness.get('disabled_verified') is not True
            or type(witness.get('last_result')) is not int or witness['last_result'] != 2):
        raise ValueError('SYNTHETIC_TASK_WITNESS_REQUIRED')
    ack_path = root / 'owner-ack.json'
    acknowledged = False
    if ack_path.exists():
        ack = json.loads(read(ack_path), object_pairs_hook=unique)
        at = datetime.fromisoformat(ack['at'])
        if (ack.get('identifier') != identifier or ack.get('correlation_code') != correlation_code(identifier)
                or ack.get('provenance') != 'OWNER_ATTESTED_SYNTHETIC_POPUP_SEEN_NOT_INDEPENDENT_DELIVERY'
                or at.utcoffset() is None or at.astimezone(IST).date().isoformat() < day or at > now):
            raise ValueError('OWNER_ATTESTATION_RECORD_INVALID')
        acknowledged = True
    return dict(status='ISOLATED_FAILURE_ROUTE_ACK_RECORDED' if acknowledged else
                'ISOLATED_FAILURE_ROUTE_RECORDED_AWAITING_OWNER_ACK', synthetic=True,
                scheduler_result=2, launch_acknowledged=True, popup_seen=True if acknowledged else None,
                owner_acknowledged=acknowledged,
                correlation_code=correlation_code(identifier),
                owner_ack_provenance='OWNER_ATTESTED_NOT_INDEPENDENT_DELIVERY' if acknowledged else None,
                task_disabled_owner_witness=True, production_failure_verified=False,
                independent_delivery_verified=False, capture_writes=0)


def acknowledge(identifier: str, now: datetime, seen_code: str) -> dict[str, Any]:
    if seen_code != correlation_code(identifier):
        raise ValueError('HUMAN_SYNTHETIC_CODE_MISMATCH')
    result = inspect(identifier, now)
    write_new(root_for(identifier) / 'owner-ack.json', dict(identifier=identifier,
        correlation_code=seen_code,
        provenance='OWNER_ATTESTED_SYNTHETIC_POPUP_SEEN_NOT_INDEPENDENT_DELIVERY', at=now.isoformat()))
    return {**result, 'status': 'ISOLATED_FAILURE_ROUTE_OWNER_ACKNOWLEDGED', 'popup_seen': True,
            'owner_acknowledged': True, 'approval_authority': False, 'training_eligible': False}


def check(identifier: str, now: datetime) -> dict[str, Any]:
    recipe(identifier, now, current=True)
    load_functions()
    return dict(status='ISOLATED_DRILL_PREREQUISITES_CHECK_PASSED', writes=0, task_mutations=0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--drill-id', required=True)
    parser.add_argument('--mode', choices=('setup', 'worker', 'inspect', 'acknowledge', 'check'), default='inspect')
    parser.add_argument('--confirm-drill-only', action='store_true')
    parser.add_argument('--confirm-notification-seen', action='store_true')
    parser.add_argument('--seen-code', default='')
    args = parser.parse_args(argv)
    if not args.confirm_drill_only:
        print(json.dumps(dict(status='PREVIEW', reads=0, writes=0, task_mutations=0, capture_invocations=0)))
        return 0
    try:
        if os.name != 'nt' or tuple(__import__('sys').version_info[:3]) != (3, 13, 9):
            raise ValueError('REVIEWED_WINDOWS_PYTHON_REQUIRED')
        if args.mode == 'acknowledge' and not args.confirm_notification_seen:
            raise ValueError('HUMAN_SYNTHETIC_ACK_REQUIRED')
        now = datetime.now(timezone.utc)
        if args.mode == 'acknowledge':
            result = acknowledge(args.drill_id, now, args.seen_code)
        else:
            action = dict(setup=setup, worker=worker, inspect=inspect, check=check)[args.mode]
            result = action(args.drill_id, now)
        print(json.dumps(result))
        return 2 if args.mode == 'worker' else 0
    except Exception as error:
        reasons = {'REVIEWED_WINDOWS_PYTHON_REQUIRED', 'HUMAN_SYNTHETIC_ACK_REQUIRED',
            'HUMAN_SYNTHETIC_CODE_MISMATCH',
            'POSTSESSION_OR_WEEKEND_REQUIRED', 'DRILL_ID_INVALID', 'LINK_REJECTED',
            'REVIEWED_SOURCE_PIN_MISMATCH', 'REVIEWED_FUNCTION_MISSING',
            'ISOLATED_DRILL_RECIPE_REVIEW_REQUIRED', 'CONTROLLER_ATTEMPT_REQUIRED',
            'EXACT_ATTEMPT_RECORDS_REQUIRED', 'ATTEMPT_DATE_REQUIRED',
            'EXACT_ALERT_MARKER_REQUIRED', 'EXACT_SYNTHETIC_REPORT_REQUIRED',
            'OWNER_ATTESTATION_RECORD_INVALID',
            'SYNTHETIC_LAUNCH_NOT_ACKNOWLEDGED', 'SYNTHETIC_TASK_WITNESS_REQUIRED',
            'BOUNDED_REGULAR_FILE_REQUIRED', 'READ_IDENTITY_CHANGED', 'DUPLICATE_KEY',
            'REPORT_BOUND_EXCEEDED', 'AWARE_TIME_REQUIRED', 'LOCAL_ABSOLUTE_PATH_REQUIRED'}
        reason = str(error) if type(error) is ValueError and str(error) in reasons else (
            'EXISTING_DRILL_STATE_NO_RETRY' if isinstance(error, FileExistsError) else
            'REQUIRED_DRILL_FILE_MISSING' if isinstance(error, FileNotFoundError) else 'REDACTED_UNEXPECTED_FAILURE')
        print(json.dumps(dict(status='BLOCKED', code='ISOLATED_DRILL_STOP_REVIEW_NO_RETRY',
            stage=args.mode.upper(), reason=reason, raw_error_printed=False, capture_writes=0, approval_authority=False)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
