from __future__ import annotations

import json
from pathlib import Path

from security_profile_successors import regression_hash

import pytest

import recovery_contract_upload_check as c


def test_real_manifest_hashes_and_pinned_dependencies() -> None:
    root = Path(__file__).resolve().parents[1]
    value = json.loads(c.safe_read(root / c.MANIFEST))
    assert value['base'] == c.BASE and value['version'] == c.VERSION
    assert set(value['files']) == set(c.FILES)
    assert value['prerequisites'] == c.PREREQUISITES
    assert value['files'][c.MANIFEST] is None
    for name, digest in value['files'].items():
        if name != c.MANIFEST:
            assert c.sha(c.safe_read(root / name)) == regression_hash(root, name, digest), name
    for name, digest in c.PREREQUISITES.items():
        assert c.sha(c.safe_read(root / name)) == regression_hash(root, name, digest), name


@pytest.mark.parametrize('tamper', ['', 'head', 'root', 'manifest', 'hash', 'staged', 'pin',
    'paths', 'mode', 'conflict', 'unstaged', 'untracked', 'raw', 'exception'])
def test_fail_closed_public_upload_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: str) -> None:
    files = ('new.py', c.MANIFEST)
    content = {'new.py': b'new public bytes', 'dependency.py': b'reviewed prerequisite'}
    pins = {'dependency.py': c.sha(content['dependency.py'])}
    value = dict(version=c.VERSION, base=c.BASE,
        files={'new.py': c.sha(content['new.py']), c.MANIFEST: None}, prerequisites=pins)
    if tamper == 'manifest':
        value['version'] = 'wrong'
    content[c.MANIFEST] = json.dumps(value).encode()
    monkeypatch.setattr(c, 'FILES', files)
    monkeypatch.setattr(c, 'PREREQUISITES', pins)
    monkeypatch.setattr(c, 'safe_read', lambda path: content[path.name])
    def git(root: Path, *args: str) -> bytes:
        if tamper == 'exception':
            raise RuntimeError('synthetic private error must not escape')
        if args == ('rev-parse', 'HEAD'):
            return ('f' * 40 if tamper == 'head' else c.BASE).encode()
        if args == ('rev-parse', '--show-toplevel'):
            return str(tmp_path / 'wrong' if tamper == 'root' else tmp_path).encode()
        if args[0] == 'show':
            name = args[1].split(':', 1)[1]
            if (name == 'dependency.py' and tamper == 'pin'
                    or name == 'new.py' and tamper in ('hash', 'staged')
                    or name == c.MANIFEST and tamper == 'raw'):
                return b'changed'
            return content[name]
        if args[:3] == ('diff', '--cached', '--name-status'):
            return '\n'.join(('M' if tamper == 'paths' else 'A') + '\t' + name for name in files).encode()
        if args[:2] == ('ls-files', '--stage'):
            mode = '100755' if tamper == 'mode' else '100644'
            stage = '2' if tamper == 'conflict' else '0'
            return '\n'.join(f'{mode} {"a" * 40} {stage}\t{name}' for name in files).encode()
        if args[:2] == ('diff', '--name-only') and tamper == 'unstaged':
            return b'extra.py'
        if args[:2] == ('ls-files', '--others') and tamper == 'untracked':
            return b'extra.py'
        return b''
    monkeypatch.setattr(c, 'git', git)
    result = c.check(tmp_path, c.BASE)
    assert bool(result['failures']) == bool(tamper)
    assert result['restore_authorised'] is False
    assert 'synthetic private error' not in json.dumps(result)
    if tamper == 'pin':
        assert {'path', 'expected', 'actual', 'location'} <= result['failures'][0].keys()


def test_wrong_base_rejected_without_reading_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object) -> bytes:
        raise AssertionError('No reads allowed')
    monkeypatch.setattr(c, 'safe_read', forbidden)
    monkeypatch.setattr(c, 'git', forbidden)
    assert c.check(tmp_path, 'wrong')['failures'] == [{'rule': 'EXACT_BASE_REQUIRED'}]
