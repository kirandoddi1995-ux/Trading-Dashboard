"""Synthetic pre-open initialization, no secrets, transport or real session data."""
from datetime import date, timedelta
import json
from pathlib import Path
from typing import Any, Callable, cast

import pytest

import forward_quarantine_prepare as preparation
from forward_local_diagnostic import inspect_session
from forward_nifty_producer import ROOT
from forward_revision_quarantine import QuarantineProducer
from research_input_archive import InputArchive
from research_integrity import IntegrityError, canonical
from research_replay_comparison import instant
from test_forward_nifty_producer import config as _fixture, candles as _candles

config = _fixture
candles = cast(Callable[[dict[str, Any], int], list[list[Any]]], _candles)


def saved(tmp_path: Path, config: dict[str, Any]) -> tuple[Path, date]:
    day = instant(config['session_open']).date()
    path = tmp_path / day.isoformat()
    path.mkdir()
    (path / 'config.json').write_bytes(canonical(config))
    return tmp_path, day


def test_new_empty_state_supports_raw_producer(tmp_path: Path, config: dict[str, Any]) -> None:
    root, day = saved(tmp_path, config)
    original = (root / day.isoformat() / 'config.json').read_bytes()
    result = preparation.prepare(root, day, lambda: instant(config['session_open']) - timedelta(minutes=1))
    assert result['recorded_decisions'] == 0 and result['missing_decisions'] == 75
    assert result['decision_capture_enabled'] is False
    state = root / day.isoformat() / 'state'
    producer = QuarantineProducer(config, state / 'observations.sqlite', InputArchive(state / 'inputs'))
    assert producer.baseline == []
    receipt = instant(config['session_open']) + timedelta(minutes=5, seconds=30)
    raw = producer.record_poll(candles(config, 1), received_at=receipt.isoformat(), computed_clock=lambda: receipt)
    assert raw['recorded_decisions'] == 0 and raw['missing_decisions'] == 75
    assert inspect_session(root, day)['counts'] == {'observations': 0, 'forward_context': 0}
    assert (state / 'inputs').is_dir()
    assert (root / day.isoformat() / 'config.json').read_bytes() == original


@pytest.mark.parametrize('offset', [0, 1, 375, -600])
def test_wrong_time_creates_no_state(tmp_path: Path, config: dict[str, Any], offset: int) -> None:
    root, day = saved(tmp_path, config)
    with pytest.raises(IntegrityError, match='EMPTY_JOURNAL_PREOPEN_REQUIRED'):
        preparation.prepare(root, day, lambda: instant(config['session_open']) + timedelta(minutes=offset))
    assert not (root / day.isoformat() / 'state').exists()


def test_naive_clock_blocked(tmp_path: Path, config: dict[str, Any]) -> None:
    root, day = saved(tmp_path, config)
    with pytest.raises(IntegrityError):
        preparation.prepare(root, day, lambda: instant(config['session_open']).replace(tzinfo=None))
    assert not (root / day.isoformat() / 'state').exists()


def test_existing_state_never_touched(tmp_path: Path, config: dict[str, Any]) -> None:
    root, day = saved(tmp_path, config)
    state = root / day.isoformat() / 'state'
    state.mkdir()
    marker = state / 'existing'
    marker.write_bytes(b'KEEP')
    with pytest.raises(FileExistsError):
        preparation.prepare(root, day, lambda: instant(config['session_open']) - timedelta(minutes=1))
    assert marker.read_bytes() == b'KEEP' and list(state.iterdir()) == [marker]


def test_partial_failure_is_retained(tmp_path: Path, config: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    root, day = saved(tmp_path, config)
    def failed(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError('private price password path must not escape')
    monkeypatch.setattr(preparation, 'Producer', failed)
    with pytest.raises(RuntimeError):
        preparation.prepare(root, day, lambda: instant(config['session_open']) - timedelta(minutes=1))
    assert (root / day.isoformat() / 'state').is_dir()
    with pytest.raises(FileExistsError):
        preparation.prepare(root, day, lambda: instant(config['session_open']) - timedelta(minutes=1))


def test_preview_and_redaction(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert preparation.main(['--root', str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)['writes'] == 0
    assert list(tmp_path.iterdir()) == []
    assert preparation.main(['--root', str(tmp_path), '--confirm-prepare-empty-journal']) == 2
    report = json.loads(capsys.readouterr().out)
    assert report['category'] == 'EMPTY_JOURNAL_PREOPEN_REQUIRED'
    assert str(tmp_path) not in json.dumps(report)


def test_bad_config_never_creates_state(tmp_path: Path, config: dict[str, Any]) -> None:
    root, day = saved(tmp_path, config)
    config['calendar_source'] = 'invented'
    (root / day.isoformat() / 'config.json').write_bytes(canonical(config))
    with pytest.raises(IntegrityError):
        preparation.prepare(root, day, lambda: instant(config['session_open']) - timedelta(minutes=1))
    assert not (root / day.isoformat() / 'state').exists()


def test_crossing_open_retains_partial_state(tmp_path: Path, config: dict[str, Any]) -> None:
    root, day = saved(tmp_path, config)
    times = iter([instant(config['session_open']) - timedelta(seconds=1), instant(config['session_open'])])
    with pytest.raises(IntegrityError, match='EMPTY_JOURNAL_PREOPEN_REQUIRED'):
        preparation.prepare(root, day, lambda: next(times))
    assert (root / day.isoformat() / 'state' / 'observations.sqlite').is_file()


def test_repository_and_relative_roots_forbidden(config: dict[str, Any]) -> None:
    day = instant(config['session_open']).date()
    for root in (Path('relative'), ROOT):
        with pytest.raises(IntegrityError, match='LOCAL_STATE_PRIVATE_PATH_REQUIRED'):
            preparation.prepare(root, day, lambda: instant(config['session_open']))
