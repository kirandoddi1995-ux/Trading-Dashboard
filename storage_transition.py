"""Offline physical-capacity and partition-retirement plans, never write authority.

No SQL execution, credentials, extension install, runtime policy or quota change.
Inputs are reviewed upper bounds, not pg_column_size estimates or expected savings.
Reservations are accounting inputs only; all-writer enforcement is a later gate.
"""
from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import re
from typing import TypedDict

QUOTA = 500_000_000
ADMISSION_FLOOR = 24_000_000
MAX_AGE = dt.timedelta(seconds=60)


class TransitionError(ValueError):
    """Invalid measurements/bounds block, never coerce unknown data to zero."""


def _bytes(value: object, *, positive: bool = False) -> int:
    if type(value) is not int or value < int(positive) or value > (1 << 63) - 1:
        raise TransitionError('TRANSITION_SIZE_INVALID')
    return value


def _instant(value: dt.datetime) -> dt.datetime:
    if type(value) is not dt.datetime or value.tzinfo is None or value.utcoffset() is None:
        raise TransitionError('TRANSITION_CLOCK_INVALID')
    return value.astimezone(dt.timezone.utc)


def _name(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch('[a-z][a-z0-9_]{0,62}', value):
        raise TransitionError('TRANSITION_IDENTIFIER_INVALID')
    return value


@dataclass(frozen=True)
class Capacity:
    """Fresh cluster quota AND physical free disk; WAL lives on physical disk."""
    at: dt.datetime
    cluster_bytes: int
    physical_free_bytes: int
    reserved_growth_bytes: int
    physical_reserve_bytes: int


@dataclass(frozen=True)
class Allocation:
    """Reviewed transient upper bounds, inclusive of indexes/TOAST/scratch/WAL.

    additional_database_bytes counts NEW transient allocation while old files
    remain. additional_disk_bytes includes that allocation plus scratch/WAL.
    No future reclaimed bytes offset a peak. None means unverified, not zero.
    """
    operation: str
    additional_database_bytes: int | None
    additional_disk_bytes: int | None


class CapacityPlan(TypedDict):
    """Typed offline result; successful arithmetic is not a reservation."""
    status: str
    blockers: list[str]
    projected_database_peak_bytes: int | None
    projected_physical_remaining_bytes: int | None
    required_database_headroom_bytes: int
    reservation_enforced: bool
    hosted_write_authority: bool
    approval_authority: bool


def capacity_plan(capacity: Capacity, allocation: Allocation, *, now: dt.datetime) -> CapacityPlan:
    """Review feasibility while preserving the CURRENT 24 MB admission margin.

    This does not reserve space or account for an uncoordinated concurrent writer.
    No result permits compaction, partition conversion or any hosted write.
    """
    _name(allocation.operation)
    age = _instant(now) - _instant(capacity.at)
    cluster = _bytes(capacity.cluster_bytes, positive=True)
    free = _bytes(capacity.physical_free_bytes)
    growth = _bytes(capacity.reserved_growth_bytes)
    reserve = _bytes(capacity.physical_reserve_bytes)
    reasons: list[str] = []
    if not dt.timedelta(0) <= age <= MAX_AGE:
        reasons.append('MEASUREMENT_STALE_OR_FUTURE')
    database_peak: int | None = None
    disk_remaining: int | None = None
    if allocation.additional_database_bytes is None or allocation.additional_disk_bytes is None:
        reasons.append('TRANSIENT_UPPER_BOUND_UNVERIFIED')
    else:
        extra_database = _bytes(allocation.additional_database_bytes)
        extra_disk = _bytes(allocation.additional_disk_bytes)
        if extra_disk < extra_database:
            raise TransitionError('TRANSITION_DISK_BOUND_INCONSISTENT')
        database_peak = cluster + growth + extra_database
        disk_remaining = free - growth - reserve - extra_disk
        if database_peak > QUOTA - ADMISSION_FLOOR:
            reasons.append('DATABASE_PEAK_BREAKS_ADMISSION_MARGIN')
        if disk_remaining < 0:
            reasons.append('PHYSICAL_DISK_RESERVE_NOT_MET')
    return {'status': 'OFFLINE_CAPACITY_PLAN_BLOCKED' if reasons else 'OFFLINE_CAPACITY_PLAN_FITS',
            'blockers': reasons, 'projected_database_peak_bytes': database_peak,
            'projected_physical_remaining_bytes': disk_remaining,
            'required_database_headroom_bytes': ADMISSION_FLOOR,
            'reservation_enforced': False, 'hosted_write_authority': False,
            'approval_authority': False}


@dataclass(frozen=True)
class Partition:
    """Half-open UTC-aware interval; never infer bounds from filenames."""
    schema: str
    table: str
    lower: dt.datetime
    upper: dt.datetime


@dataclass(frozen=True)
class RetirementChecks:
    """Fresh observed blockers and reviewed proof references, not signed proof.

    Hashes only locate independently authenticated receipts. These references
    alone cannot prove replica independence, licensing, source identity or restore.
    Unknown references/counts fail closed. Parent constraints/reader wiring must
    be reviewed separately before using any owner-run partition SQL.
    """
    at: dt.datetime
    active_references: int | None
    unresolved_delivery: int | None
    archive_receipt_sha256: str | None
    second_copy_receipt_sha256: str | None
    restore_receipt_sha256: str | None
    inventory_receipt_sha256: str | None


class RetirementPlan(TypedDict):
    """Typed prerequisite references; signatures/locks remain unverified."""
    status: str
    blockers: list[str]
    proof_signatures_verified: bool
    source_locked_and_rechecked: bool
    hosted_write_authority: bool
    approval_authority: bool


def retirement_plan(partition: Partition, checks: RetirementChecks, *,
                    now: dt.datetime, retain_from: dt.datetime) -> RetirementPlan:
    """List prerequisites for a sealed old interval; NEVER generate DROP/DELETE.

    A partition straddling retain_from stays hot. Equality is eligible because
    PostgreSQL range upper bounds are exclusive. Special sessions/holidays do
    not change interval math; dependency retention still overrides its age.
    """
    _name(partition.schema)
    _name(partition.table)
    lower, upper = _instant(partition.lower), _instant(partition.upper)
    current, retained = _instant(now), _instant(retain_from)
    if lower >= upper or retained > current:
        raise TransitionError('TRANSITION_INTERVAL_INVALID')
    reasons: list[str] = []
    if not dt.timedelta(0) <= current - _instant(checks.at) <= MAX_AGE:
        reasons.append('RETIREMENT_MEASUREMENT_STALE_OR_FUTURE')
    if upper > retained or upper > current:
        reasons.append('PARTITION_OVERLAPS_PROTECTED_INTERVAL')
    for name, value in (('ACTIVE_REFERENCES', checks.active_references),
                        ('UNRESOLVED_DELIVERY', checks.unresolved_delivery)):
        if value is None:
            reasons.append(name + '_UNKNOWN')
        elif _bytes(value) > 0:
            reasons.append(name + '_PRESENT')
    for name, proof in (('ARCHIVE', checks.archive_receipt_sha256),
                        ('SECOND_COPY', checks.second_copy_receipt_sha256),
                        ('RESTORE', checks.restore_receipt_sha256),
                        ('INVENTORY', checks.inventory_receipt_sha256)):
        if proof is None:
            reasons.append(name + '_PROOF_MISSING')
        elif not isinstance(proof, str) or not re.fullmatch('[0-9a-f]{64}', proof):
            raise TransitionError('TRANSITION_PROOF_REFERENCE_INVALID')
    return {'status': 'RETIREMENT_PREREQUISITES_MISSING' if reasons else 'RETIREMENT_REFERENCES_READY_FOR_AUTHENTICATION',
            'blockers': reasons, 'proof_signatures_verified': False,
            'source_locked_and_rechecked': False, 'hosted_write_authority': False,
            'approval_authority': False}
