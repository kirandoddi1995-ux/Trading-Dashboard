"""Offline SQLite generations and separate local checkpoints, not commissioning.

No CLI, network, runtime imports, encryption, live restore or source deletion.
Caller owns private directories, ACLs, original keys and independent replicas.
Local SQLite commit is not proof of independent-device or power-loss recovery.
"""
from __future__ import annotations

from collections.abc import Mapping
from contextlib import closing
from dataclasses import asdict, dataclass, field
import datetime as dt
import json
import os
from pathlib import Path
import re
import sqlite3
import time

import catalog_receipts as receipts
import local_state_recovery as state
import recovery_bundle as bundle

MAX_EXPORT_SECONDS = 30.0
SQLITE_TIMEOUT = 2.0
PAGE_BATCH = 128
MAX_CUSTODY_BYTES = 64 * 1024
IMAGE = 'primary.sqlite'
MANIFEST = 'bundle.json'
CUSTODY_SCHEMA = ('CREATE TABLE custody(singleton INTEGER PRIMARY KEY CHECK(singleton=1),'
                  'contract TEXT NOT NULL,generation INTEGER NOT NULL,'
                  'root TEXT NOT NULL,receipt_sha TEXT NOT NULL)')


class ExportError(ValueError):
    """Stable failures; partial generations remain for private inspection."""


@dataclass(frozen=True)
class PreparedGeneration:
    """Local files only; proposed checkpoint has not been committed."""
    directory: Path = field(repr=False)
    signed: bundle.SignedBundle


def _contract(contract: bundle.BackupContract) -> str:
    """Only one SQLite source is supported; never imply a cross-file freeze."""
    bundle.genesis(contract)  # Public validation; not a lost-checkpoint fallback.
    if (len(contract.bindings) != 1 or contract.bindings[0].name != 'primary_state'
            or contract.bindings[0].format != 'sqlite-image-v1'):
        raise ExportError('EXPORT_CROSS_FILE_ADAPTER_REQUIRED')
    return json.dumps(asdict(contract), sort_keys=True, separators=(',', ':'))


def _readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True,
                           timeout=SQLITE_TIMEOUT)


def _file(path: Path) -> Path:
    """Refuse links/directories; parent custody/TOCTOU protection is caller-owned."""
    if path.is_symlink() or path.is_junction() or not path.is_file():
        raise ExportError('EXPORT_REGULAR_FILE_REQUIRED')
    return path.resolve(strict=True)


def _directory(path: Path) -> Path:
    if path.is_symlink() or path.is_junction() or not path.is_dir():
        raise ExportError('EXPORT_PRIVATE_DIRECTORY_REQUIRED')
    return path.resolve(strict=True)


def _sync(path: Path) -> None:
    with path.open('r+b') as stream:
        os.fsync(stream.fileno())


def _write_new(path: Path, data: bytes) -> None:
    with path.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _integrity(path: Path) -> None:
    """Bounded full-image SQLite check, not just the five-table state witness."""
    if not 0 < path.stat().st_size <= bundle.MAX_ARTIFACT_BYTES:
        raise ExportError('EXPORT_SIZE_BOUND')
    deadline = time.monotonic() + MAX_EXPORT_SECONDS
    # SQLite 3.51 skips CHECK validation for mode=ro. Only the exported image
    # gets a mode=rw handle with query_only; the original source stays mode=ro.
    with closing(_readonly(path)) as check:
        if check.execute('PRAGMA journal_mode').fetchone() != ('delete',):
            raise ExportError('EXPORT_IMAGE_JOURNAL_UNVERIFIED')
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=rw', uri=True,
                                timeout=SQLITE_TIMEOUT)) as conn:
        conn.execute('PRAGMA query_only=ON')
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
        if conn.execute('PRAGMA integrity_check(1)').fetchone() != ('ok',):
            raise ExportError('EXPORT_IMAGE_INTEGRITY_UNVERIFIED')


def prepare(source: Path, directory: Path, *, contract: bundle.BackupContract,
            previous: receipts.RootAnchor, original_keys: Mapping[str, bytes],
            key_id: str, key: bytes, bundle_id: str, cut_id: str,
            at: dt.datetime) -> PreparedGeneration:
    """Export one source read transaction to a NEW private generation directory.

    Witness is computed from the exported source snapshot, before any restore.
    No side-file or WAL copying. Source may have WAL writers; read snapshot stays
    pinned. All partial files are retained on failure, never reused/overwritten.
    Deadline is checked between backup steps; driver I/O must remain bounded.
    """
    try:
        _contract(contract)
        source = _file(source)
        parent = _directory(directory.parent)
        if directory.name in ('', '.', '..') or directory.is_symlink():
            raise ExportError('EXPORT_NEW_GENERATION_REQUIRED')
        directory = parent / directory.name
        if directory.exists():
            raise ExportError('EXPORT_NEW_GENERATION_REQUIRED')
        if source.is_relative_to(directory):
            raise ExportError('EXPORT_SOURCE_OVERLAP')
        directory.mkdir()  # Exclusive; another process cannot share a generation.
        image = directory / IMAGE
        _write_new(image, b'')
        deadline = time.monotonic() + MAX_EXPORT_SECONDS
        with closing(_readonly(source)) as before, closing(sqlite3.connect(image)) as after:
            before.execute('PRAGMA query_only=ON')
            before.execute('BEGIN')
            page_size = int(before.execute('PRAGMA page_size').fetchone()[0])
            pages = int(before.execute('PRAGMA page_count').fetchone()[0])
            if not 0 < pages * page_size <= bundle.MAX_ARTIFACT_BYTES:
                raise ExportError('EXPORT_SIZE_BOUND')
            # page_count establishes the source transaction's snapshot.
            def progress(status: int, remaining: int, total: int) -> None:
                if time.monotonic() > deadline:
                    raise ExportError('EXPORT_TIME_BOUND')
                if total * page_size > bundle.MAX_ARTIFACT_BYTES:
                    raise ExportError('EXPORT_SIZE_BOUND')
                if status not in (sqlite3.SQLITE_OK, sqlite3.SQLITE_DONE):
                    raise ExportError('EXPORT_BACKUP_BLOCKED')
            before.backup(after, pages=PAGE_BATCH, progress=progress, sleep=0.0)
            before.rollback()
            after.execute('PRAGMA journal_mode=DELETE')
        _sync(image)
        _integrity(image)
        with state.capture(lambda: _readonly(image), original_keys,
                           spool_parent=directory) as snapshot:
            witness = snapshot.witness
        with image.open('rb') as stream:
            identity = bundle.measure('primary_state', stream)
        signed = bundle.seal(contract, witness, (identity,), previous=previous,
            key_id=key_id, key=key, bundle_id=bundle_id, cut_id=cut_id, at=at)
        _write_new(directory / MANIFEST, signed.data)
        # Do not claim directory-entry flush or second-copy durability on Windows.
        return PreparedGeneration(directory, signed)
    except ExportError:
        raise
    except Exception:
        raise ExportError('EXPORT_STOP_INSPECT_PARTIAL_GENERATION') from None


def verify_generation(directory: Path, *, checkpoint: bundle.BundleCheckpoint,
                      contract: bundle.BackupContract, keys: Mapping[str, bytes],
                      original_keys: Mapping[str, bytes], spool_parent: Path) -> bytes:
    """Authenticate bytes AND original signed state before any checkpoint advance.

    Caller must prevent mutation of generation files during verification/custody.
    Independent copies, cross-file consistency and remote ACKs are not verified.
    """
    try:
        _contract(contract)
        directory = _directory(directory)
        if {p.name for p in directory.iterdir()} != {IMAGE, MANIFEST}:
            raise ExportError('EXPORT_INCOMPLETE_GENERATION')
        image = _file(directory / IMAGE)
        manifest = _file(directory / MANIFEST)
        with manifest.open('rb') as stream:
            data = stream.read(bundle.MAX_MANIFEST_BYTES + 1)
        bundle.verify(data, checkpoint=checkpoint, contract=contract, keyring=keys)
        _integrity(image)
        with image.open('rb') as stream:
            identity = bundle.measure('primary_state', stream)
        with state.capture(lambda: _readonly(image), original_keys,
                           spool_parent=spool_parent) as snapshot:
            witness = snapshot.witness
        with image.open('rb') as stream:
            if identity != bundle.measure('primary_state', stream):
                raise ExportError('EXPORT_IMAGE_CHANGED')
        bundle.verify_restore(data, checkpoint=checkpoint, contract=contract,
                              keyring=keys, observed=(identity,), restored_witness=witness)
        return data
    except ExportError:
        raise
    except Exception:
        raise ExportError('EXPORT_GENERATION_UNVERIFIED') from None


def create_custody(path: Path, *, contract: bundle.BackupContract) -> None:
    """Explicit NEW local checkpoint store; never called by read/commit fallback.

    Owner must retain this outside the backup generations with protected ACLs.
    This is metadata custody only, not encrypted media or independent-device proof.
    """
    try:
        reviewed = _contract(contract)
        _directory(path.parent)
        anchor = bundle.genesis(contract)
        _write_new(path, b'')
        with closing(sqlite3.connect(path, timeout=SQLITE_TIMEOUT)) as conn:
            conn.execute('PRAGMA journal_mode=DELETE')
            conn.execute('PRAGMA synchronous=FULL')
            conn.execute(CUSTODY_SCHEMA)
            conn.execute('INSERT INTO custody VALUES(1,?,?,?,?)',
                         (reviewed, anchor.generation, anchor.root, anchor.receipt_sha256))
            conn.commit()
    except Exception:
        raise ExportError('CUSTODY_BOOTSTRAP_FAILED_DO_NOT_RECREATE') from None


def _head(conn: sqlite3.Connection, contract: bundle.BackupContract) -> receipts.RootAnchor:
    objects = conn.execute('SELECT type,name,sql FROM sqlite_master LIMIT 2').fetchall()
    if objects != [('table', 'custody', CUSTODY_SCHEMA)]:
        raise ExportError('CUSTODY_SCHEMA_UNVERIFIED')
    rows = conn.execute('SELECT singleton,contract,generation,root,receipt_sha FROM custody LIMIT 2').fetchall()
    if len(rows) != 1 or rows[0][0] != 1 or rows[0][1] != _contract(contract):
        raise ExportError('CUSTODY_CONTRACT_UNVERIFIED')
    _, _, generation, root, receipt_sha = rows[0]
    if (type(generation) is not int or not 0 <= generation <= receipts.MAX_GENERATION
            or not isinstance(root, str) or not re.fullmatch('[0-9a-f]{64}', root)
            or not isinstance(receipt_sha, str) or not re.fullmatch('[0-9a-f]{64}', receipt_sha)):
        raise ExportError('CUSTODY_HEAD_INVALID')
    anchor = receipts.RootAnchor(contract.scope, generation, root, receipt_sha)
    if generation == 0 and anchor != bundle.genesis(contract):
        raise ExportError('CUSTODY_HEAD_INVALID')
    if generation > 0 and receipt_sha == bundle.genesis(contract).receipt_sha256:
        raise ExportError('CUSTODY_HEAD_INVALID')
    return anchor


def _custody_file(path: Path) -> Path:
    path = _file(path)
    if not 0 < path.stat().st_size <= MAX_CUSTODY_BYTES:
        raise ExportError('CUSTODY_SIZE_BOUND')
    return path


def read_head(path: Path, *, contract: bundle.BackupContract) -> receipts.RootAnchor:
    """Read only; missing/corrupt stores never silently bootstrap or reset."""
    try:
        with closing(_readonly(_custody_file(path))) as conn:
            return _head(conn, contract)
    except ExportError:
        raise
    except Exception:
        raise ExportError('CUSTODY_UNAVAILABLE_NO_BOOTSTRAP') from None


def commit(path: Path, generation: PreparedGeneration, *, contract: bundle.BackupContract,
           keys: Mapping[str, bytes], original_keys: Mapping[str, bytes],
           spool_parent: Path) -> dict[str, object]:
    """CAS local checkpoint only after exported generation readback succeeds.

    Exact retry verifies files again. Commit errors are ambiguous: privately read
    the store before retry; never reset or infer rollback. No hot-deletion authority.
    Hardware fsync honesty and externally preserved head remain owner obligations.
    """
    try:
        path = _custody_file(path)
        directory = _directory(generation.directory)
        if path.is_relative_to(directory):
            raise ExportError('CUSTODY_NOT_SEPARATE')
        data = verify_generation(directory, checkpoint=generation.signed.checkpoint,
            contract=contract, keys=keys, original_keys=original_keys, spool_parent=spool_parent)
        if data != generation.signed.data:
            raise ExportError('CUSTODY_GENERATION_MISMATCH')
        with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True,
                                    timeout=SQLITE_TIMEOUT)) as conn:
            if conn.execute('PRAGMA journal_mode').fetchone()[0] != 'delete':
                raise ExportError('CUSTODY_JOURNAL_UNVERIFIED')
            conn.execute('PRAGMA synchronous=FULL')
            conn.execute('BEGIN IMMEDIATE')
            head = _head(conn, contract)
            checkpoint = generation.signed.checkpoint
            if head == checkpoint.current:
                outcome = 'CUSTODY_EXACT_RETRY'
            elif head == checkpoint.previous:
                conn.execute('UPDATE custody SET generation=?,root=?,receipt_sha=? WHERE singleton=1',
                    (checkpoint.current.generation, checkpoint.current.root, checkpoint.current.receipt_sha256))
                outcome = 'CUSTODY_LOCAL_CHECKPOINT_COMMITTED'
            else:
                raise ExportError('CUSTODY_STALE_PREDECESSOR')
            conn.commit()
        if read_head(path, contract=contract) != checkpoint.current:
            raise ExportError('CUSTODY_READBACK_MISMATCH')
        return {'status': outcome, 'generation': checkpoint.current.generation,
                'independent_replica_verified': False, 'power_loss_recovery_verified': False,
                'application_recovery_verified': False, 'approval_authority': False}
    except ExportError:
        raise
    except Exception:
        raise ExportError('CUSTODY_COMMIT_UNCERTAIN_INSPECT_HEAD') from None
