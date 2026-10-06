"""Read-only emergency admission for the scheduled collector, not a global quota lock."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from typing import Any

QUOTA_BYTES = 500_000_000
RESERVE_BYTES = 20_000_000
RUN_ALLOWANCE_BYTES = 4_000_000
SQL = """SELECT clock_timestamp(),
    (SELECT sum(pg_database_size(oid))::bigint FROM pg_database),
    r.rolsuper,r.rolbypassrls
    FROM pg_roles r WHERE r.rolname=current_user"""


def assess(row: Any, now: datetime) -> dict[str, object]:
    """Reject missing, stale, privileged or inadequate measured admission evidence."""
    if not isinstance(row, (tuple, list)) or len(row) != 4:
        raise ValueError('STORAGE_MEASUREMENT_INVALID')
    observed, size, superuser, bypass = row
    if (not isinstance(observed, datetime) or observed.utcoffset() is None
            or now.utcoffset() is None or type(size) is not int or size <= 0
            or type(superuser) is not bool or type(bypass) is not bool):
        raise ValueError('STORAGE_MEASUREMENT_INVALID')
    if superuser or bypass:
        raise ValueError('RESTRICTED_ROLE_REQUIRED')
    if not timedelta(0) <= now - observed <= timedelta(seconds=60):
        raise ValueError('STORAGE_MEASUREMENT_STALE_OR_FUTURE')
    headroom = QUOTA_BYTES - size
    allowed = headroom >= RESERVE_BYTES + RUN_ALLOWANCE_BYTES
    return {'status': 'COLLECTOR_STORAGE_ALLOWED' if allowed else 'COLLECTOR_STORAGE_BLOCKED',
            'allowed': allowed, 'observed_at': observed.isoformat(),
            'cluster_bytes': size, 'nominal_headroom_bytes': headroom,
            'required_headroom_bytes': RESERVE_BYTES + RUN_ALLOWANCE_BYTES,
            'transaction_enforced': False, 'approval_authority': False}


def measure(database_url: str) -> Any:
    """TLS-required restricted connection; SELECT only, short statement/lock limits."""
    import psycopg
    with psycopg.connect(database_url, connect_timeout=5, sslmode='require') as connection:
        connection.read_only = True
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout='10s'")
            cursor.execute("SET LOCAL lock_timeout='2s'")
            cursor.execute(SQL)
            return cursor.fetchone()


def main(argv: list[str] | None = None) -> int:
    """Offline preview unless explicitly asked to check; never print raw exceptions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    if not args.check:
        print(json.dumps({'status': 'PREVIEW', 'network_calls': 0, 'writes': 0}))
        return 0
    try:
        url = os.environ.get('DATABASE_URL', '').strip()
        if not url:
            raise ValueError('DATABASE_CONNECTION_REQUIRED')
        result = assess(measure(url), datetime.now(timezone.utc))
    except Exception as error:
        codes = {'DATABASE_CONNECTION_REQUIRED', 'STORAGE_MEASUREMENT_INVALID',
                 'RESTRICTED_ROLE_REQUIRED', 'STORAGE_MEASUREMENT_STALE_OR_FUTURE'}
        code = str(error) if isinstance(error, ValueError) and str(error) in codes else 'STORAGE_CHECK_UNAVAILABLE'
        print(json.dumps({'status': 'COLLECTOR_STORAGE_BLOCKED', 'allowed': False,
                          'code': code, 'writes': 0, 'approval_authority': False}))
        return 2
    print(json.dumps(result))
    return 0 if result['allowed'] is True else 2


if __name__ == '__main__':
    raise SystemExit(main())
