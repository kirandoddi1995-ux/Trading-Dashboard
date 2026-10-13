"""Offline capacity and quota parsing with no hosted accounts or secrets."""
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

import pytest

import overnight_operations_inputs as operations
from overnight_operations_alerts import OperationError

NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)


class FakeCursor:
    def __init__(self, row: Sequence[object] | None = (NOW, 394_000_000)) -> None:
        self.row = row
        self.queries: list[str] = []
        self.closed = False

    def execute(self, query: str) -> object:
        self.queries.append(query)
        return None

    def fetchone(self) -> Sequence[object] | None:
        return self.row

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self, row: Sequence[object] | None = (NOW, 394_000_000)) -> None:
        self.reader = FakeCursor(row)
        self.closed = False
        self.rolled_back = False

    def cursor(self) -> FakeCursor:
        return self.reader

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def test_capacity_readonly_all_databases() -> None:
    connection = FakeConnection()
    result = operations.measure_capacity(lambda: connection, clock=lambda: NOW)
    assert result.cluster_bytes == 394_000_000
    assert connection.reader.queries[0] == 'BEGIN READ ONLY'
    assert 'FROM pg_database' in connection.reader.queries[-1]
    assert connection.closed and connection.rolled_back and connection.reader.closed
    assert all('COMMIT' not in q for q in connection.reader.queries)


@pytest.mark.parametrize('row', [None, (NOW,), (NOW, True), (NOW, 0), (NOW, -1),
                                 (NOW, 2 ** 63), ('date', 1),
                                 (NOW.replace(tzinfo=None), 1), (NOW + timedelta(seconds=1), 1)])
def test_capacity_missing_invalid_redacted(row: Sequence[object] | None) -> None:
    connection = FakeConnection(row)
    with pytest.raises(OperationError, match='MEASUREMENT_UNAVAILABLE'):
        operations.measure_capacity(lambda: connection, clock=lambda: NOW)
    assert connection.closed and connection.rolled_back


def test_capacity_connect_failure_redacted() -> None:
    def connect() -> operations.Connection:
        raise RuntimeError('PRIVATE CONNECTION STRING')

    with pytest.raises(OperationError) as caught:
        operations.measure_capacity(connect, clock=lambda: NOW)
    assert 'PRIVATE' not in str(caught.value)


def test_quota_accountwide_and_unknown_limit() -> None:
    raw: dict[str, object] = {'storageQuota': {'limit': '15000000000', 'usage': '1000',
                                             'usageInDrive': '800', 'usageInDriveTrash': '100'}}
    parsed = operations.drive_quota(raw)
    assert parsed.available_bytes == 14_999_999_000 and not parsed.capacity_verified
    raw['storageQuota'] = {'usage': '1000', 'usageInDrive': '800', 'usageInDriveTrash': '100'}
    assert operations.drive_quota(raw).limit_bytes is None


@pytest.mark.parametrize('bad', [None, {}, {'usage': True},
    {'usage': '10', 'usageInDrive': '11', 'usageInDriveTrash': '0'},
    {'usage': '10', 'usageInDrive': '9', 'usageInDriveTrash': '10'},
    {'limit': '0', 'usage': '10', 'usageInDrive': '9', 'usageInDriveTrash': '0'},
    {'limit': str(2 ** 63), 'usage': '10', 'usageInDrive': '9', 'usageInDriveTrash': '0'},
    {'usage': '010', 'usageInDrive': '9', 'usageInDriveTrash': '0'}])
def test_quota_invalid(bad: object) -> None:
    with pytest.raises(OperationError):
        operations.drive_quota({'storageQuota': bad})


def test_prerequisites_never_infer_from_key_names() -> None:
    inventory = operations.Prerequisites(('current', 'old'), ('current',), False, False, False)
    assert operations.prerequisite_blockers(inventory) == ('ORIGINAL_KEY_CUSTODY_UNVERIFIED',
        'INDEPENDENT_ENCRYPTED_RESTORE_UNVERIFIED', 'DRIVE_CAPACITY_RETENTION_UNVERIFIED',
        'TRUSTED_CHECKPOINT_CUSTODY_UNVERIFIED')
    inventory = operations.Prerequisites(('current',), ('current',), True, True, True)
    assert operations.prerequisite_blockers(inventory) == ()  # inventory only, no deletion authority


@pytest.mark.parametrize('names', [('duplicate', 'duplicate'), ('bad/key',), ('',)])
def test_key_inventory_invalid(names: tuple[str, ...]) -> None:
    with pytest.raises(OperationError):
        operations.prerequisite_blockers(operations.Prerequisites(names, (), False, False, False))
