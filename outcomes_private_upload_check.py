"""Exact-base inactive Package B gate. Read-only; never commissions custody."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from programme_next_upload_check import git, safe_read, sha, unique

BASE = 'e2e1d0d797e453e2fd9d12fd0df7fb8bcb968b99'
MANIFEST = 'OUTCOMES_PRIVATE_UPLOAD.json'
VERSION = 'outcomes-private-upload-v1'
FILES = (
    "outcomes_private_worker.py",
    "outcomes_private_container.py",
    "tests/test_outcomes_private_worker.py",
    "tests/test_outcomes_private_container.py",
    "docker/outcomes-private.Dockerfile",
    "docker/outcomes-private.requirements.txt",
    ".github/workflows/outcomes-private-conformance.yml",
    "normal_user_test_run.py",
    "tests/test_normal_user_test_run.py",
    "PRESERVATION_COMMISSION_2026-10-20.md",
    "OUTCOMES_PRIVATE_RUNBOOK.md",
    "outcomes_private_upload_check.py",
    "tests/test_outcomes_private_upload_check.py",
    "OUTCOMES_PRIVATE_UPLOAD.json",
)
PREREQUISITES = {
    "programme_next_upload_check.py": "c975be41f99994b2159e1e19b699fb1b71e6699e186bb6bb19e711adfcd01a81",
    "constraints.txt": "433d34cc1146a838c792b8b417acefed300895a3543d62a295cb00c2791a7ba3",
    "archive_preservation_inventory.py": "4b274005403c9bfc3a4df1cb06a9f0e19970134a6b199cac4204414af3949bdf",
    "archive_preservation_witness.py": "fd90d64a1a8dbff203c02f0b94782f822fd302996719412eebb5cacf8a63e74c",
    "archive_catalog_verify.py": "f63723a83bb9ee4a39790ad064da1caf91dbb291081bf7592c0e90eea323ef61",
    "archive_catalog_reconcile.py": "f00ffd005e68d076ff9667a516c3d77c8d686fbd6152b88291dc455fb46b7eb8",
    "archive_recovery_review.py": "17aaeb69b32d3513d9ecfcb70ef96ee16eb7b2b8ff1a345c0339a1e54bc16c8d",
    "outcomes_footer_diagnostic.py": "3a1d87da023084a2f35269412645827774c943e21ae1dda188494db794cc565d",
    "outcomes_large_profile.py": "d7fa2493d95941dacf3a88df4e3c0755b3a7842fa167d30584ca742255b0c61f",
    "tests/sql-harness/package-lock.json": "f8a3f615f5815cef039b6f133914e724abe25117424c9a612b3c678454e1af4d"
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
    return {'status': 'BLOCKED' if failures else 'OUTCOMES_PRIVATE_PACKAGE_VERIFIED_REQUIRES_TESTS_AND_EXACT_COMMIT_CI',
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
