"""Verify actual durable PostgreSQL append material using a disposable SQL engine."""
from contextlib import contextmanager
import datetime as dt
import hashlib
import json
import os

import pytest

from ledger_segments import restore, seal
from production_repository import ProductionRepository
from test_archive_maintenance_sql import Pg


@pytest.mark.skipif(not os.environ.get('EQUITY_TEST_PGLITE_MODULE'), reason='SQL engine not configured')
def test_segment_restores_real_durable_writer_output(monkeypatch):
    db = Pg()
    try:
        db.send({'script': '''CREATE SCHEMA quant_app;
            CREATE TABLE quant_app.evidence_ledger_events(
            event_id uuid PRIMARY KEY,aggregate_id text,sequence_no integer,
            event_type text,recorded_at timestamptz,effective_at timestamptz,
            source text,actor_id text,idempotency_key text UNIQUE,payload jsonb,
            previous_hash text,event_hash text,hash_algorithm text,schema_version integer,
            key_id text,UNIQUE(aggregate_id,sequence_no));'''})
        key = b'durable-fixture-event-key'
        repo = ProductionRepository('', evidence_signing_key=key)
        repo.ensure_schema = lambda: None
        monkeypatch.setattr('production_repository._utcnow', lambda: dt.datetime(
            2026, 10, 5, 0, 0, 0, 123000, tzinfo=dt.timezone.utc))

        @contextmanager
        def connect():
            class Connection:
                def execute(self, sql, params=()):
                    return db.execute(sql, tuple(json.dumps(p.obj) if hasattr(p, 'obj') else p for p in params))
                def commit(self):
                    pass
                def rollback(self):
                    db.execute('ROLLBACK')
            with db.connect():
                yield Connection()

        repo.connect = connect
        for i in range(3):
            repo.append_evidence_event(aggregate_id='sql-fixture', event_type='DECISION_EVALUATED',
                                       payload={'original': i}, idempotency_key=f'fixture-{i}')
        rows = repo.events('sql-fixture')
        # PGlite's JS transport returns strings, real psycopg returns datetime.
        for row in rows:
            for name in ('recorded_at', 'effective_at'):
                row[name] = dt.datetime.fromisoformat(row[name].replace('Z', '+00:00'))
        ring = {hashlib.sha256(key).hexdigest()[:16]: key}
        segment = seal(rows, {}, ring, b'offline-archive-seal-key-fixture!!')
        restored, heads = restore(segment.data, segment.sha256, {}, ring,
                                  b'offline-archive-seal-key-fixture!!')
        assert [row['event_hash'] for row in restored] == [row['event_hash'] for row in rows]
        assert heads['sql-fixture'][0] == 3
    finally:
        db.send({'close': True})
        db.process.stdin.close()
        db.process.wait(timeout=10)
