"""Exact additive observer upload gate. No capture imports, hosting or mutation."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any

MANIFEST = 'FORWARD_OBSERVER_UPLOAD_2026-10-16.json'
VERSION = 'forward-observer-upload-v2'
BASE = '0b0aad4efa102643cc5dc4073dc7fc915281c1bf'
PREREQUISITES = {
    'forward_daily_contract.py': '9f72b8e0431fc1d484d0bbdfb4bfe0a8a30a5f64fc17ca4ae6b60b47cafa4a0c',
    'forward_daily_owner.ps1': '4ee910bc266fe87b7dd768f4037c4a126896ff1f3d3b5ea7fdab0214b51ce8db',
}
FILES = (
    'owner_capability_inventory.py', 'tests/test_owner_capability_inventory.py',
    'tests/test_project_status_ledger.py', 'PROJECT_STATUS_LEDGER_2026-10-16.csv',
    'FRIDAY_OWNER_STATUS_2026-10-16.md', 'forward_live_status.py', 'forward_observer_tools.ps1',
    'forward_operations_runner.py', 'operations_evidence_matrix.py',
    'tests/test_forward_live_status.py', 'tests/test_forward_operations_runner.py',
    'tests/test_operations_evidence_matrix.py', 'FORWARD_OBSERVER_RUNBOOK_2026-10-16.md',
    'OPERATIONS_EVIDENCE_2026-10-16.json', 'forward_observer_upload_check.py',
    'tests/test_forward_observer_upload_check.py', 'FORWARD_OBSERVER_UPLOAD_2026-10-16.md',
    'forward_guided_owner.ps1', 'tests/test_forward_guided_owner.py',
    'FRIDAY_COMPLETION_WITNESS_2026-10-16.json', 'WEEKEND_OWNER_PLAN_2026-10-16.md', MANIFEST)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest()


def git(root: Path, *args: str) -> bytes:
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, timeout=20, check=False)
    if result.returncode != 0 or len(result.stdout) > 8*1024*1024:
        raise ValueError('GIT_READ_FAILED')
    return result.stdout


def check(root: Path, base: str) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    try:
        if base != BASE or git(root, 'rev-parse', '--verify', base).decode().strip() != BASE:
            raise ValueError('EXACT_REVIEWED_BASE_REQUIRED')
        if git(root,'rev-parse','HEAD').decode().strip() != BASE:
            raise ValueError('EXACT_REVIEWED_BASE_REQUIRED')
        if Path(git(root, 'rev-parse', '--show-toplevel').decode().strip()).resolve() != root.resolve():
            raise ValueError('CHECKOUT_ROOT_REQUIRED')
        manifest = json.loads((root / MANIFEST).read_text(encoding='utf8'))
        hashes = manifest['files']
        if (manifest.get('version') != VERSION or manifest.get('base') != BASE or set(hashes) != set(FILES)
                or hashes.get(MANIFEST) is not None
                or manifest.get('prerequisites') != PREREQUISITES):
            raise ValueError('MANIFEST_CONTRACT_INVALID')
        for path in FILES:
            file = root / path
            if any(p.is_symlink() or p.is_junction() for p in (file, *file.parents)):
                raise ValueError('PACKAGE_LINK_REJECTED')
            if path == MANIFEST:
                continue
            actual = sha(file.read_bytes()) if file.is_file() else 'MISSING'
            expected = hashes[path]
            if type(expected) is not str or not re.fullmatch('[a-f0-9]{64}', expected):
                raise ValueError('MANIFEST_HASH_INVALID')
            staged = sha(git(root, 'show', ':'+path))
            if actual != expected or staged != expected:
                failures.append(dict(rule='PACKAGE_HASH_MISMATCH', path=path, expected=expected,
                                     actual=actual, staged=staged))
        for path, expected in PREREQUISITES.items():
            for location, raw in [('base',git(root,'show',base+':'+path)),
                                  ('index',git(root,'show',':'+path)), ('worktree',(root/path).read_bytes())]:
                actual = sha(raw)
                if actual != expected:
                    failures.append(dict(rule='PREREQUISITE_HASH_MISMATCH',path=path,
                                         location=location,expected=expected,actual=actual))
        changed = set(git(root,'diff','--cached','--name-only',base,'--').decode().splitlines())
        if changed != set(FILES):
            failures.append(dict(rule='EXACT_STAGED_PATHS_REQUIRED',missing=sorted(set(FILES)-changed),
                                 extra=sorted(changed-set(FILES))))
        statuses = git(root,'diff','--cached','--name-status',base,'--').decode().splitlines()
        if set(statuses) != {'A\t'+p for p in FILES}:
            failures.append(dict(rule='ADDITIVE_FILES_ONLY_REQUIRED'))
        entries = git(root,'ls-files','--stage','--',*FILES).decode().splitlines()
        if (len(entries) != len(FILES) or any(not e.startswith('100644 ') or ' 0\t' not in e for e in entries)):
            failures.append(dict(rule='REGULAR_STAGE_ZERO_FILES_REQUIRED'))
        if git(root,'diff','--name-only','--').strip():
            failures.append(dict(rule='UNSTAGED_TRACKED_CHANGES'))
        if git(root,'ls-files','--others','--exclude-standard').strip():
            failures.append(dict(rule='UNTRACKED_FILES_PRESENT'))
        if git(root,'show',':'+MANIFEST) != (root/MANIFEST).read_bytes():
            failures.append(dict(rule='MANIFEST_INDEX_WORKTREE_MISMATCH',path=MANIFEST))
    except Exception as error:
        allowed = {'EXACT_REVIEWED_BASE_REQUIRED','CHECKOUT_ROOT_REQUIRED','MANIFEST_CONTRACT_INVALID',
                   'PACKAGE_LINK_REJECTED','MANIFEST_HASH_INVALID','GIT_READ_FAILED'}
        failures.append(dict(rule=str(error) if type(error) is ValueError and str(error) in allowed
                             else 'PACKAGE_READ_OR_CONTRACT_FAILED'))
    return dict(status='BLOCKED' if failures else 'OBSERVER_PACKAGE_VERIFIED_REQUIRES_TESTS_AND_EXACT_COMMIT_CI',
                failures=failures,hosted_changes=0,capture_changes=0,task_enable_operations=0,
                actual_task_state='NOT_OBSERVED',
                commissioning_verified=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',required=True)
    args = parser.parse_args(argv)
    result = check(Path.cwd(),args.base)
    print(json.dumps(result))
    return 2 if result['failures'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
