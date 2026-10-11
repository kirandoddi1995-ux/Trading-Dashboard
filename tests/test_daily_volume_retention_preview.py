"""Execute the exact preview SELECT in disposable PostgreSQL, never hosted SQL."""
from __future__ import annotations

from pathlib import Path
import os
import re
from typing import Any

import pytest

from test_archive_maintenance_sql import Pg

ROOT = Path(__file__).resolve().parents[1]


def query() -> str:
    """Return the reviewed file's exact marked SELECT, not a rewritten test query."""
    source = (ROOT / 'sql/daily_volume_retention_read_only.sql').read_text(encoding='utf-8')
    return source.split('-- BEGIN_VOLUME_INVENTORY\n', 1)[1].split('-- END_VOLUME_INVENTORY', 1)[0].strip()


@pytest.fixture
def volume_db() -> Any:
    if not os.environ.get('EQUITY_TEST_PGLITE_MODULE'):
        pytest.fail('Configure the existing offline SQL harness; do not skip retention checks')
    factory: Any = Pg  # Existing untyped harness; SQL itself is the reviewed input.
    db: Any = factory()
    try:
        db.send({'script': '''CREATE SCHEMA quant_app;
            CREATE SCHEMA fixture_clock;
            CREATE FUNCTION fixture_clock.transaction_timestamp() RETURNS timestamptz
                LANGUAGE sql IMMUTABLE AS $$ SELECT TIMESTAMPTZ '2026-10-08 04:00:00+00' $$;
            SET search_path=fixture_clock,pg_catalog;
            CREATE TABLE quant_app.market_daily_volumes (
                instrument_key text NOT NULL,trade_date date NOT NULL,
                max_captured_volume bigint,PRIMARY KEY(instrument_key,trade_date));
            INSERT INTO quant_app.market_daily_volumes
                SELECT 'long',(transaction_timestamp() AT TIME ZONE 'Asia/Kolkata')::date-n,100+n
                FROM generate_series(1,25) n;
            INSERT INTO quant_app.market_daily_volumes
                SELECT 'short',(transaction_timestamp() AT TIME ZONE 'Asia/Kolkata')::date-n,100+n
                FROM generate_series(1,3) n;
            INSERT INTO quant_app.market_daily_volumes VALUES
                ('long',(transaction_timestamp() AT TIME ZONE 'Asia/Kolkata')::date,100),
                ('long',(transaction_timestamp() AT TIME ZONE 'Asia/Kolkata')::date+1,100),
                ('long',(transaction_timestamp() AT TIME ZONE 'Asia/Kolkata')::date-30,NULL);
        '''})
        yield db
    finally:
        db.send({'close': True})
        db.process.stdin.close()
        db.process.wait(timeout=10)


def test_exact_preview_keeps_per_instrument_20_prior_dates(volume_db: Any) -> None:
    before = volume_db.execute('SELECT count(*) FROM quant_app.market_daily_volumes').fetchone()
    volume_db.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
    try:
        result = volume_db.execute(query()).fetchone()
        assert str(result[0])[:10] == '2026-10-08'
        assert result[1:4] == (31, 23, 5)
        assert result[4] > 0  # tuple estimate only, not shrink or migration bound
        assert result[5:] == (1, False, False, False)
    finally:
        volume_db.execute('ROLLBACK')
    assert volume_db.execute('SELECT count(*) FROM quant_app.market_daily_volumes').fetchone() == before


def test_sparse_dates_are_available_dates_not_calendar_days(volume_db: Any) -> None:
    volume_db.execute('''UPDATE quant_app.market_daily_volumes SET trade_date=trade_date-100
        WHERE instrument_key='short' ''')
    result = volume_db.execute(query()).fetchone()
    assert result[2:4] == (23, 5)  # short history still protects all three captured dates


def test_null_rows_stay_protected_in_this_preview(volume_db: Any) -> None:
    volume_db.execute('UPDATE quant_app.market_daily_volumes SET max_captured_volume=NULL')
    result = volume_db.execute(query()).fetchone()
    assert result[1:6] == (31, 0, 0, 0, 0)
    assert result[6:] == (False, False, False)


def test_empty_table_still_reports_explicit_false_authority(volume_db: Any) -> None:
    volume_db.execute('DELETE FROM quant_app.market_daily_volumes')
    result = volume_db.execute(query()).fetchone()
    assert result[1:6] == (0, 0, 0, 0, 0)
    assert result[6:] == (False, False, False)


@pytest.mark.parametrize('name', ['storage_layout_inventory_read_only.sql',
                                  'daily_volume_retention_read_only.sql'])
def test_owner_sql_has_only_read_only_statements(name: str) -> None:
    text = (ROOT / 'sql' / name).read_text(encoding='utf-8')
    text = re.sub(r'--[^\n]*', '', text)
    statements = [part.strip() for part in text.split(';') if part.strip()]
    assert statements and statements[-1] == 'ROLLBACK'
    for statement in statements:
        assert re.match(r'^(BEGIN\b|SET LOCAL\b|SELECT\b|WITH\b|ROLLBACK\b)', statement)
        assert not re.search(r'\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|GRANT|REVOKE|COPY|VACUUM)\b',
                             statement, re.IGNORECASE)
    assert all('READ ONLY' in statement for statement in statements if statement.startswith('BEGIN'))


def test_all_layout_selects_plan_in_disposable_postgres(volume_db: Any) -> None:
    text = (ROOT / 'sql/storage_layout_inventory_read_only.sql').read_text(encoding='utf-8')
    text = re.sub(r'--[^\n]*', '', text)
    selects = [part.strip() for part in text.split(';') if part.strip().startswith('SELECT')]
    assert len(selects) == 4
    for statement in selects:
        assert volume_db.execute('EXPLAIN ' + statement).fetchall()
