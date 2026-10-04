import pandas as pd
import pytest

import app_runtime as runtime
from equity_research_collector import summarize_outcomes


@pytest.mark.parametrize('stamp,expected', [("2026-10-01T10:00:00+05:30", 4),
    ("2026-09-30T15:29:00+05:30", 1), (None, 1)])
def test_volume_date_guard(stamp, expected):
    assert runtime.volume_pace(1, stamp, '2026-10-01T10:15:00+05:30', .25, True) == expected


def test_daily_excludes_developing_day_even_after_close():
    frame = pd.DataFrame({'Close': [100, 999]}, index=pd.to_datetime(['2026-09-30', '2026-10-01']))
    assert runtime.completed_daily_bars(frame, '2026-10-01T18:00:00+05:30').Close.tolist() == [100]


@pytest.mark.parametrize('stamp,expected', [('2026-10-01T10:00:00+05:30', 4),
    ('2026-09-30T15:29:00+05:30', 1), (None, 1)])
def test_actual_stage1_volume_wiring(stamp, expected):
    from scanner_funnel import stage1_prefilter
    quote = {'last_price': 100, 'ohlc': {'close': 99, 'high': 101, 'low': 98},
             'volume': 100, 'timestamp': stamp}
    _, report = stage1_prefilter(['TEST'], {'TEST': 'K'}, {'K': quote}, 1,
        average_volumes={'K': 100}, elapsed_fraction=.25, as_of='2026-10-01T10:15:00+05:30')
    assert report['_evidence'][0]['features']['volume_pace_ratio'] == expected


def test_intraday_completed_boundary():
    frame = pd.DataFrame({'Close': [1, 2, 3]}, index=pd.date_range('2026-10-01 10:00', periods=3, freq='5min', tz='Asia/Kolkata'))
    assert runtime.completed_intraday_bars(frame, 5, '2026-10-01T10:07:00+05:30').Close.tolist() == [1]


def test_summary_unknown_does_not_become_no_touch():
    rows = [{'horizon_complete': True, 'coverage_complete': False, 'target_touched': None, 'stop_touched': None},
            {'horizon_complete': True, 'coverage_complete': True, 'target_touched': False, 'stop_touched': False},
            {'horizon_complete': False, 'coverage_complete': True, 'target_touched': True, 'first_observed_touch': 'TARGET'}]
    result = summarize_outcomes(rows)
    assert result['horizons_complete'] == 2
    assert result['completed_horizon_coverage_incomplete'] == 1
    assert result['target'] == {'touched': 1, 'not_touched': 1, 'unknown': 1}
    assert result['first_touch']['UNKNOWN'] == 1
    assert result['first_touch']['NO_TOUCH_CONFIRMED'] == 1
    assert summarize_outcomes([])['outcomes'] == 0
