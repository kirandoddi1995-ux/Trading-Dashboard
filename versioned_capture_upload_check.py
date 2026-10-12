"""Exact additive capture package; read-only clean-clone rehearsal."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

import reviewed_upload_check as checks

MANIFEST = 'VERSIONED_CAPTURE_UPLOAD_2026-10-12.json'
FILES = frozenset({'forward_versioned_producer.py', 'forward_versioned_capture.py',
    'versioned_capture_upload_check.py', 'tests/test_forward_versioned_producer.py',
    'tests/test_forward_versioned_capture.py', 'tests/test_versioned_capture_upload.py',
    'VERSIONED_CAPTURE_2026-10-12.md', MANIFEST})
PREREQUISITES = frozenset({'reviewed_upload_check.py', 'forward_revision_policy.py',
    'forward_revision_evidence.py', 'forward_revision_quarantine.py',
    'forward_nifty_producer.py', 'forward_nifty_job.py', 'forward_nifty_schedule.py'})


def validate(root: Path, changed: set[str]) -> None:
    """Reject unexpected/private files, wrong destinations or stale dependencies."""
    path = root / MANIFEST
    if path.is_symlink() or path.is_junction() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError('MANIFEST_INVALID')
    manifest = json.loads(path.read_bytes())
    entries = manifest['files']
    if (manifest['version'] != 'versioned-capture-upload-v1'
            or len(entries) != len(FILES) or {e['destination'] for e in entries} != FILES
            or any(e['source'] != e['destination'] for e in entries) or changed - FILES):
        raise ValueError('PACKAGE_PATHS_INVALID')
    control = [e for e in entries if e['destination'] == MANIFEST]
    if len(control) != 1 or control[0]['sha256_lf'] is not None:
        raise ValueError('MANIFEST_INVALID')
    checks.validate_files(root, [e for e in entries if e['destination'] != MANIFEST], changed - {MANIFEST})
    dependencies = manifest['prerequisites']
    if (len(dependencies) != len(PREREQUISITES)
            or {e['destination'] for e in dependencies} != PREREQUISITES
            or any(e['source'] != e['destination'] for e in dependencies)):
        raise ValueError('PREREQUISITES_INVALID')
    checks.validate_files(root, dependencies, set())


def main(argv: list[str] | None = None) -> int:
    """No Git writes, remote fetching, credential reads or task changes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        if (re.fullmatch('[0-9a-f]{40}', args.base) is None
                or checks.git(root, 'rev-parse', 'HEAD') != args.base
                or Path(checks.git(root, 'rev-parse', '--show-toplevel')).resolve() != root):
            raise ValueError('EXACT_CLEAN_CLONE_BASE_REQUIRED')
        changed = set(checks.git(root, 'diff', '--name-only', args.base, '--').splitlines())
        changed.update(checks.git(root, 'ls-files', '--others', '--exclude-standard').splitlines())
        validate(root, changed)
        print(json.dumps({'status': 'UPLOAD_FILES_VERIFIED_REQUIRES_TESTS_AND_CI',
                          'blockers': [], 'hosted_changes': 0, 'approval_authority': False}))
        return 0
    except Exception:
        print(json.dumps({'status': 'BLOCKED', 'code': 'VERSIONED_CAPTURE_UPLOAD_CHECK_FAILED',
                          'hosted_changes': 0, 'approval_authority': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
