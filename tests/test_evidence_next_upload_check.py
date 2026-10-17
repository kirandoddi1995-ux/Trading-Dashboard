import json
from pathlib import Path
from typing import Any

import pytest

import evidence_next_upload_check as checker


def test_final_manifest_integrity() -> None:
    root = Path(__file__).resolve().parents[1]
    value = json.loads(checker.safe_read(root / checker.MANIFEST), object_pairs_hook=checker.unique)
    assert value['base'] == checker.BASE
    assert value['prerequisites'] == checker.PREREQUISITES
    assert set(value['files']) == set(checker.FILES)
    for name, expected in value['files'].items():
        assert (expected is None) if name == checker.MANIFEST else checker.sha(checker.safe_read(root / name)) == expected
    for name, expected in checker.PREREQUISITES.items():
        assert checker.sha(checker.safe_read(root / name)) == expected


def test_wrong_base_performs_no_io(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any) -> bytes:
        raise AssertionError('NO_IO')
    monkeypatch.setattr(checker, 'git', forbidden)
    assert checker.check(tmp_path, 'bad')['failures'] == [{'rule': 'EXACT_BASE_REQUIRED'}]


@pytest.mark.parametrize('tamper', ['', 'worktree', 'index', 'prerequisite', 'extra', 'mode', 'unstaged', 'untracked', 'manifest'])
def test_synthetic_git_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: str) -> None:
    names = ('payload.py', checker.MANIFEST)
    monkeypatch.setattr(checker, 'FILES', names)
    prereqs = {'fixed.py': checker.sha(b'fixed')}
    monkeypatch.setattr(checker, 'PREREQUISITES', prereqs)
    raw = {'payload.py': b'payload', 'fixed.py': b'fixed'}
    raw[checker.MANIFEST] = json.dumps(dict(version='evidence-next-upload-v1', base=checker.BASE,
        files={'payload.py': checker.sha(b'payload'), checker.MANIFEST: None}, prerequisites=prereqs)).encode()
    for name, value in raw.items():
        (tmp_path / name).write_bytes(value)
    if tamper == 'worktree':
        (tmp_path / 'payload.py').write_bytes(b'changed')
    def git(path: Path, *args: str) -> bytes:
        if args == ('rev-parse', 'HEAD'):
            return checker.BASE.encode()
        if args == ('rev-parse', '--show-toplevel'):
            return str(tmp_path).encode()
        if args[0] == 'show':
            name = args[1].split(':', 1)[1]
            if (tamper == 'index' and name == 'payload.py'
                    or tamper == 'prerequisite' and name == 'fixed.py'
                    or tamper == 'manifest' and name == checker.MANIFEST):
                return b'changed'
            return raw[name]
        if args[:3] == ('diff', '--cached', '--name-status'):
            return ('\n'.join('A\t' + x for x in names) + ('\nA\textra' if tamper == 'extra' else '')).encode()
        if args[:2] == ('ls-files', '--stage'):
            return '\n'.join(('100755' if tamper == 'mode' else '100644') + ' ' + 'a' * 40 + ' 0\t' + x for x in names).encode()
        if tamper == 'unstaged' and args[:2] == ('diff', '--name-only'):
            return b'extra'
        if tamper == 'untracked' and args[:2] == ('ls-files', '--others'):
            return b'extra'
        return b''
    monkeypatch.setattr(checker, 'git', git)
    result = checker.check(tmp_path, checker.BASE)
    assert (result['status'] == 'BLOCKED') is bool(tamper)
    assert result['run_authorised'] is False
    if tamper == 'prerequisite':
        assert result['failures'][0]['rule'] == 'PREREQUISITE_HASH_MISMATCH'
        assert {'path', 'expected', 'actual', 'location'} <= result['failures'][0].keys()
