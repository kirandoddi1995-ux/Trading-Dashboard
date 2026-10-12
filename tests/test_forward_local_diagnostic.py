"""Synthetic local checks and frozen-code-preserving poll diagnostics."""
from datetime import date
import errno
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, cast

import pytest

import forward_local_diagnostic as diagnostic
import forward_nifty_job as job
import forward_nifty_schedule as schedule
from forward_nifty_producer import Producer
from research_integrity import IntegrityError, canonical
from test_forward_nifty_producer import config as _config_fixture, candles as _candles, make as _make, poll as _poll

config = _config_fixture
candles = cast(Callable[[dict[str, Any], int], list[list[Any]]], _candles)
make = cast(Callable[[Path, dict[str, Any]], Producer], _make)
poll = cast(Callable[[Producer, list[list[Any]], int], dict[str, Any]], _poll)


@pytest.mark.parametrize('code', sorted(diagnostic.LOCAL_CODES))
def test_fixed_local_integrity_categories(code: str) -> None:
    assert diagnostic.local_category(IntegrityError(code)) == code


def test_redaction_and_sqlite_classification() -> None:
    assert diagnostic.local_category(IntegrityError('PRIVATE token path')) is None
    assert diagnostic.local_category(RuntimeError('PRIVATE token path')) is None
    assert diagnostic.local_category(OSError(errno.ENOSPC, 'PRIVATE')) == 'LOCAL_DISK_FULL'
    error = sqlite3.OperationalError('PRIVATE provider message')
    error.sqlite_errorcode = sqlite3.SQLITE_BUSY
    assert diagnostic.local_category(error) == 'LOCAL_SQLITE_BUSY'


def test_preview_never_reads_state_or_credentials(monkeypatch: pytest.MonkeyPatch,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(diagnostic, 'inspect_session', lambda *a: pytest.fail('state read'))
    monkeypatch.setattr(diagnostic, 'supervised_poll', lambda *a: pytest.fail('poll'))
    assert diagnostic.main(['--root', 'unused']) == 0
    assert json.loads(capsys.readouterr().out)['writes'] == 0


def test_classifier_restored_even_when_scheduler_raises(tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    original = job.failure_category
    original_read = job.read_current
    def failing(args: list[str]) -> int:
        assert args == ['--root', str(tmp_path), '--mode', 'poll', '--confirm-run']
        assert job.failure_category(IntegrityError('CLOSED_BAR_REVISION_REVIEW_REQUIRED')) == 'CLOSED_BAR_REVISION_REVIEW_REQUIRED'
        raise RuntimeError('PRIVATE')
    monkeypatch.setattr(schedule, 'main', failing)
    with pytest.raises(RuntimeError):
        diagnostic.supervised_poll(tmp_path)
    assert job.failure_category is original
    assert job.read_current is original_read


@pytest.mark.parametrize('field,index', [('open', 1), ('high', 2), ('low', 3),
                                       ('close', 4), ('volume', 5), ('open_interest', 6)])
def test_revision_field_masks_without_values(field: str, index: int) -> None:
    values = [100, 110, 90, 105, 123456, 0]
    bar: list[Any] = ['2026-10-12T09:15:00+05:30', *values]
    bar[index] += 1
    report = diagnostic.compare_candles([{'start': bar[0], 'values': values}], [bar])
    assert report['revised_closed_bars'] == 1
    assert report['revisions'][0]['changed_fields'] == [field]
    assert '123456' not in json.dumps(report)
    assert report['resume_authorised'] is False


def test_timestamp_offset_and_numeric_representation_are_not_revisions() -> None:
    report = diagnostic.compare_candles(
        [{'start': '2026-10-12T03:45:00+00:00', 'values': [100, 110, 90, 105, 0, 0]}],
        [['2026-10-12T09:15:00+05:30', 100.0, 110.0, 90.0, 105.0, 0.0, 0.0]])
    assert report['matched_closed_bars'] == 1
    assert report['revisions'] == []


@pytest.mark.parametrize('value', [True, 'SECRET', float('nan'), float('inf'), None])
def test_revision_check_rejects_invalid_values_without_echo(value: Any) -> None:
    with pytest.raises(IntegrityError, match='^CANDLE_VALUES_INVALID$'):
        diagnostic.compare_candles(
            [{'start': '2026-10-12T03:45:00+00:00', 'values': [100, 110, 90, 105, 0, 0]}],
            [['2026-10-12T03:45:00+00:00', value, 110, 90, 105, 0, 0]])


def test_revision_report_missing_and_empty_response_stay_missing() -> None:
    report = diagnostic.compare_candles(
        [{'start': '2026-10-12T03:45:00+00:00', 'values': [100, 110, 90, 105, 0, 0]}], [])
    assert report['stored_bars_absent_from_response'] == 1
    assert report['matched_closed_bars'] == 0
    assert diagnostic.compare_candles([], [])['stored_closed_bars'] == 0


def test_revision_report_duplicate_and_size_bounds() -> None:
    bar: list[Any] = ['2026-10-12T03:45:00+00:00', 100, 110, 90, 105, 0, 0]
    with pytest.raises(IntegrityError, match='CANDLE_GRID_INVALID'):
        diagnostic.compare_candles([], [bar, bar])
    with pytest.raises(IntegrityError, match='LOCAL_STATE_SIZE_BOUND'):
        diagnostic.compare_candles([], [bar] * 101)


def test_guarded_read_reports_once_and_preserves_bars(tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    bars: list[list[Any]] = [['private-price']]
    reads: list[int] = []
    def read(session: Any, token: str) -> list[list[Any]]:
        reads.append(1)
        return bars
    monkeypatch.setattr(job, 'read_current', read)
    monkeypatch.setattr(diagnostic, 'revision_report', lambda *a: {'status': 'SAFE'})
    def run(args: list[str]) -> int:
        assert job.read_current(None, 'PRIVATE_TOKEN') is bars
        return 2
    monkeypatch.setattr(schedule, 'main', run)
    assert diagnostic.supervised_poll(tmp_path) == 2
    assert reads == [1]
    assert json.loads(capsys.readouterr().out) == {'status': 'SAFE'}
    assert job.read_current is read


def test_diagnostic_failure_never_replaces_producer_validation(tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    bars: list[list[Any]] = []
    monkeypatch.setattr(job, 'read_current', lambda *a: bars)
    def blocked(*args: Any) -> dict[str, Any]:
        raise RuntimeError('SECRET_TOKEN_AND_PRICE')
    monkeypatch.setattr(diagnostic, 'revision_report', blocked)
    def run(args: list[str]) -> int:
        assert job.read_current(None, 'SECRET') is bars
        return 2
    monkeypatch.setattr(schedule, 'main', run)
    assert diagnostic.supervised_poll(tmp_path) == 2
    output = capsys.readouterr().out
    assert 'SECRET' not in output
    assert json.loads(output)['status'] == 'REVISION_DIAGNOSTIC_BLOCKED'


def test_read_only_inspection_preserves_existing_state(tmp_path: Path, config: dict[str, Any]) -> None:
    root = tmp_path / 'private'
    session = root / '2022-01-03'
    session.mkdir(parents=True)
    (session / 'config.json').write_bytes(canonical(config))
    from research_input_archive import InputArchive
    producer = Producer(config, session / 'state' / 'observations.sqlite', InputArchive(session / 'state' / 'inputs'))
    poll(producer, candles(config, 1), 5)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    result = diagnostic.inspect_session(root, date(2022, 1, 3))
    assert result['counts'] == {'observations': 1, 'forward_context': 1}
    assert result['resume_authorised'] is False
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()} == before


def test_first_poll_then_closed_revision_is_reproduced_not_relaxed(tmp_path: Path,
                                                                config: dict[str, Any]) -> None:
    producer = make(tmp_path, config)
    assert poll(producer, candles(config, 1), 5)['recorded_decisions'] == 1
    changed = candles(config, 2)
    changed[0][4] += 1
    with pytest.raises(IntegrityError) as error:
        poll(producer, changed, 10)
    assert diagnostic.local_category(error.value) == 'CLOSED_BAR_REVISION_REVIEW_REQUIRED'
    assert len(producer.context()) == 1
    assert producer.bundle('CHECK', producer.context())['recorded_decisions'] == 1


def test_missing_database_is_not_created(tmp_path: Path, config: dict[str, Any]) -> None:
    folder = tmp_path / '2022-01-03'
    folder.mkdir()
    (folder / 'config.json').write_bytes(canonical(config))
    with pytest.raises(FileNotFoundError):
        diagnostic.inspect_session(tmp_path, date(2022, 1, 3))
    assert not (folder / 'state').exists()
