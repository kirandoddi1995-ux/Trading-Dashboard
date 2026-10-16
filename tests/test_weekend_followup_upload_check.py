import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest

import weekend_followup_upload_check as checker


def test_only_public_ledger_csv_has_narrow_ignore_exception() -> None:
    rules = (Path(__file__).resolve().parents[1] / '.gitignore').read_text(encoding='utf8').splitlines()
    assert '*.csv' in rules
    assert '!PROJECT_STATUS_LEDGER_2026-10-16.csv' in rules
    assert '!*.csv' not in rules


def test_final_manifest_has_exact_payload_hashes_and_prerequisites() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads(checker.safe_read(root / checker.MANIFEST), object_pairs_hook=checker.unique)
    assert manifest['base'] == checker.BASE
    assert manifest['prerequisites'] == checker.PREREQUISITES
    assert set(manifest['files']) == set(checker.FILES)
    assert manifest['files'][checker.MANIFEST] is None
    for name in checker.FILES:
        if name != checker.MANIFEST:
            assert checker.sha(checker.safe_read(root / name)) == manifest['files'][name], name
    for name, expected in checker.PREREQUISITES.items():
        assert checker.sha(checker.safe_read(root / name)) == expected, name


def fake_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, str | None],dict[str, bytes]]:
    hashes: dict[str,str | None] = {}
    raw: dict[str,bytes] = {}
    for path in checker.FILES:
        target=tmp_path/path
        target.parent.mkdir(parents=True,exist_ok=True)
        payload=(path+'\n').encode()
        target.write_bytes(payload)
        raw[path]=payload
        hashes[path]=checker.sha(payload)
    hashes[checker.MANIFEST]=None
    prerequisites={'forward_daily_contract.py':checker.sha(b'fixed')}
    monkeypatch.setattr(checker,'PREREQUISITES',prerequisites)
    (tmp_path/'forward_daily_contract.py').write_bytes(b'fixed')
    manifest=dict(version=checker.VERSION,base=checker.BASE,files=hashes,prerequisites=prerequisites)
    raw[checker.MANIFEST]=json.dumps(manifest).encode()
    (tmp_path/checker.MANIFEST).write_bytes(raw[checker.MANIFEST])
    def git(root: Path,*args: str) -> bytes:
        if args[:2]==('rev-parse','--verify'): return checker.BASE.encode()
        if args==('rev-parse','HEAD'):return checker.BASE.encode()
        if args==('rev-parse','--show-toplevel'): return str(tmp_path).encode()
        if args[0]=='merge-base':return b''
        if args[0]=='show':
            path=args[1].split(':')[-1]
            return b'fixed' if path=='forward_daily_contract.py' else raw[path]
        if args[:3]==('diff','--cached','--name-only'):return '\n'.join(checker.FILES).encode()
        if args[:3]==('diff','--cached','--name-status'):return '\n'.join(('M' if p in checker.MODIFIED else 'A')+'\t'+p for p in checker.FILES).encode()
        if args[:2]==('ls-files','--stage'):return '\n'.join('100644 '+'a'*40+' 0\t'+p for p in checker.FILES).encode()
        return b''
    monkeypatch.setattr(checker,'git',git)
    return hashes,raw


def test_exact_fixed_package_and_no_operational_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_tree(tmp_path,monkeypatch)
    result=checker.check(tmp_path,checker.BASE)
    assert result['failures']==[]
    assert result['commissioning_verified'] is False


def test_hash_failure_names_file_expected_actual_and_stage(tmp_path: Path,monkeypatch: pytest.MonkeyPatch) -> None:
    hashes,_=fake_tree(tmp_path,monkeypatch)
    (tmp_path/'forward_saved_audit_status.py').write_bytes(b'changed')
    result=checker.check(tmp_path,checker.BASE)
    failure=next(x for x in result['failures'] if x['rule']=='PACKAGE_HASH_MISMATCH')
    assert failure['path']=='forward_saved_audit_status.py'
    assert failure['expected']==hashes['forward_saved_audit_status.py']
    assert failure['actual']==checker.sha(b'changed')


@pytest.mark.parametrize('change',[{'base':'f'*40},{'prerequisites':{}},{'files':{}}])
def test_no_pin_loosening(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str,Any]) -> None:
    fake_tree(tmp_path,monkeypatch)
    path=tmp_path/checker.MANIFEST
    manifest=json.loads(path.read_bytes());manifest.update(change)
    path.write_text(json.dumps(manifest),encoding='utf8')
    assert checker.check(tmp_path,checker.BASE)['failures'][0]['rule']=='MANIFEST_CONTRACT_INVALID'


def test_wrong_base_fails_before_read(tmp_path: Path) -> None:
    assert checker.check(tmp_path,'a'*40)['failures']==[{'rule':'EXACT_REVIEWED_BASE_REQUIRED'}]


def test_duplicate_manifest_keys_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_tree(tmp_path, monkeypatch)
    file = tmp_path / checker.MANIFEST
    raw = file.read_text(encoding='utf8')
    file.write_text('{"base":"ambiguous",' + raw[1:], encoding='utf8')
    assert checker.check(tmp_path, checker.BASE)['failures'] == [{'rule': 'DUPLICATE_MANIFEST_KEY'}]


def test_safe_read_rejects_links_before_reading(tmp_path: Path) -> None:
    target = tmp_path / 'target'; target.write_bytes(b'private synthetic')
    link = tmp_path / 'link'
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip('Windows symlink privilege unavailable; Linux exercises this case')
    with pytest.raises(ValueError, match='PACKAGE_LINK_REJECTED'):
        checker.safe_read(link)


def test_safe_read_rejects_large_regular_file(tmp_path: Path) -> None:
    file = tmp_path / 'large'
    with file.open('wb') as stream:
        stream.truncate(8*1024*1024+1)
    with pytest.raises(ValueError, match='BOUNDED_REGULAR_FILE_REQUIRED'):
        checker.safe_read(file)


def test_real_synthetic_git_index_modes_hashes_and_head(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not shutil.which('git'):
        pytest.skip('Git is required for synthetic index rehearsal')
    def run(*args: str) -> str:
        return subprocess.run(['git','-C',str(tmp_path),*args],check=True,capture_output=True,text=True).stdout.strip()
    run('init')
    run('config','user.email','synthetic@example.invalid')
    run('config','user.name','Synthetic fixture')
    run('config','core.autocrlf','false')
    (tmp_path/'forward_daily_contract.py').write_bytes(b'fixed')
    for name in checker.MODIFIED:
        (tmp_path/name).write_bytes(b'baseline')
    run('add','forward_daily_contract.py',*checker.MODIFIED)
    run('commit','-m','Synthetic baseline')
    base=run('rev-parse','HEAD')
    monkeypatch.setattr(checker,'BASE',base)
    actual_git=checker.git
    fake_tree(tmp_path,monkeypatch)
    monkeypatch.setattr(checker,'git',actual_git)
    run('add',*checker.FILES)
    assert checker.check(tmp_path,base)['failures']==[]
    run('commit','-m','Synthetic package')
    assert checker.check(tmp_path,base)['failures'][0]['rule']=='EXACT_REVIEWED_BASE_REQUIRED'
