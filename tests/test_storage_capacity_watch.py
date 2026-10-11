"""Synthetic clock/capacity/deadline tests, no historical data or alert accounts."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

import storage_capacity_watch as watch

NOW = datetime(2026, 10, 8, 4, tzinfo=timezone.utc)
CURRENT = watch.Observation(NOW, 456_260_405)
PREVIOUS = watch.Observation(NOW - timedelta(hours=1), 456_000_000)
SCHEDULE = 'a' * 64
RUN = watch.ExpectedRun('synthetic_scan', 'b'*64, NOW-timedelta(minutes=2),
                        NOW+timedelta(minutes=1), None, None)


def evaluate(current: watch.Observation | None = CURRENT,
             previous: watch.Observation | None = PREVIOUS,
             runs: Any = ()) -> watch.WatchReport:
    return watch.evaluate(current, previous, runs, schedule_sha256=SCHEDULE, now=NOW)


def test_observed_ok_never_claims_authenticated_delivery_or_global_safety() -> None:
    result = evaluate()
    assert result['status'] == 'OBSERVED_OK' and result['alert_required'] is False
    assert result['nominal_headroom_bytes'] == 43_739_595
    assert result['observed_delta_bytes'] == 260_405
    assert result['positive_growth_bytes_per_day_ceiling'] == 6_249_720
    assert result['diagnostic_seconds_to_floor'] == (19_739_595 * 3600) // 260_405
    for name in ('alert_delivery_verified', 'authenticated_inputs_verified',
                 'all_writers_enforced', 'approval_authority'):
        assert result[name] is False


def test_empty_runs_require_explicit_schedule_identity_even_on_holiday() -> None:
    result = watch.evaluate(CURRENT, PREVIOUS, [], schedule_sha256=None, now=NOW)
    assert result['status'] == 'UNKNOWN' and result['alert_required'] is True
    assert result['reasons'] == ['SCHEDULE_INVENTORY_UNAVAILABLE']


def test_missing_snapshot_and_missing_trend_are_not_a_successful_poll() -> None:
    result = evaluate(None, None)
    assert result['status'] == 'UNKNOWN' and result['alert_required'] is True
    assert result['nominal_headroom_bytes'] is None
    result = evaluate(CURRENT, None)
    assert result['status'] == 'UNKNOWN' and result['diagnostic_seconds_to_floor'] is None


@pytest.mark.parametrize('age', [-1, 61])
def test_snapshot_stale_or_future_is_unknown_alarm(age: int) -> None:
    result = evaluate(replace(CURRENT, at=NOW-timedelta(seconds=age)))
    assert result['status'] == 'UNKNOWN' and result['alert_required']
    assert 'CAPACITY_MEASUREMENT_STALE_OR_FUTURE' in result['reasons']


def test_exact_freshness_boundary_and_ist_clock() -> None:
    current = replace(CURRENT, at=(NOW-timedelta(seconds=60)).astimezone(timezone(timedelta(hours=5, minutes=30))))
    assert evaluate(current)['status'] == 'OBSERVED_OK'


@pytest.mark.parametrize('interval', [0, -1, 86_401])
def test_bad_trend_window_is_unknown_not_unlimited_runway(interval: int) -> None:
    result = evaluate(previous=replace(PREVIOUS, at=NOW-timedelta(seconds=interval)))
    assert result['status'] == 'UNKNOWN' and result['diagnostic_seconds_to_floor'] is None


@pytest.mark.parametrize('before', [456_260_405, 470_000_000])
def test_flat_or_negative_growth_never_claims_infinite_future_capacity(before: int) -> None:
    result = evaluate(previous=replace(PREVIOUS, cluster_bytes=before))
    assert result['positive_growth_bytes_per_day_ceiling'] == 0
    assert result['diagnostic_seconds_to_floor'] is None
    assert result['nominal_headroom_bytes'] == 43_739_595


def test_subsecond_growth_ceil_does_not_round_to_zero() -> None:
    previous = watch.Observation(NOW-timedelta(microseconds=1), CURRENT.cluster_bytes-1)
    result = evaluate(previous=previous)
    assert result['positive_growth_bytes_per_day_ceiling'] == 86_400_000_000
    assert result['diagnostic_seconds_to_floor'] == 19
    assert result['status'] == 'ALARM'


@pytest.mark.parametrize('size', [476_000_001, 500_000_000, 500_000_001])
def test_actual_floor_breach_is_alarm_even_if_negative_growth(size: int) -> None:
    result = evaluate(watch.Observation(NOW, size), replace(PREVIOUS, cluster_bytes=size+1))
    assert result['status'] == 'ALARM' and result['alert_required'] is True
    assert 'CURRENT_ADMISSION_FLOOR_BREACHED' in result['reasons']


def test_warning_growth_is_diagnostic_not_write_authorisation() -> None:
    result = evaluate(previous=replace(PREVIOUS, cluster_bytes=450_000_000))
    assert result['status'] == 'ALARM'
    assert 'DIAGNOSTIC_GROWTH_APPROACHES_ADMISSION_FLOOR' in result['reasons']
    assert result['all_writers_enforced'] is False


def test_zero_append_runway_alerts_even_without_a_positive_trend() -> None:
    current = watch.Observation(NOW, 476_000_000)
    result = evaluate(current, replace(PREVIOUS, cluster_bytes=current.cluster_bytes))
    assert result['status'] == 'ALARM'
    assert result['reasons'] == ['BOUNDED_APPEND_RUNWAY_NOT_MET']


def test_missing_receipt_is_pending_at_exact_deadline_then_late() -> None:
    result = evaluate(runs=[replace(RUN, deadline=NOW)])
    assert result['pending_runs'] == 1 and result['unhealthy_runs'] == []
    result = evaluate(runs=[replace(RUN, deadline=NOW-timedelta(microseconds=1))])
    assert result['pending_runs'] == 0 and result['status'] == 'ALARM'
    assert result['unhealthy_runs'] == ['synthetic_scan:' + 'b'*64]


def test_successful_bound_receipt_and_future_pending_run() -> None:
    current = replace(RUN, receipt_at=NOW, successful=True)
    future = replace(RUN, run_id='c'*64, starts_at=NOW+timedelta(hours=1), deadline=NOW+timedelta(hours=2))
    result = evaluate(runs=[current, future])
    assert result['pending_runs'] == 1 and result['status'] == 'OBSERVED_OK'


def test_failed_receipt_alerts_before_deadline() -> None:
    result = evaluate(runs=[replace(RUN, receipt_at=NOW, successful=False)])
    assert result['status'] == 'ALARM' and result['reasons'] == ['EXPECTED_RUN_FAILED']


def test_late_successful_receipt_retains_lateness_alarm() -> None:
    result = evaluate(runs=[replace(RUN, deadline=NOW-timedelta(seconds=1), receipt_at=NOW, successful=True)])
    assert result['status'] == 'ALARM' and result['reasons'] == ['EXPECTED_RUN_RECEIPT_LATE']


def test_previous_day_receipt_cannot_satisfy_current_run() -> None:
    with pytest.raises(watch.WatchError, match='RECEIPT_TIME_INVALID'):
        evaluate(runs=[replace(RUN, receipt_at=NOW-timedelta(days=1), successful=True)])


@pytest.mark.parametrize('receipt,success', [(NOW, 'false'), (NOW, 1), (NOW, None), (None, True), (None, False)])
def test_receipt_boolean_and_timestamp_are_exact_not_truthy(receipt: Any, success: Any) -> None:
    with pytest.raises(watch.WatchError, match='RECEIPT_INVALID'):
        evaluate(runs=[replace(RUN, receipt_at=receipt, successful=success)])


def test_future_receipt_cannot_predict_success() -> None:
    with pytest.raises(watch.WatchError, match='RECEIPT_TIME_INVALID'):
        evaluate(runs=[replace(RUN, receipt_at=NOW+timedelta(seconds=1), successful=True)])


def test_duplicate_run_not_doubly_counted_and_different_runs_stay_distinct() -> None:
    with pytest.raises(watch.WatchError, match='DUPLICATE_RUN'):
        evaluate(runs=[RUN, RUN])
    result = evaluate(runs=[RUN, replace(RUN, run_id='c'*64)])
    assert result['pending_runs'] == 2


@pytest.mark.parametrize('size', [0, -1, True, 1.5, '455', None, 1 << 64])
def test_bad_size_is_unavailable_not_healthy(size: Any) -> None:
    with pytest.raises(watch.WatchError, match='SIZE_INVALID'):
        evaluate(replace(CURRENT, cluster_bytes=size))


@pytest.mark.parametrize('value', [0, -1, True, '172800', 30*86_400+1])
def test_bad_horizon_cannot_suppress_alerts(value: Any) -> None:
    with pytest.raises(watch.WatchError, match='HORIZON_INVALID'):
        watch.evaluate(CURRENT, PREVIOUS, (), schedule_sha256=SCHEDULE, now=NOW,
                       warning_horizon_seconds=value)


@pytest.mark.parametrize('value', ['A'*64, 'a'*63, 'secret/url', True])
def test_bad_schedule_identity(value: Any) -> None:
    with pytest.raises(watch.WatchError, match='SCHEDULE_IDENTITY_INVALID'):
        watch.evaluate(CURRENT, PREVIOUS, (), schedule_sha256=value, now=NOW)


def test_bad_run_identity_deadline_and_inventory() -> None:
    for run in (replace(RUN, producer='private/url'), replace(RUN, run_id='x'), None):
        with pytest.raises(watch.WatchError, match='RUN_IDENTITY_INVALID'):
            evaluate(runs=[run])
    with pytest.raises(watch.WatchError, match='DEADLINE_INVALID'):
        evaluate(runs=[replace(RUN, starts_at=NOW+timedelta(days=1))])
    inventory: Any
    for inventory in ({}, [RUN]*(watch.MAX_RUNS+1)):
        with pytest.raises(watch.WatchError, match='RUN_INVENTORY_INVALID'):
            evaluate(runs=inventory)


def test_naive_timestamp_and_wrong_observation_block() -> None:
    with pytest.raises(watch.WatchError, match='CLOCK_INVALID'):
        evaluate(replace(CURRENT, at=NOW.replace(tzinfo=None)))
    with pytest.raises(watch.WatchError, match='OBSERVATION_INVALID'):
        evaluate(current={})  # type: ignore[arg-type]


def test_report_is_stable_under_run_order_with_sorted_unhealthy_ids() -> None:
    first = replace(RUN, deadline=NOW-timedelta(seconds=1))
    second = replace(first, run_id='c'*64)
    assert evaluate(runs=[first, second]) == evaluate(runs=[second, first])
    failure = replace(second, receipt_at=NOW, successful=False)
    assert evaluate(runs=[first, failure]) == evaluate(runs=[failure, first])
