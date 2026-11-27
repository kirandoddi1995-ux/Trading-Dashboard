"""Nightly DB maintenance check: the pg_cron VACUUM (job 8) leaves its trace, one alert, never raises; job 7 retirement SQL."""
import ast
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import types

import pytest

import db_maintenance_watch as dm
import run_failure_alert
import run_watchdog

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
NOW = datetime(2026, 11, 24, 22, 30, tzinfo=UTC)           # the 04:00 IST slot
LAST_NIGHT = NOW - timedelta(hours=23, minutes=45)          # previous 22:45 UTC VACUUM
ENV = {"DATABASE_URL": "postgresql://runtime@db.example/postgres",
       "TELEGRAM_BOT_TOKEN": "123456789:" + "A" * 35, "TELEGRAM_CHAT_ID": "-1001234567890"}
WORKFLOW = (ROOT / ".github/workflows/run-watchdog.yml").read_text(encoding="utf-8")
RETIRE_FILE = (ROOT / "supabase/retire-purge-raw-quotes-cron.sql").read_text(encoding="utf-8")
JOB7 = "UPDATE quant_app.market_quotes SET raw = NULL WHERE observed_at < now() - interval '3 days'"
INSTALL_IF = ("if: ${{ !cancelled() && steps.watch.outcome != 'skipped' && "
              "(github.event.schedule || inputs.slot) != '0 6 * * 1-5' && "
              "(github.event.schedule || inputs.slot) != '30 10 * * 1-5' }}")
CHECK_IF = "if: ${{ !cancelled() && steps.driver.outcome == 'success' }}"


def _archive_growing_tables():
    """archive_maintenance.GROWING_TABLES read from source (importing it needs psycopg)."""
    tree = ast.parse((ROOT / "archive_maintenance.py").read_text(encoding="utf-8"))
    return next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                and [getattr(t, "id", None) for t in node.targets] == ["GROWING_TABLES"])


def _vacuums(**changes):
    """pg_stat rows for the four tables, last night's VACUUM unless changed (reversed order: no ORDER BY)."""
    last = {name: LAST_NIGHT for name in dm.TABLES} | changes
    return [(name, last[name]) for name in reversed(dm.TABLES)]


def _sent(calls):
    """A Telegram transport that records the text and accepts it."""
    def post(path, body):
        """Echo the text back the way Telegram does."""
        text = json.loads(body)["text"]
        calls.append(text)
        return 200, json.dumps({"ok": True, "result": {"text": text, "chat": {"id": -1001234567890}}}).encode()
    return post


def _check(reply, env=ENV, calls=None, waits=None):
    """check() with a fixed read, clock and transport; a list of replies is consumed one read at a time."""
    def measure_fn(url):
        """Return (or raise) the next prepared reply."""
        item = reply.pop(0) if isinstance(reply, list) else reply
        if isinstance(item, Exception):
            raise item
        return item
    return dm.check(env, measure_fn=measure_fn, post=_sent([] if calls is None else calls),
                    sleep=(waits if waits is not None else []).append, clock=lambda: NOW)


def test_vacuum_ok_prints_ok_and_sends_nothing():
    """Every table vacuumed 23 h 45 m ago: one OK line, no message."""
    calls = []
    assert _check((NOW, _vacuums()), calls=calls) == ["VACUUM (job 8): OK"]
    assert calls == []


def test_vacuum_age_boundary_is_26_hours():
    """Exactly 26 h is OK; one second more is LATE with the whole hours shown."""
    assert dm.assess(NOW, _vacuums(market_quotes=NOW - timedelta(hours=26))) is None
    assert dm.assess(NOW, _vacuums(market_quotes=NOW - timedelta(hours=26, seconds=1))) == (
        "VACUUM (pg_cron job 8) late: market_quotes 26 h ago")


def test_late_vacuum_gives_one_message_naming_each_table_in_job_order():
    """A stale table and a table with no VACUUM recorded: one message, fixed shape, IST time."""
    calls = []
    reply = (NOW, _vacuums(universe_membership=None, scanner_observations=NOW - timedelta(hours=49, minutes=59)))
    assert _check(reply, calls=calls) == ["VACUUM (job 8): LATE", "alert: RUN_ALERT_SENT"]
    assert calls == ["LATE: nightly DB maintenance (25 Nov 04:00 IST) - VACUUM (pg_cron job 8) late: "
                     "scanner_observations 49 h ago, universe_membership none recorded. "
                     "Check the job history: Supabase > Integrations > Cron."]


def test_a_future_vacuum_time_is_not_late():
    """A clock skew that puts last_vacuum after the read is not an alert."""
    assert dm.assess(NOW, _vacuums(market_quotes=NOW + timedelta(minutes=5))) is None


@pytest.mark.parametrize("now,vacuums", [
    (NOW.replace(tzinfo=None), _vacuums()),                       # naive database time
    ("2026-11-24 22:30", _vacuums()),
    (NOW, _vacuums()[:3]),                                        # a table missing
    (NOW, _vacuums() + [("other", LAST_NIGHT)]),                  # an extra table
    (NOW, _vacuums()[1:2] + _vacuums()[1:]),                      # a duplicate in place of a table
    (NOW, _vacuums() + _vacuums()[:1]),                           # all four plus a duplicate row
    (NOW, _vacuums(market_quotes=LAST_NIGHT.replace(tzinfo=None))),
    (NOW, _vacuums(market_quotes="2026-11-23")),
    (NOW, [row + (1,) for row in _vacuums()]),                    # wrong row shape
    (NOW, None),
])
def test_unexpected_replies_are_invalid_not_ok(now, vacuums):
    """Anything but the expected shapes and types fails closed, loudly, without a retry."""
    calls, waits = [], []
    lines = _check((now, vacuums), calls=calls, waits=waits)
    assert lines == ["nightly DB maintenance: CHECK_FAILED MAINTENANCE_MEASUREMENT_INVALID", "alert: RUN_ALERT_SENT"]
    assert waits == [] and len(calls) == 1


def test_a_reply_that_is_not_a_pair_is_invalid():
    """measure() returning something else entirely is invalid too."""
    assert dm.read(ENV, lambda url: "x", lambda s: None) == "MAINTENANCE_MEASUREMENT_INVALID"


@pytest.mark.parametrize("url", ["", "   "])
def test_missing_connection_alerts(url):
    """No DATABASE_URL (secret missing) is a loud failure, never a silent OK; nothing is read."""
    calls = []
    lines = _check(AssertionError("must not read"), env=ENV | {"DATABASE_URL": url}, calls=calls)
    assert lines == ["nightly DB maintenance: CHECK_FAILED DATABASE_CONNECTION_REQUIRED", "alert: RUN_ALERT_SENT"]
    assert calls == ["CHECK FAILED: nightly DB maintenance check (25 Nov 04:00 IST) could not read the database "
                     "(DATABASE_CONNECTION_REQUIRED); VACUUM (pg_cron job 8) is unchecked."]


def test_one_failed_read_is_retried_after_20_seconds():
    """A transient connection failure, then a good read: OK, no message, one 20 s wait."""
    calls, waits = [], []
    assert _check([OSError("blip"), (NOW, _vacuums())], calls=calls, waits=waits) == ["VACUUM (job 8): OK"]
    assert waits == [20] and calls == []


def test_two_failed_reads_alert_once_without_the_error_text():
    """Both reads fail: CHECK_FAILED with a fixed code; the provider's error text never reaches the message."""
    calls, waits = [], []
    lines = _check([OSError("host db.secret-host"), RuntimeError("password=hunter2")], calls=calls, waits=waits)
    assert lines == ["nightly DB maintenance: CHECK_FAILED MAINTENANCE_CHECK_UNAVAILABLE", "alert: RUN_ALERT_SENT"]
    assert waits == [20] and len(calls) == 1
    assert "secret-host" not in calls[0] and "hunter2" not in calls[0] and "MAINTENANCE_CHECK_UNAVAILABLE" in calls[0]


def test_alert_without_telegram_secrets_names_them_only():
    """Not configured: the status names the missing secrets; the problem is still printed."""
    lines = _check((NOW, _vacuums(market_quotes=None)), env={"DATABASE_URL": "postgresql://x"})
    assert lines == ["VACUUM (job 8): LATE",
                     "alert: RUN_ALERT_NOT_CONFIGURED missing=TELEGRAM_BOT_TOKEN,TELEGRAM_CHAT_ID"]


@pytest.mark.parametrize("lines,code", [
    (["VACUUM (job 8): OK"], 0),
    (["VACUUM (job 8): LATE", "alert: RUN_ALERT_SENT"], 0),
    (["nightly DB maintenance: CHECK_FAILED X", "alert: RUN_ALERT_DELIVERY_UNVERIFIED"], 1),
    (["VACUUM (job 8): LATE", "alert: RUN_ALERT_NOT_CONFIGURED missing=X"], 1),
])
def test_main_prints_and_exits_1_only_when_a_needed_alert_was_not_delivered(monkeypatch, capsys, lines, code):
    """CLI: prints every line; a problem nobody was told about turns the run red."""
    monkeypatch.setattr(dm, "check", lambda env: lines)
    assert dm.main([], env={}) == code
    assert capsys.readouterr().out == "".join(line + "\n" for line in lines)


def test_main_default_check_uses_the_environment(monkeypatch, capsys):
    """Without injected env, main reads os.environ (no DATABASE_URL and no Telegram here -> loud, exit 1)."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert dm.main([]) == 1
    assert "CHECK_FAILED DATABASE_CONNECTION_REQUIRED" in capsys.readouterr().out


def test_measure_is_read_only_tls_with_short_limits(monkeypatch):
    """One TLS connection, read-only and not autocommit at every statement, timeouts first, then the SELECTs."""
    seen = {"executed": []}

    class Cursor:
        """Records statements; replies like psycopg."""
        def __enter__(self):
            """Context entry."""
            return self

        def __exit__(self, *exc):
            """Context exit."""
            return False

        def execute(self, sql, params=None):
            """Record the statement and the session state then."""
            seen["executed"].append((sql, params, connection.read_only, connection.autocommit))

        def fetchone(self):
            """The database time row."""
            return (NOW,)

        def fetchall(self):
            """The VACUUM rows."""
            return _vacuums()

    class Connection:
        """A connection whose read_only / autocommit flags are observable."""
        read_only = False
        autocommit = False   # SET LOCAL needs the implicit transaction: autocommit would drop the limits

        def __enter__(self):
            """Context entry."""
            return self

        def __exit__(self, *exc):
            """Context exit."""
            return False

        def cursor(self):
            """One cursor."""
            return Cursor()

    connection = Connection()

    def connect(url, **kwargs):
        """Record the connection arguments."""
        seen["connect"] = (url, kwargs)
        return connection

    monkeypatch.setitem(sys.modules, "psycopg", types.SimpleNamespace(connect=connect))
    assert dm.measure("postgresql://x") == (NOW, _vacuums())
    assert seen["connect"] == ("postgresql://x", {"connect_timeout": 10, "sslmode": "require"})
    assert seen["executed"] == [("SET LOCAL statement_timeout='15s'", None, True, False),
                                ("SET LOCAL lock_timeout='2s'", None, True, False),
                                ("SELECT now()", None, True, False),
                                (dm.VACUUM_SQL, (list(dm.TABLES),), True, False)]


def test_query_is_select_only_and_reads_last_vacuum():
    """No write keyword; manual last_vacuum (not autovacuum) of quant_app tables from pg_catalog."""
    assert dm.VACUUM_SQL.startswith("SELECT ")
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|GRANT|VACUUM|COPY)\b", dm.VACUUM_SQL)
    assert "s.last_vacuum" in dm.VACUUM_SQL and "autovacuum" not in dm.VACUUM_SQL
    assert "pg_catalog.pg_stat_user_tables s ON s.schemaname = 'quant_app'" in dm.VACUUM_SQL
    assert "unnest(%s::text[])" in dm.VACUUM_SQL


def test_limit_covers_a_daily_job_and_the_tables_are_job_8s():
    """26 h covers the 23 h 45 m gap at 22:30 UTC with room for a late run; the tables are the archive's growing set."""
    assert timedelta(hours=24) < dm.VACUUM_AGE <= timedelta(hours=26)
    assert set(dm.TABLES) == {"market_quotes", "scanner_observations", "universe_membership_versions",
                              "universe_membership"} == set(_archive_growing_tables())
    assert len(dm.TABLES) == 4


def test_workflow_runs_the_check_in_every_run_but_the_scan_slots():
    """The install skips the scan slots and a failed checkout; the check needs a good install; only it sees the DB secret."""
    scans = {cron for cron, slot in run_watchdog.WATCHES.items() if slot is not run_watchdog.ARCHIVE}
    assert scans == {"0 6 * * 1-5", "30 10 * * 1-5"} and run_watchdog.WATCHES["30 22 * * *"] is run_watchdog.ARCHIVE
    steps = WORKFLOW.split("      - ")
    install = next(s for s in steps if s.startswith("name: Install the database driver"))
    check = next(s for s in steps if s.startswith("name: Check the nightly DB maintenance job"))
    assert INSTALL_IF in install and "id: driver" in install and CHECK_IF in check
    watch = next(s for s in steps if s.startswith("name: Check the expected runs"))
    assert watch.splitlines()[1] == "        id: watch" and "if:" not in watch and "continue-on-error" not in watch
    runs = [line for line in watch.splitlines() if line.strip().startswith("run:")]
    assert runs == ["        run: python run_watchdog.py"]   # its exit code reaches the job
    assert "continue-on-error" not in WORKFLOW and "|| true" not in WORKFLOW and "timeout-minutes: 8" in WORKFLOW
    assert 'python -m pip install --quiet -c constraints.txt "psycopg[binary]"' in install
    assert "run: python db_maintenance_watch.py" in check
    assert "DATABASE_URL: ${{ secrets.DATABASE_URL }}" in check
    assert WORKFLOW.count("secrets.DATABASE_URL") == 1 and "DATABASE_MIGRATION_URL" not in WORKFLOW
    assert WORKFLOW.index("run: python run_watchdog.py") < WORKFLOW.index("name: Install the database driver")
    assert "contents: read" in WORKFLOW and "write" not in WORKFLOW.split("permissions:")[1].split("concurrency:")[0]


def test_workflow_alerts_when_the_watchdog_run_itself_fails():
    """A failed install or check step is loud: the last step alerts on failure or cancel, with a valid label."""
    last = WORKFLOW.rstrip().split("      - ")[-1]
    assert last.startswith("name: Phone alert when this watchdog run fails")
    assert "if: failure() || cancelled()" in last and "JOB_STATUS: ${{ job.status }}" in last
    assert "run: python3 run_failure_alert.py --label run-watchdog" in last   # works even if setup-python failed
    workflow = re.search(r"^name: (.+)$", WORKFLOW, re.MULTILINE)[1].strip()
    env = {"GITHUB_WORKFLOW": workflow, "GITHUB_REPOSITORY": "owner/repo", "GITHUB_RUN_ID": "1"}
    assert run_failure_alert.message(env, "run-watchdog", NOW).startswith("FAILED: Run watchdog (run-watchdog)")


def test_retire_sql_prechecks_the_recorded_job_and_only_unschedules_it():
    """The owner SQL stops unless job 7 is exactly as recorded, then removes only that job."""
    sql = RETIRE_FILE.replace("''", "'")
    code = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    assert code.index("raise exception") < code.index("cron.unschedule(")
    precheck = code.split("do $$")[1].split("end $$;")[0]
    assert f"command = '{JOB7}'" in precheck
    assert "jobname = 'purge_raw_quotes' and active and schedule = '0 20 * * *'" in precheck
    change = code.split("end $$;")[1]
    assert re.findall(r"cron\.\w+\(", change) == ["cron.unschedule("]
    assert "select cron.unschedule('purge_raw_quotes');" in change
    assert f"select cron.schedule('purge_raw_quotes', '0 20 * * *',\n--     '{JOB7}');" in sql   # rollback
    assert "Job 7 purge_raw_quotes is retired by supabase/retire-purge-raw-quotes-cron.sql" in " ".join(dm.__doc__.split())


@pytest.mark.skipif(not os.environ.get("EQUITY_TEST_PGLITE_MODULE") or not shutil.which("node"),
                    reason="Disposable WASM Postgres harness not configured")
def test_query_on_postgres_sees_a_vacuum_and_not_autovacuum_or_other_schemas():
    """Real Postgres: VACUUM sets last_vacuum only for the tables it ran on; a same-named table elsewhere is ignored."""
    script = r'''
const {PGlite}=require(process.argv[1]);
(async()=>{const db=new PGlite();await db.waitReady;
await db.exec(`CREATE SCHEMA quant_app; CREATE SCHEMA other;
CREATE TABLE quant_app.market_quotes(x int); CREATE TABLE quant_app.scanner_observations(x int);
CREATE TABLE quant_app.universe_membership(x int); CREATE TABLE quant_app.universe_membership_versions(x int);
CREATE TABLE other.universe_membership(x int);`);
const vacuum=process.argv[2], tables=JSON.parse(process.argv[3]);
const before=await db.query(vacuum,[tables]);
await db.exec("VACUUM (ANALYZE) quant_app.market_quotes, quant_app.scanner_observations, other.universe_membership");
const after=await db.query(vacuum,[tables]);
const now=await db.query("SELECT now()");
process.stdout.write(JSON.stringify({before:before.rows,after:after.rows,now:now.rows}));await db.close();
})().catch(e=>{process.stderr.write('SQL_FAILED '+e.message);process.exitCode=1;});
'''
    output = subprocess.run(["node", "-e", script, os.environ["EQUITY_TEST_PGLITE_MODULE"],
                             dm.VACUUM_SQL.replace("%s", "$1"), json.dumps(list(dm.TABLES))],
                            capture_output=True, text=True, check=True, timeout=60)
    result = json.loads(output.stdout)
    assert {r["name"]: r["last_vacuum"] is not None for r in result["before"]} == dict.fromkeys(dm.TABLES, False)
    assert {r["name"]: r["last_vacuum"] is not None for r in result["after"]} == {
        "market_quotes": True, "scanner_observations": True, "universe_membership_versions": False,
        "universe_membership": False}
    assert len(result["after"]) == 4 and len(result["now"]) == 1


@pytest.mark.skipif(not os.environ.get("EQUITY_TEST_PGLITE_MODULE") or not shutil.which("node"),
                    reason="Disposable WASM Postgres harness not configured")
def test_retire_sql_runs_on_postgres_removes_only_job_7_and_stops_on_a_changed_job():
    """The real file on Postgres with a stub cron: recorded job -> removed, job 8 kept; changed or gone -> error, unchanged."""
    script = r'''
const {PGlite}=require(process.argv[1]);
const stub=`CREATE SCHEMA cron;
CREATE TABLE cron.job(jobid bigint, jobname text, schedule text, active boolean, command text);
CREATE FUNCTION cron.unschedule(job_name text) RETURNS boolean LANGUAGE sql AS
  $f$ WITH d AS (DELETE FROM cron.job WHERE jobname = job_name RETURNING 1) SELECT count(*) = 1 FROM d $f$;`;
async function run(jobs){const db=new PGlite();await db.waitReady;await db.exec(stub);
 for (const [id,name,schedule,active,command] of jobs)
   await db.query("INSERT INTO cron.job VALUES ($1,$2,$3,$4,$5)",[id,name,schedule,active,command]);
 let error=null;try{await db.exec(process.argv[2]);}catch(e){error=e.message;}
 const rows=(await db.query("SELECT jobid::int AS jobid, jobname FROM cron.job ORDER BY jobid")).rows;
 await db.close();return {error,rows};}
(async()=>{const cmd=JSON.parse(process.argv[3]);
 const vac=[8,'nightly-vacuum-growing-tables','45 22 * * *',true,'VACUUM'];
 const out={};
 out.first=await run([[7,'purge_raw_quotes','0 20 * * *',true,cmd],vac]);
 out.changed=await run([[7,'purge_raw_quotes','0 20 * * *',true,cmd+';'],vac]);
 out.paused=await run([[7,'purge_raw_quotes','0 20 * * *',false,cmd],vac]);
 out.moved=await run([[7,'purge_raw_quotes','0 21 * * *',true,cmd],vac]);
 out.again=await run([vac]);
 process.stdout.write(JSON.stringify(out));
})().catch(e=>{process.stderr.write('SQL_FAILED '+e.message);process.exitCode=1;});
'''
    output = subprocess.run(["node", "-e", script, os.environ["EQUITY_TEST_PGLITE_MODULE"], RETIRE_FILE,
                             json.dumps(JOB7)], capture_output=True, text=True, check=True, timeout=60)
    result = json.loads(output.stdout)
    assert result["first"] == {"error": None, "rows": [{"jobid": 8, "jobname": "nightly-vacuum-growing-tables"}]}
    for case in ("changed", "paused", "moved", "again"):
        assert "nothing changed" in result[case]["error"]
        assert len(result[case]["rows"]) == (1 if case == "again" else 2)
