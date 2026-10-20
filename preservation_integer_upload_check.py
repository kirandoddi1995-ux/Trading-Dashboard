"""Exact-base preservation numeric repair gate. No private IO/commissioning."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

from programme_next_upload_check import git, safe_read, sha, unique

BASE = 'a69870ba0bc59fc206824fe6d9f1db138ae1aec0'
MANIFEST = 'PRESERVATION_INTEGER_UPLOAD.json'
VERSION = 'preservation-integer-upload-v1'
FILES = (
    'archive_preservation_inventory.py',
    'archive_preservation_witness.py',
    'tests/test_archive_preservation_witness.py',
    'tests/test_archive_preservation_upload_check.py',
    'tests/test_outcomes_private_upload_check.py',
    'PRESERVATION_COMMISSION_2026-10-20.md',
    'tests/test_preservation_integer_contract.py',
    'preservation_integer_upload_check.py',
    'tests/test_preservation_integer_upload_check.py',
    'PRESERVATION_INTEGER_REPAIR_2026-10-20.md',
    'PRESERVATION_INTEGER_UPLOAD.json',
)
MODIFIED_BASE_HASHES = {
    "archive_preservation_inventory.py": "4b274005403c9bfc3a4df1cb06a9f0e19970134a6b199cac4204414af3949bdf",
    "archive_preservation_witness.py": "fd90d64a1a8dbff203c02f0b94782f822fd302996719412eebb5cacf8a63e74c",
    "tests/test_archive_preservation_witness.py": "832147769c8690bb735451b96176a73ce9daf4ac24528c56f6d6c2b89bff1706",
    "tests/test_archive_preservation_upload_check.py": "97ae26cc0a7304681c7155dcf1370b1e0cda6d8f377c62800492631bfe3510d2",
    "tests/test_outcomes_private_upload_check.py": "2f5a8379defc60cb2af616cdae956b593097ff37f1f1588714c23d2c72f74fc6",
    "PRESERVATION_COMMISSION_2026-10-20.md": "65ed67edab1b64951b711a4b06c671a9b77eddd1730c99daccbece9bbadbbc08"
}
PREREQUISITES = {
    "programme_next_upload_check.py": "c975be41f99994b2159e1e19b699fb1b71e6699e186bb6bb19e711adfcd01a81",
    "constraints.txt": "433d34cc1146a838c792b8b417acefed300895a3543d62a295cb00c2791a7ba3",
    "ARCHIVE_PRESERVATION_UPLOAD.json": "f0aaeb5fbd843578d4ec573000f48a6f8f2c9be6176f379f56776ec0cb703d7e",
    "OUTCOMES_PRIVATE_UPLOAD.json": "56857aaaca948094a68a326527b1b89e05ebb82137e5d1fa0012909a79d05a30",
    "archive_catalog_verify.py": "f63723a83bb9ee4a39790ad064da1caf91dbb291081bf7592c0e90eea323ef61",
    "outcomes_private_container.py": "03098b9e0466fb5f38c247fcdf1a9c9b490b0b63c9c2e307f65c242a8371a110",
    "outcomes_private_worker.py": "c40f12d445a63de0d05b20e696476950563d09347f507e61c7e8f98a6e0ee0f2",
    "normal_user_test_run.py": "72a58c562beae96e2f770dff4589bd6ec2fd760fd0165e62ddd45502f3ef875d",
    "tests/sql-harness/package-lock.json": "f8a3f615f5815cef039b6f133914e724abe25117424c9a612b3c678454e1af4d",
    "scheduled_collector.py": "6be0f30152472309f3e83378f6053ed9f1a8b09e2c10be4aecef5343d7554dde",
    "nifty_session_calendar.py": "b6274191ca3399d65314d238194589482ff88c7599e52bce2517c1c0212a935b"
}


def reviewed_successor_hash(root: Path, name: str, original: str) -> str:
    """Keep old manifests immutable while checking this explicit successor's bytes.

    Not a fallback, historical repin or an uploader admission function. Only six
    named paths with exactly enrolled predecessor hashes can use the successor.
    The new staged checker additionally binds old bytes to the exact public base.
    """
    if name not in MODIFIED_BASE_HASHES:
        return original
    if original != MODIFIED_BASE_HASHES[name]:
        raise ValueError('HISTORICAL_PREDECESSOR_MISMATCH')
    value = json.loads(safe_read(root / MANIFEST), object_pairs_hook=unique)
    if (set(value) != {'version', 'base', 'files', 'prerequisites'}
            or value['version'] != VERSION or value['base'] != BASE
            or set(value['files']) != set(FILES) or value['files'][MANIFEST] is not None
            or value['prerequisites'] != PREREQUISITES):
        raise ValueError('HISTORICAL_SUCCESSOR_CONTRACT_INVALID')
    result = value['files'][name]
    if type(result) is not str or re.fullmatch('[a-f0-9]{64}', result) is None:
        raise ValueError('HISTORICAL_SUCCESSOR_HASH_REQUIRED')
    return result


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
        for name, expected in MODIFIED_BASE_HASHES.items():
            actual = sha(git(root, 'show', BASE + ':' + name))
            if actual != expected:
                failures.append(dict(rule='MODIFIED_BASE_HASH_MISMATCH', path=name, expected=expected, actual=actual))
        for name, expected in PREREQUISITES.items():
            for location, source in [('base', git(root, 'show', BASE + ':' + name)),
                                     ('index', git(root, 'show', ':' + name)), ('worktree', safe_read(root / name))]:
                actual = sha(source)
                if actual != expected:
                    failures.append(dict(rule='PREREQUISITE_HASH_MISMATCH', path=name,
                                         location=location, expected=expected, actual=actual))
        paths = set(git(root, 'diff', '--cached', '--name-status', BASE, '--').decode().splitlines())
        if paths != ({'M\t' + name for name in MODIFIED_BASE_HASHES} | {'A\t' + name for name in FILES if name not in MODIFIED_BASE_HASHES}):
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
    return {'status': 'BLOCKED' if failures else 'PRESERVATION_INTEGER_PACKAGE_VERIFIED_REQUIRES_EXACT_COMMIT_CI',
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
