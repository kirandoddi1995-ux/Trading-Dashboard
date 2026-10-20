"""Exact-base read-only containment repair; public source checks only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

from programme_next_upload_check import git, safe_read, sha, unique

BASE = 'b18f5af7e73f37f0eb61bc1fab47bf41d4786f4b'
MANIFEST = 'OUTCOMES_READONLY_UPLOAD.json'
VERSION = 'outcomes-readonly-upload-v1'
FILES = (
    'outcomes_private_worker.py',
    'outcomes_private_container.py',
    'tests/test_outcomes_private_worker.py',
    'tests/test_outcomes_private_container.py',
    'tests/test_outcomes_private_upload_check.py',
    'tests/test_preservation_integer_upload_check.py',
    'OUTCOMES_PRIVATE_RUNBOOK.md',
    'outcomes_readonly_upload_check.py',
    'tests/test_outcomes_readonly_upload_check.py',
    'OUTCOMES_READONLY_REPAIR_2026-10-20.md',
    'OUTCOMES_READONLY_UPLOAD.json',
)
MODIFIED_BASE_HASHES = {
    "outcomes_private_worker.py": "c40f12d445a63de0d05b20e696476950563d09347f507e61c7e8f98a6e0ee0f2",
    "outcomes_private_container.py": "03098b9e0466fb5f38c247fcdf1a9c9b490b0b63c9c2e307f65c242a8371a110",
    "tests/test_outcomes_private_worker.py": "2a8ec1b24237cde87f9390b7a391d4ac4192906d505542b8485b46d453c82998",
    "tests/test_outcomes_private_container.py": "093f374f67821a3a96252625777ad1b14e3c7d7a37a5a8001e608946975b40be",
    "tests/test_outcomes_private_upload_check.py": "fed76d15f85b2ca0035e7d9a5a38ebb2d8fc3a61925d7612145ebb501f89b571",
    "tests/test_preservation_integer_upload_check.py": "58f0e30c1bd1a5100ce902f87476c6eef872a90b0bb1206156ab8b34f0fed3d5",
    "OUTCOMES_PRIVATE_RUNBOOK.md": "c0f9d2c48e89b176124fc9c9981dc208ac73205abe470505b20d30bf5d2de2af"
}
PREREQUISITES = {
    "programme_next_upload_check.py": "c975be41f99994b2159e1e19b699fb1b71e6699e186bb6bb19e711adfcd01a81",
    "constraints.txt": "433d34cc1146a838c792b8b417acefed300895a3543d62a295cb00c2791a7ba3",
    "ARCHIVE_PRESERVATION_UPLOAD.json": "f0aaeb5fbd843578d4ec573000f48a6f8f2c9be6176f379f56776ec0cb703d7e",
    "OUTCOMES_PRIVATE_UPLOAD.json": "56857aaaca948094a68a326527b1b89e05ebb82137e5d1fa0012909a79d05a30",
    "PRESERVATION_INTEGER_UPLOAD.json": "dc6e92d21a646246f477e49eaa82562b549a32832796e7d7e8e3291129aaef3f",
    "preservation_integer_upload_check.py": "874f3d902d18b688afd6b38a9c070ac5c5de12a7eb0a46eb7f642cd5284ae143",
    "archive_preservation_inventory.py": "ec497442d9e5d779584a5153db6b15bcea07fe58b2fd2c79889ac8083b69de27",
    "archive_preservation_witness.py": "6348101f6e1ed5789854ee700539e2ca078b030c7b5a500d0d9a3901e05570cc",
    "archive_catalog_verify.py": "f63723a83bb9ee4a39790ad064da1caf91dbb291081bf7592c0e90eea323ef61",
    "docker/outcomes-private.Dockerfile": "e5fd02e2045971eb2a93b13a3b147eba8072953a46abde735ecf809d6aaf3f88",
    "docker/outcomes-private.requirements.txt": "430df71779f7eecd816c5171d0d35d31133aaa21f017e364169a0e8a1ab1694b",
    ".github/workflows/outcomes-private-conformance.yml": "3ff38058bcc633385a728571424c08b2cad3a3ac502c17190deb8f1fdf2b3f01",
    "normal_user_test_run.py": "72a58c562beae96e2f770dff4589bd6ec2fd760fd0165e62ddd45502f3ef875d"
}


def reviewed_successor_hash(root: Path, name: str, original: str) -> str:
    """Keep old manifests immutable while checking this explicit successor's bytes.

    Not a fallback, historical repin or an uploader admission function. Only seven
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
    return {'status': 'BLOCKED' if failures else 'OUTCOMES_READONLY_PACKAGE_VERIFIED_REQUIRES_EXACT_COMMIT_CI',
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
