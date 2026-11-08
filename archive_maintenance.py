"""Separate bounded archive job. Deletion requires a restore proof from this same run.

Only explicit source tables are allowlisted. No source locks during network I/O.
Recommissioned 4 Nov 2026 (ARCHIVE_DELETION_RECOMMISSIONING_2026-11-04.md): the
unconditional hold of 17 Oct is replaced by archive_restore_check.prove(), which
re-reads the Drive copies and proves they restore into the live tables before any
source row may be deleted. Flags and environment variables still cannot unlock it.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
import json
import os
import re
import time

import psycopg

import archive_restore_check as restore_check

from drive_archive import (APPEND_ONLY, ArchiveError, DriveArchive, RELATIONS, SPECS, batch_identity,
                           credentials, upload_verified)

ROLE = 'quant_archive_worker'
UTC = dt.timezone.utc
HOT_RETENTION_DAYS = 14  # Eligibility below additionally protects live dependencies.


GROWING_TABLES = ('market_quotes', 'scanner_observations', 'universe_membership_versions',
                  'universe_membership')
_ACTIVE_PROOF: restore_check.RestoreProof | None = None
ORDER_COLUMNS = {
    'mf_nav': ('nav_date', 'scheme_code'),
    'universe_membership': ('snapshot_date', 'instrument_key'),
    'market_quotes': ('observed_at', 'instrument_key'),
    'universe_membership_versions': ('observed_at', 'snapshot_id', 'instrument_key'),
    'scanner_observations': ('as_of_date', 'observation_id'),
    'equity_research.outcomes': ('recorded_at', 'snapshot_id'),
    'evidence_ledger_events': ('recorded_at', 'event_id'),
}
# Ledger pages: one closed UTC day at most, and at most this many stored (TOAST) payload bytes, so a
# page never changes once exported and its Parquet file stays well under MAX_BYTES (single events
# reach ~2.6 MB of JSON, ~0.6 MB stored).
LEDGER_PAGE_STORED_BYTES = 6 * 1024 * 1024
PRUNE_MAX_MINUTES = 170  # the job limit is 180 minutes
# Must stay byte-compatible with verify_local_archive_copy.INVENTORY_SET_SQL (tested).
GENERATION_SQL = """SELECT count(*), encode(sha256(convert_to(coalesce(string_agg(
  batch_id||E'\\t'||source_table||E'\\t'||row_count::text||E'\\t'||file_sha256||E'\\t'||drive_file_id||E'\\n',
  '' ORDER BY batch_id COLLATE "C"), ''), 'UTF8')), 'hex')
  FROM quant_app.archive_manifests WHERE verified_at <= %(before)s::timestamptz"""
HEX64 = re.compile(r'[0-9a-f]{64}')


def activate_restore_proof(proof: restore_check.RestoreProof) -> None:
    """Accept only a passing proof object produced by archive_restore_check.prove()."""
    global _ACTIVE_PROOF
    if not isinstance(proof, restore_check.RestoreProof) or not proof.valid_now():
        raise ArchiveError('ARCHIVE_RESTORE_PROOF_FAILED')
    _ACTIVE_PROOF = proof


def require_commissioned_delete(context: str | None = None) -> None:
    """No env/CLI boolean can establish custody or restore; only a passing proof can.

    The proof must come from archive_restore_check.prove() in this process, cover every
    recorded batch, contain no failure, be younger than PROOF_MAX_AGE_SECONDS and, when a
    context is given, have been made for that same database and Drive folder.
    """
    if _ACTIVE_PROOF is None or not _ACTIVE_PROOF.valid_now(context):
        raise ArchiveError('AUTHENTICATED_CUSTODY_AND_RESTORE_NOT_COMMISSIONED')


def batch_size_for(table, requested=None):
    if table not in SPECS:
        raise ArchiveError('UNSUPPORTED_TABLE')
    if requested is not None:
        if not 1 <= requested <= 2000:
            raise ArchiveError('INVALID_BATCH_LIMIT')
        return requested
    return {'equity_research.outcomes': 100, 'universe_membership': 500,
            'evidence_ledger_events': 500}.get(table, 1000)


def cutoff_for(table, today, nav_cutoff=None):
    """Deletion retention cutoff. Append-only tables have none (see export_cutoff)."""
    if table not in SPECS or table in APPEND_ONLY:
        raise ArchiveError('UNSUPPORTED_TABLE')
    days = 7 if table == 'equity_research.outcomes' else HOT_RETENTION_DAYS
    normal = today - dt.timedelta(days=days)
    if nav_cutoff is None:
        return normal
    if table != 'mf_nav' or nav_cutoff >= today:
        raise ArchiveError('INVALID_ONE_TIME_NAV_CUTOFF')
    return nav_cutoff


def export_cutoff(table, today, nav_cutoff=None):
    """Export bound. The ledger has no retention cutoff (it is never deleted): any CLOSED UTC day."""
    if table in APPEND_ONLY:
        if nav_cutoff is not None:
            raise ArchiveError('INVALID_ONE_TIME_NAV_CUTOFF')
        return today - dt.timedelta(days=1)
    return cutoff_for(table, today, nav_cutoff)


def export_condition(table):
    """Rows a run may READ for export. Append-only tables have no deletion predicate at all."""
    if table in APPEND_ONLY:
        return "s.recorded_at < (%(cutoff)s::date::timestamp AT TIME ZONE 'UTC')"
    return predicate(table)


def predicate(table):
    if table == 'universe_membership':
        return """s.snapshot_date < %(cutoff)s
            AND s.observed_at < (%(cutoff)s::date::timestamp AT TIME ZONE 'UTC')
            AND EXISTS (SELECT 1 FROM quant_app.universe_snapshots h
                WHERE h.snapshot_date=s.snapshot_date
                  AND h.observed_at < (%(cutoff)s::date::timestamp AT TIME ZONE 'UTC'))
            AND s.snapshot_date < (SELECT max(snapshot_date) FROM quant_app.universe_snapshots)
            AND s.snapshot_date < (SELECT max(snapshot_date) FROM quant_app.universe_snapshots WHERE is_complete)
            AND NOT EXISTS (SELECT 1 FROM quant_app.scanner_observations o
                WHERE o.universe_snapshot_date=s.snapshot_date)"""
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

    def check(self, readable=()):
        """Role shape and grants. `readable`: append-only tables this run will export (SELECT needed)."""
        with self.connection(readonly=True) as conn:
            forbidden = conn.execute("""SELECT EXISTS (
                SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname IN ('quant_app','equity_operations','equity_research')
                  AND c.relkind IN ('r','p','v','m')
                  AND NOT (n.nspname='quant_app' AND c.relname IN
                      ('mf_nav','market_quotes','market_daily_volumes','archive_manifests',
                       'universe_membership_versions','universe_membership','scanner_observations',
                       'evidence_ledger_events')
                       OR n.nspname='equity_research' AND c.relname='outcomes')
                  AND (has_table_privilege(current_user,c.oid,'SELECT')
                    OR has_table_privilege(current_user,c.oid,'INSERT')
                    OR has_table_privilege(current_user,c.oid,'UPDATE')
                    OR has_table_privilege(current_user,c.oid,'DELETE')))
            """).fetchone()[0]
            if forbidden:
                raise ArchiveError('ARCHIVE_ROLE_TOO_BROAD')
            for table in SPECS:
                if table in APPEND_ONLY:
                    # Never deletable by this role; SELECT only when this run exports it.
                    if conn.execute('SELECT has_table_privilege(current_user,%s,%s)',
                                    (RELATIONS[table], 'DELETE,INSERT,UPDATE,TRUNCATE,TRIGGER')).fetchone()[0]:
                        raise ArchiveError('ARCHIVE_APPEND_ONLY_WRITE_GRANT_FORBIDDEN')
                    if table in readable and not conn.execute(
                            'SELECT has_table_privilege(current_user,%s,%s)',
                            (RELATIONS[table], 'SELECT')).fetchone()[0]:
                        raise ArchiveError('ARCHIVE_LEDGER_SELECT_GRANT_MISSING')
                    continue
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
            conn.execute('SELECT snapshot_date,observed_at,is_complete '
                         'FROM quant_app.universe_snapshots LIMIT 0')
            if not conn.execute("""SELECT EXISTS (SELECT 1 FROM pg_trigger
                WHERE tgrelid='quant_app.universe_membership'::regclass
                  AND tgname='canonical_archive_row_guard' AND tgtype=11
                  AND tgenabled IN ('O','A') AND NOT tgisinternal
                  AND tgfoid='quant_app.guard_canonical_archive_delete()'::regprocedure)
                AND has_function_privilege(current_user,
                    'quant_app.lock_canonical_archive_dependencies()', 'EXECUTE')""").fetchone()[0]:
                raise ArchiveError('CANONICAL_ARCHIVE_GUARDS_REQUIRED')
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
        condition = export_condition(table)
        with self.connection(readonly=True) as conn:
            return conn.execute(f'SELECT count(*) FROM {RELATIONS[table]} s WHERE {condition}',
                                {'cutoff': cutoff}).fetchone()[0]

    def select(self, table, cutoff, limit, after=None):
        """Eligible rows in a stable order. `after` (the order key of the last row of the previous
        batch) pages forward without deleting, so bulk export never re-selects the same rows."""
        condition = export_condition(table)
        columns = ORDER_COLUMNS[table]
        order = ','.join(f's.{column}' for column in columns)
        params = {'cutoff': cutoff, 'limit': limit}
        page = ''
        if after is not None:
            if len(after) != len(columns):
                raise ArchiveError('INVALID_PAGE_KEY')
            bounds = ','.join(f'CAST(%(after{i})s AS {SPECS[table][column]})'
                              for i, column in enumerate(columns))
            page = f' AND ({order}) > ({bounds})'
            params.update({f'after{i}': value for i, value in enumerate(after)})
        if table in APPEND_ONLY:
            params['budget'] = LEDGER_PAGE_STORED_BYTES
            # A page ends at the first row's UTC day and at the stored-byte budget (first row always
            # included). Days before the cutoff are closed, so the same page is selected every run.
            sql = f"""WITH eligible AS (
                    SELECT s.recorded_at,s.event_id,pg_column_size(s.payload) AS size
                    FROM {RELATIONS[table]} s WHERE {condition}{page}),
                day AS (SELECT min(recorded_at) AS first FROM eligible),
                ranked AS (
                    SELECT e.event_id,row_number() OVER w AS n,sum(e.size) OVER w AS run
                    FROM eligible e,day
                    WHERE e.recorded_at < ((date_trunc('day',day.first AT TIME ZONE 'UTC')
                                            + interval '1 day') AT TIME ZONE 'UTC')
                    WINDOW w AS (ORDER BY e.recorded_at,e.event_id ROWS UNBOUNDED PRECEDING))
                SELECT to_jsonb(s)::text FROM {RELATIONS[table]} s JOIN ranked r ON r.event_id=s.event_id
                WHERE r.n <= %(limit)s AND (r.n = 1 OR r.run <= %(budget)s) ORDER BY r.n"""
        else:
            sql = (f'SELECT to_jsonb(s)::text FROM {RELATIONS[table]} s '
                   f'WHERE {condition}{page} ORDER BY {order} LIMIT %(limit)s')
        with self.connection(readonly=True) as conn:
            # Canonical PostgreSQL JSON text, never a driver float conversion.
            rows = conn.execute(sql, params).fetchall()
            return [row[0] for row in rows]

    def database_now(self):
        """The database clock: a generation timestamp is always taken from here."""
        with self.connection(readonly=True) as conn:
            text = conn.execute('SELECT clock_timestamp()::text').fetchone()[0]  # full microseconds
        return as_aware(text)

    def generation(self, before):
        """(count, fingerprint) of every catalog batch recorded at or before `before`. Byte-compatible
        with verify_local_archive_copy.INVENTORY_SET_SQL / inventory_set_sha256 for the same rows."""
        with self.connection(readonly=True) as conn:
            count, fingerprint = conn.execute(GENERATION_SQL, {'before': as_aware(before).isoformat()}).fetchone()
        return int(count), fingerprint

    def recorded(self, batch_id):
        """Whether this content-addressed batch is already in the catalog."""
        with self.connection(readonly=True) as conn:
            return conn.execute('SELECT 1 FROM quant_app.archive_manifests WHERE batch_id=%s',
                                (batch_id,)).fetchone() is not None

    def preserved_candidates(self, before, limit, expected, tables):
        """Bind the verified prefix and its candidate records to one statement snapshot."""
        tables = [table for table in tables if table not in APPEND_ONLY]
        with self.connection(readonly=True) as conn:
            rows = conn.execute(f"""
                WITH generation(batch_count,fingerprint) AS ({GENERATION_SQL}),
                candidates AS (
                    SELECT batch_id,source_table,row_count,file_sha256,drive_file_id,
                           drive_manifest_id,verified_at
                    FROM quant_app.archive_manifests
                    WHERE verified_at <= %(before)s::timestamptz AND completed_at IS NULL
                      AND source_table = ANY(%(tables)s::text[])
                    ORDER BY verified_at,batch_id LIMIT %(limit)s
                )
                SELECT g.batch_count,g.fingerprint,c.batch_id,c.source_table,c.row_count,
                       c.file_sha256,c.drive_file_id,c.drive_manifest_id
                FROM generation g LEFT JOIN candidates c ON true
                ORDER BY c.verified_at,c.batch_id""",
                                {'before': as_aware(before).isoformat(), 'limit': limit,
                                 'tables': tables}).fetchall()
        if not rows or tuple(rows[0][:2]) != expected:
            raise ArchiveError('PRESERVED_GENERATION_MISMATCH')
        names = ('batch_id', 'source_table', 'row_count', 'file_sha256', 'drive_file_id', 'drive_manifest_id')
        return [dict(zip(names, row[2:])) for row in rows if row[2] is not None]

    def acknowledge(self, manifest, texts, cutoff, delete, custody=None, *, require_complete=False):
        """Verification records are atomic; deletion needs an active restore proof.

        A deleting call must also pass `custody`, a callable that re-confirms this batch's Drive
        copies. It runs inside the transaction, after the locks and immediately before the
        DELETE; if it raises, nothing is recorded or deleted.

        A completed manifest is never reused to authorize unrelated source data.
        Unknown outcomes require read-only reconciliation, never automatic retry.
        """
        if delete and manifest.get('source_table') in APPEND_ONLY:
            raise ArchiveError('APPEND_ONLY_NEVER_DELETED')
        if delete:
            require_commissioned_delete()  # No active proof: denied before anything else.
            if not restore_check.valid_custody(custody, manifest):
                raise ArchiveError('CUSTODY_CHECK_REQUIRED')
            # This repository (the receiver), the custody check and the proof must all name the same
            # database and Drive folder; the custody object's own claim is not enough.
            receiver = restore_check.context_key(self, custody.drive)
            if receiver != custody.context:
                raise ArchiveError('AUTHENTICATED_CUSTODY_AND_RESTORE_NOT_COMMISSIONED')
            require_commissioned_delete(receiver)
            # The rows deleted must be exactly the verified batch: recompute its content-addressed
            # identity from a snapshot, and delete only that snapshot.
            texts = tuple(texts)
            batch_id, rows = batch_identity(manifest['source_table'], texts)
            if (batch_id != manifest['batch_id'] or len(rows) != manifest['rows']
                    or len(texts) != len(rows)):
                raise ArchiveError('ROWS_NOT_THE_VERIFIED_BATCH')
        table = manifest['source_table']
        condition = predicate(table) if delete else None  # deletion only; export uses export_condition
        with self.connection() as conn:
            # Bounded wait: the byte check ran before this point, so a long queue must fail, not drift.
            conn.execute("SET LOCAL lock_timeout = '5s'")  # same bound as the session option; never longer
            # Transaction-scoped serialization; safe with Supabase session pooler.
            conn.execute('SELECT pg_advisory_xact_lock(71429051)')
            # The custody callback talks to Drive while locks are held: bound the idle wait.
            conn.execute("SET LOCAL idle_in_transaction_session_timeout = '30s'")
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
                'universe_membership': "s.snapshot_date=(v.original->>'snapshot_date')::date AND s.instrument_key=v.original->>'instrument_key'",
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
            if table == 'universe_membership':
                # Stage verified rows before blocking scanner/universe writers.
                # Recheck dependencies and exact payloads under these locks below.
                conn.execute('SELECT quant_app.lock_canonical_archive_dependencies()')
            custody()  # Fresh Drive check of this batch's two copies, right before the DELETE.
            count = conn.execute(f"""WITH removed AS (
                DELETE FROM {RELATIONS[table]} s USING verified_archive_rows v
                WHERE {key_match} AND to_jsonb(s)=v.original AND {condition}
                  AND to_jsonb(jsonb_populate_record(NULL::{RELATIONS[table]}, v.original))=v.original
                RETURNING 1) SELECT count(*) FROM removed""", {'cutoff': cutoff}).fetchone()[0]
            if require_complete and count != len(texts):
                raise ArchiveError('SOURCE_CHANGED_OR_ALREADY_REMOVED_REVIEW_REQUIRED')
            conn.execute("""UPDATE quant_app.archive_manifests
                SET completed_at=clock_timestamp(),
                    deleted_count=GREATEST(COALESCE(deleted_count,0),%s) WHERE batch_id=%s""",
                         (count, manifest['batch_id']))
            return count


def as_aware(value):
    """A timezone-aware datetime from a datetime or ISO text; naive or unparseable is refused."""
    try:
        value = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(str(value))
    except ValueError:
        raise ArchiveError('PRESERVED_GENERATION_REQUIRED') from None
    if value.tzinfo is None:
        raise ArchiveError('PRESERVED_GENERATION_REQUIRED')
    return value


def order_key(table, text):
    row = json.loads(text)
    return tuple(row[column] for column in ORDER_COLUMNS[table])


def run_batch(repo, drive, table, cutoff, limit=1000, delete=False):
    if delete:
        require_commissioned_delete(restore_check.context_key(repo, drive))
    texts = repo.select(table, cutoff, limit)
    if not texts:
        return {'selected': 0, 'verified': 0, 'deleted': 0, 'retained': 0}
    return archive_texts(repo, drive, table, texts, cutoff, delete)


def archive_texts(repo, drive, table, texts, cutoff, delete):
    """Upload one selected batch, verify it, record it, and (when deleting) delete it."""
    manifest, verified = upload_verified(drive, table, texts)
    custody = None
    if delete:
        # Building the check runs the full byte comparison and pins revision ids before any
        # database lock; only the quick form runs under locks.
        custody = restore_check.CustodyCheck(repo, drive, manifest)
    deleted = repo.acknowledge(manifest, verified, cutoff, delete, custody=custody)
    result = {'selected': len(texts), 'verified': len(verified), 'deleted': deleted,
              'retained': len(texts) - deleted, 'batch_id': manifest['batch_id']}
    if not delete:
        # Non-deleting probe on real Drive: would the full check and the under-lock quick check
        # pass for this batch? Reported in the log only; nothing is deleted either way.
        try:
            restore_check.CustodyCheck(repo, drive, manifest)()
            result['custody_probe'] = 'ok'
        except ArchiveError as error:
            result['custody_probe'] = str(error)
        except Exception as error:  # a probe must never break an export; the log shows the type
            result['custody_probe'] = 'PROBE_ERROR_' + type(error).__name__
    return result


def build_drive_credentials():
    try:
        token_info = json.loads(os.environ.get('DRIVE_OAUTH_TOKEN_JSON', '{}'))
    except (ValueError, TypeError):
        raise ArchiveError('INVALID_OAUTH_CONFIGURATION') from None
    return credentials(token_info)


def export_batches(repo, drive, table, cutoff, limit, max_batches, report=None):
    """Upload and record up to `max_batches` NEW batches without deleting anything.

    Pages forward by order key. A page whose content-addressed batch is already in the catalog
    (exported by an earlier run) is passed over without uploading and does not count against
    `max_batches`, so a repeated bounded run continues where the previous one stopped."""
    results, after = [], None
    while len(results) < max_batches:
        texts = repo.select(table, cutoff, limit, after=after) if after is not None else repo.select(
            table, cutoff, limit)
        if not texts:
            break
        after = order_key(table, texts[-1])  # never printed (row values)
        if repo.recorded(batch_identity(table, texts)[0]):
            continue
        results.append(archive_texts(repo, drive, table, texts, cutoff, False))
        if report:
            report(results[-1])
    return results


def prune_preserved(repo, drive, proof, *, before, expected_batches, expected_sha256, today, limit,
                    report=None, nav_cutoff=None, tables=tuple(SPECS), deadline=None):
    """Delete source rows only for batches of an independently preserved generation.

    The generation is every catalog batch recorded at or before `before`; its count and fingerprint
    must equal what the owner verified on an independent copy, or nothing happens. Only exported,
    not-yet-pruned batches of that generation are candidates. Each batch's rows are rebuilt from the
    archive file itself (never selected from the live table), custody is re-proved, and the normal
    deleting transaction runs. Any retained row stops the whole run for review.

    A candidate the proof did not deep-check is refused; an incremental proof deep-checks every
    unpruned batch plus those recorded after `proof.deep_after`, so no pending batch is stranded. `deadline`
    (time.monotonic()) stops starting new batches, so a bounded run ends inside the job limit."""
    before = as_aware(before)
    if (type(expected_batches) is not int or expected_batches < 1
            or not HEX64.fullmatch(str(expected_sha256).lower())):
        raise ArchiveError('PRESERVED_GENERATION_REQUIRED')
    require_commissioned_delete(restore_check.context_key(repo, drive))
    expected = (expected_batches, str(expected_sha256).lower())
    results = []
    for record in repo.preserved_candidates(before, limit, expected, tables):
        if proof.deep_ids is not None and record['batch_id'] not in proof.deep_ids:
            raise ArchiveError('BATCH_NOT_DEEP_PROVEN')
        if deadline is not None and time.monotonic() >= deadline:
            if report:
                report({'stopped': 'TIME_BOUND', 'pruned_batches': len(results)})
            break
        restore_check.recheck_presence(repo, drive, proof)
        table = record['source_table']
        manifest = {'batch_id': record['batch_id'], 'source_table': table, 'rows': record['row_count'],
                    'sha256': record['file_sha256'], 'drive_file_id': record['drive_file_id'],
                    'drive_manifest_id': record['drive_manifest_id']}
        try:
            texts = restore_check.archived_rows(drive.download(record['drive_file_id']), record)
        except ArchiveError:
            raise
        except Exception as error:  # noqa: BLE001 - never print file contents
            raise ArchiveError('PRESERVED_BATCH_UNREADABLE_' + type(error).__name__) from None
        custody = restore_check.CustodyCheck(repo, drive, manifest)
        # A one-time NAV cutoff used at export applies to NAV batches only, as in delete mode.
        cutoff = cutoff_for(table, today, nav_cutoff if table == 'mf_nav' else None)
        deleted = repo.acknowledge(manifest, texts, cutoff, True, custody=custody,
                                   require_complete=True)
        result = {'table': table, 'batch_id': record['batch_id'], 'rows': len(texts), 'deleted': deleted}
        results.append(result)
        if report:
            report(result)
        if deleted != len(texts):
            raise ArchiveError('SOURCE_CHANGED_OR_ALREADY_REMOVED_REVIEW_REQUIRED')
    restore_check.recheck_presence(repo, drive, proof)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description='Verified Drive archival, isolated from scans')
    parser.add_argument('--mode', choices=('preview', 'export', 'restore-check', 'delete', 'prune-preserved'),
                        default='preview')
    parser.add_argument('--table', choices=(*SPECS, 'growing'), default='mf_nav')
    parser.add_argument('--nav-cutoff', type=dt.date.fromisoformat,
                        help='Manual one-time NAV cleanup only; normal policy is 14 days')
    parser.add_argument('--batch-size', type=int, default=None,
                        help='1–2000; default outcomes=100, canonical universe=500, others=1000')
    parser.add_argument('--max-batches', type=int, default=20)
    parser.add_argument('--preserved-before', default=None,
                        help='prune-preserved: generation timestamp with offset (from the database clock)')
    parser.add_argument('--preserved-batches', type=int, default=None,
                        help='prune-preserved: batch count of that generation verified on the copy')
    parser.add_argument('--preserved-sha256', default=None,
                        help='prune-preserved: fingerprint of that generation verified on the copy')
    parser.add_argument('--proven-after', default=None,
                        help='restore-check / prune-preserved: deep-check only batches recorded after this '
                             'timestamp (with offset); use the previous cycle\'s preserved-before')
    parser.add_argument('--max-minutes', type=int, default=None,
                        help=f'prune-preserved: start no new batch after this many minutes (1-{PRUNE_MAX_MINUTES})')
    args = parser.parse_args(argv)
    started = time.monotonic()
    drive = None
    try:
        tables = GROWING_TABLES if args.table == 'growing' else (args.table,)
        if args.table == 'growing' and args.mode not in ('preview', 'export', 'delete', 'prune-preserved'):
            raise ArchiveError('GROWING_PRESET_PREVIEW_EXPORT_OR_DELETE_ONLY')
        pruning = args.mode == 'prune-preserved'
        proven_after = None
        if args.proven_after:
            if args.mode not in ('restore-check', 'prune-preserved'):
                raise ArchiveError('PROVEN_AFTER_RESTORE_CHECK_OR_PRUNE_ONLY')
            proven_after = as_aware(args.proven_after)
        if args.max_minutes is not None and (not pruning or not 1 <= args.max_minutes <= PRUNE_MAX_MINUTES):
            raise ArchiveError('INVALID_MAX_MINUTES')
        before = None
        if pruning:
            before = as_aware(args.preserved_before or '')
            if (args.preserved_batches is None or args.preserved_batches < 1
                    or not HEX64.fullmatch(str(args.preserved_sha256 or '').lower())):
                raise ArchiveError('PRESERVED_GENERATION_REQUIRED')
        sizes = {table: batch_size_for(table, args.batch_size) for table in tables}
        if not 1 <= args.max_batches <= 200:
            raise ArchiveError('INVALID_BATCH_LIMIT')
        deleting = args.mode == 'delete'
        if (deleting or pruning) and os.environ.get('ARCHIVE_DELETE_ENABLED') != 'true':
            raise ArchiveError('DELETION_NOT_ENABLED')
        if (deleting or pruning) and args.table in APPEND_ONLY:
            raise ArchiveError('APPEND_ONLY_NEVER_DELETED')
        today = dt.datetime.now(UTC).date()
        cutoffs = {table: export_cutoff(table, today, args.nav_cutoff) for table in tables}
        repo = ArchiveRepository(os.environ.get('ARCHIVE_DATABASE_URL'))
        repo.check(readable=tables if args.mode in ('preview', 'export') else ())
        for table in tables:
            print(json.dumps({'mode': args.mode, 'table': table, 'cutoff': str(cutoffs[table]),
                              'eligible': repo.preview(table, cutoffs[table])}), flush=True)
        if args.mode == 'preview':
            return 0
        creds = build_drive_credentials()
        drive = DriveArchive(creds, os.environ.get('DRIVE_ARCHIVE_FOLDER_ID', ''))
        if args.mode not in ('restore-check', 'prune-preserved'):
            drive.check_folder()  # Writers need canAddChildren; read-only checks and pruning do not.
        if args.mode == 'restore-check' or deleting or pruning:
            # Pruning always runs the full proof, including the cross-batch key-conflict check.
            proof = restore_check.prove(repo, drive, today=today,
                                        everything=args.mode in ('restore-check', 'prune-preserved'),
                                        deep_after=proven_after,
                                        progress=lambda item: print('RESTORE_PROGRESS ' + json.dumps(item), flush=True))
            print('RESTORE_PROOF ' + json.dumps(proof.summary()), flush=True)
            if not proof.valid_now():
                raise ArchiveError('ARCHIVE_RESTORE_PROOF_FAILED')
            if args.mode == 'restore-check':
                print(json.dumps({'status': 'SUCCESS', 'restore_proof': 'PASSED'}), flush=True)
                return 0
            activate_restore_proof(proof)
        if pruning:
            pruned = prune_preserved(
                repo, drive, proof, before=before, expected_batches=args.preserved_batches,
                expected_sha256=args.preserved_sha256, today=today, limit=args.max_batches,
                nav_cutoff=args.nav_cutoff, tables=tables,
                deadline=None if args.max_minutes is None else started + 60 * args.max_minutes,
                report=lambda item: print('ARCHIVE_PRUNE ' + json.dumps(item), flush=True))
            print(json.dumps({'status': 'SUCCESS', 'pruned_batches': len(pruned),
                              'deleted_rows': sum(item['deleted'] for item in pruned),
                              'eligible_unpruned': {table: repo.preview(table, cutoffs[table])
                                                    for table in tables}}), flush=True)
            return 0
        if args.mode == 'export':
            for table in tables:
                exported = export_batches(
                    repo, drive, table, cutoffs[table], sizes[table], args.max_batches,
                    report=lambda item, table=table: print('ARCHIVE_BATCH ' + json.dumps({'table': table, **item}),
                                                           flush=True))
                print(json.dumps({'status': 'TABLE_EXPORTED', 'table': table, 'batches': len(exported),
                                  'custody_probe_not_ok': sum(item.get('custody_probe') != 'ok'
                                                              for item in exported)}), flush=True)
            # The generation to copy and verify independently, then to give prune-preserved.
            at = repo.database_now()
            count, fingerprint = repo.generation(at)
            print('ARCHIVE_GENERATION ' + json.dumps({'preserved_before': at.isoformat(),
                                                       'preserved_batches': count,
                                                       'preserved_sha256': fingerprint}), flush=True)
            print(json.dumps({'status': 'SUCCESS'}), flush=True)
            return 0
        for table in tables:
            for _ in range(args.max_batches):
                if deleting:
                    # The proof may be minutes old: re-list Drive immediately before each batch.
                    restore_check.recheck_presence(repo, drive, proof)
                result = run_batch(repo, drive, table, cutoffs[table], sizes[table], deleting)
                print('ARCHIVE_BATCH ' + json.dumps({'table': table, **result}), flush=True)
                if result['selected'] == 0:
                    break
                if result['retained']:
                    raise ArchiveError('SOURCE_CHANGED_OR_ALREADY_REMOVED_REVIEW_REQUIRED')
            print(json.dumps({'status': 'TABLE_DONE', 'table': table,
                              'eligible_remaining': repo.preview(table, cutoffs[table])}), flush=True)
        if deleting:
            # Includes tonight's new batches: a copy lost right after deletion fails loudly.
            restore_check.recheck_presence(repo, drive, proof)
        print(json.dumps({'status': 'SUCCESS'}), flush=True)
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
