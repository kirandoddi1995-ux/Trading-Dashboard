"""Exact-base staged Package A gate. Read-only; never commissions custody."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from programme_next_upload_check import git, safe_read, sha, unique

BASE = '1175e5515de0f9b7f6a682cdddda9f2f4a94eb4a'
MANIFEST = 'ARCHIVE_PRESERVATION_UPLOAD.json'
VERSION = 'archive-preservation-upload-v1'
FILES = ('archive_preservation_inventory.py', 'archive_preservation_witness.py',
         'tests/test_archive_preservation_inventory.py', 'tests/test_archive_preservation_witness.py',
         'archive_preservation_upload_check.py', 'tests/test_archive_preservation_upload_check.py',
         'ARCHIVE_PRESERVATION_RUNBOOK.md', MANIFEST)
PREREQUISITES = {
    'programme_next_upload_check.py': 'c975be41f99994b2159e1e19b699fb1b71e6699e186bb6bb19e711adfcd01a81',
    'archive_catalog_verify.py': 'f63723a83bb9ee4a39790ad064da1caf91dbb291081bf7592c0e90eea323ef61',
    'constraints.txt': '433d34cc1146a838c792b8b417acefed300895a3543d62a295cb00c2791a7ba3',
}


def check(root: Path, base: str) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    try:
        if base != BASE:
            raise ValueError('EXACT_BASE_REQUIRED')
        if git(root, 'rev-parse', 'HEAD').decode().strip() != BASE:
            raise ValueError('EXACT_BASE_REQUIRED')
        if Path(git(root, 'rev-parse', '--show-toplevel').decode().strip()).resolve() != root.resolve():
            raise ValueError('CHECKOUT_ROOT_REQUIRED')
        raw = safe_read(root / MANIFEST)
        value = json.loads(raw, object_pairs_hook=unique)
        if (set(value) != {'version', 'base', 'files', 'prerequisites'} or value['version'] != VERSION
                or value['base'] != BASE or set(value['files']) != set(FILES)
                or value['files'][MANIFEST] is not None or value['prerequisites'] != PREREQUISITES):
            raise ValueError('MANIFEST_CONTRACT_INVALID')
        for name in FILES:
            if name == MANIFEST:
                continue
            actual = sha(safe_read(root / name))
            staged = sha(git(root, 'show', ':' + name))
            expected = value['files'][name]
            if actual != expected or staged != expected:
                failures.append(dict(rule='PAYLOAD_HASH_MISMATCH', path=name, expected=expected, actual=actual, staged=staged))
        for name, expected in PREREQUISITES.items():
            for location, source in [('base', git(root, 'show', BASE + ':' + name)),
                                     ('index', git(root, 'show', ':' + name)), ('worktree', safe_read(root / name))]:
                actual = sha(source)
                if actual != expected:
                    failures.append(dict(rule='PREREQUISITE_HASH_MISMATCH', path=name,
                                         location=location, expected=expected, actual=actual))
        paths = set(git(root, 'diff', '--cached', '--name-status', BASE, '--').decode().splitlines())
        if paths != {'A\t' + name for name in FILES}:
            raise ValueError('EXACT_NEW_PATHS_REQUIRED')
        entries = git(root, 'ls-files', '--stage', '--', *FILES).decode().splitlines()
        if len(entries) != len(FILES) or any(not row.startswith('100644 ') or ' 0\t' not in row for row in entries):
            raise ValueError('REGULAR_STAGE_ZERO_REQUIRED')
        if git(root, 'diff', '--name-only', '--').strip() or git(root, 'ls-files', '--others', '--exclude-standard').strip():
            raise ValueError('UNSTAGED_OR_UNTRACKED_FILES')
        if git(root, 'show', ':' + MANIFEST) != raw:
            raise ValueError('MANIFEST_INDEX_MISMATCH')
    except Exception as error:
        allowed = {'EXACT_BASE_REQUIRED', 'CHECKOUT_ROOT_REQUIRED', 'MANIFEST_CONTRACT_INVALID',
                   'EXACT_NEW_PATHS_REQUIRED', 'REGULAR_STAGE_ZERO_REQUIRED', 'UNSTAGED_OR_UNTRACKED_FILES',
                   'MANIFEST_INDEX_MISMATCH', 'DUPLICATE_MANIFEST_KEY', 'PACKAGE_LINK_REJECTED',
                   'GIT_READ_FAILED', 'BOUNDED_REGULAR_FILE_REQUIRED', 'PUBLIC_FILE_IDENTITY_CHANGED'}
        failures.append({'rule': str(error) if type(error) is ValueError and str(error) in allowed else 'PACKAGE_READ_FAILED'})
    return {'status': 'BLOCKED' if failures else 'PRESERVATION_PACKAGE_VERIFIED_REQUIRES_TESTS_AND_EXACT_COMMIT_CI',
            'failures': failures, 'hosted_changes': 0, 'run_authorised': False,
            'custody_verified': False, 'deletion_authorised': False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    args = parser.parse_args()
    result = check(Path.cwd(), args.base)
    print(json.dumps(result))
    return 2 if result['failures'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
