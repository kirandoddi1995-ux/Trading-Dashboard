import json
from pathlib import Path
from typing import Any

import pytest

import recovery_incident_upload_check as checker



def test_final_manifest_and_builder_staged_source_mapping() -> None:
    root = Path(__file__).resolve().parents[1]
    value = json.loads(checker.safe_read(root / checker.MANIFEST), object_pairs_hook=checker.unique)
    assert value['base'] == checker.BASE
    assert value['modified_base_files'] == checker.MODIFIED
    assert value['prerequisites'] == checker.PREREQUISITES
    assert set(value['files']) == set(checker.FILES)
    for name, expected in value['files'].items():
        path = root / name
        assert (expected is None) if name == checker.MANIFEST else checker.sha(checker.safe_read(path)) == expected
    for name, expected in checker.PREREQUISITES.items():
        assert checker.sha(checker.safe_read(root / name)) == expected


def test_wrong_base_has_no_io(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any) -> bytes:
        raise AssertionError('NO_IO')
    monkeypatch.setattr(checker, 'git', forbidden)
    assert checker.check(tmp_path, 'bad')['failures'] == [{'rule': 'EXACT_BASE_REQUIRED'}]


@pytest.mark.parametrize('tamper', ['', 'base', 'payload', 'index', 'prerequisite', 'extra', 'mode', 'untracked', 'manifest'])
def test_synthetic_fixed_base_staging_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: str) -> None:
    files = ('modified.py', 'added.py', checker.MANIFEST)
    modified = {'modified.py': checker.sha(b'old')}
    prereqs = {'fixed.py': checker.sha(b'fixed')}
    monkeypatch.setattr(checker, 'FILES', files)
    monkeypatch.setattr(checker, 'MODIFIED', modified)
    monkeypatch.setattr(checker, 'PREREQUISITES', prereqs)
    raw = {'modified.py': b'new', 'added.py': b'added', 'fixed.py': b'fixed'}
    raw[checker.MANIFEST] = json.dumps(dict(version='recovery-incident-upload-v1', base=checker.BASE,
        files={**{name: checker.sha(raw[name]) for name in files if name != checker.MANIFEST}, checker.MANIFEST: None},
        modified_base_files=modified, prerequisites=prereqs)).encode()
    for name, value in raw.items():
        (tmp_path / name).write_bytes(value)
    if tamper == 'payload':
        (tmp_path / 'added.py').write_bytes(b'changed')
    def git(path: Path, *args: str) -> bytes:
        if args == ('rev-parse', 'HEAD'):
            return checker.BASE.encode()
        if args == ('rev-parse', '--show-toplevel'):
            return str(tmp_path).encode()
        if args[0] == 'show':
            name = args[1].split(':', 1)[1]
            if args[1].startswith(checker.BASE + ':') and name in modified:
                return b'changed' if tamper == 'base' else b'old'
            if (tamper == 'index' and name == 'added.py'
                    or tamper == 'prerequisite' and name == 'fixed.py'
                    or tamper == 'manifest' and name == checker.MANIFEST):
                return b'changed'
            return raw[name]
        if args[:3] == ('diff', '--cached', '--name-status'):
            return ('\n'.join(('M' if name in modified else 'A') + '\t' + name for name in files)
                    + ('\nA\textra' if tamper == 'extra' else '')).encode()
        if args[:2] == ('ls-files', '--stage'):
            return '\n'.join(('100755' if tamper == 'mode' else '100644') + ' ' + 'a' * 40 + ' 0\t' + name for name in files).encode()
        if tamper == 'untracked' and args[:2] == ('ls-files', '--others'):
            return b'extra'
        return b''
    monkeypatch.setattr(checker, 'git', git)
    result = checker.check(tmp_path, checker.BASE)
    assert (result['status'] == 'BLOCKED') is bool(tamper)
    if tamper == 'base':
        assert result['failures'][0]['rule'] == 'MODIFIED_BASE_HASH_MISMATCH'
        assert {'path', 'expected', 'actual'} <= result['failures'][0].keys()
    assert result['run_authorised'] is False
