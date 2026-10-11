"""Offline exact-file upload rehearsal against the owner's actual clean Git base."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any

MANIFEST = 'REMAINING_UPLOADS_2026-10-08.json'
FOUNDATION_MANIFEST = 'STORAGE_FOUNDATION_UPLOAD_2026-10-11.json'
REPAIR_MANIFEST = 'STORAGE_NATIVE_REPAIR_UPLOAD_2026-10-11.json'
LEDGER_MANIFEST = 'STORAGE_NATIVE_LEDGER_UPLOAD_2026-10-11.json'
NATIVE_WORKFLOW = '.github/workflows/storage-native-conformance.yml'


def relative(value: object) -> str:
    """Allow explicit public source destinations only, never private/link paths."""
    if not isinstance(value, str):
        raise ValueError('PATH_INVALID')
    path = PurePosixPath(value)
    if (path.is_absolute() or '..' in path.parts or ':' in value or '\\' in value
            or value != path.as_posix()
            or (any(part.startswith('.') for part in path.parts) and value != NATIVE_WORKFLOW)
            or (path.suffix not in ('.py', '.md', '.sql', '.json') and value != NATIVE_WORKFLOW)
            or (path.suffix == '.json' and value not in (MANIFEST, FOUNDATION_MANIFEST, REPAIR_MANIFEST, LEDGER_MANIFEST))):
        raise ValueError('PATH_INVALID')
    return value


def checked_file(root: Path, name: str) -> Path:
    """Reject symlinks and junctions before opening allowlisted public sources."""
    path = root
    for part in PurePosixPath(relative(name)).parts:
        path /= part
        if path.is_symlink() or path.is_junction():
            raise ValueError('SOURCE_LINK_REJECTED')
    if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('SOURCE_MISSING_OR_TOO_LARGE')
    return path


def validate_files(root: Path, entries: list[dict[str, Any]], changed: set[str]) -> None:
    """All expected files must match; no other public changed path may sneak in."""
    names = [relative(entry['destination']) for entry in entries]
    if not names or len(names) != len(set(names)) or changed - set(names):
        raise ValueError('CHANGED_PATH_SET_INVALID')
    for entry in entries:
        path = checked_file(root, entry['destination'])
        expected = entry['sha256_lf']
        if entry['destination'] in (MANIFEST, FOUNDATION_MANIFEST, REPAIR_MANIFEST, LEDGER_MANIFEST) and expected is None:
            continue  # The reviewed control manifest cannot hash itself.
        if not isinstance(expected, str) or re.fullmatch(r'[0-9a-f]{64}', expected) is None:
            raise ValueError('MANIFEST_HASH_INVALID')
        actual = hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
        if actual != expected:
            raise ValueError('SOURCE_HASH_MISMATCH')


def git(root: Path, *args: str) -> str:
    """Read Git metadata only; never commit, stage, fetch, push or print stderr."""
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                            text=True, encoding='utf-8', errors='strict', timeout=20, check=False)
    if result.returncode != 0:
        raise ValueError('GIT_READ_FAILED')
    return result.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    """Capture base before copying; exact-tree rehearsal remains separate from CI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group', required=True, choices=('capture', 'storage', 'foundation', 'native_repair', 'native_ledger'))
    parser.add_argument('--manifest', choices=(MANIFEST, FOUNDATION_MANIFEST, REPAIR_MANIFEST, LEDGER_MANIFEST), default=MANIFEST)
    parser.add_argument('--base', required=True)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        if re.fullmatch(r'[0-9a-f]{40}', args.base) is None:
            raise ValueError('BASE_SHA_INVALID')
        root = args.root.resolve(strict=True)
        if git(root, 'rev-parse', 'HEAD') != args.base:
            raise ValueError('BASE_NOT_CURRENT_HEAD')
        if Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != root:
            raise ValueError('CLONE_ROOT_REQUIRED')
        manifest = json.loads(checked_file(root, args.manifest).read_bytes())
        expected_version = {MANIFEST: 'remaining-uploads-v1',
                            FOUNDATION_MANIFEST: 'storage-foundation-upload-v1',
                            REPAIR_MANIFEST: 'storage-native-repair-upload-v1',
                            LEDGER_MANIFEST: 'storage-native-ledger-upload-v1'}[args.manifest]
        allowed_groups = {MANIFEST: ('capture', 'storage'),
                          FOUNDATION_MANIFEST: ('foundation',), REPAIR_MANIFEST: ('native_repair',),
                          LEDGER_MANIFEST: ('native_ledger',)}
        if (manifest.get('version') != expected_version
                or args.group not in allowed_groups[args.manifest]):
            raise ValueError('MANIFEST_VERSION_INVALID')
        changed = set(git(root, 'diff', '--name-only', args.base, '--').splitlines())
        changed.update(git(root, 'ls-files', '--others', '--exclude-standard').splitlines())
        validate_files(root, manifest['groups'][args.group], changed)
        prerequisites = manifest.get('prerequisites', {}).get(args.group, [])
        if prerequisites:
            validate_files(root, prerequisites, set())
        print(json.dumps({'status': 'UPLOAD_FILES_VERIFIED_REQUIRES_TESTS_AND_CI',
                          'group': args.group, 'base': args.base, 'blockers': [],
                          'hosted_changes': 0, 'approval_authority': False}))
        return 0
    except Exception as error:
        codes = {'PATH_INVALID', 'SOURCE_LINK_REJECTED', 'SOURCE_MISSING_OR_TOO_LARGE',
                 'CHANGED_PATH_SET_INVALID', 'MANIFEST_HASH_INVALID', 'SOURCE_HASH_MISMATCH',
                 'GIT_READ_FAILED', 'BASE_SHA_INVALID', 'BASE_NOT_CURRENT_HEAD',
                 'CLONE_ROOT_REQUIRED', 'MANIFEST_VERSION_INVALID'}
        code = str(error) if type(error) is ValueError and str(error) in codes else 'UPLOAD_CHECK_FAILED'
        print(json.dumps({'status': 'BLOCKED', 'code': code, 'approval_authority': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
