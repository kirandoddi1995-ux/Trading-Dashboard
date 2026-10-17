"""Explicit generated 2022 toy reference prices, never market evidence."""
from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import math
from pathlib import Path
from typing import cast

import pytest

from research_dataset_boundary import (
    BoundaryReport, DatasetPlan, DecisionInput, ReferenceLabel, SourceVersion,
    evaluate, input_sha256, version_sha256,
)

PIN = 'a'*64
END = '2022-01-03T10:05:00+05:30'
NOW = '2022-01-03T10:06:00+05:30'


def fixture() -> tuple[DatasetPlan, tuple[SourceVersion, ...], DecisionInput, ReferenceLabel]:
    plan = DatasetPlan(PIN, PIN, 'DEVELOPMENT_2022_2024',
                       '2022-01-01T00:00:00+05:30', ('toy',), PIN, PIN,
                       True, True, True, False, 'SYNTHETIC')
    entry = SourceVersion('entry', 1, '2022-01-03T09:59:00+05:30',
                          '2022-01-03T10:00:00+05:30', 100., 1, PIN, PIN)
    target = SourceVersion('target', 1, END, END, 101., 1, PIN, PIN)
    decision = DecisionInput('toy', entry.observed_at, ('entry',), 'entry', input_sha256((entry,)))
    label = ReferenceLabel('toy', END, END, 'target', version_sha256(target))
    return plan, (entry, target), decision, label


def run(*, plan: DatasetPlan | None = None, versions: tuple[SourceVersion, ...] | None = None,
        decision: DecisionInput | None = None, label: ReferenceLabel | None = None,
        now: str = NOW) -> BoundaryReport:
    p, v, d, l = fixture()
    return evaluate(p if plan is None else plan, v if versions is None else versions,
                    (d if decision is None else decision,), (l if label is None else label,),
                    evaluated_at=now)


def test_synthetic_reference_only_manifest_never_grants_admission() -> None:
    result = run()
    assert result.status == 'STRUCTURAL_REFERENCE_OUTPUT_UNADMITTED'
    assert result.rows[0].direction == 1
    assert result.rows[0].label_kind == 'REFERENCE_DIRECTION_NOT_EXECUTABLE_PNL'
    for flag in (result.training_eligible, result.promotable, result.approval_authority,
                 result.authenticated_admission, result.executable_pnl):
        assert flag is False
    manifest = json.loads(result.manifest)
    assert manifest['input_kind'] == 'SYNTHETIC'
    assert manifest['provenance'] == 'CALLER_CLAIMS_NOT_AUTHENTICATED'
    assert result.manifest_sha256 == hashlib.sha256(result.manifest).hexdigest()
    assert result == run()
    with pytest.raises(FrozenInstanceError):
        setattr(result, 'status', 'ADMITTED')


def test_late_revision_does_not_replace_frozen_decision_input() -> None:
    _, versions, decision, _ = fixture()
    revised = replace(versions[0], version=2, observed_at='2022-01-03T10:01:00+05:30',
                      reference_price=200., payload_sha256='b'*64)
    result = run(versions=versions+(revised,))
    assert result.rows == run().rows
    assert result.manifest_sha256 != run().manifest_sha256
    leaked = replace(decision, input_sha256=input_sha256((revised,)))
    failure = run(versions=versions+(revised,), decision=leaked)
    assert failure.rows == ()
    assert failure.rejected[0].code == 'FROZEN_INPUT_PREFIX_MISMATCH'


def test_asof_selects_latest_already_observed_version_not_final_version() -> None:
    _, versions, decision, _ = fixture()
    entry = replace(versions[0], observed_at='2022-01-03T09:59:00+05:30')
    revised = replace(entry, version=2, observed_at=decision.decision_at, reference_price=102.)
    selected = replace(decision, input_sha256=input_sha256((revised,)))
    result = run(versions=(versions[1], revised, entry), decision=selected)
    assert result.rows[0].direction == -1
    assert run(versions=(entry, revised, versions[1]), decision=selected) == result


def test_full_declared_input_prefix_not_latest_price_only() -> None:
    _, versions, decision, _ = fixture()
    context = replace(versions[0], event_id='context', reference_price=50.)
    d = replace(decision, event_ids=('context', 'entry'))
    assert run(versions=versions+(context,), decision=d).rejected[0].code == 'FROZEN_INPUT_PREFIX_MISMATCH'
    d = replace(d, input_sha256=input_sha256((context, versions[0])))
    assert run(versions=versions+(context,), decision=d).rows


def test_unobserved_input_is_missing_even_when_future_version_is_supplied() -> None:
    _, versions, _, _ = fixture()
    entry = replace(versions[0], observed_at='2022-01-03T10:01:00+05:30')
    result = run(versions=(entry, versions[1]))
    assert result.missing[0].code == 'INPUT_NOT_OBSERVED_AT_DECISION'
    assert not result.rows


def test_source_identity_and_duplicate_prefix_are_rejected() -> None:
    _, versions, decision, _ = fixture()
    with pytest.raises(ValueError, match='SOURCE_IDENTITY_MISMATCH'):
        run(versions=(replace(versions[0], source_sha256='b'*64), versions[1]))
    with pytest.raises(ValueError, match='AMBIGUOUS_INPUT_PREFIX'):
        run(decision=replace(decision, event_ids=('entry', 'entry')))


def test_neutral_label_is_reference_zero_not_missing_or_pnl() -> None:
    _, versions, _, label = fixture()
    target = replace(versions[1], reference_price=100.)
    result = run(versions=(versions[0], target),
                 label=replace(label, target_version_sha256=version_sha256(target)))
    assert result.rows[0].direction == 0 and result.executable_pnl is False


def test_equivalent_aware_instants_have_equal_version_hashes() -> None:
    _, versions, _, _ = fixture()
    changed = replace(versions[0], event_at='2022-01-03T04:29:00+00:00',
                      observed_at='2022-01-03T04:30:00+00:00')
    assert version_sha256(changed) == version_sha256(versions[0])


@pytest.mark.parametrize('field', ['licence_attested', 'provenance_attested', 'preregistration_attested'])
def test_missing_attestation_withholds_all_rows(field: str) -> None:
    plan, _, _, _ = fixture()
    if field == 'licence_attested':
        plan = replace(plan, licence_attested=False)
    elif field == 'provenance_attested':
        plan = replace(plan, provenance_attested=False)
    else:
        plan = replace(plan, preregistration_attested=False)
    result = run(plan=plan)
    assert result.status == 'INSUFFICIENT_EVIDENCE' and not result.rows
    assert result.missing


def test_missing_licence_and_provenance_hashes_are_classified() -> None:
    plan, _, _, _ = fixture()
    result = run(plan=replace(plan, licence_sha256=None, provenance_sha256=None))
    assert {i.code for i in result.missing} == {'LICENCE_EVIDENCE_REQUIRED', 'PROVENANCE_EVIDENCE_REQUIRED'}


def test_missing_family_decision_and_label_no_partial_dataset() -> None:
    plan, versions, decision, _ = fixture()
    result = evaluate(replace(plan, decision_ids=('toy', 'missing')), versions, (decision,), (), evaluated_at=NOW)
    assert not result.rows
    assert {i.code for i in result.missing} == {'DECISION_NOT_REPORTED', 'LABEL_NOT_REPORTED'}


@pytest.mark.parametrize('kind', ['horizon', 'receipt', 'target_receipt', 'early', 'pin'])
def test_immature_invalid_or_missing_label_is_not_fabricated(kind: str) -> None:
    _, versions, _, label = fixture()
    if kind == 'horizon':
        result = run(now='2022-01-03T10:04:00+05:30')
    elif kind == 'receipt':
        result = run(label=replace(label, observed_at='2022-01-03T10:07:00+05:30'))
    elif kind == 'target_receipt':
        target = replace(versions[1], observed_at=NOW)
        result = run(versions=(versions[0], target), label=replace(label, target_version_sha256=version_sha256(target)))
    elif kind == 'early':
        result = run(label=replace(label, horizon_end='2022-01-03T09:59:00+05:30'))
    else:
        result = run(label=replace(label, target_version_sha256='b'*64))
    assert not result.rows and (result.missing or result.rejected)


@pytest.mark.parametrize('kind', ['entry_price', 'target_price', 'entry_count', 'target_count'])
def test_insufficient_reference_quote_is_missing_not_executable(kind: str) -> None:
    _, versions, decision, label = fixture()
    entry, target = versions
    if kind == 'entry_price':
        entry = replace(entry, reference_price=None)
    elif kind == 'target_price':
        target = replace(target, reference_price=None)
    elif kind == 'entry_count':
        entry = replace(entry, quote_count=0)
    else:
        target = replace(target, quote_count=0)
    result = run(versions=(entry, target), decision=replace(decision, input_sha256=input_sha256((entry,))),
                 label=replace(label, target_version_sha256=version_sha256(target)))
    assert result.missing[0].code == 'INSUFFICIENT_REFERENCE_QUOTE'
    assert not result.rows and result.executable_pnl is False


@pytest.mark.parametrize('kind', ['same_version', 'same_receipt', 'reversed_receipt', 'changed_event'])
def test_ambiguous_duplicates_and_revision_ordering_rejected(kind: str) -> None:
    _, versions, _, _ = fixture()
    revised = replace(versions[0], version=2)
    if kind == 'same_version':
        revised = versions[0]
    elif kind == 'reversed_receipt':
        revised = replace(revised, observed_at=versions[0].event_at)
    elif kind == 'changed_event':
        revised = replace(revised, event_at='2022-01-03T09:58:00+05:30', observed_at=END)
    with pytest.raises(ValueError, match='AMBIGUOUS_OR_NONMONOTONIC_REVISION'):
        run(versions=versions+(revised,))


@pytest.mark.parametrize('kind', ['decision', 'label', 'planned', 'undeclared'])
def test_ambiguous_or_outside_frozen_scope_rejected(kind: str) -> None:
    p, v, d, l = fixture()
    with pytest.raises(ValueError):
        if kind == 'decision':
            evaluate(p, v, (d, d), (l,), evaluated_at=NOW)
        elif kind == 'label':
            evaluate(p, v, (d,), (l, l), evaluated_at=NOW)
        elif kind == 'planned':
            run(plan=replace(p, decision_ids=('toy', 'toy')))
        else:
            run(decision=replace(d, decision_id='not_declared'))


@pytest.mark.parametrize('price', [True, math.nan, math.inf, -1., 0., 1e12+1])
def test_bad_prices_rejected(price: float) -> None:
    _, versions, _, _ = fixture()
    with pytest.raises(ValueError, match='INVALID_REFERENCE_PRICE'):
        run(versions=(replace(versions[0], reference_price=price), versions[1]))


def test_preregistration_after_decision_rejects_and_hashes_bind_policy() -> None:
    plan, versions, _, _ = fixture()
    result = run(plan=replace(plan, preregistered_at=END))
    assert result.rejected[0].code == 'DECISION_PARTITION_OR_PREREGISTRATION_TIME'
    assert run(plan=replace(plan, study_sha256='b'*64)).plan_sha256 != run().plan_sha256
    assert run(versions=(versions[0], replace(versions[1], payload_sha256='b'*64))).manifest_sha256 != run().manifest_sha256


def test_sealed_history_is_never_accepted_as_development() -> None:
    # Calendar metadata substitution only; no historical records are read.
    plan, versions, decision, label = fixture()
    for year in ('2025', '2026'):
        v = tuple(replace(row, event_at=row.event_at.replace('2022', year),
                          observed_at=row.observed_at.replace('2022', year)) for row in versions)
        d = replace(decision, decision_at=decision.decision_at.replace('2022', year), input_sha256=input_sha256((v[0],)))
        l = replace(label, horizon_end=label.horizon_end.replace('2022', year),
                    observed_at=label.observed_at.replace('2022', year), target_version_sha256=version_sha256(v[1]))
        result = evaluate(plan, v, (d,), (l,), evaluated_at=NOW.replace('2022', year))
        assert result.status == 'REJECTED_EVIDENCE' and not result.rows


def test_explicit_prospective_partition_still_requires_separate_gate_and_never_admits() -> None:
    # Synthetic timestamp metadata, not 2026 capture data or a REAL assertion.
    p, v, d, l = fixture()
    v = tuple(replace(row, event_at=row.event_at.replace('2022', '2026'),
                      observed_at=row.observed_at.replace('2022', '2026')) for row in v)
    d = replace(d, decision_at=d.decision_at.replace('2022', '2026'), input_sha256=input_sha256((v[0],)))
    l = replace(l, horizon_end=l.horizon_end.replace('2022', '2026'), observed_at=l.observed_at.replace('2022', '2026'),
                target_version_sha256=version_sha256(v[1]))
    p = replace(p, partition='PROSPECTIVE_VERSIONED_2026', preregistered_at=p.preregistered_at.replace('2022', '2026'))
    result = evaluate(p, v, (d,), (l,), evaluated_at=NOW.replace('2022', '2026'))
    assert result.missing[0].code == 'SEPARATE_PROSPECTIVE_ATTESTATION_REQUIRED'
    result = evaluate(replace(p, prospective_attested=True), v, (d,), (l,), evaluated_at=NOW.replace('2022', '2026'))
    assert result.rows and result.authenticated_admission is False


def test_bounds_naive_time_boolean_flags_and_fake_real_claim() -> None:
    p, v, d, l = fixture()
    with pytest.raises(ValueError, match='COLLECTION_BOUND'):
        evaluate(p, v*2049, (d,), (l,), evaluated_at=NOW)
    with pytest.raises(ValueError, match='AWARE_TIMESTAMP_REQUIRED'):
        run(now='2022-01-03T10:06:00')
    with pytest.raises(ValueError, match='LITERAL_ATTESTATION_REQUIRED'):
        run(plan=replace(p, licence_attested=cast(bool, 1)))
    with pytest.raises(ValueError, match='UNAUTHENTICATED_INPUT_KIND_REQUIRED'):
        run(plan=replace(p, input_kind='REAL'))
    with pytest.raises(ValueError, match='INVALID_QUOTE_COUNT'):
        run(versions=(replace(v[0], quote_count=cast(int, True)), v[1]))


def test_module_has_only_stdlib_imports_and_no_activation_entrypoint() -> None:
    path = Path(__file__).resolve().parents[1]/'research_dataset_boundary.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imports.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
    assert imports <= {'__future__', 'dataclasses', 'datetime', 'hashlib', 'json', 'math', 're'}
    assert not any(isinstance(node, ast.If) for node in tree.body)
