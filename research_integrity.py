"""Local research provenance and sealed development access; never live authority."""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any
from collections.abc import Callable
import uuid

MAX_INPUT_BYTES = 64 * 1024 * 1024


class IntegrityError(ValueError):
    """Fixed non-sensitive failure codes for the automation boundary."""


def canonical(value: Any) -> bytes:
    """Canonical JSON rejects nonfinite numbers and produces stable hashes."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(data: bytes) -> str:
    """SHA-256 of exact bytes, not a platform-dependent representation."""
    return hashlib.sha256(data).hexdigest()


def hash_value(value: Any) -> str:
    """Fingerprint a JSON record independently of dictionary insertion order."""
    return digest(canonical(value))


def require_hash(value: Any) -> str:
    """Accept only explicit lowercase SHA-256 values."""
    if not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{64}', value) is None:
        raise IntegrityError('INVALID_SHA256')
    return value


@dataclass(frozen=True)
class DevelopmentManifest:
    """Hash-bound artifact declared development-only; adapters verify content dates."""

    relative_path: str
    sha256: str
    start: str
    end: str

    def read_bytes(self, root: Path) -> bytes:
        """Check declared partition/path BEFORE reading, then verify exact bytes.

        Content dates also require verification by the replay diagnostic adapter;
        declaration alone is not evidence. This API deliberately has no unseal
        flag, including for owners: future validation needs separate review.
        """
        try:
            start, end = date.fromisoformat(self.start), date.fromisoformat(self.end)
        except ValueError:
            raise IntegrityError('INVALID_DATA_PERIOD') from None
        if not date(2022, 1, 1) <= start <= end <= date(2024, 12, 31):
            raise IntegrityError('SEALED_OR_UNSUPPORTED_PARTITION')
        require_hash(self.sha256)
        relative = Path(self.relative_path)
        if (relative.anchor or '..' in relative.parts or not relative.parts
                or '\\' in self.relative_path or ':' in self.relative_path):
            raise IntegrityError('UNSAFE_DATA_PATH')
        base = root.resolve()
        path = base
        for part in relative.parts:
            path = path / part
            if path.is_symlink():
                raise IntegrityError('SYMLINK_DATA_FORBIDDEN')
        if not path.resolve().is_relative_to(base) or not path.is_file():
            raise IntegrityError('DATA_UNAVAILABLE')
        with path.open('rb') as source:
            raw = source.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise IntegrityError('DATA_TOO_LARGE')
        if digest(raw) != self.sha256:
            raise IntegrityError('DATA_HASH_MISMATCH')
        return raw

    def load(self, root: Path) -> dict[str, Any]:
        """Load a verified object report; CSV/calendar loaders reuse read_bytes."""
        raw = self.read_bytes(root)
        try:
            result = json.loads(raw.decode('utf-8-sig'))
        except (ValueError, UnicodeError):
            raise IntegrityError('INVALID_REPORT_JSON') from None
        if not isinstance(result, dict):
            raise IntegrityError('REPORT_OBJECT_REQUIRED')
        return result


class TrialLedger:
    """Append-only SQLite hash chain with serialized writes and no overwrite API.

    Transaction/trigger integrity protects accidental mutation, not a malicious
    OS/file owner or undetectable suffix truncation. Back up the file externally;
    do not call this cryptographically immutable or use it for live evidence.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS research_events (
                    sequence INTEGER PRIMARY KEY, previous_hash TEXT NOT NULL,
                    event_json TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE
                );
                CREATE TRIGGER IF NOT EXISTS research_no_update
                BEFORE UPDATE ON research_events BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY'); END;
                CREATE TRIGGER IF NOT EXISTS research_no_delete
                BEFORE DELETE ON research_events BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY'); END;
            ''')

    def connect(self) -> sqlite3.Connection:
        """A local bounded connection; FULL synchronous commits precede return."""
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.execute('PRAGMA synchronous=FULL')
        return connection

    @staticmethod
    def _events(connection: sqlite3.Connection) -> list[dict[str, Any]]:
        previous = '0' * 64
        result: list[dict[str, Any]] = []
        for index, (sequence, prior, text, stored) in enumerate(connection.execute(
                'SELECT sequence,previous_hash,event_json,event_hash FROM research_events ORDER BY sequence'), 1):
            if sequence != index or prior != previous or digest((prior + '\n' + text).encode()) != stored:
                raise IntegrityError('TRIAL_LEDGER_CORRUPT')
            event = json.loads(text)
            if not isinstance(event, dict):
                raise IntegrityError('TRIAL_LEDGER_CORRUPT')
            result.append(event)
            previous = stored
        return result

    def events(self) -> list[dict[str, Any]]:
        """Verify the complete chain before returning any research history."""
        with closing(self.connect()) as connection:
            return self._events(connection)

    def append(self, event: dict[str, Any]) -> None:
        """Validate lifecycle and serialize chain inspection/insertion atomically."""
        text = canonical(event).decode()
        with closing(self.connect()) as connection:
            connection.execute('BEGIN IMMEDIATE')
            try:
                events = self._events(connection)
                kind, identity = event.get('kind'), event.get('identity')
                if not isinstance(identity, str) or not identity:
                    raise IntegrityError('EVENT_IDENTITY_REQUIRED')
                related = [item for item in events if item.get('identity') == identity]
                if kind == 'REGISTERED':
                    if identity != require_hash(event.get('spec_hash')):
                        raise IntegrityError('REGISTRATION_IDENTITY_MISMATCH')
                    if related:
                        raise IntegrityError('SPEC_ALREADY_REGISTERED')
                elif kind == 'STARTED':
                    spec_hash = require_hash(event.get('spec_hash'))
                    if related or not any(item.get('kind') == 'REGISTERED' and
                                          item.get('spec_hash') == spec_hash for item in events):
                        raise IntegrityError('TRIAL_UNREGISTERED_OR_DUPLICATE')
                elif kind in ('SUCCEEDED', 'FAILED'):
                    if len(related) != 1 or related[0].get('kind') != 'STARTED':
                        raise IntegrityError('TRIAL_NOT_ACTIVE')
                    if event.get('spec_hash') != related[0].get('spec_hash'):
                        raise IntegrityError('TRIAL_SPEC_MISMATCH')
                    if kind == 'SUCCEEDED':
                        require_hash(event.get('result_hash'))
                        if any(item.get('kind') == 'SUCCEEDED' and
                               item.get('spec_hash') == event.get('spec_hash') and
                               item.get('result_hash') != event.get('result_hash') for item in events):
                            raise IntegrityError('REPRODUCIBILITY_MISMATCH')
                else:
                    raise IntegrityError('UNSUPPORTED_EVENT')
                row = connection.execute('SELECT event_hash FROM research_events ORDER BY sequence DESC LIMIT 1').fetchone()
                prior = row[0] if row else '0' * 64
                stored = digest((prior + '\n' + text).encode())
                connection.execute('INSERT INTO research_events VALUES (?,?,?,?)',
                                   (len(events) + 1, prior, text, stored))
                connection.commit()
            except BaseException:
                connection.rollback()
                raise


def recorded_trial(ledger: TrialLedger, spec_hash: str,
                   operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Durably record attempts before data access; never fabricate success."""
    if not any(item.get('kind') == 'REGISTERED' and item.get('spec_hash') == spec_hash
               for item in ledger.events()):
        raise IntegrityError('SPEC_NOT_REGISTERED')
    identity = uuid.uuid4().hex
    ledger.append({'kind': 'STARTED', 'identity': identity, 'spec_hash': spec_hash,
                   'at': datetime.now(timezone.utc).isoformat()})
    try:
        result = operation()
        if result.get('approval_authority') is not False or result.get('fill_evidence') is not False:
            raise IntegrityError('RESEARCH_AUTHORITY_REQUIRED')
        ledger.append({'kind': 'SUCCEEDED', 'identity': identity, 'spec_hash': spec_hash,
                       'result_hash': hash_value(result), 'at': datetime.now(timezone.utc).isoformat()})
        return result
    except BaseException:
        ledger.append({'kind': 'FAILED', 'identity': identity, 'spec_hash': spec_hash,
                       'code': 'RESEARCH_CHECK_FAILED', 'at': datetime.now(timezone.utc).isoformat()})
        raise
