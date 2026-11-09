"""Universe and quote writer SQL in a disposable engine; no hosted data or secrets."""
import ast
import hashlib
import json
from contextlib import contextmanager
import datetime as dt
import os
from pathlib import Path

import pytest

from drive_archive import SPECS
from production_repository import ProductionRepository
from test_archive_maintenance_sql import Pg

pytestmark = pytest.mark.skipif(not os.environ.get('EQUITY_TEST_PGLITE_MODULE'), reason='SQL engine not configured')


@pytest.fixture
def repository(monkeypatch):
    monkeypatch.setattr('production_repository._utcnow', lambda: dt.datetime(2026, 10, 5, tzinfo=dt.timezone.utc))
    db = Pg()
    db.send({'script': '''CREATE SCHEMA quant_app;
      CREATE TABLE quant_app.universe_snapshots(snapshot_date date PRIMARY KEY,
      observed_at timestamptz,source text,instrument_count integer,payload_hash text,
      is_complete boolean,schema_version integer);
      CREATE TABLE quant_app.universe_snapshot_versions(snapshot_id text PRIMARY KEY,
      snapshot_date date,observed_at timestamptz,source text,instrument_count integer,
      payload_hash text,is_complete boolean,schema_version integer);'''})
    for table, key in [('universe_membership','snapshot_date'), ('universe_membership_versions','snapshot_id')]:
        columns = ','.join(f'{name} {kind}' for name, kind in SPECS[table].items())
        db.execute(f'CREATE TABLE quant_app.{table} ({columns}, PRIMARY KEY({key},instrument_key))')
    repo = ProductionRepository('')
    repo.ensure_schema = lambda: None
    @contextmanager
    def connect():
        class Connection:
            def execute(self, sql, params=()):
                return db.execute(sql, tuple(json.dumps(p.obj) if hasattr(p, 'obj') else p for p in params))
            def cursor(self):
                return self
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def executemany(self, sql, rows):
                for row in rows:
                    self.execute(sql, row)
            def commit(self):
                pass
        with db.connect():
            yield Connection()
    repo.connect = connect
    try:
        yield repo, db
    finally:
        db.send({'close': True})
        db.process.stdin.close()
        db.process.wait(timeout=10)


def records(count=2):
    return [{'instrument_key': f'NSE_EQ|{i}', 'trading_symbol': f'S{i}', 'name': 'fixture'} for i in range(count)]


def test_compact_quote_retains_typed_fields_and_daily_volume(repository):
    repo, db = repository
    columns = ','.join(f'{name} {kind}' for name, kind in SPECS['market_quotes'].items())
    db.execute(f'CREATE TABLE quant_app.market_quotes ({columns}, PRIMARY KEY(instrument_key,observed_at))')
    db.execute("""CREATE TABLE quant_app.market_daily_volumes(
        instrument_key text, trade_date date, max_captured_volume numeric,
        PRIMARY KEY(instrument_key,trade_date))""")
    migration = (Path(__file__).resolve().parents[1] / 'sql/drive_archive_draft.sql').read_text()
    function = migration[migration.index('CREATE OR REPLACE FUNCTION quant_app.capture_daily_volume()'):
                         migration.index('REVOKE ALL ON FUNCTION quant_app.capture_daily_volume()')]
    trigger = migration[migration.index('CREATE TRIGGER quote_daily_volume_insert'):
                        migration.index('\n\nINSERT INTO quant_app.market_daily_volumes')]
    db.send({'script': function + trigger})
    observed = dt.datetime(2026, 10, 5, 9, tzinfo=dt.timezone.utc)
    quote = {'instrument_key': 'NSE_EQ|1', 'last_price': 11, 'volume': 20, 'oi': 2,
             'ohlc': {'open': 9, 'high': 12, 'low': 8, 'close': 10},
             'unread_payload': 'x' * 2000}
    assert repo.archive_quotes([quote], observed_at=observed) == 1
    assert repo.archive_quotes([dict(quote, volume=30)], observed_at=observed + dt.timedelta(hours=1)) == 1
    assert db.execute("""SELECT last_price,open,high,low,previous_close,volume,open_interest,
        raw->>'retention' AS retention, raw ? 'unread_payload' AS has_payload
        FROM quant_app.market_quotes ORDER BY observed_at LIMIT 1""").fetchone() == (
        '11', '9', '12', '8', '10', '20', '2', 'typed_only_v1', False)
    assert db.execute('SELECT max_captured_volume FROM quant_app.market_daily_volumes').fetchone()[0] == '30'


def test_quote_zero_volume_is_stored_not_overwritten_by_ohlc(repository):
    # A real 0 (no trades this tick) must be stored as 0, not fall through to ohlc.volume.
    repo, db = repository
    columns = ','.join(f'{name} {kind}' for name, kind in SPECS['market_quotes'].items())
    db.execute(f'CREATE TABLE quant_app.market_quotes ({columns}, PRIMARY KEY(instrument_key,observed_at))')
    observed = dt.datetime(2026, 10, 5, 9, tzinfo=dt.timezone.utc)
    quote = {'instrument_key': 'NSE_EQ|1', 'last_price': 11, 'volume': 0,
             'ohlc': {'open': 9, 'high': 12, 'low': 8, 'close': 10, 'volume': 999}}
    assert repo.archive_quotes([quote], observed_at=observed) == 1
    assert db.execute(
        "SELECT volume FROM quant_app.market_quotes WHERE instrument_key='NSE_EQ|1'"
    ).fetchone()[0] == '0'


def test_repeat_is_storage_noop_preserves_receipt(repository, monkeypatch):
    repo, db = repository
    first = repo.archive_universe(records(), '2026-10-05', minimum_complete=2)
    monkeypatch.setattr('production_repository._utcnow', lambda: dt.datetime(2026, 10, 5, 1, tzinfo=dt.timezone.utc))
    before = db.execute('SELECT to_jsonb(s) FROM quant_app.universe_snapshots s').fetchall()
    # A trigger proves the writer does not attempt canonical UPDATE/DELETE/INSERT.
    db.send({'script': '''CREATE FUNCTION quant_app.reject_write() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Unexpected unchanged write'; END $$;
    CREATE TRIGGER block_header BEFORE UPDATE ON quant_app.universe_snapshots FOR EACH ROW EXECUTE FUNCTION quant_app.reject_write();
    CREATE TRIGGER block_members BEFORE INSERT OR DELETE ON quant_app.universe_membership FOR EACH ROW EXECUTE FUNCTION quant_app.reject_write();
    CREATE TRIGGER block_versions BEFORE INSERT ON quant_app.universe_membership_versions FOR EACH ROW EXECUTE FUNCTION quant_app.reject_write();'''})
    repeated = repo.archive_universe(list(reversed(records())), '2026-10-05', minimum_complete=2)
    assert not repeated['canonical_changed'] and not repeated['version_created']
    assert repeated['observed_at'] == first['observed_at']
    assert db.execute('SELECT to_jsonb(s) FROM quant_app.universe_snapshots s').fetchall() == before


def test_change_and_incomplete_preserve_history(repository):
    repo, db = repository
    first = repo.archive_universe(records(), '2026-10-05', minimum_complete=2)
    partial = repo.archive_universe(records(1), '2026-10-05', minimum_complete=2)
    assert partial['canonical_preserved'] and partial['version_created']
    assert not partial['canonical_changed']
    assert db.execute('SELECT count(*) FROM quant_app.universe_membership').fetchone()[0] == 2
    revised = records()
    revised[0]['name'] = 'real revision fixture'
    result = repo.archive_universe(revised, '2026-10-05', minimum_complete=2)
    assert result['canonical_changed'] and result['version_created']
    assert first['snapshot_id'] != result['snapshot_id']
    assert db.execute('SELECT count(*) FROM quant_app.universe_snapshot_versions').fetchone()[0] == 3
    assert db.execute('SELECT count(*) FROM quant_app.universe_membership_versions').fetchone()[0] == 5


def test_new_date_same_content_retains_calendar_identity(repository):
    repo, db = repository
    repo.archive_universe(records(), '2026-10-05', minimum_complete=2)
    assert repo.archive_universe(records(), '2026-10-06', minimum_complete=2)['version_created']
    assert db.execute('SELECT count(*) FROM quant_app.universe_membership').fetchone()[0] == 4


def test_missing_canonical_members_cannot_be_certified_as_unchanged(repository):
    repo, db = repository
    repo.archive_universe(records(), '2026-10-05', minimum_complete=2)
    db.execute("DELETE FROM quant_app.universe_membership WHERE instrument_key='NSE_EQ|0'")
    with pytest.raises(RuntimeError, match='UNIVERSE_CANONICAL_MEMBERSHIP_COUNT_MISMATCH'):
        repo.archive_universe(records(), '2026-10-05', minimum_complete=2)


def test_first_quick_scan_requires_explicit_button():
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / 'app.py').read_text(encoding='utf-8'))
    branch = next(n for n in ast.walk(tree) if isinstance(n, ast.If)
                  and ast.unparse(n.test) == 'not already_scanned_this_session')
    assignment = next(n for n in branch.body if isinstance(n, ast.Assign))
    assert isinstance(assignment.value, ast.Call)
    assert ast.unparse(assignment.value.func) == 'st.button'


def test_compact_quote_keeps_a_zero_open_interest(repository):
    """With the raw payload no longer kept, a real 0 must not become NULL (CodeAnt, PR #75)."""
    repo, db = repository
    columns = ','.join(f'{name} {kind}' for name, kind in SPECS['market_quotes'].items())
    db.execute(f'CREATE TABLE quant_app.market_quotes ({columns}, PRIMARY KEY(instrument_key,observed_at))')
    observed = dt.datetime(2026, 10, 5, 9, tzinfo=dt.timezone.utc)
    quote = {'instrument_key': 'NSE_EQ|1', 'last_price': 11, 'oi': 0, 'ohlc': {'close': 10}}
    assert repo.archive_quotes([quote], observed_at=observed) == 1
    assert db.execute('SELECT open_interest FROM quant_app.market_quotes').fetchone()[0] == '0'


def provider_rows():
    """Collector shape: Upstox BOD equity rows (lot_size int; some keys absent)."""
    return [
        {'isin': 'INE467B01029', 'name': 'TATA CONSULTANCY SERV LT', 'segment': 'NSE_EQ', 'exchange': 'NSE',
         'lot_size': 1, 'tick_size': 10.0, 'short_name': 'TCS', 'cas_eligible': True, 'security_type': 'NORMAL',
         'exchange_token': '11536', 'instrument_key': 'NSE_EQ|INE467B01029', 'qty_multiplier': 1.0,
         'trading_symbol': 'TCS', 'freeze_quantity': 100000.0, 'instrument_type': 'EQ'},
        {'isin': 'INE002A01018', 'name': 'RELIANCE INDUSTRIES LTD', 'segment': 'NSE_EQ', 'exchange': 'NSE',
         'lot_size': 1, 'tick_size': 10.0, 'security_type': 'NORMAL', 'exchange_token': '2885',
         'instrument_key': 'NSE_EQ|INE002A01018', 'qty_multiplier': 1.0, 'trading_symbol': 'RELIANCE',
         'freeze_quantity': 100000.0, 'instrument_type': 'EQ'},
    ]


def app_frame_rows():
    """The app's shape: the same BOD file through pandas, as app.py reshapes it."""
    pd = pytest.importorskip('pandas')
    future = {'segment': 'NSE_FO', 'exchange': 'NSE', 'instrument_key': 'NSE_FO|1', 'trading_symbol': 'X FUT',
              'expiry': 1795000000000, 'weekly': False, 'lot_size': 75, 'strike_price': 0.0,
              'underlying_key': 'NSE_INDEX|Nifty 50', 'minimum_lot': 75, 'instrument_type': 'FUT'}
    index = {'segment': 'NSE_INDEX', 'exchange': 'NSE', 'instrument_key': 'NSE_INDEX|Nifty 50',
             'trading_symbol': 'NIFTY', 'instrument_type': 'INDEX'}  # no lot_size: the column becomes float
    df = pd.DataFrame(provider_rows() + [future, index])
    df['tradingsymbol'] = df['trading_symbol']
    df['source_exchange'] = df.get('exchange')
    df['exchange'] = df['segment']
    numeric_expiry = pd.to_numeric(df['expiry'], errors='coerce')
    df['expiry'] = pd.to_datetime(numeric_expiry, unit='ms', errors='coerce')
    equities = df[(df['segment'] == 'NSE_EQ') & (df['instrument_type'] == 'EQ')]
    return equities.to_dict('records')


def test_app_frame_rows_are_the_same_universe_version(repository):
    repo, db = repository
    shaped = app_frame_rows()
    assert shaped[0]['lot_size'] == 1.0 and isinstance(shaped[0]['lot_size'], float)
    assert shaped[0]['exchange'] == 'NSE_EQ' and 'tradingsymbol' in shaped[0]
    first = repo.archive_universe(provider_rows(), '2026-11-06', minimum_complete=2)
    second = repo.archive_universe(shaped, '2026-11-06', minimum_complete=2)
    assert second['snapshot_id'] == first['snapshot_id']
    assert not second['version_created'] and not second['canonical_changed']
    assert db.execute('SELECT count(*) FROM quant_app.universe_membership_versions').fetchone()[0] == 2
    # The other order: app first, then the collector, is equally a single version.
    other = repo.archive_universe(shaped, '2026-11-07', minimum_complete=2)
    collector = repo.archive_universe(provider_rows(), '2026-11-07', minimum_complete=2)
    assert other['version_created'] and not collector['version_created']
    assert collector['snapshot_id'] == other['snapshot_id']
    stored = {row[0]: row[1] for row in db.execute(
        "SELECT instrument_key, raw FROM quant_app.universe_membership_versions WHERE snapshot_id=%s",
        (other['snapshot_id'],)).fetchall()}
    expected = {row['instrument_key']: row for row in provider_rows()}
    assert {k: json.loads(v) if isinstance(v, str) else v for k, v in stored.items()} == expected


def test_provider_rows_pass_through_unchanged():
    from production_repository import _provider_universe_record
    for row in provider_rows():
        assert _provider_universe_record(row) is row


def test_canonical_rows_point_to_the_exact_version_payload(repository):
    repo, db = repository
    result = repo.archive_universe(provider_rows(), '2026-11-06', minimum_complete=2)
    canonical = db.execute(
        "SELECT DISTINCT raw::text FROM quant_app.universe_membership WHERE snapshot_date='2026-11-06'"
    ).fetchall()
    assert [json.loads(row[0]) for row in canonical] == [{'retention': 'versions_v1'}]
    # Lossless: date + header payload_hash identify the version holding the provider rows.
    rebuilt = db.execute("""
        SELECT m.instrument_key, v.raw::text FROM quant_app.universe_membership m
        JOIN quant_app.universe_snapshots h USING (snapshot_date)
        JOIN quant_app.universe_snapshot_versions sv
          ON sv.snapshot_date=h.snapshot_date AND sv.payload_hash=h.payload_hash
        JOIN quant_app.universe_membership_versions v
          ON v.snapshot_id=sv.snapshot_id AND v.instrument_key=m.instrument_key
        WHERE m.snapshot_date='2026-11-06' ORDER BY 1""").fetchall()
    assert {key: json.loads(raw) for key, raw in rebuilt} == {r['instrument_key']: r for r in provider_rows()}
    assert result['snapshot_id'] == hashlib.sha256(f"2026-11-06|{result['payload_hash']}".encode()).hexdigest()


def test_app_row_without_provider_exchange_drops_the_segment_copy():
    from production_repository import _provider_universe_record
    row = {'instrument_key': 'NSE_EQ|X', 'trading_symbol': 'X', 'tradingsymbol': 'X',
           'segment': 'NSE_EQ', 'exchange': 'NSE_EQ', 'source_exchange': float('nan'), 'weekly': None}
    assert _provider_universe_record(row) == {'instrument_key': 'NSE_EQ|X', 'trading_symbol': 'X',
                                              'segment': 'NSE_EQ'}
