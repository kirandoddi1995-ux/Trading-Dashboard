"""Atomic, bounded original-history staging for offline cold-reader consumers.

Caller provides immutable pinned history, original keys and independently protected
terminal heads. Nothing is exposed until the input iterator is fully exhausted,
all signatures/identities/heads verified and the caller's end fence succeeds.
Private temporary storage must be on an owner-approved protected volume. This
module neither discovers credentials nor connects to hosted resources.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
import hashlib
import datetime as dt
import json
from pathlib import Path
import sqlite3
import tempfile
import time
from types import MappingProxyType
from typing import cast

from evidence_ledger import GENESIS_HASH, canonical_json
from ledger_segments import FIELDS, Head, MAX_RAW_BYTES, verify_records

MAX_ROWS = 1_000_000
MAX_BYTES = 512 * 1024 * 1024
MAX_SECONDS = 60.0


class HistoryStreamError(ValueError):
    """Stable redacted failure; never expose private paths, rows or driver text."""


@dataclass(frozen=True)
class HistoryWitness:
    """Order-sensitive identity of the fully consumed original history."""

    rows: int
    bytes: int
    sha256: str
    hmac_events: int
    unsigned_events: int
    heads: Mapping[str, Head] = field(repr=False)


class VerifiedHistory:
    """Read-only staged rows, usable only inside the owning context manager."""

    def __init__(self, connection: sqlite3.Connection, witness: HistoryWitness):
        self._connection = connection
        self.witness = witness

    def rows(self) -> Iterator[dict[str, object]]:
        """Return detached original dictionaries, ordered exactly like the input."""
        try:
            cursor = self._connection.execute('SELECT body FROM history ORDER BY ordinal')
            for (body,) in cursor:
                yield cast(dict[str, object], json.loads(body))
        except Exception:
            raise HistoryStreamError('HISTORY_STAGE_UNAVAILABLE') from None

    def duplicate(self, idempotency_key: str) -> dict[str, object] | None:
        """Detached original or absence within this COMPLETE verified cut.

        The existing globally unique retry index avoids rescanning every event
        for each pending delivery. Closed/corrupt spools are errors, not absence.
        """
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key.encode()) <= 900:
            raise HistoryStreamError('HISTORY_RETRY_IDENTITY_INVALID')
        try:
            result = self._connection.execute('SELECT body FROM history WHERE retry_key=?',
                                              (idempotency_key,)).fetchone()
            return None if result is None else cast(dict[str, object], json.loads(result[0]))
        except Exception:
            raise HistoryStreamError('HISTORY_RETRY_READ_BLOCKED') from None

    def decision_pairs(self, *, include_unmatured: bool = False,
                       first_outcome: bool = False) -> Iterator[
                           tuple[dict[str, object], dict[str, object] | None]]:
        """Stream original decision/outcome joins with existing SQL semantics.

        Each decision joins all outcomes in its aggregate, or the first outcome
        by sequence when requested. Unmatured decisions are included only by an
        explicit flag. No current features, fabricated labels or rule retuning.
        """
        if type(include_unmatured) is not bool or type(first_outcome) is not bool:
            raise HistoryStreamError('HISTORY_PAIR_FLAGS_INVALID')
        try:
            # Both reads follow explicit indexes: no global payload sort spilling
            # into SQLite's OS temp directory outside the approved private parent.
            cursor = self._connection.execute('''SELECT body,aggregate_id FROM history
                INDEXED BY history_decision_order_idx WHERE event_type='DECISION_EVALUATED'
                ORDER BY effective_utc,aggregate_id,sequence_no''')
            suffix = ' LIMIT 1' if first_outcome else ''
            for decision, aggregate in cursor:
                outcomes = self._connection.execute('''SELECT body FROM history
                    INDEXED BY history_pair_idx
                    WHERE aggregate_id=? AND event_type='OUTCOME_MATURED'
                    ORDER BY sequence_no''' + suffix, (aggregate,))
                found = False
                for (outcome,) in outcomes:
                    found = True
                    yield (cast(dict[str, object], json.loads(decision)),
                           cast(dict[str, object], json.loads(outcome)))
                if not found and include_unmatured:
                    yield cast(dict[str, object], json.loads(decision)), None
        except Exception:
            raise HistoryStreamError('HISTORY_PAIR_READ_BLOCKED') from None


def _parent(path: Path) -> Path:
    """Require a real existing directory and reject link/reparse ancestors."""
    if not isinstance(path, Path):
        raise HistoryStreamError('HISTORY_PRIVATE_PARENT_INVALID')
    for item in (path, *path.parents):
        if item.is_symlink() or item.is_junction():
            raise HistoryStreamError('HISTORY_PRIVATE_PARENT_LINKED')
    if not path.is_dir():
        raise HistoryStreamError('HISTORY_PRIVATE_PARENT_INVALID')
    return path.resolve(strict=True)


def _expected(value: Mapping[str, Head]) -> dict[str, Head]:
    """Validate even zero-event terminals, including bool/type edge cases."""
    result: dict[str, Head] = {}
    for name, head in value.items():
        if not isinstance(name, str) or not 1 <= len(name.encode()) <= 900:
            raise HistoryStreamError('HISTORY_TERMINAL_INVALID')
        sequence, digest = head
        if (type(sequence) is not int or sequence < 0 or not isinstance(digest, str)
                or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest)
                or (sequence == 0 and digest != GENESIS_HASH)):
            raise HistoryStreamError('HISTORY_TERMINAL_INVALID')
        result[name] = head
    return result


@contextmanager
def stage(records: Iterable[Mapping[str, object]], *, expected_heads: Mapping[str, Head],
          keyring: Mapping[str, bytes], private_parent: Path,
          end_fence: Callable[[], None]) -> Iterator[VerifiedHistory]:
    """Exhaust/verify before yielding, then remove only this ephemeral spool.

    A fence exception blocks exposure. Caller must compare protected root/head
    state before and after its complete stream; a no-op is acceptable ONLY for
    already immutable offline fixtures. This API grants no archive/delete rights.
    Size/time limits are checked between input reads: transport must independently
    impose a timeout. No checkpoint/outbox/application recovery claim is made.
    """
    try:
        expected = _expected(expected_heads)
        parent = _parent(private_parent)
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix='verified-ledger-', dir=parent) as directory:
            with closing(sqlite3.connect(Path(directory) / 'history.sqlite')) as connection:
                try:
                    connection.execute('PRAGMA journal_mode=DELETE')
                    connection.execute('PRAGMA temp_store=FILE')
                    connection.execute('PRAGMA cache_size=-2048')
                    connection.execute('PRAGMA page_size=4096')
                    connection.execute(f'PRAGMA max_page_count={MAX_BYTES // 4096}')
                    connection.execute('''CREATE TABLE history (
                        ordinal INTEGER PRIMARY KEY,event_id TEXT NOT NULL UNIQUE,
                        retry_key TEXT NOT NULL UNIQUE,body TEXT NOT NULL,
                        aggregate_id TEXT NOT NULL,event_type TEXT NOT NULL,
                        sequence_no INTEGER NOT NULL,effective_utc TEXT NOT NULL)''')
                    connection.execute('CREATE INDEX history_pair_idx ON history(aggregate_id,event_type,sequence_no)')
                    connection.execute('CREATE INDEX history_decision_order_idx ON history(event_type,effective_utc,aggregate_id,sequence_no)')
                    heads: dict[str, Head] = {}
                    total, count = 0, 0
                    hmac_count = 0
                    identity = hashlib.sha256(b'ledger-history-stream-v1\x00')
                    for row in records:
                        if time.monotonic() - started > MAX_SECONDS:
                            raise HistoryStreamError('HISTORY_STAGE_TIMEOUT')
                        count += 1
                        if count > MAX_ROWS:
                            raise HistoryStreamError('HISTORY_STAGE_ROW_LIMIT')
                        heads = verify_records([row], heads, keyring)
                        hmac_count += int(row['hash_algorithm'] == 'HMAC-SHA256')
                        body = canonical_json({name: row[name] for name in FIELDS}).encode()
                        total += len(body)
                        if len(body) > MAX_RAW_BYTES or total > MAX_BYTES:
                            raise HistoryStreamError('HISTORY_STAGE_BYTE_LIMIT')
                        identity.update(len(body).to_bytes(8, 'big'))
                        identity.update(body)
                        stamp = row['effective_at']
                        if isinstance(stamp, str):
                            instant = dt.datetime.fromisoformat(stamp.replace('Z', '+00:00'))
                        elif isinstance(stamp, dt.datetime):
                            instant = stamp
                        else:
                            raise HistoryStreamError('HISTORY_CLOCK_INVALID')
                        connection.execute('INSERT INTO history VALUES(?,?,?,?,?,?,?,?)',
                            (count, str(row['event_id']), row['idempotency_key'], body.decode(),
                             row['aggregate_id'], row['event_type'], row['sequence_no'],
                             instant.astimezone(dt.timezone.utc).isoformat(timespec='microseconds')))
                    actual = {name: head for name, head in expected.items() if head[0] == 0}
                    actual.update(heads)
                    if actual != expected:
                        raise HistoryStreamError('HISTORY_TERMINAL_MISMATCH')
                    if time.monotonic() - started > MAX_SECONDS:
                        raise HistoryStreamError('HISTORY_STAGE_TIMEOUT')
                    end_fence()
                    if time.monotonic() - started > MAX_SECONDS:
                        raise HistoryStreamError('HISTORY_STAGE_TIMEOUT')
                    connection.commit()
                    connection.execute('PRAGMA query_only=ON')
                    witness = HistoryWitness(count, total, identity.hexdigest(), hmac_count,
                                             count-hmac_count,
                                             MappingProxyType(dict(actual)))
                    yield VerifiedHistory(connection, witness)
                finally:
                    connection.close()
    except HistoryStreamError:
        raise
    except Exception:
        raise HistoryStreamError('HISTORY_STAGE_BLOCKED') from None
