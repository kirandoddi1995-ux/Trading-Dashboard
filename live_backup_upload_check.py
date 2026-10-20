"""Exact-base additive live-backup package verification. Public source only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from programme_next_upload_check import git, safe_read, sha, unique

BASE = '563665a32e5454633b0c27256072a7249503c520'
MANIFEST = 'LIVE_BACKUP_UPLOAD.json'
VERSION = 'live-backup-upload-v1'
FILES = ('live_database_backup.py', 'live_backup_conformance.py',
    'tests/test_live_database_backup.py', 'tests/test_live_backup_conformance.py',
    '.github/workflows/live-backup-conformance.yml', 'live_backup_upload_check.py',
    'tests/test_live_backup_upload_check.py', 'LIVE_BACKUP_HANDOFF_2026-10-21.md', MANIFEST)
PREREQUISITES = {
    'programme_next_upload_check.py': 'c975be41f99994b2159e1e19b699fb1b71e6699e186bb6bb19e711adfcd01a81',
    'archive_preservation_inventory.py': 'ec497442d9e5d779584a5153db6b15bcea07fe58b2fd2c79889ac8083b69de27',
    'archive_preservation_witness.py': '6348101f6e1ed5789854ee700539e2ca078b030c7b5a500d0d9a3901e05570cc',
    'archive_restore_policy.py': 'dab6613432f93f473d585535df63b2d4102d9010d35b6889898dc9f1e6124c25',
    'archive_recovery_binding.py': '7a267a61bdf681ee7b3195576d025810182950674fe57ea304c83048330d5910',
    'project_conductor.py': 'f318b5ca3c14d00f34c3780c2384fcc45f243e3c1fcede54515e6227c9a858bb',
    'programme_agent_team.py': 'b66d5ba6f366f2edfda299bbdb7340a2c8ce6a53a8e797d80c86aca7ca227e5a',
    'constraints.txt': '433d34cc1146a838c792b8b417acefed300895a3543d62a295cb00c2791a7ba3',
    'tests/test_workflow_runtimes.py': '008779697c5507bfb0feb70160bf3251f840bd08f72d08a67b5c2329a3d07415',
    'RECOVERY_CONTRACT_UPLOAD.json': '377ed1544ec06cdf39ed5b1ffd4e703a5bb8f44183958b2b1b920bf253cf016b',
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
            for location, raw_file in (('base', git(root, 'show', BASE + ':' + name)),
                    ('index', git(root, 'show', ':' + name)), ('worktree', safe_read(root / name))):
                actual = sha(raw_file)
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
    return dict(status='BLOCKED' if failures else 'LIVE_BACKUP_PACKAGE_VERIFIED_REQUIRES_EXACT_COMMIT_CI',
        failures=failures, hosted_changes=0, run_authorised=False,
        custody_verified=False, restore_verified=False, deletion_authorised=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    result = check(Path.cwd(), parser.parse_args().base)
    print(json.dumps(result, sort_keys=True))
    return 2 if result['failures'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
