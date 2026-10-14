"""Deterministic public fixtures only; no real index, export, provider or state."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

import pytest

import daily_volume_upload_check as check
import overnight_programme_upload_check as frozen


@pytest.fixture
def tree(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    ordinary = set(check.FILES) | set(check.SEEDS) | set(check.EXTRA_PINS) | {'dependency.py'}
    for name in ordinary - {check.MANIFEST}:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'# public\r\n')
    (tmp_path / 'production_repository.py').write_text('import dependency\n', encoding='utf-8')
    closure = frozen.guarded_members(tmp_path, list(check.SEEDS))
    prerequisites = (closure | set(check.EXTRA_PINS)) - set(check.FILES)
    def pin(name: str) -> dict[str, object]:
        return {'destination': name, 'sha256_lf': None if name == check.MANIFEST
                else check.digest((tmp_path / name).read_bytes())}
    manifest: dict[str, Any] = {
        'version': check.VERSION, 'group': check.GROUP,
        'files': [pin(name) for name in check.FILES],
        'prerequisites': [pin(name) for name in sorted(prerequisites)],
        'seeds': list(check.SEEDS), 'extra_pins': list(check.EXTRA_PINS),
    }
    (tmp_path / check.MANIFEST).write_text(json.dumps(manifest), encoding='utf-8')
    return tmp_path, manifest


def save(tree: tuple[Path, dict[str, Any]]) -> Path:
    root, manifest = tree
    (root / check.MANIFEST).write_text(json.dumps(manifest), encoding='utf-8')
    return root


def test_exact_schema_closure_and_mandatory_semantic_pins(tree: tuple[Path, dict[str, Any]]) -> None:
    root, manifest = tree
    assert check.verify(root, set(check.FILES)) == []
    prerequisites = {pin['destination'] for pin in manifest['prerequisites']}
    assert {'production_repository.py', 'dependency.py', check.SQL_SOURCE,
            'overnight_programme_upload_check.py'} <= prerequisites
    assert len(check.SEEDS) == 3 and len(check.FILES) == 6


@pytest.mark.parametrize('name', ['dependency.py', 'production_repository.py', check.SQL_SOURCE,
                                 'overnight_programme_upload_check.py', 'storage_daily_volume_reader.py'])
def test_pin_changes_report_only_public_hashes(tree: tuple[Path, dict[str, Any]], name: str) -> None:
    root, manifest = tree
    old = next(pin['sha256_lf'] for pin in manifest['files'] + manifest['prerequisites'] if pin['destination'] == name)
    changed = b'# changed\nimport dependency\n' if name == 'production_repository.py' else b'# changed\n'
    (root / name).write_bytes(changed)
    assert check.verify(root, set(check.FILES)) == [
        {'path': name, 'expected': old, 'actual': check.digest(changed)},
    ]


@pytest.mark.parametrize('mutation', ['version', 'group', 'extra_key', 'missing_key', 'files_type',
    'entry_type', 'entry_extra', 'destination_type', 'hash_type', 'duplicate', 'control_hash',
    'missing_file', 'missing_prerequisite', 'overlap', 'seed_order', 'seed_type', 'extra_order',
    'missing_common_pin', 'null_prerequisite'])
def test_untrusted_schema_and_omissions_rejected(tree: tuple[Path, dict[str, Any]], mutation: str) -> None:
    root, manifest = tree
    if mutation == 'version':
        manifest['version'] = True
    elif mutation == 'group':
        manifest['group'] = 'untrusted-export'
    elif mutation == 'extra_key':
        manifest['export'] = 'private'
    elif mutation == 'missing_key':
        del manifest['files']
    elif mutation == 'files_type':
        manifest['files'] = {}
    elif mutation == 'entry_type':
        manifest['files'][0] = 'private'
    elif mutation == 'entry_extra':
        manifest['files'][0]['data'] = 'private'
    elif mutation == 'destination_type':
        manifest['files'][0]['destination'] = []
    elif mutation == 'hash_type':
        manifest['files'][0]['sha256_lf'] = False
    elif mutation == 'duplicate':
        manifest['files'].append(manifest['files'][0])
    elif mutation == 'control_hash':
        manifest['files'][-1]['sha256_lf'] = 'a' * 64
    elif mutation == 'missing_file':
        manifest['files'].pop()
    elif mutation == 'missing_prerequisite':
        manifest['prerequisites'].pop()
    elif mutation == 'overlap':
        manifest['prerequisites'].append(manifest['files'][0])
    elif mutation == 'seed_order':
        manifest['seeds'].reverse()
    elif mutation == 'seed_type':
        manifest['seeds'] = {'production_repository.py': True}
    elif mutation == 'extra_order':
        manifest['extra_pins'].reverse()
    elif mutation == 'missing_common_pin':
        manifest['prerequisites'] = [pin for pin in manifest['prerequisites']
                                     if pin['destination'] != 'overnight_programme_upload_check.py']
    else:
        manifest['prerequisites'][0]['sha256_lf'] = None
    with pytest.raises(ValueError):
        check.verify(save((root, manifest)), set(check.FILES))


@pytest.mark.parametrize('content', ['[]', 'false', '{"version":NaN}', '{"group":1,"group":2}'])
def test_json_types_constants_duplicates(tree: tuple[Path, dict[str, Any]], content: str) -> None:
    root, _ = tree
    (root / check.MANIFEST).write_text(content)
    with pytest.raises(ValueError):
        check.verify(root, set(check.FILES))


@pytest.mark.parametrize('name', ['../private.py', 'C:/private.py', 'tests/../private.py',
    'sql/other.sql', 'sql/../drive_archive_draft.sql', 'untrusted_export.json',
    'FUTURE_OPS_UPLOAD_2026-10-14.json', 'client_secret.py', 'sql\\drive_archive_draft.sql'])
def test_paths_and_untrusted_exports_rejected(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError, match='PUBLIC_SOURCE_PATH_REQUIRED'):
        check.public_source(tmp_path, name)


def test_special_guards_reject_linked_components(tree: tuple[Path, dict[str, Any]],
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    root, _ = tree
    monkeypatch.setattr(Path, 'is_junction', lambda self: self == root / 'sql')
    with pytest.raises(ValueError, match='SOURCE_LINK_REJECTED'):
        check.public_source(root, check.SQL_SOURCE)
    monkeypatch.setattr(Path, 'is_junction', lambda self: self == root / check.MANIFEST)
    with pytest.raises(ValueError, match='SOURCE_LINK_REJECTED'):
        check.public_source(root, check.MANIFEST)


def test_control_cap_is_strict_and_precedes_read(tree: tuple[Path, dict[str, Any]],
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    root, _ = tree
    target = root / check.MANIFEST
    target.write_bytes(b' ' * check.CONTROL_LIMIT)
    def denied(*args: object, **kwargs: object) -> Any:
        raise AssertionError('control read happened')
    monkeypatch.setattr(Path, 'open', denied)
    with pytest.raises(ValueError, match='CONTROL_TOO_LARGE'):
        check.verify(root, set(check.FILES))


def test_discovery_rejects_unsafe_ast_without_importing(tree: tuple[Path, dict[str, Any]]) -> None:
    root, manifest = tree
    (root / 'storage_daily_volume_reader.py').write_text("importlib.import_module('.child', package='private')")
    manifest['files'][0]['sha256_lf'] = check.digest((root / 'storage_daily_volume_reader.py').read_bytes())
    with pytest.raises(ValueError, match='UNSUPPORTED_DYNAMIC_IMPORT'):
        check.verify(save((root, manifest)), set(check.FILES))


@pytest.mark.parametrize('source', [
    "importlib.import_module(target)", "__import__(target)",
    "__import__('dependency' + suffix)", "importlib.import_module(name='dependency')",
    "from importlib import import_module as load\nload('dependency')",
    "from builtins import __import__ as load\nload('dependency')",
    "loader = importlib.import_module\nloader('dependency')",
    "loader = __import__\nloader('dependency')",
    "__import__('dependency', level=1)",
    "__import__('dependency', None, None, (), relative_level)",
    "importlib.import_module('dependency', **options)",
    "importlib.import_module('../untrusted')",
])
def test_unsupported_dynamic_imports_block_without_discovering_targets(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str) -> None:
    entry = tmp_path / 'entry.py'
    entry.write_text(source, encoding='utf-8')
    # Prove the new gate rejects even when frozen discovery silently omits it.
    monkeypatch.setattr(frozen, 'guarded_members', lambda root, seeds: {'entry.py'})
    original = check.public_bytes
    reads: list[str] = []
    def read(root: Path, name: str) -> bytes:
        reads.append(name)
        assert name == 'entry.py'
        return original(root, name)
    monkeypatch.setattr(check, 'public_bytes', read)
    with pytest.raises(ValueError, match='UNSUPPORTED_DYNAMIC_IMPORT'):
        check.guarded_members(tmp_path, ['entry.py'])
    assert reads == ['entry.py']


@pytest.mark.parametrize('source', ["importlib.import_module('dependency')",
    "import importlib as loader\nloader.import_module('dependency')",
    "from importlib import import_module\nimport_module('dependency')",
    "__import__('dependency')", "__import__('dependency', level=0)"])
def test_supported_literal_imports_remain_in_frozen_closure(tmp_path: Path, source: str) -> None:
    (tmp_path / 'entry.py').write_text(source, encoding='utf-8')
    (tmp_path / 'dependency.py').write_text('# public', encoding='utf-8')
    assert check.guarded_members(tmp_path, ['entry.py']) == {'entry.py', 'dependency.py'}


@pytest.mark.parametrize('source', ["__import__(target)",
    "importlib.import_module('C:/private')", "importlib.import_module('/private')",
    "from importlib import import_module as loader\nloader('private')"])
def test_unsupported_call_rejected_before_frozen_discovery(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str) -> None:
    (tmp_path / 'entry.py').write_text(source, encoding='utf-8')
    def denied(*args: object, **kwargs: object) -> set[str]:
        raise AssertionError('frozen discovery ran before import validation')
    monkeypatch.setattr(frozen, 'guarded_members', denied)
    with pytest.raises(ValueError, match='UNSUPPORTED_DYNAMIC_IMPORT'):
        check.guarded_members(tmp_path, ['entry.py'])


def fake_index(root: Path, monkeypatch: pytest.MonkeyPatch, *, staged: dict[str, bytes],
               mode: str = '100644', reported_size: str | None = None) -> list[str]:
    queried: list[str] = []
    identities = {'a' * 40: b''}
    def git(path: Path, *args: str) -> str:
        if args[:2] == ('ls-files', '--stage'):
            name = args[-1]
            queried.append(name)
            identities['a' * 40] = staged.get(name, (root / name).read_bytes())
            return mode + ' ' + 'a' * 40 + ' 0\t' + name
        if args[:2] == ('cat-file', '-s'):
            return reported_size if reported_size is not None else str(len(identities[args[-1]]))
        raise AssertionError(args)
    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert args[3:5] == ['cat-file', 'blob']
        return subprocess.CompletedProcess(args, 0, identities[args[-1]])
    monkeypatch.setattr(check, 'git', git)
    monkeypatch.setattr(subprocess, 'run', run)
    return queried


def test_all_index_bytes_including_control_sql_and_prerequisites(tree: tuple[Path, dict[str, Any]],
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    root, manifest = tree
    names = {pin['destination'] for pin in manifest['files'] + manifest['prerequisites']}
    queried = fake_index(root, monkeypatch, staged={})
    assert check.index_matches(root, names) == []
    assert set(queried) == names
    assert {check.MANIFEST, check.SQL_SOURCE, 'production_repository.py'} <= set(queried)


@pytest.mark.parametrize('name', [check.MANIFEST, check.SQL_SOURCE, 'production_repository.py'])
def test_index_divergence_not_hidden(tree: tuple[Path, dict[str, Any]], monkeypatch: pytest.MonkeyPatch,
                                  name: str) -> None:
    root, _ = tree
    fake_index(root, monkeypatch, staged={name: b'# different\n'})
    failures = check.index_matches(root, {name})
    assert failures == [{'path': name, 'expected': check.digest((root / name).read_bytes()),
                         'actual': check.digest(b'# different\n')}]


@pytest.mark.parametrize('mode,size,rule', [('120000', None, 'INDEX_ENTRY_INVALID'),
    ('160000', None, 'INDEX_ENTRY_INVALID'), ('100644', '-1', 'INDEX_BLOB_INVALID'),
    ('100644', str(check.CONTROL_LIMIT), 'INDEX_BLOB_TOO_LARGE')])
def test_index_modes_and_caps_fail_before_blob_read(tree: tuple[Path, dict[str, Any]],
                                                  monkeypatch: pytest.MonkeyPatch,
                                                  mode: str, size: str | None, rule: str) -> None:
    root, _ = tree
    fake_index(root, monkeypatch, staged={}, mode=mode, reported_size=size)
    def denied(*args: object, **kwargs: object) -> Any:
        raise AssertionError('blob read happened')
    monkeypatch.setattr(subprocess, 'run', denied)
    with pytest.raises(ValueError, match=rule):
        check.index_matches(root, {check.MANIFEST})


@pytest.mark.parametrize('condition', ['stale', 'bad_base', 'not_root', 'unstaged', 'untracked', 'extra_staged'])
def test_git_gates_fail_closed(tree: tuple[Path, dict[str, Any]], monkeypatch: pytest.MonkeyPatch,
                             capsys: pytest.CaptureFixture[str], condition: str) -> None:
    root, _ = tree
    monkeypatch.chdir(root)
    def git(path: Path, *args: str) -> str:
        if args == ('rev-parse', 'HEAD'):
            return 'b' * 40 if condition == 'stale' else 'a' * 40
        if args == ('rev-parse', '--show-toplevel'):
            return str(root / 'other') if condition == 'not_root' else str(root)
        if args == ('diff', '--name-only', '--'):
            return 'private-secret-path' if condition == 'unstaged' else ''
        if args == ('ls-files', '--others', '--exclude-standard'):
            return 'private-secret-path' if condition == 'untracked' else ''
        if args[:2] == ('diff', '--cached'):
            return '\n'.join((*check.FILES, 'other.py'))
        raise AssertionError(args)
    monkeypatch.setattr(check, 'git', git)
    assert check.main(['--base', 'bad' if condition == 'bad_base' else 'a' * 40]) == 2
    output = capsys.readouterr().out
    assert json.loads(output)['status'] == 'BLOCKED'
    assert 'private-secret-path' not in output


def test_main_binds_complete_closure_and_redacts_errors(tree: tuple[Path, dict[str, Any]],
                                                     monkeypatch: pytest.MonkeyPatch,
                                                     capsys: pytest.CaptureFixture[str]) -> None:
    root, manifest = tree
    monkeypatch.chdir(root)
    def git(path: Path, *args: str) -> str:
        if args == ('rev-parse', 'HEAD'):
            return 'a' * 40
        if args == ('rev-parse', '--show-toplevel'):
            return str(root)
        if args[:2] == ('diff', '--cached'):
            return '\n'.join(check.FILES)
        return ''
    monkeypatch.setattr(check, 'git', git)
    queried: list[set[str]] = []
    def capture(path: Path, names: set[str]) -> list[dict[str, str]]:
        queried.append(names)
        return []
    monkeypatch.setattr(check, 'index_matches', capture)
    assert check.main(['--base', 'a' * 40]) == 0
    assert queried == [{pin['destination'] for pin in manifest['files'] + manifest['prerequisites']}]
    capsys.readouterr()
    def failed(path: Path, names: set[str]) -> list[dict[str, str]]:
        raise RuntimeError('PRIVATE_SECRET_MUST_NOT_PRINT')
    monkeypatch.setattr(check, 'index_matches', failed)
    assert check.main(['--base', 'a' * 40]) == 2
    output = capsys.readouterr().out
    assert json.loads(output)['rule'] == 'UPLOAD_REVIEW_REQUIRED'
    assert 'PRIVATE_SECRET' not in output
