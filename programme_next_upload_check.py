"""Exact reviewed programme upload gate. No capture imports, hosting or mutation."""
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

MANIFEST = 'PROGRAMME_NEXT_UPLOAD_2026-10-17.json'
VERSION = 'programme-next-upload-v1'
BASE = '597a19d404cd1dc6c2734e48833c80e729d05d50'
PREREQUISITES = {
    "forward_session_ops.py": "e2acaed4856bf215e64507dcd1ea45bef538de4fde9a7e18f96438b6b478490c",
    "forward_ops_host.py": "41e17a6d94ba90c19607a14d35949a555356df732f033d9e0c70996300e34885",
    "automated_development_checks.py": "54d4530d75bf61fc4e7c9a01e797a4734bd6db5a9cd740ab0b314078200d2cd7",
    "research_integrity.py": "37a2c4b372bee7f989ab196efe7020d5c39585486d9ec8e3c35709e7dbead689"
}
MODIFIED_BASE_HASHES = {
    'download_nifty_history.py': '33ce8943b90c7a5aa460bb3561a650ec7820a63186bd4a258822cabdc877c4a0',
    'tests/test_download_nifty_history.py': '208a248840c661b24f88b42e953f5b058eb01f49a5b178dbee6fcb6c1d806b55',
}
FILES = ('download_nifty_history.py', 'tests/test_download_nifty_history.py', "isolated_alert_drill.py",
    "isolated_alert_task_drill.ps1",
    "tests/test_isolated_alert_drill.py",
    "research_session_inference.py",
    "tests/test_research_session_inference.py",
    "PROGRAMME_BUILD_AND_COMMISSION_2026-10-17.md",
    "RESEARCH_METHODS_AND_DELIVERY_2026-10-17.md",
    "ISOLATED_ALERT_DRILL_RUNBOOK_2026-10-17.md",
    "programme_next_upload_check.py",
    "tests/test_programme_next_upload_check.py",
    "PROGRAMME_NEXT_UPLOAD_2026-10-17.md",
    "PROGRAMME_VERIFICATION_2026-10-17.json",
    "PROGRAMME_NEXT_UPLOAD_2026-10-17.json")
MODIFIED: frozenset[str] = frozenset(MODIFIED_BASE_HASHES)


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
                or manifest.get('prerequisites') != PREREQUISITES
                or manifest.get('modified_base_files') != MODIFIED_BASE_HASHES):
            raise ValueError('MANIFEST_CONTRACT_INVALID')
        for path, expected in MODIFIED_BASE_HASHES.items():
            actual = sha(git(root, 'show', base+':'+path))
            if actual != expected:
                failures.append(dict(rule='MODIFIED_BASE_HASH_MISMATCH', path=path,
                                     expected=expected, actual=actual))
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
    return dict(status='BLOCKED' if failures else 'PROGRAMME_PACKAGE_VERIFIED_REQUIRES_TESTS_AND_EXACT_COMMIT_CI',
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
