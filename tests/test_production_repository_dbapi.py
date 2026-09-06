from decimal import Decimal
import datetime as dt

import pytest

from production_repository import (
    _connection_error_code,
    _executemany,
    _finite_decimal,
    _safe_database_url_shape,
    _strict_utc_datetime,
)


class _Cursor:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def executemany(self, statement, rows):
        self.calls.append((statement, list(rows)))


class _Connection:
    def __init__(self):
        self.db_cursor = _Cursor()

    def cursor(self):
        return self.db_cursor


def test_executemany_uses_psycopg_cursor_api():
    conn = _Connection()

    _executemany(conn, "INSERT INTO sample VALUES (%s)", [(1,), (2,)])

    assert conn.db_cursor.calls == [
        ("INSERT INTO sample VALUES (%s)", [(1,), (2,)])
    ]


def test_finite_decimal_preserves_valid_values_and_rejects_non_finite_values():
    assert _finite_decimal("123.45") == Decimal("123.45")
    assert _finite_decimal("NaN") is None
    assert _finite_decimal("Infinity") is None
    assert _finite_decimal(None) is None


def test_database_url_shape_reports_structure_without_exposing_password():
    url = "postgresql://quant_app_runtime.projectref:Secret123@pooler.example.com:5432/postgres"

    shape = _safe_database_url_shape(url)

    assert shape == {
        "parseable": True,
        "scheme_valid": True,
        "has_whitespace": False,
        "has_surrounding_quotes": False,
        "scheme": "postgresql",
        "username": "quant_app_runtime.projectref",
        "host": "pooler.example.com",
        "port": 5432,
        "database": "postgres",
        "password_present": True,
        "password_length": 9,
        "password_alphanumeric": True,
    }
    assert "Secret123" not in repr(shape)


def test_database_connection_errors_are_safely_classified():
    assert _connection_error_code(Exception("password authentication failed for user")) == "AUTHENTICATION_FAILED"
    assert _connection_error_code(Exception("FATAL: Tenant or user not found")) == "POOLER_IDENTITY_NOT_FOUND"
    assert _connection_error_code(Exception("circuit breaker open")) == "POOLER_CIRCUIT_BREAKER"
    assert _connection_error_code(Exception("connection timed out")) == "CONNECTION_TIMEOUT"
    assert _connection_error_code(Exception("unexpected provider text")) == "OPERATIONAL_ERROR"


def test_training_readiness_timestamp_parser_rejects_naive_values():
    with pytest.raises(ValueError, match="timezone-aware"):
        _strict_utc_datetime("2026-09-06T10:00:00", "decision_at")
    assert _strict_utc_datetime(
        "2026-09-06T15:30:00+05:30", "decision_at",
    ) == dt.datetime(2026, 9, 6, 10, 0, tzinfo=dt.timezone.utc)
