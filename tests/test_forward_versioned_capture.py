"""Launcher seams only; default preview has zero IO or credentials."""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Any

import pytest

import forward_versioned_capture as launcher
import forward_nifty_job as job
import forward_nifty_schedule as schedule
from research_integrity import IntegrityError, canonical
from test_forward_versioned_producer import config as _fixture

config = _fixture
DAY = date(2022, 1, 3)


def test_preview_never_reads_or_probes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                     capsys: pytest.CaptureFixture[str]) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail('preview accessed state or clock')
    monkeypatch.setattr(launcher, 'private_read', forbidden)
    monkeypatch.setattr(schedule, 'now', forbidden)
    assert launcher.main(['--root', str(tmp_path), '--session-date', '2022-01-03']) == 0
    assert 'PREVIEW' in capsys.readouterr().out


def setup(tmp_path: Path, config: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    opening = datetime.fromisoformat(config['session_open'])
    monkeypatch.setattr(schedule, 'now', lambda: opening.replace(hour=9, minute=0).astimezone(timezone.utc))
    monkeypatch.setattr(schedule, 'measure_clock', lambda: {})
    monkeypatch.setattr(schedule, 'clock_error', lambda *args, **kwargs: None)
    folder = tmp_path / DAY.isoformat()
    folder.mkdir()
    (folder / 'config.json').write_bytes(canonical(config))
    assert launcher.prepare(tmp_path, DAY)['status'] == 'VERSION_POLICY_PREPARED'


def test_prepare_no_overwrite_or_after_open(tmp_path: Path, config: dict[str, Any],
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    setup(tmp_path, config, monkeypatch)
    with pytest.raises(IntegrityError):
        launcher.prepare(tmp_path, DAY)
    monkeypatch.setattr(schedule, 'now', lambda: datetime.fromisoformat(config['session_open']))
    with pytest.raises(IntegrityError):
        launcher.prepare(tmp_path, DAY)


@pytest.mark.parametrize('raised', [False, True])
def test_process_bindings_restored_and_original_scheduler_used(tmp_path: Path, config: dict[str, Any],
                                                             monkeypatch: pytest.MonkeyPatch, raised: bool) -> None:
    setup(tmp_path, config, monkeypatch)
    original = {n: getattr(job, n) for n in ('Producer', 'publish', 'write_once', 'failure_category')}
    def capture(args: list[str]) -> int:
        assert args == ['--root', str(tmp_path), '--mode', 'poll', '--confirm-run']
        assert getattr(job, 'Producer') != original['Producer']
        if raised:
            raise IntegrityError('synthetic')
        return 0
    monkeypatch.setattr(schedule, 'main', capture)
    if raised:
        with pytest.raises(IntegrityError):
            launcher.run(tmp_path, DAY, 'poll')
    else:
        assert launcher.run(tmp_path, DAY, 'poll') == 0
    assert all(getattr(job, name) == value for name, value in original.items())


def test_wrong_session_blocks_before_scheduler(tmp_path: Path, config: dict[str, Any],
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    setup(tmp_path, config, monkeypatch)
    monkeypatch.setattr(schedule, 'now', lambda: datetime(2022, 1, 4, tzinfo=timezone.utc))
    with pytest.raises(IntegrityError):
        launcher.run(tmp_path, DAY, 'poll')


def test_clock_failure_does_not_freeze(tmp_path: Path, config: dict[str, Any],
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / DAY.isoformat()
    folder.mkdir()
    (folder / 'config.json').write_bytes(canonical(config))
    monkeypatch.setattr(schedule, 'now', lambda: datetime.fromisoformat(config['frozen_at']))
    monkeypatch.setattr(schedule, 'measure_clock', lambda: {})
    monkeypatch.setattr(schedule, 'clock_error', lambda *args, **kwargs: 'CLOCK_UNVERIFIED')
    with pytest.raises(IntegrityError, match='CLOCK_UNVERIFIED'):
        launcher.prepare(tmp_path, DAY)
    assert not (folder / 'state' / 'versioned-v1' / 'recipe.json').exists()


def test_unchanged_job_integrates_two_polls_and_separate_receipts(tmp_path: Path, config: dict[str, Any],
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    from test_forward_versioned_producer import candles
    setup(tmp_path, config, monkeypatch)
    current = datetime.fromisoformat(config['session_open'])
    class Clock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> Clock:
            return cls.fromtimestamp(current.timestamp(), tz or timezone.utc)
    class Drive:
        def __init__(self, *args: Any) -> None:
            self.objects: dict[str, bytes] = {}
        def check_folder(self) -> None:
            pass
        def close(self) -> None:
            pass
        def put(self, name: str, raw: bytes, batch: str, kind: str, mime: str) -> str:
            self.objects[kind] = raw
            return kind
        def download(self, identity: str) -> bytes:
            return self.objects[identity]
    monkeypatch.setattr(job, 'datetime', Clock)
    monkeypatch.setattr(schedule, 'now', lambda: current)
    monkeypatch.setattr(job, 'measure_clock', lambda: {})
    monkeypatch.setattr(job, 'clock_error', lambda *args, **kwargs: None)
    monkeypatch.setattr(job, 'credentials', lambda value: None)
    monkeypatch.setattr(job, 'DriveArchive', Drive)
    monkeypatch.setenv('FORWARD_CAPTURE_LICENSE_ACK', 'true')
    monkeypatch.setenv('UPSTOX_ANALYTICS_TOKEN', 'synthetic-not-a-token')
    monkeypatch.setenv('FORWARD_TOKEN_EXPIRES_AT', '2022-01-04T00:00:00+00:00')
    monkeypatch.setenv('DRIVE_OAUTH_TOKEN_JSON', '{}')
    state = tmp_path / DAY.isoformat() / 'state'
    monkeypatch.setattr(schedule, 'main', lambda args: job.main([
        '--config', str(state.parent / 'config.json'), '--state', str(state), '--confirm-run']))
    for count in (1, 2):
        current = current.replace(hour=9, minute=15+count*5, second=30)
        bars = candles(config, count)
        if count == 2:
            bars[0][4] += 1
        monkeypatch.setattr(job, 'read_current', lambda session, token: bars)
        assert launcher.run(tmp_path, DAY, 'poll') == 0
    receipts = list((state / 'versioned-v1' / 'receipts').glob('receipt-*.json'))
    assert len(receipts) == 2
    assert sorted(json.loads(p.read_bytes())['recorded_decisions'] for p in receipts) == [1, 2]
    assert not (state / 'observations.sqlite').exists()
    assert not list(state.glob('receipt-*.json'))
    current = current.replace(hour=15, minute=40)
    assert launcher.run(tmp_path, DAY, 'audit') == 0
