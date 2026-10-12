"""Exact inactive custody/alert package rehearsal in an owner's clean Git clone."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

import reviewed_upload_check as checks

MANIFEST = 'CUSTODY_ALERT_UPLOAD_2026-10-12.json'
FILES = frozenset({
    'recovery_custody_rehearsal.py', 'storage_alert_delivery.py',
    'tests/test_recovery_custody_rehearsal.py', 'tests/test_storage_alert_delivery.py',
    'custody_alert_upload_check.py', 'tests/test_custody_alert_upload.py',
    'CUSTODY_ALERT_PACKAGE_2026-10-12.md', MANIFEST})


def validate(root: Path, changed: set[str]) -> None:
    """No private JSON, extra files, staged destinations or unchecked prerequisites."""
    path = root / MANIFEST
    if path.is_symlink() or path.is_junction() or not path.is_file() or path.stat().st_size > 64 * 1024:
        raise ValueError('CONTROL_MANIFEST_INVALID')
    manifest = json.loads(path.read_bytes())
    entries = manifest['files']
    if (manifest['version'] != 'custody-alert-upload-v1'
            or len(entries) != len(FILES)
            or {e['destination'] for e in entries} != FILES
            or any(e['source'] != e['destination'] for e in entries)
            or changed - FILES):
        raise ValueError('PACKAGE_PATH_SET_INVALID')
    controls = [e for e in entries if e['destination'] == MANIFEST]
    if len(controls) != 1 or controls[0]['sha256_lf'] is not None:
        raise ValueError('CONTROL_MANIFEST_INVALID')
    checks.validate_files(root, [e for e in entries if e['destination'] != MANIFEST], changed - {MANIFEST})
    required = {'reviewed_upload_check.py', 'recovery_export.py', 'recovery_bundle.py',
                'recovery_materialization.py', 'recovery_replica_audit.py', 'catalog_receipts.py',
                'storage_capacity_watch.py', 'collector_storage_preflight.py'}
    prerequisites = manifest['prerequisites']
    if (len(prerequisites) != len(required)
            or {e['destination'] for e in prerequisites} != required
            or any(e['source'] != e['destination'] for e in prerequisites)):
        raise ValueError('PACKAGE_PREREQUISITES_INVALID')
    checks.validate_files(root, prerequisites, set())


def main(argv: list[str] | None = None) -> int:
    """Read Git metadata only; no commits, fetching, credentials or hosted writes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        if re.fullmatch('[0-9a-f]{40}', args.base) is None:
            raise ValueError('BASE_SHA_INVALID')
        root = args.root.resolve(strict=True)
        if checks.git(root, 'rev-parse', 'HEAD') != args.base:
            raise ValueError('BASE_NOT_CURRENT_HEAD')
        if Path(checks.git(root, 'rev-parse', '--show-toplevel')).resolve() != root:
            raise ValueError('CLONE_ROOT_REQUIRED')
        changed = set(checks.git(root, 'diff', '--name-only', args.base, '--').splitlines())
        changed.update(checks.git(root, 'ls-files', '--others', '--exclude-standard').splitlines())
        validate(root, changed)
        print(json.dumps({'status': 'UPLOAD_FILES_VERIFIED_REQUIRES_TESTS_AND_CI',
                          'blockers': [], 'hosted_changes': 0, 'approval_authority': False}))
        return 0
    except Exception:
        print(json.dumps({'status': 'BLOCKED', 'code': 'CUSTODY_ALERT_UPLOAD_CHECK_FAILED',
                          'hosted_changes': 0, 'approval_authority': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
