"""Real disposable PostgreSQL root permissions and monotonic transaction checks."""
import os
from pathlib import Path

import pytest

from cold_catalog import EMPTY_ROOT
from test_archive_maintenance_sql import Pg

MIGRATION = Path(__file__).resolve().parents[1] / "supabase" / "migrations" / (
    "20261005194922_permanent_storage_control_review_only.sql")
pytestmark = pytest.mark.skipif(not os.environ.get("EQUITY_TEST_PGLITE_MODULE"),
                                reason="Local SQL harness not configured")


@pytest.fixture
def root_db():
    db = Pg()
    try:
        db.send({"script": "CREATE ROLE quant_app_runtime LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS;"})
        db.send({"script": MIGRATION.read_text()})
        yield db
    finally:
        db.send({"close": True})
        db.process.stdin.close()
        db.process.wait(timeout=10)


def bootstrap(db, scope="ledger"):
    db.execute("""INSERT INTO quant_storage.catalog_roots
        (scope,generation,root,receipt_sha256,published_at)
        VALUES (%s,0,%s,repeat('0',64),'2026-10-06T00:00:00Z')""", (scope, EMPTY_ROOT))


def advance(db, root="a"*64, receipt="b"*64, generation=1, before_root=EMPTY_ROOT,
            before_receipt="0"*64):
    db.execute("""UPDATE quant_storage.catalog_roots SET generation=%s,root=%s,
        receipt_sha256=%s,previous_root=%s,previous_receipt=%s,
        segment=repeat('c',64),key_id='fixture',published_at='2026-10-06T00:01:00Z'
        WHERE scope='ledger'""", (generation, root, receipt, before_root, before_receipt))


def test_migration_rerun_keeps_existing_anchor_and_does_not_bootstrap(root_db):
    assert root_db.execute("SELECT count(*) FROM quant_storage.catalog_roots").fetchone() == (0,)
    bootstrap(root_db)
    advance(root_db)
    root_db.send({"script": MIGRATION.read_text()})
    assert root_db.execute("SELECT generation,root FROM quant_storage.catalog_roots").fetchone() == (1,"a"*64)


def test_runtime_can_read_but_cannot_bootstrap_change_or_delete(root_db):
    bootstrap(root_db)
    root_db.execute("SET ROLE quant_app_runtime")
    assert root_db.execute("SELECT generation FROM quant_storage.catalog_roots").fetchone() == (0,)
    for sql in (
        "DELETE FROM quant_storage.catalog_roots",
        "UPDATE quant_storage.catalog_roots SET generation=1",
        "INSERT INTO quant_storage.catalog_roots SELECT * FROM quant_storage.catalog_roots"):
        with pytest.raises(RuntimeError, match="permission denied"):
            root_db.execute(sql)
    root_db.execute("RESET ROLE")


def test_archiver_can_advance_but_cannot_delete_or_bootstrap(root_db):
    bootstrap(root_db)
    root_db.execute("SET ROLE quant_storage_archiver")
    advance(root_db)
    assert root_db.execute("SELECT generation FROM quant_storage.catalog_roots").fetchone() == (1,)
    with pytest.raises(RuntimeError, match="permission denied"):
        root_db.execute("DELETE FROM quant_storage.catalog_roots")
    with pytest.raises(RuntimeError, match="permission denied"):
        root_db.execute("INSERT INTO quant_storage.catalog_roots SELECT * FROM quant_storage.catalog_roots")
    root_db.execute("RESET ROLE")


@pytest.mark.parametrize("kwargs", [
    {"generation": 2}, {"before_root": "d"*64}, {"before_receipt": "e"*64},
    {"root": EMPTY_ROOT}, {"receipt": "0"*64},
])
def test_wrong_predecessor_skip_noop_and_receipt_replay_leave_anchor_unchanged(root_db, kwargs):
    bootstrap(root_db)
    with pytest.raises(RuntimeError, match="PREDECESSOR_MISMATCH"):
        advance(root_db, **kwargs)
    assert root_db.execute("SELECT generation,root FROM quant_storage.catalog_roots").fetchone() == (0,EMPTY_ROOT)


def test_scope_bound_and_owner_delete_guard(root_db):
    bootstrap(root_db)
    bootstrap(root_db, "relations")
    with pytest.raises(RuntimeError, match="check constraint"):
        bootstrap(root_db, "unbounded-third-scope")
    with pytest.raises(RuntimeError, match="DELETE_FORBIDDEN"):
        root_db.execute("DELETE FROM quant_storage.catalog_roots")
    assert root_db.execute("SELECT count(*) FROM quant_storage.catalog_roots").fetchone() == (2,)


def test_crash_rolls_back_root_advance(root_db):
    bootstrap(root_db)
    with pytest.raises(RuntimeError, match="simulated crash"):
        with root_db.connect():
            advance(root_db)
            raise RuntimeError("simulated crash")
    assert root_db.execute("SELECT generation FROM quant_storage.catalog_roots").fetchone() == (0,)


def test_unknown_control_version_cannot_be_silently_downgraded(root_db):
    root_db.execute("COMMENT ON TABLE quant_storage.catalog_roots IS 'future-control-v2'")
    with pytest.raises(RuntimeError, match="VERSION_UNEXPECTED"):
        root_db.send({"script": MIGRATION.read_text()})
    root_db.execute("ROLLBACK")
    assert root_db.execute("SELECT obj_description('quant_storage.catalog_roots'::regclass,'pg_class')").fetchone() == ("future-control-v2",)


def test_unexpected_policy_fails_instead_of_leaving_public_access(root_db):
    root_db.execute("CREATE POLICY unexpected_public ON quant_storage.catalog_roots FOR SELECT USING(true)")
    with pytest.raises(RuntimeError, match="SHAPE_UNEXPECTED"):
        root_db.send({"script": MIGRATION.read_text()})
    root_db.execute("ROLLBACK")


def test_global_default_grant_leftover_is_explicitly_removed(root_db):
    root_db.execute("CREATE ROLE authenticated")
    root_db.execute("GRANT SELECT ON quant_storage.catalog_roots TO authenticated")
    root_db.send({"script": MIGRATION.read_text()})
    assert root_db.execute("SELECT has_table_privilege('authenticated','quant_storage.catalog_roots','SELECT')").fetchone() == (False,)


def test_unsafe_existing_role_is_not_repaired_silently(root_db):
    root_db.execute("ALTER ROLE quant_storage_archiver BYPASSRLS")
    with pytest.raises(RuntimeError, match="ARCHIVER_ROLE_UNSAFE"):
        root_db.send({"script": MIGRATION.read_text()})
    root_db.execute("ROLLBACK")
