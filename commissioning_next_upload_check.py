"""Read-only exact-base gate for archive hold, preserved first execution and paper replay."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from programme_next_upload_check import git, safe_read, sha, unique

BASE = '9be13929644dab3a091210df13743ddfbb38db32'
MANIFEST = 'COMMISSIONING_NEXT_UPLOAD_2026-10-17.json'
MODIFIED = {
    "archive_maintenance.py": "04aa20f18b055e328db486a0ebede0fa68ff885e5d8a3a15379b734fea5aab15",
    ".github/workflows/drive-archive.yml": "c3dae6de15d2debcf269f3bf462046623beb51b6047419a63c6afdae5b4f988d",
    "tests/test_drive_archive.py": "6db9282228b62902cd4b64cb3fcf66356d0c45591241a9310d2a70aa1324beef",
    "tests/test_archive_maintenance_sql.py": "f15784af5e85477a10b313bca66ecd9ee8f14ef62372e07de6c619c75705fdf1",
    "tests/test_archive_storage_relief.py": "2f3556819b2e4cff27fdf37f057cd00e7e3411f8958adf5dac3769d863b827e2"
}
FILES = ('archive_maintenance.py',
         '.github/workflows/drive-archive.yml',
         'tests/test_drive_archive.py',
         'tests/test_archive_maintenance_sql.py',
         'tests/test_archive_storage_relief.py',
         'tests/test_archive_commissioning_hold.py',
         'quote_faithful_futures_replay.py',
         'tests/test_quote_faithful_futures_replay.py',
         'FUTURES_REPLAY_FOUNDATION_2026-10-17.md',
         'preserved_drill_first_run.ps1',
         'tests/test_preserved_drill_first_run.py',
         'sql/archive_hold_reconciliation_read_only.sql',
         'COMMISSIONING_NEXT_2026-10-17.md',
         'commissioning_next_upload_check.py',
         'tests/test_commissioning_next_upload_check.py',
         'COMMISSIONING_NEXT_UPLOAD_2026-10-17.json',)
PREREQUISITES = {
    "programme_next_upload_check.py": "c975be41f99994b2159e1e19b699fb1b71e6699e186bb6bb19e711adfcd01a81",
    "drive_archive.py": "47bae109d49a43408fbe2cd3176a974d49e997442ddf1f1f9adcb8161caea38f",
    "requirements-archive.txt": "9c21fb56692035e7ce6bce156a589eff9e7135fe27884d7513356da62f564af4",
    "constraints.txt": "433d34cc1146a838c792b8b417acefed300895a3543d62a295cb00c2791a7ba3",
    "isolated_alert_task_drill.ps1": "d37bbf5d6fb9e5f650adbe35d7b8cff4811da9a29126268e3f8bcd89f7dd3191",
    "isolated_alert_drill.py": "fbc263471ae04fa3a38c5d2ee91add58f2d9020f0268ac6bbebb1e26ff2e25b4",
    "preserved_drill_audit.ps1": "5a64a23d700c9d228592ed7bb3f459a7943a9a7a8ad03cb77baa012a46309ae6",
    "preserved_drill_audit.py": "546c7e2936ba22278f84410b998f59add20ed72fc706dbdd10ebbf0fee5347f6",
    "forward_session_ops.py": "e2acaed4856bf215e64507dcd1ea45bef538de4fde9a7e18f96438b6b478490c",
    "forward_ops_host.py": "41e17a6d94ba90c19607a14d35949a555356df732f033d9e0c70996300e34885",
    "automated_development_checks.py": "54d4530d75bf61fc4e7c9a01e797a4734bd6db5a9cd740ab0b314078200d2cd7",
    "research_integrity.py": "37a2c4b372bee7f989ab196efe7020d5c39585486d9ec8e3c35709e7dbead689"
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
        hashes = value['files']
        if (value.get('version') != 'commissioning-next-upload-v1' or value.get('base') != BASE
                or set(hashes) != set(FILES) or hashes[MANIFEST] is not None
                or value.get('modified_base_files') != MODIFIED or value.get('prerequisites') != PREREQUISITES):
            raise ValueError('MANIFEST_CONTRACT_INVALID')
        for name, expected in MODIFIED.items():
            actual = sha(git(root, 'show', BASE + ':' + name))
            if actual != expected:
                failures.append(dict(rule='MODIFIED_BASE_HASH_MISMATCH', path=name, expected=expected, actual=actual))
        for name in FILES:
            if name == MANIFEST:
                continue
            expected = hashes[name]
            actual = sha(safe_read(root / name))
            staged = sha(git(root, 'show', ':' + name))
            if expected != actual or expected != staged:
                failures.append(dict(rule='PAYLOAD_HASH_MISMATCH', path=name, expected=expected, actual=actual, staged=staged))
        for name, expected in PREREQUISITES.items():
            for location, source in [('base', git(root, 'show', BASE + ':' + name)),
                                     ('index', git(root, 'show', ':' + name)), ('worktree', safe_read(root / name))]:
                actual = sha(source)
                if actual != expected:
                    failures.append(dict(rule='PREREQUISITE_HASH_MISMATCH', path=name, location=location,
                                         expected=expected, actual=actual))
        if set(git(root, 'diff', '--cached', '--name-status', BASE, '--').decode().splitlines()) != {('M' if x in MODIFIED else 'A') + '\t' + x for x in FILES}:
            raise ValueError('EXACT_REVIEWED_PATHS_REQUIRED')
        entries = git(root, 'ls-files', '--stage', '--', *FILES).decode().splitlines()
        if len(entries) != len(FILES) or any(not x.startswith('100644 ') or ' 0\t' not in x for x in entries):
            raise ValueError('REGULAR_STAGE_ZERO_FILES_REQUIRED')
        if git(root, 'diff', '--name-only', '--').strip() or git(root, 'ls-files', '--others', '--exclude-standard').strip():
            raise ValueError('UNSTAGED_OR_UNTRACKED_FILES')
        if git(root, 'show', ':' + MANIFEST) != raw:
            raise ValueError('MANIFEST_INDEX_WORKTREE_MISMATCH')
    except Exception as error:
        allowed = {'EXACT_BASE_REQUIRED', 'CHECKOUT_ROOT_REQUIRED', 'MANIFEST_CONTRACT_INVALID',
                   'EXACT_REVIEWED_PATHS_REQUIRED', 'REGULAR_STAGE_ZERO_FILES_REQUIRED',
                   'UNSTAGED_OR_UNTRACKED_FILES', 'MANIFEST_INDEX_WORKTREE_MISMATCH', 'DUPLICATE_MANIFEST_KEY',
                   'PACKAGE_LINK_REJECTED', 'GIT_READ_FAILED', 'BOUNDED_REGULAR_FILE_REQUIRED', 'PUBLIC_FILE_IDENTITY_CHANGED'}
        failures.append(dict(rule=str(error) if type(error) is ValueError and str(error) in allowed else 'PACKAGE_READ_FAILED'))
    return dict(status='BLOCKED' if failures else 'COMMISSIONING_PACKAGE_VERIFIED_REQUIRES_TESTS_AND_EXACT_COMMIT_CI',
                failures=failures, hosted_changes=0, capture_changes=0, task_mutations=0,
                run_authorised=False, training_eligible=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    result = check(Path.cwd(), parser.parse_args().base)
    print(json.dumps(result))
    return 2 if result['failures'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
