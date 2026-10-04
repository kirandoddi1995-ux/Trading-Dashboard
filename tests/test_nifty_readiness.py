from datetime import date
import gzip
import json

import pandas as pd
import pytest

from download_nifty_history import KEY, VERSION, encoded, sha, export
from nifty_session_calendar import session
from prepare_nifty_replay import audit, daily_closes, main
from intraday_directional_replay import validate


def bars(day, count=75, opening="09:15"):
    index = pd.date_range(f"{day} {opening}", periods=count, freq="5min", tz="Asia/Kolkata").tz_convert("UTC")
    return pd.DataFrame({"Open": 100, "High": 102, "Low": 99, "Close": 101,
                         "available_at": index + pd.Timedelta(minutes=5)}, index=index)


@pytest.mark.parametrize("day,kind", [
    ("2023-06-28", "REGULAR"), ("2023-06-29", "CLOSED"),
    ("2024-01-20", "SPECIAL"), ("2024-01-22", "CLOSED"),
    ("2024-05-20", "CLOSED"), ("2024-11-20", "CLOSED"),
    ("2026-01-15", "CLOSED"), ("2026-02-01", "SPECIAL")])
def test_amended_calendar(day, kind):
    assert session(date.fromisoformat(day))["kind"] == kind


def test_complete_missing_and_previous_close_no_fallback():
    frame = pd.concat([bars("2026-09-28"), bars("2026-09-30").iloc[:-1]])
    closes = {date(2026, 9, 25): {"close": 99, "source_sha256": "a"}}
    report, sessions = audit(frame, date(2026, 9, 28), date(2026, 9, 30), closes, True)
    assert report["counts"] == {"REGULAR_COMPLETE": 1, "REGULAR_MISSING": 1, "REGULAR_INCOMPLETE": 1}
    assert report["days"][1]["count"] == 0
    assert sessions[2]["previous_close"] is None
    assert sessions[2]["previous_close_date"] == "2026-09-29"
    accepted, excluded = validate(frame, sessions)
    assert len(accepted) == 1 and len(excluded) == 2


def test_special_close_used_but_special_never_scored():
    frame = pd.concat([bars("2026-02-01"), bars("2026-02-02")])
    closes = {date(2026, 1, 30): {"close": 99, "source_sha256": "a"},
              date(2026, 2, 1): {"close": 100, "source_sha256": "b"}}
    report, sessions = audit(frame, date(2026, 2, 1), date(2026, 2, 2), closes, True)
    assert report["counts"]["SPECIAL_COMPLETE"] == 1
    assert sessions[1]["previous_close"] == 100
    assert sessions[1]["reset_warmup"]
    accepted, excluded = validate(frame, sessions)
    assert len(accepted) == len(excluded) == 1


def test_muhurat_and_split_windows_not_regular():
    for day, frame in [
        (date(2024, 11, 1), bars("2024-11-01", 12, "18:00")),
        (date(2024, 3, 2), pd.concat([bars("2024-03-02", 9), bars("2024-03-02", 12, "11:30")]))]:
        report, sessions = audit(frame, day, day, {}, True)
        assert report["counts"] == {"SPECIAL_COMPLETE": 1}
        assert not report["replay_ready"]
        assert not validate(frame, sessions)[0]


def test_closed_bars_block_readiness_and_review_required():
    frame = pd.concat([bars("2026-09-28"), bars("2026-09-27", 1)]).sort_index()
    closes = {date(2026, 9, 25): {"close": 99, "source_sha256": "a"}}
    report, _ = audit(frame, date(2026, 9, 27), date(2026, 9, 28), closes, True)
    assert not report["replay_ready"]
    report, sessions = audit(bars("2026-09-28"), date(2026, 9, 28), date(2026, 9, 28), closes)
    assert not report["replay_ready"]
    assert not sessions[0]["replay_eligible"]


def test_delayed_availability_cannot_issue_ready_inputs():
    frame = bars("2026-09-28")
    frame["available_at"] += pd.Timedelta(seconds=1)
    closes = {date(2026, 9, 25): {"close": 99, "source_sha256": "a"}}
    report, sessions = audit(frame, date(2026, 9, 28), date(2026, 9, 28), closes, True)
    assert not report["replay_ready"]
    assert sessions[0]["exclusion_reason"] == "DELAYED_BAR_AVAILABILITY_UNSUPPORTED"


@pytest.mark.parametrize("condition", ["eligible", "outside", "missing_close", "unreviewed", "missing_bar", "delayed"])
def test_eligibility_and_exclusion_reason_are_consistent(condition):
    frame = bars("2026-09-28")
    closes = {date(2026, 9, 25): {"close": 99, "source_sha256": "a"}}
    if condition == "outside":
        frame = pd.concat([bars("2026-09-28", 1, "09:10"), frame])
    elif condition == "missing_close":
        closes = {}
    elif condition == "missing_bar":
        frame = frame.iloc[:-1]
    elif condition == "delayed":
        frame["available_at"] += pd.Timedelta(seconds=1)
    _, sessions = audit(frame, date(2026, 9, 28), date(2026, 9, 28), closes,
                        reviewed=condition != "unreviewed")
    assert sessions[0]["replay_eligible"] == (condition in {"eligible", "outside"})
    assert sessions[0]["replay_eligible"] == (sessions[0]["exclusion_reason"] is None)


def test_extra_bars_are_not_misreported_as_missing():
    frame = bars("2026-09-28", 77)
    report, sessions = audit(frame, date(2026, 9, 28), date(2026, 9, 28), {}, True)
    assert report["counts"] == {"REGULAR_COMPLETE_WITH_OUT_OF_SESSION_BARS": 1}
    assert report["days"][0]["missing"] == []
    assert len(report["days"][0]["unexpected"]) == 2
    assert not sessions[0]["replay_eligible"]


@pytest.mark.parametrize("times", [("09:10", "15:30"), ("15:35", "15:55")])
def test_outside_bars_retained_as_provenance_not_indicators(times):
    frame = pd.concat([bars("2026-09-28"), *[bars("2026-09-28", 1, t) for t in times]]).sort_index()
    closes = {date(2026, 9, 25): {"close": 99, "source_sha256": "a"}}
    report, sessions = audit(frame, date(2026, 9, 28), date(2026, 9, 28), closes, True)
    assert report["regular_grid_counts"] == {"before_boundary_filter": 0, "restored": 1, "after_boundary_filter": 1}
    assert report["replay_ready"] and sessions[0]["replay_eligible"]
    accepted, excluded = validate(frame, sessions)
    assert len(accepted[0][1]) == 75 and not excluded
    assert accepted[0][1].index.equals(bars("2026-09-28").index)
    assert len(sessions[0]["out_of_session_bars"]) == 2
    sessions[0]["out_of_session_bars"] = [frame.index[1].isoformat()]
    with pytest.raises(ValueError, match="classification"):
        validate(frame, sessions)


def test_inside_off_grid_bar_still_excluded_and_duplicates_rejected():
    frame = pd.concat([bars("2026-09-28"), bars("2026-09-28", 1, "15:29")]).sort_index()
    closes = {date(2026, 9, 25): {"close": 99, "source_sha256": "a"}}
    report, sessions = audit(frame, date(2026, 9, 28), date(2026, 9, 28), closes, True)
    assert not report["replay_ready"] and not sessions[0]["replay_eligible"]
    assert len(report["days"][0]["in_session_unexpected"]) == 1
    with pytest.raises(ValueError, match="UNIQUE"):
        audit(pd.concat([frame.iloc[:1], frame]).sort_index(), date(2026, 9, 28), date(2026, 9, 28), closes, True)


def test_daily_artifact_hash_and_duplicate_validation(tmp_path):
    rows = [["2026-09-25T00:00:00+05:30", 100, 102, 99, 101, 0, 0]]
    meta = dict(version=VERSION, key=KEY, start="2026-09-25", end="2026-09-25",
                unit="days", interval=1, row_count=1, rows_sha256=sha(encoded(rows)))
    path = tmp_path / "days-1-test.json.gz"
    content = gzip.compress(encoded({"metadata": meta, "candles": rows}))
    path.write_bytes(content)
    assert daily_closes(tmp_path)[date(2026, 9, 25)]["close"] == 101
    (tmp_path / "days-1-duplicate.json.gz").write_bytes(content)
    with pytest.raises(ValueError, match="DUPLICATE_DAILY_DATE"):
        daily_closes(tmp_path)
    (tmp_path / "days-1-duplicate.json.gz").unlink()
    rows[0][4] = 100
    path.write_bytes(gzip.compress(encoded({"metadata": meta, "candles": rows})))
    with pytest.raises(ValueError, match="DAILY_ARTIFACT_INVALID"):
        daily_closes(tmp_path)


def test_offline_cli_verified_sources_and_no_original_changes(tmp_path, capsys):
    day = "2026-09-28"
    frame = bars(day)
    rows = [[t.isoformat(), 100, 102, 99, 101, 0, 0] for t in frame.index]
    csv, parquet = export(rows)
    stem = tmp_path / f"nifty-five-minute-{day}-{day}"
    paths = {str(stem) + ".csv": csv, str(stem) + ".parquet": parquet,
        str(stem) + ".manifest.json": encoded({"csv_sha256": sha(csv),
            "parquet_sha256": sha(parquet), "row_count": 75})}
    daily = [["2026-09-25T00:00:00+05:30", 100, 102, 99, 101, 0, 0]]
    paths[str(tmp_path / "days-1-test.json.gz")] = gzip.compress(encoded({"metadata": {
        "version": VERSION, "key": KEY, "start": "2026-09-25", "end": "2026-09-25",
        "unit": "days", "interval": 1, "row_count": 1, "rows_sha256": sha(encoded(daily))}, "candles": daily}))
    from pathlib import Path
    for path, content in paths.items():
        Path(path).write_bytes(content)
    output = tmp_path / "ready"
    assert main(["--root", str(tmp_path), "--output", str(output), "--start", day,
                 "--end", day, "--calendar-reviewed"]) == 0
    assert json.loads((output / "quality.json").read_text())["replay_ready"]
    sessions = json.loads((output / "sessions.json").read_text())
    assert sessions[0]["replay_eligible"] and sessions[0]["exclusion_reason"] is None
    assert sessions[0]["previous_close_date"] == "2026-09-25"
    assert len(validate(frame, sessions)[0]) == 1
    for path, content in paths.items():
        assert Path(path).read_bytes() == content
    Path(str(stem) + ".csv").write_bytes(csv + b"tamper")
    with pytest.raises(ValueError, match="SOURCE_HASH_MISMATCH"):
        main(["--root", str(tmp_path), "--output", str(output), "--start", day, "--end", day])
    assert "replay_ready" in capsys.readouterr().out
