"""Exact-base additive recovery-contract upload gate; public source IO only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from programme_next_upload_check import git, safe_read, sha, unique

BASE = 'eb58dc2bdc29fe32ef2bc04df9f85ab381ed8d7f'
VERSION = 'recovery-contract-upload-v1'
MANIFEST = 'RECOVERY_CONTRACT_UPLOAD.json'
FILES = ('archive_recovery_binding.py', 'archive_restore_policy.py',
    'sql/recovery_backup_facts_read_only.sql',
    'tests/test_archive_recovery_binding.py', 'tests/test_archive_restore_policy.py',
    'tests/test_recovery_backup_facts_sql.py', 'recovery_contract_upload_check.py',
    'tests/test_recovery_contract_upload_check.py',
    'RECOVERY_CONTRACT_HANDOFF_2026-10-20.md', MANIFEST)
PREREQUISITES = {
    'programme_next_upload_check.py': 'c975be41f99994b2159e1e19b699fb1b71e6699e186bb6bb19e711adfcd01a81',
    'archive_preservation_witness.py': '6348101f6e1ed5789854ee700539e2ca078b030c7b5a500d0d9a3901e05570cc',
    'archive_preservation_inventory.py': 'ec497442d9e5d779584a5153db6b15bcea07fe58b2fd2c79889ac8083b69de27',
    'archive_catalog_verify.py': 'f63723a83bb9ee4a39790ad064da1caf91dbb291081bf7592c0e90eea323ef61',
    'outcomes_private_container.py': '8cba58d494b9cc2ccc13399a71a48d3458b05ddfc4f95d99d11994763c19e5fa',
    'outcomes_private_worker.py': 'cbbe1f72d4249448679576462999dc3d5f488e7a8f33447e4905c8ac98f94340',
    'drive_archive.py': '47bae109d49a43408fbe2cd3176a974d49e997442ddf1f1f9adcb8161caea38f',
    'storage_consistent_cut_export.py': '5b808a5214b014806b229bbd9c59fb066796010efead512b1b0b7e07c2c8d6b2',
    'constraints.txt': '433d34cc1146a838c792b8b417acefed300895a3543d62a295cb00c2791a7ba3',
}


def check(root: Path, base: str) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    try:
        if base != BASE or git(root, 'rev-parse', 'HEAD').decode().strip() != BASE:
            raise ValueError('EXACT_BASE_REQUIRED')
        if Path(git(root, 'rev-parse', '--show-toplevel').decode().strip()).resolve() != root.resolve():
            raise ValueError('CHECKOUT_ROOT_REQUIRED')
        raw = safe_read(root / MANIFEST)
        value = json.loads(raw, object_pairs_hook=unique)
        if (type(value) is not dict or set(value) != {'version', 'base', 'files', 'prerequisites'}
                or value['version'] != VERSION or value['base'] != BASE
                or type(value['files']) is not dict or set(value['files']) != set(FILES)
                or value['files'][MANIFEST] is not None or value['prerequisites'] != PREREQUISITES):
            raise ValueError('MANIFEST_CONTRACT_INVALID')
        for name in FILES:
            if name != MANIFEST:
                expected = value['files'][name]
                actual = sha(safe_read(root / name))
                staged = sha(git(root, 'show', ':' + name))
                if actual != expected or staged != expected:
                    failures.append(dict(rule='PAYLOAD_HASH_MISMATCH', path=name,
                        expected=expected, actual=actual, staged=staged))
        for name, expected in PREREQUISITES.items():
            for location, content in (('base', git(root, 'show', BASE + ':' + name)),
                    ('index', git(root, 'show', ':' + name)), ('worktree', safe_read(root / name))):
                actual = sha(content)
                if actual != expected:
                    failures.append(dict(rule='PREREQUISITE_HASH_MISMATCH', path=name,
                        location=location, expected=expected, actual=actual))
        if set(git(root, 'diff', '--cached', '--name-status', BASE, '--').decode().splitlines()) != {
                'A\t' + name for name in FILES}:
            raise ValueError('EXACT_ADDITIVE_PATHS_REQUIRED')
        entries = git(root, 'ls-files', '--stage', '--', *FILES).decode().splitlines()
        if len(entries) != len(FILES) or any(not row.startswith('100644 ') or ' 0\t' not in row for row in entries):
            raise ValueError('REGULAR_STAGE_ZERO_REQUIRED')
        if git(root, 'diff', '--name-only', '--').strip() or git(root, 'ls-files', '--others', '--exclude-standard').strip():
            raise ValueError('UNSTAGED_OR_UNTRACKED_FILES')
        if git(root, 'show', ':' + MANIFEST) != raw:
            raise ValueError('MANIFEST_INDEX_MISMATCH')
    except Exception as error:
        allowed = ('EXACT_BASE_REQUIRED', 'CHECKOUT_ROOT_REQUIRED', 'MANIFEST_CONTRACT_INVALID',
            'EXACT_ADDITIVE_PATHS_REQUIRED', 'REGULAR_STAGE_ZERO_REQUIRED',
            'UNSTAGED_OR_UNTRACKED_FILES', 'MANIFEST_INDEX_MISMATCH', 'DUPLICATE_MANIFEST_KEY',
            'PACKAGE_LINK_REJECTED', 'GIT_READ_FAILED', 'BOUNDED_REGULAR_FILE_REQUIRED',
            'PUBLIC_FILE_IDENTITY_CHANGED')
        rule = next((code for code in allowed if type(error) is ValueError and error.args == (code,)),
                    'PACKAGE_READ_FAILED')
        failures.append(dict(rule=rule))
    return dict(status='BLOCKED' if failures else 'RECOVERY_CONTRACT_PACKAGE_VERIFIED_REQUIRES_EXACT_COMMIT_CI',
        failures=failures, hosted_changes=0, run_authorised=False,
        custody_verified=False, restore_authorised=False, deletion_authorised=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    args = parser.parse_args()
    result = check(Path.cwd(), args.base)
    print(json.dumps(result, sort_keys=True))
    return 2 if result['failures'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
