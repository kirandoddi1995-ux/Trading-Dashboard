"""Exact-base additive outcome diagnostic and frozen-cohort upload gate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from programme_next_upload_check import git, safe_read, sha, unique

BASE = '0ffcb53f1b00f9db266b432d7194d8fc59c8ccf1'
MANIFEST = 'OUTCOME_COHORT_UPLOAD_2026-10-17.json'
MODIFIED: dict[str, str] = {}
FILES = (
    'preserved_drill_outcome.ps1',
    'tests/test_preserved_drill_outcome.py',
    'research_frozen_cohort.py',
    'tests/test_research_frozen_cohort.py',
    'FROZEN_COHORT_FOUNDATION_2026-10-17.md',
    'OUTCOME_AND_COHORT_HANDOFF_2026-10-17.md',
    'outcome_cohort_upload_check.py',
    'tests/test_outcome_cohort_upload_check.py',
    'OUTCOME_COHORT_UPLOAD_2026-10-17.json',
)
PREREQUISITES = {
    'programme_next_upload_check.py': 'c975be41f99994b2159e1e19b699fb1b71e6699e186bb6bb19e711adfcd01a81',
    'isolated_alert_task_drill.ps1': 'd37bbf5d6fb9e5f650adbe35d7b8cff4811da9a29126268e3f8bcd89f7dd3191',
    'isolated_alert_drill.py': 'fbc263471ae04fa3a38c5d2ee91add58f2d9020f0268ac6bbebb1e26ff2e25b4',
    'research_dataset_boundary.py': '8b7721a0617e575c6bc3f2b4a7a290d9b40cb282f387a699b1588189c3f5c9c5',
    'quote_faithful_futures_replay.py': '0d461eec560f4b05215b0db2fdb345cbf14bac82cb66b99c9e25b1ff839108e6',
    'research_session_inference.py': '7f3fabf2adc9978fd4721debeaf7d14e5c73adbcb4bcfb8e79d5f4c46d43209e',
    'sql/archive_hold_reconciliation_read_only.sql': '2db1e791e308642700888f1f224669bb924b0464db442d27950e31e6fb3f2311',
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
        if (value.get('version') != 'outcome-cohort-upload-v1' or value.get('base') != BASE
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
    return dict(status='BLOCKED' if failures else 'OUTCOME_COHORT_PACKAGE_VERIFIED_REQUIRES_TESTS_AND_EXACT_COMMIT_CI',
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
