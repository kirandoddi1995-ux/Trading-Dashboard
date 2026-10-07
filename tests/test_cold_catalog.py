"""Merkle cold lookup catalog: deterministic, bounded, immutable, fail closed."""
import hashlib
import json

import pytest

from cold_catalog import Catalog, CatalogError, EMPTY_ROOT, LEAF_KEYS, PAGE_BYTES, identity


def apply(patch, store):
    for digest, data in patch.pages.items():
        assert hashlib.sha256(data).hexdigest() == digest
        assert len(data) <= PAGE_BYTES
    store.update(patch.pages)
    return Catalog(patch.root, store.get)


def test_empty_genesis_is_explicit_not_missing_history():
    catalog = Catalog(EMPTY_ROOT, lambda _key: None)
    assert catalog.lookup("idem:absent") is None
    assert catalog.audit() == 0
    with pytest.raises(CatalogError, match="PAGE_MISSING"):
        Catalog("a"*64, lambda _key: None).lookup("idem:absent")


def test_split_large_catalog_and_restore_all_identities():
    store = {}
    updates = {f"idem:{i}": {"segment": f"fixture-{i}", "row": i} for i in range(700)}
    patched = Catalog(EMPTY_ROOT, store.get).patch(updates)
    catalog = apply(patched, store)
    assert catalog.audit() == 700
    for key, value in updates.items():
        assert catalog.lookup(key) == value
    assert catalog.lookup("idem:missing") is None
    # Publish final reachable pages, not 700 intermediate root rewrites.
    assert len(patched.pages) < 25


def test_entries_stream_every_authenticated_identity_in_order():
    store = {}
    values = {f'idem:{i}': {'row': i} for i in range(700)}
    catalog = apply(Catalog(EMPTY_ROOT, store.get).patch(values), store)
    entries = list(catalog.entries())
    assert entries == sorted((identity(key), value) for key, value in values.items())
    assert list(Catalog(EMPTY_ROOT, store.get).entries()) == []


def test_entry_prefix_is_not_a_successful_audit_if_later_page_missing():
    store = {}
    catalog = apply(Catalog(EMPTY_ROOT, store.get).patch(
        {f'idem:{i}': {'row': i} for i in range(300)}), store)
    root = json.loads(store[catalog.root])
    store.pop(root['right'])
    iterator = catalog.entries()
    assert next(iterator)  # Authenticated left subtree remains available.
    with pytest.raises(CatalogError, match='PAGE_MISSING'):
        list(iterator)


def test_replayed_nonempty_subtree_fails_prefix_verification():
    store = {}
    catalog = apply(Catalog(EMPTY_ROOT, store.get).patch(
        {f'idem:{i}': {'row': i} for i in range(300)}), store)
    root = json.loads(store[catalog.root])
    root['right'] = root['left']
    data = json.dumps(root, sort_keys=True, separators=(',', ':')).encode()
    digest = hashlib.sha256(data).hexdigest()
    store[digest] = data
    with pytest.raises(CatalogError, match='INVALID'):
        list(Catalog(digest, store.get).entries())


def test_old_root_survives_incremental_insert_and_frontier_replacement():
    store = {}
    first = apply(Catalog(EMPTY_ROOT, store.get).patch({"aggregate:one": {"sequence": 2}}), store)
    second_patch = first.patch({"idem:second": {"event": "original"}})
    second = apply(second_patch, store)
    assert first.lookup("idem:second") is None
    assert second.lookup("aggregate:one") == {"sequence": 2}
    with pytest.raises(CatalogError, match="IDENTITY_CONFLICT"):
        second.patch({"aggregate:one": {"sequence": 3}})
    third = apply(second.patch({"aggregate:one": {"sequence": 3}}, replace=True), store)
    assert second.lookup("aggregate:one") == {"sequence": 2}
    assert third.lookup("aggregate:one") == {"sequence": 3}


def test_same_content_is_noop_and_input_mutation_does_not_change_page():
    store = {}
    value = {"nested": {"original": 1}}
    patch = Catalog(EMPTY_ROOT, store.get).patch({"idem:one": value})
    catalog = apply(patch, store)
    value["nested"]["original"] = 2
    assert catalog.lookup("idem:one") == {"nested": {"original": 1}}
    repeated = catalog.patch({"idem:one": {"nested": {"original": 1}}})
    assert repeated.root == catalog.root and not repeated.pages


def test_build_order_deterministic():
    values = {f"idem:{i}": {"original": i} for i in range(300)}
    catalog = Catalog(EMPTY_ROOT, lambda _key: None)
    assert catalog.patch(values) == catalog.patch(dict(reversed(list(values.items()))))


def test_missing_or_corrupt_page_is_not_a_duplicate_absence():
    store = {}
    catalog = apply(Catalog(EMPTY_ROOT, store.get).patch(
        {f"idem:{i}": {"original": i} for i in range(300)}), store)
    with pytest.raises(CatalogError, match="PAGE_MISSING"):
        Catalog(catalog.root, lambda _key: None).lookup("idem:4")
    with pytest.raises(CatalogError, match="DIGEST_MISMATCH"):
        Catalog(catalog.root, lambda _key: b"corrupt").lookup("idem:4")


def test_oversized_and_invalid_input_rejected():
    catalog = Catalog(EMPTY_ROOT, lambda _key: None)
    for updates in ({}, {f"idem:{i}": {} for i in range(2001)}):
        with pytest.raises(CatalogError, match="UPDATE_COUNT"):
            catalog.patch(updates)
    with pytest.raises(CatalogError, match="VALUE_TOO_LARGE"):
        catalog.patch({"idem:one": {"large": "x"*9000}})
    with pytest.raises(CatalogError, match="NON_JSON"):
        catalog.patch({"idem:one": {"bad": float("nan")}})
    with pytest.raises(CatalogError, match="IDENTITY_INVALID"):
        identity("")


def test_large_values_split_by_bytes_before_count_limit():
    store = {}
    values = {f"idem:{i}": {"payload": "x"*7000} for i in range(LEAF_KEYS)}
    catalog = apply(Catalog(EMPTY_ROOT, store.get).patch(values), store)
    assert catalog.audit() == LEAF_KEYS
    assert all(catalog.lookup(key) == value for key, value in values.items())


def test_transport_types_and_non_json_nested_keys_fail_closed():
    with pytest.raises(CatalogError, match="DIGEST_MISMATCH"):
        Catalog("a"*64, lambda _key: "wrong-type").lookup("idem:one")
    with pytest.raises(CatalogError, match="NON_JSON_VALUE"):
        Catalog(EMPTY_ROOT, lambda _key: None).patch({"idem:one": {"nested": {1: "changed-key"}}})
    with pytest.raises(CatalogError, match="IDENTITY_INVALID"):
        Catalog(EMPTY_ROOT, lambda _key: None).patch({1: {}})


@pytest.mark.parametrize("node,code", [
    ({"format": "wrong", "kind": "leaf", "entries": {}}, "PAGE_INVALID"),
    ({"format": "cold-catalog-v1", "kind": "leaf", "entries": {"invalid": {}}}, "LEAF_INVALID"),
    ({"format": "cold-catalog-v1", "kind": "branch", "prefix": "x",
      "left": "a"*64, "right": "b"*64}, "BRANCH_INVALID"),
])
def test_even_pinned_pages_must_have_valid_schema(node, code):
    data = json.dumps(node, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    root = hashlib.sha256(data).hexdigest()
    with pytest.raises(CatalogError, match=code):
        Catalog(root, lambda _key: data).lookup("idem:one")

