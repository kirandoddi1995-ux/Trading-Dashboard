"""Synthetic contract checks only: no captures, tools, hosted runs or credentials."""
from dataclasses import FrozenInstanceError, replace
import itertools
from typing import Protocol, TypeVar, cast

import pytest

import project_conductor as pc
from programme_agent_team import Action, Role, contract


CANDIDATE = pc.Candidate('daily-dataset', 'a' * 64, 'b' * 40, 'owner')
CHOICE = pc.ScoutChoice('native tooling', 'adapt',
                       'https://learn.microsoft.com/en-us/powershell/', 'Use existing tools only')

FixtureT = TypeVar('FixtureT')


class FixtureReplacer(Protocol):
    def __call__(self, original: FixtureT, /, **changes: object) -> FixtureT: ...


# Deliberately permit malformed field values only at the synthetic-fixture
# construction boundary. Keep ordinary replace calls statically field-checked.
replace_fixture = cast(FixtureReplacer, replace)


def chain() -> tuple[pc.Receipt, ...]:
    actors = ('scout', 'builder', 'reviewer', 'verifier', 'verifier', 'owner')
    receipts: list[pc.Receipt] = []
    for index, stage in enumerate(pc.ORDER):
        proof: pc.Verification | None = None
        if stage in {pc.Stage.WINDOWS, pc.Stage.LINUX}:
            platform = 'windows' if stage == pc.Stage.WINDOWS else 'linux'
            runner = 'hosted-windows' if platform == 'windows' else 'hosted-ubuntu'
            proof = pc.Verification(platform, runner, 'python -B -m pytest',
                                    ('Python synthetic-3', 'dependencies synthetic-none'),
                                    'c' * 64, 10, 10, 0, 0)
        receipts.append(pc.Receipt(stage, CANDIDATE.milestone, CANDIDATE.sha256,
                                   CANDIDATE.source_pin, actors[index], 'd' * 64,
                                   True, True, (CHOICE,) if index == 0 else (), proof))
    return tuple(receipts)


def altered(index: int, **changes: object) -> tuple[pc.Receipt, ...]:
    receipts = list(chain())
    receipts[index] = replace_fixture(receipts[index], **changes)
    return tuple(receipts)


def verification(index: int) -> pc.Verification:
    proof = chain()[index].verification
    assert proof is not None
    return proof


@pytest.mark.parametrize('count', range(7))
def test_every_gate_requires_its_own_receipt(count: int) -> None:
    receipts = chain()[:count]
    result = pc.plan_milestone(CANDIDATE, receipts)
    assert result == pc.plan_milestone(CANDIDATE, receipts)
    assert result.missing == pc.ORDER[count:]
    assert result.execution_authority is False
    if count < 6:
        assert result.status == 'PENDING'
        assert result.next_stage == pc.ORDER[count]
        assert result.delegate == pc.DELEGATES[count]
    else:
        assert result.status == 'CONTRACT_COMPLETE'
        assert result.next_stage is None and result.delegate is None


def test_no_reordering_or_skipping() -> None:
    for permutation in itertools.permutations(chain()):
        result = pc.plan_milestone(CANDIDATE, permutation)
        assert (result.status == 'CONTRACT_COMPLETE') == (permutation == chain())
    for index in range(6):
        assert pc.plan_milestone(CANDIDATE, chain()[:index] + chain()[index + 1:]).status != 'CONTRACT_COMPLETE'


@pytest.mark.parametrize('changes', [
    {'milestone': ''}, {'milestone': ' padded'}, {'sha256': 'A' * 64},
    {'sha256': None}, {'source_pin': 'main'}, {'source_pin': 'b' * 39},
    {'owner': 'Builder'}, {'owner': ' owner'}, {'owner': ''}, {'owner': None},
])
def test_invalid_candidates_fail_closed(changes: dict[str, object]) -> None:
    assert pc.plan_milestone(replace_fixture(CANDIDATE, **changes), chain()).reason == 'INVALID_CANDIDATE'


@pytest.mark.parametrize('value', [None, {}, 'candidate', True])
def test_untyped_candidates(value: object) -> None:
    # Casts deliberately cross the typed boundary to test malformed runtime input;
    # they neither convert the value nor bypass validation in the conductor.
    assert pc.plan_milestone(cast(pc.Candidate, value)).status == 'BLOCKED'


@pytest.mark.parametrize('value', [None, [], {}, 'receipts', chain() + chain()])
def test_untyped_and_extra_receipts(value: object) -> None:
    assert pc.plan_milestone(CANDIDATE, cast(tuple[pc.Receipt, ...], value)).reason == 'INVALID_RECEIPTS'


@pytest.mark.parametrize('index', range(6))
@pytest.mark.parametrize('changes', [
    {'milestone': 'different-milestone'}, {'candidate_sha256': 'f' * 64},
    {'source_pin': 'f' * 40}, {'actor': ''}, {'actor': ' builder'},
    {'actor': 'Builder'}, {'actor': None}, {'evidence_sha256': ''},
    {'evidence_sha256': None}, {'passed': False}, {'passed': 1},
    {'verified': False}, {'verified': 'owner-reported'}, {'stage': 'builder'},
    {'choices': []},
])
def test_bad_or_owner_reported_proofs_never_complete(index: int, changes: dict[str, object]) -> None:
    result = pc.plan_milestone(CANDIDATE, altered(index, **changes))
    assert result.status == 'BLOCKED'
    assert result.missing == pc.ORDER[index:]
    assert result.delegate is None


def test_invalid_receipt_object_and_candidate_reset() -> None:
    assert pc.plan_milestone(CANDIDATE, (cast(pc.Receipt, None),)).reason == 'INVALID_RECEIPT'
    result = pc.plan_milestone(replace(CANDIDATE, sha256='f' * 64), chain())
    assert result.reason == 'SOURCE_OR_MILESTONE_MISMATCH'
    assert result.missing == pc.ORDER


@pytest.mark.parametrize('changes', [
    {'decision': 'maybe'}, {'decision': None}, {'rationale': ''},
    {'technology': ''}, {'primary_url': 'http://example.org/docs'},
    {'primary_url': 'https://example.org/private docs'}, {'primary_url': None},
    {'incremental_cost': 1}, {'incremental_cost': -1},
    {'incremental_cost': False}, {'incremental_cost': 0.0}, {'incremental_cost': None},
])
def test_radar_demands_explicit_zero_cost_choices(changes: dict[str, object]) -> None:
    result = pc.plan_milestone(CANDIDATE, altered(0, choices=(replace_fixture(CHOICE, **changes),)))
    assert result.reason == 'RADAR_REQUIRED_ZERO_COST_CHOICES'


@pytest.mark.parametrize('decision', ['adopt', 'adapt', 'defer', 'reject'])
def test_all_scout_decisions_supported(decision: str) -> None:
    receipt = replace(chain()[0], choices=(replace(CHOICE, decision=decision),))
    assert pc.plan_milestone(CANDIDATE, (receipt,)).next_stage == pc.Stage.BUILD


@pytest.mark.parametrize('choices', [(), (None,), (CHOICE, CHOICE)])
def test_missing_or_duplicate_radar_choices(choices: tuple[object, ...]) -> None:
    assert pc.plan_milestone(CANDIDATE, altered(0, choices=choices)).status == 'BLOCKED'


@pytest.mark.parametrize('index,actor,reason', [
    (2, 'builder', 'SELF_REVIEW'),
    (3, 'builder', 'VERIFIER_NOT_INDEPENDENT'),
    (3, 'reviewer', 'VERIFIER_NOT_INDEPENDENT'),
    (4, 'builder', 'VERIFIER_NOT_INDEPENDENT'),
    (4, 'reviewer', 'VERIFIER_NOT_INDEPENDENT'),
    (5, 'builder', 'OWNER_COMMISSION_REQUIRED'),
    (5, 'reviewer', 'OWNER_COMMISSION_REQUIRED'),
    (5, 'stranger', 'OWNER_COMMISSION_REQUIRED'),
] + [(i, 'owner', 'OWNER_CANNOT_APPROVE_OWN_WORK') for i in range(5)])
def test_no_principal_can_approve_own_work(index: int, actor: str, reason: str) -> None:
    assert pc.plan_milestone(CANDIDATE, altered(index, actor=actor)).reason == reason


@pytest.mark.parametrize('index', [3, 4])
@pytest.mark.parametrize('changes', [
    {'platform': 'macos'}, {'platform': None}, {'runner': 'local-debian'},
    {'runner': 'local-windows'}, {'command': ''}, {'environment': ()},
    {'environment': ['Python 3']}, {'environment': ('',)},
    {'collection_sha256': ''}, {'collected': 0}, {'passed': 0},
    {'passed': 11}, {'failed': 1}, {'skipped': 1}, {'collected': True},
    {'passed': 10.0}, {'failed': -1}, {'skip_reasons': []},
    {'skipped': 1, 'passed': 9, 'skip_reasons': ('',)},
])
def test_platform_failure_paths(index: int, changes: dict[str, object]) -> None:
    proof = replace_fixture(verification(index), **changes)
    assert pc.plan_milestone(CANDIDATE, altered(index, verification=proof)).reason == 'PLATFORM_PROOF_REQUIRED'


@pytest.mark.parametrize('index', [3, 4])
@pytest.mark.parametrize('proof', [None, {}, True])
def test_missing_platform_proofs(index: int, proof: object) -> None:
    assert pc.plan_milestone(CANDIDATE, altered(index, verification=proof)).status == 'BLOCKED'


@pytest.mark.parametrize('changes', [
    {'collection_sha256': 'e' * 64}, {'collected': 11, 'passed': 11},
])
def test_platform_collection_must_match(changes: dict[str, object]) -> None:
    proof = replace_fixture(verification(4), **changes)
    assert pc.plan_milestone(CANDIDATE, altered(4, verification=proof)).reason == 'PLATFORM_COLLECTION_MISMATCH'


def test_skips_are_counted_and_explicit_not_disguised_as_passes() -> None:
    proof = replace(verification(4), passed=9, skipped=1,
                    skip_reasons=('synthetic optional test unavailable; owner review required',))
    assert pc.plan_milestone(CANDIDATE, altered(4, verification=proof)).status == 'CONTRACT_COMPLETE'


def test_unexpected_stage_payloads_cannot_smuggle_proofs() -> None:
    assert pc.plan_milestone(CANDIDATE, altered(1, choices=(CHOICE,))).reason == 'UNEXPECTED_SCOUT_CHOICES'
    assert pc.plan_milestone(CANDIDATE, altered(0, verification=chain()[3].verification)).reason == 'UNEXPECTED_PLATFORM_PROOF'


@pytest.mark.parametrize('role', list(Role))
def test_delegation_reuses_existing_contract(role: Role) -> None:
    assert pc.delegate(role) == contract(role)


@pytest.mark.parametrize('role', [Role.MORNING, Role.AUDITOR, Role.POSTSESSION])
@pytest.mark.parametrize('action', list(Action))
def test_runtime_report_only_with_supplied_redaction(role: Role, action: Action) -> None:
    assert pc.delegation_allowed(role, action, supplied_redacted=True,
                                 disposable_offline=True) == (action in {Action.REDACTED_READ, Action.REPORT})
    assert not pc.delegation_allowed(role, action)


@pytest.mark.parametrize('role', list(Role))
@pytest.mark.parametrize('action', [Action.SECRET_READ, Action.HOSTED_WRITE, Action.TRADE,
                                   Action.TASK_ENABLE, Action.DELETE, Action.TRAIN, Action.CHANGE_GATE])
def test_every_role_denies_live_authority(role: Role, action: Action) -> None:
    assert not pc.delegation_allowed(role, action, supplied_redacted=True, disposable_offline=True)


def test_offline_delegation_is_bounded() -> None:
    assert pc.delegation_allowed(Role.BUILDER, Action.OFFLINE_EDIT, disposable_offline=True)
    assert not pc.delegation_allowed(Role.BUILDER, Action.OFFLINE_EDIT)
    assert pc.delegation_allowed(Role.VERIFIER, Action.OFFLINE_TEST, disposable_offline=True)
    assert not pc.delegation_allowed(Role.REVIEWER, Action.OFFLINE_EDIT, disposable_offline=True)
    assert not pc.delegation_allowed(Role.BUILDER, Action.REDACTED_READ)
    assert pc.delegation_allowed(Role.BUILDER, Action.REDACTED_READ, supplied_redacted=True)


@pytest.mark.parametrize('role,action,kwargs', [
    ('builder', Action.REPORT, {}), (Role.BUILDER, 'report-findings', {}),
    (None, None, {}), (Role.BUILDER, Action.REPORT, {'supplied_redacted': 1}),
    (Role.BUILDER, Action.REPORT, {'disposable_offline': 'yes'}),
])
def test_untyped_delegation_fails_closed(role: object, action: object,
                                       kwargs: dict[str, object]) -> None:
    assert not pc.delegation_allowed(
        cast(Role, role), cast(Action, action),
        supplied_redacted=cast(bool, kwargs.get('supplied_redacted', False)),
        disposable_offline=cast(bool, kwargs.get('disposable_offline', False)),
    )


def test_memory_and_routes_are_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        setattr(pc.MEMORY, 'rules', ())
    with pytest.raises(FrozenInstanceError):
        setattr(CANDIDATE, 'owner', 'builder')
    with pytest.raises(FrozenInstanceError):
        setattr(pc.plan_milestone(CANDIDATE), 'execution_authority', True)
    assert len(pc.MEMORY.ambition) == 4


def test_imported_module_has_no_execution_dependencies() -> None:
    # Static boundary regression: the conductor may import only stdlib policy
    # helpers and the pre-existing inert role module, never tools or SDKs.
    import ast
    from pathlib import Path
    tree = ast.parse(Path(pc.__file__).read_text(encoding='utf-8'))
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert modules <= {'__future__', 'dataclasses', 'enum', 'programme_agent_team'}
    assert imports <= {'re'}
