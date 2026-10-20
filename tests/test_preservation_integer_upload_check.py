"""Synthetic Git index contract and exact public source hashes."""
import json
import ast
from pathlib import Path
import sys
from typing import Any

import pytest

import preservation_integer_upload_check as c
from outcomes_readonly_upload_check import reviewed_successor_hash as readonly_successor_hash


def test_manifest_and_prerequisite_hashes() -> None:
    root = Path(__file__).resolve().parents[1]
    value = json.loads(c.safe_read(root / c.MANIFEST), object_pairs_hook=c.unique)
    assert value['version'] == c.VERSION and value['base'] == c.BASE
    assert value['prerequisites'] == c.PREREQUISITES
    assert set(value['files']) == set(c.FILES)
    for name, digest in value['files'].items():
        assert digest is None if name == c.MANIFEST else c.sha(c.safe_read(root / name)) == readonly_successor_hash(root, name, digest)
    for name, digest in c.PREREQUISITES.items():
        assert c.sha(c.safe_read(root / name)) == readonly_successor_hash(root, name, digest)


def test_runtime_import_closure_has_no_capture_transport_or_database() -> None:
    root = Path(__file__).resolve().parents[1]
    allowed = sys.stdlib_module_names | {'cryptography', 'archive_preservation_inventory',
                                        'programme_next_upload_check', 'archive_preservation_witness', 'archive_catalog_verify',
                                        'archive_catalog_reconcile', 'archive_recovery_review',
                                        'outcomes_footer_diagnostic', 'outcomes_large_profile',
                                        'outcomes_private_worker', 'normal_user_test_run', 'pyarrow'}
    for name in ('outcomes_private_worker.py', 'outcomes_private_container.py',
                 'preservation_integer_upload_check.py', 'normal_user_test_run.py'):
        tree = ast.parse((root / name).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(item.name.split('.')[0] in allowed for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0 and node.module is not None and node.module.split('.')[0] in allowed
    assert 'cryptography==50.0.1' in (root / 'constraints.txt').read_text(encoding='utf-8')


def test_wrong_base_no_io(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any) -> bytes:
        pytest.fail('IO before base validation')
    monkeypatch.setattr(c, 'git', forbidden)
    assert c.check(Path.cwd(), 'wrong')['failures'] == [{'rule': 'EXACT_BASE_REQUIRED'}]


@pytest.mark.parametrize('tamper', ['', 'head', 'payload', 'index', 'pin', 'extra', 'mode', 'unstaged', 'untracked', 'manifest'])
def test_index_contract(monkeypatch: pytest.MonkeyPatch, tamper: str) -> None:
    root = Path.cwd()
    files = ('new.py', c.MANIFEST)
    prereqs = {'fixed.py': c.sha(b'fixed')}
    monkeypatch.setattr(c, 'FILES', files)
    monkeypatch.setattr(c, 'MODIFIED_BASE_HASHES', {})
    monkeypatch.setattr(c, 'PREREQUISITES', prereqs)
    raw = {'new.py': b'new', 'fixed.py': b'fixed'}
    raw[c.MANIFEST] = json.dumps({'version': c.VERSION, 'base': c.BASE,
        'files': {'new.py': c.sha(b'new'), c.MANIFEST: None}, 'prerequisites': prereqs}).encode()
    def read(path: Path) -> bytes:
        return b'changed' if tamper == 'payload' and path.name == 'new.py' else raw[path.name]
    def git(path: Path, *args: str) -> bytes:
        if args == ('rev-parse', 'HEAD'):
            return ('bad' if tamper == 'head' else c.BASE).encode()
        if args == ('rev-parse', '--show-toplevel'):
            return str(root).encode()
        if args[0] == 'show':
            name = args[1].split(':', 1)[1]
            if ((tamper == 'index' and args[1] == ':new.py') or
                    (tamper == 'pin' and name == 'fixed.py') or
                    (tamper == 'manifest' and name == c.MANIFEST)):
                return b'tampered'
            return raw[name]
        if args[:3] == ('diff', '--cached', '--name-status'):
            return ('\n'.join('A\t' + x for x in files) + ('\nA\textra' if tamper == 'extra' else '')).encode()
        if args[:2] == ('ls-files', '--stage'):
            return '\n'.join(('100755' if tamper == 'mode' else '100644') + ' ' + 'a' * 40 + ' 0\t' + x for x in files).encode()
        if tamper == 'unstaged' and args[:2] == ('diff', '--name-only'):
            return b'new.py'
        if tamper == 'untracked' and args[:2] == ('ls-files', '--others'):
            return b'extra'
        return b''
    monkeypatch.setattr(c, 'git', git)
    monkeypatch.setattr(c, 'safe_read', read)
    result = c.check(root, c.BASE)
    assert bool(result['failures']) == bool(tamper)
    assert result['run_authorised'] is False
    if tamper == 'pin':
        assert {'path', 'expected', 'actual', 'location'} <= result['failures'][0].keys()



def test_historical_successor_is_explicit_not_a_fallback(tmp_path: Path) -> None:
    manifest = dict(version=c.VERSION, base=c.BASE,
        files={name: None if name == c.MANIFEST else 'a' * 64 for name in c.FILES},
        prerequisites=c.PREREQUISITES)
    (tmp_path / c.MANIFEST).write_text(json.dumps(manifest))
    name = 'archive_preservation_witness.py'
    assert c.reviewed_successor_hash(tmp_path, name, c.MODIFIED_BASE_HASHES[name]) == 'a' * 64
    assert c.reviewed_successor_hash(tmp_path, 'unknown.py', 'b' * 64) == 'b' * 64
    with pytest.raises(ValueError, match='HISTORICAL_PREDECESSOR_MISMATCH'):
        c.reviewed_successor_hash(tmp_path, name, 'b' * 64)
    manifest['base'] = 'wrong'
    (tmp_path / c.MANIFEST).write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='HISTORICAL_SUCCESSOR_CONTRACT_INVALID'):
        c.reviewed_successor_hash(tmp_path, name, c.MODIFIED_BASE_HASHES[name])


@pytest.mark.parametrize('change', ['missing', 'null', 'malformed', 'version', 'prerequisites'])
def test_historical_successor_contract_negatives(tmp_path: Path, change: str) -> None:
    value: dict[str, Any] = dict(version=c.VERSION, base=c.BASE,
        files={name: None if name == c.MANIFEST else 'a' * 64 for name in c.FILES},
        prerequisites=c.PREREQUISITES)
    name = 'archive_preservation_witness.py'
    if change == 'missing':
        del value['files'][name]
    elif change == 'null':
        value['files'][name] = None
    elif change == 'malformed':
        value['files'][name] = 'not a hash'
    elif change == 'version':
        value['version'] = 'wrong'
    else:
        value['prerequisites'] = {}
    (tmp_path / c.MANIFEST).write_text(json.dumps(value))
    with pytest.raises(ValueError, match='HISTORICAL_SUCCESSOR'):
        c.reviewed_successor_hash(tmp_path, name, c.MODIFIED_BASE_HASHES[name])


@pytest.mark.parametrize('change', ['', 'old-blob', 'modified-as-added', 'missing-modified', 'extra-modified', 'staged-modified'])
def test_modified_and_added_transition_is_not_a_hash_fallback(tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    root = tmp_path.resolve()
    files = ('existing.py', 'new.py', c.MANIFEST)
    modified = {'existing.py': c.sha(b'old reviewed bytes')}
    raw = {'existing.py': b'new reviewed bytes', 'new.py': b'additive bytes'}
    value = dict(version=c.VERSION, base=c.BASE,
        files={name: None if name == c.MANIFEST else c.sha(raw[name]) for name in files}, prerequisites={})
    raw[c.MANIFEST] = json.dumps(value).encode()
    monkeypatch.setattr(c, 'FILES', files)
    monkeypatch.setattr(c, 'PREREQUISITES', {})
    monkeypatch.setattr(c, 'MODIFIED_BASE_HASHES', modified)
    monkeypatch.setattr(c, 'safe_read', lambda path: raw[path.name])
    def git(path: Path, *args: str) -> bytes:
        if args == ('rev-parse', 'HEAD'):
            return c.BASE.encode()
        if args == ('rev-parse', '--show-toplevel'):
            return str(root).encode()
        if args[0] == 'show':
            revision, name = args[1].split(':', 1)
            if revision == c.BASE:
                assert name == 'existing.py'
                return b'incorrect old bytes' if change == 'old-blob' else b'old reviewed bytes'
            if name == 'existing.py' and change == 'staged-modified':
                return b'tampered staged replacement'
            return raw[name]
        if args[:3] == ('diff', '--cached', '--name-status'):
            rows = ['A\tnew.py', 'A\t' + c.MANIFEST]
            if change != 'missing-modified':
                rows.append(('A' if change == 'modified-as-added' else 'M') + '\texisting.py')
            if change == 'extra-modified':
                rows.append('M\tunreviewed.py')
            return '\n'.join(rows).encode()
        if args[:2] == ('ls-files', '--stage'):
            return '\n'.join('100644 ' + 'a' * 40 + ' 0\t' + name for name in files).encode()
        return b''
    monkeypatch.setattr(c, 'git', git)
    result = c.check(root, c.BASE)
    assert bool(result['failures']) == bool(change)
    if change == 'old-blob':
        assert result['failures'][0]['rule'] == 'MODIFIED_BASE_HASH_MISMATCH'
    if change == 'staged-modified':
        assert result['failures'][0]['rule'] == 'PAYLOAD_HASH_MISMATCH'
