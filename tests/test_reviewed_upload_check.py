"""Deterministic synthetic file and read-only Git-boundary checks."""
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import reviewed_upload_check as check


def entry(name: str, data: bytes) -> dict[str, Any]:
    return {'source': name, 'destination': name,
            'sha256_lf': hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()}


def test_all_files_and_exact_changed_paths(tmp_path: Path) -> None:
    path = tmp_path / 'example.py'
    path.write_bytes(b'pass\r\n')
    items = [entry('example.py', b'pass\n')]
    check.validate_files(tmp_path, items, {'example.py'})
    check.validate_files(tmp_path, items, set())  # Already identical in actual base.
    with pytest.raises(ValueError, match='CHANGED_PATH_SET_INVALID'):
        check.validate_files(tmp_path, items, {'extra.py'})
    path.write_bytes(b'wrong\n')
    with pytest.raises(ValueError, match='SOURCE_HASH_MISMATCH'):
        check.validate_files(tmp_path, items, {'example.py'})


@pytest.mark.parametrize('name', ['../x.py', '/x.py', 'C:/x.py', '.streamlit/secrets.toml',
                                 'client_secret.txt', 'client_secret.json', 'token.json', 'a\\b.py'])
def test_invalid_names(name: str) -> None:
    with pytest.raises(ValueError):
        check.relative(name)


def test_missing_duplicate_and_bad_hash(tmp_path: Path) -> None:
    items = [entry('missing.py', b'pass')]
    with pytest.raises(ValueError, match='SOURCE_MISSING'):
        check.validate_files(tmp_path, items, set())
    with pytest.raises(ValueError, match='CHANGED_PATH_SET'):
        check.validate_files(tmp_path, items * 2, set())
    (tmp_path / 'missing.py').write_bytes(b'pass')
    items[0]['sha256_lf'] = None
    with pytest.raises(ValueError, match='MANIFEST_HASH'):
        check.validate_files(tmp_path, items, set())


def test_main_actual_base_and_no_mutations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / 'sample.py').write_bytes(b'pass')
    manifest = {'version': 'remaining-uploads-v1', 'groups': {'capture': [
        entry('sample.py', b'pass'), {'destination': check.MANIFEST, 'sha256_lf': None}]}}
    (tmp_path / check.MANIFEST).write_text(json.dumps(manifest), encoding='utf-8')
    calls: list[tuple[str, ...]] = []

    def git(root: Path, *args: str) -> str:
        calls.append(args)
        responses = {('rev-parse', 'HEAD'): 'a' * 40,
                     ('rev-parse', '--show-toplevel'): str(tmp_path),
                     ('diff', '--name-only', 'a' * 40, '--'): '',
                     ('ls-files', '--others', '--exclude-standard'): 'sample.py\n' + check.MANIFEST}
        return responses[args]

    monkeypatch.setattr(check, 'git', git)
    assert check.main(['--group', 'capture', '--base', 'a' * 40, '--root', str(tmp_path)]) == 0
    assert len(calls) == 4
    assert 'REQUIRES_TESTS_AND_CI' in capsys.readouterr().out
    assert check.main(['--group', 'capture', '--base', 'b' * 40, '--root', str(tmp_path)]) == 2
    assert 'BASE_NOT_CURRENT_HEAD' in capsys.readouterr().out
