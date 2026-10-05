"""Synthetic prospective receipt, durability and private transport checks."""
from copy import deepcopy
from datetime import datetime, timedelta
import gzip
import json

import pytest

import forward_nifty_job as job
from forward_nifty_archive import publish, verify, restore, recheck, main as archive_main
from forward_nifty_producer import Producer, prepare_config, validate_config, ROOT
from research_input_archive import InputArchive
from research_integrity import IntegrityError, canonical, digest


@pytest.fixture
def config():
    return prepare_config('2022-01-03', 24900, 'a' * 64, '2022-01-02T12:00:00+05:30')


def candles(config, count):
    opening = datetime.fromisoformat(config['session_open'])
    return [[(opening + timedelta(minutes=5*i)).isoformat(), 25000+i*2, 25003+i*2,
             24998+i*2, 25001+i*2, 0, 0] for i in range(count)]


def poll(producer, data, minutes):
    receipt = datetime.fromisoformat(producer.config['session_open']) + timedelta(minutes=minutes, seconds=1)
    return producer.record_poll(data, received_at=receipt.isoformat(), computed_clock=lambda: receipt + timedelta(seconds=1))


def make(tmp_path, config):
    return Producer(config, tmp_path / 'journal.sqlite', InputArchive(tmp_path / 'inputs'))


def test_first_poll_never_backfills_decisions_and_restart_is_idempotent(tmp_path, config):
    producer = make(tmp_path, config)
    first = poll(producer, candles(config, 20), 100)
    assert first['recorded_decisions'] == 1 and first['missing_decisions'] == 74
    row = first['observations'][0]
    assert row['available'] is False and row['origin'] == 'OBSERVED'
    assert row['approval_authority'] is False and row['fill_evidence'] is False
    assert row['available_at'] != row['decision_at']
    prefix = json.loads(producer.archive.get(row['input_hash']))
    assert len(prefix['bars']) == 20
    assert poll(make(tmp_path, config), candles(config, 20), 101)['observations'] == first['observations']
    assert verify(gzip.compress(canonical(first))) == first


def test_forming_values_not_read_and_empty_poll_visible(tmp_path, config):
    producer = make(tmp_path, config)
    data = candles(config, 1)
    data[0][1:] = ['DO_NOT_INTERPRET'] * 6
    result = poll(producer, data, 2)
    assert result['status'] == 'NO_COMPLETED_BAR' and result['missing_decisions'] == 75
    assert result['bars'] == []


def test_signal_calculation_and_consumed_prefix_are_reproducible(tmp_path, config):
    producer = make(tmp_path, config)
    result = poll(producer, candles(config, 75), 375)
    assert result['recorded_decisions'] == 1
    assert result['observations'][0]['available'] is True
    assert result['observations'][0]['direction'] == 1
    assert verify(gzip.compress(canonical(result))) == result


def test_missing_bar_is_unavailable_and_late_context_does_not_rewrite_old_prefix(tmp_path, config):
    producer = make(tmp_path, config)
    data = candles(config, 61)
    first = poll(producer, data[1:], 305)
    assert not first['observations'][0]['available']
    second = poll(producer, candles(config, 62), 310)
    assert second['recorded_decisions'] == 2
    assert second['observations'][0] == first['observations'][0]
    verify(gzip.compress(canonical(second)))


@pytest.mark.parametrize('mutation', ['nan', 'negative', 'crossed', 'duplicate', 'naive', 'offgrid', 'outside'])
def test_bad_closed_candles_fail_without_input_commit(tmp_path, config, mutation):
    producer = make(tmp_path, config)
    data = candles(config, 1)
    if mutation == 'nan':
        data[0][1] = float('nan')
    elif mutation == 'negative':
        data[0][5] = -1
    elif mutation == 'crossed':
        data[0][2] = 1
    elif mutation == 'duplicate':
        data *= 2
    elif mutation == 'naive':
        data[0][0] = '2022-01-03T09:15:00'
    elif mutation == 'offgrid':
        data[0][0] = '2022-01-03T09:16:00+05:30'
    else:
        data[0][0] = '2022-01-03T09:10:00+05:30'
    with pytest.raises((IntegrityError, ValueError)):
        poll(producer, data, 5)
    assert producer.context() == []
    assert not producer.journal.path.with_suffix('.producer-lock').exists()


def test_revision_and_backwards_receipt_fail_without_history_change(tmp_path, config):
    producer = make(tmp_path, config)
    first = poll(producer, candles(config, 1), 5)
    data = candles(config, 1)
    data[0][4] += 1
    with pytest.raises(IntegrityError, match='REVISION'):
        poll(producer, data, 6)
    with pytest.raises(IntegrityError, match='BACKWARDS'):
        poll(producer, candles(config, 1), 4)
    assert producer.bundle('CHECK', producer.context())['observations'] == first['observations']


def test_overlapping_or_crashed_writer_is_rejected(tmp_path, config):
    producer = make(tmp_path, config)
    lock = producer.journal.path.with_suffix('.producer-lock')
    lock.write_text('')
    with pytest.raises(IntegrityError, match='ALREADY_RUNNING'):
        poll(producer, candles(config, 1), 5)
    assert lock.exists() and producer.context() == []


def test_archive_failure_keeps_inputs_not_fake_decision(tmp_path, config, monkeypatch):
    producer = make(tmp_path, config)
    monkeypatch.setattr(producer.archive, 'put', lambda raw: (_ for _ in ()).throw(OSError('disk')))
    with pytest.raises(OSError):
        poll(producer, candles(config, 1), 5)
    assert len(producer.context()) == 1
    assert producer.journal.read(producer.identity, config['session_open']) == []


@pytest.mark.parametrize('field,value', [('previous_close', None), ('previous_close', True),
    ('previous_close', 0), ('previous_close_source_sha256', 'bad'), ('instrument_key', 'OTHER'),
    ('frozen_at', '2022-01-03T09:16:00+05:30'), ('environment', {})])
def test_frozen_config_rejects_missing_or_changed_evidence(config, field, value):
    config[field] = value
    with pytest.raises((IntegrityError, ValueError)):
        validate_config(config, ROOT)


@pytest.mark.parametrize('date', ['2026-10-02', '2026-10-04', '2024-03-02', '2027-01-04'])
def test_holiday_weekend_special_and_unreviewed_calendar_fail(date):
    with pytest.raises((IntegrityError, ValueError)):
        prepare_config(date, 25000, 'a' * 64, '2022-01-01T00:00:00+05:30')


class MemoryDrive:
    def __init__(self):
        self.files = {}

    def put(self, name, data, batch_id, kind, mime):
        identity = batch_id + kind
        self.files.setdefault(identity, data)
        return identity

    def download(self, identity):
        return self.files[identity]


def test_private_drive_retry_and_download_verification(tmp_path, config):
    bundle = poll(make(tmp_path, config), candles(config, 1), 5)
    drive = MemoryDrive()
    first = publish(drive, bundle)
    assert publish(drive, bundle) == first and len(drive.files) == 2
    assert first['sha256'] == digest(drive.files[first['data_file_id']])
    drive.files[first['data_file_id']] = b'corrupt'
    with pytest.raises(IntegrityError, match='REMOTE_VERIFICATION'):
        publish(drive, bundle)


def test_restore_and_recheck_keep_actual_receipts_and_missing_decisions(tmp_path, config):
    producer = make(tmp_path, config)
    original = poll(producer, candles(config, 61)[1:], 305)
    bundle = poll(producer, candles(config, 62), 310)
    raw = gzip.compress(canonical(bundle))
    report = recheck(raw)
    assert report['matched'] == 2 and report['missing_decisions'] == 73 and not report['complete_session']
    destination = tmp_path / 'restored'
    assert restore(raw, destination)['recorded_decisions'] == 2
    restored = Producer(config, destination / 'observations.sqlite', InputArchive(destination / 'inputs'))
    assert restored.bundle('CHECK', restored.context())['observations'] == bundle['observations']
    assert restored.bundle('CHECK', restored.context())['observations'][0] == original['observations'][0]
    with pytest.raises(IntegrityError, match='NEW_PRIVATE_RESTORE'):
        restore(raw, destination)
    path = tmp_path / 'backup.json.gz'
    path.write_bytes(raw)
    assert archive_main(['--archive', str(path), '--sha256', digest(raw)]) == 0
    assert archive_main(['--archive', str(path), '--sha256', 'a' * 64]) == 2


def test_recheck_detects_wrong_computation_not_just_hashes(tmp_path, config):
    bundle = poll(make(tmp_path, config), candles(config, 1), 5)
    bundle['observations'][0]['detail_hash'] = 'a' * 64
    raw = gzip.compress(canonical(bundle))
    verify(raw)  # Transport integrity alone is not arithmetic verification.
    with pytest.raises(IntegrityError, match='REPLAY_MISMATCH'):
        recheck(raw)


@pytest.mark.parametrize('mutation', ['authority', 'prefix', 'count', 'origin'])
def test_backup_rejects_conflicting_payloads(tmp_path, config, mutation):
    bundle = deepcopy(poll(make(tmp_path, config), candles(config, 1), 5))
    if mutation == 'authority':
        bundle['approval_authority'] = True
    elif mutation == 'prefix':
        bundle['bars'][0]['values'][0] += 1
    elif mutation == 'count':
        bundle['recorded_decisions'] += 1
    else:
        bundle['observations'][0]['origin'] = 'REPLAY'
    with pytest.raises(IntegrityError):
        verify(gzip.compress(canonical(bundle)))


def test_preview_offline_and_missing_auth_sanitized(tmp_path, config, monkeypatch, capsys):
    path = tmp_path / 'config.json'
    path.write_bytes(canonical(config))
    arguments = ['--config', str(path), '--state', str(tmp_path / 'state')]
    monkeypatch.setenv('FORWARD_CAPTURE_LICENSE_ACK', 'true')
    monkeypatch.delenv('UPSTOX_ANALYTICS_TOKEN', raising=False)
    assert job.main(arguments) == 0
    assert 'PREVIEW' in capsys.readouterr().out
    assert not (tmp_path / 'state').exists()
    assert job.main(arguments + ['--confirm-run']) == 2
    assert 'AUTH_REQUIRED' in capsys.readouterr().out
    assert len(list((tmp_path / 'state').glob('failure-*.json'))) == 1


def test_false_licence_cannot_enable_capture(tmp_path, config, monkeypatch, capsys):
    path = tmp_path / 'config.json'
    path.write_bytes(canonical(config))
    monkeypatch.setenv('FORWARD_CAPTURE_LICENSE_ACK', 'false')
    monkeypatch.setenv('UPSTOX_ANALYTICS_TOKEN', 'SECRET_VALUE')
    assert job.main(['--config', str(path), '--state', str(tmp_path / 'state'), '--confirm-run']) == 2
    output = capsys.readouterr()
    assert 'LICENSE_ACK_REQUIRED' in output.out and 'SECRET_VALUE' not in output.out + output.err


@pytest.mark.parametrize('status,body,code', [(401, {}, 'AUTH_REQUIRED'), (500, {}, 'MARKET_DATA_UNAVAILABLE'),
    (200, None, 'MARKET_RESPONSE_INVALID'), (200, {'status': 'success', 'data': {'candles': None}}, 'MARKET_RESPONSE_INVALID')])
def test_rest_failures_and_tls_policy(status, body, code):
    class Response:
        status_code = status
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_content(self, size): yield json.dumps(body).encode()
    class Session:
        def get(self, url, **kwargs):
            assert url == job.URL and kwargs['verify'] is True and kwargs['allow_redirects'] is False
            return Response()
    with pytest.raises(IntegrityError, match=code):
        job.read_current(Session(), 'SYNTHETIC_TOKEN')


def test_capture_and_backup_only_runtime_wiring(tmp_path, config, monkeypatch, capsys):
    import requests
    class Clock:
        @staticmethod
        def now(zone):
            return datetime.fromisoformat('2022-01-03T10:00:01+05:30')
    class Session:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class Drive(MemoryDrive):
        def check_folder(self): pass
        def close(self): pass
    drive = Drive()
    monkeypatch.setattr(job, 'datetime', Clock)
    monkeypatch.setattr(job, 'measure_clock', lambda: {'status': 'MEASURED'})
    monkeypatch.setattr(job, 'clock_error', lambda *args, **kwargs: None)
    monkeypatch.setattr(job, 'credentials', lambda raw: object())
    monkeypatch.setattr(job, 'DriveArchive', lambda *args: drive)
    monkeypatch.setattr(requests, 'Session', Session)
    reads = []
    monkeypatch.setattr(job, 'read_current', lambda *args: reads.append(1) or candles(config, 9))
    monkeypatch.setenv('FORWARD_CAPTURE_LICENSE_ACK', 'true')
    monkeypatch.setenv('UPSTOX_ANALYTICS_TOKEN', 'SECRET_ACCESS')
    monkeypatch.setenv('FORWARD_TOKEN_EXPIRES_AT', '2022-01-03T23:00:00+05:30')
    path = tmp_path / 'config.json'
    path.write_bytes(canonical(config))
    args = ['--config', str(path), '--state', str(tmp_path / 'state')]
    assert job.main(args + ['--confirm-run']) == 0
    assert len(reads) == 1
    monkeypatch.delenv('UPSTOX_ANALYTICS_TOKEN')
    assert job.main(args + ['--backup-only']) == 0 and len(reads) == 1
    output = capsys.readouterr()
    assert 'SECRET_ACCESS' not in output.out + output.err
    assert len(list((tmp_path / 'state').glob('receipt-*.json'))) == 2
    def down():
        raise RuntimeError('SECRET_DRIVE_FAILURE')
    monkeypatch.setattr(drive, 'check_folder', down)
    assert job.main(args + ['--backup-only']) == 2
    assert 'SECRET_DRIVE_FAILURE' not in capsys.readouterr().out
    assert len(Producer(config, tmp_path / 'state' / 'observations.sqlite',
                        InputArchive(tmp_path / 'state' / 'inputs')).context()) == 9


def test_clock_failure_prevents_broker_call(tmp_path, config, monkeypatch, capsys):
    class Clock:
        @staticmethod
        def now(zone): return datetime.fromisoformat('2022-01-03T10:00:01+05:30')
    monkeypatch.setattr(job, 'datetime', Clock)
    monkeypatch.setattr(job, 'measure_clock', lambda: {})
    monkeypatch.setattr(job, 'clock_error', lambda *args, **kwargs: 'MISSING')
    monkeypatch.setattr(job, 'read_current', lambda *args: pytest.fail('Broker called'))
    monkeypatch.setenv('FORWARD_CAPTURE_LICENSE_ACK', 'true')
    monkeypatch.setenv('UPSTOX_ANALYTICS_TOKEN', 'PRIVATE')
    monkeypatch.setenv('FORWARD_TOKEN_EXPIRES_AT', '2022-01-03T23:00:00+05:30')
    path = tmp_path / 'config.json'
    path.write_bytes(canonical(config))
    assert job.main(['--config', str(path), '--state', str(tmp_path / 'state'), '--confirm-run']) == 2
    assert 'CLOCK_UNVERIFIED' in capsys.readouterr().out


def test_offline_prepare_writes_new_config_and_refuses_overwrite(tmp_path, monkeypatch, capsys):
    class Clock:
        @staticmethod
        def now(zone): return datetime.fromisoformat('2022-01-02T10:00:01+05:30')
    monkeypatch.setattr(job, 'datetime', Clock)
    path = tmp_path / 'config.json'
    args = ['--config', str(path), '--state', str(tmp_path / 'state'), '--prepare',
            '--trading-date', '2022-01-03', '--previous-close', '24900',
            '--previous-close-source-sha256', 'a' * 64]
    assert job.main(args) == 0 and not (tmp_path / 'state').exists()
    before = path.read_bytes()
    assert job.main(args) == 2 and path.read_bytes() == before
    assert 'CONFIG_PREPARED' in capsys.readouterr().out


@pytest.mark.parametrize('expiry', ['bad', '2026-10-05T16:00:00', '2020-01-01T00:00:00+00:00'])
def test_bad_or_expired_token_is_auth_required(tmp_path, config, monkeypatch, capsys, expiry):
    path = tmp_path / 'config.json'
    path.write_bytes(canonical(config))
    monkeypatch.setenv('FORWARD_CAPTURE_LICENSE_ACK', 'true')
    monkeypatch.setenv('UPSTOX_ANALYTICS_TOKEN', 'SECRET')
    monkeypatch.setenv('FORWARD_TOKEN_EXPIRES_AT', expiry)
    monkeypatch.setattr(job, 'read_current', lambda *args: pytest.fail('Broker called'))
    assert job.main(['--config', str(path), '--state', str(tmp_path / 'state'), '--confirm-run']) == 2
    assert 'AUTH_REQUIRED' in capsys.readouterr().out


def test_local_inputs_survive_invalid_computation_timestamp(tmp_path, config):
    producer = make(tmp_path, config)
    with pytest.raises(IntegrityError, match='INVALID_COMPUTATION'):
        producer.record_poll(candles(config, 1), received_at='2022-01-03T09:20:01+05:30',
                             computed_clock=lambda: datetime.fromisoformat('2022-01-03T09:19:00+05:30'))
    assert len(producer.context()) == 1 and producer.journal.read(producer.identity, config['session_open']) == []


def test_response_limit_and_manifest_ack_fail_closed(tmp_path, config):
    class LargeResponse:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_content(self, size): yield b'x' * (2*1024*1024+1)
    class Session:
        def get(self, *args, **kwargs): return LargeResponse()
    with pytest.raises(IntegrityError, match='RESPONSE_TOO_LARGE'):
        job.read_current(Session(), 'SECRET')
    class BadManifest(MemoryDrive):
        def download(self, identity):
            return b'corrupt' if identity.endswith('manifest') else super().download(identity)
    bundle = poll(make(tmp_path, config), candles(config, 1), 5)
    with pytest.raises(IntegrityError, match='MANIFEST_VERIFICATION'):
        publish(BadManifest(), bundle)
