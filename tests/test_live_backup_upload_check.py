"""Public manifest/staging verification, no operational IO."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import live_backup_upload_check as c


def test_real_payload_hashes_and_prerequisites() -> None:
    root = Path(__file__).resolve().parents[1]
    value = json.loads(c.safe_read(root / c.MANIFEST))
    assert value['base'] == c.BASE and value['version'] == c.VERSION
    assert set(value['files']) == set(c.FILES) and value['files'][c.MANIFEST] is None
    assert value['prerequisites'] == c.PREREQUISITES
    for name, expected in value['files'].items():
        if name != c.MANIFEST:
            assert c.sha(c.safe_read(root / name)) == expected, name
    for name, expected in c.PREREQUISITES.items():
        assert c.sha(c.safe_read(root / name)) == expected, name


@pytest.mark.parametrize('tamper', ['', 'head', 'root', 'manifest', 'hash', 'pin',
    'paths', 'mode', 'conflict', 'unstaged', 'untracked', 'raw', 'exception'])
def test_staging_gate_redacted_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: str) -> None:
    files = ('new.py', c.MANIFEST)
    content = {'new.py': b'public new bytes', 'dependency.py': b'reviewed dependency'}
    pins = {'dependency.py': c.sha(content['dependency.py'])}
    value = dict(version=c.VERSION, base=c.BASE,
        files={'new.py': c.sha(content['new.py']), c.MANIFEST: None}, prerequisites=pins)
    if tamper == 'manifest':
        value['version'] = 'wrong'
    content[c.MANIFEST] = json.dumps(value).encode()
    monkeypatch.setattr(c, 'FILES', files)
    monkeypatch.setattr(c, 'MODIFIED_BASE_HASHES', {})
    monkeypatch.setattr(c, 'PREREQUISITES', pins)
    monkeypatch.setattr(c, 'safe_read', lambda path: content[path.name])
    def git(root: Path, *args: str) -> bytes:
        if tamper == 'exception':
            raise RuntimeError('private-sentinel')
        if args == ('rev-parse', 'HEAD'):
            return ('a' * 40 if tamper == 'head' else c.BASE).encode()
        if args == ('rev-parse', '--show-toplevel'):
            return str(tmp_path / 'wrong' if tamper == 'root' else tmp_path).encode()
        if args[0] == 'show':
            name = args[1].split(':', 1)[1]
            if (name == 'new.py' and tamper == 'hash' or name == 'dependency.py' and tamper == 'pin'
                    or name == c.MANIFEST and tamper == 'raw'):
                return b'changed'
            return content[name]
        if args[:3] == ('diff', '--cached', '--name-status'):
            return '\n'.join(('M' if tamper == 'paths' else 'A') + '\t' + name for name in files).encode()
        if args[:2] == ('ls-files', '--stage'):
            mode, stage = ('100755' if tamper == 'mode' else '100644'), ('2' if tamper == 'conflict' else '0')
            return '\n'.join(f'{mode} {"a" * 40} {stage}\t{name}' for name in files).encode()
        if args[:2] == ('diff', '--name-only') and tamper == 'unstaged':
            return b'extra.py'
        if args[:2] == ('ls-files', '--others') and tamper == 'untracked':
            return b'extra.py'
        return b''
    monkeypatch.setattr(c, 'git', git)
    report = c.check(tmp_path, c.BASE)
    assert bool(report['failures']) == bool(tamper)
    assert report['run_authorised'] is False and report['restore_verified'] is False
    assert 'private-sentinel' not in json.dumps(report)
    if tamper == 'pin':
        assert {'path', 'expected', 'actual', 'location'} <= report['failures'][0].keys()
