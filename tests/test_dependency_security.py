"""Security transition and fail-closed CI topology, using only public fixtures."""
from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

import live_backup_upload_check as c

ROOT = Path(__file__).resolve().parents[1]


def test_certifi_patch_is_the_only_dependency_change() -> None:
    data = (ROOT / 'constraints.txt').read_bytes().replace(b'\r\n', b'\n')
    assert data.count(b'certifi==2026.10.19\n') == 1
    original = data.replace(b'certifi==2026.10.19\n', b'certifi==2026.7.22\n')
    assert c.sha(original) == c.MODIFIED_BASE_HASHES['constraints.txt']
    assert '-c constraints.txt' in (ROOT / 'requirements.txt').read_text().splitlines()
    assert 'certifi==2026.10.19' in (ROOT / 'requirements-forward-operations.txt').read_text()
    import future_ops_diagnostics as diagnostics
    assert diagnostics.PINS['certifi'] == '2026.10.19'
    assert diagnostics.package_check(ROOT).status == 'CHECKED'


def test_quality_has_separate_hard_audit_and_no_packaging_bypass() -> None:
    text = (ROOT / '.github/workflows/quality.yml').read_text()
    audit = text.index('- run: python -m pip_audit -r requirements.txt')
    assert text.count('python -m pip_audit -r requirements.txt') == 1
    assert 'continue-on-error' not in text and '--ignore-vuln' not in text
    assert '--no-deps' not in text and '--disable-pip' not in text
    assert text.index('python -m pytest -q\n') < text.index('python resilience_acceptance.py --game-day') < audit
    assert audit < text.index('python deployment_canary.py') < text.index('python package_release.py')
    assert 'if:' not in text and '||' not in text[audit:]
    assert 'secrets.' not in text and 'contents: read' in text
    assert re.findall(r'runs-on: (\S+)', text) == ['ubuntu-24.04']


def fixture_manifest() -> dict[str, object]:
    return dict(version=c.VERSION, base=c.BASE,
        files={name: None if name == c.MANIFEST else c.SECURITY_PIN_SUCCESSORS.get(name, 'a' * 64) for name in c.FILES},
        prerequisites=c.PREREQUISITES)


@pytest.mark.parametrize('change', ['', 'old-hash', 'base', 'version', 'keys', 'pin',
    'null', 'malformed', 'missing', 'duplicate', 'arbitrary-successor'])
def test_security_successor_is_explicit_not_a_hash_fallback(tmp_path: Path, change: str) -> None:
    value = fixture_manifest()
    name = 'constraints.txt'
    files = value['files']
    assert isinstance(files, dict)
    if change == 'base':
        value['base'] = 'wrong'
    elif change == 'version':
        value['version'] = 'wrong'
    elif change == 'keys':
        value['unexpected'] = True
    elif change == 'pin':
        value['prerequisites'] = {}
    elif change == 'null':
        files[name] = None
    elif change == 'malformed':
        files[name] = 'not a digest'
    elif change == 'missing':
        del files[name]
    elif change == 'arbitrary-successor':
        files[name] = 'a' * 64
    raw = json.dumps(value)
    if change == 'duplicate':
        raw = raw[:-1] + ', "base": "wrong"}'
    (tmp_path / c.MANIFEST).write_text(raw)
    old = 'b' * 64 if change == 'old-hash' else c.MODIFIED_BASE_HASHES[name]
    if change:
        with pytest.raises(ValueError):
            c.reviewed_successor_hash(tmp_path, name, old)
    else:
        assert c.reviewed_successor_hash(tmp_path, name, old) == c.SECURITY_PIN_SUCCESSORS[name]
    # An unrelated path never gets a successor, even with a corrupt manifest.
    assert c.reviewed_successor_hash(tmp_path, 'unrelated.py', 'b' * 64) == 'b' * 64


@pytest.mark.parametrize('change', ['', 'old-blob', 'modified-as-added', 'missing', 'index', 'fixed-pin'])
def test_staged_replacement_requires_old_and_new_exact_bytes(tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    files = ('existing.txt', 'new.py', c.MANIFEST)
    modified = {'existing.txt': c.sha(b'old')}
    raw = {'existing.txt': b'new', 'new.py': b'added'}
    raw[c.MANIFEST] = json.dumps(dict(version=c.VERSION, base=c.BASE,
        files={name: None if name == c.MANIFEST else c.sha(raw[name]) for name in files},
        prerequisites={})).encode()
    monkeypatch.setattr(c, 'FILES', files)
    monkeypatch.setattr(c, 'PREREQUISITES', {})
    monkeypatch.setattr(c, 'MODIFIED_BASE_HASHES', modified)
    monkeypatch.setattr(c, 'SECURITY_PIN_SUCCESSORS', {'existing.txt': c.sha(b'new')})
    if change == 'fixed-pin':
        value = json.loads(raw[c.MANIFEST])
        value['files']['existing.txt'] = c.sha(b'old')
        raw[c.MANIFEST] = json.dumps(value).encode()
    monkeypatch.setattr(c, 'safe_read', lambda path: raw[path.name])
    def git(root: Path, *args: str) -> bytes:
        if args == ('rev-parse', 'HEAD'):
            return c.BASE.encode()
        if args == ('rev-parse', '--show-toplevel'):
            return str(tmp_path).encode()
        if args[0] == 'show':
            revision, name = args[1].split(':', 1)
            if revision == c.BASE:
                return b'bad' if change == 'old-blob' else b'old'
            return b'bad' if change == 'index' and name == 'existing.txt' else raw[name]
        if args[:3] == ('diff', '--cached', '--name-status'):
            rows = ['A\tnew.py', 'A\t' + c.MANIFEST]
            if change != 'missing':
                rows.append(('A' if change == 'modified-as-added' else 'M') + '\texisting.txt')
            return '\n'.join(rows).encode()
        if args[:2] == ('ls-files', '--stage'):
            return '\n'.join('100644 ' + 'a' * 40 + ' 0\t' + name for name in files).encode()
        return b''
    monkeypatch.setattr(c, 'git', git)
    assert bool(c.check(tmp_path, c.BASE)['failures']) == bool(change)
