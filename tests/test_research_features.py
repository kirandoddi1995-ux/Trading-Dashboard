import datetime as dt

import numpy as np
import pandas as pd
import pytest

from research_features import (
    calendar_distance_features, cross_sectional_features, lead_lag_features,
    order_book_features, parse_official_calendar, secondary_quote_features,
)


UTC = dt.timezone.utc


def test_order_book_features_reject_crossed_or_non_finite_depth():
    good = order_book_features(
        [{"price": 99, "quantity": 20}], [{"price": 101, "quantity": 10}],
    )
    assert good["order_book_imbalance_d5"] == pytest.approx(1 / 3)
    assert 99 < good["microprice_d5"] < 101
    with pytest.raises(ValueError, match="crossed"):
        order_book_features(
            [{"price": 102, "quantity": 20}], [{"price": 101, "quantity": 10}],
        )
    with pytest.raises(ValueError, match="finite"):
        order_book_features(
            [{"price": 99, "quantity": np.nan}], [{"price": 101, "quantity": 10}],
        )
    assert secondary_quote_features(bid=99, ask=101)["secondary_quote_spread_bps"] > 0
    with pytest.raises(ValueError, match="crossed"):
        secondary_quote_features(bid=102, ask=101)


def test_cross_sectional_features_are_snapshot_only_and_reject_future_availability():
    now = dt.datetime(2026, 9, 7, 5, tzinfo=UTC)
    frame = pd.DataFrame({
        "instrument_key": ["a", "b", "c"],
        "effective_at": [now - dt.timedelta(minutes=1)] * 3,
        "available_at": [now] * 3,
        "return_1d": [-0.01, 0.0, 0.02],
    })
    result = cross_sectional_features(frame, snapshot_at=now)
    assert result.loc[result.instrument_key == "c", "cross_sectional_return_rank"].iloc[0] == 1
    assert result.attrs == {"pit_verified": True, "consumed_by_scoring": False}
    frame.loc[0, "available_at"] = now + dt.timedelta(seconds=1)
    with pytest.raises(ValueError, match="future"):
        cross_sectional_features(frame, snapshot_at=now)


def test_lead_lag_uses_only_previous_completed_leader_interval():
    start = dt.datetime(2026, 9, 7, 4, tzinfo=UTC)
    rows = []
    for index in range(8):
        timestamp = start + dt.timedelta(minutes=index)
        rows.extend([
            {"instrument_key": "leader", "interval_end": timestamp,
             "available_at": timestamp, "return": index / 100},
            {"instrument_key": "target", "interval_end": timestamp,
             "available_at": timestamp, "return": max(index - 1, 0) / 100},
        ])
    result = lead_lag_features(pd.DataFrame(rows), leader="leader", targets=["target"], window=5)
    assert not result.empty
    last = result.iloc[-1]
    assert last["leader_return_lag_1"] == pytest.approx(0.06)
    assert last["feature_at"] == start + dt.timedelta(minutes=7)
    assert result.attrs["consumed_by_scoring"] is False


def test_calendar_distance_ignores_events_not_known_at_decision_time():
    decision = dt.datetime(2026, 9, 7, 6, tzinfo=UTC)
    events = parse_official_calendar([
        {"event_id": "rbi-known", "category": "RBI_POLICY",
         "event_at": decision + dt.timedelta(days=2),
         "published_at": decision - dt.timedelta(days=5),
         "available_at": decision - dt.timedelta(days=5), "source": "RBI"},
        {"event_id": "budget-late", "category": "UNION_BUDGET",
         "event_at": decision + dt.timedelta(days=3),
         "published_at": decision + dt.timedelta(days=1),
         "available_at": decision + dt.timedelta(days=1), "source": "India Budget"},
    ], collected_at=decision + dt.timedelta(days=1))
    result = calendar_distance_features(decision, events)
    assert result["RBI_POLICY"]["minutes_to_known_event"] == 2 * 24 * 60
    assert result["UNION_BUDGET"]["minutes_to_known_event"] is None
