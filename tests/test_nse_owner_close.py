"""Owner source is an explicit assertion, never a fabricated automated receipt."""
import base64
from copy import deepcopy
from datetime import date, datetime
import json
from pathlib import Path

import pytest

import forward_nifty_schedule as schedule
from forward_nifty_producer import ROOT, prepare_config, validate_config
import nse_owner_close as owner
from nifty_previous_close import validate as validate_automatic
from research_integrity import IntegrityError, digest
from test_staged_capture_repair import staged

DAY = date(2026, 10, 8)
STAMP = '2026-10-08T09:00:00+05:30'
RAW = b'Index Name,Index Date,Closing Index Value\nNifty 50,07-10-2026,20000.50\n'


def source(tmp_path, **overrides):
    path = tmp_path / 'private-source.csv'
    path.write_bytes(RAW)
    args = dict(observed_download_at='2026-10-08T08:58:00+05:30',
                read_at=STAMP, attested=True, code_root=ROOT)
    args.update(overrides)
    return owner.from_file(path, DAY, **args)


def test_original_bytes_and_distinct_authority(tmp_path):
    item = source(tmp_path)
    assert base64.b64decode(item['csv_base64']) == RAW and item['sha256'] == digest(RAW)
    assert item['publication_time'] is None and 'retrieved_at' not in item
    assert owner.validate(item, DAY, STAMP) == 20000.5
    with pytest.raises(IntegrityError):
        validate_automatic(item, DAY, STAMP)


@pytest.mark.parametrize('ack', [False, 'true', 'false', 1, None])
def test_literal_confirmation_before_file_read(tmp_path, ack, monkeypatch):
    monkeypatch.setattr(Path, 'open', lambda *a, **k: pytest.fail('File read'))
    with pytest.raises(IntegrityError, match='ATTESTATION'):
        owner.from_file(tmp_path/'missing', DAY, observed_download_at=STAMP,
                        read_at=STAMP, attested=ack, code_root=ROOT)


@pytest.mark.parametrize('stamp', ['2026-10-07T08:00:00+05:30',
    '2026-10-08T09:01:00+05:30', '2026-10-08T09:00:00'])
def test_timing_before_file_read(tmp_path, stamp, monkeypatch):
    monkeypatch.setattr(Path, 'open', lambda *a, **k: pytest.fail('File read'))
    with pytest.raises((IntegrityError, ValueError)):
        owner.from_file(tmp_path/'missing', DAY, observed_download_at=stamp,
                        read_at=STAMP, attested=True, code_root=ROOT)


@pytest.mark.parametrize('field,value', [('sha256', 'a'*64), ('close_decimal', '1'),
    ('source_url', 'https://wrong.invalid'), ('source_authenticity', 'AUTOMATIC'),
    ('publication_time', STAMP), ('file_read_at', '2026-10-08T09:15:00+05:30'),
    ('csv_base64', 'bad!')])
def test_tampered_provenance_blocks(tmp_path, field, value):
    item = source(tmp_path)
    item[field] = value
    with pytest.raises((IntegrityError, ValueError)):
        owner.validate(item, DAY, STAMP)


def test_exact_target_calendar_and_close(tmp_path):
    item = source(tmp_path)
    with pytest.raises(IntegrityError): owner.validate(item, date(2026, 10, 9), STAMP)
    with pytest.raises(IntegrityError): owner.validate(item, date(2026, 10, 10), STAMP)


def test_v3_bound_to_source_and_numeric_value(tmp_path):
    item = source(tmp_path)
    config = prepare_config(DAY.isoformat(), 20000.5, item['sha256'], STAMP)
    config.update(version='nifty-forward-v3-owner-file', previous_close_provenance=item)
    validate_config(config, ROOT)
    changed = deepcopy(config)
    changed['previous_close'] = 1
    with pytest.raises(IntegrityError, match='CONFIG_MISMATCH'): validate_config(changed, ROOT)
    changed = deepcopy(config)
    changed['version'] = 'nifty-forward-v2'
    with pytest.raises(IntegrityError): validate_config(changed, ROOT)


@pytest.fixture(params=['root', 'staged'])
def scheduler(request, monkeypatch):
    module = schedule if request.param == 'root' else staged('forward_nifty_schedule')
    monkeypatch.setattr(module, 'now', lambda: datetime.fromisoformat(STAMP))
    monkeypatch.setattr(module, 'measure_clock', lambda: {})
    monkeypatch.setattr(module, 'clock_error', lambda *a, **k: None)
    monkeypatch.setattr(module, 'read_secret', lambda *a: 'true')
    monkeypatch.setattr(module, 'fetch', lambda *a, **k: pytest.fail('NSE network fallback'))
    return module


def test_owner_prepare_preview_and_real(scheduler, tmp_path, capsys):
    path = tmp_path/'source.csv'
    path.write_bytes(RAW)
    state = tmp_path/'state'
    args = ['--root', str(state), '--mode', 'prepare', '--owner-close-file', str(path),
            '--owner-download-at', '2026-10-08T08:58:00+05:30', '--attest-nse-source']
    assert scheduler.main(args) == 0 and not state.exists()
    assert json.loads(capsys.readouterr().out)['network_calls'] == 0
    assert scheduler.main(args+['--confirm-run']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'CONFIG_PREPARED_OWNER_FILE' and result['source_network_calls'] == 0
    assert str(path) not in json.dumps(result) and '20000' not in json.dumps(result)
    config_path = state/DAY.isoformat()/'config.json'
    before = config_path.read_bytes()
    assert json.loads(before)['version'] == 'nifty-forward-v3-owner-file'
    assert scheduler.main(args+['--confirm-run']) == 2
    assert json.loads(capsys.readouterr().out)['code'] == 'SESSION_ALREADY_PREPARED'
    assert config_path.read_bytes() == before


def test_owner_mode_needs_ack_and_licence(scheduler, tmp_path, capsys, monkeypatch):
    args = ['--root', str(tmp_path/'state'), '--mode', 'prepare', '--confirm-run',
            '--owner-close-file', str(tmp_path/'missing'), '--owner-download-at', STAMP]
    assert scheduler.main(args) == 2
    assert json.loads(capsys.readouterr().out)['code'] == 'OWNER_CLOSE_ATTESTATION_REQUIRED'
    monkeypatch.setattr(scheduler, 'read_secret', lambda *a: 'false')
    assert scheduler.main(args+['--attest-nse-source']) == 2
    assert json.loads(capsys.readouterr().out)['code'] == 'LICENSE_ACK_REQUIRED'


def test_clock_and_deadline_block_manual_source(scheduler, tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, 'clock_error', lambda *a, **k: 'FAIL')
    with pytest.raises(IntegrityError, match='CLOCK'):
        scheduler.prepare(tmp_path, owner_file=tmp_path/'missing', owner_download_at=STAMP, source_attested=True)
    monkeypatch.setattr(scheduler, 'now', lambda: datetime.fromisoformat('2026-10-08T09:15:00+05:30'))
    with pytest.raises(IntegrityError, match='PREOPEN'):
        scheduler.prepare(tmp_path, owner_file=tmp_path/'missing', owner_download_at=STAMP, source_attested=True)


def test_manual_arguments_not_allowed_for_poll(scheduler, tmp_path, capsys):
    assert scheduler.main(['--root', str(tmp_path), '--mode', 'poll', '--confirm-run',
                           '--owner-close-file', str(tmp_path/'missing')]) == 2
    assert json.loads(capsys.readouterr().out)['code'] == 'OWNER_CLOSE_PREPARE_ONLY'


def test_manual_recipe_poll_and_audit_acceptance(scheduler, tmp_path, monkeypatch):
    path = tmp_path/'source.csv'
    path.write_bytes(RAW)
    state = tmp_path/'state'
    scheduler.prepare(state, owner_file=path, owner_download_at=STAMP, source_attested=True)
    from contextlib import nullcontext
    monkeypatch.setattr(scheduler, 'now', lambda: datetime.fromisoformat('2026-10-08T09:20:30+05:30'))
    monkeypatch.setattr(scheduler, 'credential_environment', lambda: nullcontext())
    monkeypatch.setattr(scheduler, 'capture', lambda args: 0)
    assert scheduler.poll(state) == 0
    monkeypatch.setattr(scheduler, 'now', lambda: datetime.fromisoformat('2026-10-08T15:40:00+05:30'))
    class EmptyJournal:
        def __init__(self, *args, **kwargs): pass
        def read(self, *args): return []
    monkeypatch.setattr(scheduler, 'ObservationJournal', EmptyJournal)
    assert scheduler.audit(state)['missing_decisions'] == 75


def test_root_and_staged_scheduler_behaviour_cannot_drift():
    import ast
    root = Path(schedule.__file__).resolve().parent
    parsed = ast.parse((root/'forward_nifty_schedule.py').read_text())
    replacement = root/'staged_capture_repair'/'forward_nifty_schedule.py'
    if replacement.exists():
        assert ast.dump(parsed) == ast.dump(ast.parse(replacement.read_text()))
        assert ast.dump(ast.parse((root/'nifty_previous_close.py').read_text())) == ast.dump(
            ast.parse((root/'staged_capture_repair'/'nifty_previous_close.py').read_text()))
    else:
        assert {'prepare', 'poll', 'audit', 'main'}.issubset(
            {node.name for node in parsed.body if isinstance(node, ast.FunctionDef)})
        assert '--attest-nse-source' in {node.value for node in ast.walk(parsed)
                                      if isinstance(node, ast.Constant) and isinstance(node.value, str)}


def test_boundary_crossing_before_write_blocks(scheduler, tmp_path, monkeypatch):
    path = tmp_path/'source.csv'
    path.write_bytes(RAW)
    stamps = iter([STAMP]*4+['2026-10-08T09:15:00+05:30'])
    monkeypatch.setattr(scheduler, 'now', lambda: datetime.fromisoformat(next(stamps)))
    state = tmp_path/'state'
    with pytest.raises(IntegrityError, match='PREOPEN'):
        scheduler.prepare(state, owner_file=path, owner_download_at=STAMP, source_attested=True)
    assert not state.exists()


def test_utc_attested_time_is_converted_to_ist(tmp_path):
    item = source(tmp_path, observed_download_at='2026-10-08T03:28:00+00:00')
    assert owner.validate(item, DAY, STAMP) == 20000.5
