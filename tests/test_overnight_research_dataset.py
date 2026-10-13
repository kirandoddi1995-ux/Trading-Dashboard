"""Synthetic development-only bundle projection; no installed capture/data access."""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from functools import lru_cache
import importlib
import importlib.util
import json
from typing import Any

import pytest

from overnight_research_dataset import (
    DataScope, ResearchError, VersionBinding, dataset_manifest, fingerprint, parquet_bytes,
    project_bundle, validate_rows,
)


@lru_cache(maxsize=16)
def _cached_bundle(counts: tuple[int, ...] = (1, 2), *, blocked: bool = False,
                day: str = '2022-01-03') -> dict[str, Any]:
    # Construct synthetic in-memory raw snapshots; never instantiate a journal.
    from forward_nifty_producer import prepare_config
    from forward_versioned_producer import recipe, _decision, verify
    from forward_revision_quarantine import snapshot
    config = prepare_config(day, 24900, 'a' * 64, day+'T08:45:00+05:30')
    frozen = recipe(config, day+'T09:00:00+05:30')
    opening = datetime.fromisoformat(config['session_open'])
    polls, sources = [], []
    for number in counts:
        bars: list[list[Any]] = [[(opening + timedelta(minutes=5 * i)).isoformat(), 25000 + 2*i,
            25003 + 2*i, 24998 + 2*i, 25001 + 2*i, 0, 0] for i in range(number)]
        if number > 1:
            bars[0][4] += 1  # revision appears only in a later received poll
        if blocked:
            bars = bars[1:]
        received = (opening + timedelta(minutes=5*number, seconds=30)).isoformat()
        computed = (datetime.fromisoformat(received) + timedelta(seconds=1)).isoformat()
        source = snapshot(config, bars, received, [], fingerprint(frozen))
        sources.append(source)
        polls.append({'source': source, 'computed_at': computed,
            'decision': _decision(config, frozen, sources, computed)})
    recorded = sum(poll['decision'] is not None for poll in polls)
    bundle = {'format': 'forward-versioned-research-bundle-v1', 'config': config,
        'recipe': frozen, 'polls': polls, 'recorded_decisions': recorded,
        'missing_decisions': 75-recorded, 'expected_decisions': 75,
        'approval_authority': False, 'fill_evidence': False, 'training_eligible': False}
    return verify(bundle)


def make_bundle(counts: tuple[int, ...] = (1, 2), *, blocked: bool = False,
                day: str = '2022-01-03') -> dict[str, Any]:
    return deepcopy(_cached_bundle(counts, blocked=blocked, day=day))


def binding(bundle: dict[str, Any], version: str | None = None) -> VersionBinding:
    return VersionBinding(version or bundle['config']['version'], fingerprint(bundle['recipe']),
        bundle['recipe']['sources']['forward_versioned_producer.py'], 'reviewed fixture binding')


def test_versions_preserve_receipts_and_no_labels() -> None:
    bundle = make_bundle()
    original = deepcopy(bundle)
    rows = project_bundle(bundle, binding(bundle))
    assert bundle == original and len(rows) == 2
    assert rows[0].status == 'WARMUP_UNAVAILABLE'
    assert dict(rows[0].features)['revision_count'] == 0
    assert dict(rows[1].features)['revision_count'] == 1
    assert rows[0].available_at != rows[0].decision_at
    assert all(row.label is None and not row.fill_evidence and not row.training_eligible for row in rows)


def test_future_revision_cannot_rewrite_prior_row() -> None:
    full = make_bundle()
    prefix = deepcopy(full)
    prefix['polls'] = prefix['polls'][:1]
    prefix.update(recorded_decisions=1, missing_decisions=74)
    assert project_bundle(prefix, binding(prefix))[0] == project_bundle(full, binding(full))[0]


def test_blocked_and_missing_are_not_backfilled() -> None:
    bundle = make_bundle((3,), blocked=True)
    rows = project_bundle(bundle, binding(bundle))
    assert len(rows) == 1 and rows[0].status == 'BLOCKED_INPUT' and rows[0].features == ()
    assert rows[0].direction is None and bundle['missing_decisions'] == 75


def test_observed_candidate_is_still_ineligible() -> None:
    bundle = make_bundle((61,))
    row = project_bundle(bundle, binding(bundle))[0]
    assert row.status == 'OBSERVED_CANDIDATE' and not row.training_eligible


@pytest.mark.parametrize('damage', ['recipe', 'decision', 'sealed', 'binding', 'letter'])
def test_bad_bundle_or_binding_fails_closed(damage: str) -> None:
    bundle = make_bundle()
    bind = binding(bundle)
    if damage == 'recipe':
        bundle['recipe']['training_eligible'] = True
    elif damage == 'decision':
        bundle['polls'][0]['decision']['observation']['direction'] = 1
    elif damage == 'sealed':
        bundle['config']['session_open'] = '2025-01-03T09:15:00+05:30'
    elif damage == 'binding':
        bind = replace(bind, recipe_sha256='b' * 64)
    else:
        bind = replace(bind, version='I')
    with pytest.raises(ValueError):
        project_bundle(bundle, bind)


def test_manifest_determinism_and_mutation_rejected() -> None:
    bundle = make_bundle()
    rows = project_bundle(bundle, binding(bundle))
    kwargs: dict[str, Any] = {'source_hashes': [fingerprint(bundle)], 'feature_code_sha256': 'c'*64}
    manifest = dataset_manifest(rows, **kwargs)
    assert dataset_manifest(tuple(reversed(rows)), **kwargs) == manifest
    assert manifest['licensing_status'] == 'UNVERIFIED' and not manifest['adequate_data']
    with pytest.raises(ResearchError):
        validate_rows((rows[0], rows[0]))
    with pytest.raises(ResearchError):
        validate_rows((replace(rows[0], training_eligible=True),))
    with pytest.raises(ResearchError, match='MANIFEST_MISMATCH'):
        parquet_bytes(rows, {**manifest, 'training_eligible': True})


def test_missing_parquet_backend_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str) -> Any:
        raise ImportError(name)
    monkeypatch.setattr(importlib, 'import_module', missing)
    manifest = dataset_manifest((), source_hashes=(), feature_code_sha256='c'*64)
    with pytest.raises(ResearchError, match='PARQUET_DEPENDENCY_UNAVAILABLE'):
        parquet_bytes((), manifest)


@pytest.mark.skipif(importlib.util.find_spec('pyarrow') is None, reason='optional pyarrow is not installed')
def test_optional_parquet_roundtrip() -> None:
    pa = importlib.import_module('pyarrow')
    pq = importlib.import_module('pyarrow.parquet')
    bundle = make_bundle()
    rows = project_bundle(bundle, binding(bundle))
    manifest = dataset_manifest(rows, source_hashes=[fingerprint(bundle)], feature_code_sha256='c'*64)
    raw = parquet_bytes(rows, manifest)
    table = pq.read_table(pa.BufferReader(raw))
    assert table.num_rows == 2
    assert json.loads(table.schema.metadata[b'overnight_research_manifest']) == manifest
    assert json.loads(table.to_pylist()[0]['payload_json']) == json.loads(json.dumps(asdict(rows[0])))


def test_prospective_2026_requires_explicit_scope_and_verified_format() -> None:
    bundle = make_bundle(day='2026-10-13')
    with pytest.raises(ResearchError, match='SEALED'):
        project_bundle(bundle, binding(bundle))
    bind = replace(binding(bundle), data_scope='PROSPECTIVE_VERSIONED')
    rows = project_bundle(bundle, bind)
    assert rows[0].data_scope == 'PROSPECTIVE_VERSIONED'
    assert rows[0].version == 'nifty-forward-v1'
    assert not rows[0].authenticity_verified and not rows[0].admission_verified
    broken = deepcopy(bundle)
    broken['format'] = 'historical-final-candles'
    with pytest.raises(ResearchError, match='FORMAT'):
        project_bundle(broken, bind)
    broken = deepcopy(bundle)
    broken['polls'][0]['decision']['observation']['input_hash'] = 'f'*64
    with pytest.raises(ValueError):
        project_bundle(broken, bind)


def test_2025_is_rejected_even_with_prospective_scope() -> None:
    bundle = make_bundle()
    bundle['config']['session_open'] = '2025-10-13T09:15:00+05:30'
    scopes: tuple[DataScope, ...] = ('DEVELOPMENT_ONLY', 'PROSPECTIVE_VERSIONED')
    for scope in scopes:
        with pytest.raises(ResearchError, match='SEALED'):
            project_bundle(bundle, replace(binding(bundle), data_scope=scope))
