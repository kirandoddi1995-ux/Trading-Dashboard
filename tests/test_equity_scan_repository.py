from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess

import pytest

from equity_scan_repository import EquityScanRepository


class Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.rowcount = connection.rowcount

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, sql, params=()):
        self.connection.calls.append((" ".join(sql.split()), params))
        self.rowcount = self.connection.rowcount

    def fetchone(self):
        return self.connection.fetchone_values.pop(0) if self.connection.fetchone_values else None

    def fetchall(self):
        return self.connection.fetchall_values.pop(0) if self.connection.fetchall_values else []


class Connection:
    def __init__(self, *, rowcount=1, fetchone=(), fetchall=()):
        self.calls = []
        self.rowcount = rowcount
        self.fetchone_values = list(fetchone)
        self.fetchall_values = list(fetchall)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return Cursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def repository(connection):
    @contextmanager
    def connect():
        yield connection
    return EquityScanRepository(connect)


def test_candidate_checkpoint_is_fenced_by_current_run_token():
    conn = Connection(rowcount=1)
    repo = repository(conn)
    assert repo.checkpoint_candidate(
        run_id="run", instrument="ABC", fencing_token=7,
        result={"Ticker": "ABC"}, quote_observed_at="2026-09-13T04:00:00+00:00",
        governance_decision_at="2026-09-13T04:00:01+00:00",
    )
    sql, params = conn.calls[0]
    assert "r.fencing_token=%s" in sql
    assert "c.status<>'COMPLETE'" in sql
    assert params[-1] == 7
    assert conn.commits == 1


def test_failed_fence_is_reported_without_false_success():
    conn = Connection(rowcount=0)
    assert not repository(conn).checkpoint_candidate(
        run_id="run", instrument="ABC", fencing_token=1, rejection={"category": "Data"})


def test_recovery_claim_increments_fence_and_returns_only_unfinished_items():
    conn = Connection(fetchone=[(3, {"scan_mode": "Quick"})],
                      fetchall=[[({"ticker": "ABC"},), ("XYZ",)]])
    claimed = repository(conn).claim_recovery("run", "owner")
    assert claimed == {
        "fencing_token": 3, "metadata": {"scan_mode": "Quick"},
        "items": [{"ticker": "ABC"}, "XYZ"],
    }
    assert "fencing_token=fencing_token+1" in conn.calls[0][0]
    assert "status<>'COMPLETE'" in conn.calls[1][0]


def test_manual_review_is_append_only_at_repository_boundary():
    conn = Connection(rowcount=1)
    review = {
        "review_id": "00000000-0000-0000-0000-000000000001",
        "decision_id": "decision", "decision_digest": "a" * 64,
        "scan_run_id": "run", "instrument": "ABC", "reviewer": "owner",
        "attested_at": "2026-09-13T04:00:00+00:00", "secondary_platform": "broker",
        "secondary_price": 100.0, "source_quote_observed_at": None,
        "primary_price": 100.0, "difference_bps": 0.0, "status": "CONFIRMED",
        "purpose": "LIVE_EQUITY_MANUAL_QUOTE_CHECK", "system_allow_trade": True,
    }
    assert repository(conn).save_manual_review(review)
    assert "INSERT INTO equity_operations.manual_quote_reviews" in conn.calls[0][0]
    assert not any("UPDATE equity_operations.manual_quote_reviews" in call[0] for call in conn.calls)


def test_migration_grants_runtime_only_and_explicitly_denies_research_role():
    sql = (Path(__file__).resolve().parents[1] / "sql" /
           "equity_scan_recovery_and_manual_review.sql").read_text(encoding="utf-8")
    assert "GRANT USAGE ON SCHEMA equity_operations TO quant_app_runtime" in sql
    assert "FROM anon, authenticated, service_role, equity_research_collector" in sql
    assert "GRANT SELECT, INSERT, UPDATE ON equity_operations.scan_runs" in sql
    assert "GRANT SELECT, INSERT ON equity_operations.manual_quote_reviews TO quant_app_runtime" in sql
    assert "GRANT" not in "\n".join(
        line for line in sql.splitlines()
        if "equity_research_collector" in line and "GRANT" in line
    )
    assert "INSERT INTO equity_research" not in sql
    assert "UPDATE equity_research" not in sql
    assert "DELETE FROM equity_research" not in sql


@pytest.mark.skipif(
    not os.environ.get("EQUITY_TEST_PGLITE_MODULE"),
    reason="PostgreSQL-engine test harness not configured",
)
def test_migration_executes_and_research_role_cannot_read_operations_schema():
    module = os.environ["EQUITY_TEST_PGLITE_MODULE"]
    migration = (Path(__file__).resolve().parents[1] / "sql" /
                 "equity_scan_recovery_and_manual_review.sql").read_text(encoding="utf-8")
    script = r"""
const {PGlite} = require(process.argv[1]);
let input = '';
process.stdin.on('data', chunk => input += chunk);
process.stdin.on('end', async () => {
  const db = new PGlite();
  try {
    await db.exec(`
      CREATE ROLE quant_app_runtime LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS
        NOCREATEDB NOCREATEROLE NOREPLICATION;
      CREATE ROLE equity_research_collector LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS
        NOCREATEDB NOCREATEROLE NOREPLICATION;
      CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role;
    `);
    await db.exec(input);
    await db.exec('SET ROLE quant_app_runtime');
    await db.query(`INSERT INTO equity_operations.scan_runs
      (run_id,owner_id,signature,scan_mode,horizon_sessions,status,fencing_token,
       started_at,heartbeat_at,metadata)
      VALUES ('run','owner','sig','Quick',15,'RUNNING',1,now(),now(),'{}')`);
    const visible = await db.query('SELECT count(*)::int AS n FROM equity_operations.scan_runs');
    await db.exec('RESET ROLE; SET ROLE equity_research_collector');
    let denied = false;
    try { await db.query('SELECT * FROM equity_operations.scan_runs'); }
    catch (_) { denied = true; }
    if (visible.rows[0].n !== 1 || !denied) throw Error('permission isolation failed');
    console.log(JSON.stringify({runtime_rows: visible.rows[0].n, research_denied: denied}));
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  } finally {
    await db.close();
  }
});
"""
    result = subprocess.run(
        ["node", "-e", script, module], input=migration, text=True,
        capture_output=True, timeout=90,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"runtime_rows": 1, "research_denied": True}


def test_production_readiness_does_not_read_operational_or_research_tables():
    root = Path(__file__).resolve().parents[1]
    sources = "\n".join((root / name).read_text(encoding="utf-8") for name in (
        "evidence_progress.py", "model_training_pipeline.py", "prediction_validation.py",
    ))
    assert "equity_operations" not in sources
    assert "manual_quote_reviews" not in sources
