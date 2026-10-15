"""One inactive Oct15 public upload: exact base, paths, hashes and staged bytes.

Reads only reviewed public sources/Git. No secrets, captures, tasks or network.
Failure metadata is restricted to public relative paths and SHA-256 values.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

import daily_volume_upload_check as guarded
from overnight_upload_check import pairs
from reviewed_upload_check import git

BASE = '1251530731cce5b75fad8601567b9320d07b710d'
MANIFEST = 'CONTINUITY_UPLOAD_2026-10-15.json'
FILES = (
    'forward_morning_route.py', 'tests/test_forward_morning_route.py',
    'forward_evidence_preserve.py', 'tests/test_forward_evidence_preserve.py',
    'storage_consistent_cut_export.py', 'tests/test_storage_consistent_cut_export.py',
    'storage_cut_native_check.py', 'tests/test_storage_cut_native_check.py',
    'research_forward_cohort.py', 'tests/test_research_forward_cohort.py',
    'programme_agent_team.py', 'tests/test_programme_agent_team.py',
    'MORNING_2026-10-15.md', 'OWNER_CAPTURE_2026-10-15.md',
    'OVERNIGHT_CONTINUITY_2026-10-15.md', 'AGENT_TEAM_2026-10-15.md',
    'continuity_upload_check.py', 'tests/test_continuity_upload_check.py',
    'CONTINUITY_UPLOAD_2026-10-15.md', MANIFEST,
)
SEEDS = ('forward_morning_route.py', 'forward_evidence_preserve.py',
         'storage_consistent_cut_export.py', 'storage_cut_native_check.py',
         'research_forward_cohort.py', 'programme_agent_team.py',
         'continuity_upload_check.py', 'forward_session_ops.py',
         'forward_versioned_producer.py', 'forward_morning_readiness.py')
EXTRA = ('requirements.txt', 'constraints.txt', 'requirements-forward-operations.txt',
         'requirements-archive.txt', 'requirements-automation.txt', 'forward_ops_task.ps1',
         'tests/test_forward_session_ops.py', 'tests/test_forward_morning_readiness.py',
         'tests/test_overnight_capture_audit.py', 'tests/test_storage_daily_volume_reader.py',
         'resilience_policy.json', 'resilience_policy.sha256')
LIMIT = 128 * 1024
SPECIAL = frozenset({MANIFEST, 'resilience_policy.json', 'resilience_policy.sha256'})
SAFE = guarded.SAFE_RULES | {'INDEX_WORKTREE_MISMATCH', 'CONTROL_ENTRY_INVALID',
                            'APPROVED_POLICY_BYTES_INVALID'}


def public_bytes(root: Path, name: str) -> bytes:
    if name not in SPECIAL:
        return guarded.public_bytes(root, name)
    guarded.root_guard(root)
    path = root / name
    if path.is_symlink() or path.is_junction():
        raise ValueError('SOURCE_LINK_REJECTED')
    if not path.is_file() or path.stat().st_size >= LIMIT:
        raise ValueError('CONTROL_TOO_LARGE')
    with path.open('rb') as stream:
        raw = stream.read(LIMIT)
    if not raw or len(raw) >= LIMIT:
        raise ValueError('CONTROL_TOO_LARGE')
    return raw


def verify(root: Path, changed: set[str]) -> list[dict[str, str]]:
    """Validate immutable public controls, never infer green CI or owner consent."""
    raw = json.loads(public_bytes(root, MANIFEST), object_pairs_hook=pairs,
                     parse_constant=guarded.reject_constant)
    if (type(raw) is not dict or set(raw) != {'version','base','files','prerequisites','seeds','extra_pins'}
            or raw['version'] != 'oct15-continuity-v1' or raw['base'] != BASE):
        raise ValueError('MANIFEST_INVALID')
    entries = raw['files']
    if type(entries) is not list or len(entries) != len(FILES):
        raise ValueError('EXACT_PACKAGE_REQUIRED')
    control = [item for item in entries if type(item) is dict and item.get('destination') == MANIFEST]
    if control != [{'destination':MANIFEST, 'sha256_lf':None}]:
        raise ValueError('CONTROL_ENTRY_INVALID')
    files = guarded.pins([item for item in entries if item is not control[0]], control=False)
    prerequisites = guarded.pins(raw['prerequisites'], control=False)
    expected = {pin.destination for pin in files} | {MANIFEST}
    if type(changed) is not set or expected != set(FILES) or changed != expected:
        raise ValueError('EXACT_PACKAGE_REQUIRED')
    guarded.exact_strings(raw['seeds'], SEEDS)
    guarded.exact_strings(raw['extra_pins'], EXTRA)
    prior = {pin.destination for pin in prerequisites}
    if prior & expected:
        raise ValueError('PREREQUISITE_OVERLAP')
    if prior != (guarded.guarded_members(root, list(SEEDS)) | set(EXTRA)) - expected:
        raise ValueError('EXACT_PINS_REQUIRED')
    # This deployed policy's approved checksum is over EXACT bytes. Never
    # normalize a broken checkout or replace its approved sidecar to pass.
    approved = public_bytes(root, 'resilience_policy.sha256').decode('ascii').strip()
    if (re.fullmatch('[0-9a-f]{64}', approved) is None
            or hashlib.sha256(public_bytes(root, 'resilience_policy.json')).hexdigest() != approved):
        raise ValueError('APPROVED_POLICY_BYTES_INVALID')
    failures = []
    for pin in (*files, *prerequisites):
        actual = guarded.digest(public_bytes(root, pin.destination))
        if actual != pin.sha256_lf:
            failures.append({'path':pin.destination, 'expected':str(pin.sha256_lf), 'actual':actual})
    return failures


def index_matches(root: Path, names: set[str]) -> list[dict[str, str]]:
    """Bind every working source/control to its immutable staged Git blob."""
    failures = []
    for name in sorted(names):
        working = public_bytes(root, name)
        entry = git(root, 'ls-files', '--stage', '--', name)
        match = re.fullmatch(r'(100644|100755) ([0-9a-f]{40}) 0\t' + re.escape(name), entry)
        if match is None:
            raise ValueError('INDEX_ENTRY_INVALID')
        size_text = git(root, 'cat-file', '-s', match[2])
        if re.fullmatch('[0-9]{1,10}', size_text) is None:
            raise ValueError('INDEX_BLOB_INVALID')
        size = int(size_text)
        maximum = LIMIT - 1 if name in SPECIAL else 4 * 1024 * 1024
        if size > maximum:
            raise ValueError('INDEX_BLOB_TOO_LARGE')
        result = subprocess.run(['git', '-C', str(root), 'cat-file', 'blob', match[2]],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
        staged = result.stdout
        if len(staged) != size:
            raise ValueError('INDEX_BLOB_INVALID')
        expected, actual = guarded.digest(working), guarded.digest(staged)
        if expected != actual:
            failures.append({'path':name, 'expected':expected, 'actual':actual})
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    args = parser.parse_args(argv)
    try:
        root = Path.cwd()
        guarded.root_guard(root)
        if args.base != BASE or git(root, 'rev-parse', 'HEAD') != BASE:
            raise ValueError('BASE_NOT_CURRENT_HEAD')
        if Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != root.resolve():
            raise ValueError('CLONE_ROOT_REQUIRED')
        if git(root, 'diff', '--name-only', '--') or git(root, 'ls-files', '--others', '--exclude-standard'):
            raise ValueError('STAGE_THEN_RECHECK')
        changed = set(git(root, 'diff', '--cached', '--name-only', BASE, '--').splitlines())
        failures = verify(root, changed)
        if not failures:
            failures = index_matches(root, changed | guarded.guarded_members(root, list(SEEDS)) | set(EXTRA))
        print(json.dumps({'status':'BLOCKED' if failures else 'UPLOAD_FILES_VERIFIED_REQUIRES_TESTS_AND_CI',
                          'failures':failures, 'hosted_changes':0}, sort_keys=True))
        return 2 if failures else 0
    except Exception as error:
        rule = str(error) if isinstance(error, ValueError) and str(error) in SAFE else 'UPLOAD_REVIEW_REQUIRED'
        print(json.dumps({'status':'BLOCKED','rule':rule,'hosted_changes':0}, sort_keys=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
