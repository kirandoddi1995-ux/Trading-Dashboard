"""Bounded native-row decoding, preserving original signing and source material."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json

from ledger_cold_store import MAX_AGGREGATES, MAX_BATCH_ROWS
from ledger_segments import FIELDS, MAX_RAW_BYTES


class SourceCaptureError(ValueError):
    """Stable source-read errors, never native row or driver diagnostic text."""


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Native JSONB has no duplicate object keys; reject ambiguity at any depth."""
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise SourceCaptureError('ARCHIVE_SOURCE_INVALID')
        result[name] = value
    return result


def _constant(_value: str) -> object:
    raise SourceCaptureError('ARCHIVE_SOURCE_INVALID')


@dataclass(frozen=True)
class SourceCapture:
    """Exact PostgreSQL to_jsonb(row)::text, retained independently from decoding."""
    row_texts: tuple[str, ...] = field(repr=False)

    def records(self) -> list[dict[str, object]]:
        """Decode bounded originals, restoring the signer's UTC timestamp spelling."""
        if (not 1 <= len(self.row_texts) <= MAX_BATCH_ROWS
                or any(not isinstance(text, str) for text in self.row_texts)
                or sum(len(text.encode('utf-8')) for text in self.row_texts) > MAX_RAW_BYTES):
            raise SourceCaptureError('ARCHIVE_SOURCE_LIMIT')
        rows: list[dict[str, object]] = []
        for text in self.row_texts:
            try:
                row = json.loads(text, object_pairs_hook=_object, parse_constant=_constant)
            except (ValueError, UnicodeError):
                raise SourceCaptureError('ARCHIVE_SOURCE_INVALID') from None
            if not isinstance(row, dict) or set(row) != set(FIELDS):
                raise SourceCaptureError('ARCHIVE_SOURCE_INVALID')
            for name in ('recorded_at', 'effective_at'):
                stamp = row[name]
                if not isinstance(stamp, str):
                    raise SourceCaptureError('ARCHIVE_SOURCE_CLOCK_INVALID')
                try:
                    parsed = datetime.fromisoformat(stamp)
                except ValueError:
                    raise SourceCaptureError('ARCHIVE_SOURCE_CLOCK_INVALID') from None
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    raise SourceCaptureError('ARCHIVE_SOURCE_CLOCK_INVALID')
                row[name] = parsed.astimezone(timezone.utc).isoformat()
            rows.append(row)
        if len({str(row['aggregate_id']) for row in rows}) > MAX_AGGREGATES:
            raise SourceCaptureError('ARCHIVE_AGGREGATE_LIMIT')
        if (any(not isinstance(row['event_id'], str) for row in rows)
                or len({row['event_id'] for row in rows}) != len(rows)):
            raise SourceCaptureError('ARCHIVE_SOURCE_IDENTITY_INVALID')
        return rows
