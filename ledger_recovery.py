"""Original-ledger recovery witnesses, not hot-row-count recovery certificates.

Expected witnesses come from a reviewed source audit, never the recovery target.
No network setup, mutations, file writes or secret discovery occur here.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from urllib.parse import parse_qsl, unquote, urlsplit

from evidence_ledger import canonical_json
from ledger_runtime_reader import LedgerRuntimeReader

VERSION = 'original-ledger-recovery-v1'
HEX = re.compile(r'[0-9a-f]{64}')


def database_identity(database_url: str) -> str:
    """Hash endpoint identity without passwords; normalize known service aliases.

    Supabase project IDs distinguish shared pooler tenants and ignore role names.
    Neon pooled/unpooled endpoint aliases refer to the same database. Unknown
    proxy aliases still need owner review; this is not proof of network isolation.
    """
    try:
        parsed = urlsplit(database_url)
        host = (parsed.hostname or '').lower()
        if parsed.scheme not in ('postgres', 'postgresql') or not host or ',' in host:
            raise ValueError
        # libpq query arguments can override URI endpoint/user/database fields.
        # Permit connection hygiene only, never identity-changing overrides.
        allowed = {'sslmode', 'sslrootcert', 'sslcert', 'sslkey', 'connect_timeout',
                   'application_name', 'channel_binding', 'target_session_attrs',
                   'keepalives', 'keepalives_idle', 'keepalives_interval', 'keepalives_count'}
        if any(name not in allowed for name, _ in parse_qsl(parsed.query, keep_blank_values=True)):
            raise ValueError
        database = unquote(parsed.path.lstrip('/'))
        if not database or parsed.fragment:
            raise ValueError
        port = parsed.port or 5432
        project = re.fullmatch(r'db\.([a-z0-9]{20})\.supabase\.co', host)
        if project:
            material = {'service': 'supabase', 'project': project[1], 'database': database}
        elif host.endswith('.pooler.supabase.com'):
            suffix = unquote(parsed.username or '').rsplit('.', 1)[-1]
            if not re.fullmatch(r'[a-z0-9]{20}', suffix):
                raise ValueError
            material = {'service': 'supabase', 'project': suffix, 'database': database}
        else:
            if host.endswith('.neon.tech'):
                first, rest = host.split('.', 1)
                host = first.removesuffix('-pooler') + '.' + rest
            material = {'service': 'postgres', 'host': host, 'port': str(port), 'database': database}
        return hashlib.sha256(canonical_json(material).encode()).hexdigest()
    except Exception:
        raise RecoveryCheckError('RECOVERY_DATABASE_IDENTITY_INVALID') from None


class RecoveryCheckError(ValueError):
    """Stable recovery errors; originals and credentials never appear in output."""


@dataclass(frozen=True)
class RecoveryWitness:
    """Trusted source count and digest of ordered original signed identities."""
    version: str
    events: int
    originals_sha256: str

    def __post_init__(self) -> None:
        if (self.version != VERSION or type(self.events) is not int or self.events < 1
                or not isinstance(self.originals_sha256, str)
                or HEX.fullmatch(self.originals_sha256) is None):
            raise RecoveryCheckError('RECOVERY_EXPECTATION_INVALID')


def capture_witness(reader: LedgerRuntimeReader) -> RecoveryWitness:
    """Exhaust the original-signature/root/head-fenced reader before certification."""
    digest = hashlib.sha256()
    count = 0
    try:
        for row in reader.verified_events():
            material = {name: row[name] for name in
                        ('aggregate_id', 'sequence_no', 'event_id', 'event_hash')}
            digest.update(canonical_json(material).encode('utf-8') + b'\n')
            count += 1
    except Exception:
        raise RecoveryCheckError('RECOVERY_ORIGINALS_UNVERIFIED') from None
    if count == 0:
        raise RecoveryCheckError('RECOVERY_SOURCE_EMPTY')
    return RecoveryWitness(VERSION, count, digest.hexdigest())


def verify_original_recovery(reader: LedgerRuntimeReader, expected: RecoveryWitness) -> dict[str, object]:
    """Compare complete authenticated originals with an independently trusted source."""
    if not isinstance(expected, RecoveryWitness):
        raise RecoveryCheckError('RECOVERY_EXPECTATION_INVALID')
    actual = capture_witness(reader)
    valid = actual == expected
    return {'status': 'PASS' if valid else 'FAILED', 'ledger_chain_verified': valid,
            'originals_verified': valid, 'events_checked': actual.events,
            'scope': 'ORIGINAL_HMAC_HOT_AND_COLD',
            'reason': None if valid else 'RECOVERY_ORIGINALS_DIFFER_FROM_SOURCE'}
