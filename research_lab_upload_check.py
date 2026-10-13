"""Exact reviewed Research Lab package; read-only Git/index and public-byte checks."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import cast

from overnight_upload_check import (SAFE_RULES, UploadCheckFailure, pairs,
    path_name as public_path_name, source as public_source)
from reviewed_upload_check import git

MANIFEST = 'RESEARCH_LAB_UPLOAD_2026-10-13.json'
FILES = ('app.py', 'equity_runtime_health.py', 'package_release.py', 'research_lab.py', 'research_lab_ui.py',
    'research_lab_grounding.py', 'research_lab_statistics.py', 'research_lab_upload_check.py',
    'tests/test_research_lab.py', 'tests/test_research_lab_grounding.py',
    'tests/test_research_lab_statistics.py', 'tests/test_research_lab_upload_check.py',
    'tests/test_streamlit_boot.py', 'RESEARCH_LAB_DESIGN_2026-10-13.md',
    'PROGRAMME_RECONCILIATION_2026-10-13.md', 'RESEARCH_LAB_UPLOAD_2026-10-13.md', MANIFEST)


def path_name(value: object) -> str:
    """One exact public code-module exception, never an actual secrets file."""
    return 'managed_secrets.py' if value == 'managed_secrets.py' else public_path_name(value)


class LabUploadFailure(UploadCheckFailure):
    """Same redacted diagnostics, with the exact public code-name exception."""

    def __init__(self, rule: str, failures: list[dict[str, str]]) -> None:
        if rule not in SAFE_RULES:
            raise ValueError('MANIFEST_INVALID')
        clean: list[dict[str, str]] = []
        for failure in failures:
            if set(failure) not in ({'path'}, {'path', 'kind', 'expected', 'actual'}):
                raise ValueError('MANIFEST_INVALID')
            item = {'path': path_name(failure['path'])}
            if 'kind' in failure:
                if failure['kind'] not in ('package_file', 'prerequisite') or any(
                        re.fullmatch('[0-9a-f]{64}', failure[key]) is None for key in ('expected', 'actual')):
                    raise ValueError('MANIFEST_INVALID')
                item.update({key: failure[key] for key in ('kind', 'expected', 'actual')})
            clean.append(item)
        self.rule, self.failures = rule, clean
        ValueError.__init__(self, rule)


def source(root: Path, value: object) -> Path:
    """Keep linkage/size guards for the public secret-access CODE prerequisite."""
    if value != 'managed_secrets.py':
        return public_source(root, value)
    path = root / 'managed_secrets.py'
    if path.is_symlink() or path.is_junction():
        raise LabUploadFailure('SOURCE_LINK_REJECTED', [{'path': 'managed_secrets.py'}])
    if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('SOURCE_MISSING_OR_TOO_LARGE')
    return path


def entries(value: object) -> list[dict[str, object]]:
    """Validate exact entry shape and unique safe destinations before any read."""
    if not isinstance(value, list) or not 1 <= len(value) <= 200:
        raise ValueError('MANIFEST_ENTRIES_INVALID')
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {'destination', 'sha256_lf'}:
            raise ValueError('MANIFEST_ENTRIES_INVALID')
        entry = cast(dict[str, object], item)
        name = path_name(entry['destination'])
        if name in seen:
            raise ValueError('MANIFEST_ENTRIES_INVALID')
        seen.add(name)
        result.append(entry)
    return result


def verify(root: Path, changed: set[str]) -> None:
    """Exact files and all pinned prerequisites; no weak or removed historical pins."""
    raw: object = json.loads(source(root, MANIFEST).read_bytes(), object_pairs_hook=pairs)
    if not isinstance(raw, dict):
        raise ValueError('MANIFEST_INVALID')
    manifest = cast(dict[str, object], raw)
    if (set(manifest) != {'version', 'files', 'prerequisites'}
            or manifest['version'] != 'research-lab-reviewed-upload-v1'):
        raise ValueError('MANIFEST_INVALID')
    files = entries(manifest['files'])
    prerequisites = entries(manifest['prerequisites'])
    if set(FILES) != changed or {v['destination'] for v in files} != set(FILES):
        raise ValueError('EXACT_UPLOAD_PATHS_REQUIRED')
    if {v['destination'] for v in prerequisites} & set(FILES):
        raise ValueError('PREREQUISITE_OVERLAP')
    failures: list[dict[str, str]] = []
    for item in files + prerequisites:
        name = path_name(item['destination'])
        content = source(root, name).read_bytes().replace(b'\r\n', b'\n')
        expected = item['sha256_lf']
        if name == MANIFEST and expected is None:
            continue  # A control file cannot recursively hash itself.
        if not isinstance(expected, str) or re.fullmatch('[0-9a-f]{64}', expected) is None:
            raise LabUploadFailure('MANIFEST_HASH_INVALID', [{'path': name}])
        actual = hashlib.sha256(content).hexdigest()
        if expected != actual:
            failures.append({'path': name, 'kind': 'package_file' if item in files else 'prerequisite',
                'expected': expected, 'actual': actual})
    if failures:
        raise LabUploadFailure('SOURCE_HASH_MISMATCH', failures)


def main(argv: list[str] | None = None) -> int:
    """Print safe public path/hash metadata only; never arbitrary exception text."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        if re.fullmatch('[0-9a-f]{40}', args.base) is None:
            raise ValueError('BASE_SHA_INVALID')
        if any(p.is_symlink() or p.is_junction() for p in (args.root, *args.root.parents)):
            raise ValueError('CLONE_ROOT_REQUIRED')
        root = args.root.resolve(strict=True)
        if git(root, 'rev-parse', 'HEAD') != args.base:
            raise ValueError('BASE_NOT_CURRENT_HEAD')
        if Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != root:
            raise ValueError('CLONE_ROOT_REQUIRED')
        if git(root, 'diff', '--name-only', '--'):
            raise ValueError('INDEX_WORKTREE_MISMATCH_STAGE_THEN_RECHECK')
        changed = set(git(root, 'diff', '--name-only', args.base, '--').splitlines())
        changed.update(git(root, 'ls-files', '--others', '--exclude-standard').splitlines())
        verify(root, changed)
        print(json.dumps({'status': 'UPLOAD_FILES_VERIFIED_REQUIRES_TESTS_AND_CI',
            'base': args.base, 'hosted_changes': 0, 'approval_authority': False}))
        return 0
    except Exception as error:
        rule, failures = 'UNCLASSIFIED_UPLOAD_FAILURE', []
        if isinstance(error, UploadCheckFailure):
            rule, failures = error.rule, error.failures
        elif isinstance(error, json.JSONDecodeError):
            rule = 'MANIFEST_JSON_INVALID'
        elif isinstance(error, ValueError) and str(error) in SAFE_RULES:
            rule = str(error)
        print(json.dumps({'status': 'BLOCKED', 'rule': rule, 'failures': failures,
            'hosted_changes': 0, 'approval_authority': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
