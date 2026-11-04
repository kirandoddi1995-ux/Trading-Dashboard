"""Offline verification of a downloaded archive copy: synthetic files only."""
import json

import pytest

import verify_local_archive_copy as verify
from drive_archive import exact_json, upload_verified
from test_archive_restore_check import ListedDrive
from test_drive_archive import nav


def _write_copy(tmp_path, drive):
    for file_id, (raw, kind) in drive.data.items():
        suffix = '.manifest.json' if kind == 'manifest' else '.parquet'
        record = drive.properties[file_id]
        table = 'mf_nav'
        (tmp_path / 'sub').mkdir(exist_ok=True)
        (tmp_path / 'sub' / f"{table}-{record['batch']}{suffix}").write_bytes(raw)


def _drive_with(codes):
    drive = ListedDrive()
    for code in codes:
        upload_verified(drive, 'mf_nav', [exact_json(nav(code))])
    return drive


def test_intact_copy_verifies_and_reports_counts(tmp_path, capsys):
    _write_copy(tmp_path, _drive_with('ABC'))
    assert verify.main([str(tmp_path), '--expect', '3']) == 0
    out = json.loads(capsys.readouterr().out)
    assert out['status'] == 'COPY_VERIFIED' and out['verified'] == 3


@pytest.mark.parametrize('damage', ['flip_byte', 'missing_data', 'short_count', 'orphan'])
def test_any_damage_or_shortfall_is_not_verified(tmp_path, capsys, damage):
    _write_copy(tmp_path, _drive_with('AB'))
    files = sorted((tmp_path / 'sub').glob('*.parquet'))
    expect = 2
    if damage == 'flip_byte':
        raw = files[0].read_bytes()
        files[0].write_bytes(raw[:-9] + bytes([raw[-9] ^ 1]) + raw[-8:])
    elif damage == 'missing_data':
        files[0].unlink()
    elif damage == 'short_count':
        expect = 3
    else:
        (tmp_path / 'sub' / 'mf_nav-extra.parquet').write_bytes(b'x')
    assert verify.main([str(tmp_path), '--expect', str(expect)]) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'COPY_NOT_VERIFIED'


def test_missing_folder_fails_closed(tmp_path, capsys):
    assert verify.main([str(tmp_path / 'nope'), '--expect', '1']) == 1
