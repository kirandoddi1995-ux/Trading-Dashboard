"""Exact native-row ledger archive transactions over an injected private connection.

No selection/retention policy is inferred here: the caller must commission readers
and supply dependency-safe prefixes. This repository performs no automatic task or
hosted connection. Upload/readback completes BEFORE its bounded SQL transaction.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Protocol, cast

from catalog_receipts import RootAnchor
from ledger_archive_publication import PrivateObjects, PublishedLedger, verify_publication
from ledger_cold_store import MAX_AGGREGATES, MAX_BATCH_ROWS
from ledger_segments import FIELDS, MAX_RAW_BYTES

HEX = re.compile(r'[0-9a-f]{64}')


class Result(Protocol):
    """Minimal driver surface shared by psycopg and disposable SQL tests."""

    def fetchone(self) -> Sequence[object] | None: ...

    def fetchall(self) -> Sequence[Sequence[object]]: ...


class Connection(Protocol):
    """Driver connection; the repository owns explicit commit/rollback."""

    def execute(self, query: str, params: Sequence[object] = ()) -> Result: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


def begin_read_snapshot(connection: Connection) -> None:
    """Enforce bounded read-only isolation, including wrappers that issued BEGIN.

    Caller must invoke inside try/finally and always roll back. A pre-existing
    transaction that has already queried cannot silently retain weaker isolation:
    SET TRANSACTION fails and the caller discards the read instead.
    """
    for query in ('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY',
                  'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY',
                  "SET LOCAL transaction_timeout='15s'",
                  "SET LOCAL statement_timeout='10s'", "SET LOCAL lock_timeout='2s'",
                  "SET LOCAL TimeZone='UTC'"):
        connection.execute(query)


class ArchiveTransactionError(ValueError):
    """Stable errors that never include native rows or driver credentials."""


@dataclass(frozen=True)
class SourceCapture:
    """Exact PostgreSQL to_jsonb(row)::text; reparse copies, never mutate evidence."""

    row_texts: tuple[str, ...] = field(repr=False)

    def records(self) -> list[dict[str, object]]:
        """Validate bounded native source envelopes without inventing fields."""
        if (not 1 <= len(self.row_texts) <= MAX_BATCH_ROWS
                or any(not isinstance(text, str) for text in self.row_texts)
                or sum(len(text.encode('utf-8')) for text in self.row_texts) > MAX_RAW_BYTES):
            raise ArchiveTransactionError('ARCHIVE_SOURCE_LIMIT')
        rows: list[dict[str, object]] = []
        for text in self.row_texts:
            try:
                row = json.loads(text)
            except (ValueError, UnicodeError):
                raise ArchiveTransactionError('ARCHIVE_SOURCE_INVALID') from None
            if not isinstance(row, dict) or set(row) != set(FIELDS):
                raise ArchiveTransactionError('ARCHIVE_SOURCE_INVALID')
            # PostgreSQL JSON timestamps trim trailing fractional zeroes. The
            # original Python signer used UTC datetime.isoformat(), including
            # six fractional digits when nonzero. Recover that representation,
            # while retaining untouched native text separately for DELETE proof.
            for name in ('recorded_at', 'effective_at'):
                stamp = row[name]
                if not isinstance(stamp, str):
                    raise ArchiveTransactionError('ARCHIVE_SOURCE_CLOCK_INVALID')
                try:
                    parsed = datetime.fromisoformat(stamp)
                except ValueError:
                    raise ArchiveTransactionError('ARCHIVE_SOURCE_CLOCK_INVALID') from None
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    raise ArchiveTransactionError('ARCHIVE_SOURCE_CLOCK_INVALID')
                row[name] = parsed.astimezone(timezone.utc).isoformat()
            rows.append(row)
        if len({str(row['aggregate_id']) for row in rows}) > MAX_AGGREGATES:
            raise ArchiveTransactionError('ARCHIVE_AGGREGATE_LIMIT')
        if (any(not isinstance(row['event_id'], str) for row in rows)
                or len({row['event_id'] for row in rows}) != len(rows)):
            raise ArchiveTransactionError('ARCHIVE_SOURCE_IDENTITY_INVALID')
        return rows


class LedgerArchiveRepository:
    """Commit original-row deletion and root CAS together; no blind retry delete."""

    def __init__(self, connect: Callable[[], AbstractContextManager[Connection]]):
        self.connect = connect

    def commit(self, source: SourceCapture, publication: PublishedLedger,
               objects: PrivateObjects, event_keys: Mapping[str, bytes], seal_key: bytes,
               receipt_keys: Mapping[str, bytes], reader_fingerprint: str) -> str:
        """Return COMMITTED or ALREADY_COMMITTED after full remote re-verification."""
        if not isinstance(reader_fingerprint, str) or not HEX.fullmatch(reader_fingerprint):
            raise ArchiveTransactionError('ARCHIVE_READER_FINGERPRINT_INVALID')
        records = source.records()
        verify_publication(publication, records, objects, event_keys, seal_key, receipt_keys)
        try:
            with self.connect() as conn:
                # ProductionRepository.connect closes but does NOT commit. Never
                # infer a successful archive from exiting an arbitrary context.
                conn.execute('BEGIN')
                try:
                    status = self._commit(conn, source, records, publication, reader_fingerprint)
                    conn.commit()
                    return status
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        # Broken connections must be discarded by the context.
                        pass
                    raise
        except ArchiveTransactionError:
            raise
        except Exception:
            # Driver/provider errors can include connection details; never expose them.
            raise ArchiveTransactionError('ARCHIVE_TRANSACTION_FAILED') from None

    @staticmethod
    def _commit(conn: Connection, source: SourceCapture, records: list[dict[str, object]],
                publication: PublishedLedger, fingerprint: str) -> str:
        for query in ("SET LOCAL transaction_timeout='30s'",
                      "SET LOCAL statement_timeout='30s'", "SET LOCAL lock_timeout='2s'",
                      "SET LOCAL TimeZone='UTC'"):
            conn.execute(query)
        row = conn.execute("""SELECT scope,generation,root,receipt_sha256
            FROM quant_storage.catalog_roots WHERE scope='ledger' FOR UPDATE""").fetchone()
        if row is None:
            raise ArchiveTransactionError('ARCHIVE_ROOT_MISSING')
        actual = RootAnchor(cast(str, row[0]), cast(int, row[1]),
                            cast(str, row[2]), cast(str, row[3]))
        if actual not in (publication.previous, publication.receipt.anchor):
            raise ArchiveTransactionError('ARCHIVE_ROOT_CHANGED')
        for aggregate in sorted({cast(str, record['aggregate_id']) for record in records}):
            conn.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', (aggregate,))
        ids = [cast(str, record['event_id']) for record in records]
        current = conn.execute("""SELECT event_id::text,to_jsonb(e)::text
            FROM quant_app.evidence_ledger_events e WHERE event_id=ANY(%s::uuid[])
            ORDER BY aggregate_id,sequence_no""", (ids,)).fetchall()
        # FOR UPDATE would require granting source UPDATE to the archiver.
        # Keep SELECT/DELETE only: DELETE takes the row locks and its trigger
        # rechecks the exact native hash after waiting for a concurrent writer.
        if actual == publication.receipt.anchor:
            if current:
                raise ArchiveTransactionError('ARCHIVE_COMMIT_INCONSISTENT')
            return 'ALREADY_COMMITTED'
        expected = {record['event_id']: text for record, text in zip(records, source.row_texts)}
        if {row[0]: row[1] for row in current} != expected:
            raise ArchiveTransactionError('ARCHIVE_SOURCE_CHANGED')
        LedgerArchiveRepository._stage(conn, records, source, publication, fingerprint)
        deleted = conn.execute("""DELETE FROM quant_app.evidence_ledger_events
            WHERE event_id=ANY(%s::uuid[]) RETURNING event_id::text""", (ids,)).fetchall()
        if {row[0] for row in deleted} != set(ids) or len(deleted) != len(ids):
            raise ArchiveTransactionError('ARCHIVE_DELETE_COUNT_MISMATCH')
        before, after = publication.previous, publication.receipt.anchor
        advanced = conn.execute("""UPDATE quant_storage.catalog_roots SET generation=%s,
            root=%s,receipt_sha256=%s,previous_root=%s,previous_receipt=%s,
            segment=%s,key_id=%s,published_at=%s
            WHERE scope='ledger' AND generation=%s AND root=%s AND receipt_sha256=%s
            RETURNING generation""", (after.generation, after.root, after.receipt_sha256,
                                      before.root, before.receipt_sha256,
                                      publication.prepared.segment.sha256, publication.key_id,
                                      publication.published_at, before.generation, before.root,
                                      before.receipt_sha256)).fetchone()
        if advanced is None:
            raise ArchiveTransactionError('ARCHIVE_ROOT_CHANGED')
        # Exercise deferred proof now; connection context still owns final COMMIT.
        conn.execute('SET CONSTRAINTS ALL IMMEDIATE')
        return 'COMMITTED'

    @staticmethod
    def _stage(conn: Connection, records: list[dict[str, object]], source: SourceCapture,
               publication: PublishedLedger, fingerprint: str) -> None:
        conn.execute("""CREATE TEMP TABLE quant_storage_ledger_rows (
            event_id uuid PRIMARY KEY,event_hash text NOT NULL,aggregate_id text NOT NULL,
            sequence_no bigint NOT NULL,source_sha256 text NOT NULL) ON COMMIT DROP""")
        proof: list[object] = []
        for record, text in zip(records, source.row_texts):
            proof.extend((record['event_id'], record['event_hash'], record['aggregate_id'],
                          record['sequence_no'], hashlib.sha256(text.encode('utf-8')).hexdigest()))
        # One bounded insert, not up to 900 network round trips while holding root.
        values = ','.join(['(%s,%s,%s,%s,%s)'] * len(records))
        conn.execute('INSERT INTO quant_storage_ledger_rows VALUES ' + values, proof)
        conn.execute("""CREATE TEMP TABLE quant_storage_ledger_stage (
            reader_fingerprint text,source_count bigint,previous_generation bigint,
            previous_root text,previous_receipt text,next_generation bigint,next_root text,
            next_receipt text,segment text) ON COMMIT DROP""")
        before, after = publication.previous, publication.receipt.anchor
        conn.execute('INSERT INTO quant_storage_ledger_stage VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                     (fingerprint, len(records), before.generation, before.root,
                      before.receipt_sha256, after.generation, after.root,
                      after.receipt_sha256, publication.prepared.segment.sha256))
