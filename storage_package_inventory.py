"""Offline source inventory and upload dependency checks; never import app code.

The reviewed baseline contains public Git tree metadata, not market data or keys.
This is a packaging aid, not CI, deployment approval or storage commissioning.
"""
from __future__ import annotations

import argparse
import ast
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

LIMIT = 4 * 1024 * 1024
HEX40 = re.compile(r'[0-9a-f]{40}')
BASELINE = 'STORAGE_MAIN_BASELINE_2026-10-07.json'
STAGES = {
    'ledger_segments': 'P1_ORIGINALS_CATALOG',
    'cold_catalog': 'P1_ORIGINALS_CATALOG',
    'catalog_receipts': 'P1_ORIGINALS_CATALOG',
    'ledger_cold_store': 'P1_ORIGINALS_CATALOG',
    'local_ledger_recovery': 'P2_RECOVERY',
    'ledger_recovery': 'P2_RECOVERY',
    'recovery_drill': 'P2_RECOVERY',
    'ledger_runtime_reader': 'P3_READERS_WRITERS',
    'ledger_storage_access': 'P3_READERS_WRITERS',
    'production_repository': 'P3_READERS_WRITERS',
    'equity_runtime_health': 'P3_READERS_WRITERS',
    'equity_delivery_repository': 'P3_READERS_WRITERS',
    'ledger_archive_publication': 'P4_ARCHIVE_COMMISSIONING',
    'ledger_archive_repository': 'P4_ARCHIVE_COMMISSIONING',
    'cold_drive_objects': 'P4_ARCHIVE_COMMISSIONING',
    'catalog_roots_sql': 'P4_ARCHIVE_COMMISSIONING',
    'ledger_archive_guards_sql': 'P4_ARCHIVE_COMMISSIONING',
    'ledger_hot_heads_sql': 'P4_ARCHIVE_COMMISSIONING',
    'storage_legacy_migration': 'P4_ARCHIVE_COMMISSIONING',
    'universe_storage_sql': 'P5_UNIVERSE_NONLEDGER',
    'archive_maintenance_sql': 'P5_UNIVERSE_NONLEDGER',
    'storage_policy': 'P6_ADMISSION_ACCEPTANCE',
    'storage_commissioning': 'P6_ADMISSION_ACCEPTANCE',
    'collector_storage_preflight': 'TRANSITION_ALREADY_RELEASED',
    'release_verification': 'PACKAGING_SUPPORT',
    'release_packaging': 'PACKAGING_SUPPORT',
    'storage_package_inventory': 'P0_INVENTORY',
    'mypy-automation': 'PACKAGING_SUPPORT',
    'prepare_capture_repair': 'HISTORICAL_CAPTURE_HELPER',
    'equity_research_observations': 'SEPARATE_RESEARCH_REVIEW',
    'equity_research_isolation': 'SEPARATE_RESEARCH_REVIEW',
    'equity_research_outcomes': 'SEPARATE_RESEARCH_REVIEW',
    'collector_trial_acceptance_read_only': 'HISTORICAL_READONLY_DIAGNOSTICS',
    'nav_compaction_review_read_only': 'HISTORICAL_READONLY_DIAGNOSTICS',
    'positions_storage_audit_readonly': 'HISTORICAL_READONLY_DIAGNOSTICS',
    'post_nav_restart_read_only': 'HISTORICAL_READONLY_DIAGNOSTICS',
    'storage_capture_restart_read_only': 'HISTORICAL_READONLY_DIAGNOSTICS',
}
MIGRATIONS = (
    'supabase/migrations/20261005194922_permanent_storage_control_review_only.sql',
    'supabase/migrations/20261005200414_permanent_storage_ledger_review_only.sql',
    'supabase/migrations/20261005210149_permanent_storage_heads_review_only.sql',
)
RESOURCES = {
    'storage_package_inventory.py': (BASELINE,),
    'tests/test_storage_package_inventory.py': (
        BASELINE, 'ledger_segments.py', 'cold_catalog.py',
        'catalog_receipts.py', 'ledger_cold_store.py', 'evidence_ledger.py'),
}


class InventoryError(ValueError):
    """Stable failures without source contents, private paths or driver errors."""


def safe_path(root: Path, name: str) -> Path:
    """Accept only explicit code/report locations, never links or private files."""
    if not isinstance(name, str) or not name:
        raise InventoryError('SOURCE_PATH_INVALID')
    relative = PurePosixPath(name)
    if (relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name
            or relative.as_posix() != name or any(p.startswith('.') for p in relative.parts)):
        raise InventoryError('SOURCE_PATH_INVALID')
    parent = relative.parent.as_posix()
    allowed = (
        (parent == '.' and relative.suffix in ('.py', '.md', '.ini'))
        or (parent == 'tests' and relative.name.startswith('test_') and relative.suffix == '.py')
        or (parent in ('sql', 'supabase/migrations') and relative.suffix == '.sql')
        or name == BASELINE
    )
    if not allowed:
        raise InventoryError('SOURCE_PATH_NOT_ALLOWLISTED')
    resolved_root = root.resolve()
    path = resolved_root
    for component in relative.parts:
        path /= component
        if path.is_symlink() or path.is_junction():
            raise InventoryError('SOURCE_LINK_REJECTED')
    if not path.resolve().is_relative_to(resolved_root):
        raise InventoryError('SOURCE_PATH_INVALID')
    return path


def read_source(root: Path, name: str) -> bytes:
    """Read bounded allowlisted source bytes; do not execute or modify them."""
    path = safe_path(root, name)
    try:
        with path.open('rb') as stream:
            raw = stream.read(LIMIT + 1)
    except OSError:
        raise InventoryError('SOURCE_MISSING_OR_UNREADABLE') from None
    if len(raw) > LIMIT:
        raise InventoryError('SOURCE_SIZE_LIMIT')
    return raw


def blob_sha(raw: bytes) -> str:
    """Reproduce Git blob identity, not a security/market-data authenticity seal."""
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


@dataclass(frozen=True)
class Baseline:
    """Pinned public source-tree metadata; origin is reviewed separately."""
    commit_sha: str
    files: Mapping[str, str]


def load_baseline(raw: bytes) -> Baseline:
    """Reject malformed or duplicate JSON metadata; no network on this path."""
    if not isinstance(raw, bytes) or len(raw) > LIMIT:
        raise InventoryError('BASELINE_INVALID')
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise InventoryError('BASELINE_DUPLICATE_KEY')
            result[key] = value
        return result
    try:
        item = json.loads(raw, object_pairs_hook=unique)
        if (not isinstance(item, dict) or set(item) != {'version', 'commit_sha', 'files'}
                or item['version'] != 'storage-source-baseline-v1'
                or not isinstance(item['commit_sha'], str) or not HEX40.fullmatch(item['commit_sha'])
                or not isinstance(item['files'], dict) or not item['files']):
            raise InventoryError('BASELINE_INVALID')
        files: dict[str, str] = {}
        for name, value in item['files'].items():
            path = PurePosixPath(name)
            if (path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name
                    or not isinstance(value, str) or not HEX40.fullmatch(value)):
                raise InventoryError('BASELINE_INVALID')
            files[name] = value
        return Baseline(item['commit_sha'], files)
    except InventoryError:
        raise
    except (ValueError, TypeError, UnicodeError):
        raise InventoryError('BASELINE_INVALID') from None


def status(raw: bytes, expected: str | None) -> str:
    """Keep newline-only differences separate from changes in source behaviour."""
    if expected is None:
        return 'LOCAL_ONLY'
    if blob_sha(raw) == expected:
        return 'MATCHES_MAIN'
    lf = raw.replace(b'\r\n', b'\n')
    if expected in (blob_sha(lf), blob_sha(lf.replace(b'\n', b'\r\n'))):
        return 'MATCHES_MAIN_NEWLINES_ONLY'
    return 'MODIFIED_FROM_MAIN'


def stage(name: str) -> str:
    """Stage assignment is an implementation plan, never approval or obsolescence."""
    if name in MIGRATIONS:
        return 'P4_REVIEW_SQL_HOLD'
    stem = PurePosixPath(name).stem.removeprefix('test_')
    if stem.endswith('_sql') and stem[:-4] in STAGES:
        stem = stem[:-4]
    return STAGES.get(stem, 'UNCLASSIFIED_REVIEW')


def inventory(root: Path, baseline: Baseline) -> list[dict[str, str]]:
    """Inspect fixed source locations only; do not recurse into private/cached data."""
    names: set[str] = set()
    for pattern in ('*.py', '*.ini', 'tests/test_*.py', 'sql/*.sql', 'supabase/migrations/*.sql'):
        for path in root.glob(pattern):
            names.add(path.relative_to(root).as_posix())
    records = []
    for name in sorted(names):
        raw = read_source(root, name)
        current = status(raw, baseline.files.get(name))
        if current in ('MATCHES_MAIN', 'MATCHES_MAIN_NEWLINES_ONLY'):
            continue
        records.append({'path': name, 'stage': stage(name), 'status': current,
                        'source_sha256': hashlib.sha256(raw).hexdigest()})
    return records


def dependencies(raw: bytes) -> set[str]:
    """Find static/literal module imports without running source or reading data."""
    try:
        tree = ast.parse(raw.decode('utf-8-sig'))
    except (SyntaxError, UnicodeError):
        raise InventoryError('SOURCE_PARSE_FAILED') from None
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise InventoryError('RELATIVE_IMPORT_REQUIRES_REVIEW')
            if node.module:
                modules.add(node.module)
        elif isinstance(node, ast.Call):
            dynamic = (isinstance(node.func, ast.Name) and node.func.id == '__import__') or (
                isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module')
            if dynamic:
                if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
                    raise InventoryError('DYNAMIC_IMPORT_REQUIRES_REVIEW')
                modules.add(node.args[0].value)
    return {name.replace('.', '/') + '.py' for name in modules}


def check_package(root: Path, baseline: Baseline, members: Sequence[str]) -> dict[str, object]:
    """Flag omitted changed/new local dependencies; resources need explicit review.

    SQL-harness tests conservatively require all three draft migrations together.
    Generic dynamic resources, package imports and runtime compatibility still need
    isolated rehearsal/CI. Success here is not a merge or installation approval.
    """
    if not members or len(members) != len(set(members)):
        raise InventoryError('PACKAGE_MEMBERS_INVALID')
    selected = set(members)
    blockers = []
    for name in sorted(selected):
        raw = read_source(root, name)
        required = dependencies(raw) if name.endswith('.py') else set()
        explicit = set(RESOURCES.get(name, ()))
        if name.startswith('tests/test_') and stage(name).startswith(('P1_', 'P2_', 'P3_', 'P4_')) and name.endswith('_sql.py'):
            explicit.update(MIGRATIONS)
        required.update(explicit)
        for dependency in sorted(required):
            # External libraries are verified by lock/environment/CI, not this tool.
            if dependency not in explicit and dependency not in baseline.files and not (root / dependency).exists():
                continue
            try:
                companion = read_source(root, dependency)
            except InventoryError:
                blockers.append({'path': name, 'dependency': dependency, 'code': 'DEPENDENCY_UNAVAILABLE'})
                continue
            if dependency not in selected and status(companion, baseline.files.get(dependency)) not in (
                    'MATCHES_MAIN', 'MATCHES_MAIN_NEWLINES_ONLY'):
                blockers.append({'path': name, 'dependency': dependency, 'code': 'DEPENDENCY_NOT_IN_PACKAGE'})
    return {'status': 'PACKAGE_CHECK_PASSED_REQUIRES_REHEARSAL' if not blockers else 'BLOCKED',
            'baseline_commit': baseline.commit_sha, 'blockers': blockers,
            'approval_authority': False, 'hosted_changes': 0,
            'coverage': 'STATIC_LOCAL_IMPORTS_AND_DECLARED_RESOURCES_NOT_ALL_RUNTIME_IO'}


def main(argv: Sequence[str] | None = None) -> int:
    """Print source metadata only; no network, writes, imports or private scanning."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-package', nargs='+', metavar='RELATIVE_SOURCE_PATH')
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent
    try:
        baseline = load_baseline(read_source(root, BASELINE))
        result = check_package(root, baseline, args.check_package) if args.check_package else {
            'status': 'SOURCE_INVENTORY', 'baseline_commit': baseline.commit_sha,
            'files': inventory(root, baseline), 'approval_authority': False, 'hosted_changes': 0}
        print(json.dumps(result, sort_keys=True))
        return 2 if result['status'] == 'BLOCKED' else 0
    except InventoryError as error:
        print(json.dumps({'status': 'BLOCKED', 'code': str(error), 'approval_authority': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
