"""Separate, bounded archive job. Preview is read-only; deletion is double-gated.

Only explicit source tables are allowlisted. No source locks during network I/O.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
import json
import os

import psycopg

from drive_archive import ArchiveError, DriveArchive, RELATIONS, SPECS, credentials, upload_verified

ROLE = 'quant_archive_worker'
UTC = dt.timezone.utc
HOT_RETENTION_DAYS = 14  # Eligibility below additionally protects live dependencies.


def cutoff_for(table, today, nav_cutoff=None):
    if table not in SPECS:
        raise ArchiveError('UNSUPPORTED_TABLE')
    normal = today - dt.timedelta(days=HOT_RETENTION_DAYS)
    if nav_cutoff is None:
        return normal
    if table != 'mf_nav' or nav_cutoff >= today:
        raise ArchiveError('INVALID_ONE_TIME_NAV_CUTOFF')
    return nav_cutoff


def predicate(table):
    if table == 'equity_research.outcomes':
        # Match ResearchRepository.report's deterministic latest-row ordering.
        return """s.recorded_at < (%(cutoff)s::date::timestamp AT TIME ZONE 'UTC')
            AND EXISTS (SELECT 1 FROM equity_research.outcomes newer
                WHERE newer.decision_id=s.decision_id
                  AND (newer.recorded_at,newer.snapshot_id) > (s.recorded_at,s.snapshot_id))"""
    if table == 'mf_nav':
        return """s.nav_date < %(cutoff)s AND EXISTS (
            SELECT 1 FROM quant_app.mf_nav newer
            WHERE newer.scheme_code=s.scheme_code AND newer.nav_date>s.nav_date)"""
    if table == 'market_quotes':
        # Old trading date alone is insufficient: a stale quote may have only
        # just been captured. Keep the hot window of capture time as well.
        return """s.trade_date < %(cutoff)s
            AND s.observed_at < (%(cutoff)s::date::timestamp AT TIME ZONE 'UTC')"""
    if table == 'universe_membership_versions':
        return """s.observed_at < (%(cutoff)s::date::timestamp AT TIME ZONE 'UTC')
            AND EXISTS (SELECT 1 FROM quant_app.universe_snapshot_versions h
                WHERE h.snapshot_id=s.snapshot_id AND h.snapshot_date < %(cutoff)s
                  AND h.observed_at < (%(cutoff)s::date::timestamp AT TIME ZONE 'UTC')
                  AND EXISTS (SELECT 1 FROM quant_app.universe_snapshot_versions newer
                    WHERE newer.is_complete AND newer.observed_at > h.observed_at))"""
    if table == 'scanner_observations':
        # Passed signals may still be awaiting outcomes indefinitely. Never delete
        # target parents (the reviewed migration also removes CASCADE as a backstop).
        return """s.as_of_date < %(cutoff)s
            AND s.observed_at < (%(cutoff)s::date::timestamp AT TIME ZONE 'UTC')
            AND s.stage2_pass IS FALSE
            AND NOT EXISTS (SELECT 1 FROM quant_app.prediction_targets t
                            WHERE t.observation_id=s.observation_id)"""
    raise ArchiveError('UNSUPPORTED_TABLE')


class ArchiveRepository:
    def __init__(self, url):
        if not url or not url.startswith(('postgres://', 'postgresql://')):
            raise ArchiveError('ARCHIVE_DATABASE_URL_MISSING')
        self.url = url

    @contextmanager
    def connection(self, readonly=False):
        with psycopg.connect(self.url, connect_timeout=10, sslmode='require',
                             application_name='quant-archive',
                             options='-c timezone=UTC -c statement_timeout=30000 -c lock_timeout=5000') as conn:
            if readonly:
                conn.execute('SET TRANSACTION READ ONLY')
            user = conn.execute("SELECT current_user,rolsuper,rolbypassrls,rolcreaterole,rolcreatedb "
                                "FROM pg_roles WHERE rolname=current_user").fetchone()
            if not user or user[0] != ROLE or any(user[1:]):
                raise ArchiveError('RESTRICTED_ARCHIVE_ROLE_REQUIRED')
            if conn.execute('SELECT EXISTS(SELECT 1 FROM pg_auth_members '
                            'WHERE member=(SELECT oid FROM pg_roles WHERE rolname=current_user))').fetchone()[0]:
                raise ArchiveError('ARCHIVE_ROLE_MEMBERSHIP_FORBIDDEN')
            yield conn

    def check(self):
        with self.connection(readonly=True) as conn:
            forbidden = conn.execute("""SELECT EXISTS (
                SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname IN ('quant_app','equity_operations','equity_research')
                  AND c.relkind IN ('r','p','v','m')
                  AND NOT (n.nspname='quant_app' AND c.relname IN
                      ('mf_nav','market_quotes','market_daily_volumes','archive_manifests',
                       'universe_membership_versions','scanner_observations')
                       OR n.nspname='equity_research' AND c.relname='outcomes')
                  AND (has_table_privilege(current_user,c.oid,'SELECT')
                    OR has_table_privilege(current_user,c.oid,'INSERT')
                    OR has_table_privilege(current_user,c.oid,'UPDATE')
                    OR has_table_privilege(current_user,c.oid,'DELETE')))
            """).fetchone()[0]
            if forbidden:
                raise ArchiveError('ARCHIVE_ROLE_TOO_BROAD')
            for table in SPECS:
                for permission in ('SELECT', 'DELETE'):
                    if not conn.execute('SELECT has_table_privilege(current_user,%s,%s)',
                                        (RELATIONS[table], permission)).fetchone()[0]:
                        raise ArchiveError('ARCHIVE_SOURCE_GRANT_MISSING')
                if conn.execute('SELECT has_table_privilege(current_user,%s,%s)',
                                (RELATIONS[table], 'INSERT,UPDATE,TRUNCATE,TRIGGER')).fetchone()[0]:
                    raise ArchiveError('ARCHIVE_SOURCE_WRITE_GRANT_FORBIDDEN')
            conn.execute('SELECT batch_id FROM quant_app.archive_manifests LIMIT 0')
            conn.execute('SELECT instrument_key FROM quant_app.market_daily_volumes LIMIT 0')
            # Read only the dependency columns, not prediction payloads or other tables.
            conn.execute('SELECT observation_id FROM quant_app.prediction_targets LIMIT 0')
            conn.execute('SELECT snapshot_id,snapshot_date,observed_at,is_complete '
                         'FROM quant_app.universe_snapshot_versions LIMIT 0')
            safe_fk = conn.execute("""SELECT EXISTS (SELECT 1 FROM pg_constraint
                WHERE conrelid='quant_app.prediction_targets'::regclass
                  AND confrelid='quant_app.scanner_observations'::regclass
                  AND conname='prediction_targets_observation_id_fkey'
                  AND contype='f' AND confdeltype='r' AND convalidated)
                AND NOT EXISTS (SELECT 1 FROM pg_constraint
                WHERE confrelid='quant_app.scanner_observations'::regclass
                  AND contype='f' AND confdeltype<>'r')""").fetchone()[0]
            if not safe_fk:
                raise ArchiveError('SCANNER_ARCHIVE_RESTRICT_FK_REQUIRED')
            guards = conn.execute("""SELECT count(*) FROM pg_trigger
                WHERE tgrelid='equity_research.outcomes'::regclass
                  AND tgenabled IN ('O','A') AND NOT tgisinternal
                  AND ((tgname='outcome_append_only' AND tgtype=58
                        AND tgfoid='equity_research.reject_mutation()'::regprocedure)
                    OR (tgname='outcome_archive_row_guard' AND tgtype=11
                        AND tgfoid='equity_research.guard_outcome_archive_delete()'::regprocedure))
            """).fetchone()[0]
            if guards != 2:
                raise ArchiveError('RESEARCH_ARCHIVE_GUARDS_REQUIRED')

    def preview(self, table, cutoff):
        condition = predicate(table)
        with self.connection(readonly=True) as conn:
            return conn.execute(f'SELECT count(*) FROM {RELATIONS[table]} s WHERE {condition}',
                                {'cutoff': cutoff}).fetchone()[0]

    def select(self, table, cutoff, limit):
        condition = predicate(table)
        order = {'mf_nav': 's.nav_date,s.scheme_code',
                 'market_quotes': 's.observed_at,s.instrument_key',
                 'universe_membership_versions': 's.observed_at,s.snapshot_id,s.instrument_key',
                 'scanner_observations': 's.as_of_date,s.observation_id',
                 'equity_research.outcomes': 's.recorded_at,s.snapshot_id'}[table]
        with self.connection(readonly=True) as conn:
            # Canonical PostgreSQL JSON text, never a driver float conversion.
            rows = conn.execute(f'SELECT to_jsonb(s)::text FROM {RELATIONS[table]} s '
                                f'WHERE {condition} ORDER BY {order} LIMIT %(limit)s',
                                {'cutoff': cutoff, 'limit': limit}).fetchall()
            return [row[0] for row in rows]

    def acknowledge(self, manifest, texts, cutoff, delete):
        """Verified manifest + exact-row deletion commit together. Crash => retry.

        A completed manifest is never reused to authorize unrelated source data.
        """
        table = manifest['source_table']
        condition = predicate(table)
        with self.connection() as conn:
            # Transaction-scoped serialization; safe with Supabase session pooler.
            conn.execute('SELECT pg_advisory_xact_lock(71429051)')
            values = (manifest['batch_id'], table, manifest['rows'], manifest['sha256'],
                      manifest['drive_file_id'], manifest['drive_manifest_id'])
            conn.execute("""INSERT INTO quant_app.archive_manifests
                (batch_id,source_table,row_count,file_sha256,drive_file_id,drive_manifest_id)
                VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(batch_id) DO NOTHING""", values)
            stored = conn.execute("""SELECT batch_id,source_table,row_count,file_sha256,
                drive_file_id,drive_manifest_id FROM quant_app.archive_manifests
                WHERE batch_id=%s FOR UPDATE""", (manifest['batch_id'],)).fetchone()
            if tuple(stored or ()) != values:
                raise ArchiveError('DATABASE_MANIFEST_CONFLICT')
            if not delete:
                return 0  # Records verification, but does not touch source data.
            conn.execute('CREATE TEMP TABLE verified_archive_rows '
                         '(original jsonb NOT NULL) ON COMMIT DROP')
            with conn.cursor() as cur:
                cur.executemany('INSERT INTO verified_archive_rows VALUES (%s::jsonb)',
                                [(text,) for text in texts])
            key_match = {
                'mf_nav': "s.scheme_code=v.original->>'scheme_code' AND s.nav_date=(v.original->>'nav_date')::date",
                'market_quotes': "s.instrument_key=v.original->>'instrument_key' AND s.observed_at=(v.original->>'observed_at')::timestamptz",
                'universe_membership_versions': "s.snapshot_id=v.original->>'snapshot_id' AND s.instrument_key=v.original->>'instrument_key'",
                'scanner_observations': "s.observation_id=v.original->>'observation_id'",
                'equity_research.outcomes': "s.snapshot_id=v.original->>'snapshot_id'",
            }[table]
            if table == 'market_quotes':
                # Fail closed if compact history does not cover archived volumes.
                missing = conn.execute(f"""SELECT count(*) FROM quant_app.market_quotes s
                    JOIN verified_archive_rows v ON {key_match}
                    WHERE to_jsonb(s)=v.original AND s.volume IS NOT NULL AND NOT EXISTS (
                      SELECT 1 FROM quant_app.market_daily_volumes d
                      WHERE d.instrument_key=s.instrument_key AND d.trade_date=s.trade_date
                        AND d.max_captured_volume>=s.volume)""").fetchone()[0]
                if missing:
                    raise ArchiveError('DAILY_VOLUME_COVERAGE_MISSING')
            count = conn.execute(f"""WITH removed AS (
                DELETE FROM {RELATIONS[table]} s USING verified_archive_rows v
                WHERE {key_match} AND to_jsonb(s)=v.original AND {condition}
                RETURNING 1) SELECT count(*) FROM removed""", {'cutoff': cutoff}).fetchone()[0]
            conn.execute("""UPDATE quant_app.archive_manifests
                SET completed_at=clock_timestamp(),
                    deleted_count=GREATEST(COALESCE(deleted_count,0),%s) WHERE batch_id=%s""",
                         (count, manifest['batch_id']))
            return count


def run_batch(repo, drive, table, cutoff, limit=1000, delete=False):
    texts = repo.select(table, cutoff, limit)
    if not texts:
        return {'selected': 0, 'verified': 0, 'deleted': 0, 'retained': 0}
    manifest, verified = upload_verified(drive, table, texts)
    deleted = repo.acknowledge(manifest, verified, cutoff, delete)
    return {'selected': len(texts), 'verified': len(verified), 'deleted': deleted,
            'retained': len(texts) - deleted, 'batch_id': manifest['batch_id']}


def build_drive_credentials():
    try:
        token_info = json.loads(os.environ.get('DRIVE_OAUTH_TOKEN_JSON', '{}'))
    except (ValueError, TypeError):
        raise ArchiveError('INVALID_OAUTH_CONFIGURATION') from None
    return credentials(token_info)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Verified Drive archival, isolated from scans')
    parser.add_argument('--mode', choices=('preview', 'export', 'delete'), default='preview')
    parser.add_argument('--table', choices=tuple(SPECS), default='mf_nav')
    parser.add_argument('--nav-cutoff', type=dt.date.fromisoformat,
                        help='Manual one-time NAV cleanup only; normal policy is 14 days')
    parser.add_argument('--batch-size', type=int, default=1000)
    parser.add_argument('--max-batches', type=int, default=20)
    args = parser.parse_args(argv)
    drive = None
    try:
        if not 1 <= args.batch_size <= 2000 or not 1 <= args.max_batches <= 200:
            raise ArchiveError('INVALID_BATCH_LIMIT')
        deleting = args.mode == 'delete'
        if deleting and os.environ.get('ARCHIVE_DELETE_ENABLED') != 'true':
            raise ArchiveError('DELETION_NOT_ENABLED')
        cutoff = cutoff_for(args.table, dt.datetime.now(UTC).date(), args.nav_cutoff)
        repo = ArchiveRepository(os.environ.get('ARCHIVE_DATABASE_URL'))
        repo.check()
        count = repo.preview(args.table, cutoff)
        print(json.dumps({'mode': args.mode, 'table': args.table, 'cutoff': str(cutoff),
                          'eligible': count}), flush=True)
        if args.mode == 'preview':
            return 0
        creds = build_drive_credentials()
        drive = DriveArchive(creds, os.environ.get('DRIVE_ARCHIVE_FOLDER_ID', ''))
        drive.check_folder()
        for _ in range(args.max_batches):
            result = run_batch(repo, drive, args.table, cutoff, args.batch_size, deleting)
            print('ARCHIVE_BATCH ' + json.dumps(result), flush=True)
            # Export-only verifies one batch as a deployment smoke test. Do not
            # repeatedly select it or pretend the whole table has been archived.
            if not deleting or result['selected'] == 0:
                break
            if result['retained']:
                raise ArchiveError('SOURCE_CHANGED_OR_ALREADY_REMOVED_REVIEW_REQUIRED')
        remaining = repo.preview(args.table, cutoff)
        print(json.dumps({'status': 'SUCCESS', 'eligible_remaining': remaining}), flush=True)
        return 0
    except Exception as exc:
        # Never emit HTTP/provider text, token JSON, database URLs or raw rows.
        code = str(exc) if isinstance(exc, ArchiveError) else type(exc).__name__
        print(json.dumps({'status': 'FAILED', 'error_category': code}), flush=True)
        return 1
    finally:
        if drive is not None:
            drive.close()


if __name__ == '__main__':
    raise SystemExit(main())
