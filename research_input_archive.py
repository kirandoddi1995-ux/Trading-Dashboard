"""Bounded private content-addressed inputs. No Drive, DB or network operations."""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any
import zlib

from automated_development_checks import write_once
from research_integrity import IntegrityError, MAX_INPUT_BYTES, digest, require_hash

MAX_COMPRESSED_BYTES = 32 * 1024 * 1024
MAX_ENVELOPE_BYTES = 45 * 1024 * 1024


class InputArchive:
    """Compressed immutable-by-API blobs addressed by exact uncompressed SHA.

    Identical bytes are deduplicated; stored objects are verified on retry/read.
    A malicious file owner remains outside this integrity model. Back up privately.
    No expiry/deletion mechanism exists. Host filesystem persistence is NOT assumed.
    """

    def __init__(self, root: Path) -> None:
        if root.resolve().is_relative_to(Path(__file__).resolve().parent):
            raise IntegrityError('PRIVATE_ARCHIVE_OUTSIDE_REPOSITORY_REQUIRED')
        if root.is_symlink():
            raise IntegrityError('ARCHIVE_SYMLINK_FORBIDDEN')
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, sha: str) -> bytes:
        """Bound encoded and expanded bytes, verify exact hash and stream ending."""
        require_hash(sha)
        path = self.root / (sha + '.json')
        if path.is_symlink():
            raise IntegrityError('ARCHIVE_SYMLINK_FORBIDDEN')
        with path.open('rb') as stream:
            encoded = stream.read(MAX_ENVELOPE_BYTES + 1)
        if len(encoded) > MAX_ENVELOPE_BYTES:
            raise IntegrityError('ARCHIVE_ENVELOPE_TOO_LARGE')
        try:
            record = json.loads(encoded)
            if (not isinstance(record, dict) or set(record) != {'version', 'sha256', 'size', 'payload'}
                    or record['version'] != 'private-input-v1' or record['sha256'] != sha
                    or type(record['size']) is not int or not 0 <= record['size'] <= MAX_INPUT_BYTES):
                raise IntegrityError('ARCHIVE_SCHEMA_INVALID')
            compressed = base64.b64decode(record['payload'], validate=True)
            if len(compressed) > MAX_COMPRESSED_BYTES:
                raise IntegrityError('ARCHIVE_COMPRESSED_TOO_LARGE')
            decoder = zlib.decompressobj()
            raw = decoder.decompress(compressed, MAX_INPUT_BYTES + 1)
            if (len(raw) > MAX_INPUT_BYTES or not decoder.eof or decoder.unused_data
                    or decoder.unconsumed_tail or len(raw) != record['size'] or digest(raw) != sha):
                raise IntegrityError('ARCHIVE_CONTENT_INVALID')
            return raw
        except (ValueError, TypeError, zlib.error):
            raise IntegrityError('ARCHIVE_CONTENT_INVALID') from None

    def put(self, raw: bytes) -> dict[str, Any]:
        """Durably publish exact input bytes before returning their reference."""
        if len(raw) > MAX_INPUT_BYTES:
            raise IntegrityError('ARCHIVE_INPUT_TOO_LARGE')
        compressed = zlib.compress(raw, level=9)
        if len(compressed) > MAX_COMPRESSED_BYTES:
            raise IntegrityError('ARCHIVE_COMPRESSED_TOO_LARGE')
        sha = digest(raw)
        record = {'version': 'private-input-v1', 'sha256': sha, 'size': len(raw),
                  'payload': base64.b64encode(compressed).decode('ascii')}
        try:
            write_once(self.root / (sha + '.json'), record)
        except FileExistsError:
            if self.get(sha) != raw:
                raise IntegrityError('ARCHIVE_CONFLICT') from None
        if self.get(sha) != raw:
            raise IntegrityError('ARCHIVE_ACKNOWLEDGMENT_FAILED')
        return {'sha256': sha, 'size': len(raw), 'compressed_size': len(compressed)}
