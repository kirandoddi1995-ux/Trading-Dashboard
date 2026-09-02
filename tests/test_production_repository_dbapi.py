from decimal import Decimal

from production_repository import _executemany, _finite_decimal


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

