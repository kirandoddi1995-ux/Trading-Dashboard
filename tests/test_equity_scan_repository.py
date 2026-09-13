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


@pytest.mark.parametrize('storage,checkpoint,expected', [
    ((True,) * 5, ('run', 'ABC', {'score': 1}, None), 'PASS'),
    ((True,) * 5, None, 'UNAVAILABLE'),
    ((False, True, True, True, True), ('run', 'ABC', {}, None), 'UNAVAILABLE'),
    ((True, True, True, False, True), ('run', 'ABC', {}, None), 'UNAVAILABLE'),
    ((True,) * 5, ('run', 'ABC', 'not an object', None), 'UNAVAILABLE'),
])
def test_recovery_health_reads_only_existing_committed_data(storage, checkpoint, expected):
    conn = Connection(fetchone=[storage, checkpoint])
    assert repository(conn).recovery_health()['status'] == expected
    assert all(sql.startswith('SELECT') for sql, _ in conn.calls)
    assert conn.commits == 0
    assert 'bool_and(has_table_privilege' in conn.calls[0][0]
    assert "c.status='COMPLETE'" in conn.calls[1][0]


@pytest.mark.skipif(not os.environ.get('EQUITY_TEST_PGLITE_MODULE'), reason='Local PostgreSQL harness not configured')
def test_recovery_health_sql_on_postgres_requires_every_privilege_and_reads_checkpoint():
    conn = Connection(fetchone=[(True,) * 5, None])
    repository(conn).recovery_health()
    migration = (Path(__file__).resolve().parents[1] / 'sql' /
                 'equity_scan_recovery_and_manual_review.sql').read_text(encoding='utf-8')
    script = r"""
const {PGlite} = require(process.argv[1]);
let input='';
process.stdin.on('data', c => input += c);
process.stdin.on('end', async () => {
 const db = new PGlite();
 try {
  const config=JSON.parse(input);
  await db.exec(`CREATE ROLE quant_app_runtime LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS;
    CREATE ROLE equity_research_collector LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS;
    CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role;`);
  await db.exec(config.migration);
  await db.exec('SET ROLE quant_app_runtime');
  if ((await db.query(config.queries[1])).rows.length !== 0) throw Error('Invented checkpoint');
  await db.exec(`INSERT INTO equity_operations.scan_runs
    (run_id,owner_id,signature,scan_mode,horizon_sessions,status,fencing_token,started_at,heartbeat_at,metadata)
    VALUES ('fixture','owner','sig','Quick',15,'RUNNING',1,now(),now(),'{}');
    INSERT INTO equity_operations.scan_candidates
    (run_id,instrument,item,status,attempt_no,result,updated_at)
    VALUES ('fixture','ABC','{}','COMPLETE',1,'{"score":1}',now());`);
  const saved=await db.query(config.queries[1]);
  if(saved.rows.length !== 1 || saved.rows[0].result.score !== 1) throw Error('Readback failed');
  // PGlite can report fsync=false because this test database is in memory.
  const before=await db.query(config.queries[0]);
  const values=Object.values(before.rows[0]);
  // Query column aliases are supplied below so no duplicate names are lost.
  if(before.rows[0].run_permissions !== true) throw Error('Expected runtime grants');
  await db.exec('RESET ROLE; REVOKE UPDATE ON equity_operations.scan_runs FROM quant_app_runtime; SET ROLE quant_app_runtime');
  const after=await db.query(config.queries[0]);
  if(after.rows[0].run_permissions !== false) throw Error('SELECT masked missing UPDATE');
  console.log('RECOVERY_READBACK_SQL_PASS');
 } catch(e) { console.error(e.message); process.exitCode=1; }
 finally { await db.close(); }
});
"""
    result = subprocess.run(['node', '-e', script, os.environ['EQUITY_TEST_PGLITE_MODULE']],
        input=json.dumps({'migration': migration, 'queries': [sql for sql, _ in conn.calls]}),
        capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    assert 'RECOVERY_READBACK_SQL_PASS' in result.stdout


def test_order_intent_requires_stored_review_and_serializes_owner():
    from test_equity_order_records import reviewed
    from test_equity_execution_policy import NOW
    signal, review = reviewed()
    conn = Connection(fetchone=[None, (review,)])
    record = repository(conn).save_order_intent(signal, review, owner_id="owner", now=NOW)
    assert record["production_evidence_eligible"] is False
    assert "pg_advisory_xact_lock" in conn.calls[0][0]
    assert "INSERT INTO equity_operations.order_intents" in conn.calls[-1][0]
    assert conn.commits == 1
    for rows in ([(1,)], [None, None]):
        blocked = Connection(fetchone=rows)
        with pytest.raises(ValueError):
            repository(blocked).save_order_intent(signal, review, owner_id="owner", now=NOW)
        assert not any("INSERT INTO" in sql for sql, _ in blocked.calls)


def test_reconciliation_retry_is_idempotent_and_conflicting_actuals_are_rejected():
    from test_equity_order_records import intent
    from test_equity_execution_policy import NOW
    from equity_order_records import build_order_result
    order = intent()
    kwargs = dict(status="FILLED", filled_quantity=1, average_fill_price=100,
                  broker_order_id="fixture", broker_event_at=NOW, confirmed=True, now=NOW)
    prior = build_order_result(order, **kwargs)
    conn = Connection(fetchone=[(order,), (prior,)])
    assert repository(conn).reconcile_order(order["intent_id"], owner_id="owner", **kwargs) == prior
    assert not any("INSERT INTO" in sql for sql, _ in conn.calls)
    with pytest.raises(ValueError, match="immutable"):
        repository(Connection(fetchone=[(order,), (prior,)])).reconcile_order(
            order["intent_id"], owner_id="owner", **{**kwargs, "average_fill_price": 101})


@pytest.mark.skipif(not os.environ.get("EQUITY_TEST_PGLITE_MODULE"), reason="Local PostgreSQL harness not configured")
def test_order_migration_enforces_real_database_isolation_and_immutability():
    root = Path(__file__).resolve().parents[1]
    migrations = "\n".join((root / "sql" / name).read_text(encoding="utf-8") for name in (
        "equity_scan_recovery_and_manual_review.sql", "equity_order_reconciliation_draft.sql"))
    script = r"""
const {PGlite} = require(process.argv[1]);
let input=''; process.stdin.on('data', d=>input+=d);
process.stdin.on('end',async()=>{
 const db = new PGlite();
 try {
  await db.exec(`CREATE ROLE quant_app_runtime LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS;
   CREATE ROLE equity_research_collector LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS;
   CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role;`);
  await db.exec(input);
  await db.exec('SET ROLE quant_app_runtime');
  const now = new Date().toISOString();
  const reviewId='00000000-0000-0000-0000-000000000001';
  const intentId='00000000-0000-0000-0000-000000000002';
  const resultId='00000000-0000-0000-0000-000000000003';
  const review={purpose:'LIVE_EQUITY_MANUAL_QUOTE_CHECK',decision_id:'d',decision_digest:'a'.repeat(64),
   instrument:'ABC',status:'CONFIRMED',system_allow_trade:true,reviewer:'owner',attested_at:now,
   primary_quote_observed_at:now,governance_decision_at:now,
   execution_plan:{order_type:'LIMIT',quantity:1,limit_price:100}};
  await db.query(`INSERT INTO equity_operations.manual_quote_reviews
   (review_id,decision_id,decision_digest,instrument,reviewer,attested_at,secondary_platform,
    secondary_price,primary_price,difference_bps,status,payload)
   VALUES ($1,'d',$2,'ABC','owner',$3,'fixture',100,100,0,'CONFIRMED',$4)`,
   [reviewId,review.decision_digest,now,JSON.stringify(review)]);
  const intent={purpose:'USER_REPORTED_ORDER_INTENT',production_evidence_eligible:false,intent_id:intentId,
    owner_id:'owner',review_id:reviewId,quantity:1,limit_price:100,decision_id:'d',
    decision_digest:review.decision_digest,created_at:now};
  await db.query(`INSERT INTO equity_operations.order_intents VALUES($1,'owner',$2,$3,$4)`,
   [intentId,reviewId,now,JSON.stringify(intent)]);
  let blocked=0;
  const deny=async(sql,params=[])=>{try {await db.query(sql,params);} catch(e){blocked++;return;}
    throw Error('Unexpectedly allowed: '+sql);};
  await deny(`INSERT INTO equity_operations.order_intents VALUES($1,'owner',$2,$3,$4)`,
   ['00000000-0000-0000-0000-000000000004',reviewId,now,JSON.stringify({...intent,intent_id:'00000000-0000-0000-0000-000000000004'})]);
  const result={purpose:'USER_REPORTED_BROKER_RESULT',production_evidence_eligible:false,result_id:resultId,
   intent_id:intentId,owner_id:'owner',confirmed:true,status:'FILLED',filled_quantity:1,average_fill_price:100,
   broker_order_id:'fixture',broker_event_at:now};
  await deny(`INSERT INTO equity_operations.order_results(result_id,intent_id,owner_id,payload) VALUES($1,$2,'owner',$3)`,
   [resultId,intentId,JSON.stringify({...result,production_evidence_eligible:true})]);
  await db.query(`INSERT INTO equity_operations.order_results(result_id,intent_id,owner_id,payload) VALUES($1,$2,'owner',$3)`,
   [resultId,intentId,JSON.stringify(result)]);
  await deny('UPDATE equity_operations.order_results SET owner_id=owner_id');
  await deny('DELETE FROM equity_operations.order_results');
  await db.exec('RESET ROLE; SET ROLE equity_research_collector');
  await deny('SELECT * FROM equity_operations.order_intents');
  await deny('SELECT * FROM equity_operations.order_results');
  await deny(`INSERT INTO equity_operations.order_results(result_id,intent_id,owner_id,payload) VALUES($1,$2,'owner',$3)`,
   [resultId,intentId,JSON.stringify(result)]);
  await db.exec('RESET ROLE');
  await deny('UPDATE equity_operations.order_intents SET owner_id=owner_id');
  if(blocked!==8) throw Error('Missing isolation assertion');
  console.log('ORDER_ISOLATION_PASS');
 } catch(e) {console.error(e.message);process.exitCode=1;} finally {await db.close();}
});
"""
    result = subprocess.run(["node", "-e", script, os.environ["EQUITY_TEST_PGLITE_MODULE"]],
                            input=migrations, text=True, capture_output=True, timeout=90)
    assert result.returncode == 0, result.stderr
    assert "ORDER_ISOLATION_PASS" in result.stdout


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
