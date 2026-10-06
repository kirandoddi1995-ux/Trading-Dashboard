"""Read original hot/cold evidence against protected SQL state, without SQL writes.

The bounded repeatable-read snapshot closes BEFORE any Drive request. Injected
credentials/transport have no import-time effects. Missing cold material and
missing protected terminals are errors, never shorter apparently valid histories.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
import re
from types import MappingProxyType
from typing import cast

from catalog_receipts import RootAnchor, genesis, verify
from cold_catalog import Catalog
from ledger_archive_publication import PrivateObjects
from ledger_archive_repository import Connection, SourceCapture, begin_read_snapshot
from ledger_cold_store import ColdLedger, MAX_BATCH_ROWS
from ledger_segments import Head, MAX_RAW_BYTES

HEX = re.compile(r'[0-9a-f]{64}')
MAX_HOT_ROWS = 20_000
MAX_HOT_AGGREGATES = 100_000


class LedgerReadError(ValueError):
    """Stable errors; no raw driver/Drive response, payload or secret output."""


def append_error(exc: Exception) -> LedgerReadError:
    """Expose only reviewed SQL control codes, never a raw driver's diagnostics."""
    allowed = {'STORAGE_APPEND_ROOT_CHANGED', 'STORAGE_APPEND_TERMINAL_CHANGED',
               'STORAGE_COLD_APPEND_STAGE_INVALID', 'STORAGE_COLD_APPEND_STAGE_MISSING',
               'STORAGE_HEADS_NOT_COMMISSIONED', 'STORAGE_HEAD_ROOT_MISSING',
               'STORAGE_TEMP_STAGE_UNSAFE', 'STORAGE_HOT_TAIL_MISSING_OR_CHANGED',
               'STORAGE_HOT_APPEND_PREDECESSOR_MISMATCH'}
    message = getattr(getattr(exc, 'diag', None), 'message_primary', None)
    if message is None:
        message = str(exc)
    return LedgerReadError(message if isinstance(message, str) and message in allowed
                           else 'LEDGER_APPEND_TRANSACTION_FAILED')


@dataclass(frozen=True)
class LedgerSnapshot:
    """SQL root and independent terminal from the SAME repeatable-read snapshot."""
    anchor: RootAnchor
    previous: RootAnchor | None
    terminal: Head | None
    native_rows: tuple[str, ...] = field(repr=False)


@dataclass(frozen=True)
class AppendEvidence:
    """Verified pre-transaction evidence; the writer MUST recheck its SQL anchor.

    No open SQL transaction or lazy Drive fetch is carried into the write path.
    A duplicate contains the original signed event, never a reconstructed event.
    """
    aggregate: str
    snapshot: LedgerSnapshot
    cold_head: Head
    terminal: Head
    duplicate: Mapping[str, object] | None = field(repr=False)


@dataclass(frozen=True)
class LedgerOverview:
    """A small consistent SQL root/head fence, without payloads or remote reads."""
    anchor: RootAnchor
    previous: RootAnchor | None
    heads: Mapping[str, Head] = field(repr=False)


class LedgerRuntimeReader:
    """Verify receipts, original signatures and protected terminal on each read."""

    def __init__(self, connect: Callable[[], AbstractContextManager[Connection]],
                 objects: PrivateObjects, event_keys: Mapping[str, bytes],
                 seal_key: bytes, receipt_keys: Mapping[str, bytes]):
        self.connect = connect
        self.objects = objects
        self.event_keys = event_keys
        self.seal_key = seal_key
        self.receipt_keys = receipt_keys

    @staticmethod
    def _state(conn: Connection) -> tuple[RootAnchor, RootAnchor | None]:
        """Validate commissioned control and protected root within caller snapshot."""
        control = conn.execute('''SELECT heads_enabled,head_audit_sha256
            FROM quant_storage.ledger_control WHERE singleton''').fetchone()
        if (control is None or control[0] is not True
                or not isinstance(control[1], str) or not HEX.fullmatch(control[1])):
            raise LedgerReadError('LEDGER_HEADS_NOT_COMMISSIONED')
        root = conn.execute('''SELECT scope,generation,root,receipt_sha256,
            previous_root,previous_receipt FROM quant_storage.catalog_roots
            WHERE scope='ledger' ''').fetchone()
        if root is None:
            raise LedgerReadError('LEDGER_ROOT_MISSING')
        if (root[0] != 'ledger' or type(root[1]) is not int or root[1] < 0
                or any(not isinstance(value, str) or not HEX.fullmatch(value) for value in root[2:4])):
            raise LedgerReadError('LEDGER_ROOT_INVALID')
        anchor = RootAnchor('ledger', root[1], cast(str, root[2]), cast(str, root[3]))
        if anchor.generation == 0:
            if anchor != genesis('ledger') or root[4] is not None or root[5] is not None:
                raise LedgerReadError('LEDGER_ROOT_INVALID')
            return anchor, None
        if any(not isinstance(value, str) or not HEX.fullmatch(value) for value in root[4:6]):
            raise LedgerReadError('LEDGER_ROOT_INVALID')
        return anchor, RootAnchor('ledger', anchor.generation-1,
                                 cast(str, root[4]), cast(str, root[5]))

    @contextmanager
    def _read_connection(self) -> Iterator[Connection]:
        """Bound every snapshot and release its transaction before remote reads."""
        try:
            with self.connect() as conn:
                try:
                    begin_read_snapshot(conn)
                    yield conn
                finally:
                    conn.rollback()  # Explicit read-only rollback; context is not a commit contract.
        except LedgerReadError:
            raise
        except Exception:
            raise LedgerReadError('LEDGER_SQL_SNAPSHOT_FAILED') from None

    def snapshot(self, aggregate: str) -> LedgerSnapshot:
        """Read bounded SQL evidence in a read-only transaction, then release it."""
        if not isinstance(aggregate, str) or not 1 <= len(aggregate.encode()) <= 900:
            raise LedgerReadError('LEDGER_AGGREGATE_INVALID')
        with self._read_connection() as conn:
            anchor, previous = self._state(conn)
            head = conn.execute('''SELECT sequence_no,event_hash
                FROM quant_storage.ledger_hot_heads WHERE aggregate_id=%s''', (aggregate,)).fetchone()
            if head is not None and (type(head[0]) is not int or head[0] < 1
                    or not isinstance(head[1], str) or not HEX.fullmatch(head[1])):
                raise LedgerReadError('LEDGER_TERMINAL_INVALID')
            rows = conn.execute('''SELECT to_jsonb(e)::text FROM quant_app.evidence_ledger_events e
                WHERE aggregate_id=%s ORDER BY sequence_no LIMIT %s''',
                                (aggregate, MAX_HOT_ROWS+1)).fetchall()
            if (len(rows) > MAX_HOT_ROWS or any(not isinstance(row[0], str) for row in rows)
                    or sum(len(cast(str, row[0]).encode()) for row in rows) > MAX_RAW_BYTES):
                raise LedgerReadError('LEDGER_HOT_READ_REQUIRES_PAGINATION')
            native = tuple(cast(str, row[0]) for row in rows)
            if native and head is None:
                raise LedgerReadError('LEDGER_PROTECTED_TERMINAL_MISSING')
            return LedgerSnapshot(anchor, previous,
                None if head is None else (cast(int, head[0]), cast(str, head[1])), native)

    def overview(self) -> LedgerOverview:
        """Take one root/head fence and check all available hot terminal rows."""
        with self._read_connection() as conn:
            anchor, previous = self._state(conn)
            rows = conn.execute('''SELECT COALESCE(h.aggregate_id,e.aggregate_id),
                h.sequence_no,h.event_hash,e.sequence_no,e.event_hash
                FROM quant_storage.ledger_hot_heads h FULL JOIN (
                  SELECT DISTINCT ON(aggregate_id) aggregate_id,sequence_no,event_hash
                  FROM quant_app.evidence_ledger_events ORDER BY aggregate_id,sequence_no DESC
                ) e ON e.aggregate_id=h.aggregate_id
                ORDER BY 1 LIMIT %s''', (MAX_HOT_AGGREGATES+1,)).fetchall()
            if len(rows) > MAX_HOT_AGGREGATES:
                raise LedgerReadError('LEDGER_OVERVIEW_REQUIRES_PAGINATION')
            heads: dict[str, Head] = {}
            for name, sequence, digest, hot_sequence, hot_digest in rows:
                if (not isinstance(name, str) or not 1 <= len(name.encode()) <= 900
                        or type(sequence) is not int or sequence < 1
                        or not isinstance(digest, str) or not HEX.fullmatch(digest)
                        or (sequence, digest) != (hot_sequence, hot_digest)):
                    raise LedgerReadError('LEDGER_HOT_TERMINAL_INCONSISTENT')
                heads[name] = (sequence, digest)
            return LedgerOverview(anchor, previous, MappingProxyType(heads))

    def verified_events(self) -> Iterator[dict[str, object]]:
        """Read every original hot/cold aggregate; exhaust before trusting results.

        Independent short SQL snapshots are fenced by identical root/head states
        before and after traversal. Concurrent append/archive causes an error,
        never a successful mixed-time global audit. No SQL is held across HTTP.
        """
        before = self.overview()
        try:
            cold = self.cold(LedgerSnapshot(before.anchor, before.previous, None, ()))
            names = sorted(set(cold.aggregates()) | set(before.heads))
            event_ids: set[str] = set()
            retry_keys: set[str] = set()
            for name in names:
                snapshot = self.snapshot(name)
                if snapshot.anchor != before.anchor or snapshot.terminal != before.heads.get(name):
                    raise LedgerReadError('LEDGER_GLOBAL_SNAPSHOT_CHANGED')
                expected = before.heads.get(name, cold.frontier(name))
                for row in cold.merged(name, self._hot_records(snapshot), expected):
                    event_id, retry = cast(str, row['event_id']), cast(str, row['idempotency_key'])
                    if event_id in event_ids or retry in retry_keys:
                        raise LedgerReadError('LEDGER_GLOBAL_IDENTITY_REUSED')
                    event_ids.add(event_id)
                    retry_keys.add(retry)
                    yield dict(row)
            if self.overview() != before:
                raise LedgerReadError('LEDGER_GLOBAL_SNAPSHOT_CHANGED')
        except LedgerReadError:
            raise
        except Exception:
            raise LedgerReadError('LEDGER_GLOBAL_ORIGINALS_UNVERIFIED') from None

    def audit(self) -> dict[str, object]:
        """Global original-signature/chain audit, including fully cold aggregates."""
        count = sum(1 for _ in self.verified_events())
        return {'verified': True, 'broken_links': 0, 'duplicate_sequences': 0,
                'events': count, 'scope': 'ORIGINAL_HMAC_HOT_AND_COLD'}

    def cold(self, snapshot: LedgerSnapshot) -> ColdLedger:
        """Resolve cold objects AFTER SQL closes, using its protected signed root."""
        if snapshot.previous is not None:
            data = self.objects.get('root-receipt', snapshot.anchor.receipt_sha256)
            if data is None:
                raise LedgerReadError('LEDGER_RECEIPT_UNAVAILABLE')
            if verify(data, snapshot.anchor.receipt_sha256, snapshot.previous,
                      self.receipt_keys) != snapshot.anchor:
                raise LedgerReadError('LEDGER_RECEIPT_MISMATCH')
        return ColdLedger(Catalog(snapshot.anchor.root,
            lambda digest: self.objects.get('catalog-page', digest)),
            lambda digest: self.objects.get('ledger-segment', digest),
            self.event_keys, self.seal_key)

    def events(self, aggregate: str) -> list[dict[str, object]]:
        """Reconstruct original history; no fallback on failed verification."""
        snapshot = self.snapshot(aggregate)
        try:
            cold = self.cold(snapshot)
            hot = self._hot_records(snapshot)
            expected = snapshot.terminal if snapshot.terminal is not None else cold.frontier(aggregate)
            if snapshot.terminal is not None and not hot:
                raise LedgerReadError('LEDGER_HOT_TAIL_MISSING')
            return [dict(row) for row in cold.merged(aggregate, hot, expected)]
        except LedgerReadError:
            raise
        except Exception:
            raise LedgerReadError('LEDGER_ORIGINAL_HISTORY_UNVERIFIED') from None

    @staticmethod
    def _hot_records(snapshot: LedgerSnapshot) -> list[dict[str, object]]:
        """Normalize bounded native rows without changing original signing material."""
        hot: list[dict[str, object]] = []
        for start in range(0, len(snapshot.native_rows), MAX_BATCH_ROWS):
            hot.extend(SourceCapture(snapshot.native_rows[start:start+MAX_BATCH_ROWS]).records())
        return hot

    def prepare_append(self, aggregate: str, idempotency_key: str) -> AppendEvidence:
        """Verify original chain and global cold retry identity BEFORE SQL locks.

        This is preparation, not write authorization. The protected root and hot
        terminal must still be compared inside the transaction before inserting.
        Cold lookup failures are errors, not permission to reuse an identity.
        """
        if (not isinstance(idempotency_key, str)
                or not 1 <= len(idempotency_key.encode()) <= 900):
            raise LedgerReadError('LEDGER_IDEMPOTENCY_INVALID')
        snapshot = self.snapshot(aggregate)
        try:
            cold = self.cold(snapshot)
            frontier = cold.frontier(aggregate)
            hot = self._hot_records(snapshot)
            terminal = snapshot.terminal if snapshot.terminal is not None else frontier
            if snapshot.terminal is not None and not hot:
                raise LedgerReadError('LEDGER_HOT_TAIL_MISSING')
            cold.merged(aggregate, hot, terminal)
            duplicate = cold.duplicate(idempotency_key)
            hot_duplicates = [row for row in hot if row['idempotency_key'] == idempotency_key]
            if duplicate is not None and hot_duplicates:
                raise LedgerReadError('LEDGER_DUPLICATE_IDENTITY_OVERLAP')
            return AppendEvidence(aggregate, snapshot, frontier, terminal, duplicate)
        except LedgerReadError:
            raise
        except Exception:
            raise LedgerReadError('LEDGER_APPEND_EVIDENCE_UNVERIFIED') from None

    @staticmethod
    def lock_append(conn: Connection, prepared: AppendEvidence, fingerprint: str) -> None:
        """Stage verified evidence and recheck under root-before-aggregate locks.

        Caller owns commit/rollback; no network and no permanent metadata writes.
        Stale evidence raises, requiring a fresh preparation outside SQL locks.
        """
        if not isinstance(fingerprint, str) or not HEX.fullmatch(fingerprint):
            raise LedgerReadError('LEDGER_WRITER_FINGERPRINT_INVALID')
        for query in ("SET LOCAL transaction_timeout='30s'", "SET LOCAL statement_timeout='30s'",
                      "SET LOCAL lock_timeout='2s'", "SET LOCAL TimeZone='UTC'"):
            conn.execute(query)
        conn.execute('''CREATE TEMP TABLE quant_storage_append_stage (
            generation bigint,root text,receipt_sha256 text,aggregate_id text,
            reader_fingerprint text,cold_sequence bigint,cold_hash text) ON COMMIT DROP''')
        # Aggregate comes from verified snapshot rows or the explicit request,
        # never a cold duplicate belonging to a different aggregate.
        conn.execute('''INSERT INTO quant_storage_append_stage VALUES(%s,%s,%s,%s,%s,%s,%s)''',
                     (prepared.snapshot.anchor.generation, prepared.snapshot.anchor.root,
                      prepared.snapshot.anchor.receipt_sha256, prepared.aggregate,
                      fingerprint, *prepared.cold_head))
        conn.execute('SELECT quant_storage.lock_ledger_append(%s,%s)',
                     prepared.snapshot.terminal if prepared.snapshot.terminal is not None else (None, None))
