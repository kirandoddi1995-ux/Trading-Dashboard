"""Immutable paged Merkle lookup catalog for cold ledger identities.

Only authenticated roots are accepted by callers. This module performs no network
or hosted writes. Old roots remain readable after updates; missing pages are errors,
never proof that an idempotency key or aggregate did not previously exist.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

PAGE_BYTES = 64 * 1024
VALUE_BYTES = 8 * 1024
LEAF_KEYS = 128
MAX_UPDATES = 2000
HEX = re.compile(r"[0-9a-f]{64}")
FORMAT = "cold-catalog-v1"


class CatalogError(ValueError):
    """Stable, data-free failure code."""


def _encode(node: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(node, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False).encode()
    except (TypeError, ValueError):
        raise CatalogError("CATALOG_NON_JSON_VALUE") from None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def identity(key: str) -> str:
    """Hash explicit namespaced identity; raw broker/user identifiers stay private."""
    if not isinstance(key, str) or not key or len(key.encode()) > 1024:
        raise CatalogError("CATALOG_IDENTITY_INVALID")
    return _sha(("cold-catalog-v1:" + key).encode())


def _bits(key: str) -> str:
    return format(int(key, 16), "0256b")


def _leaf(entries: Mapping[str, object]) -> dict[str, object]:
    return {"format": FORMAT, "kind": "leaf", "entries": dict(entries)}


EMPTY_DATA = _encode(_leaf({}))
EMPTY_ROOT = _sha(EMPTY_DATA)


@dataclass(frozen=True)
class CatalogPatch:
    """Publish every reachable page and verify it BEFORE committing the root."""

    root: str
    pages: Mapping[str, bytes] = field(repr=False)


class Catalog:
    """Content-addressed read-through catalog, with bounded page/node traversal."""

    def __init__(self, root: str, fetch: Callable[[str], bytes | None]):
        if not isinstance(root, str) or not HEX.fullmatch(root):
            raise CatalogError("CATALOG_ROOT_INVALID")
        self.root = root
        self.fetch = fetch

    def _read(self, digest: str, required_prefix: str,
              pages: Mapping[str, bytes]) -> dict[str, object]:
        raw = pages.get(digest)
        if raw is None:
            raw = EMPTY_DATA if digest == EMPTY_ROOT else self.fetch(digest)
        if raw is None:
            raise CatalogError("CATALOG_PAGE_MISSING")
        if not isinstance(raw, bytes) or len(raw) > PAGE_BYTES or _sha(raw) != digest:
            raise CatalogError("CATALOG_PAGE_DIGEST_MISMATCH")
        try:
            node = json.loads(raw)
        except (ValueError, UnicodeError):
            raise CatalogError("CATALOG_PAGE_INVALID") from None
        if not isinstance(node, dict) or node.get("format") != FORMAT or _encode(node) != raw:
            raise CatalogError("CATALOG_PAGE_INVALID")
        if node.get("kind") == "leaf":
            entries = node.get("entries")
            if (set(node) != {"format", "kind", "entries"} or not isinstance(entries, dict)
                    or len(entries) > LEAF_KEYS or (required_prefix and not entries)):
                raise CatalogError("CATALOG_LEAF_INVALID")
            for key, value in entries.items():
                if (not isinstance(key, str) or not HEX.fullmatch(key)
                        or not _bits(key).startswith(required_prefix)
                        or not isinstance(value, dict) or len(_encode(value)) > VALUE_BYTES):
                    raise CatalogError("CATALOG_LEAF_INVALID")
        elif node.get("kind") == "branch":
            prefix = node.get("prefix")
            if (set(node) != {"format", "kind", "prefix", "left", "right"}
                    or not isinstance(prefix, str) or len(prefix) >= 256
                    or set(prefix) - {"0", "1"} or not prefix.startswith(required_prefix)
                    or any(not isinstance(node.get(side), str)
                           or not HEX.fullmatch(node[side]) for side in ("left", "right"))):
                raise CatalogError("CATALOG_BRANCH_INVALID")
        else:
            raise CatalogError("CATALOG_PAGE_INVALID")
        return cast(dict[str, object], node)

    def lookup(self, key: str) -> dict[str, object] | None:
        """A verified absence is None; corruption/unavailability raises instead."""
        digest, required = self.root, ""
        hashed = identity(key)
        bits = _bits(hashed)
        for _ in range(257):
            node = self._read(digest, required, {})
            if node["kind"] == "leaf":
                value = cast(dict[str, dict[str, object]], node["entries"]).get(hashed)
                return dict(value) if value is not None else None
            prefix = cast(str, node["prefix"])
            if not bits.startswith(prefix):
                return None
            side = "left" if bits[len(prefix)] == "0" else "right"
            digest = cast(str, node[side])
            required = prefix + bits[len(prefix)]
        raise CatalogError("CATALOG_TRAVERSAL_LIMIT")

    def patch(self, updates: Mapping[str, Mapping[str, object]], *,
              replace: bool = False) -> CatalogPatch:
        """Copy-on-write pages; original identities are immutable unless explicit.

        Frontier replacement requires independent monotonic/generation validation
        by the ledger transaction. This method alone cannot authorize pruning.
        """
        if not 1 <= len(updates) <= MAX_UPDATES:
            raise CatalogError("CATALOG_UPDATE_COUNT_INVALID")
        if any(not isinstance(key, str) for key in updates):
            raise CatalogError("CATALOG_IDENTITY_INVALID")
        pages: dict[str, bytes] = {}

        def save(node: Mapping[str, object]) -> str:
            encoded = _encode(node)
            if len(encoded) > PAGE_BYTES:
                raise CatalogError("CATALOG_PAGE_TOO_LARGE")
            digest = _sha(encoded)
            pages[digest] = encoded
            return digest

        def build(entries: dict[str, object]) -> str:
            encoded = _encode(_leaf(entries))
            if len(entries) <= LEAF_KEYS and len(encoded) <= PAGE_BYTES:
                return save(_leaf(entries))
            ordered = sorted(entries)
            first, last = _bits(ordered[0]), _bits(ordered[-1])
            length = next((i for i in range(256) if first[i] != last[i]), 256)
            if length == 256:
                raise CatalogError("CATALOG_VALUE_TOO_LARGE")
            prefix = first[:length]
            left = {k: v for k, v in entries.items() if _bits(k)[length] == "0"}
            right = {k: v for k, v in entries.items() if _bits(k)[length] == "1"}
            return save({"format": FORMAT, "kind": "branch", "prefix": prefix,
                         "left": build(left), "right": build(right)})

        def insert(digest: str, required: str, hashed: str, value: dict[str, object]) -> str:
            node = self._read(digest, required, pages)
            if node["kind"] == "leaf":
                entries = dict(cast(dict[str, object], node["entries"]))
                if hashed in entries:
                    if entries[hashed] == value:
                        return digest
                    if not replace:
                        raise CatalogError("CATALOG_IDENTITY_CONFLICT")
                entries[hashed] = value
                return build(entries)
            prefix = cast(str, node["prefix"])
            bits = _bits(hashed)
            if not bits.startswith(prefix):
                length = next(i for i, bit in enumerate(prefix) if bits[i] != bit)
                old_side = "left" if prefix[length] == "0" else "right"
                new_side = "right" if old_side == "left" else "left"
                return save({"format": FORMAT, "kind": "branch", "prefix": prefix[:length],
                             old_side: digest, new_side: build({hashed: value})})
            side = "left" if bits[len(prefix)] == "0" else "right"
            child = insert(cast(str, node[side]), prefix + bits[len(prefix)], hashed, value)
            if child == node[side]:
                return digest
            return save({**node, side: child})

        root = self.root
        for key in sorted(updates):
            value = dict(updates[key])
            if len(_encode(value)) > VALUE_BYTES:
                raise CatalogError("CATALOG_VALUE_TOO_LARGE")
            # Round trip prevents caller mutation and rejects non-string nested keys.
            encoded = _encode(value)
            round_trip = json.loads(encoded)
            if round_trip != value:
                raise CatalogError("CATALOG_NON_JSON_VALUE")
            value = round_trip
            root = insert(root, "", identity(key), value)
        # Exclude intermediate copy-on-write pages unreachable from the final root.
        reachable: set[str] = set()
        def retain(digest: str) -> None:
            if digest not in pages or digest in reachable:
                return
            reachable.add(digest)
            node = json.loads(pages[digest])
            if node["kind"] == "branch":
                retain(node["left"])
                retain(node["right"])
        retain(root)
        return CatalogPatch(root, MappingProxyType({k: pages[k] for k in reachable}))

    def audit(self) -> int:
        """Walk every retained branch to verify full structural coverage offline."""
        return sum(1 for _ in self.entries())

    def entries(self) -> Iterator[tuple[str, dict[str, object]]]:
        """Stream authenticated entries in hashed-identity order, from this root.

        Completion means the iterator is exhausted successfully. A yielded prefix
        is NOT a successful audit: missing/corrupt later pages still raise. The
        radix prefix grows on every edge, bounding stack depth to256 and making
        cycles or replayed nonempty subtrees fail prefix validation. No global
        page/entry set or whole-catalog materialization is required.
        """
        stack = [(self.root, '')]
        while stack:
            digest, prefix = stack.pop()
            node = self._read(digest, prefix, {})
            if node['kind'] == 'leaf':
                entries = cast(dict[str, dict[str, object]], node['entries'])
                for key in sorted(entries):
                    yield key, dict(entries[key])
            else:
                branch = cast(str, node['prefix'])
                stack.append((cast(str, node['right']), branch+'1'))
                stack.append((cast(str, node['left']), branch+'0'))

