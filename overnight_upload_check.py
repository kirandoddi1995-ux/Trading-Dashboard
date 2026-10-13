"""Read-only, exact-tree upload checks; manifests are reviewed control files, not signatures."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import cast

from reviewed_upload_check import git

GROUPS = ('capture', 'operations', 'storage', 'research')

# Only fixed public rule names reach stdout; never exception text, Git stderr,
# absolute paths, connection strings or the contents of a manifest.
SAFE_RULES = frozenset({
    'PATH_INVALID', 'SOURCE_LINK_REJECTED', 'SOURCE_MISSING_OR_TOO_LARGE',
    'MANIFEST_DUPLICATE_KEY', 'MANIFEST_ENTRIES_INVALID', 'GROUP_INVALID',
    'MANIFEST_INVALID', 'MANIFEST_JSON_INVALID', 'EXACT_UPLOAD_PATHS_REQUIRED', 'PREREQUISITE_OVERLAP',
    'MANIFEST_HASH_INVALID', 'SOURCE_HASH_MISMATCH', 'BASE_SHA_INVALID',
    'CLONE_ROOT_REQUIRED', 'BASE_NOT_CURRENT_HEAD',
    'INDEX_WORKTREE_MISMATCH_STAGE_THEN_RECHECK',
})


class UploadCheckFailure(ValueError):
    """Allowlisted rule and public-file metadata, never arbitrary error text."""

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
                        re.fullmatch('[0-9a-f]{64}', failure[key]) is None
                        for key in ('expected', 'actual')):
                    raise ValueError('MANIFEST_INVALID')
                item.update({key: failure[key] for key in ('kind', 'expected', 'actual')})
            clean.append(item)
        self.rule = rule
        self.failures = clean
        super().__init__(rule)


def path_name(value: object) -> str:
    """Only explicit public code/document destinations; no credential files."""
    if not isinstance(value, str) or not value:
        raise ValueError('PATH_INVALID')
    path = PurePosixPath(value)
    if (path.is_absolute() or value != path.as_posix() or '\\' in value or ':' in value
            or '..' in path.parts or any(part.startswith('.') for part in path.parts)
            and value not in ('.github/workflows/overnight-research-offline.yml',
                              '.github/workflows/overnight-storage-native.yml')
            or path.suffix not in ('.py', '.md', '.json', '.sql', '.txt', '.yml')
            or any(word in value.lower() for word in ('secrets', 'client_secret', 'token.json'))):
        raise ValueError('PATH_INVALID')
    return value


def source(root: Path, value: object) -> Path:
    """Reject every linked component and oversized inputs before reading."""
    name = path_name(value)
    current = root
    for part in PurePosixPath(name).parts:
        current /= part
        if current.is_symlink() or current.is_junction():
            raise UploadCheckFailure('SOURCE_LINK_REJECTED', [{'path': name}])
    if not current.is_file() or current.stat().st_size > 4 * 1024 * 1024:
        raise UploadCheckFailure('SOURCE_MISSING_OR_TOO_LARGE', [{'path': name}])
    return current


def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    """Duplicate manifest keys must never silently replace reviewed entries."""
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise ValueError('MANIFEST_DUPLICATE_KEY')
        result[key] = value
    return result


def entries(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value or len(value) > 200:
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


def verify(root: Path, group: str, allowed: tuple[str, ...], changed: set[str]) -> None:
    """Require exact package paths and pinned prerequisite bytes without any writes."""
    if group not in GROUPS or len(allowed) != len(set(allowed)):
        raise ValueError('GROUP_INVALID')
    name = f'OVERNIGHT_{group.upper()}_UPLOAD_2026-10-13.json'
    raw: object = json.loads(source(root, name).read_bytes(), object_pairs_hook=pairs)
    if not isinstance(raw, dict):
        raise ValueError('MANIFEST_INVALID')
    manifest = cast(dict[str, object], raw)
    if set(manifest) != {'version', 'group', 'files', 'prerequisites'} or (
            manifest['version'] != 'overnight-reviewed-upload-v1' or manifest['group'] != group):
        raise ValueError('MANIFEST_INVALID')
    files = entries(manifest['files'])
    if {item['destination'] for item in files} != set(allowed) or changed != set(allowed):
        raise ValueError('EXACT_UPLOAD_PATHS_REQUIRED')
    prerequisite_value = manifest['prerequisites']
    prerequisites = [] if prerequisite_value == [] else entries(prerequisite_value)
    if {item['destination'] for item in prerequisites} & set(allowed):
        raise ValueError('PREREQUISITE_OVERLAP')
    mismatches: list[dict[str, str]] = []
    for item in files + prerequisites:
        file = source(root, item['destination'])
        expected = item['sha256_lf']
        if item['destination'] == name and expected is None:
            continue
        if not isinstance(expected, str) or re.fullmatch(r'[0-9a-f]{64}', expected) is None:
            raise UploadCheckFailure('MANIFEST_HASH_INVALID',
                                     [{'path': path_name(item['destination'])}])
        actual = hashlib.sha256(file.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
        if actual != expected:
            mismatches.append({'path': path_name(item['destination']),
                               'kind': 'package_file' if item in files else 'prerequisite',
                               'expected': expected, 'actual': actual})
    if mismatches:
        raise UploadCheckFailure('SOURCE_HASH_MISMATCH', mismatches)


def main(group: str, allowed: tuple[str, ...], argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        if re.fullmatch(r'[0-9a-f]{40}', args.base) is None:
            raise ValueError('BASE_SHA_INVALID')
        if any(path.is_symlink() or path.is_junction() for path in (args.root, *args.root.parents)):
            raise ValueError('CLONE_ROOT_REQUIRED')
        root = args.root.resolve(strict=True)
        if git(root, 'rev-parse', 'HEAD') != args.base:
            raise ValueError('BASE_NOT_CURRENT_HEAD')
        if Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != root:
            raise ValueError('CLONE_ROOT_REQUIRED')
        # A correct working tree must not hide different staged bytes in the PR.
        if git(root, 'diff', '--name-only', '--'):
            raise ValueError('INDEX_WORKTREE_MISMATCH_STAGE_THEN_RECHECK')
        changed = set(git(root, 'diff', '--name-only', args.base, '--').splitlines())
        changed.update(git(root, 'ls-files', '--others', '--exclude-standard').splitlines())
        verify(root, group, allowed, changed)
        print(json.dumps({'status': 'UPLOAD_FILES_VERIFIED_REQUIRES_TESTS_AND_CI',
                          'group': group, 'base': args.base, 'hosted_changes': 0,
                          'approval_authority': False}))
        return 0
    except Exception as error:
        rule = 'UNCLASSIFIED_UPLOAD_FAILURE'
        failures: list[dict[str, str]] = []
        if isinstance(error, UploadCheckFailure):
            rule, failures = error.rule, error.failures
        elif isinstance(error, json.JSONDecodeError):
            rule = 'MANIFEST_JSON_INVALID'
        elif isinstance(error, ValueError) and str(error) in SAFE_RULES:
            rule = str(error)
        print(json.dumps({'status': 'BLOCKED', 'code': 'OVERNIGHT_UPLOAD_CHECK_FAILED',
                          'group': group, 'rule': rule, 'failures': failures,
                          'hosted_changes': 0, 'approval_authority': False}))
        return 2
