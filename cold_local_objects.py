"""Explicit private, create-only cold-object staging; no hosted transport.

Owner provisions the parent on protected storage. Distinct directories are not
independent replicas, and this adapter does not encrypt files or authorise pruning.
Partial objects are retained on failure and must never be overwritten on retry.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re

from catalog_receipts import MAX_BYTES as MAX_RECEIPT_BYTES
from cold_catalog import PAGE_BYTES
from ledger_read_contract import Kind
from ledger_segments import MAX_FILE_BYTES

LIMITS: dict[Kind, int] = {'ledger-segment': MAX_FILE_BYTES,
                          'catalog-page': PAGE_BYTES, 'root-receipt': MAX_RECEIPT_BYTES}


class LocalObjectError(ValueError):
    """Stable, path-free staging error. Existing files remain untouched."""


class LocalObjects:
    """Injected create-only publisher/read-only reader for private local objects."""

    def __init__(self, root: Path, *, writable: bool = False):
        if type(writable) is not bool:
            raise LocalObjectError('LOCAL_OBJECT_MODE_INVALID')
        self.root = root
        self.writable = writable
        self._root()

    def _root(self) -> None:
        if not isinstance(self.root, Path):
            raise LocalObjectError('LOCAL_OBJECT_PARENT_INVALID')
        try:
            for item in (self.root, *self.root.parents):
                if item.is_symlink() or item.is_junction():
                    raise LocalObjectError('LOCAL_OBJECT_LINK_REJECTED')
            if not self.root.is_dir():
                raise LocalObjectError('LOCAL_OBJECT_PARENT_INVALID')
        except LocalObjectError:
            raise
        except Exception:
            raise LocalObjectError('LOCAL_OBJECT_PARENT_UNAVAILABLE') from None

    def _path(self, kind: Kind, digest: str) -> Path:
        self._root()
        if kind not in LIMITS or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
            raise LocalObjectError('LOCAL_OBJECT_IDENTITY_INVALID')
        path = self.root / f'{kind}-{digest}'
        if path.is_symlink() or path.is_junction():
            raise LocalObjectError('LOCAL_OBJECT_LINK_REJECTED')
        return path

    def get(self, kind: Kind, digest: str) -> bytes | None:
        """Read actual bounded bytes; absence is distinct from damaged content."""
        path = self._path(kind, digest)
        try:
            with path.open('rb') as handle:
                stat = os.fstat(handle.fileno())
                if stat.st_nlink != 1:
                    raise LocalObjectError('LOCAL_OBJECT_LINK_REJECTED')
                if not 1 <= stat.st_size <= LIMITS[kind]:
                    raise LocalObjectError('LOCAL_OBJECT_SIZE_INVALID')
                data = handle.read(LIMITS[kind] + 1)
            if len(data) != stat.st_size or hashlib.sha256(data).hexdigest() != digest:
                raise LocalObjectError('LOCAL_OBJECT_DIGEST_MISMATCH')
            return data
        except FileNotFoundError:
            return None
        except LocalObjectError:
            raise
        except Exception:
            raise LocalObjectError('LOCAL_OBJECT_READ_BLOCKED') from None

    def put(self, kind: Kind, digest: str, data: bytes) -> None:
        """Create and fsync exact bytes, or verify an exact idempotent retry.

        Publication adapters must still read back the complete signed root and
        all original events. Directory durability/power-loss custody is not proved.
        Caller must prevent directory replacement/concurrent mutation with ACLs;
        ancestor checks alone do not eliminate filesystem TOCTOU races.
        """
        if not self.writable:
            raise LocalObjectError('LOCAL_OBJECT_WRITES_DISABLED')
        path = self._path(kind, digest)
        if (not isinstance(data, bytes) or not 1 <= len(data) <= LIMITS[kind]
                or hashlib.sha256(data).hexdigest() != digest):
            raise LocalObjectError('LOCAL_OBJECT_INPUT_INVALID')
        try:
            with path.open('xb') as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            pass  # Existing partial/corrupt objects MUST block, not be repaired.
        except Exception:
            raise LocalObjectError('LOCAL_OBJECT_WRITE_UNCERTAIN_RETAIN_FILE') from None
        if self.get(kind, digest) != data:
            raise LocalObjectError('LOCAL_OBJECT_READBACK_MISMATCH')
        try:
            # Exact retry may follow a lost fsync response. Repeat persistence
            # without rewriting bytes; Windows needs a writable handle for fsync.
            with path.open('r+b') as handle:
                if os.fstat(handle.fileno()).st_nlink != 1:
                    raise LocalObjectError('LOCAL_OBJECT_LINK_REJECTED')
                os.fsync(handle.fileno())
        except LocalObjectError:
            raise
        except Exception:
            raise LocalObjectError('LOCAL_OBJECT_WRITE_UNCERTAIN_RETAIN_FILE') from None
