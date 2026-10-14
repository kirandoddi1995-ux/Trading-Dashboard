"""Exact inactive commissioning repair, pinned to the reviewed public baseline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Callable, cast

import daily_volume_upload_check as guarded
import overnight_programme_upload_check as bounded
from overnight_upload_check import pairs
from reviewed_upload_check import git

BASE = '161ffe082343c20cf118950fdb49e5315bb54e7f'
VERSION = 'forward-commissioning-repair-v1'
GROUP = 'forward_commissioning_repair'
MANIFEST = 'FORWARD_COMMISSIONING_REPAIR_UPLOAD_2026-10-14.json'
CONTROL_LIMIT = 128 * 1024
FILES = (
    'forward_session_ops.py', 'tests/test_forward_session_ops.py',
    'forward_ops_host.py',
    'forward_morning_readiness.py', 'tests/test_forward_morning_readiness.py',
    'forward_commissioning_upload_check.py', 'tests/test_forward_commissioning_upload_check.py',
    'FORWARD_COMMISSIONING_REPAIR_2026-10-14.md',
    'FORWARD_COMMISSIONING_REPAIR_UPLOAD_2026-10-14.md', MANIFEST,
)
SEEDS = ('forward_session_ops.py', 'forward_morning_readiness.py', 'forward_commissioning_upload_check.py')
EXTRA_PINS = (
    'constraints.txt', 'requirements.txt', 'requirements-archive.txt',
    'requirements-option-capture.txt', 'requirements-forward-operations.txt',
    'forward_ops_task.ps1', 'tests/test_forward_versioned_capture.py',
    'tests/test_overnight_capture_audit.py',
)
SCHEMA = frozenset({'version', 'group', 'base', 'files', 'prerequisites', 'seeds', 'extra_pins'})
SAFE_RULES = guarded.SAFE_RULES | {'INDEX_WORKTREE_MISMATCH'}


def public_source(root: Path, name: object) -> Path:
    guarded.root_guard(root)
    if type(name) is not str:
        raise ValueError('PUBLIC_SOURCE_PATH_REQUIRED')
    if name != MANIFEST:
        if name.endswith('.json'):
            raise ValueError('PUBLIC_SOURCE_PATH_REQUIRED')
        return cast(Callable[[Path, object], Path], guarded.public_source)(root, name)
    path = root / MANIFEST
    if path.is_symlink() or path.is_junction():
        raise ValueError('SOURCE_LINK_REJECTED')
    if not path.is_file():
        raise ValueError('SOURCE_MISSING_OR_TOO_LARGE')
    if path.stat().st_size >= CONTROL_LIMIT:
        raise ValueError('CONTROL_TOO_LARGE')
    return path


def public_bytes(root: Path, name: str) -> bytes:
    path = public_source(root, name)
    limit = CONTROL_LIMIT - 1 if name == MANIFEST else bounded.MAX_BYTES
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('CONTROL_TOO_LARGE' if name == MANIFEST else 'SOURCE_MISSING_OR_TOO_LARGE')
    return raw


def verify(root: Path, changed: set[str]) -> list[dict[str, str]]:
    raw: object = json.loads(public_bytes(root, MANIFEST), object_pairs_hook=pairs,
                            parse_constant=guarded.reject_constant)
    if (type(raw) is not dict or set(raw) != SCHEMA or raw['version'] != VERSION
            or raw['group'] != GROUP or raw['base'] != BASE):
        raise ValueError('MANIFEST_INVALID')
    # Reuse strict typed pin parsing; our own control is the sole null hash.
    def entries(value: object, control: bool) -> tuple[guarded.Pin, ...]:
        if type(value) is not list or not value or len(value) > 512:
            raise ValueError('EXACT_PINS_REQUIRED')
        result: list[guarded.Pin] = []
        seen: set[str] = set()
        for item in value:
            if type(item) is not dict or set(item) != {'destination', 'sha256_lf'}:
                raise ValueError('EXACT_PINS_REQUIRED')
            name, sha = item['destination'], item['sha256_lf']
            if type(name) is not str or name in seen:
                raise ValueError('EXACT_PINS_REQUIRED')
            if control and name == MANIFEST:
                if sha is not None:
                    raise ValueError('MANIFEST_HASH_INVALID')
            elif type(sha) is not str or re.fullmatch('[0-9a-f]{64}', sha) is None:
                raise ValueError('MANIFEST_HASH_INVALID')
            seen.add(name)
            result.append(guarded.Pin(name, sha))
        return tuple(result)
    files, prerequisites = entries(raw['files'], True), entries(raw['prerequisites'], False)
    names = {pin.destination for pin in files}
    if type(changed) is not set or names != set(FILES) or changed != names:
        raise ValueError('EXACT_PACKAGE_REQUIRED')
    guarded.exact_strings(raw['seeds'], SEEDS)
    guarded.exact_strings(raw['extra_pins'], EXTRA_PINS)
    prior = {pin.destination for pin in prerequisites}
    if prior & names:
        raise ValueError('PREREQUISITE_OVERLAP')
    for name in names | prior | set(SEEDS) | set(EXTRA_PINS):
        public_source(root, name)
    closure = guarded.guarded_members(root, list(SEEDS))
    if prior != (closure | set(EXTRA_PINS)) - names:
        raise ValueError('EXACT_PINS_REQUIRED')
    failures: list[dict[str, str]] = []
    for pin in (*files, *prerequisites):
        raw_bytes = public_bytes(root, pin.destination)
        if pin.destination == MANIFEST:
            continue
        assert pin.sha256_lf is not None
        actual = guarded.digest(raw_bytes)
        if actual != pin.sha256_lf:
            failures.append({'path': pin.destination, 'expected': pin.sha256_lf, 'actual': actual})
    return failures


def index_matches(root: Path, names: set[str]) -> list[dict[str, str]]:
    """Reuse guarded immutable-blob comparisons; independently guard new control."""
    failures = cast(Callable[[Path, set[str]], list[dict[str, str]]],
                    guarded.index_matches)(root, names - {MANIFEST})
    if MANIFEST not in names:
        return failures
    # Read the fixed control blob by immutable identity, not a caller's revision.
    working = public_bytes(root, MANIFEST)
    entry = git(root, 'ls-files', '--stage', '--', MANIFEST)
    match = re.fullmatch(r'(100644|100755) ([0-9a-f]{40}) 0\t' + re.escape(MANIFEST), entry)
    if match is None:
        raise ValueError('INDEX_ENTRY_INVALID')
    identity = match[2]
    size_text = git(root, 'cat-file', '-s', identity)
    if re.fullmatch('[0-9]{1,10}', size_text) is None:
        raise ValueError('INDEX_BLOB_INVALID')
    size = int(size_text)
    if size >= CONTROL_LIMIT:
        raise ValueError('INDEX_BLOB_TOO_LARGE')
    # Git helper returns text with strip(); it must not be used for blob bytes.
    import subprocess
    response = subprocess.run(['git', '-C', str(root), 'cat-file', 'blob', identity],
                              check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
    staged = response.stdout
    if type(staged) is not bytes or len(staged) != size:
        raise ValueError('INDEX_BLOB_INVALID')
    expected, actual = guarded.digest(working), guarded.digest(staged)
    if expected != actual:
        failures.append({'path': MANIFEST, 'expected': expected, 'actual': actual})
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    args = parser.parse_args(argv)
    try:
        root = Path.cwd()
        guarded.root_guard(root)
        if (re.fullmatch('[0-9a-f]{40}', args.base) is None or args.base != BASE
                or git(root, 'rev-parse', 'HEAD') != args.base):
            raise ValueError('BASE_NOT_CURRENT_HEAD')
        if Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != root.resolve():
            raise ValueError('CLONE_ROOT_REQUIRED')
        if git(root, 'diff', '--name-only', '--') or git(root, 'ls-files', '--others', '--exclude-standard'):
            raise ValueError('STAGE_THEN_RECHECK')
        changed = set(git(root, 'diff', '--cached', '--name-only', args.base, '--').splitlines())
        failures = verify(root, changed)
        if not failures:
            indexed = changed | guarded.guarded_members(root, list(SEEDS)) | set(EXTRA_PINS)
            failures = index_matches(root, indexed)
        print(json.dumps({'status': 'BLOCKED' if failures else 'UPLOAD_FILES_VERIFIED_REQUIRES_TESTS_AND_CI',
                          'failures': failures, 'hosted_changes': 0}))
        return 2 if failures else 0
    except Exception as error:
        rule = str(error) if isinstance(error, ValueError) and str(error) in SAFE_RULES else 'UPLOAD_REVIEW_REQUIRED'
        print(json.dumps({'status': 'BLOCKED', 'rule': rule, 'hosted_changes': 0}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
