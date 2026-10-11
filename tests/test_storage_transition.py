"""Offline accounting and interval tests; no owner SQL or private inputs."""
from __future__ import annotations

from dataclasses import replace
import datetime as dt
from typing import Any

import pytest

import storage_transition as plan

NOW = dt.datetime(2026, 10, 8, 4, tzinfo=dt.timezone.utc)
CAPACITY = plan.Capacity(NOW, 456_260_405, 1_200_000_000, 0, 128_000_000)
CHECKS = plan.RetirementChecks(NOW, 0, 0, 'a'*64, 'b'*64, 'c'*64, 'd'*64)
OLD = plan.Partition('synthetic', 'quotes_day', NOW-dt.timedelta(days=4), NOW-dt.timedelta(days=3))


def test_remaining_margin_not_nominal_headroom() -> None:
    result = plan.capacity_plan(CAPACITY, plan.Allocation('shadow_copy', 19_739_595, 19_739_595), now=NOW)
    assert result['status'] == 'OFFLINE_CAPACITY_PLAN_FITS'
    assert result['projected_database_peak_bytes'] == 476_000_000
    assert result['hosted_write_authority'] is False and result['reservation_enforced'] is False
    blocked = plan.capacity_plan(CAPACITY, plan.Allocation('shadow_copy', 19_739_596, 19_739_596), now=NOW)
    assert 'DATABASE_PEAK_BREAKS_ADMISSION_MARGIN' in blocked['blockers']


def test_large_rewrite_does_not_credit_eventual_savings() -> None:
    result = plan.capacity_plan(CAPACITY, plan.Allocation('repack_quotes', 162_000_000, 162_000_000), now=NOW)
    assert result['status'] == 'OFFLINE_CAPACITY_PLAN_BLOCKED'
    assert result['projected_database_peak_bytes'] == 618_260_405


@pytest.mark.parametrize('age', [-1, 61])
def test_stale_or_future(age: int) -> None:
    result = plan.capacity_plan(replace(CAPACITY, at=NOW-dt.timedelta(seconds=age)),
                               plan.Allocation('copy', 0, 0), now=NOW)
    assert 'MEASUREMENT_STALE_OR_FUTURE' in result['blockers']


@pytest.mark.parametrize('database,disk', [(None, 1), (1, None), (None, None)])
def test_unknown_upper_bound(database: int | None, disk: int | None) -> None:
    result = plan.capacity_plan(CAPACITY, plan.Allocation('copy', database, disk), now=NOW)
    assert result['status'] == 'OFFLINE_CAPACITY_PLAN_BLOCKED'


@pytest.mark.parametrize('value', [-1, True, 1.0, '1', 1 << 64])
def test_bad_sizes(value: Any) -> None:
    with pytest.raises(plan.TransitionError):
        plan.capacity_plan(replace(CAPACITY, reserved_growth_bytes=value), plan.Allocation('copy', 0, 0), now=NOW)


def test_physical_disk_distinct_from_database_quota() -> None:
    result = plan.capacity_plan(replace(CAPACITY, physical_free_bytes=128_000_000),
                               plan.Allocation('copy', 1, 1), now=NOW)
    assert result['blockers'] == ['PHYSICAL_DISK_RESERVE_NOT_MET']
    with pytest.raises(plan.TransitionError, match='INCONSISTENT'):
        plan.capacity_plan(CAPACITY, plan.Allocation('copy', 2, 1), now=NOW)


def test_concurrent_reserved_growth_consumes_both_budgets() -> None:
    result = plan.capacity_plan(replace(CAPACITY, reserved_growth_bytes=20_000_000),
                               plan.Allocation('copy', 0, 0), now=NOW)
    assert 'DATABASE_PEAK_BREAKS_ADMISSION_MARGIN' in result['blockers']


def test_old_partition_requires_authentication_even_with_all_references() -> None:
    result = plan.retirement_plan(OLD, CHECKS, now=NOW, retain_from=OLD.upper)
    assert result['blockers'] == []
    assert result['status'] == 'RETIREMENT_REFERENCES_READY_FOR_AUTHENTICATION'
    assert result['proof_signatures_verified'] is False
    assert result['source_locked_and_rechecked'] is False
    assert result['hosted_write_authority'] is False
    assert result['approval_authority'] is False


@pytest.mark.parametrize('field', ['archive_receipt_sha256', 'second_copy_receipt_sha256',
    'restore_receipt_sha256', 'inventory_receipt_sha256', 'active_references', 'unresolved_delivery'])
def test_unknown_retirement_evidence(field: str) -> None:
    changes: dict[str, Any] = {field: None}
    result = plan.retirement_plan(OLD, replace(CHECKS, **changes), now=NOW, retain_from=OLD.upper)
    assert result['blockers']


@pytest.mark.parametrize('field', ['active_references', 'unresolved_delivery'])
def test_active_dependencies_override_age(field: str) -> None:
    changes: dict[str, Any] = {field: 1}
    result = plan.retirement_plan(OLD, replace(CHECKS, **changes), now=NOW, retain_from=OLD.upper)
    assert result['blockers']


def test_ist_half_open_boundary() -> None:
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    local = replace(OLD, lower=OLD.lower.astimezone(ist), upper=OLD.upper.astimezone(ist))
    assert plan.retirement_plan(local, CHECKS, now=NOW, retain_from=OLD.upper)['blockers'] == []
    result = plan.retirement_plan(local, CHECKS, now=NOW, retain_from=OLD.upper-dt.timedelta(microseconds=1))
    assert 'PARTITION_OVERLAPS_PROTECTED_INTERVAL' in result['blockers']


@pytest.mark.parametrize('damage', ['clock', 'identifier', 'reversed', 'future_cutoff', 'proof', 'stale'])
def test_retirement_invalid_or_stale(damage: str) -> None:
    part, checks, cutoff = OLD, CHECKS, OLD.upper
    if damage == 'clock':
        part = replace(part, upper=part.upper.replace(tzinfo=None))
    elif damage == 'identifier':
        part = replace(part, table='quotes;drop')
    elif damage == 'reversed':
        part = replace(part, upper=part.lower)
    elif damage == 'future_cutoff':
        cutoff = NOW+dt.timedelta(days=1)
    elif damage == 'proof':
        checks = replace(checks, restore_receipt_sha256='invalid')
    else:
        checks = replace(checks, at=NOW-dt.timedelta(seconds=61))
        assert plan.retirement_plan(part, checks, now=NOW, retain_from=cutoff)['blockers']
        return
    with pytest.raises(plan.TransitionError):
        plan.retirement_plan(part, checks, now=NOW, retain_from=cutoff)
