"""Sealed-segment preparation and cold/hot ledger reads over a trusted Merkle root.

No database or Drive mutations. Publication, exact-row deletion and generation CAS
remain the archive repository's responsibility; preparing bytes is NOT permission
to delete source rows.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import re

from cold_catalog import Catalog, CatalogPatch, identity
from ledger_segments import Head, SealedSegment, restore, seal, verify_records
from evidence_ledger import GENESIS_HASH

HEX = re.compile(r"[0-9a-f]{64}")
MAX_BATCH_ROWS = 900  # 2 identities/event + bounded frontier metadata fits 2000 updates.
MAX_AGGREGATES = 32
MAX_READ_SEGMENTS = 2048


class ColdLedgerError(ValueError):
    """Stable failure category; never include payloads or signing material."""


@dataclass(frozen=True)
class PreparedArchive:
    """Verified bytes and catalog pages; commit both only after remote verification."""

    segment: SealedSegment
    catalog: CatalogPatch


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ColdLedgerError("COLD_METADATA_INVALID")
    return value


def _number(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ColdLedgerError("COLD_METADATA_INVALID")
    return value


def _hash(value: object) -> str:
    text = _text(value)
    if not HEX.fullmatch(text):
        raise ColdLedgerError("COLD_METADATA_INVALID")
    return text


def _frontier(value: Mapping[str, object]) -> tuple[Head, str]:
    if set(value) != {"sequence", "hash", "segment"}:
        raise ColdLedgerError("COLD_METADATA_INVALID")
    sequence = _number(value["sequence"])
    if sequence < 1:
        raise ColdLedgerError("COLD_METADATA_INVALID")
    return (sequence, _hash(value["hash"])), _hash(value["segment"])


def _unique_identities(rows: Sequence[Mapping[str, object]]) -> None:
    """Reject identity reuse even when every segment has a valid signature."""
    seen_events: set[str] = set()
    seen_keys: set[str] = set()
    for row in rows:
        event_id, key = _text(row.get("event_id")), _text(row.get("idempotency_key"))
        if event_id in seen_events or key in seen_keys:
            raise ColdLedgerError("COLD_DUPLICATE_EVENT_IDENTITY")
        seen_events.add(event_id)
        seen_keys.add(key)


def _boundary(catalog: Catalog, segment: str, aggregate: str) -> dict[str, object]:
    value: dict[str, object] | None = catalog.lookup(f"segment:{segment}:aggregate:{aggregate}")
    required = {"before_sequence", "before_hash", "previous_segment",
                "after_sequence", "after_hash", "count"}
    if value is None or set(value) != required:
        raise ColdLedgerError("COLD_BOUNDARY_MISSING")
    before, after = _number(value["before_sequence"]), _number(value["after_sequence"])
    count = _number(value["count"])
    if count < 1 or after != before + count:
        raise ColdLedgerError("COLD_BOUNDARY_INVALID")
    _hash(value["before_hash"])
    _hash(value["after_hash"])
    if value["previous_segment"] is None:
        if before != 0 or value["before_hash"] != GENESIS_HASH:
            raise ColdLedgerError("COLD_GENESIS_INVALID")
    else:
        _hash(value["previous_segment"])
        if before == 0:
            raise ColdLedgerError("COLD_BOUNDARY_INVALID")
    return value


def prepare(records: Sequence[Mapping[str, object]], catalog: Catalog,
            keyring: Mapping[str, bytes], seal_key: bytes) -> PreparedArchive:
    """Prepare original contiguous prefixes with bounded cold identity indexing."""
    if not 1 <= len(records) <= MAX_BATCH_ROWS:
        raise ColdLedgerError("COLD_BATCH_LIMIT")
    _unique_identities(records)
    aggregates = sorted({_text(row.get("aggregate_id")) for row in records})
    if len(aggregates) > MAX_AGGREGATES:
        raise ColdLedgerError("COLD_AGGREGATE_LIMIT")
    predecessors: dict[str, Head] = {}
    previous_segments: dict[str, str | None] = {}
    for aggregate in aggregates:
        existing = catalog.lookup(f"aggregate:{aggregate}")
        if existing is None:
            predecessors[aggregate] = (0, GENESIS_HASH)
            previous_segments[aggregate] = None
        else:
            predecessors[aggregate], previous_segments[aggregate] = _frontier(existing)
    for row in records:
        key = _text(row.get("idempotency_key"))
        if catalog.lookup(f"idem:{key}") is not None:
            raise ColdLedgerError("COLD_IDENTITY_ALREADY_COMMITTED")
        if catalog.lookup(f"event:{_text(row.get('event_id'))}") is not None:
            raise ColdLedgerError("COLD_EVENT_ID_ALREADY_COMMITTED")
    segment = seal(records, predecessors, keyring, seal_key)
    counts = Counter(_text(row["aggregate_id"]) for row in records)
    updates: dict[str, Mapping[str, object]] = {
        f"segment:{segment.sha256}": {"aggregates": aggregates, "rows": len(records)}}
    for aggregate in aggregates:
        before = predecessors[aggregate]
        after = segment.heads[aggregate]
        updates[f"aggregate:{aggregate}"] = {
            "sequence": after[0], "hash": after[1], "segment": segment.sha256}
        updates[f"segment:{segment.sha256}:aggregate:{aggregate}"] = {
            "before_sequence": before[0], "before_hash": before[1],
            "previous_segment": previous_segments[aggregate],
            "after_sequence": after[0], "after_hash": after[1], "count": counts[aggregate]}
    for row in records:
        locator = {
            "aggregate": _text(row["aggregate_id"]), "sequence": row["sequence_no"],
            "event_id": _text(row["event_id"]), "hash": row["event_hash"],
            "segment": segment.sha256}
        updates[f"idem:{_text(row['idempotency_key'])}"] = locator
        updates[f"event:{_text(row['event_id'])}"] = locator
    return PreparedArchive(segment, catalog.patch(updates, replace=True))


class ColdLedger:
    """Read authenticated cold rows and merge with independently pinned hot heads."""

    def __init__(self, catalog: Catalog, fetch_segment: Callable[[str], bytes | None],
                 keyring: Mapping[str, bytes], seal_key: bytes):
        self.catalog = catalog
        self.fetch_segment = fetch_segment
        self.keyring = keyring
        self.seal_key = seal_key

    def frontier(self, aggregate: str) -> Head:
        """Return a verified catalog frontier, never a hot terminal substitute."""
        value = self.catalog.lookup(f"aggregate:{aggregate}")
        return (0, GENESIS_HASH) if value is None else _frontier(value)[0]

    def aggregates(self) -> list[str]:
        """Discover every cold aggregate from authenticated global event locators.

        Frontier hashes must match exactly: an orphan frontier cannot silently
        disappear from a global audit. Raw catalog names are deliberately hashed;
        event locators supply the original aggregate labels without guessing.
        Missing later pages abort the whole enumeration, not a successful prefix.
        """
        counts: Counter[str] = Counter()
        frontiers: dict[str, int] = {}
        for hashed, value in self.catalog.entries():
            if set(value) == {'sequence', 'hash', 'segment'}:
                frontiers[hashed] = _frontier(value)[0][0]
            elif set(value) == {'aggregate', 'sequence', 'event_id', 'hash', 'segment'}:
                aggregate = _text(value['aggregate'])
                event_id = _text(value['event_id'])
                if _number(value['sequence']) < 1:
                    raise ColdLedgerError('COLD_METADATA_INVALID')
                _hash(value['hash'])
                _hash(value['segment'])
                if hashed == identity('event:'+event_id):
                    counts[aggregate] += 1
        if frontiers != {identity('aggregate:'+name): count for name, count in counts.items()}:
            raise ColdLedgerError('COLD_AGGREGATE_DIRECTORY_INCOMPLETE')
        return sorted(counts)

    def segment_records(self, segment: str) -> list[dict[str, object]]:
        """Restore one complete signed segment using catalog-pinned boundaries."""
        metadata = self.catalog.lookup(f"segment:{segment}")
        if metadata is None or set(metadata) != {"aggregates", "rows"}:
            raise ColdLedgerError("COLD_SEGMENT_METADATA_MISSING")
        aggregates = metadata["aggregates"]
        if (not isinstance(aggregates, list) or not 1 <= len(aggregates) <= MAX_AGGREGATES
                or any(not isinstance(item, str) or not item for item in aggregates)
                or len(set(aggregates)) != len(aggregates)):
            raise ColdLedgerError("COLD_METADATA_INVALID")
        count = _number(metadata["rows"])
        if not 1 <= count <= MAX_BATCH_ROWS:
            raise ColdLedgerError("COLD_METADATA_INVALID")
        predecessors: dict[str, Head] = {}
        boundaries: dict[str, dict[str, object]] = {}
        for aggregate in aggregates:
            boundary = _boundary(self.catalog, segment, aggregate)
            boundaries[aggregate] = boundary
            predecessors[aggregate] = (_number(boundary["before_sequence"]),
                                       _hash(boundary["before_hash"]))
        data = self.fetch_segment(segment)
        if data is None:
            raise ColdLedgerError("COLD_SEGMENT_UNAVAILABLE")
        restored: tuple[list[dict[str, object]], dict[str, Head]] = restore(
            data, segment, predecessors, self.keyring, self.seal_key)
        records, heads = restored
        actual_counts = Counter(_text(row["aggregate_id"]) for row in records)
        if len(records) != count or set(actual_counts) != set(aggregates):
            raise ColdLedgerError("COLD_SEGMENT_COUNT_MISMATCH")
        for aggregate, boundary in boundaries.items():
            if (actual_counts[aggregate] != boundary["count"]
                    or heads[aggregate] != (boundary["after_sequence"], boundary["after_hash"])):
                raise ColdLedgerError("COLD_SEGMENT_COUNT_MISMATCH")
        return records

    def events(self, aggregate: str) -> list[dict[str, object]]:
        """Recover complete cold prefix; unavailability never silently shortens it."""
        value = self.catalog.lookup(f"aggregate:{aggregate}")
        if value is None:
            return []
        expected, segment = _frontier(value)
        chunks: list[list[dict[str, object]]] = []
        seen: set[str] = set()
        for _ in range(MAX_READ_SEGMENTS):
            if segment in seen:
                raise ColdLedgerError("COLD_SEGMENT_REPLAY")
            seen.add(segment)
            boundary = _boundary(self.catalog, segment, aggregate)
            if expected != (boundary["after_sequence"], boundary["after_hash"]):
                raise ColdLedgerError("COLD_FRONTIER_MISMATCH")
            rows = [row for row in self.segment_records(segment) if row["aggregate_id"] == aggregate]
            chunks.append(rows)
            if boundary["previous_segment"] is None:
                result = [row for chunk in reversed(chunks) for row in chunk]
                _unique_identities(result)
                return result
            expected = (_number(boundary["before_sequence"]), _hash(boundary["before_hash"]))
            segment = _hash(boundary["previous_segment"])
        raise ColdLedgerError("COLD_READ_LIMIT_REQUIRES_PAGINATION")

    def duplicate(self, key: str) -> dict[str, object] | None:
        """Restore original event for cold at-least-once retry identity checking."""
        value = self.catalog.lookup(f"idem:{key}")
        if value is None:
            return None
        if set(value) != {"aggregate", "sequence", "event_id", "hash", "segment"}:
            raise ColdLedgerError("COLD_METADATA_INVALID")
        records = self.segment_records(_hash(value["segment"]))
        matches = [row for row in records if row["idempotency_key"] == key]
        if (len(matches) != 1 or matches[0]["aggregate_id"] != value["aggregate"]
                or matches[0]["sequence_no"] != value["sequence"]
                or matches[0]["event_id"] != value["event_id"]
                or matches[0]["event_hash"] != value["hash"]):
            raise ColdLedgerError("COLD_IDEMPOTENCY_MISMATCH")
        return matches[0]

    def merged(self, aggregate: str, hot: Sequence[Mapping[str, object]],
               expected_head: Head) -> list[Mapping[str, object]]:
        """Validate cold prefix + hot tail against a separately committed terminal head."""
        rows: list[Mapping[str, object]] = [*self.events(aggregate), *hot]
        if any(row.get("aggregate_id") != aggregate for row in rows):
            raise ColdLedgerError("COLD_AGGREGATE_MISMATCH")
        heads: dict[str, Head] = {}
        _unique_identities(rows)
        for start in range(0, len(rows), 2000):
            heads = verify_records(rows[start:start + 2000], heads, self.keyring)
        sequence, digest = expected_head
        _number(sequence)
        _hash(digest)
        if sequence == 0 and digest != GENESIS_HASH:
            raise ColdLedgerError("COLD_TERMINAL_HEAD_MISMATCH")
        terminal = heads.get(aggregate, (0, GENESIS_HASH))
        if terminal != expected_head:
            raise ColdLedgerError("COLD_TERMINAL_HEAD_MISMATCH")
        return rows

