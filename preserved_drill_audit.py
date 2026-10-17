"""Read-only source/recipe consistency review; never grants execution admission."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

REVIEWED_ID = '389daf12415a482eb0231443ddfd8697'
IST = timezone(timedelta(hours=5, minutes=30))
WORKER_HASH = 'fbc263471ae04fa3a38c5d2ee91add58f2d9020f0268ac6bbebb1e26ff2e25b4'
OLD_CONTROLLER_HASH = '086ee265a6d94023e9a1ddafd728dfdf005be3f035debf5c089a25383dc57503'
SOURCE_PINS = {
    'forward_session_ops.py': 'e2acaed4856bf215e64507dcd1ea45bef538de4fde9a7e18f96438b6b478490c',
    'forward_ops_host.py': '41e17a6d94ba90c19607a14d35949a555356df732f033d9e0c70996300e34885',
    'automated_development_checks.py': '54d4530d75bf61fc4e7c9a01e797a4734bd6db5a9cd740ab0b314078200d2cd7',
    'research_integrity.py': '37a2c4b372bee7f989ab196efe7020d5c39585486d9ec8e3c35709e7dbead689',
}


def safe(path: Path) -> None:
    if not path.is_absolute() or str(path).startswith(('\\\\', '//')):
        raise ValueError('LOCAL_ABSOLUTE_PATH_REQUIRED')
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise ValueError('LINK_REJECTED')


def read(path: Path) -> bytes:
    safe(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > 1024 * 1024:
        raise ValueError('BOUNDED_REGULAR_FILE_REQUIRED')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    try:
        opened = os.fstat(fd)
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino) or not stat.S_ISREG(opened.st_mode):
            raise ValueError('READ_CHANGED')
        raw = os.read(fd, 1024 * 1024 + 1)
        after = os.fstat(fd)
        safe(path)
        if (len(raw) != opened.st_size or len(raw) > 1024 * 1024
                or (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns)):
            raise ValueError('READ_CHANGED')
        return raw
    finally:
        os.close(fd)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest()


def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError('DUPLICATE_RECIPE_KEY')
        result[name] = value
    return result


def review(old_tools: Path, root: Path, identifier: str, now: datetime) -> dict[str, Any]:
    if re.fullmatch('[0-9a-f]{32}', identifier) is None:
        raise ValueError('DRILL_ID_INVALID')
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('AWARE_TIME_REQUIRED')
    safe(old_tools)
    safe(root)
    pins = {**SOURCE_PINS, 'isolated_alert_drill.py': WORKER_HASH,
            'isolated_alert_task_drill.ps1': OLD_CONTROLLER_HASH}
    for name, expected in pins.items():
        if sha(read(old_tools / name)) != expected:
            raise ValueError('OLD_PUBLIC_SOURCE_PIN_MISMATCH')
    value = json.loads(read(root / 'recipe.json'), object_pairs_hook=unique)
    if (type(value) is not dict or set(value) != {'schema', 'identifier', 'session_date', 'sources', 'worker_sha256', 'synthetic'}
            or value['schema'] != 'isolated-alert-drill-v1' or value['identifier'] != identifier
            or value['sources'] != SOURCE_PINS or value['worker_sha256'] != WORKER_HASH
            or value['synthetic'] is not True):
        raise ValueError('RECIPE_CONSISTENCY_FAILED')
    day = datetime.strptime(value['session_date'], '%Y-%m-%d').date()
    if day.isoformat() != value['session_date'] or day > now.astimezone(IST).date():
        raise ValueError('RECIPE_DATE_REVIEW_REQUIRED')
    # Metadata only, maximum17 entries; any extra artefact prevents closure review.
    entries = list(itertools.islice(root.iterdir(), 17))
    if len(entries) != 1 or entries[0].name != 'recipe.json':
        raise ValueError('EXTRA_STATE_OR_EXECUTION_WITNESS_REVIEW_REQUIRED')
    same_day = day == now.astimezone(IST).date()
    return dict(status='PRESERVED_RECIPE_AND_SOURCES_CONSISTENT_NOT_RUN_ADMISSION',
                source_integrity=True, recipe_consistency=True, recipe_authenticated=False,
                same_ist_day=same_day, historical_recipe=not same_day,
                execution_history_independently_verified=False, run_authorised=False,
                replacement_id_authorised=False, operational_writes=0, credential_reads=0,
                task_mutations=0, approval_authority=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--drill-id', required=True)
    parser.add_argument('--old-tools-root', required=True)
    parser.add_argument('--confirm-read-only', action='store_true')
    args = parser.parse_args()
    if not args.confirm_read_only:
        print(json.dumps(dict(status='PREVIEW', reads=0, writes=0, task_queries=0)))
        return 0
    try:
        if os.name != 'nt' or args.drill_id != REVIEWED_ID:
            raise ValueError('REVIEWED_WINDOWS_DRILL_REQUIRED')
        root = Path(os.environ['LOCALAPPDATA']) / 'KiranTrading' / 'AlertDrills' / args.drill_id
        result = review(Path(args.old_tools_root), root, args.drill_id, datetime.now(timezone.utc))
    except Exception as error:
        known = {'REVIEWED_WINDOWS_DRILL_REQUIRED', 'LOCAL_ABSOLUTE_PATH_REQUIRED', 'LINK_REJECTED',
                 'BOUNDED_REGULAR_FILE_REQUIRED', 'READ_CHANGED', 'DRILL_ID_INVALID', 'AWARE_TIME_REQUIRED',
                 'DUPLICATE_RECIPE_KEY', 'OLD_PUBLIC_SOURCE_PIN_MISMATCH', 'RECIPE_CONSISTENCY_FAILED',
                 'RECIPE_DATE_REVIEW_REQUIRED', 'EXTRA_STATE_OR_EXECUTION_WITNESS_REVIEW_REQUIRED'}
        reason = str(error) if type(error) is ValueError and str(error) in known else 'READ_ONLY_REVIEW_NOT_ESTABLISHED'
        print(json.dumps(dict(status='BLOCKED', reason=reason, raw_values_printed=False,
                              run_authorised=False, replacement_id_authorised=False, operational_writes=0)))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
