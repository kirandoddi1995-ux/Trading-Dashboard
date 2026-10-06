"""Original recovery on synthetic private objects and disposable PostgreSQL only."""
import os
from contextlib import contextmanager
from dataclasses import replace

import pytest

from ledger_recovery import (RecoveryWitness, RecoveryCheckError, VERSION,
                             database_identity, capture_witness, verify_original_recovery)
from ledger_runtime_reader import LedgerRuntimeReader
from recovery_drill import verify_isolated_target

pytest_plugins = ('test_ledger_runtime_reader_sql',)
SQL = pytest.mark.skipif(not os.environ.get('EQUITY_TEST_PGLITE_MODULE'),
                         reason='Local SQL harness not configured')


@SQL
def test_trusted_source_witness_survives_complete_verified_archival(reader):
    _, _, _, commit, runtime = reader
    expected = capture_witness(runtime)
    assert expected.events == 3
    commit()
    assert capture_witness(runtime) == expected
    result = verify_original_recovery(runtime, expected)
    assert result['status'] == 'PASS' and result['originals_verified'] is True


@SQL
def test_recovery_missing_original_is_not_empty_hot_success(reader):
    _, objects, publication, commit, runtime = reader
    expected = capture_witness(runtime)
    commit()
    objects.data.pop(('ledger-segment', publication.prepared.segment.sha256))
    with pytest.raises(RecoveryCheckError, match='^RECOVERY_ORIGINALS_UNVERIFIED$'):
        verify_original_recovery(runtime, expected)


@SQL
@pytest.mark.parametrize('field,value', [('events', 4), ('originals_sha256', 'a'*64)])
def test_valid_shorter_or_different_history_is_not_the_reviewed_source(reader, field, value):
    runtime = reader[-1]
    expected = replace(capture_witness(runtime), **{field: value})
    result = verify_original_recovery(runtime, expected)
    assert result['status'] == 'FAILED' and result['originals_verified'] is False


@SQL
def test_empty_source_cannot_make_its_own_recovery_baseline(reader):
    db, _, _, _, runtime = reader
    db.execute('TRUNCATE quant_app.evidence_ledger_events,quant_storage.ledger_hot_heads')
    with pytest.raises(RecoveryCheckError, match='SOURCE_EMPTY'):
        capture_witness(runtime)


@pytest.mark.parametrize('events,digest', [(0, 'a'*64), (-1, 'a'*64), (True, 'a'*64),
                                          (1, 'A'*64), (1, 'invalid')])
def test_witness_rejects_invalid_or_empty_expectation(events, digest):
    with pytest.raises(RecoveryCheckError, match='EXPECTATION_INVALID'):
        RecoveryWitness(VERSION, events, digest)


def test_database_identity_ignores_password_and_normalizes_known_aliases():
    project = 'a'*20
    direct = f'postgresql://reader:synthetic-password@db.{project}.supabase.co/postgres'
    pooled = f'postgres://different.{project}:other-fixture@aws-0-x.pooler.supabase.com:6543/postgres'
    assert database_identity(direct) == database_identity(pooled)
    assert database_identity(direct) != database_identity(direct.replace(project, 'b'*20))
    assert database_identity('postgres://a:x@ep-fixture-pooler.region.neon.tech/db') == database_identity(
        'postgresql://b:y@ep-fixture.region.neon.tech/db')
    assert database_identity('postgres://a:x@localhost/db') != database_identity('postgres://a:x@localhost/other')


@pytest.mark.parametrize('url', ['https://private:never-output@example.com/db',
                               'postgres://private:never-output@host:bad/db',
                               'postgres://user@aws-0-x.pooler.supabase.com/db',
                               'postgres://user@host',
                               'postgres://user@host/db?dbname=other',
                               'postgres://user@host/db?user=other',
                               'postgres://user@host/db?hostaddr=127.0.0.1'])
def test_invalid_identity_does_not_expose_connection_string(url):
    with pytest.raises(RecoveryCheckError, match='^RECOVERY_DATABASE_IDENTITY_INVALID$'):
        database_identity(url)


def test_dr_has_no_implicit_production_or_self_generated_expectation():
    with pytest.raises(ValueError, match='Explicit DR'):
        verify_isolated_target('')
    result = verify_isolated_target('postgres://unused.invalid/dr')
    assert result['reason'] == 'RECOVERY_EXPECTATION_REQUIRED'
    assert result['ledger_chain_verified'] is False


@SQL
def test_dr_uses_explicit_target_connection_and_verified_originals(reader, monkeypatch):
    _, objects, _, commit, runtime = reader
    expected = capture_witness(runtime)
    commit()
    from production_repository import ProductionRepository
    @contextmanager
    def target_connect(self):
        assert self._database_url == 'postgres://target.invalid/dr'
        with runtime.connect() as conn:
            yield conn
    monkeypatch.setattr(ProductionRepository, 'connect', target_connect)
    def factory(connect):
        return LedgerRuntimeReader(connect, objects, runtime.event_keys,
                                   runtime.seal_key, runtime.receipt_keys)
    result = verify_isolated_target('postgres://target.invalid/dr',
        source_database_url='postgres://source.invalid/source', expected=expected, reader_factory=factory)
    assert result['status'] == 'PASS' and result['events_checked'] == 3
    assert result['application_recovery_verified'] is False and result['approval_authority'] is False


@SQL
def test_dr_refuses_reusing_production_reader_or_source_endpoint(reader, monkeypatch):
    runtime = reader[-1]
    expected = capture_witness(runtime)
    from production_repository import ProductionRepository
    monkeypatch.setattr(ProductionRepository, 'connect', lambda self: runtime.connect())
    result = verify_isolated_target('postgres://target.invalid/dr',
        source_database_url='postgres://source.invalid/source', expected=expected,
        reader_factory=lambda connect: runtime)
    assert result['reason'] == 'RECOVERY_READER_TARGET_MISMATCH'
    result = verify_isolated_target('postgres://source.invalid/source',
        source_database_url='postgres://source.invalid/source', expected=expected,
        reader_factory=lambda connect: runtime)
    assert result['reason'] == 'RECOVERY_TARGET_IS_SOURCE'


@SQL
def test_dr_blocks_owner_target_before_factory_or_object_access(reader, monkeypatch):
    db, _, _, _, runtime = reader
    expected = capture_witness(runtime)
    from production_repository import ProductionRepository
    monkeypatch.setattr(ProductionRepository, 'connect', lambda self: db.connect())
    def forbidden(connect):
        raise AssertionError('Unsafe owner target must not reach cold objects')
    result = verify_isolated_target('postgres://target.invalid/dr',
        source_database_url='postgres://source.invalid/source', expected=expected, reader_factory=forbidden)
    assert result['reason'] == 'RECOVERY_TARGET_ROLE_UNSAFE'


@SQL
def test_dr_suppresses_unreviewed_factory_error_details(reader, monkeypatch):
    runtime = reader[-1]
    expected = capture_witness(runtime)
    from production_repository import ProductionRepository
    monkeypatch.setattr(ProductionRepository, 'connect', lambda self: runtime.connect())
    def failing(connect):
        raise RecoveryCheckError('synthetic-private-password-must-not-escape')
    result = verify_isolated_target('postgres://target.invalid/dr',
        source_database_url='postgres://source.invalid/source', expected=expected, reader_factory=failing)
    assert result['reason'] == 'RECOVERY_TARGET_UNVERIFIED'
    assert 'password' not in str(result)


@SQL
def test_recovery_verifies_original_signatures_not_only_previous_hash_links(reader):
    db, _, _, _, runtime = reader
    expected = capture_witness(runtime)
    db.execute('ALTER TABLE quant_app.evidence_ledger_events DISABLE TRIGGER evidence_ledger_no_update')
    db.execute("UPDATE quant_app.evidence_ledger_events SET payload='{}' WHERE sequence_no=2")
    db.execute('ALTER TABLE quant_app.evidence_ledger_events ENABLE TRIGGER evidence_ledger_no_update')
    with pytest.raises(RecoveryCheckError, match='ORIGINALS_UNVERIFIED'):
        verify_original_recovery(runtime, expected)
