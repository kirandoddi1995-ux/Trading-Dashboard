"""Exact reviewed checkout-diagnostics follow-up on the green d5cd80f tree.

Read-only public source/Git checks. Historical manifests remain unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from daily_owner_upload_check import digest, git, pairs, source

BASE = 'd5cd80f41a52de902d23cb81d761e7bb720e710c'
CONTROL = 'DAILY_SETUP_REPAIR_UPLOAD_2026-10-15.json'
MODIFIED = ('forward_daily_owner.ps1', 'tests/test_forward_daily_owner.py',
            'FRIDAY_CAPTURE_2026-10-16.md')
ADDED = ('daily_setup_repair_upload_check.py', 'tests/test_daily_setup_repair_upload_check.py',
         'DAILY_SETUP_REPAIR_UPLOAD_2026-10-15.md', CONTROL)
PRIOR = ('daily_owner_upload_check.py', 'forward_daily_contract.py',
         'resilience_policy.json', 'resilience_policy.sha256',
         'CONTINUITY_UPLOAD_2026-10-15.json', 'DAILY_OWNER_UPLOAD_2026-10-15.json')


def pins(value: object, names: tuple[str, ...]) -> dict[str, str | None]:
    if type(value) is not list:
        raise ValueError('CONTROL_PINS_INVALID')
    result: dict[str, str | None] = {}
    for item in value:
        if type(item) is not dict or set(item) != {'path', 'sha256_lf'}:
            raise ValueError('CONTROL_PINS_INVALID')
        name, sha = item['path'], item['sha256_lf']
        if (type(name) is not str or name not in names or name in result
                or (sha is None and name != CONTROL)
                or (sha is not None and (type(sha) is not str or re.fullmatch('[0-9a-f]{64}', sha) is None))):
            raise ValueError('CONTROL_PINS_INVALID')
        result[name] = sha
    if set(result) != set(names):
        raise ValueError('EXACT_PACKAGE_REQUIRED')
    return result


def blob(root: Path, revision: str) -> bytes:
    oid = git(root, 'rev-parse', revision)
    if re.fullmatch('[0-9a-f]{40}', oid) is None:
        raise ValueError('PUBLIC_BLOB_INVALID')
    size = git(root, 'cat-file', '-s', oid)
    if re.fullmatch('[0-9]{1,10}', size) is None or int(size) > 2 * 1024 * 1024:
        raise ValueError('PUBLIC_BLOB_INVALID')
    value = subprocess.run(['git', '-C', str(root), 'cat-file', 'blob', oid], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30).stdout
    if len(value) != int(size):
        raise ValueError('PUBLIC_BLOB_INVALID')
    return value


def verify(root: Path, base: str) -> list[dict[str, str]]:
    if base != BASE or git(root, 'rev-parse', 'HEAD') != BASE:
        raise ValueError('EXACT_GREEN_BASE_REQUIRED')
    if Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != root.resolve():
        raise ValueError('CLONE_ROOT_REQUIRED')
    if git(root, 'diff', '--name-only', '--') or git(root, 'ls-files', '--others', '--exclude-standard'):
        raise ValueError('STAGE_EXACT_PACKAGE_THEN_CHECK')
    expected = {f'M\t{name}' for name in MODIFIED} | {f'A\t{name}' for name in ADDED}
    if set(git(root, 'diff', '--cached', '--name-status', '--no-renames', BASE, '--').splitlines()) != expected:
        raise ValueError('EXACT_SEVEN_PATHS_REQUIRED')
    control = json.loads(source(root, CONTROL), object_pairs_hook=pairs)
    if (type(control) is not dict or set(control) != {'version', 'base', 'files', 'prerequisites'}
            or control['version'] != 'daily-setup-diagnostics-v1' or control['base'] != BASE):
        raise ValueError('CONTROL_INVALID')
    current = pins(control['files'], MODIFIED + ADDED)
    prior = pins(control['prerequisites'], PRIOR)
    if current[CONTROL] is not None:
        raise ValueError('CONTROL_SELF_PIN_INVALID')
    failures: list[dict[str, str]] = []
    for name, expected_hash in {**prior, **current}.items():
        actual = digest(source(root, name))
        if name in prior and digest(blob(root, f'{BASE}:{name}')) != expected_hash:
            raise ValueError('PREREQUISITE_REBINDING_REJECTED')
        if expected_hash is not None and actual != expected_hash:
            failures.append(dict(path=name, expected=expected_hash, actual=actual))
        stage = git(root, 'ls-files', '--stage', '--', name)
        if re.fullmatch(r'100644 [0-9a-f]{40} 0\t' + re.escape(name), stage) is None:
            raise ValueError('REGULAR_STAGE_ZERO_BLOB_REQUIRED')
        staged_hash = digest(blob(root, ':' + name))
        if actual != staged_hash:
            failures.append(dict(path=name, expected=staged_hash, actual=actual))
    approved = source(root, 'resilience_policy.sha256').decode('ascii').strip()
    if hashlib.sha256(source(root, 'resilience_policy.json')).hexdigest() != approved:
        raise ValueError('APPROVED_POLICY_BYTES_INVALID')
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    args = parser.parse_args(argv)
    try:
        failures = verify(Path.cwd(), args.base)
        print(json.dumps(dict(status='BLOCKED' if failures else 'SETUP_DIAGNOSTICS_PACKAGE_VERIFIED_REQUIRES_EXACT_COMMIT_CI',
                              failures=failures, hosted_changes=0), sort_keys=True))
        return 2 if failures else 0
    except Exception as error:
        safe = {'EXACT_GREEN_BASE_REQUIRED', 'CLONE_ROOT_REQUIRED', 'STAGE_EXACT_PACKAGE_THEN_CHECK',
                'EXACT_SEVEN_PATHS_REQUIRED', 'CONTROL_INVALID', 'CONTROL_PINS_INVALID',
                'EXACT_PACKAGE_REQUIRED', 'CONTROL_SELF_PIN_INVALID', 'PUBLIC_BLOB_INVALID',
                'PREREQUISITE_REBINDING_REJECTED', 'REGULAR_STAGE_ZERO_BLOB_REQUIRED',
                'APPROVED_POLICY_BYTES_INVALID', 'DUPLICATE_CONTROL_FIELD', 'PUBLIC_PATH_INVALID',
                'PUBLIC_SOURCE_LINK_REJECTED', 'PUBLIC_SOURCE_MISSING_OR_TOO_LARGE'}
        rule = str(error) if isinstance(error, ValueError) and str(error) in safe else 'PUBLIC_PACKAGE_REVIEW_REQUIRED'
        print(json.dumps(dict(status='BLOCKED', rule=rule, raw_error_printed=False, hosted_changes=0)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
