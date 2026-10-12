"""Offline synthetic provider revisions; no credentials, real data or hosted writes."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any, Callable, cast

import pytest

import forward_nifty_job as job
import forward_nifty_schedule as schedule
import forward_revision_quarantine as quarantine
from forward_nifty_producer import Producer
from research_input_archive import InputArchive
from research_integrity import IntegrityError, canonical
from test_forward_nifty_producer import config as _fixture, candles as _candles, poll as _poll

config = _fixture
candles = cast(Callable[[dict[str, Any], int], list[list[Any]]], _candles)
poll = cast(Callable[[Producer, list[list[Any]], int], dict[str, Any]], _poll)


def baseline(config: dict[str, Any]) -> list[dict[str, Any]]:
    bar = candles(config, 1)[0]
    return [{'start': bar[0], 'values': bar[1:], 'available_at':
             (datetime.fromisoformat(config['session_open']) + timedelta(minutes=5, seconds=30)).isoformat()}]


def received(config: dict[str, Any], minutes: int = 10) -> str:
    return (datetime.fromisoformat(config['session_open']) + timedelta(minutes=minutes, seconds=30)).isoformat()


def test_preserves_both_closes_and_never_claims_decisions(config: dict[str, Any]) -> None:
    old = baseline(config)
    bars = candles(config, 2)
    bars[0][4] += 1
    record = quarantine.snapshot(config, bars, received(config), old, 'a' * 64)
    assert record['accepted_baseline'] == old
    assert record['closed_bars'][0]['values'][3] != old[0]['values'][3]
    assert record['revision_check']['revisions'][0]['changed_fields'] == ['close']
    assert record['closed_bars'][0]['received_at'] == record['received_at']
    assert record['training_eligible'] is False and record['decisions_added'] == 0
    assert quarantine.verify(canonical(record)) == record


@pytest.mark.parametrize('mutation', ['nan', 'negative', 'duplicate', 'naive', 'offgrid', 'outside', 'empty'])
def test_bad_rows_fail_closed(config: dict[str, Any], mutation: str) -> None:
    bars = candles(config, 2)
    if mutation == 'nan':
        bars[0][1] = float('nan')
    elif mutation == 'negative':
        bars[0][5] = -1
    elif mutation == 'duplicate':
        bars.append(bars[0])
    elif mutation == 'naive':
        bars[0][0] = '2022-01-03T09:15:00'
    elif mutation == 'offgrid':
        bars[0][0] = '2022-01-03T09:16:00+05:30'
    elif mutation == 'outside':
        bars[0][0] = '2022-01-03T09:10:00+05:30'
    else:
        bars = []
    with pytest.raises(IntegrityError):
        quarantine.snapshot(config, bars, received(config), baseline(config), 'a' * 64)


@pytest.mark.parametrize('timestamp', ['2022-01-03T09:19:30+05:30', '2022-01-03T09:22:01+05:30',
                                     '2022-01-03T15:35:30+05:30'])
def test_no_catchup_or_outside_slot(config: dict[str, Any], timestamp: str) -> None:
    with pytest.raises(IntegrityError, match='MISSED_OR_OUTSIDE_POLL_SLOT'):
        quarantine.snapshot(config, candles(config, 2), timestamp, baseline(config), 'a' * 64)


def test_future_baseline_receipt_rejected(config: dict[str, Any]) -> None:
    old = baseline(config)
    old[0]['available_at'] = received(config, 15)
    with pytest.raises(IntegrityError, match='FORWARD_INPUT_STORE_CORRUPT'):
        quarantine.snapshot(config, candles(config, 2), received(config), old, 'a' * 64)


@pytest.mark.parametrize('field,value', [('training_eligible', True), ('decisions_added', 1),
                                       ('approval_authority', True), ('fill_evidence', True)])
def test_archive_cannot_be_promoted(config: dict[str, Any], field: str, value: Any) -> None:
    record = quarantine.snapshot(config, candles(config, 2), received(config), baseline(config), 'a' * 64)
    record[field] = value
    with pytest.raises(IntegrityError, match='ARCHIVE_CONTENT_INVALID'):
        quarantine.verify(canonical(record))


class MemoryDrive:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.bad_kind: str | None = None

    def check_folder(self) -> None:
        pass

    def put(self, name: str, data: bytes, batch_id: str, kind: str, mime: str) -> str:
        assert kind in ('data', 'manifest')  # Real transport's allowlist.
        identity = batch_id + '-' + kind
        self.files[identity] = data
        return identity

    def download(self, identity: str) -> bytes:
        return b'corrupt' if identity.endswith(str(self.bad_kind)) else self.files[identity]

    def close(self) -> None:
        pass


@pytest.mark.parametrize('bad', [None, 'data', 'manifest'])
def test_both_remote_objects_must_verify(config: dict[str, Any], bad: str | None) -> None:
    record = quarantine.snapshot(config, candles(config, 2), received(config), baseline(config), 'a' * 64)
    drive = MemoryDrive()
    drive.bad_kind = bad
    if bad is not None:
        with pytest.raises(IntegrityError, match='ARCHIVE_ACKNOWLEDGMENT_FAILED'):
            quarantine.publish(drive, {'_snapshot': record})
    else:
        manifest = quarantine.publish(drive, {'_snapshot': record})
        assert manifest['status'] == 'REMOTE_VERIFIED' and manifest['decisions_added'] == 0


def prepared(tmp_path: Path, config: dict[str, Any]) -> tuple[Path, Path]:
    root = tmp_path / 'private'
    base = root / '2022-01-03'
    base.mkdir(parents=True)
    (base / 'config.json').write_bytes(canonical(config))
    journal = base / 'state' / 'observations.sqlite'
    producer = Producer(config, journal, InputArchive(journal.parent / 'inputs'))
    poll(producer, candles(config, 1), 5)
    return root, journal


def test_two_slots_preserve_journal_and_original_inputs(tmp_path: Path, config: dict[str, Any]) -> None:
    root, journal = prepared(tmp_path, config)
    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    recorder = quarantine.QuarantineProducer(config, journal, None)
    for minutes in (10, 15):
        bars = candles(config, minutes // 5)
        bars[0][4] += 1
        result = recorder.record_poll(bars, received_at=received(config, minutes), computed_clock=datetime.now)
        assert result['recorded_decisions'] == 1 and result['missing_decisions'] == 74
        assert quarantine.verify(canonical(result['_snapshot']))['decisions_added'] == 0
    assert all(path.read_bytes() == data for path, data in before.items())
    assert len(list(recorder.directory.glob('snapshots/*.json'))) == 2
    with pytest.raises(IntegrityError, match='QUARANTINE_SLOT_ALREADY_RECORDED'):
        recorder.record_poll(bars, received_at=received(config, 15), computed_clock=datetime.now)
    assert not (recorder.directory / '.quarantine-lock').exists()


def test_existing_policy_cannot_change(tmp_path: Path, config: dict[str, Any]) -> None:
    _, journal = prepared(tmp_path, config)
    recorder = quarantine.QuarantineProducer(config, journal, None)
    recorder.record_poll(candles(config, 2), received_at=received(config), computed_clock=datetime.now)
    recorder.code_hash = 'b' * 64
    with pytest.raises(IntegrityError, match='ARCHIVE_CONFLICT'):
        recorder.record_poll(candles(config, 3), received_at=received(config, 15), computed_clock=datetime.now)


def test_preview_is_offline(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(quarantine, 'run', lambda *a: pytest.fail('run'))
    assert quarantine.main(['--root', 'unused']) == 0
    assert json.loads(capsys.readouterr().out)['credential_reads'] == 0


def test_scoped_wiring_restored_on_scheduler_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    originals = {name: getattr(job, name) for name in ('Producer', 'publish', 'write_once', 'failure_category')}
    def fail(args: list[str]) -> int:
        assert args == ['--root', str(tmp_path), '--mode', 'poll', '--confirm-run']
        assert getattr(job, 'Producer') is quarantine.QuarantineProducer
        raise RuntimeError('SYNTHETIC')
    monkeypatch.setattr(schedule, 'main', fail)
    with pytest.raises(RuntimeError):
        quarantine.run(tmp_path)
    assert all(getattr(job, name) is value for name, value in originals.items())


def test_confirmation_requires_today_and_does_not_run_tomorrow(monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(schedule, 'now', lambda: datetime.fromisoformat('2026-10-13T09:25:30+05:30'))
    monkeypatch.setattr(quarantine, 'run', lambda *a: pytest.fail('capture called'))
    assert quarantine.main(['--root', 'unused', '--session-date', '2026-10-12',
                            '--confirm-raw-quarantine']) == 2
    assert json.loads(capsys.readouterr().out)['status'] == 'BLOCKED'


@pytest.mark.parametrize('fault', [None, 'data', 'manifest', 'licence', 'auth', 'clock'])
def test_runtime_job_two_slots_and_no_accepted_journal_write(tmp_path: Path, config: dict[str, Any],
        fault: str | None,
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    root, journal = prepared(tmp_path, config)
    before = journal.read_bytes()
    clock = [datetime.fromisoformat(received(config))]
    class Clock:
        @staticmethod
        def now(zone: Any) -> datetime:
            return clock[0]
    drive = MemoryDrive()
    drive.bad_kind = fault if fault in ('data', 'manifest') else None
    monkeypatch.setattr(job, 'datetime', Clock)
    monkeypatch.setattr(job, 'measure_clock', lambda: {'status': 'MEASURED'})
    monkeypatch.setattr(job, 'clock_error', lambda *a, **k: 'MISSING' if fault == 'clock' else None)
    monkeypatch.setattr(job, 'credentials', lambda *a: object())
    monkeypatch.setattr(job, 'DriveArchive', lambda *a: drive)
    bars = deepcopy(candles(config, 2))
    bars[0][4] += 1
    reads: list[int] = []
    def read(*args: Any) -> list[list[Any]]:
        reads.append(1)
        return bars
    monkeypatch.setattr(job, 'read_current', read)
    monkeypatch.setenv('FORWARD_CAPTURE_LICENSE_ACK', 'false' if fault == 'licence' else 'true')
    monkeypatch.setenv('UPSTOX_ANALYTICS_TOKEN', '' if fault == 'auth' else 'SYNTHETIC_SECRET')
    monkeypatch.setenv('FORWARD_TOKEN_EXPIRES_AT', '2022-01-03T23:00:00+05:30')
    def execute(args: list[str]) -> int:
        return job.main(['--config', str(journal.parent.parent / 'config.json'),
                         '--state', str(journal.parent), '--confirm-run'])
    monkeypatch.setattr(schedule, 'main', execute)
    for minutes in ((10, 15) if fault is None else (10,)):
        clock[0] = datetime.fromisoformat(received(config, minutes))
        assert quarantine.run(root) == (0 if fault is None else 2)
    assert journal.read_bytes() == before
    receipts = list(journal.parent.glob('quarantine-v1/receipts/receipt-*.json'))
    assert len(receipts) == (2 if fault is None else 0)
    assert not list(journal.parent.glob('receipt-*.json'))
    assert all(json.loads(p.read_bytes())['format'] == quarantine.MANIFEST for p in receipts)
    assert 'SYNTHETIC_SECRET' not in capsys.readouterr().out
    snapshots = list(journal.parent.glob('quarantine-v1/snapshots/*.json'))
    if fault in ('licence', 'auth', 'clock'):
        assert reads == [] and snapshots == []
    elif fault in ('data', 'manifest'):
        assert len(snapshots) == 1 and len(reads) == 1
