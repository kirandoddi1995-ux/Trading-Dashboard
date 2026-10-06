"""Protected terminal heads: actual disposable SQL, not hosted mutations."""
import os

import pytest

from test_catalog_roots_sql import advance
from test_ledger_archive_guards_sql import HEAD_MIGRATION, commission, stage, state

pytest_plugins = ('test_ledger_archive_guards_sql',)
pytestmark = pytest.mark.skipif(not os.environ.get('EQUITY_TEST_PGLITE_MODULE'),
                                reason='Local SQL harness not configured')


def heads(db):
    return db.execute('''SELECT aggregate_id,sequence_no,event_hash
        FROM quant_storage.ledger_hot_heads ORDER BY aggregate_id''').fetchall()


def append(db, sequence=3, previous='d'*64, digest='e'*64, *, conflict=False):
    query = '''INSERT INTO quant_app.evidence_ledger_events
        VALUES(%s,'fixture',%s,'FIXTURE','2026-10-06Z','2026-10-06Z',
               'test','test',%s,'{}',%s,%s,'HMAC-SHA256',2,'fixture')'''
    if conflict:
        query += ' ON CONFLICT(event_id) DO NOTHING'
    db.execute(query, ('00000000-0000-0000-0000-'+str(sequence).zfill(12),
                       sequence, 'idem-'+str(sequence), previous, digest))


def test_heads_do_not_bootstrap_or_enable_themselves(ledger_db):
    assert heads(ledger_db) == []
    assert ledger_db.execute('SELECT heads_enabled,pruning_enabled FROM quant_storage.ledger_control').fetchone() == (False, False)
    # Old append behaviour is unchanged until explicitly commissioned.
    append(ledger_db)
    assert heads(ledger_db) == []


def test_owner_bootstrap_must_match_every_available_terminal(ledger_db):
    with pytest.raises(RuntimeError, match='BOOTSTRAP_MISMATCH'):
        ledger_db.execute('''UPDATE quant_storage.ledger_control SET heads_enabled=true,
                            head_audit_sha256=repeat('e',64)''')
    ledger_db.execute("INSERT INTO quant_storage.ledger_hot_heads VALUES('fixture',2,repeat('e',64))")
    with pytest.raises(RuntimeError, match='BOOTSTRAP_MISMATCH'):
        ledger_db.execute('''UPDATE quant_storage.ledger_control SET heads_enabled=true,
                            head_audit_sha256=repeat('e',64)''')


@pytest.mark.parametrize('role', ['quant_app_runtime', 'quant_storage_archiver'])
def test_workers_can_read_but_cannot_rewrite_or_retire_heads(ledger_db, role):
    commission(ledger_db)
    ledger_db.execute('SET ROLE '+role)
    assert heads(ledger_db) == [('fixture', 2, 'd'*64)]
    for query in ("UPDATE quant_storage.ledger_hot_heads SET sequence_no=1",
                  'DELETE FROM quant_storage.ledger_hot_heads',
                  'TRUNCATE quant_storage.ledger_hot_heads',
                  "INSERT INTO quant_storage.ledger_hot_heads VALUES('other',1,repeat('a',64))",
                  'SELECT quant_storage.advance_hot_head()',
                  'SELECT quant_storage.retire_cold_heads()'):
        with pytest.raises(RuntimeError, match='permission denied'):
            ledger_db.execute(query)
    ledger_db.execute('RESET ROLE')


def test_actual_runtime_insert_advances_protected_head_and_retry_does_not(ledger_db):
    commission(ledger_db)
    ledger_db.execute('GRANT USAGE ON SCHEMA quant_app TO quant_app_runtime')
    ledger_db.execute('GRANT SELECT,INSERT ON quant_app.evidence_ledger_events TO quant_app_runtime')
    ledger_db.execute('SET ROLE quant_app_runtime')
    append(ledger_db)
    assert heads(ledger_db) == [('fixture', 3, 'e'*64)]
    append(ledger_db, conflict=True)
    assert heads(ledger_db) == [('fixture', 3, 'e'*64)]
    ledger_db.execute('RESET ROLE')


@pytest.mark.parametrize('sequence,previous', [(4, 'd'*64), (3, 'a'*64)])
def test_invalid_append_rolls_back_source_and_head(ledger_db, sequence, previous):
    commission(ledger_db)
    with pytest.raises(RuntimeError, match='PREDECESSOR_MISMATCH'):
        append(ledger_db, sequence=sequence, previous=previous)
    assert heads(ledger_db) == [('fixture', 2, 'd'*64)]
    assert state(ledger_db) == (2, 0)


def test_transaction_rollback_cannot_leave_a_future_head(ledger_db):
    commission(ledger_db)
    with pytest.raises(RuntimeError, match='fixture crash'):
        with ledger_db.connect():
            append(ledger_db)
            raise RuntimeError('fixture crash')
    assert heads(ledger_db) == [('fixture', 2, 'd'*64)]
    assert state(ledger_db) == (2, 0)


def test_tail_loss_cannot_reset_the_expected_terminal(ledger_db):
    commission(ledger_db)
    # Fixture-only privileged damage: head is deliberately not truncated.
    ledger_db.execute('TRUNCATE quant_app.evidence_ledger_events')
    with pytest.raises(RuntimeError, match='TAIL_MISSING_OR_CHANGED'):
        append(ledger_db)
    assert heads(ledger_db) == [('fixture', 2, 'd'*64)]


def test_missing_head_with_hot_rows_blocks_append(ledger_db):
    commission(ledger_db)
    ledger_db.execute('DELETE FROM quant_storage.ledger_hot_heads')
    with pytest.raises(RuntimeError, match='HOT_HEAD_MISSING'):
        append(ledger_db)
    assert state(ledger_db) == (2, 0)


def archive(db, *, partial=False):
    with db.connect():
        db.execute('SET LOCAL ROLE quant_storage_archiver')
        stage(db, count=1 if partial else 2)
        if partial:
            db.execute('DELETE FROM quant_storage_ledger_rows WHERE sequence_no=2')
        db.execute('''DELETE FROM quant_app.evidence_ledger_events WHERE event_id IN
                      (SELECT event_id FROM quant_storage_ledger_rows)''')
        advance(db)
        db.execute('SET CONSTRAINTS ALL IMMEDIATE')


def test_prefix_archival_keeps_the_independent_hot_terminal(ledger_db):
    commission(ledger_db)
    archive(ledger_db, partial=True)
    assert state(ledger_db) == (1, 1)
    assert heads(ledger_db) == [('fixture', 2, 'd'*64)]


def test_complete_archival_retires_head_only_with_root_commit(ledger_db):
    commission(ledger_db)
    archive(ledger_db)
    assert state(ledger_db) == (0, 1)
    assert heads(ledger_db) == []
    with pytest.raises(RuntimeError, match='COLD_APPEND_STAGE_MISSING'):
        append(ledger_db, sequence=1, previous='0'*64)
    assert state(ledger_db) == (0, 1)
    with pytest.raises(RuntimeError, match='COLD_HEAD_TRACKING_REQUIRED'):
        ledger_db.execute('''UPDATE quant_storage.ledger_control
                            SET pruning_enabled=false,heads_enabled=false''')


def test_damaged_head_prevents_source_pruning_and_root_advancement(ledger_db):
    commission(ledger_db)
    ledger_db.execute("UPDATE quant_storage.ledger_hot_heads SET event_hash=repeat('e',64)")
    with pytest.raises(RuntimeError, match='HEAD_RETIRE_MISMATCH'):
        archive(ledger_db)
    assert state(ledger_db) == (2, 0)
    assert heads(ledger_db) == [('fixture', 2, 'e'*64)]


def test_tracking_audit_is_immutable_and_rerun_preserves_heads(ledger_db):
    commission(ledger_db)
    append(ledger_db)
    with pytest.raises(RuntimeError, match='AUDIT_IMMUTABLE'):
        ledger_db.execute("UPDATE quant_storage.ledger_control SET head_audit_sha256=repeat('a',64)")
    ledger_db.send({'script': HEAD_MIGRATION.read_text()})
    assert heads(ledger_db) == [('fixture', 3, 'e'*64)]
    assert ledger_db.execute('SELECT heads_enabled FROM quant_storage.ledger_control').fetchone() == (True,)


def test_definer_trigger_cannot_be_reused_on_another_table(ledger_db):
    commission(ledger_db)
    ledger_db.send({'script': '''CREATE TEMP TABLE fake_ledger
        (LIKE quant_app.evidence_ledger_events INCLUDING ALL);
        CREATE TRIGGER fake AFTER INSERT ON fake_ledger FOR EACH ROW
        EXECUTE FUNCTION quant_storage.advance_hot_head();'''})
    with pytest.raises(RuntimeError, match='CONTEXT_INVALID'):
        ledger_db.execute('INSERT INTO fake_ledger SELECT * FROM quant_app.evidence_ledger_events WHERE sequence_no=1')
    assert heads(ledger_db) == [('fixture', 2, 'd'*64)]


def cold_stage(db, **overrides):
    db.execute('''CREATE TEMP TABLE quant_storage_append_stage (
        generation bigint,root text,receipt_sha256 text,aggregate_id text,
        reader_fingerprint text,cold_sequence bigint,cold_hash text) ON COMMIT DROP''')
    values = {'generation': 1, 'root': 'a'*64, 'receipt_sha256': 'b'*64,
              'aggregate_id': 'fixture', 'reader_fingerprint': 'f'*64,
              'cold_sequence': 2, 'cold_hash': 'd'*64}
    values.update(overrides)
    db.execute('INSERT INTO quant_storage_append_stage VALUES(%s,%s,%s,%s,%s,%s,%s)',
               tuple(values.values()))


def test_cold_only_aggregate_reappears_with_snapshot_bound_frontier(ledger_db):
    commission(ledger_db)
    archive(ledger_db)
    with ledger_db.connect():
        cold_stage(ledger_db)
        append(ledger_db)
    assert state(ledger_db) == (1, 1)
    assert heads(ledger_db) == [('fixture', 3, 'e'*64)]
    assert ledger_db.execute("SELECT to_regclass('pg_temp.quant_storage_append_stage')").fetchone() == (None,)


@pytest.mark.parametrize('override', [
    {'generation': 0}, {'root': 'c'*64}, {'receipt_sha256': 'c'*64},
    {'aggregate_id': 'other'}, {'reader_fingerprint': 'c'*64},
    {'cold_sequence': None}, {'cold_sequence': -1}, {'cold_hash': None},
    {'cold_hash': 'invalid'}, {'cold_sequence': 0, 'cold_hash': 'd'*64},
])
def test_stale_or_invalid_cold_stage_cannot_recreate_a_head(ledger_db, override):
    commission(ledger_db)
    archive(ledger_db)
    with pytest.raises(RuntimeError, match='STAGE_INVALID'):
        with ledger_db.connect():
            cold_stage(ledger_db, **override)
            append(ledger_db)
    assert state(ledger_db) == (0, 1)
    assert heads(ledger_db) == []


def test_stage_cannot_change_the_next_sequence_or_previous_hash(ledger_db):
    commission(ledger_db)
    archive(ledger_db)
    with pytest.raises(RuntimeError, match='PREDECESSOR_MISMATCH'):
        with ledger_db.connect():
            cold_stage(ledger_db)
            append(ledger_db, sequence=1, previous='0'*64)
    assert state(ledger_db) == (0, 1)


def test_sql_cannot_enable_pruning_without_head_tracking(ledger_db):
    with pytest.raises(RuntimeError, match='check constraint'):
        ledger_db.execute('''UPDATE quant_storage.ledger_control SET pruning_enabled=true,
                            reader_fingerprint=repeat('f',64),commissioned_at=now()''')
    assert ledger_db.execute('SELECT pruning_enabled FROM quant_storage.ledger_control').fetchone() == (False,)


def test_privileged_append_never_evaluates_a_caller_supplied_view(ledger_db):
    commission(ledger_db)
    archive(ledger_db)
    ledger_db.send({'script': '''CREATE FUNCTION public.fixture_escalate() RETURNS text
        LANGUAGE plpgsql SECURITY INVOKER AS $$BEGIN
        INSERT INTO quant_storage.ledger_hot_heads VALUES('attack',1,repeat('a',64));
        RETURN repeat('a',64); END;$$;'''} )
    ledger_db.execute('GRANT USAGE ON SCHEMA quant_app TO quant_app_runtime')
    ledger_db.execute('GRANT INSERT ON quant_app.evidence_ledger_events TO quant_app_runtime')
    with pytest.raises(RuntimeError, match='TEMP_STAGE_UNSAFE'):
        with ledger_db.connect():
            ledger_db.execute('SET LOCAL ROLE quant_app_runtime')
            ledger_db.send({'script': '''CREATE TEMP VIEW quant_storage_append_stage AS
                SELECT 1::bigint AS generation,public.fixture_escalate() AS root,
                  repeat('b',64)::text AS receipt_sha256,'fixture'::text AS aggregate_id,
                  repeat('f',64)::text AS reader_fingerprint,2::bigint AS cold_sequence,
                  repeat('d',64)::text AS cold_hash;'''} )
            append(ledger_db)
    assert heads(ledger_db) == []
    assert state(ledger_db) == (0, 1)


def test_privileged_append_rejects_custom_column_domains(ledger_db):
    commission(ledger_db)
    archive(ledger_db)
    with pytest.raises(RuntimeError, match='TEMP_STAGE_UNSAFE'):
        with ledger_db.connect():
            cold_stage(ledger_db)
            ledger_db.execute('CREATE DOMAIN pg_temp.fixture_text AS text')
            ledger_db.execute('ALTER TABLE quant_storage_append_stage ALTER root TYPE pg_temp.fixture_text')
            append(ledger_db)
    assert heads(ledger_db) == []
    assert state(ledger_db) == (0, 1)


@pytest.mark.parametrize('grant', [
    'GRANT UPDATE ON quant_storage.ledger_hot_heads TO fixture_reader',
    'GRANT UPDATE(event_hash) ON quant_storage.ledger_hot_heads TO fixture_reader',
    'GRANT EXECUTE ON FUNCTION quant_storage.advance_hot_head() TO fixture_reader',
])
def test_unexpected_grants_require_review_instead_of_silent_access(ledger_db, grant):
    ledger_db.execute('CREATE ROLE fixture_reader')
    ledger_db.execute(grant)
    with pytest.raises(RuntimeError, match='GRANT_UNEXPECTED'):
        ledger_db.send({'script': HEAD_MIGRATION.read_text()})
    ledger_db.execute('ROLLBACK')
