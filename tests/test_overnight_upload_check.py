"""Synthetic exact-tree checker failures; no dependency on later upload groups."""
import hashlib
import json
from pathlib import Path

import pytest

import overnight_upload_check as check


def fixture(root: Path) -> tuple[str, ...]:
    name = 'OVERNIGHT_CAPTURE_UPLOAD_2026-10-13.json'
    code = root / 'example.py'
    code.write_bytes(b'pass\r\n')
    content = {'version': 'overnight-reviewed-upload-v1', 'group': 'capture',
               'files': [{'destination': 'example.py', 'sha256_lf': hashlib.sha256(b'pass\n').hexdigest()},
                         {'destination': name, 'sha256_lf': None}], 'prerequisites': []}
    (root / name).write_text(json.dumps(content), encoding='utf-8')
    return ('example.py', name)


def test_exact(tmp_path: Path) -> None:
    allowed = fixture(tmp_path)
    check.verify(tmp_path, 'capture', allowed, set(allowed))


@pytest.mark.parametrize('path', ['../x.py', '/x.py', 'C:/x.py', 'tests\\x.py', '.streamlit/secrets.toml',
                                 'client_secret.json', 'x//y.py', '', 'data.csv'])
def test_bad_paths(path: str) -> None:
    with pytest.raises(ValueError):
        check.path_name(path)


@pytest.mark.parametrize('extra', ['extra.py', 'token.json'])
def test_extra(tmp_path: Path, extra: str) -> None:
    allowed = fixture(tmp_path)
    with pytest.raises(ValueError, match='EXACT_UPLOAD'):
        check.verify(tmp_path, 'capture', allowed, {*allowed, extra})


def test_tamper(tmp_path: Path) -> None:
    allowed = fixture(tmp_path)
    (tmp_path / 'example.py').write_bytes(b'changed')
    with pytest.raises(ValueError, match='SOURCE_HASH'):
        check.verify(tmp_path, 'capture', allowed, set(allowed))


def test_duplicate_keys(tmp_path: Path) -> None:
    allowed = fixture(tmp_path)
    (tmp_path / allowed[1]).write_text('{"group":"capture","group":"research"}', encoding='utf-8')
    with pytest.raises(ValueError, match='DUPLICATE'):
        check.verify(tmp_path, 'capture', allowed, set(allowed))


def test_nonmanifest_null_hash(tmp_path: Path) -> None:
    allowed = fixture(tmp_path)
    path = tmp_path / allowed[1]
    payload = json.loads(path.read_text(encoding='utf-8'))
    payload['files'][0]['sha256_lf'] = None
    path.write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(ValueError, match='HASH_INVALID'):
        check.verify(tmp_path, 'capture', allowed, set(allowed))


def test_wrong_base_without_git(tmp_path: Path) -> None:
    assert check.main('capture', (), ['--base', 'not-sha', '--root', str(tmp_path)]) == 2


def test_read_only_git_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    allowed = fixture(tmp_path)
    sha = 'a' * 40
    calls: list[tuple[str, ...]] = []

    def git(root: Path, *args: str) -> str:
        assert root == tmp_path.resolve()
        calls.append(args)
        if args == ('rev-parse', 'HEAD'):
            return sha
        if args == ('rev-parse', '--show-toplevel'):
            return str(tmp_path)
        if args == ('diff', '--name-only', sha, '--'):
            return ''
        if args == ('diff', '--name-only', '--'):
            return ''
        if args == ('ls-files', '--others', '--exclude-standard'):
            return '\n'.join(allowed)
        pytest.fail('unexpected Git operation')

    monkeypatch.setattr(check, 'git', git)
    assert check.main('capture', allowed, ['--base', sha, '--root', str(tmp_path)]) == 0
    assert len(calls) == 5


def test_staged_worktree_mismatch_blocks_before_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sha = 'a' * 40
    def git(root: Path, *args: str) -> str:
        if args == ('rev-parse', 'HEAD'):
            return sha
        if args == ('rev-parse', '--show-toplevel'):
            return str(root)
        if args == ('diff', '--name-only', '--'):
            return 'example.py'
        pytest.fail('mismatch must block immediately')
    monkeypatch.setattr(check, 'git', git)
    assert check.main('capture', (), ['--base', sha, '--root', str(tmp_path)]) == 2
