"""Exact reviewed overnight groups; current HEAD and full dependency pins required."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from overnight_upload_check import pairs
from reviewed_upload_check import git

MANIFESTS = {'future_ops': 'FUTURE_OPS_UPLOAD_2026-10-14.json',
             'application': 'RESEARCH_WORKBENCH_UPLOAD_2026-10-14.json'}
MAX_BYTES = 4 * 1024 * 1024

# Explicit destination sets are review controls, not caller-selected file lists.
GROUP_FILES = {
    'future_ops': ('future_ops_diagnostics.py', 'future_ops_task.ps1',
        'requirements-forward-operations.txt', 'tests/test_future_ops_diagnostics.py',
        'FUTURE_OPERATIONS_REPAIR.md', 'MORNING_CARD_2026-10-14.md',
        'overnight_programme_upload_check.py', 'tests/test_overnight_programme_upload_check.py',
        'FUTURE_OPS_UPLOAD_2026-10-14.md', 'FUTURE_OPS_UPLOAD_2026-10-14.json'),
    'application': ('app.py', 'equity_runtime_health.py', 'package_release.py',
        'research_workbench.py', 'research_workbench_ui.py', 'research_assistant.py',
        'tests/test_research_workbench.py', 'tests/test_research_workbench_ui.py',
        'tests/test_research_assistant.py', 'tests/test_streamlit_boot.py', 'RESEARCH_WORKBENCH_METHODS.md',
        'LLM_PROVIDER_DECISION_2026-10-14.md', 'RESEARCH_BACKFILL_RIGHTS_2026-10-14.md',
        'OVERNIGHT_DECISIONS_2026-10-14.md', 'OVERNIGHT_ACCEPTANCE_2026-10-14.md',
        'RESEARCH_WORKBENCH_UPLOAD_2026-10-14.md', 'RESEARCH_WORKBENCH_UPLOAD_2026-10-14.json'),
}
GROUP_SEEDS = {'future_ops': ('future_ops_diagnostics.py', 'forward_session_ops.py', 'overnight_programme_upload_check.py'),
               'application': ('app.py', 'equity_runtime_health.py', 'package_release.py',
                   'research_workbench.py', 'research_workbench_ui.py', 'research_assistant.py',
                   'overnight_programme_upload_check.py')}
EXTRA_PINS = ('constraints.txt', 'requirements.txt', 'requirements-archive.txt',
              'requirements-option-capture.txt', 'tests/test_streamlit_boot.py')


def public_path(root: Path, name: object) -> Path:
    """Restrict reads to explicitly public source/document/manifest paths."""
    if not isinstance(name, str) or re.fullmatch(r'(?:tests/)?[A-Za-z0-9_-]+\.(?:py|md|txt|ps1|json)', name) is None:
        raise ValueError('PUBLIC_SOURCE_PATH_REQUIRED')
    if name.endswith('.json') and name not in MANIFESTS.values():
        raise ValueError('PUBLIC_SOURCE_PATH_REQUIRED')
    if name != 'managed_secrets.py' and any(v in name.lower() for v in ('secret', 'token')):
        raise ValueError('PUBLIC_SOURCE_PATH_REQUIRED')
    current = root
    for part in name.split('/'):
        current /= part
        if current.is_symlink() or current.is_junction():
            raise ValueError('SOURCE_LINK_REJECTED')
    if not current.is_file() or current.stat().st_size > MAX_BYTES:
        raise ValueError('SOURCE_MISSING_OR_TOO_LARGE')
    return current


def guarded_members(root: Path, seeds: list[str]) -> set[str]:
    """Flat public modules only; validate before reading, never traverse packages."""
    index = {p.stem: p.name for p in root.iterdir() if p.suffix == '.py'}
    selected: set[str] = set()
    pending = list(seeds)
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        path = public_path(root, name)
        selected.add(name)
        if path.suffix != '.py':
            continue
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        requested: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                requested.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    raise ValueError('PUBLIC_SOURCE_PATH_REQUIRED')
                requested.append(node.module or '')
            elif isinstance(node, ast.Call) and node.args:
                label = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ''
                if label in ('__import__', 'import_module') and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    if node.args[0].value.startswith('.'):
                        raise ValueError('PUBLIC_SOURCE_PATH_REQUIRED')
                    requested.append(node.args[0].value)
        for target in requested:
            top = target.split('.')[0]
            if top in index:
                pending.append(index[top])
            elif top and (root / top).exists():
                # This reviewed repository has no importable local packages.
                # A new package requires a separately reviewed discovery contract.
                raise ValueError('PUBLIC_SOURCE_PATH_REQUIRED')
    return selected


def index_matches(root: Path, names: set[str]) -> list[dict[str, str]]:
    """Bind upload bytes to the staged index, even with assume-unchanged flags."""
    failures: list[dict[str, str]] = []
    for name in sorted(names):
        working = public_path(root, name).read_bytes().replace(b'\r\n', b'\n')
        response = subprocess.run(['git', 'show', ':' + name], cwd=root, check=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
        staged = response.stdout.replace(b'\r\n', b'\n')
        expected, actual = hashlib.sha256(working).hexdigest(), hashlib.sha256(staged).hexdigest()
        if len(staged) > MAX_BYTES or expected != actual:
            failures.append({'path': name, 'expected': expected, 'actual': actual})
    return failures


def verify(root: Path, group: str, changed: set[str]) -> list[dict[str, str]]:
    """Recompute complete local imports; never trust an omitted manifest pin."""
    if group not in MANIFESTS:
        raise ValueError('GROUP_INVALID')
    control = MANIFESTS[group]
    manifest: Any = json.loads(public_path(root, control).read_bytes(), object_pairs_hook=pairs)
    if not isinstance(manifest, dict) or set(manifest) != {'version', 'group', 'files', 'seeds', 'prerequisites', 'extra_pins'} or manifest['version'] != 'overnight-programme-v1':
        raise ValueError('MANIFEST_INVALID')
    if manifest['group'] != group:
        raise ValueError('GROUP_INVALID')
    plan = manifest
    for key in ('files', 'prerequisites'):
        values = plan[key]
        if not isinstance(values, list) or not values or any(not isinstance(v, dict) or set(v) != {'destination', 'sha256_lf'} for v in values):
            raise ValueError('EXACT_PINS_REQUIRED')
        entry_names = [v['destination'] for v in values]
        if any(not isinstance(v, str) for v in entry_names) or len(set(entry_names)) != len(entry_names):
            raise ValueError('EXACT_PINS_REQUIRED')
    names = {v['destination'] for v in plan['files']}
    if names != changed or names != set(GROUP_FILES[group]):
        raise ValueError('EXACT_PACKAGE_REQUIRED')
    if any(not isinstance(plan[k], list) or not plan[k] or any(not isinstance(n, str) for n in plan[k]) for k in ('seeds', 'extra_pins')):
        raise ValueError('MANIFEST_INVALID')
    if tuple(plan['seeds']) != GROUP_SEEDS[group] or tuple(plan['extra_pins']) != EXTRA_PINS:
        raise ValueError('EXACT_PINS_REQUIRED')
    for n in (*plan['seeds'], *plan['extra_pins']):
        public_path(root, n)
    closure = guarded_members(root, plan['seeds'])
    required = (closure | set(plan['extra_pins'])) - names
    if {v['destination'] for v in plan['prerequisites']} != required:
        raise ValueError('EXACT_PINS_REQUIRED')
    failures: list[dict[str, str]] = []
    for item in plan['files'] + plan['prerequisites']:
        path = item['destination']
        content = public_path(root, path).read_bytes().replace(b'\r\n', b'\n')
        expected = item['sha256_lf']
        if path == control and expected is None:
            continue
        if not isinstance(expected, str) or re.fullmatch('[0-9a-f]{64}', expected) is None:
            raise ValueError('MANIFEST_HASH_INVALID')
        actual = hashlib.sha256(content).hexdigest()
        if expected != actual:
            failures.append({'path': path, 'expected': expected, 'actual': actual})
    return failures


def main(argv: list[str] | None = None) -> int:
    """Read-only Git check. Every package uses the newest exact green merged HEAD."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--group', required=True, choices=('future_ops', 'application'))
    args = parser.parse_args(argv)
    safe = {'PUBLIC_SOURCE_PATH_REQUIRED', 'SOURCE_LINK_REJECTED', 'SOURCE_MISSING_OR_TOO_LARGE',
            'MANIFEST_INVALID', 'GROUP_INVALID', 'EXACT_PINS_REQUIRED', 'EXACT_PACKAGE_REQUIRED',
            'MANIFEST_HASH_INVALID', 'BASE_NOT_CURRENT_HEAD', 'STAGE_THEN_RECHECK', 'CLONE_ROOT_REQUIRED'}
    try:
        root = Path.cwd()
        if any(p.is_symlink() or p.is_junction() for p in (root, *root.parents)):
            raise ValueError('CLONE_ROOT_REQUIRED')
        if re.fullmatch('[0-9a-f]{40}', args.base) is None or git(root, 'rev-parse', 'HEAD') != args.base:
            raise ValueError('BASE_NOT_CURRENT_HEAD')
        if Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != root.resolve():
            raise ValueError('CLONE_ROOT_REQUIRED')
        if git(root, 'diff', '--name-only', '--'):
            raise ValueError('STAGE_THEN_RECHECK')
        if git(root, 'ls-files', '--others', '--exclude-standard'):
            raise ValueError('STAGE_THEN_RECHECK')
        changed = set(git(root, 'diff', '--cached', '--name-only', args.base, '--').splitlines())
        failures = verify(root, args.group, changed)
        if not failures:
            indexed = changed | guarded_members(root, list(GROUP_SEEDS[args.group])) | set(EXTRA_PINS)
            failures = index_matches(root, indexed)
        print(json.dumps({'status': 'BLOCKED' if failures else 'UPLOAD_FILES_VERIFIED_REQUIRES_TESTS_AND_CI',
                          'failures': failures, 'hosted_changes': 0}))
        return 2 if failures else 0
    except Exception as error:
        print(json.dumps({'status': 'BLOCKED', 'rule': str(error) if isinstance(error, ValueError) and str(error) in safe else 'UPLOAD_REVIEW_REQUIRED', 'hosted_changes': 0}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
