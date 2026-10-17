"""Exact-base, read-only upload gate for the isolated SID repair."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from programme_next_upload_check import git, safe_read, sha, unique

BASE = 'd2da7bb90f092dc53be9e5b5bf5875799108d123'
MANIFEST = 'ISOLATED_IDENTITY_UPLOAD_2026-10-17.json'
MODIFIED = {
    'isolated_alert_task_drill.ps1': '086ee265a6d94023e9a1ddafd728dfdf005be3f035debf5c089a25383dc57503',
    'tests/test_isolated_alert_drill.py': '380a4e32942ca4454f221eabdf83fe15b9ac8d261919f10839e18d28ae635fc7',
    'ISOLATED_ALERT_DRILL_RUNBOOK_2026-10-17.md': '52417d49cc0625c9847c5edab36991b4812a151b73eb6b5477d297ca174df507',
    'PROGRAMME_NEXT_UPLOAD_2026-10-17.json': '42e0196109de47bfaf719f1b3afb79912a09efa6f87cf39d57073c414d9dbd6e',
}
PREREQUISITES = {
    'programme_next_upload_check.py': 'c975be41f99994b2159e1e19b699fb1b71e6699e186bb6bb19e711adfcd01a81',
    'isolated_alert_drill.py': 'fbc263471ae04fa3a38c5d2ee91add58f2d9020f0268ac6bbebb1e26ff2e25b4',
}
FILES = (*MODIFIED, 'isolated_alert_reconcile.ps1', 'tests/test_isolated_alert_identity.py',
         'isolated_identity_upload_check.py', 'tests/test_isolated_identity_upload_check.py',
         'ISOLATED_ALERT_IDENTITY_REPAIR_2026-10-17.md', MANIFEST)


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
        manifest = json.loads(raw, object_pairs_hook=unique)
        hashes = manifest['files']
        if (manifest.get('base') != BASE or manifest.get('version') != 'isolated-identity-upload-v1'
                or set(hashes) != set(FILES) or hashes[MANIFEST] is not None
                or manifest.get('modified_base_files') != MODIFIED
                or manifest.get('prerequisites') != PREREQUISITES):
            raise ValueError('MANIFEST_CONTRACT_INVALID')
        for name, expected in MODIFIED.items():
            actual = sha(git(root, 'show', BASE + ':' + name))
            if actual != expected:
                failures.append(dict(rule='BASE_HASH_MISMATCH', path=name, expected=expected, actual=actual))
        for name in FILES:
            if name == MANIFEST:
                continue
            actual = sha(safe_read(root / name))
            staged = sha(git(root, 'show', ':' + name))
            expected = hashes[name]
            if expected != actual or expected != staged:
                failures.append(dict(rule='PAYLOAD_HASH_MISMATCH', path=name, expected=expected, actual=actual, staged=staged))
        for name, expected in PREREQUISITES.items():
            for location, value in [('base', git(root, 'show', BASE + ':' + name)),
                                    ('index', git(root, 'show', ':' + name)), ('worktree', safe_read(root / name))]:
                actual = sha(value)
                if actual != expected:
                    failures.append(dict(rule='PREREQUISITE_HASH_MISMATCH', path=name, location=location,
                                         expected=expected, actual=actual))
        wanted = {('M' if name in MODIFIED else 'A') + '\t' + name for name in FILES}
        if set(git(root, 'diff', '--cached', '--name-status', BASE, '--').decode().splitlines()) != wanted:
            raise ValueError('EXACT_STAGED_PATHS_AND_TYPES_REQUIRED')
        entries = git(root, 'ls-files', '--stage', '--', *FILES).decode().splitlines()
        if len(entries) != len(FILES) or any(not x.startswith('100644 ') or ' 0\t' not in x for x in entries):
            raise ValueError('REGULAR_STAGE_ZERO_FILES_REQUIRED')
        if git(root, 'diff', '--name-only', '--').strip() or git(root, 'ls-files', '--others', '--exclude-standard').strip():
            raise ValueError('UNSTAGED_OR_UNTRACKED_FILES')
        if git(root, 'show', ':' + MANIFEST) != raw:
            raise ValueError('MANIFEST_INDEX_WORKTREE_MISMATCH')
    except Exception as error:
        allowed = {'EXACT_BASE_REQUIRED', 'CHECKOUT_ROOT_REQUIRED', 'MANIFEST_CONTRACT_INVALID',
                   'EXACT_STAGED_PATHS_AND_TYPES_REQUIRED', 'REGULAR_STAGE_ZERO_FILES_REQUIRED',
                   'UNSTAGED_OR_UNTRACKED_FILES', 'MANIFEST_INDEX_WORKTREE_MISMATCH',
                   'PACKAGE_LINK_REJECTED', 'DUPLICATE_MANIFEST_KEY', 'GIT_READ_FAILED',
                   'BOUNDED_REGULAR_FILE_REQUIRED', 'PUBLIC_FILE_IDENTITY_CHANGED'}
        failures.append(dict(rule=str(error) if type(error) is ValueError and str(error) in allowed else 'PACKAGE_READ_FAILED'))
    return dict(status='BLOCKED' if failures else 'IDENTITY_PACKAGE_VERIFIED_REQUIRES_TESTS_AND_EXACT_COMMIT_CI',
                failures=failures, task_mutations=0, hosted_changes=0, retry_authorised=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    result = check(Path.cwd(), parser.parse_args().base)
    print(json.dumps(result))
    return 2 if result['failures'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
