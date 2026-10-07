"""Owner-installed Windows scheduling adapter; preview/offline plan by default."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Iterator, cast
import uuid
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from automated_development_checks import write_once
from equity_runtime_health import clock_error, measure_clock
from forward_nifty_job import main as capture
from forward_nifty_producer import ROOT, prepare_config, validate_config
from forward_windows_credentials import load, read_secret
from nifty_previous_close import fetch, validate as validate_close
from nse_owner_close import from_file as owner_close_file
from nifty_session_calendar import cash_session
from research_integrity import IntegrityError, require_hash
from research_replay_comparison import ObservationJournal, instant

IST = ZoneInfo('Asia/Kolkata')


def now() -> datetime:
    """Separate clock seam for deterministic offline tests."""
    return datetime.now(timezone.utc)


def private_root(path: Path) -> None:
    """Resolve junctions before allowing state writes; never accept repository state."""
    if path.resolve().is_relative_to(ROOT):
        raise IntegrityError('PRIVATE_STATE_OUTSIDE_REPOSITORY_REQUIRED')


def session_paths(root: Path, day: date) -> tuple[Path, Path]:
    """Separate immutable recipes and state for every IST session."""
    private_root(root)
    base = root / day.isoformat()
    private_root(base)
    return base / 'config.json', base / 'state'


def receipt(root: Path, result: dict[str, Any]) -> None:
    """Local completion/failure evidence, not an independent watchdog notification."""
    target = root / 'scheduler-receipts'
    private_root(target)
    target.mkdir(parents=True, exist_ok=True)
    write_once(target / (uuid.uuid4().hex + '.json'), dict(result, at=now().isoformat(),
                                                        approval_authority=False, fill_evidence=False))


def prepare(root: Path, *, owner_file: Path | None = None,
            owner_download_at: str | None = None, source_attested: bool = False) -> dict[str, Any]:
    """Explicit source selection before open; no fallback or recipe overwrite."""
    timestamp = now()
    day = timestamp.astimezone(IST).date()
    path, _ = session_paths(root, day)
    opening = datetime.combine(day, datetime.min.time(), tzinfo=IST) + timedelta(hours=9, minutes=15)
    if timestamp >= opening:
        raise IntegrityError('PREOPEN_PREPARATION_REQUIRED')
    manual = owner_file is not None or owner_download_at is not None or source_attested
    if manual and (owner_file is None or owner_download_at is None or source_attested is not True):
        raise IntegrityError('OWNER_CLOSE_ATTESTATION_REQUIRED')
    if path.exists():
        if manual:
            raise IntegrityError('SESSION_ALREADY_PREPARED')
        config = json.loads(path.read_bytes())
        validate_config(config, ROOT)
        if config['version'] != 'nifty-forward-v2' or instant(config['session_open']) != opening.astimezone(timezone.utc):
            raise IntegrityError('AUTOMATIC_SOURCE_CONFIG_REQUIRED')
        return {'status': 'CONFIG_ALREADY_PREPARED', 'network_calls': 0}
    probe = cast(Callable[[], dict[str, Any]], measure_clock)()
    if cast(Callable[..., str | None], clock_error)(probe, now=now(), maximum_offset=1.0):
        raise IntegrityError('CLOCK_UNVERIFIED')
    if manual:
        assert owner_file is not None and owner_download_at is not None
        provenance = owner_close_file(owner_file, day, observed_download_at=owner_download_at,
                                      read_at=now().isoformat(), attested=source_attested, code_root=ROOT)
    else:
        import requests
        with requests.Session() as session:
            provenance = fetch(session, day, received_clock=now)
    frozen = now().isoformat()
    if instant(frozen) >= opening:
        raise IntegrityError('PREOPEN_PREPARATION_REQUIRED')
    from nse_owner_close import validate as validate_owner_close
    validator = validate_owner_close if manual else validate_close
    value = validator(provenance, day, frozen)
    config = prepare_config(day.isoformat(), value, provenance['sha256'], frozen)
    config.update(version='nifty-forward-v3-owner-file' if manual else 'nifty-forward-v2',
                  previous_close_provenance=provenance)
    validate_config(config, ROOT)
    if now() >= opening:
        raise IntegrityError('PREOPEN_PREPARATION_REQUIRED')
    path.parent.mkdir(parents=True, exist_ok=True)
    write_once(path, config)
    if manual:
        return {'status': 'CONFIG_PREPARED_OWNER_FILE', 'source_sha256': provenance['sha256'],
                'previous_close_date': provenance['close_date'], 'source_network_calls': 0,
                'source_authenticity': provenance['source_authenticity'], 'clock_check': 'PASS'}
    return {'status': 'CONFIG_PREPARED', 'source_sha256': provenance['sha256'],
            'previous_close_date': provenance['close_date'], 'network_calls': 1}


@contextmanager
def credential_environment() -> Iterator[None]:
    """Same-user OS vault, process memory only; restore existing environment even on failure."""
    values = load()
    previous = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def poll(root: Path) -> int:
    """One serial five-minute slot, at most two minutes late; no catch-up decisions."""
    timestamp = now()
    path, state = session_paths(root, timestamp.astimezone(IST).date())
    if not path.exists():
        raise IntegrityError('SESSION_NOT_PREPARED')
    config = json.loads(path.read_bytes())
    validate_config(config, ROOT)
    if config['version'] not in ('nifty-forward-v2', 'nifty-forward-v3-owner-file'):
        raise IntegrityError('AUTOMATIC_SOURCE_CONFIG_REQUIRED')
    opening, ending = instant(config['session_open']), instant(config['session_close'])
    slot = opening + timedelta(seconds=int((timestamp-opening).total_seconds() // 300)*300)
    if not opening < slot <= ending or not timedelta() <= timestamp-slot <= timedelta(seconds=120):
        raise IntegrityError('MISSED_OR_OUTSIDE_POLL_SLOT')
    with credential_environment():
        return cast(Callable[[list[str]], int], capture)(['--config', str(path), '--state', str(state), '--confirm-run'])


def audit(root: Path) -> dict[str, Any]:
    """Read-only local coverage/backup acknowledgment audit; never generate missed rows."""
    timestamp = now()
    day = timestamp.astimezone(IST).date()
    path, state = session_paths(root, day)
    if not path.exists():
        ending = datetime.combine(day, datetime.min.time(), tzinfo=IST) + timedelta(hours=15, minutes=30)
        if timestamp < ending + timedelta(minutes=5):
            raise IntegrityError('POSTSESSION_AUDIT_REQUIRED')
        if state.exists():
            raise IntegrityError('SESSION_STATE_WITHOUT_CONFIG')
        return {'status': 'SESSION_CAPTURE_INCOMPLETE', 'code': 'SESSION_NOT_PREPARED',
                'recorded_decisions': 0, 'missing_decisions': 75,
                'unavailable_decisions': 0, 'remote_acknowledged_decisions': 0,
                'approval_authority': False}
    config = json.loads(path.read_bytes())
    identity = validate_config(config, ROOT)
    if (config['version'] not in ('nifty-forward-v2', 'nifty-forward-v3-owner-file')
            or instant(config['session_open']).astimezone(IST).date() != now().astimezone(IST).date()):
        raise IntegrityError('CURRENT_AUTOMATIC_SESSION_REQUIRED')
    if now() < instant(config['session_close']) + timedelta(minutes=5):
        raise IntegrityError('POSTSESSION_AUDIT_REQUIRED')
    rows = ObservationJournal(state / 'observations.sqlite', read_only=True).read(identity, config['session_open'])
    acknowledged = 0
    for file in state.glob('receipt-*.json'):
        record = json.loads(file.read_bytes())
        if (record.get('status') == 'REMOTE_VERIFIED' and record.get('spec_hash') == identity
                and record.get('format') == 'forward-backup-manifest-v1'
                and record.get('approval_authority') is False and record.get('fill_evidence') is False
                and isinstance(record.get('data_file_id'), str) and bool(record['data_file_id'])
                and isinstance(record.get('manifest_file_id'), str) and bool(record['manifest_file_id'])
                and type(record.get('recorded_decisions')) is int and 0 <= record['recorded_decisions'] <= 75):
            require_hash(record['sha256'])
            acknowledged = max(acknowledged, record['recorded_decisions'])
    complete = len(rows) == 75 and acknowledged == 75
    return {'status': 'SESSION_CAPTURE_COMPLETE' if complete else 'SESSION_CAPTURE_INCOMPLETE',
            'recorded_decisions': len(rows), 'missing_decisions': 75-len(rows),
            'unavailable_decisions': sum(not row.available for row in rows),
            'remote_acknowledged_decisions': acknowledged, 'approval_authority': False}


def task_xml(mode: str, root: Path, start: date, owner_sid: str) -> str:
    """Generate only; owner registers disabled least-privilege interactive tasks."""
    private_root(root)
    if mode not in ('prepare', 'poll', 'audit') or re.fullmatch(r'S-\d+(?:-\d+)+', owner_sid) is None:
        raise IntegrityError('TASK_PLAN_INVALID')
    schedule = {'prepare': (9, 0, 0), 'poll': (9, 20, 30), 'audit': (15, 40, 0)}
    hour, minute, second = schedule[mode]
    boundary = datetime.combine(start, datetime.min.time(), tzinfo=IST).replace(hour=hour, minute=minute, second=second)
    task = ET.Element('Task', version='1.2', xmlns='http://schemas.microsoft.com/windows/2004/02/mit/task')
    trigger = ET.SubElement(ET.SubElement(task, 'Triggers'), 'CalendarTrigger')
    if mode == 'poll':
        repeat = ET.SubElement(trigger, 'Repetition')
        ET.SubElement(repeat, 'Interval').text = 'PT5M'
        ET.SubElement(repeat, 'Duration').text = 'PT6H11M'
        ET.SubElement(repeat, 'StopAtDurationEnd').text = 'false'
    ET.SubElement(trigger, 'StartBoundary').text = boundary.isoformat()
    ET.SubElement(trigger, 'Enabled').text = 'true'
    ET.SubElement(ET.SubElement(trigger, 'ScheduleByDay'), 'DaysInterval').text = '1'
    principal = ET.SubElement(ET.SubElement(task, 'Principals'), 'Principal', id='Owner')
    ET.SubElement(principal, 'UserId').text = owner_sid
    ET.SubElement(principal, 'LogonType').text = 'InteractiveToken'
    ET.SubElement(principal, 'RunLevel').text = 'LeastPrivilege'
    settings = ET.SubElement(task, 'Settings')
    for key, value in [('MultipleInstancesPolicy', 'IgnoreNew'), ('StartWhenAvailable', 'false'),
                       ('DisallowStartIfOnBatteries', 'false'), ('StopIfGoingOnBatteries', 'false'),
                       ('Enabled', 'false'), ('WakeToRun', 'false'), ('ExecutionTimeLimit', 'PT2M')]:
        ET.SubElement(settings, key).text = value
    execute = ET.SubElement(ET.SubElement(task, 'Actions', Context='Owner'), 'Exec')
    ET.SubElement(execute, 'Command').text = str(ROOT / '.venv' / 'Scripts' / 'python.exe')
    # Windows argv quoting: no user-controlled text is embedded in a shell script.
    import subprocess
    ET.SubElement(execute, 'Arguments').text = subprocess.list2cmdline([
        str(ROOT / 'forward_nifty_schedule.py'), '--root', str(root.resolve()), '--mode', mode, '--confirm-run'])
    ET.SubElement(execute, 'WorkingDirectory').text = str(ROOT)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(task, encoding='unicode')


def main(argv: list[str] | None = None) -> int:
    """Offline preview by default; explicit confirmation required for any network/vault access."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--mode', choices=['prepare', 'poll', 'audit', 'plan'], default='plan')
    parser.add_argument('--confirm-run', action='store_true')
    parser.add_argument('--owner-close-file', type=Path)
    parser.add_argument('--owner-download-at', help='Actual owner-observed download time with timezone')
    parser.add_argument('--attest-nse-source', action='store_true',
                        help='Confirm direct official URL download and unmodified CSV; not independent verification')
    plans_mode = parser.add_mutually_exclusive_group()
    plans_mode.add_argument('--write-task-plans', action='store_true')
    plans_mode.add_argument('--verify-task-plans', action='store_true')
    parser.add_argument('--start-date')
    parser.add_argument('--owner-sid')
    args = parser.parse_args(argv)
    try:
        private_root(args.root)
        if args.write_task_plans or args.verify_task_plans:
            if (args.confirm_run or args.mode != 'plan' or not args.start_date or not args.owner_sid
                    or args.owner_close_file or args.owner_download_at or args.attest_nse_source):
                raise IntegrityError('TASK_PLAN_ARGUMENTS_REQUIRED')
            start = date.fromisoformat(args.start_date)
            plans = args.root / 'task-plans'
            private_root(plans)
            if args.write_task_plans:
                plans.mkdir(parents=True, exist_ok=True)
            for mode in ('prepare', 'poll', 'audit'):
                xml = task_xml(mode, args.root, start, args.owner_sid)
                path = plans / (mode + '.xml')
                if args.verify_task_plans:
                    if path.read_text(encoding='utf-8') != xml:
                        raise IntegrityError('TASK_PLAN_MISMATCH')
                else:
                    with path.open('x', encoding='utf-8') as stream:
                        stream.write(xml)
            print(json.dumps({'status': 'TASK_PLANS_VERIFIED_DISABLED' if args.verify_task_plans else 'TASK_PLANS_WRITTEN_DISABLED',
                              'network_calls': 0, 'credential_reads': 0}))
            return 0
        if not args.confirm_run:
            print(json.dumps({'status': 'PREVIEW', 'network_calls': 0, 'credential_reads': 0,
                              'approval_authority': False}))
            return 0
        if args.mode != 'prepare' and (args.owner_close_file or args.owner_download_at or args.attest_nse_source):
            raise IntegrityError('OWNER_CLOSE_PREPARE_ONLY')
        definition = cast(Callable[[date], dict[str, Any]], cash_session)(now().astimezone(IST).date())
        if definition['kind'] != 'REGULAR':
            print(json.dumps({'status': 'SKIPPED_' + definition['kind'], 'network_calls': 0}))
            return 0
        if args.mode == 'prepare':
            if read_secret('FORWARD_CAPTURE_LICENSE_ACK') != 'true':
                raise IntegrityError('LICENSE_ACK_REQUIRED')
            result = prepare(args.root, owner_file=args.owner_close_file,
                             owner_download_at=args.owner_download_at,
                             source_attested=args.attest_nse_source)
        elif args.mode == 'poll':
            code = poll(args.root)
            result = {'status': 'POLL_COMPLETED' if code == 0 else 'POLL_BLOCKED', 'exit_code': code}
            receipt(args.root, result)
            return code
        elif args.mode == 'audit':
            result = audit(args.root)
        else:
            raise IntegrityError('EXECUTION_MODE_REQUIRED')
        receipt(args.root, result)
        print(json.dumps(dict(result, approval_authority=False)))
        return 1 if result['status'] == 'SESSION_CAPTURE_INCOMPLETE' else 0
    except Exception as error:
        allowed = {'CLOCK_UNVERIFIED', 'PREOPEN_PREPARATION_REQUIRED', 'NSE_CLOSE_UNAVAILABLE',
                   'MISSED_OR_OUTSIDE_POLL_SLOT', 'PRIVATE_CREDENTIAL_REQUIRED', 'POSTSESSION_AUDIT_REQUIRED',
                   'NSE_CLOSE_INVALID', 'NSE_CLOSE_SIZE_INVALID', 'NSE_CLOSE_SCHEMA_INVALID', 'NSE_CLOSE_ROW_INVALID',
                   'NSE_CLOSE_DATE_MISMATCH', 'NSE_CLOSE_PRICE_INVALID', 'NSE_CLOSE_UNIQUE_INDEX_REQUIRED',
                   'NSE_CLOSE_PROVENANCE_INVALID', 'NSE_CLOSE_PROVENANCE_MISMATCH', 'NSE_CLOSE_CONFIG_MISMATCH',
                   'NSE_CLOSE_NUMERIC_PRECISION_INVALID', 'PRIVATE_CREDENTIAL_CONFIG_INVALID'}
        allowed.update({'LICENSE_ACK_REQUIRED', 'SESSION_NOT_PREPARED', 'SESSION_STATE_WITHOUT_CONFIG',
                        'NSE_CLOSE_TRANSPORT_UNAVAILABLE', 'FORWARD_CONFIG_MISMATCH',
                        'AUTOMATIC_SOURCE_CONFIG_REQUIRED', 'CURRENT_AUTOMATIC_SESSION_REQUIRED'})
        allowed.update({'OWNER_CLOSE_ATTESTATION_REQUIRED', 'OWNER_CLOSE_PREPARE_ONLY',
                        'OWNER_CLOSE_PROVENANCE_INVALID', 'OWNER_CLOSE_TIMING_INVALID',
                        'OWNER_CLOSE_BYTES_MISMATCH', 'SESSION_ALREADY_PREPARED',
                        'LOCAL_PRIVATE_FILE_REQUIRED', 'SOURCE_OUTSIDE_CODE_FOLDER_REQUIRED'})
        failure_code = str(error) if isinstance(error, IntegrityError) and str(error) in allowed else 'SCHEDULER_BLOCKED'
        result = {'status': 'BLOCKED', 'code': failure_code, 'stage': args.mode,
                  'approval_authority': False}
        if args.confirm_run:
            try:
                receipt(args.root, result)
            except Exception:
                pass
        print(json.dumps(result))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
