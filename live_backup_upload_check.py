"""Exact-base backup/security replacement verification. Public source only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

from programme_next_upload_check import git, safe_read, sha, unique

BASE = '563665a32e5454633b0c27256072a7249503c520'
MANIFEST = 'LIVE_BACKUP_UPLOAD.json'
VERSION = 'live-backup-upload-v2-security'
FILES = ('live_database_backup.py', 'live_backup_conformance.py',
    'tests/test_live_database_backup.py', 'tests/test_live_backup_conformance.py',
    '.github/workflows/live-backup-conformance.yml', 'live_backup_upload_check.py',
    'tests/test_live_backup_upload_check.py', 'LIVE_BACKUP_HANDOFF_2026-10-21.md',
    'tests/test_dependency_security.py', 'DEPENDENCY_SECURITY_HANDOFF_2026-10-21.md',
    'constraints.txt',
    '.github/workflows/quality.yml',
    'tests/test_archive_verify_upload_check.py',
    'tests/test_commissioning_next_upload_check.py',
    'tests/test_legacy_rehearsal_upload_check.py',
    'tests/test_recovery_incident_upload_check.py',
    'tests/test_outcomes_footer_upload_check.py',
    'tests/test_outcomes_large_upload_check.py',
    'tests/test_archive_preservation_upload_check.py',
    'tests/test_outcomes_private_upload_check.py',
    'tests/test_preservation_integer_upload_check.py',
    'tests/test_outcomes_readonly_upload_check.py',
    'tests/test_recovery_contract_upload_check.py',
    'requirements-forward-operations.txt', 'future_ops_diagnostics.py',
    MANIFEST)
MODIFIED_BASE_HASHES = {
    'requirements-forward-operations.txt': '318ef73a86c751271f2805c443b4a4646a1188cf5d4cbb6575cf467a0e92994c',
    'future_ops_diagnostics.py': '7a0594cad1dedf4b0df4d8b66841320d467724cff29900952e04ff4ab07e92d9',
    'constraints.txt': '433d34cc1146a838c792b8b417acefed300895a3543d62a295cb00c2791a7ba3',
    '.github/workflows/quality.yml': '25cf80f6227ec5745e50fe987425f4db5d54193431b09fa8cc82bc70b185115a',
    'tests/test_archive_verify_upload_check.py': 'd669d106201ba5437a21657287cce8ff56773ef2bbdc017a5a28c30d0ddf57f5',
    'tests/test_commissioning_next_upload_check.py': '0e9bfece13c8d83bfa6b672e2ad30ae0e41b2ab3371e621e8e12cf1fa8a49689',
    'tests/test_legacy_rehearsal_upload_check.py': 'aef21d242ad8cf929791a9348b4ac68536ff0646d12a55301441cb8b32901e9d',
    'tests/test_recovery_incident_upload_check.py': 'c8f6410c1f02310525cf29d39246348e864b6299c36d5cdcad231745c1b9258f',
    'tests/test_outcomes_footer_upload_check.py': 'af00dd1b60f426b1af515a645d212023f7b71bd463691e8a32f32101914fc3a4',
    'tests/test_outcomes_large_upload_check.py': 'e611a9261be01922c527b8dea351b64102c7eef56931351307f49bf0aae7aa8c',
    'tests/test_archive_preservation_upload_check.py': '6c1362558a20ad267f22af87c56ee4bc50e79e1ede849549cdd9a80f0073111b',
    'tests/test_outcomes_private_upload_check.py': '20cc0798916f81794241ea5f109d0d55128e3eded6f409a7714c9523ccbe89c2',
    'tests/test_preservation_integer_upload_check.py': 'eeb63e74c2a2c830d9b8f67ff59e18bac7e5310bc3cfc070333a8b0dd28600c8',
    'tests/test_outcomes_readonly_upload_check.py': 'ed801cc9c315e87f14ffd49177e5c176c87055f11f62eb98623a7e657c85e1ee',
    'tests/test_recovery_contract_upload_check.py': '96c6fb6d714692ad5ba3527c262ae99cc144c71abb04ff562cf1bf30c7923d21',
}
PREREQUISITES = {
    'programme_next_upload_check.py': 'c975be41f99994b2159e1e19b699fb1b71e6699e186bb6bb19e711adfcd01a81',
    'archive_preservation_inventory.py': 'ec497442d9e5d779584a5153db6b15bcea07fe58b2fd2c79889ac8083b69de27',
    'archive_preservation_witness.py': '6348101f6e1ed5789854ee700539e2ca078b030c7b5a500d0d9a3901e05570cc',
    'archive_restore_policy.py': 'dab6613432f93f473d585535df63b2d4102d9010d35b6889898dc9f1e6124c25',
    'archive_recovery_binding.py': '7a267a61bdf681ee7b3195576d025810182950674fe57ea304c83048330d5910',
    'project_conductor.py': 'f318b5ca3c14d00f34c3780c2384fcc45f243e3c1fcede54515e6227c9a858bb',
    'programme_agent_team.py': 'b66d5ba6f366f2edfda299bbdb7340a2c8ce6a53a8e797d80c86aca7ca227e5a',
    'tests/test_workflow_runtimes.py': '008779697c5507bfb0feb70160bf3251f840bd08f72d08a67b5c2329a3d07415',
    'RECOVERY_CONTRACT_UPLOAD.json': '377ed1544ec06cdf39ed5b1ffd4e703a5bb8f44183958b2b1b920bf253cf016b',
}
SECURITY_PIN_SUCCESSORS = {
    'constraints.txt': 'de193df5d74ce93e8583c732317cc6553e9c9543156f64fd416c88e6c3bc2454',
    'requirements-forward-operations.txt': '8a4258900e3e8a7aaaac288da454c0d8b527a046e4c29b214daefe57f237b369',
    'future_ops_diagnostics.py': 'ab9241605a8e1d92f91178173e1385e94716626504e4aaad4c2e6399368b7c29',
}


def reviewed_successor_hash(root: Path, name: str, original: str) -> str:
    """One explicit security transition for current-tree historical self-tests.

    Historical manifests/upload admission remain immutable. A known predecessor
    MUST match; unknown paths are never enrolled or relaxed. External exact-SHA
    CI and the staged checker bind the successor manifest to the reviewed commit.
    """
    if name not in MODIFIED_BASE_HASHES:
        return original
    if original != MODIFIED_BASE_HASHES[name]:
        raise ValueError('SECURITY_PREDECESSOR_MISMATCH')
    value = json.loads(safe_read(root / MANIFEST), object_pairs_hook=unique)
    if (type(value) is not dict or set(value) != {'version', 'base', 'files', 'prerequisites'}
            or value['version'] != VERSION or value['base'] != BASE
            or type(value['files']) is not dict or set(value['files']) != set(FILES)
            or value['files'][MANIFEST] is not None or value['prerequisites'] != PREREQUISITES):
        raise ValueError('SECURITY_SUCCESSOR_CONTRACT_INVALID')
    result = value['files'][name]
    if type(result) is not str or re.fullmatch('[a-f0-9]{64}', result) is None:
        raise ValueError('SECURITY_SUCCESSOR_HASH_REQUIRED')
    if name in SECURITY_PIN_SUCCESSORS and result != SECURITY_PIN_SUCCESSORS[name]:
        raise ValueError('SECURITY_FIXED_SUCCESSOR_REQUIRED')
    return result


def check(root: Path, base: str) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    try:
        if base != BASE or git(root, 'rev-parse', 'HEAD').decode().strip() != BASE:
            raise ValueError('EXACT_BASE_REQUIRED')
        if Path(git(root, 'rev-parse', '--show-toplevel').decode().strip()).resolve() != root.resolve():
            raise ValueError('CHECKOUT_ROOT_REQUIRED')
        raw = safe_read(root / MANIFEST)
        value = json.loads(raw, object_pairs_hook=unique)
        if (type(value) is not dict or set(value) != {'version', 'base', 'files', 'prerequisites'}
                or value['version'] != VERSION or value['base'] != BASE
                or type(value['files']) is not dict or set(value['files']) != set(FILES)
                or value['files'][MANIFEST] is not None or value['prerequisites'] != PREREQUISITES):
            raise ValueError('MANIFEST_CONTRACT_INVALID')
        for name in FILES:
            if name != MANIFEST:
                expected = value['files'][name]
                if name in SECURITY_PIN_SUCCESSORS and expected != SECURITY_PIN_SUCCESSORS[name]:
                    raise ValueError('SECURITY_FIXED_SUCCESSOR_REQUIRED')
                actual = sha(safe_read(root / name))
                staged = sha(git(root, 'show', ':' + name))
                if actual != expected or staged != expected:
                    failures.append(dict(rule='PAYLOAD_HASH_MISMATCH', path=name,
                        expected=expected, actual=actual, staged=staged))
        for name, expected in MODIFIED_BASE_HASHES.items():
            actual = sha(git(root, 'show', BASE + ':' + name))
            if actual != expected:
                failures.append(dict(rule='MODIFIED_BASE_HASH_MISMATCH', path=name,
                    expected=expected, actual=actual))
        for name, expected in PREREQUISITES.items():
            for location, raw_file in (('base', git(root, 'show', BASE + ':' + name)),
                    ('index', git(root, 'show', ':' + name)), ('worktree', safe_read(root / name))):
                actual = sha(raw_file)
                if actual != expected:
                    failures.append(dict(rule='PREREQUISITE_HASH_MISMATCH', path=name,
                        location=location, expected=expected, actual=actual))
        if set(git(root, 'diff', '--cached', '--name-status', BASE, '--').decode().splitlines()) != {
                ('M' if name in MODIFIED_BASE_HASHES else 'A') + '\t' + name for name in FILES}:
            raise ValueError('EXACT_REVIEWED_PATHS_REQUIRED')
        entries = git(root, 'ls-files', '--stage', '--', *FILES).decode().splitlines()
        if len(entries) != len(FILES) or any(not row.startswith('100644 ') or ' 0\t' not in row for row in entries):
            raise ValueError('REGULAR_STAGE_ZERO_REQUIRED')
        if git(root, 'diff', '--name-only', '--').strip() or git(root, 'ls-files', '--others', '--exclude-standard').strip():
            raise ValueError('UNSTAGED_OR_UNTRACKED_FILES')
        if git(root, 'show', ':' + MANIFEST) != raw:
            raise ValueError('MANIFEST_INDEX_MISMATCH')
    except Exception as error:
        allowed = ('EXACT_BASE_REQUIRED', 'CHECKOUT_ROOT_REQUIRED', 'MANIFEST_CONTRACT_INVALID',
            'SECURITY_FIXED_SUCCESSOR_REQUIRED',
            'EXACT_REVIEWED_PATHS_REQUIRED', 'REGULAR_STAGE_ZERO_REQUIRED',
            'UNSTAGED_OR_UNTRACKED_FILES', 'MANIFEST_INDEX_MISMATCH', 'DUPLICATE_MANIFEST_KEY',
            'PACKAGE_LINK_REJECTED', 'GIT_READ_FAILED', 'BOUNDED_REGULAR_FILE_REQUIRED',
            'PUBLIC_FILE_IDENTITY_CHANGED')
        rule = next((code for code in allowed if type(error) is ValueError and error.args == (code,)),
                    'PACKAGE_READ_FAILED')
        failures.append(dict(rule=rule))
    return dict(status='BLOCKED' if failures else 'LIVE_BACKUP_PACKAGE_VERIFIED_REQUIRES_EXACT_COMMIT_CI',
        failures=failures, hosted_changes=0, run_authorised=False,
        custody_verified=False, restore_verified=False, deletion_authorised=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    result = check(Path.cwd(), parser.parse_args().base)
    print(json.dumps(result, sort_keys=True))
    return 2 if result['failures'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
