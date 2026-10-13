"""Inactive switching review, real local source inventory, no import/execute."""
from __future__ import annotations

from dataclasses import replace
import ast
import hashlib
from pathlib import Path

import pytest

from overnight_storage_contracts import ContractError, digest
from overnight_storage_switching import REQUIRED, SwitchingEvidence, inventory, switching_plan


@pytest.mark.parametrize('name,semantic_hash', [
    ('equity_research_observations.py',
     'fcd3e95f2331fed73bbf1233540085032d01c0a9d0eca8b165e27744d0bdc93d'),
    ('recovery_drill.py',
     '508a45437320607d7a45c280f92f11e2b45e11251ff9b4e4ff6c84d80ae78dfc'),
])
def test_reviewed_main_dependencies_have_unchanged_executable_ast(
        name: str, semantic_hash: str) -> None:
    """Reviewed 1134237 differs from the old candidate only by one EOF blank line.

    This is additional compatibility evidence, not a replacement for the exact
    LF byte pins. No dependency is imported or executed by this inspection.
    """
    raw = (Path(__file__).resolve().parents[1] / name).read_bytes()
    normalized_ast = ast.dump(ast.parse(raw), include_attributes=False).encode()
    assert hashlib.sha256(normalized_ast).hexdigest() == semantic_hash


def synthetic_sources() -> dict[str, bytes]:
    sources: dict[str, bytes] = {}
    for path, symbols in REQUIRED.items():
        raw = ''
        for symbol in symbols:
            if symbol[0].isupper():
                raw += f'class {symbol}:\n    def append(self): pass\n'
            else:
                raw += f'def {symbol}(): pass\n'
        sources[path] = raw.encode()
    return sources


def evidence() -> SwitchingEvidence:
    observed = inventory(synthetic_sources())
    reference = digest(b'synthetic migration proof')
    return SwitchingEvidence('a' * 40, observed.source_sha256, observed.callables,
                             reference, reference, reference, reference, reference, reference)


def test_actual_local_inventory_cannot_claim_public_switch() -> None:
    root = Path(__file__).resolve().parents[1]
    observed = inventory({path: (root / path).read_bytes() for path in REQUIRED})
    assert observed.missing == ()
    assert 'app.py:get_production_repository' in observed.callables
    assert 'production_repository.py:ProductionRepository.connect' in observed.callables
    assert 'equity_scan_repository.py:EquityScanRepository.create_run' in observed.callables
    assert 'derivative_repository.py:DerivativeRepository.ingest_master' in observed.callables
    plan = switching_plan(observed, SwitchingEvidence(None, (), (), None, None, None, None, None, None))
    assert 'PUBLIC_BASE_UNVERIFIED' in plan.blockers
    assert 'ALL_FACTORY_CALLABLES_UNVERIFIED' in plan.blockers
    assert not plan.active and not plan.globally_wired


@pytest.mark.parametrize('missing', list(REQUIRED))
def test_every_required_source_is_gate(missing: str) -> None:
    sources = synthetic_sources()
    sources.pop(missing)
    observed = inventory(sources)
    assert missing in observed.missing
    assert switching_plan(observed, evidence()).blockers


@pytest.mark.parametrize('field', ['allocation_bounds_sha256', 'same_connection_transactions_sha256',
    'original_receipt_reconciliation_sha256', 'historical_lookup_parity_sha256',
    'native_fencing_races_sha256', 'deployment_inventory_sha256', 'public_base_sha'])
def test_every_switching_proof_is_gate(field: str) -> None:
    observed = inventory(synthetic_sources())
    from dataclasses import fields
    original = evidence()
    values: dict[str, object] = {item.name: getattr(original, item.name) for item in fields(original)}
    values[field] = None
    # Explicit fields preserve strict typing of the dataclass constructor.
    from typing import cast
    changed = SwitchingEvidence(cast(str | None, values['public_base_sha']), original.public_sources,
        original.reviewed_callables, cast(str | None, values['allocation_bounds_sha256']),
        cast(str | None, values['same_connection_transactions_sha256']),
        cast(str | None, values['original_receipt_reconciliation_sha256']),
        cast(str | None, values['historical_lookup_parity_sha256']),
        cast(str | None, values['native_fencing_races_sha256']),
        cast(str | None, values['deployment_inventory_sha256']))
    plan = switching_plan(observed, changed)
    assert plan.blockers and not plan.active and not plan.globally_wired


def test_reviewed_candidate_still_has_no_switch_primitive() -> None:
    plan = switching_plan(inventory(synthetic_sources()), evidence())
    assert plan.blockers == ()
    assert not plan.active and not plan.globally_wired


def test_source_revision_duplicate_proof_and_parse_failure() -> None:
    observed = inventory(synthetic_sources())
    provided = evidence()
    changed = list(provided.public_sources)
    changed[0] = (changed[0][0], digest(b'other revision'))
    assert 'PUBLIC_SOURCE_HASH_COVERAGE_UNVERIFIED' in switching_plan(
        observed, replace(provided, public_sources=tuple(changed))).blockers
    assert switching_plan(observed, replace(provided, reviewed_callables=())).blockers
    sources = synthetic_sources()
    sources['app.py'] = b'import bad syntax!!'
    with pytest.raises(ContractError, match='PARSE'):
        inventory(sources)
