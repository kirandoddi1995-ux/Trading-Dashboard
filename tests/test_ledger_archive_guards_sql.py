"""Execute ledger archive guards in disposable PostgreSQL, never hosted SQL.

These fixtures exercise atomicity and role/row guards, not remote publication or
owner commissioning. Only the eventual private archiver may stage verified proof.
"""
import os
from pathlib import Path

import pytest

from cold_catalog import EMPTY_ROOT
from test_archive_maintenance_sql import Pg
from test_catalog_roots_sql import MIGRATION as ROOT_MIGRATION, bootstrap, advance

MIGRATION = Path(__file__).resolve().parents[1] / 'supabase' / 'migrations' / (
    '20261005200414_permanent_storage_ledger_review_only.sql')
HEAD_MIGRATION = MIGRATION.with_name('20261005210149_permanent_storage_heads_review_only.sql')
pytestmark = pytest.mark.skipif(not os.environ.get('EQUITY_TEST_PGLITE_MODULE'),
                                reason='Local SQL harness not configured')


@pytest.fixture
def ledger_db():
    db = Pg()
    try:
        db.send({'script': """
            CREATE ROLE quant_app_runtime LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS;
            CREATE SCHEMA quant_app;
            CREATE TABLE quant_app.evidence_ledger_events (
              event_id uuid PRIMARY KEY, aggregate_id text NOT NULL,
              sequence_no bigint NOT NULL, event_type text NOT NULL,
              recorded_at timestamptz NOT NULL, effective_at timestamptz NOT NULL,
              source text NOT NULL, actor_id text NOT NULL,
              idempotency_key text NOT NULL UNIQUE, payload jsonb NOT NULL,
              previous_hash text NOT NULL, event_hash text NOT NULL,
              hash_algorithm text NOT NULL, schema_version integer NOT NULL,
              key_id text, UNIQUE(aggregate_id,sequence_no));
            CREATE FUNCTION quant_app.fixture_immutable() RETURNS trigger
              LANGUAGE plpgsql AS $$BEGIN RAISE EXCEPTION 'IMMUTABLE'; END;$$;
            CREATE TRIGGER evidence_ledger_no_update BEFORE UPDATE
              ON quant_app.evidence_ledger_events FOR EACH ROW
              EXECUTE FUNCTION quant_app.fixture_immutable();
            CREATE TRIGGER evidence_ledger_no_delete BEFORE DELETE
              ON quant_app.evidence_ledger_events FOR EACH ROW
              EXECUTE FUNCTION quant_app.fixture_immutable();
            INSERT INTO quant_app.evidence_ledger_events
              SELECT ('00000000-0000-0000-0000-'||lpad(n::text,12,'0'))::uuid,
                'fixture',n,'FIXTURE','2026-10-01Z'::timestamptz,
                '2026-10-01Z'::timestamptz,'test','test','idem-'||n,
                jsonb_build_object('original',n),repeat('0',64),repeat('d',64),
                'HMAC-SHA256',2,'fixture' FROM generate_series(1,2) n;
        """})
        db.send({'script': ROOT_MIGRATION.read_text()})
        bootstrap(db)
        db.send({'script': MIGRATION.read_text()})
        db.send({'script': HEAD_MIGRATION.read_text()})
        yield db
    finally:
        db.send({'close': True})
        db.process.stdin.close()
        db.process.wait(timeout=10)


def commission(db):
    """Owner approval synthetic fixture, not an owner/live instruction."""
    db.execute('''INSERT INTO quant_storage.ledger_hot_heads
        SELECT DISTINCT ON(aggregate_id) aggregate_id,sequence_no,event_hash
        FROM quant_app.evidence_ledger_events ORDER BY aggregate_id,sequence_no DESC
        ON CONFLICT(aggregate_id) DO UPDATE SET sequence_no=EXCLUDED.sequence_no,
                                              event_hash=EXCLUDED.event_hash''')
    db.execute("""UPDATE quant_storage.ledger_control SET pruning_enabled=true,
        heads_enabled=true,head_audit_sha256=repeat('e',64),
        reader_fingerprint=repeat('f',64),commissioned_at='2026-10-06Z'""")


def stage(db, *, count=2):
    db.execute("SET LOCAL TimeZone='UTC'")
    db.execute("""CREATE TEMP TABLE quant_storage_ledger_rows (
        event_id uuid PRIMARY KEY,event_hash text NOT NULL,
        aggregate_id text NOT NULL,sequence_no bigint NOT NULL,
        source_sha256 text NOT NULL) ON COMMIT DROP""")
    db.execute("""INSERT INTO quant_storage_ledger_rows SELECT event_id,event_hash,
        aggregate_id,sequence_no,encode(sha256(convert_to(to_jsonb(e)::text,'UTF8')),'hex')
        FROM quant_app.evidence_ledger_events e""")
    db.execute("""CREATE TEMP TABLE quant_storage_ledger_stage (
        reader_fingerprint text,source_count bigint,previous_generation bigint,
        previous_root text,previous_receipt text,next_generation bigint,
        next_root text,next_receipt text,segment text) ON COMMIT DROP""")
    db.execute("""INSERT INTO quant_storage_ledger_stage VALUES
        (repeat('f',64),%s,0,%s,repeat('0',64),1,repeat('a',64),
         repeat('b',64),repeat('c',64))""", (count, EMPTY_ROOT))


def state(db):
    return db.execute("""SELECT (SELECT count(*) FROM quant_app.evidence_ledger_events),
        generation FROM quant_storage.catalog_roots WHERE scope='ledger'""").fetchone()


def test_default_disabled_even_with_proof(ledger_db):
    with pytest.raises(RuntimeError, match='NOT_COMMISSIONED'):
        with ledger_db.connect():
            ledger_db.execute('SET LOCAL ROLE quant_storage_archiver')
            stage(ledger_db)
            ledger_db.execute('DELETE FROM quant_app.evidence_ledger_events')
    assert state(ledger_db) == (2, 0)


@pytest.mark.parametrize('root_first', [False, True])
def test_exact_batch_and_root_commit_together(ledger_db, root_first):
    commission(ledger_db)
    with ledger_db.connect():
        ledger_db.execute('SET LOCAL ROLE quant_storage_archiver')
        stage(ledger_db)
        if root_first:
            advance(ledger_db)
        assert len(ledger_db.execute('DELETE FROM quant_app.evidence_ledger_events RETURNING event_id').fetchall()) == 2
        if not root_first:
            advance(ledger_db)
    assert state(ledger_db) == (0, 1)


@pytest.mark.parametrize('operation,code', [
    ('DELETE FROM quant_app.evidence_ledger_events', 'ROOT_NOT_ADVANCED'),
    ('root', 'BATCH_NOT_DELETED'),
    ('partial', 'BATCH_NOT_DELETED'),
])
def test_incomplete_transaction_rolls_back_both(ledger_db, operation, code):
    commission(ledger_db)
    with pytest.raises(RuntimeError, match=code):
        with ledger_db.connect():
            ledger_db.execute('SET LOCAL ROLE quant_storage_archiver')
            stage(ledger_db)
            if operation == 'root':
                advance(ledger_db)
            elif operation == 'partial':
                ledger_db.execute('DELETE FROM quant_app.evidence_ledger_events WHERE sequence_no=1')
                advance(ledger_db)
            else:
                ledger_db.execute(operation)
    assert state(ledger_db) == (2, 0)


@pytest.mark.parametrize('mutation,code', [
    ("UPDATE quant_storage_ledger_rows SET source_sha256=repeat('e',64)", 'ROW_NOT_VERIFIED'),
    ("UPDATE quant_storage_ledger_rows SET event_hash=repeat('e',64)", 'ROW_NOT_VERIFIED'),
    ("UPDATE quant_storage_ledger_stage SET reader_fingerprint=repeat('e',64)", 'STAGE_INVALID'),
    ("UPDATE quant_storage_ledger_stage SET source_count=901", 'STAGE_INVALID'),
    ("UPDATE quant_storage_ledger_stage SET source_count=NULL", 'STAGE_INVALID'),
    ("DELETE FROM quant_storage_ledger_rows WHERE sequence_no=2", 'STAGE_INVALID'),
    ("UPDATE quant_storage_ledger_stage SET next_root=repeat('e',64)", 'ROOT_STAGE_MISMATCH'),
])
def test_bad_proof_rolls_back_everything(ledger_db, mutation, code):
    commission(ledger_db)
    with pytest.raises(RuntimeError, match=code):
        with ledger_db.connect():
            ledger_db.execute('SET LOCAL ROLE quant_storage_archiver')
            stage(ledger_db)
            ledger_db.execute(mutation)
            ledger_db.execute('DELETE FROM quant_app.evidence_ledger_events')
            advance(ledger_db)
    assert state(ledger_db) == (2, 0)


def test_raw_delete_without_stage_is_blocked(ledger_db):
    commission(ledger_db)
    with pytest.raises(RuntimeError, match='STAGE_MISSING'):
        with ledger_db.connect():
            ledger_db.execute('SET LOCAL ROLE quant_storage_archiver')
            ledger_db.execute("SET LOCAL TimeZone='UTC'")
            ledger_db.execute('DELETE FROM quant_app.evidence_ledger_events')
    assert state(ledger_db) == (2, 0)


def test_runtime_cannot_delete_or_commission_and_update_remains_immutable(ledger_db):
    ledger_db.execute('SET ROLE quant_app_runtime')
    for sql in ('DELETE FROM quant_app.evidence_ledger_events',
                'UPDATE quant_storage.ledger_control SET pruning_enabled=true'):
        with pytest.raises(RuntimeError, match='permission denied'):
            ledger_db.execute(sql)
    ledger_db.execute('RESET ROLE')
    with pytest.raises(RuntimeError, match='IMMUTABLE'):
        ledger_db.execute("UPDATE quant_app.evidence_ledger_events SET payload='{}'")


def test_migration_rerun_preserves_commissioning_and_root(ledger_db):
    commission(ledger_db)
    ledger_db.send({'script': MIGRATION.read_text()})
    assert ledger_db.execute('SELECT pruning_enabled FROM quant_storage.ledger_control').fetchone() == (True,)
    assert state(ledger_db) == (2, 0)


@pytest.mark.parametrize('change,code', [
    ("COMMENT ON TABLE quant_storage.ledger_control IS 'future-v2'", 'VERSION_UNEXPECTED'),
    ('CREATE POLICY unexpected ON quant_storage.ledger_control USING(true)', 'SHAPE_UNEXPECTED'),
    ('ALTER ROLE quant_storage_archiver BYPASSRLS', 'ROLE_OR_OWNER_UNSAFE'),
])
def test_unsupported_control_state_not_silently_repaired(ledger_db, change, code):
    ledger_db.execute(change)
    with pytest.raises(RuntimeError, match=code):
        ledger_db.send({'script': MIGRATION.read_text()})
    ledger_db.execute('ROLLBACK')


def test_default_public_role_grant_is_removed(ledger_db):
    ledger_db.execute('CREATE ROLE authenticated')
    ledger_db.execute('GRANT SELECT ON quant_storage.ledger_control TO authenticated')
    ledger_db.send({'script': MIGRATION.read_text()})
    assert ledger_db.execute("SELECT has_table_privilege('authenticated', 'quant_storage.ledger_control','SELECT')").fetchone() == (False,)


def test_relations_root_does_not_require_ledger_stage(ledger_db):
    bootstrap(ledger_db, 'relations')
    ledger_db.execute("""UPDATE quant_storage.catalog_roots SET generation=1,
        root=repeat('a',64),receipt_sha256=repeat('b',64),previous_root=%s,
        previous_receipt=repeat('0',64),segment=repeat('c',64),key_id='fixture'
        WHERE scope='relations'""", (EMPTY_ROOT,))
    assert ledger_db.execute("SELECT generation FROM quant_storage.catalog_roots WHERE scope='relations'").fetchone() == (1,)
