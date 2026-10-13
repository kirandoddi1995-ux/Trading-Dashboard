"""Opt-in byte/journal readback; no credentials, networking or operational restore."""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Protocol

from forward_nifty_producer import ROOT
from forward_versioned_producer import MAX_BUNDLE_BYTES, verify
from research_integrity import IntegrityError, canonical, digest, hash_value


class Download(Protocol):
    """Caller supplies a read-only transport; this module never constructs one."""

    def download(self, file_id: str) -> bytes: ...


@dataclass(frozen=True)
class Generation:
    sha256: str
    recipe_sha256: str
    session_open: str
    raw_polls: int
    recorded_decisions: int
    missing_decisions: int
    expected_decisions: int
    scope: str = 'LOCAL_BYTES_REPLAYED'
    remote_custody_verified: bool = False
    independent_custody_verified: bool = False
    training_eligible: bool = False
    approval_authority: bool = False
    policy_sha256: str = ''


@dataclass(frozen=True)
class LogicalRestoration:
    """Private in-memory logical snapshot, never a producer journal or new labels."""

    generation: Generation
    original_bytes: bytes = field(repr=False)
    operational_resume_supported: bool = False
    writes: int = 0


@dataclass(frozen=True)
class SignedCustodyAudit:
    """Verified signer attestation bound to readback, not a retention guarantee."""

    generation: Generation
    report_sha256: str
    signer_public_key_sha256: str
    signed_at: str
    signature_verified: bool = True
    custody_scope: str = 'SIGNED_ATTESTATION_BOUND_TO_READBACK_NOT_INDEPENDENT_CUSTODY'


def _decode(raw: bytes) -> dict[str, Any]:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BUNDLE_BYTES:
        raise IntegrityError('OVERNIGHT_SIZE_BOUND')
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise IntegrityError('OVERNIGHT_DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    try:
        value: Any = json.loads(raw, object_pairs_hook=unique)
        if not isinstance(value, dict):
            raise ValueError
        canonical(value)  # Reject NaN/Infinity before replay.
        return value
    except (ValueError, UnicodeError):
        raise IntegrityError('OVERNIGHT_JSON_INVALID') from None


def audit_bytes(raw: bytes, *, source_root: Path = ROOT) -> Generation:
    """Replay supplied bytes against the exact installed source recipe, offline."""
    try:
        bundle = verify(_decode(raw), root=source_root)
        return Generation(digest(raw), hash_value(bundle['recipe']),
                          bundle['config']['session_open'], len(bundle['polls']),
                          bundle['recorded_decisions'], bundle['missing_decisions'],
                          bundle['expected_decisions'], policy_sha256=hash_value(bundle['recipe']['policy']))
    except Exception:
        raise IntegrityError('OVERNIGHT_BUNDLE_REPLAY_FAILED') from None


def audit_file(path: Path, *, source_root: Path = ROOT) -> Generation:
    """Explicit bounded private read; never called on import or by a scheduler."""
    # Same alias refusal as private_read, with the versioned bundle's 8 MiB cap.
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise IntegrityError('OVERNIGHT_PRIVATE_PATH_REQUIRED')
    with path.open('rb') as stream:
        raw = stream.read(MAX_BUNDLE_BYTES + 1)
    return audit_bytes(raw, source_root=source_root)


def journal_bytes(path: Path, config: dict[str, Any], frozen: dict[str, Any],
                  *, source_root: Path = ROOT) -> bytes:
    """SELECT-only snapshot, bypassing Producer's constructor and write locks."""
    if (not path.is_absolute() or not path.is_file()
            or any(p.is_symlink() or p.is_junction() for p in (path, *path.parents))
            or path.with_suffix('.producer-lock').exists()
            or any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal'))):
        raise IntegrityError('OVERNIGHT_PAUSED_PRIVATE_JOURNAL_REQUIRED')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)) as conn:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        metadata = conn.execute('SELECT recipe FROM metadata WHERE id=1').fetchall()
        guards = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        if (metadata != [(canonical(frozen).decode(),)] or guards != {
                'metadata_no_update', 'metadata_no_delete', 'polls_no_update', 'polls_no_delete'}):
            raise IntegrityError('OVERNIGHT_JOURNAL_IDENTITY_OR_GUARDS')
        # substr prevents arbitrarily large corrupt payloads being materialized.
        rows = conn.execute('SELECT slot,substr(payload,1,?),sha,length(CAST(payload AS BLOB)) '
                            'FROM polls ORDER BY slot LIMIT 76', (MAX_BUNDLE_BYTES + 1,)).fetchall()
        if len(rows) > 75:
            raise IntegrityError('OVERNIGHT_JOURNAL_SIZE_BOUND')
        polls: list[dict[str, Any]] = []
        total = 0
        for slot, payload, sha, size in rows:
            total += size
            if total > MAX_BUNDLE_BYTES or digest(payload.encode()) != sha:
                raise IntegrityError('OVERNIGHT_JOURNAL_CORRUPT')
            item = _decode(payload.encode())
            if item['source']['slot'] != slot:
                raise IntegrityError('OVERNIGHT_JOURNAL_SLOT_CONFLICT')
            polls.append(item)
    count = sum(p['decision'] is not None for p in polls)
    raw = canonical({'format': 'forward-versioned-research-bundle-v1', 'config': config,
                     'recipe': frozen, 'polls': polls, 'recorded_decisions': count,
                     'missing_decisions': 75 - count, 'expected_decisions': 75,
                     'approval_authority': False, 'fill_evidence': False, 'training_eligible': False})
    audit_bytes(raw, source_root=source_root)
    return raw


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9_-]{1,200}', value) is None:
        raise IntegrityError('OVERNIGHT_REMOTE_ID_INVALID')
    return value


def audit_remote(transport: Download, manifest_id: str, expected_sha256: str,
                 *, source_root: Path = ROOT) -> Generation:
    """Fresh injected readback of one pinned generation; no ACL/custody inference."""
    if re.fullmatch(r'[0-9a-f]{64}', expected_sha256) is None:
        raise IntegrityError('OVERNIGHT_GENERATION_PIN_REQUIRED')
    try:
        manifest = _decode(transport.download(_identifier(manifest_id)))
        required = {'format', 'status', 'sha256', 'spec_hash', 'data_file_id',
                    'recorded_decisions', 'training_eligible', 'approval_authority', 'fill_evidence'}
        if (set(manifest) != required or manifest['format'] != 'forward-versioned-manifest-v1'
                or manifest['status'] != 'REMOTE_VERIFIED' or manifest['sha256'] != expected_sha256
                or any(manifest[k] is not False for k in
                       ('training_eligible', 'approval_authority', 'fill_evidence'))):
            raise ValueError
        data_id = _identifier(manifest['data_file_id'])
        if data_id == manifest_id:
            raise ValueError
        raw = transport.download(data_id)
        result = audit_bytes(raw, source_root=source_root)
        if (result.sha256 != expected_sha256 or result.recipe_sha256 != manifest['spec_hash']
                or type(manifest['recorded_decisions']) is not int
                or result.recorded_decisions != manifest['recorded_decisions']):
            raise ValueError
        return Generation(result.sha256, result.recipe_sha256, result.session_open,
                          result.raw_polls, result.recorded_decisions, result.missing_decisions,
                          result.expected_decisions, scope='INJECTED_TRANSPORT_BYTES_REPLAYED',
                          policy_sha256=result.policy_sha256)
    except Exception:
        raise IntegrityError('OVERNIGHT_REMOTE_READBACK_FAILED') from None


def restore_logical(raw: bytes, expected_sha256: str,
                    *, source_root: Path = ROOT) -> LogicalRestoration:
    """Recover exact verified bytes privately in memory, with original flags intact."""
    generation = audit_bytes(raw, source_root=source_root)
    if generation.sha256 != expected_sha256:
        raise IntegrityError('OVERNIGHT_RESTORE_GENERATION_MISMATCH')
    return LogicalRestoration(generation, raw)


def audit_lineage(generations: tuple[bytes, ...], *, source_root: Path = ROOT) -> tuple[Generation, ...]:
    """Verify append-only generations from one session; reject forks and duplicates."""
    if not 0 < len(generations) <= 75:
        raise IntegrityError('OVERNIGHT_LINEAGE_SIZE_BOUND')
    results = []
    previous: dict[str, Any] | None = None
    for raw in generations:
        result = audit_bytes(raw, source_root=source_root)
        bundle = _decode(raw)
        if previous is not None:
            prior = previous['polls']
            current = bundle['polls']
            if (canonical(previous['recipe']) != canonical(bundle['recipe'])
                    or canonical(previous['config']) != canonical(bundle['config'])
                    or len(current) <= len(prior)
                    or canonical(current[:len(prior)]) != canonical(prior)):
                raise IntegrityError('OVERNIGHT_GENERATION_LINEAGE_CONFLICT')
        previous = bundle
        results.append(result)
    return tuple(results)


def audit_signed_remote(transport: Download, manifest_id: str, expected_sha256: str,
                        signed_report: bytes, trusted_public_key: bytes, *, checked_at: datetime,
                        source_root: Path = ROOT) -> SignedCustodyAudit:
    """Ed25519 report verification with an out-of-band trusted key and exact readback.

    Envelope: {body: {...}, signature_hex: <128 lowercase hex characters>}.
    Body pins object IDs, byte hashes, recipe/count, observation/expiry times and
    evidence hashes for ACL and retention review. No caller verification flags.
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        if (checked_at.utcoffset() is None or len(trusted_public_key) != 32
                or not 0 < len(signed_report) <= 65536):
            raise ValueError
        envelope = _decode(signed_report)
        if set(envelope) != {'body', 'signature_hex'}:
            raise ValueError
        body = envelope['body']
        signature = envelope['signature_hex']
        required = {'format', 'manifest_id', 'data_id', 'manifest_sha256', 'generation_sha256',
                    'recipe_sha256', 'recorded_decisions', 'signed_at', 'expires_at',
                    'acl_evidence_sha256', 'retention_evidence_sha256'}
        if (not isinstance(body, dict) or set(body) != required
                or body['format'] != 'overnight-capture-custody-attestation-v1'
                or not isinstance(signature, str) or re.fullmatch(r'[0-9a-f]{128}', signature) is None):
            raise ValueError
        # Authenticity is established before interpreting any claimed evidence.
        Ed25519PublicKey.from_public_bytes(trusted_public_key).verify(
            bytes.fromhex(signature), canonical(body))
        signed_at, expires = (datetime.fromisoformat(body[k]) for k in ('signed_at', 'expires_at'))
        if (signed_at.utcoffset() is None or expires.utcoffset() is None
                or not signed_at <= checked_at <= expires
                or checked_at - signed_at > timedelta(hours=24)
                or expires <= signed_at):
            raise ValueError
        for key in ('manifest_sha256', 'generation_sha256', 'recipe_sha256',
                    'acl_evidence_sha256', 'retention_evidence_sha256'):
            if not isinstance(body[key], str) or re.fullmatch(r'[0-9a-f]{64}', body[key]) is None:
                raise ValueError
        if (body['manifest_id'] != manifest_id or body['generation_sha256'] != expected_sha256
                or _identifier(body['data_id']) == manifest_id):
            raise ValueError
        fetched: dict[str, bytes] = {}

        class CaptureDownload:
            def download(self, file_id: str) -> bytes:
                raw = transport.download(file_id)
                pinned = (body['manifest_sha256'] if file_id == manifest_id
                          else body['generation_sha256'] if file_id == body['data_id'] else None)
                if pinned is None or digest(raw) != pinned:
                    raise IntegrityError('OVERNIGHT_SIGNED_OBJECT_BINDING_FAILED')
                fetched[file_id] = raw
                return raw

        generation = audit_remote(CaptureDownload(), manifest_id, expected_sha256, source_root=source_root)
        manifest_raw = fetched[manifest_id]
        manifest = _decode(manifest_raw)
        if (body['manifest_id'] != manifest_id or body['data_id'] != manifest['data_file_id']
                or body['manifest_sha256'] != digest(manifest_raw)
                or body['generation_sha256'] != generation.sha256
                or body['recipe_sha256'] != generation.recipe_sha256
                or type(body['recorded_decisions']) is not int
                or body['recorded_decisions'] != generation.recorded_decisions):
            raise ValueError
        return SignedCustodyAudit(generation, digest(signed_report), digest(trusted_public_key),
                                  signed_at.isoformat())
    except Exception:
        raise IntegrityError('OVERNIGHT_SIGNED_CUSTODY_READBACK_FAILED') from None
