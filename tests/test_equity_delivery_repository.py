from contextlib import contextmanager
import datetime as dt
import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from production_repository import ProductionRepository


def plain(value):
    if hasattr(value, "obj"):
        return value.obj
    if isinstance(value, dt.datetime):
        return value.isoformat()
    return value


class Connection:
    """Capture actual repository SQL and model its readbacks for replay on PG."""
    def __init__(self, rows):
        self.rows = rows
        self.operations = []
        self.commits = 0
        self.rollbacks = 0
        self.active = False
        self.fail_insert = False

    def execute(self, sql, params=()):
        if not self.active:
            self.operations.append(("BEGIN", []))
            self.active = True
        values = [plain(value) for value in params]
        self.operations.append((sql, values))
        row = None
        if "WHERE idempotency_key=%s" in sql:
            row = self.rows.get(params[0])
        elif "SELECT sequence_no,event_hash" in sql:
            candidates = [r for r in self.rows.values() if r[1] == params[0]]
            if candidates:
                previous = max(candidates, key=lambda r: r[2])
                row = (previous[2], previous[11])
        elif "INSERT INTO" in sql:
            if self.fail_insert:
                raise OSError("synthetic insert error")
            self.rows[params[8]] = values
        return SimpleNamespace(fetchone=lambda: row)

    def commit(self):
        self.commits += 1
        self.operations.append(("COMMIT", []))
        self.active = False

    def rollback(self):
        self.rollbacks += 1
        self.operations.append(("ROLLBACK", []))
        self.active = False


def repo():
    repository = ProductionRepository("postgresql://unused-test-placeholder")
    repository._schema_ready = True
    rows, connections = {}, []
    @contextmanager
    def connect():
        connection = Connection(rows)
        connections.append(connection)
        yield connection
    repository.connect = connect
    return repository, connections


def request(key):
    return dict(aggregate_id="equity:test", event_type="DECISION_EVALUATED",
                payload={"identifiers": {"asset_class": "equity"}, "entry": 123},
                effective_at="2026-09-12T04:00:00+00:00", idempotency_key=key)


def test_batch_reuses_connection_but_preserves_per_event_commit_and_idempotency():
    repository, connections = repo()
    with repository.evidence_delivery_session() as send:
        first = send(**request("one"))
        second = send(**request("two"))
        duplicate = send(**request("one"))
        tampered = request("one")
        tampered["payload"]["entry"] = 124
        with pytest.raises(ValueError, match="different durable evidence"):
            send(**tampered)
    assert len(connections) == 1
    assert connections[0].commits == 4  # session setup + 3 event transactions
    assert connections[0].rollbacks == 1
    assert first["sequence_no"] == 1 and second["sequence_no"] == 2
    assert duplicate["duplicate"] and duplicate["event_id"] == first["event_id"]


def test_legacy_calls_still_use_one_connection_each_without_sender_settings():
    repository, connections = repo()
    repository.append_evidence_event(**request("one"))
    repository.append_evidence_event(**request("two"))
    assert len(connections) == 2
    assert all(connection.commits == 1 for connection in connections)
    assert not any("SET statement_timeout" in sql for c in connections for sql, _ in c.operations)


def test_failed_session_transaction_rolls_back():
    repository, connections = repo()
    with repository.evidence_delivery_session() as send:
        connections[0].fail_insert = True
        with pytest.raises(OSError):
            send(**request("one"))
    assert connections[0].rollbacks == 1
    assert not connections[0].active


@pytest.mark.skipif(not os.environ.get("EQUITY_TEST_PGLITE_MODULE"), reason="Local PostgreSQL harness not configured")
def test_sender_repository_sql_executes_on_postgres_with_chain_and_duplicate_readback():
    repository, connections = repo()
    with repository.evidence_delivery_session() as send:
        first = send(**request("one"))
        second = send(**request("two"))
        send(**request("one"))
    script = r'''
const {PGlite} = require(process.argv[1]);
const fs = require('fs');
(async () => {
 const db = new PGlite();
 try {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  await db.exec(`CREATE SCHEMA quant_app;
   CREATE TABLE quant_app.evidence_ledger_events (
    event_id uuid PRIMARY KEY, aggregate_id text NOT NULL, sequence_no integer NOT NULL,
    event_type text NOT NULL, recorded_at timestamptz NOT NULL, effective_at timestamptz NOT NULL,
    source text NOT NULL, actor_id text NOT NULL, idempotency_key text UNIQUE NOT NULL,
    payload jsonb NOT NULL, previous_hash text NOT NULL, event_hash text NOT NULL,
    hash_algorithm text NOT NULL, schema_version integer NOT NULL, key_id text,
    UNIQUE(aggregate_id, sequence_no));`);
  for (const [sql, params] of input.operations) {
   let n=0;
   await db.query(sql.replace(/%s/g, () => '$' + (++n)), params);
  }
  const rows=(await db.query('SELECT * FROM quant_app.evidence_ledger_events ORDER BY sequence_no')).rows;
  if (rows.length !== 2 || rows[0].event_id !== input.first.event_id || rows[1].event_id !== input.second.event_id)
    throw Error('duplicate/readback mismatch');
  if (rows[1].previous_hash !== rows[0].event_hash || rows[1].payload.entry !== 123)
    throw Error('chain/payload mismatch');
  console.log('SENDER_PG_CHAIN_READBACK_PASS');
 } finally {await db.close();}
})().catch(e => {console.error(e.message); process.exitCode=1;});
'''
    result = subprocess.run(["node", "-e", script, os.environ["EQUITY_TEST_PGLITE_MODULE"]],
                            input=json.dumps({"operations": connections[0].operations,
                                              "first": first, "second": second}),
                            text=True, capture_output=True, timeout=90)
    assert result.returncode == 0, result.stderr
    assert "SENDER_PG_CHAIN_READBACK_PASS" in result.stdout
