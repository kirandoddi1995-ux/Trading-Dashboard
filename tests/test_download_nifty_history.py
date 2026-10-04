from datetime import date
import gzip
import io
import json

import pandas as pd
import pytest
import requests

import download_nifty_history as history


DAY = date(2026, 9, 30)
SECRET = "sensitive-test-token-never-print"


def rows():
    times = pd.date_range("2026-09-30 09:15", periods=75, freq="5min", tz="Asia/Kolkata")
    return [[t.isoformat(), 25000, 25002, 24998, 25001, 0, 0] for t in times]


class Response:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self.headers = status, headers or {}
        self.raw = json.dumps(body or {"status": "success", "data": {"candles": rows()}}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, size):
        yield self.raw


class Session:
    def __init__(self, responses):
        self.responses, self.calls = iter(responses), []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def test_monthly_boundaries_leap_year_and_inclusive_ranges():
    result = list(history.monthly(date(2024, 1, 19), date(2024, 3, 3)))
    assert result == [(date(2024, 1, 19), date(2024, 1, 31)),
                      (date(2024, 2, 1), date(2024, 2, 29)), (date(2024, 3, 1), date(2024, 3, 3))]


def test_documented_order_timezone_and_reverse_provider_order():
    result = history.candles({"status": "success", "data": {"candles": rows()[::-1]}}, DAY, DAY)
    assert history.check_session(result, DAY)["status"] == "PASS"
    assert result[0][0].endswith("09:15:00+05:30")
    assert result[-1][0].endswith("15:25:00+05:30")


@pytest.mark.parametrize("issue", ["naive", "duplicate", "conflict", "nan", "crossed", "out_of_range", "string", "bool", "shape"])
def test_invalid_candles_rejected(issue):
    data = rows()
    if issue == "naive":
        data[0][0] = "2026-09-30T09:15:00"
    elif issue in {"duplicate", "conflict"}:
        data.append(data[0].copy())
        if issue == "conflict":
            data[-1][4] = 25002
    elif issue == "nan":
        data[0][1] = float("nan")
    elif issue == "crossed":
        data[0][2] = 1
    elif issue == "out_of_range":
        data[0][0] = "2026-09-29T09:15:00+05:30"
    elif issue == "string":
        data[0][1] = "25000"
    elif issue == "bool":
        data[0][5] = True
    else:
        data[0].pop()
    with pytest.raises(history.HistoryError):
        history.candles({"status": "success", "data": {"candles": data}}, DAY, DAY)


def test_missing_and_end_time_shift_fail_check():
    assert history.check_session(rows()[1:], DAY)["status"] == "FAIL"
    shifted = rows()
    for row in shifted:
        row[0] = (pd.Timestamp(row[0]) + pd.Timedelta(minutes=5)).isoformat()
    assert history.check_session(shifted, DAY)["status"] == "FAIL"


def test_https_reused_session_redirect_denied_and_bounded_retry():
    session = Session([Response(429, headers={"Retry-After": "2"}), Response()])
    waits = []
    assert len(history.Reader(SECRET, session, waits.append).fetch(DAY, DAY)) == 75
    assert waits == [2]
    for url, kwargs in session.calls:
        assert url.startswith("https://api.upstox.com/v3/historical-candle/")
        assert kwargs["verify"] is True and kwargs["allow_redirects"] is False
        assert kwargs["timeout"] == (5, 30)


@pytest.mark.parametrize("status,code", [(401, "AUTH_REQUIRED"), (403, "AUTH_REQUIRED"), (302, "HTTP_REJECTED"), (404, "HTTP_REJECTED")])
def test_http_failures_do_not_expose_response_or_token(status, code, capsys):
    session = Session([Response(status, {"secret": SECRET})])
    with pytest.raises(history.HistoryError, match=code) as error:
        history.Reader(SECRET, session).fetch(DAY, DAY)
    assert SECRET not in str(error.value)
    assert SECRET not in capsys.readouterr().out
    assert len(session.calls) == 1


def test_transport_error_sanitized_after_bounded_retries():
    session = Session([requests.ConnectionError(SECRET)] * 3)
    with pytest.raises(history.HistoryError, match="TRANSPORT_FAILED") as error:
        history.Reader(SECRET, session, lambda _: None).fetch(DAY, DAY)
    assert SECRET not in str(error.value)
    assert len(session.calls) == 3


def test_size_bound(monkeypatch):
    monkeypatch.setattr(history, "MAX_RESPONSE", 10)
    with pytest.raises(history.HistoryError, match="RESPONSE_TOO_LARGE"):
        history.Reader(SECRET, Session([Response()])).fetch(DAY, DAY)


def test_archive_resume_and_tamper_detection(tmp_path):
    reader = history.Reader(SECRET, Session([Response()]))
    first, path = history.acquire(reader, tmp_path, DAY, DAY)
    assert history.acquire(None, tmp_path, DAY, DAY)[0] == first
    content = json.loads(gzip.decompress(path.read_bytes()))
    content["candles"][0][1] += 1
    path.write_bytes(gzip.compress(json.dumps(content).encode()))
    with pytest.raises(history.HistoryError, match="LOCAL_ARTIFACT_INVALID"):
        history.acquire(None, tmp_path, DAY, DAY)


def test_immutable_publication_never_overwrites(tmp_path):
    path = tmp_path / "artifact"
    history.immutable(path, b"first")
    history.immutable(path, b"first")
    with pytest.raises(history.HistoryError, match="CONFLICT"):
        history.immutable(path, b"second")
    assert path.read_bytes() == b"first"


def test_csv_and_parquet_roundtrip_and_assumption_label():
    csv, parquet = history.export(rows())
    frame = pd.read_parquet(io.BytesIO(parquet))
    assert len(frame) == len(pd.read_csv(io.BytesIO(csv))) == 75
    assert set(frame.availability_basis) == {"historical_final_assumed_bar_end"}
    assert pd.Timestamp(frame.available_at.iloc[0]) - pd.Timestamp(frame.timestamp.iloc[0]) == pd.Timedelta(minutes=5)


def test_bulk_gate_precedes_token_access(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(history.getpass, "getpass", lambda _: pytest.fail("Token prompt before gate"))
    assert history.main(["download", "--root", str(tmp_path), "--licence-confirmed"]) == 1
    assert "REVIEWED_SESSION_CHECK_REQUIRED" in capsys.readouterr().out


def test_check_is_first_cli_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("UPSTOX_ANALYTICS_TOKEN", SECRET)
    reader = history.Reader(SECRET, Session([Response()]))
    monkeypatch.setattr(history, "Reader", lambda *_: reader)
    assert history.main(["check", "--date", str(DAY), "--root", str(tmp_path), "--licence-confirmed"]) == 0
    assert json.loads((tmp_path / "session-check.json").read_text())["status"] == "PASS"
    output = capsys.readouterr()
    assert SECRET not in output.out + output.err


def test_project_output_rejected_before_auth(capsys):
    assert history.main(["check", "--date", str(DAY), "--root", str(history.Path(history.__file__).parent)]) == 1
    assert "DATA_MUST_BE_OUTSIDE_PROJECT" in capsys.readouterr().out


def test_daily_range_allows_previous_year_without_weakening_minutes():
    earlier = date(2021, 12, 1)
    with pytest.raises(history.HistoryError, match="INVALID_HISTORY_RANGE"):
        list(history.monthly(earlier, DAY))
    assert len(list(history.monthly(earlier, date(2022, 1, 31), date(2000, 1, 1)))) == 2


def test_daily_cli_does_not_export_five_minute_availability(tmp_path, monkeypatch, capsys):
    reader = history.Reader(SECRET, Session([Response()]))
    history.acquire(reader, tmp_path, DAY, DAY)
    history.immutable(tmp_path / "session-check.json", history.encoded(history.check_session(rows(), DAY)))
    monkeypatch.setenv("UPSTOX_ANALYTICS_TOKEN", SECRET)
    daily = [[f"{DAY}T00:00:00+05:30", 25000, 25002, 24998, 25001, 0, 0]]
    reader = history.Reader(SECRET, Session([Response(body={"status": "success", "data": {"candles": daily}})]))
    monkeypatch.setattr(history, "Reader", lambda *_: reader)
    assert history.main(["download-daily", "--root", str(tmp_path), "--start", str(DAY),
        "--end", str(DAY), "--licence-confirmed", "--reviewed-session-check"]) == 0
    assert reader.session.calls[0][0].endswith(f"/days/1/{DAY}/{DAY}")
    assert not list(tmp_path.glob("*.csv"))
    assert (tmp_path / f"daily-{DAY}-{DAY}.manifest.json").exists()
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err
