"""Cold catalog + original segments + hot tail round trips with no hosted writes."""
import datetime as dt
import hashlib
import hmac
import sqlite3
import uuid

import pytest

from cold_catalog import Catalog, CatalogError, EMPTY_ROOT
from evidence_ledger import GENESIS_HASH, ImmutableEvidenceLedger, canonical_json
from ledger_cold_store import ColdLedger, ColdLedgerError, prepare
from ledger_segments import seal

KEY = b"cold-fixture-event-key"
SEAL_KEY = b"fixture-archive-sealing-key-only!"


@pytest.fixture
def history(tmp_path, monkeypatch):
    monkeypatch.setattr("evidence_ledger._utcnow", lambda: dt.datetime(
        2026, 10, 6, microsecond=123400, tzinfo=dt.timezone.utc))
    ledger = ImmutableEvidenceLedger(sqlite3.connect, str(tmp_path / "fixture.sqlite"), KEY)
    for aggregate in ("one", "two"):
        for i in range(6):
            ledger.append(aggregate_id=aggregate, event_type="DECISION_EVALUATED",
                          payload={"original": i}, idempotency_key=f"{aggregate}-{i}")
    rows = {name: ledger.events(name) for name in ("one", "two")}
    ring = {rows["one"][0]["key_id"]: KEY}
    return rows, ring


def publish(prepared, pages, segments):
    pages.update(prepared.catalog.pages)
    segments[prepared.segment.sha256] = prepared.segment.data
    return Catalog(prepared.catalog.root, pages.get)


def test_authenticated_aggregate_enumeration_includes_cold_only_history(history):
    rows, ring = history
    pages, segments = {}, {}
    catalog = publish(prepare(rows['one'][:2]+rows['two'][:3],
                             Catalog(EMPTY_ROOT, pages.get), ring, SEAL_KEY), pages, segments)
    cold = ColdLedger(catalog, segments.get, ring, SEAL_KEY)
    assert cold.aggregates() == ['one', 'two']
    assert ColdLedger(Catalog(EMPTY_ROOT, pages.get), segments.get, ring, SEAL_KEY).aggregates() == []


def test_orphan_frontier_cannot_hide_from_global_audit(history):
    rows, ring = history
    pages, segments = {}, {}
    catalog = publish(prepare(rows['one'][:2], Catalog(EMPTY_ROOT, pages.get), ring, SEAL_KEY),
                      pages, segments)
    patch = catalog.patch({'aggregate:hidden': {'sequence': 1, 'hash': 'a'*64, 'segment': 'b'*64}})
    pages.update(patch.pages)
    with pytest.raises(ColdLedgerError, match='DIRECTORY_INCOMPLETE'):
        ColdLedger(Catalog(patch.root, pages.get), segments.get, ring, SEAL_KEY).aggregates()


def test_two_sealed_segments_recover_original_prefix_hot_tail_and_retry(history):
    rows, ring = history
    pages, segments = {}, {}
    catalog = Catalog(EMPTY_ROOT, pages.get)
    first = prepare(rows["one"][:2] + rows["two"][:3], catalog, ring, SEAL_KEY)
    catalog = publish(first, pages, segments)
    old_root = catalog.root
    second = prepare(rows["one"][2:4] + rows["two"][3:5], catalog, ring, SEAL_KEY)
    catalog = publish(second, pages, segments)
    cold = ColdLedger(catalog, segments.get, ring, SEAL_KEY)
    for aggregate, count in [("one", 4), ("two", 5)]:
        restored = cold.events(aggregate)
        assert [r["event_hash"] for r in restored] == [r["event_hash"] for r in rows[aggregate][:count]]
        expected = (6, rows[aggregate][-1]["event_hash"])
        complete = cold.merged(aggregate, rows[aggregate][count:], expected)
        assert [r["event_hash"] for r in complete] == [r["event_hash"] for r in rows[aggregate]]
    duplicate = cold.duplicate("one-0")
    assert duplicate["payload"] == rows["one"][0]["payload"]
    assert duplicate["event_hash"] == rows["one"][0]["event_hash"]
    assert cold.duplicate("absent") is None
    # Historical roots remain independently readable, not rewritten in place.
    old = ColdLedger(Catalog(old_root, pages.get), segments.get, ring, SEAL_KEY)
    assert len(old.events("one")) == 2
    with pytest.raises(ColdLedgerError, match="ALREADY_COMMITTED"):
        prepare(rows["one"][:2], catalog, ring, SEAL_KEY)


def test_missing_segment_or_page_cannot_be_treated_as_no_history(history):
    rows, ring = history
    pages, segments = {}, {}
    catalog = publish(prepare(rows["one"][:2], Catalog(EMPTY_ROOT, pages.get), ring, SEAL_KEY),
                      pages, segments)
    with pytest.raises(ColdLedgerError, match="UNAVAILABLE"):
        ColdLedger(catalog, lambda _sha: None, ring, SEAL_KEY).duplicate("one-0")
    with pytest.raises(CatalogError, match="PAGE_MISSING"):
        ColdLedger(Catalog(catalog.root, lambda _sha: None), segments.get, ring, SEAL_KEY).events("one")


def test_dropped_hot_tail_is_detected_by_independent_terminal_head(history):
    rows, ring = history
    pages, segments = {}, {}
    catalog = publish(prepare(rows["one"][:2], Catalog(EMPTY_ROOT, pages.get), ring, SEAL_KEY),
                      pages, segments)
    cold = ColdLedger(catalog, segments.get, ring, SEAL_KEY)
    with pytest.raises(ColdLedgerError, match="TERMINAL_HEAD"):
        cold.merged("one", rows["one"][2:5], (6, rows["one"][-1]["event_hash"]))
    with pytest.raises(ColdLedgerError, match="AGGREGATE_MISMATCH"):
        cold.merged("one", rows["two"][2:], (6, rows["one"][-1]["event_hash"]))


def test_generation_catalog_metadata_cannot_silently_point_to_wrong_evidence(history):
    rows, ring = history
    pages, segments = {}, {}
    catalog = publish(prepare(rows["one"][:2], Catalog(EMPTY_ROOT, pages.get), ring, SEAL_KEY),
                      pages, segments)
    # An explicitly altered root is not automatically trusted by SQL, even if
    # structurally valid; its inconsistent row facts still fail reader validation.
    patch = catalog.patch({"idem:one-0": {
        "aggregate": "one", "sequence": 99, "event_id": rows["one"][0]["event_id"],
        "hash": rows["one"][0]["event_hash"], "segment": next(iter(segments))}}, replace=True)
    pages.update(patch.pages)
    with pytest.raises(ColdLedgerError, match="IDEMPOTENCY_MISMATCH"):
        ColdLedger(Catalog(patch.root, pages.get), segments.get, ring, SEAL_KEY).duplicate("one-0")


def test_empty_and_large_batches_block():
    catalog = Catalog(EMPTY_ROOT, lambda _sha: None)
    for rows in ([], [{}]*1001):
        with pytest.raises(ColdLedgerError, match="BATCH_LIMIT"):
            prepare(rows, catalog, {}, SEAL_KEY)


def test_reader_segment_count_is_verified(history):
    rows, ring = history
    pages, segments = {}, {}
    catalog = publish(prepare(rows["one"][:2], Catalog(EMPTY_ROOT, pages.get), ring, SEAL_KEY),
                      pages, segments)
    sha = next(iter(segments))
    patch = catalog.patch({f"segment:{sha}": {"aggregates": ["one"], "rows": 1}}, replace=True)
    pages.update(patch.pages)
    with pytest.raises(ColdLedgerError, match="COUNT_MISMATCH"):
        ColdLedger(Catalog(patch.root, pages.get), segments.get, ring, SEAL_KEY).events("one")


@pytest.mark.parametrize("field", ["event_id", "idempotency_key"])
def test_reused_identity_in_same_batch_is_rejected_before_index_overwrite(history, field):
    rows, ring = history
    changed = dict(rows["one"][1], **{field: rows["one"][0][field]})
    with pytest.raises(ColdLedgerError, match="DUPLICATE_EVENT_IDENTITY"):
        prepare([rows["one"][0], changed], Catalog(EMPTY_ROOT, lambda _sha: None),
                ring, SEAL_KEY)


@pytest.mark.parametrize("field", ["event_id", "idempotency_key"])
def test_cold_only_reader_rejects_signed_identity_reuse_across_segments(history, field):
    rows, ring = history
    pages, segments = {}, {}
    first = prepare(rows["one"][:1], Catalog(EMPTY_ROOT, pages.get), ring, SEAL_KEY)
    catalog = publish(first, pages, segments)
    changed = dict(rows["one"][1], **{field: rows["one"][0][field]})
    kwargs = {k: changed[k] for k in (
        "event_id", "aggregate_id", "sequence_no", "event_type", "recorded_at",
        "effective_at", "source", "actor_id", "idempotency_key", "previous_hash",
        "hash_algorithm", "schema_version", "key_id")}
    kwargs["payload_json"] = canonical_json(changed["payload"])
    changed["event_hash"] = hmac.new(
        KEY, ImmutableEvidenceLedger._material(**kwargs).encode(), hashlib.sha256).hexdigest()
    # Bypass legitimate prepare's identity gate to model a signed but inconsistent
    # external catalog. Both event signatures and segment seals remain valid.
    second = seal([changed], {"one": (1, rows["one"][0]["event_hash"])}, ring, SEAL_KEY)
    patch = catalog.patch({
        "aggregate:one": {"sequence": 2, "hash": changed["event_hash"], "segment": second.sha256},
        f"segment:{second.sha256}": {"aggregates": ["one"], "rows": 1},
        f"segment:{second.sha256}:aggregate:one": {
            "before_sequence": 1, "before_hash": rows["one"][0]["event_hash"],
            "previous_segment": first.segment.sha256,
            "after_sequence": 2, "after_hash": changed["event_hash"], "count": 1}}, replace=True)
    pages.update(patch.pages)
    segments[second.sha256] = second.data
    with pytest.raises(ColdLedgerError, match="DUPLICATE_EVENT_IDENTITY"):
        ColdLedger(Catalog(patch.root, pages.get), segments.get, ring, SEAL_KEY).events("one")


def test_maximum_batch_fits_bounded_catalog_and_restores_every_identity(history):
    rows, ring = history
    generated, preceding = [], GENESIS_HASH
    for i in range(900):
        row = dict(rows['one'][0], sequence_no=i+1, event_id=str(uuid.UUID(int=i+1)),
                   idempotency_key=f'bounded-fixture-{i}', previous_hash=preceding)
        kwargs = {k: row[k] for k in (
            'event_id', 'aggregate_id', 'sequence_no', 'event_type', 'recorded_at',
            'effective_at', 'source', 'actor_id', 'idempotency_key', 'previous_hash',
            'hash_algorithm', 'schema_version', 'key_id')}
        kwargs['payload_json'] = canonical_json(row['payload'])
        preceding = hmac.new(KEY, ImmutableEvidenceLedger._material(**kwargs).encode(),
                             hashlib.sha256).hexdigest()
        row['event_hash'] = preceding
        generated.append(row)
    pages, segments = {}, {}
    prepared = prepare(generated, Catalog(EMPTY_ROOT, pages.get), ring, SEAL_KEY)
    catalog = publish(prepared, pages, segments)
    cold = ColdLedger(catalog, segments.get, ring, SEAL_KEY)
    assert len(cold.merged('one', [], (900, preceding))) == 900
    assert catalog.audit() == 1803  # two identities/event + frontier/boundary/segment.
    assert cold.duplicate('bounded-fixture-899')['event_hash'] == preceding
    with pytest.raises(ColdLedgerError, match='BATCH_LIMIT'):
        prepare(generated + [generated[-1]], catalog, ring, SEAL_KEY)

