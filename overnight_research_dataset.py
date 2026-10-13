"""Inactive, in-memory causal dataset projection. No capture or dataset discovery."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
import math
import re
from typing import Any, Literal, Mapping, Sequence

DataScope = Literal['DEVELOPMENT_ONLY', 'PROSPECTIVE_VERSIONED']
PROSPECTIVE_START = datetime(2026, 10, 13, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def validate_version(value: str) -> None:
    if type(value) is not str or re.fullmatch(r'[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*', value) is None:
        raise ResearchError('EXPLICIT_VERSION_ID_REQUIRED')


class ResearchError(ValueError):
    """Stable local validation failure."""


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def unique_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate fields recursively in retained governance/experiment JSON."""
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ResearchError('DUPLICATE_JSON_FIELD')
        result[key] = value
    return result


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def sha(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ResearchError('SHA256_REQUIRED')
    return value


def instant(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        raise ResearchError('AWARE_TIME_REQUIRED') from None


def development_time(value: str) -> datetime:
    result = instant(value)
    # No owner override and no loader for sealed 2025/2026 historical inputs.
    if not 2022 <= result.astimezone(PROSPECTIVE_START.tzinfo).year <= 2024:
        raise ResearchError('SEALED_OR_UNSUPPORTED_PERIOD')
    return result


def scoped_time(value: str, scope: DataScope) -> datetime:
    if scope == 'DEVELOPMENT_ONLY':
        return development_time(value)
    result = instant(value)
    if scope != 'PROSPECTIVE_VERSIONED' or result < PROSPECTIVE_START:
        raise ResearchError('SEALED_OR_UNSUPPORTED_PERIOD')
    return result


@dataclass(frozen=True)
class VersionBinding:
    """Explicit capture version + recipe identity. Programme item letters are not versions."""

    version: str
    recipe_sha256: str
    source_code_sha256: str
    interpretation: str
    data_scope: DataScope = 'DEVELOPMENT_ONLY'

    def validate(self) -> None:
        validate_version(self.version)
        if not self.interpretation.strip() or self.data_scope not in ('DEVELOPMENT_ONLY', 'PROSPECTIVE_VERSIONED'):
            raise ResearchError('VERSION_BINDING_REQUIRED')
        sha(self.recipe_sha256)
        sha(self.source_code_sha256)


@dataclass(frozen=True)
class CausalRow:
    row_id: str
    version: str
    recipe_sha256: str
    binding_sha256: str
    session_open: str
    decision_at: str
    available_at: str
    projection_sha256: str | None
    poll_sha256: str
    status: str
    direction: int | None
    features: tuple[tuple[str, float], ...]
    data_scope: DataScope = 'DEVELOPMENT_ONLY'
    authenticity_verified: bool = False
    admission_verified: bool = False
    label: None = None
    training_eligible: bool = False
    approval_authority: bool = False
    fill_evidence: bool = False


def validate_rows(rows: Sequence[CausalRow]) -> None:
    seen: set[str] = set()
    for row in rows:
        validate_version(row.version)
        if (row.row_id in seen or row.label is not None
                or row.training_eligible is not False or row.approval_authority is not False
                or row.fill_evidence is not False or row.authenticity_verified is not False
                or row.admission_verified is not False):
            raise ResearchError('INACTIVE_UNIQUE_ROWS_REQUIRED')
        seen.add(row.row_id)
        for value in (row.row_id, row.recipe_sha256, row.binding_sha256, row.poll_sha256):
            sha(value)
        if row.projection_sha256 is not None:
            sha(row.projection_sha256)
        opening, decision, available = (scoped_time(value, row.data_scope) for value in (
            row.session_open, row.decision_at, row.available_at))
        if not opening < decision <= available:
            raise ResearchError('ROW_CHRONOLOGY_INVALID')
        if (len(dict(row.features)) != len(row.features)
                or any(type(v) not in (int, float) or not math.isfinite(v) for _, v in row.features)):
            raise ResearchError('FEATURES_INVALID')


def project_bundle(bundle: Mapping[str, Any], binding: VersionBinding) -> tuple[CausalRow, ...]:
    """Replay the existing verifier before deriving frozen-prefix features.

    Only explicit development or verified versioned prospective-format bundles are accepted. Blocked polls remain
    rows without features. Missing polls are never backfilled into observations.
    """
    binding.validate()
    if bundle.get('format') != 'forward-versioned-research-bundle-v1':
        raise ResearchError('VERSIONED_CAPTURE_FORMAT_REQUIRED')
    scoped_time(bundle['config']['session_open'], binding.data_scope)
    scoped_time(bundle['config']['session_close'], binding.data_scope)
    if binding.version != bundle['config']['version']:
        raise ResearchError('CAPTURE_VERSION_BINDING_MISMATCH')
    if fingerprint(bundle['recipe']) != binding.recipe_sha256:
        raise ResearchError('RECIPE_BINDING_MISMATCH')
    if bundle['recipe'].get('sources', {}).get('forward_versioned_producer.py') != binding.source_code_sha256:
        raise ResearchError('SOURCE_CODE_BINDING_MISMATCH')
    # Import only on explicit call; never instantiate Producer, capture, or publish.
    from forward_versioned_producer import verify
    verified = verify(dict(bundle))
    rows: list[CausalRow] = []
    for poll in verified['polls']:
        source, decision = poll['source'], poll['decision']
        receipt = scoped_time(source['received_at'], binding.data_scope)
        computed = scoped_time(poll['computed_at'], binding.data_scope)
        if computed < receipt:
            raise ResearchError('COMPUTATION_BEFORE_RECEIPT')
        features: tuple[tuple[str, float], ...] = ()
        status, direction, projection_hash = 'BLOCKED_INPUT', None, None
        if decision is not None:
            projection = decision['projection']
            bars = projection['bars']
            for bar in bars:
                if (scoped_time(bar['known_at'], binding.data_scope) > receipt
                        or scoped_time(bar['bar_start'], binding.data_scope) + timedelta(minutes=5) > receipt):
                    raise ResearchError('FUTURE_PREFIX_INPUT')
            closes = [float(bar['values'][3]) for bar in bars]
            last = bars[-1]['values']
            features = (('completed_prefix_bars', float(len(bars))),
                        ('last_range_fraction', (float(last[1]) - float(last[2])) / closes[-1]),
                        ('close_return_1', closes[-1] / closes[-2] - 1 if len(closes) > 1 else 0.0),
                        ('single_bar_return_unavailable', float(len(closes) == 1)),
                        ('revision_count', float(len(projection['revision_annotations']))))
            observation = decision['observation']
            direction = observation['direction']
            status = 'OBSERVED_CANDIDATE' if observation['available'] else 'WARMUP_UNAVAILABLE'
            projection_hash = projection['projection_sha256']
        poll_hash = fingerprint(poll)
        bind_hash = fingerprint(asdict(binding))
        rows.append(CausalRow(
            fingerprint({'binding': bind_hash, 'poll': poll_hash}), binding.version,
            binding.recipe_sha256, bind_hash, verified['config']['session_open'],
            source['slot'], computed.isoformat(), projection_hash, poll_hash,
            status, direction, features, binding.data_scope))
    validate_rows(rows)
    return tuple(rows)


def dataset_manifest(rows: Sequence[CausalRow], *, source_hashes: Sequence[str],
                     feature_code_sha256: str, licensing_status: str = 'UNVERIFIED') -> dict[str, Any]:
    """Logical dataset manifest only; not a release/package manifest or admission."""
    validate_rows(rows)
    sha(feature_code_sha256)
    hashes = sorted(set(sha(value) for value in source_hashes))
    if rows and not hashes:
        raise ResearchError('SOURCE_HASHES_REQUIRED')
    if licensing_status not in ('UNVERIFIED', 'DENIED', 'REVIEWED_FOR_DECLARED_RESEARCH'):
        raise ResearchError('LICENSING_STATUS_INVALID')
    ordered = sorted(rows, key=lambda r: (instant(r.available_at), r.version, r.row_id))
    body = {'format': 'overnight-research-dataset-v1', 'row_count': len(rows),
            'rows_sha256': fingerprint([asdict(row) for row in ordered]),
            'source_sha256s': hashes, 'feature_code_sha256': feature_code_sha256,
            'versions': sorted({row.version for row in rows}),
            'data_scopes': sorted({row.data_scope for row in rows}),
            'bindings': sorted({row.binding_sha256 for row in rows}),
            'availability_basis': 'ACTUAL_RECEIPT_AND_COMPUTATION',
            'licensing_status': licensing_status, 'adequate_data': False,
            'status': 'EMPTY' if not rows else 'CANDIDATE_ONLY',
            'training_eligible': False, 'approval_authority': False,
            'fill_evidence': False, 'sealed_historical_years': [2025, 2026],
            'prospective_not_before': PROSPECTIVE_START.isoformat(),
            'authenticity_verified': False, 'admission_verified': False}
    return {**body, 'manifest_sha256': fingerprint(body)}


def parquet_bytes(rows: Sequence[CausalRow], manifest: Mapping[str, Any]) -> bytes:
    """Optional explicit Arrow export to memory; missing backend fails closed.

    Uniform JSON row payload preserves schema without inference across versions.
    No installs, fallback CSV, external paths, or files are opened.
    """
    validate_rows(rows)
    body = {key: value for key, value in manifest.items() if key != 'manifest_sha256'}
    ordered = sorted(rows, key=lambda r: (instant(r.available_at), r.version, r.row_id))
    if (manifest.get('manifest_sha256') != fingerprint(body)
            or manifest.get('rows_sha256') != fingerprint([asdict(row) for row in ordered])
            or manifest.get('row_count') != len(rows)
            or any(manifest.get(flag) is not False for flag in
                   ('training_eligible', 'approval_authority', 'fill_evidence', 'adequate_data'))):
        raise ResearchError('MANIFEST_MISMATCH')
    try:
        arrow = importlib.import_module('pyarrow')
        parquet = importlib.import_module('pyarrow.parquet')
    except ImportError:
        raise ResearchError('PARQUET_DEPENDENCY_UNAVAILABLE') from None
    schema = arrow.schema([('row_id', arrow.string()), ('version', arrow.string()),
                           ('available_at', arrow.timestamp('us', tz='UTC')),
                           ('payload_json', arrow.string())], metadata={
                               b'overnight_research_manifest': canonical(dict(manifest))})
    table = arrow.Table.from_pylist([{'row_id': row.row_id, 'version': row.version,
        'available_at': instant(row.available_at), 'payload_json': canonical(asdict(row)).decode()}
        for row in ordered], schema=schema)
    sink = arrow.BufferOutputStream()
    parquet.write_table(table, sink, compression='NONE', version='2.6')
    raw = sink.getvalue().to_pybytes()
    if type(raw) is not bytes:
        raise ResearchError('PARQUET_BACKEND_BYTES_INVALID')
    return raw
