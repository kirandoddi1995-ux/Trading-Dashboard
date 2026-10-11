"""Offline, synthetic failure boundaries; no credentials, Drive or broker requests."""
from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any

from google.auth.exceptions import RefreshError, TransportError
import pytest
from requests.exceptions import SSLError, Timeout

import forward_nifty_job as job
from drive_archive import ArchiveError
from forward_nifty_producer import Producer, prepare_config
from research_input_archive import InputArchive
from research_integrity import IntegrityError, canonical


def google_error(kind: type[Exception], message: str) -> Exception:
    """The dependency's constructors are untyped; retain a typed test boundary."""
    constructor: Any = kind
    result: Exception = constructor(message)
    return result


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Real private synthetic journal with fixed clock and no transport."""
    config = prepare_config('2022-01-03', 24900, 'a' * 64, '2022-01-02T12:00:00+05:30')
    path = tmp_path / 'config.json'
    path.write_bytes(canonical(config))
    state = tmp_path / 'state'
    clock = datetime.fromisoformat('2022-01-03T09:20:31+05:30')

    class Clock:
        @staticmethod
        def now(zone: object) -> datetime:
            return clock

    class Drive:
        def check_folder(self) -> None:
            pass

        def close(self) -> None:
            pass

    drive = Drive()
    monkeypatch.setattr(job, 'datetime', Clock)
    monkeypatch.setattr(job, 'measure_clock', lambda: {})
    monkeypatch.setattr(job, 'clock_error', lambda *a, **k: None)
    monkeypatch.setattr(job, 'credentials', lambda _: object())
    monkeypatch.setattr(job, 'DriveArchive', lambda *a: drive)
    opening = (clock - timedelta(minutes=5, seconds=31)).isoformat()
    monkeypatch.setattr(job, 'read_current', lambda *a: [[opening, 25000, 25003, 24998, 25001, 0, 0]])
    monkeypatch.setenv('FORWARD_CAPTURE_LICENSE_ACK', 'true')
    monkeypatch.setenv('UPSTOX_ANALYTICS_TOKEN', 'SYNTHETIC_SECRET')
    monkeypatch.setenv('FORWARD_TOKEN_EXPIRES_AT', '2022-01-03T23:00:00+05:30')
    monkeypatch.setattr(job, 'publish', lambda *a: {'status': 'REMOTE_VERIFIED'})
    return {'args': ['--config', str(path), '--state', str(state)],
            'state': state, 'drive': drive, 'config': config}


@pytest.mark.parametrize('boundary,stage,committed,verified', [
    ('folder', 'DRIVE_FOLDER_CHECK', True, False),
    ('publish', 'DRIVE_PUBLISH_VERIFY', True, False),
    ('receipt', 'LOCAL_RECEIPT_WRITE', True, True),
    ('close', 'DRIVE_CLOSE', True, True),
    ('read', 'MARKET_DATA_READ', False, False),
    ('record', 'LOCAL_RECORD_POLL', None, False),
    ('credentials', 'DRIVE_CONFIGURATION', False, False),
])
def test_failure_boundary(runtime: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
                          capsys: pytest.CaptureFixture[str], boundary: str, stage: str,
                          committed: bool | None, verified: bool) -> None:
    def fail(*args: object, **kwargs: object) -> Any:
        raise RuntimeError('SYNTHETIC_SECRET https://private.invalid/provider-body')

    if boundary in ('folder', 'close'):
        monkeypatch.setattr(runtime['drive'], 'check_folder' if boundary == 'folder' else 'close', fail)
    elif boundary == 'record':
        monkeypatch.setattr(Producer, 'record_poll', fail)
    elif boundary == 'receipt':
        original = getattr(job, 'write_once')

        def write(path: Path, content: Any) -> None:
            if path.name.startswith('receipt-'):
                fail()
            original(path, content)

        monkeypatch.setattr(job, 'write_once', write)
    else:
        monkeypatch.setattr(job, {'publish': 'publish', 'read': 'read_current',
                                 'credentials': 'credentials'}[boundary], fail)
    assert job.main(runtime['args'] + ['--confirm-run']) == 2
    output = capsys.readouterr()
    assert 'SYNTHETIC_SECRET' not in output.out + output.err
    assert 'private.invalid' not in output.out + output.err
    record = json.loads(output.out)
    assert record['stage'] == stage
    assert record['local_poll_committed'] is committed
    assert record['remote_verified'] is verified
    assert record['receipt_written'] is (boundary == 'close')
    failures = list(runtime['state'].glob('failure-*.json'))
    assert len(failures) == 1
    assert json.loads(failures[0].read_bytes())['stage'] == stage
    if committed:
        producer = Producer(runtime['config'], runtime['state'] / 'observations.sqlite',
                            InputArchive(runtime['state'] / 'inputs'))
        assert len(producer.context()) == 1
        assert producer.bundle('CHECK', producer.context())['recorded_decisions'] == 1


def test_cleanup_cannot_mask_refresh_failure(runtime: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    def folder() -> None:
        raise google_error(RefreshError, 'SYNTHETIC_SECRET invalid_grant provider-body')

    def close() -> None:
        raise RuntimeError('SECOND_SECRET')

    monkeypatch.setattr(runtime['drive'], 'check_folder', folder)
    monkeypatch.setattr(runtime['drive'], 'close', close)
    assert job.main(runtime['args'] + ['--confirm-run']) == 2
    output = capsys.readouterr()
    record = json.loads(output.out)
    assert record['stage'] == 'DRIVE_FOLDER_CHECK'
    assert record['category'] == 'DRIVE_AUTH_REFRESH_FAILED'
    assert 'SECRET' not in output.out + output.err


def test_committed_poll_then_bundle_failure_is_unknown(runtime: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    original = Producer.bundle

    def broken_bundle(self: Producer, *args: Any, **kwargs: Any) -> Any:
        raise IntegrityError('FORWARD_ARCHIVE_IDENTITY_INVALID')

    monkeypatch.setattr(Producer, 'bundle', broken_bundle)
    assert job.main(runtime['args'] + ['--confirm-run']) == 2
    record = json.loads(capsys.readouterr().out)
    assert record['stage'] == 'LOCAL_RECORD_POLL'
    assert record['local_poll_committed'] is None
    assert record['remote_verified'] is False
    monkeypatch.setattr(Producer, 'bundle', original)
    producer = Producer(runtime['config'], runtime['state'] / 'observations.sqlite',
                        InputArchive(runtime['state'] / 'inputs'))
    assert len(producer.context()) == 1
    assert producer.bundle('CHECK', producer.context())['recorded_decisions'] == 1


def test_backup_only_does_not_fetch_or_add_observations(runtime: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    assert job.main(runtime['args'] + ['--confirm-run']) == 0
    capsys.readouterr()
    producer = Producer(runtime['config'], runtime['state'] / 'observations.sqlite',
                        InputArchive(runtime['state'] / 'inputs'))
    before = producer.bundle('CHECK', producer.context())

    def fail(*args: object) -> Any:
        raise AssertionError('Must not fetch market data')

    def folder() -> None:
        raise ArchiveError('DRIVE_HTTP_403')

    monkeypatch.setattr(job, 'read_current', fail)
    monkeypatch.setattr(runtime['drive'], 'check_folder', folder)
    monkeypatch.delenv('UPSTOX_ANALYTICS_TOKEN')
    assert job.main(runtime['args'] + ['--backup-only']) == 2
    record = json.loads(capsys.readouterr().out)
    assert record['stage'] == 'DRIVE_FOLDER_CHECK'
    assert record['category'] == 'DRIVE_HTTP_403'
    assert record['local_poll_committed'] is False
    assert producer.bundle('CHECK', producer.context()) == before


@pytest.mark.parametrize('error,expected', [
    (google_error(RefreshError, 'private'), 'DRIVE_AUTH_REFRESH_FAILED'),
    (google_error(TransportError, 'private'), 'TRANSPORT_FAILED'),
    (SSLError('private'), 'TLS_FAILED'), (Timeout('private'), 'TRANSPORT_TIMEOUT'),
    (ArchiveError('DRIVE_HTTP_404'), 'DRIVE_HTTP_404'),
    (ArchiveError('DRIVE_HTTP_404 private'), 'UNCLASSIFIED_FAILURE'),
    (IntegrityError('FORWARD_REMOTE_VERIFICATION_FAILED'), 'FORWARD_REMOTE_VERIFICATION_FAILED'),
    (ValueError('private'), 'UNCLASSIFIED_FAILURE'),
])
def test_only_fixed_codes_exposed(error: Exception, expected: str) -> None:
    assert job.failure_category(error) == expected
