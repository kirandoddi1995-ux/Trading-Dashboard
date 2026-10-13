"""Read-only exact operations package, with public path/hash failure diagnostics."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, cast

from overnight_upload_check import pairs
from reviewed_upload_check import git
from release_verification import release_members

MANIFEST = 'FORWARD_OPERATIONS_UPLOAD_2026-10-13.json'
FILES = ('forward_session_ops.py', 'forward_ops_host.py', 'forward_ops_plan.py',
    'forward_ops_task.ps1', 'forward_ops_upload_check.py', 'tests/test_forward_session_ops.py',
    'tests/test_forward_ops_plan.py', 'tests/test_forward_ops_upload_check.py',
    'FORWARD_OPERATIONS_UPLOAD_2026-10-13.md', MANIFEST)
SEEDS = ('forward_session_ops.py', 'forward_ops_host.py', 'forward_ops_plan.py',
         'forward_ops_upload_check.py')


def source(root: Path, name: str) -> Path:
    """Public Python/explicit package only; reject links, private names and large files."""
    if name not in FILES and re.fullmatch(r'(?:tests/)?[A-Za-z0-9_]+\.py', name) is None:
        raise ValueError('PUBLIC_PATH_REQUIRED')
    if name != 'managed_secrets.py' and any(s in name.lower() for s in ('secret', 'token')):
        raise ValueError('PUBLIC_PATH_REQUIRED')
    current = root
    for part in name.split('/'):
        current /= part
        if current.is_symlink() or current.is_junction():
            raise ValueError('SOURCE_LINK_REJECTED')
    if not current.is_file() or current.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('SOURCE_MISSING_OR_TOO_LARGE')
    return current


def verify(root: Path, changed: set[str]) -> list[dict[str, str]]:
    """Pins include the current complete local import closure; none may be omitted."""
    manifest: Any = json.loads(source(root, MANIFEST).read_bytes(), object_pairs_hook=pairs)
    if (not isinstance(manifest, dict) or set(manifest) != {'version', 'files', 'prerequisites'}
            or manifest['version'] != 'forward-operations-reviewed-v1' or changed != set(FILES)):
        raise ValueError('EXACT_PACKAGE_REQUIRED')
    required = set(cast(Callable[[Path, tuple[str, ...]], list[str]], release_members)(root, SEEDS)) - set(FILES)
    required.add('tests/test_overnight_capture_audit.py')
    failures = []
    for key, names in (('files', set(FILES)), ('prerequisites', required)):
        entries = manifest[key]
        if (not isinstance(entries, list) or not entries or any(not isinstance(e, dict)
                or set(e) != {'destination', 'sha256_lf'} for e in entries)
                or len(entries) != len(names) or {e['destination'] for e in entries} != names):
            raise ValueError('EXACT_PINS_REQUIRED')
        for item in entries:
            name, expected = item['destination'], item['sha256_lf']
            if name == MANIFEST and expected is None:
                continue
            if not isinstance(expected, str) or re.fullmatch('[0-9a-f]{64}', expected) is None:
                raise ValueError('MANIFEST_HASH_INVALID')
            actual = hashlib.sha256(source(root, name).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
            if actual != expected:
                failures.append({'path': name, 'expected': expected, 'actual': actual})
    return failures


def main(argv: list[str] | None = None) -> int:
    """No Git writes; base/index/working tree and closure must all agree."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        if re.fullmatch('[0-9a-f]{40}', args.base) is None:
            raise ValueError('BASE_SHA_INVALID')
        if any(p.is_symlink() or p.is_junction() for p in (args.root, *args.root.parents)):
            raise ValueError('CLONE_ROOT_REQUIRED')
        root = args.root.resolve(strict=True)
        if git(root, 'rev-parse', 'HEAD') != args.base:
            raise ValueError('BASE_NOT_CURRENT_HEAD')
        if Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != root:
            raise ValueError('CLONE_ROOT_REQUIRED')
        if git(root, 'diff', '--name-only', '--'):
            raise ValueError('STAGE_THEN_RECHECK')
        changed = set(git(root, 'diff', '--name-only', args.base, '--').splitlines())
        changed.update(git(root, 'ls-files', '--others', '--exclude-standard').splitlines())
        failures = verify(root, changed)
        print(json.dumps({'status': 'BLOCKED' if failures else 'UPLOAD_FILES_VERIFIED_REQUIRES_TESTS_AND_CI',
                          'failures': failures, 'hosted_changes': 0}))
        return 2 if failures else 0
    except Exception as error:
        safe = {'BASE_SHA_INVALID', 'CLONE_ROOT_REQUIRED', 'BASE_NOT_CURRENT_HEAD',
                'STAGE_THEN_RECHECK', 'EXACT_PACKAGE_REQUIRED', 'EXACT_PINS_REQUIRED',
                'MANIFEST_HASH_INVALID', 'PUBLIC_PATH_REQUIRED', 'SOURCE_LINK_REJECTED',
                'SOURCE_MISSING_OR_TOO_LARGE', 'MANIFEST_DUPLICATE_KEY'}
        print(json.dumps({'status': 'BLOCKED', 'rule': str(error) if isinstance(error, ValueError)
            and str(error) in safe else 'UPLOAD_REVIEW_REQUIRED', 'hosted_changes': 0}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
