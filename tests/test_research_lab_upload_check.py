"""Reviewed package cannot hide mismatches or disclose raw private errors."""
import hashlib
import json
from pathlib import Path

import pytest

import research_lab_upload_check as checker
from overnight_upload_check import UploadCheckFailure


def fixture(root: Path) -> dict[str, object]:
    for name in checker.FILES:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'public\n')
    (root / 'dependency.py').write_bytes(b'public\n')
    digest = hashlib.sha256(b'public\n').hexdigest()
    body: dict[str, object] = {'version': 'research-lab-reviewed-upload-v1',
        'files': [{'destination': name, 'sha256_lf': None if name == checker.MANIFEST else digest}
                  for name in checker.FILES],
        'prerequisites': [{'destination': 'dependency.py', 'sha256_lf': digest}]}
    (root / checker.MANIFEST).write_text(json.dumps(body), encoding='utf-8')
    return body


def test_exact_public_package(tmp_path: Path) -> None:
    fixture(tmp_path)
    checker.verify(tmp_path, set(checker.FILES))


def test_hash_mismatch_is_diagnostic(tmp_path: Path) -> None:
    fixture(tmp_path)
    (tmp_path / 'dependency.py').write_bytes(b'changed\n')
    with pytest.raises(UploadCheckFailure) as result:
        checker.verify(tmp_path, set(checker.FILES))
    assert result.value.rule == 'SOURCE_HASH_MISMATCH'
    assert result.value.failures[0]['path'] == 'dependency.py'
    assert result.value.failures[0]['actual'] == hashlib.sha256(b'changed\n').hexdigest()


@pytest.mark.parametrize('changed', [set(), set(checker.FILES) | {'unrelated.py'}])
def test_exact_paths(tmp_path: Path, changed: set[str]) -> None:
    fixture(tmp_path)
    with pytest.raises(ValueError, match='EXACT_UPLOAD_PATHS_REQUIRED'):
        checker.verify(tmp_path, changed)


@pytest.mark.parametrize('payload', ['[]', '{', '{"version":1,"version":2}'])
def test_invalid_manifest(tmp_path: Path, payload: str) -> None:
    fixture(tmp_path)
    (tmp_path / checker.MANIFEST).write_text(payload)
    with pytest.raises(ValueError):
        checker.verify(tmp_path, set(checker.FILES))


def test_cli_error_redaction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                             capsys: pytest.CaptureFixture[str]) -> None:
    def failed(*args: object) -> str:
        raise RuntimeError('PRIVATE_URL_TOKEN')
    monkeypatch.setattr(checker, 'git', failed)
    assert checker.main(['--root', str(tmp_path), '--base', 'a'*40]) == 2
    assert 'PRIVATE' not in capsys.readouterr().out


def test_missing_source_rejected(tmp_path: Path) -> None:
    fixture(tmp_path)
    # Every missing source also blocks, irrespective of trust in a manifest.
    (tmp_path / 'dependency.py').unlink()
    with pytest.raises(UploadCheckFailure, match='SOURCE_MISSING_OR_TOO_LARGE'):
        checker.verify(tmp_path, set(checker.FILES))


def test_exact_public_secret_access_module_not_credentials(tmp_path: Path) -> None:
    target = tmp_path / 'managed_secrets.py'
    target.write_bytes(b'public code\n')
    assert checker.source(tmp_path, 'managed_secrets.py') == target
    for name in ('secrets.toml', 'client_secret.json', 'other_secrets.py'):
        with pytest.raises(ValueError, match='PATH_INVALID'):
            checker.source(tmp_path, name)
    failure = checker.LabUploadFailure('SOURCE_HASH_MISMATCH', [{'path': 'managed_secrets.py',
        'kind': 'prerequisite', 'expected': 'a'*64, 'actual': 'b'*64}])
    assert failure.failures[0]['path'] == 'managed_secrets.py'
