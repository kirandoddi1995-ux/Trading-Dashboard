"""Exact-base inactive legacy rehearsal and directory-only upload gate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from programme_next_upload_check import git, safe_read, sha, unique

BASE = 'a9bbcd4359a3f941fad24f7202aba155c1582eb2'
MANIFEST = 'LEGACY_REHEARSAL_UPLOAD_2026-10-18.json'
MODIFIED: dict[str, str] = {}
FILES = (
    'legacy_archive_rehearsal.py',
    'tests/test_legacy_archive_rehearsal.py',
    'LEGACY_REHEARSAL_HANDOFF_2026-10-18.md',
    'legacy_rehearsal_upload_check.py',
    'tests/test_legacy_rehearsal_upload_check.py',
    'LEGACY_REHEARSAL_UPLOAD_2026-10-18.json',
)
PREREQUISITES = {
    "programme_next_upload_check.py": "c975be41f99994b2159e1e19b699fb1b71e6699e186bb6bb19e711adfcd01a81",
    "archive_recovery_review.py": "17aaeb69b32d3513d9ecfcb70ef96ee16eb7b2b8ff1a345c0339a1e54bc16c8d",
    "drive_archive.py": "47bae109d49a43408fbe2cd3176a974d49e997442ddf1f1f9adcb8161caea38f",
    "catalog_receipts.py": "ff0608df2cd2efa8feec3749a045c173fc3a6ec40fe46b8d86f439f57cb0e5d2",
    "cold_catalog.py": "4753cab1ca61ff551284c75b1a8004be41b5712ab8534bde9981b1272de7ff8a",
    "evidence_ledger.py": "6c410ee20bf664552e0ac42845fb995d652dc1e6488ddf8bfe66dadabd930669",
    "requirements-archive.txt": "9c21fb56692035e7ce6bce156a589eff9e7135fe27884d7513356da62f564af4",
    "constraints.txt": "433d34cc1146a838c792b8b417acefed300895a3543d62a295cb00c2791a7ba3"
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
        if (value.get('version') != 'legacy-rehearsal-upload-v1' or value.get('base') != BASE
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
    return dict(status='BLOCKED' if failures else 'LEGACY_REHEARSAL_PACKAGE_VERIFIED_REQUIRES_TESTS_AND_EXACT_COMMIT_CI',
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
