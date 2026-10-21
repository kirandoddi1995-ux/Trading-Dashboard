"""Exact package pins and synthetic read-only index checks; no private filesystem."""
import json
from pathlib import Path
from typing import Any

import pytest

import archive_verify_upload_check as checker
from live_backup_upload_check import reviewed_successor_hash as security_successor_hash


def test_final_manifest_and_public_prerequisite_hashes() -> None:
    root = Path(__file__).resolve().parents[1]
    value = json.loads(checker.safe_read(root / checker.MANIFEST), object_pairs_hook=checker.unique)
    assert value['base'] == checker.BASE
    assert value['prerequisites'] == checker.PREREQUISITES
    assert value['modified_base_files'] == checker.MODIFIED == {}
    assert set(value['files']) == set(checker.FILES)
    for name, pin in value['files'].items():
        if name == checker.MANIFEST:
            assert pin is None
        else:
            assert checker.sha(checker.safe_read(root / name)) == security_successor_hash(root, name, pin)
    for name, pin in checker.PREREQUISITES.items():
        assert checker.sha(checker.safe_read(root / name)) == security_successor_hash(root, name, pin)


def test_wrong_base_has_no_git_or_file_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any) -> bytes:
        raise AssertionError('NO_IO')
    monkeypatch.setattr(checker, 'git', forbidden)
    monkeypatch.setattr(checker, 'safe_read', forbidden)
    assert checker.check(Path.cwd(), 'bad')['failures'] == [{'rule': 'EXACT_BASE_REQUIRED'}]


@pytest.mark.parametrize('tamper', ['', 'payload', 'index', 'prerequisite', 'extra', 'mode',
                                   'untracked', 'unstaged', 'manifest', 'dirty_base'])
def test_synthetic_staged_index_contract(monkeypatch: pytest.MonkeyPatch, tamper: str) -> None:
    root = Path.cwd()
    files = ('added.py', checker.MANIFEST)
    prereqs = {'fixed.py': checker.sha(b'fixed')}
    monkeypatch.setattr(checker, 'FILES', files)
    monkeypatch.setattr(checker, 'PREREQUISITES', prereqs)
    raw = {'added.py': b'new', 'fixed.py': b'fixed'}
    raw[checker.MANIFEST] = json.dumps(dict(version='archive-verify-upload-v1', base=checker.BASE,
        files={'added.py': checker.sha(raw['added.py']), checker.MANIFEST: None},
        modified_base_files={}, prerequisites=prereqs)).encode()
    def read(path: Path) -> bytes:
        return b'changed' if tamper == 'payload' and path.name == 'added.py' else raw[path.name]
    def git(path: Path, *args: str) -> bytes:
        if args == ('rev-parse', 'HEAD'):
            return ('bad' if tamper == 'dirty_base' else checker.BASE).encode()
        if args == ('rev-parse', '--show-toplevel'):
            return str(root).encode()
        if args[0] == 'show':
            name = args[1].split(':', 1)[1]
            if (tamper == 'index' and name == 'added.py' or tamper == 'prerequisite' and name == 'fixed.py'
                    or tamper == 'manifest' and name == checker.MANIFEST):
                return b'changed'
            return raw[name]
        if args[:3] == ('diff', '--cached', '--name-status'):
            return ('\n'.join('A\t' + name for name in files) + ('\nA\textra' if tamper == 'extra' else '')).encode()
        if args[:2] == ('ls-files', '--stage'):
            return '\n'.join(('100755' if tamper == 'mode' else '100644') + ' ' + 'a' * 40 + ' 0\t' + name for name in files).encode()
        if tamper == 'untracked' and args[:2] == ('ls-files', '--others'):
            return b'extra'
        if tamper == 'unstaged' and args[:2] == ('diff', '--name-only'):
            return b'added.py'
        return b''
    monkeypatch.setattr(checker, 'safe_read', read)
    monkeypatch.setattr(checker, 'git', git)
    result = checker.check(root, checker.BASE)
    assert (result['status'] == 'BLOCKED') == bool(tamper)
    assert result['run_authorised'] is False
    if tamper == 'prerequisite':
        assert result['failures'][0]['path'] == 'fixed.py'
        assert {'expected', 'actual', 'location'} <= result['failures'][0].keys()
