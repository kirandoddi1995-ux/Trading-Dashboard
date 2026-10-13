"""Read-only capacity/quota adapters and honest owner-prerequisite inventory.

Callers inject a reviewed connection/HTTP adapter explicitly. This module never
reads secrets, connects automatically, installs extensions or mutates hosted data.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Protocol

from overnight_operations_alerts import OperationError, instant
from storage_capacity_watch import Observation


class Cursor(Protocol):
    """Minimal DB-API boundary, usable with deterministic offline fakes."""
    def execute(self, query: str) -> object: ...
    def fetchone(self) -> Sequence[object] | None: ...
    def close(self) -> None: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


def measure_capacity(connect: Callable[[], Connection], *, clock: Callable[[], datetime]) -> Observation:
    """One short read-only transaction; count all databases, not only current DB.

    Deployment must commission verify-full TLS, restricted role and independent
    watcher provenance. Local validation alone does not authenticate the server.
    Failed or skewed measurements remain UNKNOWN to the alert evaluator.
    """
    start = instant(clock())
    connection: Connection | None = None
    cursor: Cursor | None = None
    try:
        connection = connect()
        cursor = connection.cursor()
        cursor.execute('BEGIN READ ONLY')
        cursor.execute("SET LOCAL statement_timeout = '5s'")
        cursor.execute("SET LOCAL lock_timeout = '1s'")
        cursor.execute('SELECT clock_timestamp(), sum(pg_database_size(oid))::bigint FROM pg_database')
        row = cursor.fetchone()
        end = instant(clock())
        if (row is None or len(row) != 2 or type(row[0]) is not datetime
                or type(row[1]) is not int or not 0 < row[1] <= (1 << 63) - 1):
            raise ValueError
        at = instant(row[0])
        if not start <= at <= end or not 0 <= (end - start).total_seconds() <= 10:
            raise ValueError
        return Observation(at, row[1])
    except Exception:
        raise OperationError('CAPACITY_MEASUREMENT_UNAVAILABLE') from None
    finally:
        # Closing does not turn an unknown reading into success; never commit.
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                pass
            try:
                connection.close()
            except Exception:
                pass


@dataclass(frozen=True)
class DriveQuota:
    """Account-wide bytes, including non-Drive services; no guessed free-plan limit."""
    limit_bytes: int | None
    usage_bytes: int
    drive_bytes: int
    trash_bytes: int
    available_bytes: int | None
    capacity_verified: bool = False


def drive_quota(reply: Mapping[str, object]) -> DriveQuota:
    """Parse only official about.storageQuota string-int64 fields; fail on ambiguity.

    Absent limit means UNKNOWN here, not an assumed free 15 GB allowance. Pooled
    organisation quota and other Google services can consume the account limit.
    Provider response authenticity and a retention policy require commissioning.
    """
    quota = reply.get('storageQuota')
    if not isinstance(quota, Mapping):
        raise OperationError('DRIVE_QUOTA_UNAVAILABLE')

    def amount(name: str) -> int:
        value = quota.get(name)
        if type(value) is not str or re.fullmatch('0|[1-9][0-9]{0,18}', value) is None:
            raise OperationError('DRIVE_QUOTA_INVALID')
        number = int(value)
        if number > (1 << 63) - 1:
            raise OperationError('DRIVE_QUOTA_INVALID')
        return number

    usage, drive, trash = amount('usage'), amount('usageInDrive'), amount('usageInDriveTrash')
    limit = amount('limit') if 'limit' in quota else None
    if trash > drive or drive > usage or (limit is not None and limit == 0):
        raise OperationError('DRIVE_QUOTA_INCONSISTENT')
    return DriveQuota(limit, usage, drive, trash, None if limit is None else max(0, limit - usage))


@dataclass(frozen=True)
class Prerequisites:
    """Names/status only: do not inspect key material or infer custody from filenames."""
    required_key_ids: tuple[str, ...]
    independently_verified_key_ids: tuple[str, ...]
    encrypted_disk_restore_verified: bool
    drive_capacity_retention_verified: bool
    trusted_checkpoint_custody_verified: bool


def prerequisite_blockers(inventory: Prerequisites) -> tuple[str, ...]:
    """Owner evidence inventory, NOT an authority that permits deletion or releases."""
    for names in (inventory.required_key_ids, inventory.independently_verified_key_ids):
        if (type(names) is not tuple or len(names) > 1024 or len(names) != len(set(names))
                or any(type(name) is not str or re.fullmatch('[A-Za-z0-9_-]{1,64}', name) is None for name in names)):
            raise OperationError('KEY_INVENTORY_INVALID')
    flags = (inventory.encrypted_disk_restore_verified, inventory.drive_capacity_retention_verified,
             inventory.trusted_checkpoint_custody_verified)
    if any(type(flag) is not bool for flag in flags):
        raise OperationError('PREREQUISITE_STATUS_INVALID')
    blockers: list[str] = []
    if not inventory.required_key_ids:
        blockers.append('ORIGINAL_KEY_INVENTORY_UNAVAILABLE')
    elif set(inventory.required_key_ids) - set(inventory.independently_verified_key_ids):
        blockers.append('ORIGINAL_KEY_CUSTODY_UNVERIFIED')
    if not flags[0]:
        blockers.append('INDEPENDENT_ENCRYPTED_RESTORE_UNVERIFIED')
    if not flags[1]:
        blockers.append('DRIVE_CAPACITY_RETENTION_UNVERIFIED')
    if not flags[2]:
        blockers.append('TRUSTED_CHECKPOINT_CUSTODY_UNVERIFIED')
    return tuple(blockers)
