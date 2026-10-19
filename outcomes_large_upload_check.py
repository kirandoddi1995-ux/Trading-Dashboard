"""Exact-base inactive outcomes profile upload gate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from programme_next_upload_check import git, safe_read, sha, unique

BASE = '07313864a9033a8b97f041012c77f55d54cb127a'
REVIEWED_PR_HEAD = '088fab77bc2bc847d2d798eb2cbe429a9a81c997'
MANIFEST = 'OUTCOMES_LARGE_UPLOAD_2026-10-19.json'
MODIFIED: dict[str, str] = {
    'tests/test_workflow_runtimes.py': '68f23381098e65766064a9ab7e2d4b709568401e44ecadbcdbb420c82f2c3a47',
}
FILES = (
    'tests/test_workflow_runtimes.py',
    'outcomes_large_profile.py',
    'outcomes_resource_conformance.py',
    'tests/test_outcomes_large_profile.py',
    'tests/test_outcomes_resource_conformance.py',
    '.github/workflows/outcomes-resource-conformance.yml',
    'OUTCOMES_LARGE_HANDOFF_2026-10-19.md',
    'outcomes_large_upload_check.py',
    'tests/test_outcomes_large_upload_check.py',
    'OUTCOMES_LARGE_UPLOAD_2026-10-19.json',
)
PREREQUISITES = {
    "programme_next_upload_check.py": "c975be41f99994b2159e1e19b699fb1b71e6699e186bb6bb19e711adfcd01a81",
    "outcomes_footer_diagnostic.py": "3a1d87da023084a2f35269412645827774c943e21ae1dda188494db794cc565d",
    "archive_catalog_verify.py": "f63723a83bb9ee4a39790ad064da1caf91dbb291081bf7592c0e90eea323ef61",
    "archive_catalog_reconcile.py": "f00ffd005e68d076ff9667a516c3d77c8d686fbd6152b88291dc455fb46b7eb8",
    "archive_recovery_review.py": "17aaeb69b32d3513d9ecfcb70ef96ee16eb7b2b8ff1a345c0339a1e54bc16c8d",
    "archive_maintenance.py": "7715add8c1c9893a875dc54db75110aa3be5d17f9b6f6ae6aec20bbce6baf46f",
    "drive_archive.py": "47bae109d49a43408fbe2cd3176a974d49e997442ddf1f1f9adcb8161caea38f",
    "requirements-archive.txt": "9c21fb56692035e7ce6bce156a589eff9e7135fe27884d7513356da62f564af4",
    "constraints.txt": "433d34cc1146a838c792b8b417acefed300895a3543d62a295cb00c2791a7ba3",
    "equity_research_outcomes.py": "63cb023dc7b09d914d880d323d6c42e883776103e792dc28b01252c23d480718",
    "equity_research_collector.py": "c582c01b0817a6f7a775b5d2f77fc46b577f6fbd17e5323952133f97f0d10464",
    "equity_research_repository.py": "a8af611399128ebd15e468dc051a27a397baeff12f9b78e5d93f16178d27b3ca"
}



def check(root: Path, base: str, update_pr49: bool = False) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    try:
        if base != BASE:
            raise ValueError('EXACT_BASE_REQUIRED')
        expected_head = REVIEWED_PR_HEAD if update_pr49 else BASE
        if git(root, 'rev-parse', 'HEAD').decode().strip() != expected_head:
            raise ValueError('EXACT_REVIEWED_PR_HEAD_REQUIRED' if update_pr49 else 'EXACT_BASE_REQUIRED')
        if update_pr49 and git(root, 'rev-parse', 'HEAD^').decode().strip() != BASE:
            raise ValueError('REVIEWED_PR_PARENT_REQUIRED')
        if Path(git(root, 'rev-parse', '--show-toplevel').decode().strip()).resolve() != root.resolve():
            raise ValueError('CHECKOUT_ROOT_REQUIRED')
        raw = safe_read(root / MANIFEST)
        value = json.loads(raw, object_pairs_hook=unique)
        hashes = value['files']
        if (value.get('version') != 'outcomes-large-upload-v2' or value.get('base') != BASE
                or value.get('reviewed_pr_head') != REVIEWED_PR_HEAD
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
                   'EXACT_REVIEWED_PR_HEAD_REQUIRED', 'REVIEWED_PR_PARENT_REQUIRED',
                   'EXACT_REVIEWED_PATHS_REQUIRED', 'REGULAR_STAGE_ZERO_FILES_REQUIRED',
                   'UNSTAGED_OR_UNTRACKED_FILES', 'MANIFEST_INDEX_WORKTREE_MISMATCH', 'DUPLICATE_MANIFEST_KEY',
                   'PACKAGE_LINK_REJECTED', 'GIT_READ_FAILED', 'BOUNDED_REGULAR_FILE_REQUIRED', 'PUBLIC_FILE_IDENTITY_CHANGED'}
        failures.append(dict(rule=str(error) if type(error) is ValueError and str(error) in allowed else 'PACKAGE_READ_FAILED'))
    return dict(status='BLOCKED' if failures else 'OUTCOMES_LARGE_PACKAGE_VERIFIED_REQUIRES_TESTS_AND_EXACT_COMMIT_CI',
                failures=failures, hosted_changes=0, capture_changes=0, task_mutations=0,
                run_authorised=False, training_eligible=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--update-pr49', action='store_true', help='Only the exact reviewed unmerged PR49 head; never arbitrary HEAD')
    args = parser.parse_args()
    result = check(Path.cwd(), args.base, args.update_pr49)
    print(json.dumps(result))
    return 2 if result['failures'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
