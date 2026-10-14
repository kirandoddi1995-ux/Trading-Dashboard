"""Inactive exact DailyVolume package gate. Public sources/Git only; no exports."""
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess

import overnight_programme_upload_check as base
from overnight_upload_check import pairs
from reviewed_upload_check import git

VERSION = 'daily-volume-reader-v1'
GROUP = 'daily_volume_reader'
MANIFEST = 'DAILY_VOLUME_READER_UPLOAD_2026-10-14.json'
SQL_SOURCE = 'sql/drive_archive_draft.sql'
CONTROL_LIMIT = 128 * 1024  # Strictly smaller, including before JSON parsing.
FILES = (
    'storage_daily_volume_reader.py', 'tests/test_storage_daily_volume_reader.py',
    'daily_volume_upload_check.py', 'tests/test_daily_volume_upload_check.py',
    'DAILY_VOLUME_READER_UPLOAD_2026-10-14.md', MANIFEST,
)
SEEDS = ('storage_daily_volume_reader.py', 'daily_volume_upload_check.py', 'production_repository.py')
EXTRA_PINS = ('constraints.txt', 'requirements.txt', 'requirements-archive.txt',
              'overnight_programme_upload_check.py', SQL_SOURCE)
SCHEMA = frozenset({'version', 'group', 'files', 'prerequisites', 'seeds', 'extra_pins'})
SAFE_RULES = frozenset({
    'PUBLIC_SOURCE_PATH_REQUIRED', 'SOURCE_LINK_REJECTED', 'SOURCE_MISSING_OR_TOO_LARGE',
    'CONTROL_TOO_LARGE', 'MANIFEST_INVALID', 'MANIFEST_DUPLICATE_KEY', 'EXACT_PACKAGE_REQUIRED',
    'EXACT_PINS_REQUIRED', 'MANIFEST_HASH_INVALID', 'PREREQUISITE_OVERLAP',
    'BASE_NOT_CURRENT_HEAD', 'CLONE_ROOT_REQUIRED', 'STAGE_THEN_RECHECK',
    'INDEX_ENTRY_INVALID', 'INDEX_BLOB_TOO_LARGE', 'INDEX_BLOB_INVALID',
    'UNSUPPORTED_DYNAMIC_IMPORT',
})


@dataclass(frozen=True)
class Pin:
    destination: str
    sha256_lf: str | None


def root_guard(root: Path) -> None:
    if not root.is_absolute() or any(p.is_symlink() or p.is_junction() for p in (root, *root.parents)):
        raise ValueError('CLONE_ROOT_REQUIRED')


def public_source(root: Path, name: object) -> Path:
    """Only two fixed new special paths; ordinary sources use the frozen guard."""
    root_guard(root)
    if type(name) is not str:
        raise ValueError('PUBLIC_SOURCE_PATH_REQUIRED')
    if name not in (MANIFEST, SQL_SOURCE):
        # Do not accept other JSON controls/exports through the common checker.
        if name.endswith('.json'):
            raise ValueError('PUBLIC_SOURCE_PATH_REQUIRED')
        return base.public_path(root, name)
    current = root
    for part in name.split('/'):
        current /= part
        if current.is_symlink() or current.is_junction():
            raise ValueError('SOURCE_LINK_REJECTED')
    if not current.is_file():
        raise ValueError('SOURCE_MISSING_OR_TOO_LARGE')
    size = current.stat().st_size
    if name == MANIFEST and size >= CONTROL_LIMIT:
        raise ValueError('CONTROL_TOO_LARGE')
    if size > base.MAX_BYTES:
        raise ValueError('SOURCE_MISSING_OR_TOO_LARGE')
    return current


def public_bytes(root: Path, name: str) -> bytes:
    # Bounded read also protects against growth after the stat check.
    path = public_source(root, name)
    limit = CONTROL_LIMIT - 1 if name == MANIFEST else base.MAX_BYTES
    with path.open('rb') as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise ValueError('CONTROL_TOO_LARGE' if name == MANIFEST else 'SOURCE_MISSING_OR_TOO_LARGE')
    return content


def digest(content: bytes) -> str:
    return hashlib.sha256(content.replace(b'\r\n', b'\n')).hexdigest()


def supported_imports(tree: ast.AST) -> None:
    """Reject imports the frozen discovery cannot follow; never evaluate targets."""
    labels = {'__import__', 'import_module'}
    call_functions: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in labels and alias.asname not in (None, alias.name):
                    raise ValueError('UNSUPPORTED_DYNAMIC_IMPORT')
        if not isinstance(node, ast.Call):
            continue
        label = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ''
        if label not in labels:
            continue
        call_functions.add(id(node.func))
        if (not node.args or not isinstance(node.args[0], ast.Constant)
                or type(node.args[0].value) is not str
                or node.args[0].value.startswith('.')
                or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*', node.args[0].value) is None):
            raise ValueError('UNSUPPORTED_DYNAMIC_IMPORT')
        # __import__('child', ..., level=1) is also relative despite a plain name.
        if label == '__import__':
            level = node.args[4] if len(node.args) >= 5 else next(
                (keyword.value for keyword in node.keywords if keyword.arg == 'level'), None)
            if level is not None and (not isinstance(level, ast.Constant)
                                      or type(level.value) is not int or level.value != 0):
                raise ValueError('UNSUPPORTED_DYNAMIC_IMPORT')
        if any(keyword.arg is None for keyword in node.keywords):
            raise ValueError('UNSUPPORTED_DYNAMIC_IMPORT')
    for node in ast.walk(tree):
        label = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else ''
        # Assignment, forwarding or other importer references can hide aliased
        # calls from the frozen walker. Direct calls alone are supported.
        if label in labels and id(node) not in call_functions:
            raise ValueError('UNSUPPORTED_DYNAMIC_IMPORT')


def guarded_members(root: Path, seeds: list[str]) -> set[str]:
    """Prevalidate bounded public ASTs, then confirm the frozen exact closure."""
    root_guard(root)
    index = {path.stem: path.name for path in root.iterdir() if path.suffix == '.py'}
    selected: set[str] = set()
    pending = list(seeds)
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        content = public_bytes(root, name)
        selected.add(name)
        if not name.endswith('.py'):
            continue
        tree = ast.parse(content.decode('utf-8-sig'))
        supported_imports(tree)
        requested: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                requested.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    raise ValueError('PUBLIC_SOURCE_PATH_REQUIRED')
                requested.append(node.module or '')
            elif isinstance(node, ast.Call):
                label = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ''
                if label in ('__import__', 'import_module'):
                    # supported_imports already proved the first argument safe.
                    argument = node.args[0]
                    assert isinstance(argument, ast.Constant) and type(argument.value) is str
                    requested.append(argument.value)
        for target in requested:
            top = target.split('.')[0]
            if top in index:
                pending.append(index[top])
            elif top and (root / top).exists():
                raise ValueError('PUBLIC_SOURCE_PATH_REQUIRED')
    if base.guarded_members(root, seeds) != selected:
        raise ValueError('EXACT_PINS_REQUIRED')
    return selected


def reject_constant(value: str) -> object:
    raise ValueError('MANIFEST_INVALID')


def pins(value: object, *, control: bool) -> tuple[Pin, ...]:
    if type(value) is not list or not value or len(value) > 512:
        raise ValueError('EXACT_PINS_REQUIRED')
    result: list[Pin] = []
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
        result.append(Pin(name, sha))
    return tuple(result)


def exact_strings(value: object, expected: tuple[str, ...]) -> None:
    if type(value) is not list or any(type(item) is not str for item in value) or tuple(value) != expected:
        raise ValueError('EXACT_PINS_REQUIRED')


def verify(root: Path, changed: set[str]) -> list[dict[str, str]]:
    """Verify schema, exact set and complete guarded AST closure without imports."""
    raw: object = json.loads(public_bytes(root, MANIFEST), object_pairs_hook=pairs,
                            parse_constant=reject_constant)
    if (type(raw) is not dict or set(raw) != SCHEMA or raw['version'] != VERSION
            or raw['group'] != GROUP):
        raise ValueError('MANIFEST_INVALID')
    files = pins(raw['files'], control=True)
    prerequisites = pins(raw['prerequisites'], control=False)
    names = {pin.destination for pin in files}
    if type(changed) is not set or names != set(FILES) or changed != names:
        raise ValueError('EXACT_PACKAGE_REQUIRED')
    exact_strings(raw['seeds'], SEEDS)
    exact_strings(raw['extra_pins'], EXTRA_PINS)
    prerequisite_names = {pin.destination for pin in prerequisites}
    if prerequisite_names & names:
        raise ValueError('PREREQUISITE_OVERLAP')
    # Validate every declared name before discovery or any content read.
    for name in names | prerequisite_names | set(SEEDS) | set(EXTRA_PINS):
        public_source(root, name)
    closure = guarded_members(root, list(SEEDS))
    if prerequisite_names != (closure | set(EXTRA_PINS)) - names:
        raise ValueError('EXACT_PINS_REQUIRED')
    failures: list[dict[str, str]] = []
    for pin in (*files, *prerequisites):
        content = public_bytes(root, pin.destination)
        if pin.destination == MANIFEST and pin.sha256_lf is None:
            continue  # Control is structurally validated and independently index-bound.
        assert pin.sha256_lf is not None
        actual = digest(content)
        if actual != pin.sha256_lf:
            failures.append({'path': pin.destination, 'expected': pin.sha256_lf, 'actual': actual})
    return failures


def index_matches(root: Path, names: set[str]) -> list[dict[str, str]]:
    """Guard all paths, modes and immutable blob sizes before staged-byte reads.

    The frozen index helper cannot guard this new control JSON or SQL path.
    Read immutable object IDs here; never print Git output or invoke filters.
    """
    failures: list[dict[str, str]] = []
    for name in sorted(names):
        working = public_bytes(root, name)
        entry = git(root, 'ls-files', '--stage', '--', name)
        match = re.fullmatch(r'(100644|100755) ([0-9a-f]{40}) 0\t' + re.escape(name), entry)
        if match is None:
            raise ValueError('INDEX_ENTRY_INVALID')
        identity = match[2]
        size_text = git(root, 'cat-file', '-s', identity)
        if re.fullmatch('[0-9]{1,10}', size_text) is None:
            raise ValueError('INDEX_BLOB_INVALID')
        size = int(size_text)
        limit = CONTROL_LIMIT - 1 if name == MANIFEST else base.MAX_BYTES
        if size > limit:
            raise ValueError('INDEX_BLOB_TOO_LARGE')
        response = subprocess.run(['git', '-C', str(root), 'cat-file', 'blob', identity],
                                  check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
        staged = response.stdout
        if type(staged) is not bytes or len(staged) != size:
            raise ValueError('INDEX_BLOB_INVALID')
        expected, actual = digest(working), digest(staged)
        if expected != actual:
            failures.append({'path': name, 'expected': expected, 'actual': actual})
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    args = parser.parse_args(argv)
    try:
        root = Path.cwd()
        root_guard(root)
        if re.fullmatch('[0-9a-f]{40}', args.base) is None or git(root, 'rev-parse', 'HEAD') != args.base:
            raise ValueError('BASE_NOT_CURRENT_HEAD')
        if Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != root.resolve():
            raise ValueError('CLONE_ROOT_REQUIRED')
        if git(root, 'diff', '--name-only', '--') or git(root, 'ls-files', '--others', '--exclude-standard'):
            raise ValueError('STAGE_THEN_RECHECK')
        changed = set(git(root, 'diff', '--cached', '--name-only', args.base, '--').splitlines())
        failures = verify(root, changed)
        if not failures:
            indexed = changed | guarded_members(root, list(SEEDS)) | set(EXTRA_PINS)
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
