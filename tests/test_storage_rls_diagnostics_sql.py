"""Read-only owner diagnostics against disposable local PostgreSQL, never hosted."""
import os
from pathlib import Path

import pytest
import test_archive_maintenance_sql as sql_harness

pg = sql_harness.pg

pytestmark = pytest.mark.skipif(not os.environ.get('EQUITY_TEST_PGLITE_MODULE'), reason='SQL engine not configured')


def test_all_diagnostics_are_executable_in_read_only_transaction(pg):
    pg.send({'script': """
      CREATE TABLE quant_app.schema_migrations(version integer,applied_at timestamptz);
      INSERT INTO equity_research.source_decisions VALUES('test');
      INSERT INTO equity_research.observations VALUES('test');
      INSERT INTO equity_research.outcomes VALUES
        ('old','test','{"source_candles":[]}',CURRENT_TIMESTAMP-INTERVAL '30 days'),
        ('new','test','{"source_candles":[]}',CURRENT_TIMESTAMP);
    """})
    text = (Path(__file__).resolve().parents[1]/'sql/storage_rls_followup_read_only.sql').read_text()
    blocks = [section.split('\n',1)[1] for section in text.split('-- CHECK ')[1:]]
    assert len(blocks) == 8
    pg.execute('BEGIN READ ONLY')
    try:
        results = [pg.execute(block).fetchall() for block in blocks]
        assert results[5][0][0] == 2  # Live outcomes, not a stale statistics estimate.
        assert results[5][0][-1] == 1  # Superseded old row only; latest retained.
        assert results[6][0][0] == 2
    finally:
        pg.execute('ROLLBACK')
    assert pg.execute('SELECT count(*) FROM equity_research.outcomes').fetchone()[0] == 2


def test_growth_and_content_checks_are_read_only_and_compare_content_not_counts(pg):
    pg.send({'script': """
      INSERT INTO quant_app.universe_snapshots(snapshot_date) VALUES('2026-09-21');
      INSERT INTO quant_app.universe_membership(snapshot_date,instrument_key,observed_at,raw) VALUES
        ('2026-09-18','K','2026-09-18Z','{"sector":"A"}'),
        ('2026-09-19','K','2026-09-19Z','{"sector":"A"}'),
        ('2026-09-21','K','2026-09-21Z','{"sector":"B"}');
    """})
    text = (Path(__file__).resolve().parents[1]/'sql/storage_growth_baseline_read_only.sql').read_text()
    blocks = [section.split('\n',1)[1] for section in text.split('-- CHECK ')[1:]]
    assert len(blocks) == 3
    pg.execute('BEGIN READ ONLY')
    try:
        baseline, compared, outcomes = [pg.execute(block).fetchall() for block in blocks]
        assert baseline[0][0]['database_bytes'] >= 0
        assert compared[0][4] is False  # Same count but changed metadata.
        assert compared[1][3] is True and compared[1][4] is True  # Weekend repeat.
        assert compared[0][5] is True
        assert not outcomes
    finally:
        pg.execute('ROLLBACK')
