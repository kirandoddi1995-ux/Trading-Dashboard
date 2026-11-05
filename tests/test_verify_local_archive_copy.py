"""Offline verification of a downloaded archive copy against a frozen, anchored inventory.

Synthetic files only. Round-3 review of 8401eaa found that a count (--expect) could certify an empty
folder or the wrong set of batches, and that malformed manifests were accepted.
"""
import hashlib
import json

import pytest

import verify_local_archive_copy as verify
from drive_archive import exact_json, upload_verified
from test_archive_restore_check import ListedDrive
from test_drive_archive import nav


def _drive_with(codes):
    drive, manifests = ListedDrive(), {}
    for code in codes:
        manifest, _ = upload_verified(drive, 'mf_nav', [exact_json(nav(code))])
        manifests[code] = manifest
    return drive, manifests


def _write_copy(folder, drive, only=None):
    (folder / 'sub').mkdir(parents=True, exist_ok=True)
    for file_id, (raw, kind) in drive.data.items():
        batch = drive.properties[file_id]['batch']
        if only is not None and batch not in only:
            continue
        suffix = '.manifest.json' if kind == 'manifest' else '.parquet'
        (folder / 'sub' / f'mf_nav-{batch}{suffix}').write_bytes(raw)


def _inventory(tmp_path, manifests, name='inventory.json'):
    entries = [{'batch_id': m['batch_id'], 'source_table': m['source_table'], 'row_count': m['rows'],
                'file_sha256': m['sha256'], 'drive_file_id': m['drive_file_id'],
                'drive_manifest_id': m['drive_manifest_id']} for m in manifests]
    raw = json.dumps({'format': verify.INVENTORY_FORMAT, 'batches': entries}).encode()
    path = tmp_path / name
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def _run(capsys, copy, inventory, anchor):
    code = verify.main([str(copy), '--inventory', str(inventory), '--inventory-sha256', anchor])
    return code, json.loads(capsys.readouterr().out)


def test_copy_matching_the_anchored_inventory_is_verified(tmp_path, capsys):
    drive, manifests = _drive_with('ABC')
    _write_copy(tmp_path / 'copy', drive)
    inventory, anchor = _inventory(tmp_path, manifests.values())
    code, out = _run(capsys, tmp_path / 'copy', inventory, anchor)
    assert code == 0 and out['status'] == 'COPY_MATCHES_INVENTORY' and out['matched'] == 3


def test_inventory_that_does_not_match_its_anchor_is_refused(tmp_path, capsys):
    drive, manifests = _drive_with('AB')
    _write_copy(tmp_path / 'copy', drive)
    inventory, _ = _inventory(tmp_path, manifests.values())
    code, out = _run(capsys, tmp_path / 'copy', inventory, '0' * 64)
    assert code == 1 and out['error'] == 'INVENTORY_NOT_ANCHORED'


def test_same_count_but_different_batches_is_not_verified(tmp_path, capsys):
    drive, manifests = _drive_with('ABC')
    _write_copy(tmp_path / 'copy', drive,
                only={manifests['A']['batch_id'], manifests['B']['batch_id']})  # copy holds {A,B}
    inventory, anchor = _inventory(tmp_path, [manifests['A'], manifests['C']])  # expected {A,C}
    code, out = _run(capsys, tmp_path / 'copy', inventory, anchor)
    assert code == 1 and out['status'] == 'COPY_DOES_NOT_MATCH_INVENTORY'
    assert out['missing'] == 1 and out['not_in_inventory'] == 1


@pytest.mark.parametrize('damage', ['flip_byte', 'missing_data', 'orphan', 'duplicate'])
def test_any_damage_is_not_verified(tmp_path, capsys, damage):
    drive, manifests = _drive_with('AB')
    _write_copy(tmp_path / 'copy', drive)
    files = sorted((tmp_path / 'copy' / 'sub').glob('*.parquet'))
    if damage == 'flip_byte':
        raw = files[0].read_bytes()
        files[0].write_bytes(raw[:-9] + bytes([raw[-9] ^ 1]) + raw[-8:])
    elif damage == 'missing_data':
        files[0].unlink()
    elif damage == 'orphan':
        (tmp_path / 'copy' / 'sub' / 'mf_nav-extra.parquet').write_bytes(b'x')
    else:
        (tmp_path / 'copy' / 'other').mkdir()
        (tmp_path / 'copy' / 'other' / files[0].name).write_bytes(files[0].read_bytes())
    inventory, anchor = _inventory(tmp_path, manifests.values())
    code, out = _run(capsys, tmp_path / 'copy', inventory, anchor)
    assert code == 1 and out['status'] == 'COPY_DOES_NOT_MATCH_INVENTORY'


@pytest.mark.parametrize('change', ['bool_rows', 'float_rows', 'format', 'duplicate_key', 'extra_field'])
def test_a_manifest_that_is_not_the_exact_expected_bytes_is_rejected(tmp_path, capsys, change):
    drive, manifests = _drive_with('A')
    _write_copy(tmp_path / 'copy', drive)
    path = next((tmp_path / 'copy' / 'sub').glob('*.manifest.json'))
    record = json.loads(path.read_bytes())
    if change == 'bool_rows':
        record['rows'] = True
    elif change == 'float_rows':
        record['rows'] = 1.0
    elif change == 'format':
        record['format'] = 'drive-archive-v0'
    elif change == 'extra_field':
        record['note'] = 'x'
    raw = exact_json(record)
    if change == 'duplicate_key':
        raw = raw[:-1] + ',"rows":1}'
    path.write_bytes(raw.encode())
    inventory, anchor = _inventory(tmp_path, manifests.values())
    code, out = _run(capsys, tmp_path / 'copy', inventory, anchor)
    assert code == 1 and any('MANIFEST_NOT_EXPECTED_BYTES' in f for f in out['first_failures'])


@pytest.mark.parametrize('problem', ['empty', 'duplicate_key', 'bool_rows', 'zero_rows', 'duplicate_batch',
                                     'missing_field', 'bad_hash', 'format'])
def test_malformed_inventory_is_refused(tmp_path, capsys, problem):
    drive, manifests = _drive_with('A')
    _write_copy(tmp_path / 'copy', drive)
    m = manifests['A']
    entry = {'batch_id': m['batch_id'], 'source_table': 'mf_nav', 'row_count': m['rows'],
             'file_sha256': m['sha256'], 'drive_file_id': m['drive_file_id'],
             'drive_manifest_id': m['drive_manifest_id']}
    document = {'format': verify.INVENTORY_FORMAT, 'batches': [entry]}
    if problem == 'empty':
        document['batches'] = []
    elif problem == 'bool_rows':
        entry['row_count'] = True
    elif problem == 'zero_rows':
        entry['row_count'] = 0
    elif problem == 'duplicate_batch':
        document['batches'] = [entry, dict(entry)]
    elif problem == 'missing_field':
        del entry['drive_manifest_id']
    elif problem == 'bad_hash':
        entry['file_sha256'] = 'XYZ'
    elif problem == 'format':
        document['format'] = 'something-else'
    raw = json.dumps(document)
    if problem == 'duplicate_key':
        raw = raw[:-1] + ', "format": "' + verify.INVENTORY_FORMAT + '"}'
    path = tmp_path / 'inventory.json'
    path.write_text(raw)
    code, out = _run(capsys, tmp_path / 'copy', path, hashlib.sha256(raw.encode()).hexdigest())
    assert code == 1 and out['error'].startswith('INVENTORY_')


def test_self_check_never_claims_custody_and_an_empty_folder_fails(tmp_path, capsys):
    drive, _ = _drive_with('AB')
    _write_copy(tmp_path / 'copy', drive)
    assert verify.main([str(tmp_path / 'copy'), '--self-check-only']) == 0
    out = json.loads(capsys.readouterr().out)
    assert out['status'] == 'SELF_CONSISTENT_ONLY' and out['deletion_authority'] is False
    (tmp_path / 'empty').mkdir()
    assert verify.main([str(tmp_path / 'empty'), '--self-check-only']) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'NOT_SELF_CONSISTENT'


def test_copy_inside_a_cloud_sync_folder_is_not_independent(tmp_path, capsys):
    drive, manifests = _drive_with('A')
    copy = tmp_path / 'My Drive' / 'copy'
    _write_copy(copy, drive)
    inventory, anchor = _inventory(tmp_path, manifests.values())
    code, out = _run(capsys, copy, inventory, anchor)
    assert code == 1 and out['error'] == 'DESTINATION_LOOKS_LIKE_A_SYNC_FOLDER'


def test_missing_folder_fails_closed(tmp_path, capsys):
    assert verify.main([str(tmp_path / 'nope'), '--self-check-only']) == 1


# ---- Fingerprint mode: database count + set hash, no inventory file to move ----

def _fingerprint(manifests):
    entries = [{'batch_id': m['batch_id'], 'source_table': m['source_table'], 'row_count': m['rows'],
                'file_sha256': m['sha256'], 'drive_file_id': m['drive_file_id']} for m in manifests]
    return verify.inventory_set_sha256(entries)


def _run_fp(capsys, copy, count, fingerprint):
    code = verify.main([str(copy), '--expect-batches', str(count), '--expect-set-sha256', fingerprint])
    return code, json.loads(capsys.readouterr().out)


def test_fingerprint_mode_matches_the_exact_batch_set(tmp_path, capsys):
    drive, manifests = _drive_with('ABC')
    _write_copy(tmp_path / 'copy', drive)
    code, out = _run_fp(capsys, tmp_path / 'copy', 3, _fingerprint(manifests.values()).upper())
    assert code == 0 and out['status'] == 'COPY_MATCHES_INVENTORY' and out['per_table'] == {'mf_nav': 3}


def test_fingerprint_mode_rejects_same_count_different_set_and_wrong_or_missing_count(tmp_path, capsys):
    drive, manifests = _drive_with('ABC')
    _write_copy(tmp_path / 'copy', drive,
                only={manifests['A']['batch_id'], manifests['B']['batch_id']})
    expected = _fingerprint([manifests['A'], manifests['C']])
    code, out = _run_fp(capsys, tmp_path / 'copy', 2, expected)
    assert code == 1 and out['fingerprint_matches'] is False
    right = _fingerprint([manifests['A'], manifests['B']])
    assert _run_fp(capsys, tmp_path / 'copy', 3, right)[0] == 1
    for count in ('0', '-1'):
        assert verify.main([str(tmp_path / 'copy'), '--expect-batches', count,
                            '--expect-set-sha256', right]) == 1
        assert json.loads(capsys.readouterr().out)['error'] == 'FINGERPRINT_AND_POSITIVE_COUNT_REQUIRED'
    assert verify.main([str(tmp_path / 'copy'), '--expect-set-sha256', right]) == 1
    capsys.readouterr()
    assert _run_fp(capsys, tmp_path / 'copy', 2, right)[0] == 0


@pytest.mark.skipif(not __import__('os').environ.get('EQUITY_TEST_PGLITE_MODULE'),
                    reason='Local SQL harness not configured')
def test_database_fingerprint_sql_equals_the_verifier_fingerprint(tmp_path):
    """The SQL run on Supabase and the verifier's rebuild must agree byte for byte."""
    import test_archive_maintenance_sql as sql_harness
    db = sql_harness.Pg()
    try:
        db.send({'script': """CREATE SCHEMA quant_app; CREATE TABLE quant_app.archive_manifests (
            batch_id text PRIMARY KEY, source_table text, row_count int, file_sha256 text,
            drive_file_id text, drive_manifest_id text)"""})
        _, manifests = _drive_with('ABCD')
        for m in manifests.values():
            db.execute('INSERT INTO quant_app.archive_manifests VALUES (%s,%s,%s,%s,%s,%s)',
                       (m['batch_id'], m['source_table'], m['rows'], m['sha256'], m['drive_file_id'],
                        m['drive_manifest_id']))
        count, fingerprint = db.execute(verify.INVENTORY_SET_SQL).fetchone()
    finally:
        db.send({'close': True})
        db.process.communicate(timeout=15)
    assert count == 4 and fingerprint == _fingerprint(manifests.values())


# ---- CodeAnt review of PR #72 ----

def _link_or_skip(make):
    """Real links are mandatory where the OS allows them; skip only when creation itself is refused
    (Windows without the symlink privilege raises WinError 1314)."""
    try:
        make()
    except OSError as error:
        if getattr(error, 'winerror', None) == 1314 or error.errno in (1, 13):
            pytest.skip(f'link creation refused by the OS: {error}')
        raise


@pytest.mark.parametrize('link', ['file', 'directory'])
def test_links_to_files_outside_the_copy_do_not_count(tmp_path, capsys, link):
    drive, manifests = _drive_with('AB')
    outside = tmp_path / 'outside'
    _write_copy(outside, drive)
    copy = tmp_path / 'copy'
    copy.mkdir()
    if link == 'file':
        _link_or_skip(lambda: [(copy / item.name).symlink_to(item) for item in (outside / 'sub').iterdir()])
    else:
        _link_or_skip(lambda: (copy / 'sub').symlink_to(outside / 'sub', target_is_directory=True))
    code, out = _run_fp(capsys, copy, 2, _fingerprint(manifests.values()))
    assert code == 1 and out['status'] == 'COPY_DOES_NOT_MATCH_INVENTORY'
    # The refusal must be because of the link, not merely a mismatch (an implementation that
    # silently ignored links would also mismatch).
    assert any(item.endswith(':LINK_NOT_ALLOWED') for item in out['first_failures'])


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows directory junctions only')
def test_windows_junction_to_files_outside_the_copy_does_not_count(tmp_path, capsys):
    import _winapi  # junctions need no special privilege
    drive, manifests = _drive_with('AB')
    outside = tmp_path / 'outside'
    _write_copy(outside, drive)
    copy = tmp_path / 'copy'
    copy.mkdir()
    _winapi.CreateJunction(str(outside / 'sub'), str(copy / 'sub'))
    code, out = _run_fp(capsys, copy, 2, _fingerprint(manifests.values()))
    assert code == 1 and any(item.endswith(':LINK_NOT_ALLOWED') for item in out['first_failures'])


def test_oversized_files_are_refused_without_reading_them(tmp_path, capsys, monkeypatch):
    drive, manifests = _drive_with('A')
    _write_copy(tmp_path / 'copy', drive)
    monkeypatch.setattr(verify, 'MAX_BYTES', 10)
    code, out = _run_fp(capsys, tmp_path / 'copy', 1, _fingerprint(manifests.values()))
    assert code == 1 and any('FILE_TOO_LARGE' in f for f in out['first_failures'])
