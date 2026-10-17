import json
from pathlib import Path
from typing import Any

import pytest

import isolated_identity_upload_check as checker


def test_manifest_payloads_and_fixed_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    value = json.loads(checker.safe_read(root / checker.MANIFEST), object_pairs_hook=checker.unique)
    assert value['base'] == checker.BASE
    assert value['modified_base_files'] == checker.MODIFIED
    assert value['prerequisites'] == checker.PREREQUISITES
    assert set(value['files']) == set(checker.FILES)
    for name, expected in value['files'].items():
        assert (expected is None) if name == checker.MANIFEST else checker.sha(checker.safe_read(root / name)) == expected


def test_wrong_base_stops_without_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any) -> bytes:
        raise AssertionError('NO_GIT')
    monkeypatch.setattr(checker, 'git', forbidden)
    assert checker.check(tmp_path, 'bad')['failures'] == [{'rule': 'EXACT_BASE_REQUIRED'}]


@pytest.mark.parametrize('tamper', ['', 'base', 'payload', 'extra', 'mode', 'prerequisite'])
def test_synthetic_staging_and_redacted_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: str) -> None:
    root = Path(__file__).resolve().parents[1]
    raw = {name: checker.safe_read(root / name) for name in (*checker.FILES, *checker.PREREQUISITES)}
    for name, value in raw.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    def git(path: Path, *args: str) -> bytes:
        if args == ('rev-parse', 'HEAD'):
            return checker.BASE.encode()
        if args == ('rev-parse', '--show-toplevel'):
            return str(tmp_path).encode()
        if args[0] == 'show':
            target = args[1].split(':', 1)[1]
            if args[1].startswith(checker.BASE + ':') and target in checker.MODIFIED:
                # Hash is injected below for this synthetic old tree.
                return b'old'
            if tamper == 'prerequisite' and target in checker.PREREQUISITES:
                return b'bad'
            return raw[target]
        if args[:3] == ('diff', '--cached', '--name-status'):
            return ('\n'.join(('M' if x in checker.MODIFIED else 'A') + '\t' + x for x in checker.FILES)
                    + ('\nA\textra.py' if tamper == 'extra' else '')).encode()
        if args[:2] == ('ls-files', '--stage'):
            mode = '100755' if tamper == 'mode' else '100644'
            return '\n'.join(mode + ' ' + 'a' * 40 + ' 0\t' + x for x in checker.FILES).encode()
        return b''
    old_sha = checker.sha
    def sha(value: bytes) -> str:
        if value == b'old':
            return 'bad' if tamper == 'base' else checker.MODIFIED[next(iter(checker.MODIFIED))]
        return old_sha(value)
    # Give all synthetic old files one immutable expected old hash.
    modified = {name: 'a' * 64 for name in checker.MODIFIED}
    monkeypatch.setattr(checker, 'MODIFIED', modified)
    manifest = json.loads(raw[checker.MANIFEST])
    manifest['modified_base_files'] = modified
    raw[checker.MANIFEST] = json.dumps(manifest).encode()
    (tmp_path / checker.MANIFEST).write_bytes(raw[checker.MANIFEST])
    if tamper == 'payload':
        (tmp_path / 'isolated_alert_reconcile.ps1').write_bytes(b'changed')
    monkeypatch.setattr(checker, 'git', git)
    monkeypatch.setattr(checker, 'sha', sha)
    result = checker.check(tmp_path, checker.BASE)
    assert (result['status'] == 'BLOCKED') is bool(tamper)
    assert result['retry_authorised'] is False
    if tamper == 'base':
        assert result['failures'][0]['rule'] == 'BASE_HASH_MISMATCH'
        assert set(result['failures'][0]) == {'rule', 'path', 'expected', 'actual'}
