"""Synthetic private files only; no downloaded data, network or capture state."""
from datetime import date
import hashlib
import json
from pathlib import Path

import pytest

import nse_close_file_check as diagnostic
from research_integrity import IntegrityError


def csv_bytes(day='06-10-2026', value='20000.50', name='Nifty 50'):
    return f'Index Name,Index Date,Closing Index Value\n{name},{day},{value}\n'.encode()


def test_correct_file_not_authenticity_or_preparation(tmp_path):
    path = tmp_path / 'synthetic.csv'
    raw = csv_bytes()
    path.write_bytes(raw)
    result = diagnostic.check_file(path, date(2026, 10, 7))
    assert result['expected_close_date'] == '2026-10-06'
    assert result['sha256'] == hashlib.sha256(raw).hexdigest()
    assert result['source_authenticity'] == result['retrieval_time'] == 'NOT_ESTABLISHED_BY_TOOL'
    assert result['session_prepared'] is False and result['network_calls'] == result['writes'] == 0
    assert '20000' not in json.dumps(result)
    assert list(tmp_path.iterdir()) == [path]


def test_today_file_cannot_be_reused_as_next_sessions_close(tmp_path):
    path = tmp_path / 'synthetic.csv'
    path.write_bytes(csv_bytes())
    with pytest.raises(IntegrityError, match='DATE_MISMATCH'):
        diagnostic.check_file(path, date(2026, 10, 8))


@pytest.mark.parametrize('raw', [b'', b'<html>Denied</html>', csv_bytes(name='Nifty 50 TRI'),
    csv_bytes() + b'Nifty 50,06-10-2026,20000.50\n', csv_bytes(value='NaN'),
    b'x' * (diagnostic.LIMIT + 1)], ids=['empty', 'html', 'tri', 'duplicate', 'nan', 'oversize'])
def test_bad_source_fail_closed(tmp_path, raw):
    path = tmp_path / 'synthetic.csv'
    path.write_bytes(raw)
    with pytest.raises(IntegrityError):
        diagnostic.check_file(path, date(2026, 10, 7))


def test_holiday_weekend_and_special_previous_session(tmp_path):
    path = tmp_path / 'synthetic.csv'
    path.write_bytes(csv_bytes(day='01-10-2026'))
    assert diagnostic.check_file(path, date(2026, 10, 5))['expected_close_date'] == '2026-10-01'
    path.write_bytes(csv_bytes(day='02-03-2024'))
    assert diagnostic.check_file(path, date(2024, 3, 4))['expected_close_date'] == '2024-03-02'
    with pytest.raises(IntegrityError):
        diagnostic.check_file(path, date(2026, 10, 2))


@pytest.mark.parametrize('path', ['//private-server/share/source.csv', '\\\\private-server\\share\\source.csv'])
def test_network_paths_block_before_resolution(path, monkeypatch):
    monkeypatch.setattr(Path, 'resolve', lambda *args, **kwargs: pytest.fail('Resolution'))
    with pytest.raises(IntegrityError, match='LOCAL_PRIVATE'):
        diagnostic.check_file(Path(path), date(2026, 10, 7))


def test_code_folder_source_rejected_without_read():
    with pytest.raises(IntegrityError, match='OUTSIDE_CODE'):
        diagnostic.check_file(Path(diagnostic.__file__), date(2026, 10, 7))


def test_preview_does_not_read_or_resolve_file(monkeypatch, capsys):
    monkeypatch.setattr(Path, 'resolve', lambda *args, **kwargs: pytest.fail('Resolution'))
    monkeypatch.setattr(Path, 'open', lambda *args, **kwargs: pytest.fail('Read'))
    assert diagnostic.main(['--session-date', '2026-10-07', '--file', 'PRIVATE_PATH']) == 0
    output = capsys.readouterr().out
    assert 'PRIVATE' not in output and json.loads(output)['file_reads'] == 0


@pytest.mark.parametrize('session_date', ['20261007', '2026-02-30', 'PRIVATE_INVALID_DATE'])
def test_invalid_date_redacted(session_date, monkeypatch, capsys):
    monkeypatch.setattr(Path, 'open', lambda *args, **kwargs: pytest.fail('Read'))
    assert diagnostic.main(['--session-date', session_date, '--file', 'PRIVATE_PATH', '--check']) == 2
    output = capsys.readouterr().out
    assert 'PRIVATE' not in output
    assert json.loads(output)['code'] == 'SESSION_DATE_INVALID'


def test_missing_file_redacted(tmp_path, capsys):
    path = tmp_path / 'PRIVATE_PATH.csv'
    assert diagnostic.main(['--session-date', '2026-10-07', '--file', str(path), '--check']) == 2
    output = capsys.readouterr().out
    assert 'PRIVATE' not in output and str(tmp_path) not in output
    assert json.loads(output)['code'] == 'FILE_CHECK_UNAVAILABLE'


def test_cli_success_has_no_price_or_path(tmp_path, capsys):
    path = tmp_path / 'PRIVATE_PATH.csv'
    path.write_bytes(csv_bytes())
    assert diagnostic.main(['--session-date', '2026-10-07', '--file', str(path), '--check']) == 0
    output = capsys.readouterr().out
    assert 'PRIVATE' not in output and '20000' not in output
    assert json.loads(output)['session_prepared'] is False
