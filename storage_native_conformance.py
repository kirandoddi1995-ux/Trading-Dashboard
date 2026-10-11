"""Explicit disposable native-PG guard tests; never connects to project storage.

Default is offline preview. The execute path uses fixed loopback/sandbox/fixture
credentials only, not environment URLs, vaults or installed capture state.
The sandbox must already be provisioned by the separate disposable workflow.
Passing proves only the cases listed here, not ledger races or commissioning.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from typing import Any, Callable

import storage_write_guard as guard

DATABASE = 'storage_conformance_sandbox'
ROLE = 'storage_conformance_writer'
MARKER = 'disposable-storage-guard-v1'
FIXTURE_PASSWORD = 'public-disposable-fixture-only'
BOUND = guard.AppendBound('native_conformance', 4_000_000)
PROFILE_SQL = """SELECT current_database(),current_user,
    current_setting('server_version_num')::int,pg_backend_pid(),
    obj_description((SELECT oid FROM pg_database WHERE datname=current_database()),'pg_database'),
    r.rolsuper,r.rolbypassrls,r.rolcreatedb,r.rolcreaterole,
    EXISTS(SELECT 1 FROM pg_auth_members WHERE member=r.oid)
    FROM pg_roles r WHERE rolname=current_user"""


class ConformanceError(ValueError):
    """Fixed public codes, not driver text or private configuration."""


def validate_profile(row: object) -> int:
    """Reject emulators, privileged roles and any unmarked/wrong database."""
    if (not isinstance(row, (tuple, list)) or len(row) != 10
            or row[0] != DATABASE or row[1] != ROLE or row[4] != MARKER
            or type(row[2]) is not int or not 170000 <= row[2] < 180000
            or type(row[3]) is not int or row[3] <= 0
            or any(value is not False for value in row[5:])):
        raise ConformanceError('NATIVE_SANDBOX_IDENTITY_UNVERIFIED')
    return row[3]


def _query(connection: Any, sql: str) -> Any:
    with connection.cursor() as cursor:
        cursor.execute(sql)
        return cursor.fetchone()


def _profile(connection: Any) -> int:
    try:
        result = validate_profile(_query(connection, PROFILE_SQL))
        connection.rollback()
        return result
    except Exception:
        raise ConformanceError('NATIVE_SANDBOX_IDENTITY_UNVERIFIED') from None


def _require(value: bool) -> None:
    if value is not True:
        raise ConformanceError('NATIVE_CONFORMANCE_ASSERTION_FAILED')


def _clock() -> datetime:
    return datetime.now(timezone.utc)


def _expected(code: str, operation: Callable[[], None]) -> None:
    try:
        operation()
    except guard.GuardError as error:
        _require(str(error) == code)
    else:
        raise ConformanceError('NATIVE_EXPECTED_BLOCK_NOT_OBSERVED')


def run_native(connect: Callable[[], Any]) -> dict[str, object]:
    """Execute synthetic inserts on two independently authenticated connections.

    No DROP/TRUNCATE/DELETE, schema setup, privilege changes, retries or production
    data. Requires the empty, restricted, precreated native fixture. Connections
    are closed even on failure; the disposable service owns eventual cleanup.
    All exceptions are redacted, including connection/context cleanup failures.
    """
    try:
        with closing(connect()) as first, closing(connect()) as second:
            pid1, pid2 = _profile(first), _profile(second)
            _require(pid1 != pid2)
            _require(_query(first, 'SELECT count(*) FROM public.guard_probe') == (0,))
            first.rollback()
            checks = ['native_identity_and_distinct_backends']

            with guard.append_transaction(first, BOUND, clock=_clock) as receipt:
                _query(first, 'INSERT INTO public.guard_probe VALUES(1) RETURNING id')
            _require(receipt.status == 'COMMITTED')
            _require(_query(second, 'SELECT id FROM public.guard_probe WHERE id=1') == (1,))
            second.rollback()
            checks.append('committed_append_visible_on_independent_connection')

            def contender() -> None:
                with guard.append_transaction(second, BOUND, clock=_clock):
                    raise ConformanceError('NATIVE_CONTENDER_ENTERED')

            with guard.append_transaction(first, BOUND, clock=_clock):
                # The first writer remains in its transaction throughout the
                # independent thread's try-lock. No sleeps/timing race required.
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(_expected,
                        'STORAGE_WRITER_BUSY_OR_LOCK_UNVERIFIED', contender)
                    future.result(timeout=15)
                _query(first, 'INSERT INTO public.guard_probe VALUES(2) RETURNING id')
            with guard.append_transaction(second, BOUND, clock=_clock):
                _query(second, 'INSERT INTO public.guard_probe VALUES(3) RETURNING id')
            checks.append('concurrent_writer_blocked_then_lock_released_on_commit')

            class SyntheticFailure(Exception):
                pass

            try:
                with guard.append_transaction(first, BOUND, clock=_clock):
                    _query(first, 'INSERT INTO public.guard_probe VALUES(4) RETURNING id')
                    raise SyntheticFailure
            except SyntheticFailure:
                pass
            _require(_query(second, 'SELECT count(*) FROM public.guard_probe WHERE id=4') == (0,))
            second.rollback()
            with guard.append_transaction(second, BOUND, clock=_clock):
                _query(second, 'INSERT INTO public.guard_probe VALUES(5) RETURNING id')
            checks.append('body_failure_rolls_back_and_releases_lock')

            def broken_owner() -> None:
                with guard.append_transaction(first, BOUND, clock=_clock):
                    _query(first, 'INSERT INTO public.guard_probe VALUES(6) RETURNING id')
                    first.commit()  # Deliberate synthetic contract violation.

            _expected('STORAGE_TRANSACTION_OWNERSHIP_LOST', broken_owner)
            # A caller's rogue commit cannot be undone; no success/retry claim.
            _require(_query(second, 'SELECT count(*) FROM public.guard_probe WHERE id=6') == (1,))
            second.rollback()
            checks.append('caller_commit_detected_without_claiming_undo')

            def duplicate() -> None:
                with guard.append_transaction(first, BOUND, clock=_clock):
                    _query(first, 'INSERT INTO public.guard_probe VALUES(1) RETURNING id')

            try:
                duplicate()
            except Exception as error:
                _require(getattr(error, 'sqlstate', None) == '23505')
                _require(first.info.transaction_status == 0)
            else:
                raise ConformanceError('NATIVE_EXPECTED_BLOCK_NOT_OBSERVED')
            _require(_query(second, 'SELECT count(*) FROM public.guard_probe WHERE id=1') == (1,))
            second.rollback()
            checks.append('database_constraint_failure_rolls_back_without_retry')
        return {'status': 'NATIVE_GUARD_CASES_PASSED', 'checks': checks,
                'native_cases_executed': len(checks), 'approval_authority': False,
                'ledger_archive_races_verified': False,
                'global_enforcement_commissioned': False, 'hosted_changes': 0}
    except Exception:
        raise ConformanceError('NATIVE_CONFORMANCE_FAILED') from None


def connect_fixture(port: int) -> Any:
    """Fixed explicit parameters; never fall back to a production DSN/passfile."""
    import psycopg
    return psycopg.connect(host='127.0.0.1', hostaddr='127.0.0.1', port=port,
        dbname=DATABASE, user=ROLE, password=FIXTURE_PASSWORD, passfile=os.devnull,
        service='', sslmode='disable', gssencmode='disable', connect_timeout=5,
        application_name='disposable-storage-conformance', options='', autocommit=False)


def main(argv: list[str] | None = None) -> int:
    """Explicit two-switch execution; preview opens nothing and imports no driver."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--confirm-disposable', action='store_true')
    parser.add_argument('--port', type=int, default=55432)
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({'status': 'PREVIEW', 'network_calls': 0, 'writes': 0}))
        return 0
    if args.confirm_disposable is not True or not 1024 <= args.port <= 65535:
        print(json.dumps({'status': 'BLOCKED', 'code': 'DISPOSABLE_CONFIRMATION_REQUIRED'}))
        return 2
    try:
        result = run_native(lambda: connect_fixture(args.port))
    except Exception:
        print(json.dumps({'status': 'BLOCKED', 'code': 'NATIVE_CONFORMANCE_FAILED',
                          'global_enforcement_commissioned': False, 'approval_authority': False}))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
