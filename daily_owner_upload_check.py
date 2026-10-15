"""Exact public tree: combined33 on125, or daily13 after frozen continuity20.

The post-merge SHA is not guessed. --base must equal actual HEAD; its COMPLETE
delta from the anchor must be empty(combined) or exactly twenty pinned additions.
No pin is removed or refreshed on a failure. Reads public Git/files only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any

ANCHOR = '1251530731cce5b75fad8601567b9320d07b710d'
CONTROL = 'DAILY_OWNER_UPLOAD_2026-10-15.json'
FILES = (
    'forward_daily_contract.py', 'forward_daily_owner.ps1',
    'tests/test_forward_daily_contract.py', 'tests/test_forward_daily_owner.py',
    'project_conductor.py', 'tests/test_project_conductor.py',
    'PROJECT_WORKING_AGREEMENT.md', 'TECHNOLOGY_RADAR_2026-10-15.md',
    'FRIDAY_CAPTURE_2026-10-16.md', 'daily_owner_upload_check.py',
    'tests/test_daily_owner_upload_check.py', 'DAILY_OWNER_UPLOAD_2026-10-15.md', CONTROL,
)
LIMIT = 512 * 1024
# Commitment to the reviewed, unchanged20files, independently of this new JSON.
# Canonical encoding: sorted `path:sha256_lf` lines joined by LF, no final LF.
PREREQUISITE_SET_SHA256 = '3294e8b01b649fc6b6caf48bd4816196ff2e2e4616600e123e56a6b056fe676c'


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(['git', '-C', str(root), *arguments], check=True,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30)
    return result.stdout.decode('utf-8').strip()


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError('DUPLICATE_CONTROL_FIELD')
        result[key] = value
    return result


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest()


def source(root: Path, name: str) -> bytes:
    relative = PurePosixPath(name)
    if (relative.is_absolute() or name != relative.as_posix() or '\\' in name
            or ':' in name or '..' in relative.parts or not relative.parts
            or any(p.startswith('.') for p in relative.parts)):
        raise ValueError('PUBLIC_PATH_INVALID')
    for path in (root, *root.parents):
        if path.is_symlink() or path.is_junction():
            raise ValueError('PUBLIC_SOURCE_LINK_REJECTED')
    path = root
    for part in relative.parts:
        path /= part
        if path.is_symlink() or path.is_junction():
            raise ValueError('PUBLIC_SOURCE_LINK_REJECTED')
    if not path.is_file() or path.stat().st_size > LIMIT:
        raise ValueError('PUBLIC_SOURCE_MISSING_OR_TOO_LARGE')
    with path.open('rb') as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('PUBLIC_SOURCE_MISSING_OR_TOO_LARGE')
    return raw


def entries(value: object) -> dict[str, str | None]:
    if type(value) is not list:
        raise ValueError('CONTROL_PINS_INVALID')
    pins: dict[str, str | None] = {}
    for item in value:
        if type(item) is not dict or set(item) != {'path', 'sha256_lf'}:
            raise ValueError('CONTROL_PINS_INVALID')
        name, sha = item['path'], item['sha256_lf']
        if (type(name) is not str or name in pins
                or (sha is None and name != CONTROL)
                or (sha is not None and (type(sha) is not str or re.fullmatch('[0-9a-f]{64}', sha) is None))):
            raise ValueError('CONTROL_PINS_INVALID')
        pins[name] = sha
    return pins


def verify(root: Path, base: str, *, combined: bool = False) -> list[dict[str, str]]:
    """Bind prior complete tree and staged next tree; no network or writes."""
    if (type(combined) is not bool or (combined and base != ANCHOR)
            or re.fullmatch('[0-9a-f]{40}', base) is None or git(root, 'rev-parse', 'HEAD') != base):
        raise ValueError('BASE_NOT_CURRENT_HEAD')
    if Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != root.resolve():
        raise ValueError('CLONE_ROOT_REQUIRED')
    git(root, 'merge-base', '--is-ancestor', ANCHOR, base)
    raw = json.loads(source(root, CONTROL), object_pairs_hook=pairs,
                     parse_constant=lambda _: (_ for _ in ()).throw(ValueError('CONTROL_CONSTANT_INVALID')))
    if (type(raw) is not dict or set(raw) != {'version', 'anchor', 'files', 'prerequisites'}
            or raw['version'] != 'daily-owner-v1' or raw['anchor'] != ANCHOR):
        raise ValueError('CONTROL_INVALID')
    current, prior = entries(raw['files']), entries(raw['prerequisites'])
    if set(current) != set(FILES) or current.get(CONTROL, '') is not None or len(prior) != 20 or set(current) & set(prior):
        raise ValueError('EXACT_PACKAGE_REQUIRED')
    required_prior = {
        'forward_morning_route.py', 'tests/test_forward_morning_route.py',
        'forward_evidence_preserve.py', 'tests/test_forward_evidence_preserve.py',
        'storage_consistent_cut_export.py', 'tests/test_storage_consistent_cut_export.py',
        'storage_cut_native_check.py', 'tests/test_storage_cut_native_check.py',
        'research_forward_cohort.py', 'tests/test_research_forward_cohort.py',
        'programme_agent_team.py', 'tests/test_programme_agent_team.py',
        'MORNING_2026-10-15.md', 'OWNER_CAPTURE_2026-10-15.md',
        'OVERNIGHT_CONTINUITY_2026-10-15.md', 'AGENT_TEAM_2026-10-15.md',
        'continuity_upload_check.py', 'tests/test_continuity_upload_check.py',
        'CONTINUITY_UPLOAD_2026-10-15.md', 'CONTINUITY_UPLOAD_2026-10-15.json',
    }
    if set(prior) != required_prior:
        raise ValueError('EXACT_PREREQUISITES_REQUIRED')
    commitment = '\n'.join(f'{name}:{prior[name]}' for name in sorted(prior)).encode('utf-8')
    if hashlib.sha256(commitment).hexdigest() != PREREQUISITE_SET_SHA256:
        raise ValueError('FROZEN_PREREQUISITE_HASH_REBINDING_REJECTED')
    expected_prior = set() if combined else {f'A\t{name}' for name in prior}
    if set(git(root, 'diff', '--name-status', '--no-renames', ANCHOR, base, '--').splitlines()) != expected_prior:
        raise ValueError('BASE_TREE_NOT_ANCHOR_PLUS_FROZEN_CONTINUITY')
    if git(root, 'diff', '--name-only', '--') or git(root, 'ls-files', '--others', '--exclude-standard'):
        raise ValueError('STAGE_EXACT_PACKAGE_THEN_CHECK')
    staged = set(current) | set(prior) if combined else set(current)
    if set(git(root, 'diff', '--cached', '--name-status', '--no-renames', base, '--').splitlines()) != {f'A\t{name}' for name in staged}:
        raise ValueError('EXACT_STAGED_ADDITIONS_REQUIRED')
    failures = []
    for name, expected in {**prior, **current}.items():
        working = source(root, name)
        actual = digest(working)
        if expected is not None and actual != expected:
            failures.append(dict(path=name, expected=expected, actual=actual))
        index = git(root, 'ls-files', '--stage', '--', name)
        match = re.fullmatch(r'100644 ([0-9a-f]{40}) 0\t' + re.escape(name), index)
        if match is None:
            raise ValueError('REGULAR_STAGE_ZERO_BLOB_REQUIRED')
        size = git(root, 'cat-file', '-s', match[1])
        if re.fullmatch('[0-9]{1,10}', size) is None or int(size) > LIMIT:
            raise ValueError('STAGED_BLOB_TOO_LARGE')
        blob = subprocess.run(['git', '-C', str(root), 'cat-file', 'blob', match[1]],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30).stdout
        if len(blob) != int(size):
            raise ValueError('STAGED_BLOB_SIZE_MISMATCH')
        if digest(blob) != actual:
            failures.append(dict(path=name, expected=digest(blob), actual=actual))
    approved = source(root, 'resilience_policy.sha256').decode('ascii').strip()
    if hashlib.sha256(source(root, 'resilience_policy.json')).hexdigest() != approved:
        raise ValueError('APPROVED_POLICY_BYTES_INVALID')
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--combined', action='store_true', help='Exact33 additions on the unchanged anchor125 only')
    args = parser.parse_args(argv)
    try:
        failures = verify(Path.cwd(), args.base, combined=args.combined)
        print(json.dumps(dict(status='BLOCKED' if failures else 'DAILY_PACKAGE_VERIFIED_REQUIRES_TESTS_AND_EXACT_COMMIT_CI',
            failures=failures, hosted_changes=0), sort_keys=True))
        return 2 if failures else 0
    except Exception as error:
        safe = {'DUPLICATE_CONTROL_FIELD', 'PUBLIC_PATH_INVALID', 'PUBLIC_SOURCE_LINK_REJECTED',
            'PUBLIC_SOURCE_MISSING_OR_TOO_LARGE', 'CONTROL_PINS_INVALID', 'BASE_NOT_CURRENT_HEAD',
            'CLONE_ROOT_REQUIRED', 'CONTROL_CONSTANT_INVALID', 'CONTROL_INVALID', 'EXACT_PACKAGE_REQUIRED',
            'EXACT_PREREQUISITES_REQUIRED', 'BASE_TREE_NOT_ANCHOR_PLUS_FROZEN_CONTINUITY',
            'STAGE_EXACT_PACKAGE_THEN_CHECK', 'EXACT_STAGED_ADDITIONS_REQUIRED',
            'REGULAR_STAGE_ZERO_BLOB_REQUIRED', 'APPROVED_POLICY_BYTES_INVALID',
            'STAGED_BLOB_TOO_LARGE', 'STAGED_BLOB_SIZE_MISMATCH'}
        safe.add('FROZEN_PREREQUISITE_HASH_REBINDING_REJECTED')
        rule = str(error) if isinstance(error, ValueError) and str(error) in safe else 'PUBLIC_PACKAGE_REVIEW_REQUIRED'
        print(json.dumps(dict(status='BLOCKED', rule=rule, hosted_changes=0, raw_error_printed=False)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
