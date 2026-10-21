"""Synthetic Git index contract and exact public source hashes."""
import json
import ast
from pathlib import Path
import sys
from typing import Any

import pytest

import archive_preservation_upload_check as c
from live_backup_upload_check import reviewed_successor_hash as security_successor_hash
from preservation_integer_upload_check import reviewed_successor_hash


def test_manifest_and_prerequisite_hashes() -> None:
    root = Path(__file__).resolve().parents[1]
    value = json.loads(c.safe_read(root / c.MANIFEST), object_pairs_hook=c.unique)
    assert value['version'] == c.VERSION and value['base'] == c.BASE
    assert value['prerequisites'] == c.PREREQUISITES
    assert set(value['files']) == set(c.FILES)
    for name, digest in value['files'].items():
        assert digest is None if name == c.MANIFEST else c.sha(c.safe_read(root / name)) == security_successor_hash(root, name, reviewed_successor_hash(root, name, digest))
    for name, digest in c.PREREQUISITES.items():
        assert c.sha(c.safe_read(root / name)) == security_successor_hash(root, name, reviewed_successor_hash(root, name, digest))


def test_runtime_import_closure_has_no_capture_transport_or_database() -> None:
    root = Path(__file__).resolve().parents[1]
    allowed = sys.stdlib_module_names | {'cryptography', 'archive_preservation_inventory',
                                        'programme_next_upload_check'}
    for name in ('archive_preservation_inventory.py', 'archive_preservation_witness.py',
                 'archive_preservation_upload_check.py', 'programme_next_upload_check.py'):
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
