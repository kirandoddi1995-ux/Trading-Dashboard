"""Explicit owner-only bounded NAV rewrite; offline preview is the default."""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
from typing import Any

import psycopg

from nav_compaction_backup import bounded_read, rehearse

ROOT = Path(__file__).resolve().parent
EXPECTED_SCHEMA = 'b242961c2c703b5e63934f03161b85dc'
EXPECTED_ROWS = 9424
EXPECTED_DATA = '566e821aa5e6c28826d5b5532de895f8'
SCHEMA_SQL = """SELECT md5(jsonb_build_object(
 'owner',pg_get_userbyid(c.relowner),'rls',c.relrowsecurity,
 'force_rls',c.relforcerowsecurity,'acl',c.relacl::text,
 'columns',(SELECT jsonb_agg(jsonb_build_array(a.attname,
  format_type(a.atttypid,a.atttypmod),a.attnotnull,a.attcollation::regcollation::text,
  pg_get_expr(d.adbin,d.adrelid)) ORDER BY a.attnum)
  FROM pg_attribute a LEFT JOIN pg_attrdef d
  ON d.adrelid=a.attrelid AND d.adnum=a.attnum
  WHERE a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped),
 'indexes',(SELECT jsonb_agg(pg_get_indexdef(i.indexrelid) ORDER BY i.indexrelid)
  FROM pg_index i WHERE i.indrelid=c.oid),
 'constraints',(SELECT jsonb_agg(pg_get_constraintdef(k.oid) ORDER BY k.conname)
  FROM pg_constraint k WHERE k.conrelid=c.oid),
 'triggers',(SELECT jsonb_agg(pg_get_triggerdef(t.oid) ORDER BY t.tgname)
  FROM pg_trigger t WHERE t.tgrelid=c.oid),
 'policies',(SELECT jsonb_agg(jsonb_build_array(p.polname,p.polpermissive,p.polroles,
  p.polcmd,pg_get_expr(p.polqual,p.polrelid),pg_get_expr(p.polwithcheck,p.polrelid))
  ORDER BY p.polname) FROM pg_policy p WHERE p.polrelid=c.oid)
)::text) FROM pg_class c WHERE c.oid='quant_app.mf_nav'::regclass"""
DATA_SQL = """SELECT count(*),count(DISTINCT scheme_code),
 md5(string_agg(to_jsonb(s)::text,E'\\n' ORDER BY scheme_code)) FROM quant_app.mf_nav s"""
SIZE_SQL = """SELECT (SELECT sum(pg_database_size(oid))::bigint FROM pg_database),
 pg_total_relation_size('quant_app.mf_nav')"""
BLOCKERS_SQL = """SELECT
 (SELECT count(*) FROM pg_stat_activity WHERE pid<>pg_backend_pid()
  AND xact_start<now()-interval '5 minutes'),
 (SELECT count(*) FROM pg_replication_slots WHERE xmin IS NOT NULL OR catalog_xmin IS NOT NULL),
 (SELECT count(*) FROM pg_prepared_xacts),
 (SELECT count(*) FROM pg_stat_progress_vacuum),
 (SELECT count(*) FROM pg_locks WHERE relation='quant_app.mf_nav'::regclass
  AND pid IS DISTINCT FROM pg_backend_pid())"""
VACUUM_SQL = 'VACUUM (FULL, ANALYZE) quant_app.mf_nav'
SAFE_FAILURE_CODES = frozenset({
    'OWNER_READ_WRITE_SESSION_REQUIRED', 'NAV_PRE_OR_POST_INVARIANT_FAILED',
    'AUTOCOMMIT_SESSION_REQUIRED', 'PHYSICAL_CAPACITY_ATTESTATION_INSUFFICIENT',
    'MAINTENANCE_BLOCKERS_PRESENT', 'OWNER_MAINTENANCE_CONFIRMATIONS_REQUIRED',
    'VERIFIED_TLS_CA_REQUIRED', 'NEW_PRIVATE_RECEIPT_DIRECTORY_REQUIRED',
    'NAV_DATA_INVARIANT_FAILED', 'NAV_SCHEMA_INVARIANT_FAILED', 'NAV_SIZE_INVARIANT_FAILED',
})


class MaintenanceBlocked(RuntimeError):
    """Fixed, credential-free failure; no read-only override or retry."""


def measure(conn: Any) -> dict[str, Any]:
    """Read exact row and logical-definition invariants before and after the rewrite."""
    role = conn.execute("SELECT current_user,current_setting('default_transaction_read_only')").fetchone()
    if not role or role != ('postgres', 'off'):
        raise MaintenanceBlocked('OWNER_READ_WRITE_SESSION_REQUIRED')
    data = conn.execute(DATA_SQL).fetchone()
    definition = conn.execute(SCHEMA_SQL).fetchone()
    size = conn.execute(SIZE_SQL).fetchone()
    if not data or data != (EXPECTED_ROWS, EXPECTED_ROWS, EXPECTED_DATA):
        raise MaintenanceBlocked('NAV_DATA_INVARIANT_FAILED')
    if not definition or definition != (EXPECTED_SCHEMA,):
        raise MaintenanceBlocked('NAV_SCHEMA_INVARIANT_FAILED')
    if (not size or len(size) != 2
            or any(type(value) is not int or value <= 0 for value in size)):
        raise MaintenanceBlocked('NAV_SIZE_INVARIANT_FAILED')
    return dict(rows=data[0], fingerprint=data[2], schema_fingerprint=definition[0],
                cluster_bytes=size[0], nav_bytes=size[1])


def check_only(conn: Any) -> dict[str, Any]:
    """Connected diagnostics in an explicit read-only transaction; never rewrite."""
    if conn.autocommit is not True:
        raise MaintenanceBlocked('AUTOCOMMIT_SESSION_REQUIRED')
    conn.execute('BEGIN READ ONLY')
    try:
        result = measure(conn)
        blockers = conn.execute(BLOCKERS_SQL).fetchone()
        if (not blockers or len(blockers) != 5
                or any(type(value) is not int or value != 0 for value in blockers)):
            raise MaintenanceBlocked('MAINTENANCE_BLOCKERS_PRESENT')
        return dict(status='NAV_CONNECTED_CHECK_PASSED', measurements=result,
                    blockers=list(blockers), hosted_changes=0, rewrite_outcome='NOT_ATTEMPTED',
                    collector_resume_authorised=False, approval_authority=False)
    finally:
        conn.execute('ROLLBACK')


def compact(conn: Any, folder: Path, physical_free_bytes: int) -> dict[str, Any]:
    """Exactly one rewrite; persisted before evidence precedes the hosted change."""
    if conn.autocommit is not True:
        raise MaintenanceBlocked('AUTOCOMMIT_SESSION_REQUIRED')
    before = measure(conn)
    # Conservative maintenance margin, NOT a claimed exact WAL/rewrite estimate.
    if (type(physical_free_bytes) is not int
            or physical_free_bytes < 4 * before['nav_bytes'] + 256_000_000):
        raise MaintenanceBlocked('PHYSICAL_CAPACITY_ATTESTATION_INSUFFICIENT')
    blockers = conn.execute(BLOCKERS_SQL).fetchone()
    if not blockers or any(type(value) is not int or value != 0 for value in blockers):
        raise MaintenanceBlocked('MAINTENANCE_BLOCKERS_PRESENT')
    record = dict(before=before, physical_free_bytes_owner_attested=physical_free_bytes,
                  transient_quota_behaviour_unverified=True, approval_authority=False)
    with (folder / 'before.json').open('x', encoding='utf-8') as stream:
        json.dump(record, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    conn.execute(VACUUM_SQL)  # Outside a transaction; session timeouts set at connection.
    after = measure(conn)
    result = dict(status='NAV_COMPACTION_VERIFIED', before=before, after=after,
                  reclaimed_cluster_bytes=before['cluster_bytes'] - after['cluster_bytes'],
                  nominal_headroom_bytes=500_000_000-after['cluster_bytes'],
                  collector_capacity_floor_met=after['cluster_bytes'] <= 476_000_000,
                  approval_authority=False)
    with (folder / 'after.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, sort_keys=True)
    return result


def main(argv: list[str] | None = None) -> int:
    """Owner invokes explicitly; no URL/password in argv, environment or output."""
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--compact', action='store_true')
    modes.add_argument('--check-only', action='store_true')
    parser.add_argument('--confirm-writers-quiesced', action='store_true')
    parser.add_argument('--acknowledge-transient-quota-risk', action='store_true')
    parser.add_argument('--physical-free-bytes', type=int)
    parser.add_argument('--data', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--pglite-module', type=Path)
    parser.add_argument('--ca-file', type=Path)
    parser.add_argument('--receipt-dir', type=Path)
    args = parser.parse_args(argv)
    phase = 'LOCAL_PREFLIGHT'
    try:
        if not args.compact and not args.check_only:
            print(json.dumps({'status': 'PREVIEW', 'network_calls': 0, 'hosted_changes': 0,
                              'table': 'quant_app.mf_nav', 'rewrites_if_confirmed': 1}))
            return 0
        if args.check_only:
            if not args.ca_file or not args.ca_file.is_file():
                raise MaintenanceBlocked('VERIFIED_TLS_CA_REQUIRED')
        elif (not args.confirm_writers_quiesced or not args.acknowledge_transient_quota_risk
                or not args.physical_free_bytes or not args.data or not args.manifest
                or not args.pglite_module or not args.ca_file or not args.receipt_dir):
            raise MaintenanceBlocked('OWNER_MAINTENANCE_CONFIRMATIONS_REQUIRED')
        if args.compact:
            if not args.ca_file.is_file():
                raise MaintenanceBlocked('VERIFIED_TLS_CA_REQUIRED')
            folder = args.receipt_dir.resolve()
            if folder.is_relative_to(ROOT) or folder.exists():
                raise MaintenanceBlocked('NEW_PRIVATE_RECEIPT_DIRECTORY_REQUIRED')
            proof = rehearse(bounded_read(args.data), json.loads(bounded_read(args.manifest)), args.pglite_module)
            folder.mkdir(parents=True, exist_ok=False)
            with (folder / 'restore-proof.json').open('x', encoding='utf-8') as stream:
                json.dump(proof, stream, sort_keys=True)
        url = getpass.getpass('Owner PostgreSQL connection URL (hidden, never saved): ')
        phase = 'CONNECTING'
        with psycopg.connect(url, connect_timeout=5, autocommit=True,
                             sslmode='verify-full', sslrootcert=str(args.ca_file.resolve()),
                             application_name='owner-nav-compaction',
                             options='-c timezone=UTC -c statement_timeout=120000 -c lock_timeout=5000') as conn:
            if args.check_only:
                phase = 'CONNECTED_CHECK'
                result = check_only(conn)
            else:
                phase = 'MAINTENANCE'
                result = compact(conn, folder, args.physical_free_bytes)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        # A rewrite may have committed before a post-check/output failure. Never
        # report rollback as certain; retain receipts and ask for read-only inspection.
        code = (str(error) if isinstance(error, MaintenanceBlocked)
                and str(error) in SAFE_FAILURE_CODES else 'NAV_MAINTENANCE_STOP_INSPECT_RECEIPTS')
        result = {'status': 'BLOCKED', 'code': code, 'phase': phase,
                  'rewrite_outcome': ('CHECK_PRIVATELY_DO_NOT_RETRY'
                                      if phase == 'MAINTENANCE' else 'NOT_ATTEMPTED'),
                  'collector_resume_authorised': False}
        if phase == 'LOCAL_PREFLIGHT':
            result.update(network_calls=0, hosted_changes=0)
        print(json.dumps(result))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
