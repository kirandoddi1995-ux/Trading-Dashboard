"""Opt-in synthetic LOCAL Postgres checks, never hosted SQL or credentials.

Default preview has no imports/network/SQL. Execution is pinned to loopback port
55436, database kiran_cut_disposable, public fixture credentials and Postgres17.
Use ONLY a fresh disposable container. No production connection-string argument.
Fixture writes are synthetic; exporter handle is dedicated restricted/read-only.
No DROP, DELETE, migration or production factory activation exists here.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
import json
import os
from typing import Any

PORT = 55436
DATABASE = 'kiran_cut_disposable'
APP = 'kiran_cut_native_fixture'


@dataclass
class PgCursor:
    wrapped: Any
    after_settings: Callable[[], None] | None = None

    def execute(self, operation: str, parameters: Sequence[object] = ()) -> object:
        import storage_consistent_cut_export as export
        result = self.wrapped.execute(operation, parameters)
        if operation == export.SETTINGS_SQL and self.after_settings is not None:
            callback, self.after_settings = self.after_settings, None
            callback()
        return result

    def fetchmany(self, size: int) -> Sequence[Sequence[object]]:
        return list(self.wrapped.fetchmany(size))

    def close(self) -> None:
        self.wrapped.close()


@dataclass
class PgHandle:
    """Test-only psycopg3-to-injected-DBAPI seam, not a production factory."""

    wrapped: Any
    after_settings: Callable[[], None] | None = None

    @property
    def autocommit(self) -> bool:
        return bool(self.wrapped.autocommit)

    def get_transaction_status(self) -> int:
        return int(self.wrapped.info.transaction_status)

    def set_session(self, *, isolation_level: str, readonly: bool, autocommit: bool) -> None:
        from psycopg import IsolationLevel
        if (isolation_level, readonly, autocommit) != ('REPEATABLE READ', True, False):
            raise ValueError('NATIVE_SETTINGS_INVALID')
        self.wrapped.isolation_level = IsolationLevel.REPEATABLE_READ
        self.wrapped.read_only = True
        self.wrapped.autocommit = False

    def cursor(self) -> PgCursor:
        return PgCursor(self.wrapped.cursor(), self.after_settings)

    def rollback(self) -> None:
        self.wrapped.rollback()

    def close(self) -> None:
        self.wrapped.close()


def preview() -> dict[str, object]:
    return {'status': 'PREVIEW', 'network_calls': 0, 'hosted_changes': 0,
            'fixture_writes': 0, 'approval_authority': False}


def execute() -> dict[str, object]:
    """Consume fresh synthetic database; fixed cases expose no values/credentials."""
    import psycopg
    import storage_consistent_cut_export as export
    # Refuse inherited libpq configuration by NAME, before constructing a handle.
    if any(key.startswith('PG') for key in os.environ):
        return {'status': 'BLOCKED', 'stage': 'ENVIRONMENT', 'code': 'NATIVE_ENVIRONMENT_NOT_ISOLATED',
                'hosted_changes': 0, 'approval_authority': False}
    case = 'CONNECT_AND_FIXTURE_IDENTITY'
    cases: list[str] = []
    admin: Any = None
    try:
        def connect(user: str) -> Any:
            return psycopg.connect(host='127.0.0.1', hostaddr='127.0.0.1', port=PORT,
                dbname=DATABASE, user=user, password='synthetic-disposable-only', sslmode='disable',
                connect_timeout=3, application_name=APP,
                options='-c statement_timeout=5000 -c lock_timeout=1000 -c idle_in_transaction_session_timeout=10000')
        admin = connect('postgres')
        admin.autocommit = True
        facts = admin.execute("SELECT current_database(), current_user, current_setting('server_version_num')::int, inet_server_addr()::text").fetchone()
        if facts is None or facts[0] != DATABASE or facts[1] != 'postgres' or not 170000 <= facts[2] < 180000:
            raise ValueError('NATIVE_FIXTURE_IDENTITY')
        if (admin.execute("SELECT to_regnamespace('quant_app')").fetchone() != (None,)
                or admin.execute("SELECT COUNT(*) FROM pg_roles WHERE rolname='kiran_cut_reader'").fetchone() != (0,)):
            raise ValueError('NATIVE_FRESH_DATABASE_REQUIRED')
        admin.execute('CREATE SCHEMA quant_app')
        admin.execute('CREATE TABLE quant_app.market_daily_volumes(instrument_key text NOT NULL, trade_date date NOT NULL, max_captured_volume numeric NOT NULL, PRIMARY KEY(instrument_key,trade_date))')
        admin.execute("CREATE ROLE kiran_cut_reader LOGIN PASSWORD 'synthetic-disposable-only' NOSUPERUSER NOBYPASSRLS")
        admin.execute('GRANT USAGE ON SCHEMA quant_app TO kiran_cut_reader')
        admin.execute('GRANT SELECT ON quant_app.market_daily_volumes TO kiran_cut_reader')
        admin.execute("INSERT INTO quant_app.market_daily_volumes VALUES ('A','2024-01-02',10),('A','2024-01-03',20),('B','2024-01-02',5)")
        cases.append('RESTRICTED_SYNTHETIC_FIXTURE')
        request = export.ExportRequest('native_cut_1', date(2024,1,1), date(2024,1,10), lookback=20)
        case = 'NATIVE_COUNT_SUM_AVERAGE'
        cut = export.export_daily_volumes(PgHandle(connect('kiran_cut_reader')), request)
        if (cut.row_count != 3 or cut.key_count != 2 or dict(cut.averages) != {'A':15.0, 'B':5.0}
                or cut.historical_pit_verified or cut.snapshot_visibility_timestamp_exact
                or 'clock_timestamp()' not in export.SETTINGS_SQL):
            raise ValueError('NATIVE_AGGREGATE_MISMATCH')
        cases.append(case)
        case = 'REPEATABLE_READ_CONCURRENT_COMMIT'
        def concurrent_commit() -> None:
            admin.execute("INSERT INTO quant_app.market_daily_volumes VALUES ('A','2024-01-04',30)")
        cut = export.export_daily_volumes(PgHandle(connect('kiran_cut_reader'), concurrent_commit), request)
        if cut.row_count != 3 or dict(cut.averages) != {'A':15.0, 'B':5.0}:
            raise ValueError('NATIVE_MIXED_SNAPSHOT')
        cases.append(case)
        case = 'NEXT_CUT_SEES_COMMIT'
        cut = export.export_daily_volumes(PgHandle(connect('kiran_cut_reader')), request)
        if cut.row_count != 4 or dict(cut.averages) != {'A':20.0, 'B':5.0}:
            raise ValueError('NATIVE_COMMIT_NOT_VISIBLE')
        cases.append(case)
        case = 'SNAPSHOT_AFTER_TRANSACTION_START'
        class BeforeSnapshot(PgHandle):
            def cursor(self) -> PgCursor:
                # BEGIN is transaction control only; snapshot is not yet fixed.
                self.wrapped.execute('BEGIN')
                admin.execute("INSERT INTO quant_app.market_daily_volumes VALUES ('A','2024-01-05',40)")
                return super().cursor()
        cut = export.export_daily_volumes(BeforeSnapshot(connect('kiran_cut_reader')), request)
        if (cut.row_count != 5 or dict(cut.averages) != {'A':25.0, 'B':5.0}
                or cut.historical_pit_verified or cut.snapshot_visibility_timestamp_exact):
            raise ValueError('NATIVE_SNAPSHOT_OBSERVATION_MISMATCH')
        cases.append(case)
        case = 'EXACT_EMPTY_WINDOW'
        empty = export.ExportRequest('empty_native', date(2024,2,1), date(2024,2,2))
        cut = export.export_daily_volumes(PgHandle(connect('kiran_cut_reader')), empty)
        if cut.row_count != 0 or len(cut.objects) != 1 or dict(cut.averages):
            raise ValueError('NATIVE_EMPTY_MISMATCH')
        cases.append(case)
        case = 'NONFINITE_NUMERIC_BLOCKED'
        admin.execute("INSERT INTO quant_app.market_daily_volumes VALUES ('C','2024-01-02','NaN'::numeric)")
        try:
            export.export_daily_volumes(PgHandle(connect('kiran_cut_reader')), request)
        except export.ExportError as error:
            if str(error) != 'CUT_ROW_INVALID':
                raise ValueError('NATIVE_WRONG_NONFINITE_FAILURE') from None
        else:
            raise ValueError('NATIVE_NONFINITE_ACCEPTED')
        cases.append(case)
        return {'status':'DISPOSABLE_NATIVE_CUT_CASES_PASSED', 'cases':cases,
                'hosted_changes':0, 'synthetic_fixture_only':True,
                'custody_verified':False, 'global_enforcement_commissioned':False,
                'approval_authority':False}
    except Exception as error:
        return {'status':'BLOCKED', 'stage':case, 'safe_error_class':type(error).__name__
                    if type(error).__name__ in {'ValueError','ExportError','OperationalError','ProgrammingError'} else 'NativeCheckError',
                'code':'NATIVE_CUT_CHECK_FAILED', 'completed_cases':cases,
                'hosted_changes':0, 'approval_authority':False}
    finally:
        if admin is not None:
            admin.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--confirm-disposable', action='store_true')
    args = parser.parse_args(argv)
    if not args.execute:
        result = preview()
    elif not args.confirm_disposable:
        result = {'status':'BLOCKED','code':'DISPOSABLE_CONFIRMATION_REQUIRED','network_calls':0,
                  'hosted_changes':0,'approval_authority':False}
    else:
        try:
            result = execute()
        except Exception:
            # Includes unavailable driver or cleanup errors; never emit traceback.
            result = {'status':'BLOCKED', 'stage':'RUNNER_DEPENDENCY_OR_CLEANUP',
                      'code':'NATIVE_CUT_CHECK_FAILED', 'hosted_changes':0,
                      'approval_authority':False}
    print(json.dumps(result, sort_keys=True))
    return 2 if result['status'] == 'BLOCKED' else 0


if __name__ == '__main__':
    raise SystemExit(main())
