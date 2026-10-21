"""Exact package pins and synthetic read-only index checks; no private filesystem."""
import json
from pathlib import Path
from typing import Any

import pytest

import outcomes_large_upload_check as checker
from live_backup_upload_check import reviewed_successor_hash as security_successor_hash


def test_final_manifest_and_public_prerequisite_hashes() -> None:
    root = Path(__file__).resolve().parents[1]
    value = json.loads(checker.safe_read(root / checker.MANIFEST), object_pairs_hook=checker.unique)
    assert value['base'] == checker.BASE
    assert value['reviewed_pr_head'] == checker.REVIEWED_PR_HEAD
    assert value['prerequisites'] == checker.PREREQUISITES
    assert value['modified_base_files'] == checker.MODIFIED
    assert set(checker.MODIFIED) == {'tests/test_workflow_runtimes.py'}
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
                                   'untracked', 'unstaged', 'manifest', 'dirty_base', 'modified', 'modified_base',
                                   'update', 'wrong_update_head', 'wrong_parent', 'modified_payload', 'modified_index'])
def test_synthetic_staged_index_contract(monkeypatch: pytest.MonkeyPatch, tamper: str) -> None:
    root = Path.cwd()
    updating = tamper in ('update', 'wrong_update_head', 'wrong_parent')
    modified = {'fixed.py': checker.sha(b'old-fixed')} if tamper in ('modified', 'modified_base', 'modified_payload', 'modified_index') else {}
    files = ('added.py', 'fixed.py', checker.MANIFEST) if modified else ('added.py', checker.MANIFEST)
    prereqs = {'prereq.py': checker.sha(b'fixed')}
    monkeypatch.setattr(checker, 'FILES', files)
    monkeypatch.setattr(checker, 'PREREQUISITES', prereqs)
    monkeypatch.setattr(checker, 'MODIFIED', modified)
    raw = {'added.py': b'new', 'fixed.py': b'new-fixed', 'prereq.py': b'fixed'}
    raw[checker.MANIFEST] = json.dumps(dict(version='outcomes-large-upload-v2', base=checker.BASE,
        reviewed_pr_head=checker.REVIEWED_PR_HEAD,
        files={**{name: checker.sha(raw[name]) for name in files if name != checker.MANIFEST}, checker.MANIFEST: None},
        modified_base_files=modified, prerequisites=prereqs)).encode()
    def read(path: Path) -> bytes:
        if tamper == 'modified_payload' and path.name == 'fixed.py':
            return b'changed'
        return b'changed' if tamper == 'payload' and path.name == 'added.py' else raw[path.name]
    def git(path: Path, *args: str) -> bytes:
        if args == ('rev-parse', 'HEAD'):
            return ('bad' if tamper in ('dirty_base', 'wrong_update_head') else checker.REVIEWED_PR_HEAD if updating else checker.BASE).encode()
        if args == ('rev-parse', 'HEAD^'):
            return ('bad' if tamper == 'wrong_parent' else checker.BASE).encode()
        if args == ('rev-parse', '--show-toplevel'):
            return str(root).encode()
        if args[0] == 'show':
            name = args[1].split(':', 1)[1]
            if tamper == 'modified_base' and args[1] == checker.BASE + ':fixed.py':
                return b'changed'
            if args[1] == checker.BASE + ':fixed.py' and modified:
                return b'old-fixed'
            if (tamper == 'modified_index' and args[1] == ':fixed.py'
                    or tamper == 'index' and name == 'added.py' or tamper == 'prerequisite' and name == 'prereq.py'
                    or tamper == 'manifest' and name == checker.MANIFEST):
                return b'changed'
            return raw[name]
        if args[:3] == ('diff', '--cached', '--name-status'):
            return ('\n'.join(('M' if name in modified else 'A') + '\t' + name for name in files) + ('\nA\textra' if tamper == 'extra' else '')).encode()
        if args[:2] == ('ls-files', '--stage'):
            return '\n'.join(('100755' if tamper == 'mode' else '100644') + ' ' + 'a' * 40 + ' 0\t' + name for name in files).encode()
        if tamper == 'untracked' and args[:2] == ('ls-files', '--others'):
            return b'extra'
        if tamper == 'unstaged' and args[:2] == ('diff', '--name-only'):
            return b'added.py'
        return b''
    monkeypatch.setattr(checker, 'safe_read', read)
    monkeypatch.setattr(checker, 'git', git)
    result = checker.check(root, checker.BASE, updating)
    assert (result['status'] == 'BLOCKED') == (tamper not in ('', 'modified', 'update'))
    assert result['run_authorised'] is False
    if tamper == 'prerequisite':
        assert result['failures'][0]['path'] == 'prereq.py'
        assert {'expected', 'actual', 'location'} <= result['failures'][0].keys()
    if tamper == 'modified_base':
        assert result['failures'][0]['rule'] == 'MODIFIED_BASE_HASH_MISMATCH'
