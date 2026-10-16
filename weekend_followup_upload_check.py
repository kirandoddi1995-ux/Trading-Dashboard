"""Exact reviewed weekend follow-up gate. No capture imports, hosting or mutation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any

MANIFEST = 'WEEKEND_FOLLOWUP_UPLOAD_2026-10-17.json'
VERSION = 'weekend-followup-upload-v1'
BASE = 'a6e5be8484565be0f3d1669d6c3e004f692478e8'
PREREQUISITES = {
    'forward_live_status.py': 'eb53fd0f8774490becd82bb2bd278e84661c75e2cd134a30f44487d776320af2',
    'forward_daily_contract.py': '9f72b8e0431fc1d484d0bbdfb4bfe0a8a30a5f64fc17ca4ae6b60b47cafa4a0c',
    'forward_daily_owner.ps1': '4ee910bc266fe87b7dd768f4037c4a126896ff1f3d3b5ea7fdab0214b51ce8db',
}
FILES = (".gitignore",
    "forward_saved_audit_status.py",
    "tests/test_forward_saved_audit_status.py",
    "PROJECT_STATUS_LEDGER_2026-10-16.csv",
    "FRIDAY_OWNER_STATUS_2026-10-16.md",
    "OPERATIONS_EVIDENCE_2026-10-16.json",
    "WEEKEND_OWNER_PLAN_2026-10-16.md",
    "FORWARD_OBSERVER_RUNBOOK_2026-10-16.md",
    "WEEKEND_COMMISSIONING_STATUS_2026-10-17.md",
    "weekend_followup_upload_check.py",
    "tests/test_weekend_followup_upload_check.py",
    "WEEKEND_FOLLOWUP_UPLOAD_2026-10-17.md",
    "WEEKEND_FOLLOWUP_UPLOAD_2026-10-17.json")
MODIFIED = frozenset((".gitignore", "PROJECT_STATUS_LEDGER_2026-10-16.csv", "FRIDAY_OWNER_STATUS_2026-10-16.md", "OPERATIONS_EVIDENCE_2026-10-16.json", "WEEKEND_OWNER_PLAN_2026-10-16.md", "FORWARD_OBSERVER_RUNBOOK_2026-10-16.md"))


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest()


def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('DUPLICATE_MANIFEST_KEY')
        result[key] = value
    return result


def safe_read(file: Path) -> bytes:
    """Fixed public paths only; no following links before the regular-file check."""
    if any(p.is_symlink() or p.is_junction() for p in (file, *file.parents)):
        raise ValueError('PACKAGE_LINK_REJECTED')
    before = file.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > 8 * 1024 * 1024:
        raise ValueError('BOUNDED_REGULAR_FILE_REQUIRED')
    fd = os.open(file, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    try:
        opened = os.fstat(fd)
        if (not stat.S_ISREG(opened.st_mode) or
                (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)):
            raise ValueError('PUBLIC_FILE_IDENTITY_CHANGED')
        if any(p.is_symlink() or p.is_junction() for p in (file, *file.parents)):
            raise ValueError('PACKAGE_LINK_REJECTED')
        blocks = bytearray()
        while len(blocks) <= 8 * 1024 * 1024:
            block = os.read(fd, min(65536, 8 * 1024 * 1024 + 1 - len(blocks)))
            if not block:
                break
            blocks.extend(block)
        after = os.fstat(fd)
        if (len(blocks) != opened.st_size or len(blocks) > 8 * 1024 * 1024
                or (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns)):
            raise ValueError('PUBLIC_FILE_IDENTITY_CHANGED')
        return bytes(blocks)
    finally:
        os.close(fd)


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
        manifest_raw = safe_read(root / MANIFEST)
        manifest = json.loads(manifest_raw, object_pairs_hook=unique)
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
            actual = sha(safe_read(file)) if file.exists() else 'MISSING'
            expected = hashes[path]
            if type(expected) is not str or not re.fullmatch('[a-f0-9]{64}', expected):
                raise ValueError('MANIFEST_HASH_INVALID')
            staged = sha(git(root, 'show', ':'+path))
            if actual != expected or staged != expected:
                failures.append(dict(rule='PACKAGE_HASH_MISMATCH', path=path, expected=expected,
                                     actual=actual, staged=staged))
        for path, expected in PREREQUISITES.items():
            for location, raw in [('base',git(root,'show',base+':'+path)),
                                  ('index',git(root,'show',':'+path)), ('worktree',safe_read(root/path))]:
                actual = sha(raw)
                if actual != expected:
                    failures.append(dict(rule='PREREQUISITE_HASH_MISMATCH',path=path,
                                         location=location,expected=expected,actual=actual))
        changed = set(git(root,'diff','--cached','--name-only',base,'--').decode().splitlines())
        if changed != set(FILES):
            failures.append(dict(rule='EXACT_STAGED_PATHS_REQUIRED',missing=sorted(set(FILES)-changed),
                                 extra=sorted(changed-set(FILES))))
        statuses = git(root,'diff','--cached','--name-status',base,'--').decode().splitlines()
        if set(statuses) != {('M' if p in MODIFIED else 'A')+'\t'+p for p in FILES}:
            failures.append(dict(rule='EXACT_REVIEWED_CHANGE_TYPES_REQUIRED'))
        entries = git(root,'ls-files','--stage','--',*FILES).decode().splitlines()
        if (len(entries) != len(FILES) or any(not e.startswith('100644 ') or ' 0\t' not in e for e in entries)):
            failures.append(dict(rule='REGULAR_STAGE_ZERO_FILES_REQUIRED'))
        if git(root,'diff','--name-only','--').strip():
            failures.append(dict(rule='UNSTAGED_TRACKED_CHANGES'))
        if git(root,'ls-files','--others','--exclude-standard').strip():
            failures.append(dict(rule='UNTRACKED_FILES_PRESENT'))
        if git(root,'show',':'+MANIFEST) != manifest_raw:
            failures.append(dict(rule='MANIFEST_INDEX_WORKTREE_MISMATCH',path=MANIFEST))
    except Exception as error:
        allowed = {'EXACT_REVIEWED_BASE_REQUIRED','CHECKOUT_ROOT_REQUIRED','MANIFEST_CONTRACT_INVALID',
                   'PACKAGE_LINK_REJECTED','MANIFEST_HASH_INVALID','GIT_READ_FAILED',
                   'DUPLICATE_MANIFEST_KEY','BOUNDED_REGULAR_FILE_REQUIRED','PUBLIC_FILE_IDENTITY_CHANGED'}
        failures.append(dict(rule=str(error) if type(error) is ValueError and str(error) in allowed
                             else 'PACKAGE_READ_OR_CONTRACT_FAILED'))
    return dict(status='BLOCKED' if failures else 'WEEKEND_PACKAGE_VERIFIED_REQUIRES_TESTS_AND_EXACT_COMMIT_CI',
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
