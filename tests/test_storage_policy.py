"""Offline steady-state allocation and storage-admission policy boundaries."""
import datetime as dt

import pytest

from storage_policy import (BUDGETS, CATALOG_ALLOWANCE_BYTES, CRITICAL_BYTES,
                            Measurement, PAUSE_BYTES, QUOTA_BYTES, WARNING_BYTES, assess)

NOW = dt.datetime(2026, 10, 6, tzinfo=dt.timezone.utc)


def sample(size=300_000_000, age=0, extra=None):
    remaining = max(0, size - CATALOG_ALLOWANCE_BYTES)
    relations = {}
    for budget in BUDGETS:
        allocation = min(remaining, budget.allocated_bytes)
        relations[budget.name] = allocation
        remaining -= allocation
    relations.update(extra or {})
    return Measurement(NOW-dt.timedelta(seconds=age), size, relations)


def test_all_hot_budgets_fit_target_and_derivatives_have_reserved_allocation():
    assert len(BUDGETS) == len({b.name for b in BUDGETS}) == 45
    assert sum(b.allocated_bytes for b in BUDGETS) + CATALOG_ALLOWANCE_BYTES < WARNING_BYTES
    assert sum(b.allocated_bytes for b in BUDGETS if b.name.startswith("derivatives_")) == 10_000_000
    assert all(b.retention and b.allocated_bytes > 0 for b in BUDGETS)


@pytest.mark.parametrize("size,state,allowed", [
    (WARNING_BYTES-1, "NORMAL", False), (WARNING_BYTES, "WARNING", False),
    (PAUSE_BYTES-1, "WARNING", False), (PAUSE_BYTES, "PAUSE", False),
    (CRITICAL_BYTES, "EMERGENCY", False), (QUOTA_BYTES, "EMERGENCY", False),
])
def test_thresholds_are_inclusive(size, state, allowed):
    result = assess(sample(size), NOW)
    assert result["state"] == state
    assert result["nonessential_writes_allowed"] is allowed
    assert result["critical_capacity_available"] is (size < QUOTA_BYTES)
    assert result["approval_authority"] is False


@pytest.mark.parametrize("age,allowed", [(60, True), (61, False), (-1, False)])
def test_clock_and_measurement_freshness(age, allowed):
    assert assess(sample(age=age), NOW)["nonessential_writes_allowed"] is allowed


def test_missing_inventory_unknown_table_and_partial_derivative_installation_block():
    assert not assess(Measurement(NOW, 300_000_000, {}), NOW)["nonessential_writes_allowed"]
    assert "UNBUDGETED_RELATION" in assess(sample(extra={"quant_app.unreviewed": 1}), NOW)["reasons"]
    assert "STORAGE_INVENTORY_INCOMPLETE" in assess(
        Measurement(NOW, 300_000_000, {"derivatives_monitor.state": 0}), NOW)["reasons"]


def test_other_cluster_allocation_is_bounded_even_below_global_warning():
    relations = {b.name: b.allocated_bytes for b in BUDGETS}
    total = sum(relations.values())
    allowed = assess(Measurement(NOW, total + CATALOG_ALLOWANCE_BYTES, relations), NOW)
    assert allowed["nonessential_writes_allowed"] is True
    assert allowed["other_cluster_bytes"] == CATALOG_ALLOWANCE_BYTES
    blocked = assess(Measurement(NOW, total + CATALOG_ALLOWANCE_BYTES + 1, relations), NOW)
    assert blocked["state"] == "NORMAL"
    assert blocked["nonessential_writes_allowed"] is False
    assert "OTHER_CLUSTER_BUDGET_EXCEEDED" in blocked["reasons"]


def test_table_budget_and_planned_allocation_guard():
    assert "TABLE_BUDGET_EXCEEDED" in assess(sample(
        extra={"quant_app.mf_nav": 5_000_001}), NOW)["reasons"]
    assert not assess(sample(PAUSE_BYTES-1), NOW, requested_bytes=1)["nonessential_writes_allowed"]


def test_growth_can_reduce_permission_never_increase_it():
    previous = Measurement(NOW-dt.timedelta(days=1), 290_000_000, {})
    assert assess(sample(), NOW, previous=previous)["growth_bytes_per_day"] == 10_000_000
    previous = Measurement(NOW-dt.timedelta(days=1), 200_000_000, {})
    assert "PROJECTED_RESERVE_EXHAUSTION" in assess(sample(360_000_000), NOW, previous=previous)["reasons"]
    previous = Measurement(NOW-dt.timedelta(days=1), 490_000_000, {})
    assert not assess(sample(410_000_000), NOW, previous=previous)["nonessential_writes_allowed"]


@pytest.mark.parametrize("bad", [True, 0, -1, 1.5])
def test_invalid_cluster_measurement_is_not_a_zero_default(bad):
    with pytest.raises(ValueError, match="STORAGE_MEASUREMENT_INVALID"):
        assess(sample(bad), NOW)


def test_naive_time_and_inconsistent_allocation_fail():
    with pytest.raises(ValueError, match="STORAGE_CLOCK_UNVERIFIED"):
        assess(sample(), NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="STORAGE_MEASUREMENT_INVALID"):
        assess(sample(extra={"quant_app.mf_nav": 500_000_000}), NOW)
    with pytest.raises(ValueError, match="STORAGE_TREND_INVALID"):
        assess(sample(), NOW, previous=sample())

