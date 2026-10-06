"""Prepare the reviewed Oct 6 repair in a separate clean checkout; never publish."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Callable

AUDITED_MAIN = '0d78993d28d46db023d83eb29381bec252f8a33e'
GOOD_RELEASE = 'b23323ffaed67129a1e03d87247bfdec789c44f9'
RESTORE = (
    'equity_runtime_health.py', 'mypy-automation.ini', 'production_repository.py',
    'recovery_drill.py', 'release_verification.py',
    'tests/test_archive_maintenance_sql.py', 'tests/test_equity_delivery_repository.py',
    'tests/test_release_packaging.py',
)
MODULES = (
    'catalog_receipts', 'cold_catalog', 'cold_drive_objects',
    'ledger_archive_publication', 'ledger_archive_repository', 'ledger_cold_store',
    'ledger_recovery', 'ledger_runtime_reader', 'ledger_segments',
    'ledger_storage_access', 'local_ledger_recovery', 'storage_policy',
)
TESTS = (
    'catalog_receipts', 'catalog_roots_sql', 'cold_catalog', 'cold_drive_objects',
    'ledger_archive_guards_sql', 'ledger_archive_publication',
    'ledger_archive_repository_sql', 'ledger_cold_store', 'ledger_hot_heads_sql',
    'ledger_recovery_sql', 'ledger_runtime_reader_sql', 'ledger_segments',
    'ledger_segments_sql', 'ledger_storage_access_sql', 'local_ledger_recovery',
    'staged_capture_repair', 'storage_legacy_migration', 'storage_policy',
)
REMOVE_CODE = tuple(name + '.py' for name in MODULES) + tuple(
    'tests/test_' + name + '.py' for name in TESTS)
CACHE = '.iv_history_cache.json'
Git = Callable[[Path, list[str]], str]
ERROR_CODES = frozenset({
    'LOCAL_GIT_FAILED', 'SEPARATE_CHECKOUT_REQUIRED', 'CHECKOUT_ROOT_REQUIRED',
    'MAIN_CHANGED_REVIEW_REQUIRED', 'CLEAN_CHECKOUT_REQUIRED',
    'REPAIR_PATHS_UNVERIFIED', 'REPAIR_PATH_UNSAFE',
    'REPAIR_POSTCONDITION_FAILED_NO_COMMIT',
    'POLICY_CHECKOUT_BYTES_INVALID_RECLONE_LF',
})


class RepairBlocked(RuntimeError):
    """Fixed, credential-free diagnostic for an unverified repair checkout."""


def git(root: Path, args: list[str]) -> str:
    """Local git only, bounded, no shell; never expose raw stderr or configuration."""
    try:
        result = subprocess.run(['git', '-C', str(root), *args], check=True,
                                capture_output=True, text=True, timeout=30)
        return result.stdout
    except (OSError, subprocess.SubprocessError) as from_error:
        raise RepairBlocked('LOCAL_GIT_FAILED') from from_error


def validate(root: Path, run: Git = git) -> None:
    """Require the exact audited clean clone, not the active source workspace."""
    if not root.is_dir() or root.resolve() == Path(__file__).resolve().parent:
        raise RepairBlocked('SEPARATE_CHECKOUT_REQUIRED')
    top = Path(run(root, ['rev-parse', '--show-toplevel']).strip()).resolve()
    if top != root.resolve():
        raise RepairBlocked('CHECKOUT_ROOT_REQUIRED')
    if run(root, ['rev-parse', 'HEAD']).strip() != AUDITED_MAIN:
        raise RepairBlocked('MAIN_CHANGED_REVIEW_REQUIRED')
    if run(root, ['status', '--porcelain']):
        raise RepairBlocked('CLEAN_CHECKOUT_REQUIRED')
    policy = root / 'resilience_policy.json'
    sidecar = root / 'resilience_policy.sha256'
    if (policy.is_symlink() or sidecar.is_symlink()
            or not policy.is_file() or not sidecar.is_file()
            or hashlib.sha256(policy.read_bytes()).hexdigest() != sidecar.read_text().strip()):
        raise RepairBlocked('POLICY_CHECKOUT_BYTES_INVALID_RECLONE_LF')
    run(root, ['merge-base', '--is-ancestor', GOOD_RELEASE, AUDITED_MAIN])
    expected = set(RESTORE + REMOVE_CODE + (CACHE,))
    tracked = set(run(root, ['ls-files', '-z']).split('\0'))
    if not expected <= tracked:
        raise RepairBlocked('REPAIR_PATHS_UNVERIFIED')
    for name in sorted(expected):
        path = root / name
        if not path.is_file() or any(part.is_symlink() for part in (path, *path.parents)):
            raise RepairBlocked('REPAIR_PATH_UNSAFE')


def prepare(root: Path, *, apply: bool = False, run: Git = git) -> dict[str, object]:
    """Restore released code/tests; withdraw drafts; untrack but retain cache on disk."""
    validate(root, run)
    result: dict[str, object] = {
        'status': 'REPAIR_PREVIEW', 'base': GOOD_RELEASE, 'audited_main': AUDITED_MAIN,
        'restore': list(RESTORE), 'withdraw': list(REMOVE_CODE), 'untrack': [CACHE],
        'network_calls': 0, 'hosted_changes': 0, 'commit_created': False,
    }
    if not apply:
        return result
    run(root, ['restore', '--source', GOOD_RELEASE, '--staged', '--worktree', '--', *RESTORE])
    run(root, ['rm', '--', *REMOVE_CODE])
    run(root, ['rm', '--cached', '--', CACHE])
    changed = set(run(root, ['diff', '--cached', '--name-only', '-z']).split('\0')) - {''}
    if changed != set(RESTORE + REMOVE_CODE + (CACHE,)) or not (root / CACHE).is_file():
        raise RepairBlocked('REPAIR_POSTCONDITION_FAILED_NO_COMMIT')
    for name in RESTORE:
        run(root, ['diff', '--exit-code', GOOD_RELEASE, '--', name])
    result['status'] = 'LOCAL_REPAIR_STAGED_NOT_COMMITTED'
    return result


def main(argv: list[str] | None = None) -> int:
    """Preview by default; explicit local application never commits, pushes or dispatches."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', type=Path, required=True)
    parser.add_argument('--apply-local', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = prepare(args.checkout, apply=args.apply_local)
    except Exception as error:
        code = (str(error) if isinstance(error, RepairBlocked) and str(error) in ERROR_CODES
                else 'LOCAL_REPAIR_UNAVAILABLE')
        print(json.dumps({'status': 'BLOCKED', 'code': code, 'commit_created': False,
                          'hosted_changes': 0}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
