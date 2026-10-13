"""Synthetic manifests; no credentials, owner state or GitHub access."""
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import forward_ops_upload_check as checker


def fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(checker, 'release_members', lambda *args: ['forward_session_ops.py', 'prerequisite.py'])
    manifest: dict[str, Any] = {'version': 'forward-operations-reviewed-v1', 'files': [], 'prerequisites': []}
    for name in (*checker.FILES, 'prerequisite.py', 'tests/test_overnight_capture_audit.py'):
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b'public\n')
        key = 'files' if name in checker.FILES else 'prerequisites'
        manifest[key].append({'destination': name, 'sha256_lf': None if name == checker.MANIFEST
                              else hashlib.sha256(b'public\n').hexdigest()})
    return manifest


def test_exact_and_diagnostic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    value = fixture(tmp_path, monkeypatch)
    (tmp_path / checker.MANIFEST).write_text(json.dumps(value))
    assert checker.verify(tmp_path, set(checker.FILES)) == []
    (tmp_path / 'prerequisite.py').write_bytes(b'changed\n')
    failures = checker.verify(tmp_path, set(checker.FILES))
    assert failures[0]['path'] == 'prerequisite.py'
    assert set(failures[0]) == {'path', 'expected', 'actual'}


@pytest.mark.parametrize('kind', ['missing_pin', 'extra_path', 'duplicate_pin', 'bad_hash'])
def test_cannot_loosen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    value = fixture(tmp_path, monkeypatch)
    changed = set(checker.FILES)
    if kind == 'missing_pin':
        value['prerequisites'].pop()
    elif kind == 'duplicate_pin':
        value['prerequisites'].append(value['prerequisites'][0])
    elif kind == 'extra_path':
        changed.add('private.json')
    else:
        value['files'][0]['sha256_lf'] = 'wrong'
    (tmp_path / checker.MANIFEST).write_text(json.dumps(value))
    with pytest.raises(ValueError):
        checker.verify(tmp_path, changed)


@pytest.mark.parametrize('name', ['../x.py', '.streamlit/secrets.toml', 'client_secret.json', 'token.py', 'C:/x.py'])
def test_private_path_blocked(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError):
        checker.source(tmp_path, name)


@pytest.mark.parametrize('current', [True, False])
def test_base_is_exact_current_head_not_historical_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], current: bool,
) -> None:
    """A reviewed newer tree is supported; a stale base cannot bypass its pins."""
    value = fixture(tmp_path, monkeypatch)
    (tmp_path / checker.MANIFEST).write_text(json.dumps(value))
    head = 'f' * 40

    def fake_git(root: Path, *args: str) -> str:
        assert root == tmp_path.resolve()
        if args == ('rev-parse', 'HEAD'):
            return head
        if args == ('rev-parse', '--show-toplevel'):
            return str(tmp_path)
        if args == ('diff', '--name-only', '--'):
            return ''
        if args == ('diff', '--name-only', head, '--'):
            return '\n'.join(checker.FILES)
        if args == ('ls-files', '--others', '--exclude-standard'):
            return ''
        raise AssertionError('Unexpected Git operation')

    monkeypatch.setattr(checker, 'git', fake_git)
    result = checker.main(['--root', str(tmp_path), '--base', head if current else 'a' * 40])
    report = json.loads(capsys.readouterr().out)
    assert result == (0 if current else 2)
    if current:
        assert report['status'] == 'UPLOAD_FILES_VERIFIED_REQUIRES_TESTS_AND_CI'
        assert report['failures'] == []
    else:
        assert report['rule'] == 'BASE_NOT_CURRENT_HEAD'
