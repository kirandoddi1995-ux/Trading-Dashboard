"""No agent, LLM, backend or tool invocation; contract matrix only."""
import pytest

from programme_agent_team import Action, Role, contract, proposal_allowed, review_is_independent, role_templates


@pytest.mark.parametrize('role', list(Role))
@pytest.mark.parametrize('action', [Action.HOSTED_WRITE, Action.TASK_ENABLE, Action.SECRET_READ,
    Action.CHANGE_GATE, Action.TRADE, Action.DELETE, Action.TRAIN])
def test_all_roles_deny_authority(role: Role, action: Action) -> None:
    assert not proposal_allowed(role, action, disposable_offline=True)


@pytest.mark.parametrize('role', [Role.MORNING, Role.AUDITOR, Role.POSTSESSION])
@pytest.mark.parametrize('action', [Action.OFFLINE_EDIT, Action.OFFLINE_TEST])
def test_runtime_agents_report_only(role: Role, action: Action) -> None:
    assert contract(role).runtime
    assert not proposal_allowed(role, action, disposable_offline=True)
    assert proposal_allowed(role, Action.REPORT)


def test_offline_roles_have_distinct_permissions() -> None:
    assert proposal_allowed(Role.BUILDER, Action.OFFLINE_EDIT, disposable_offline=True)
    assert not proposal_allowed(Role.BUILDER, Action.OFFLINE_EDIT)
    assert not proposal_allowed(Role.REVIEWER, Action.OFFLINE_EDIT, disposable_offline=True)
    assert not proposal_allowed(Role.REVIEWER, Action.OFFLINE_TEST, disposable_offline=True)
    assert proposal_allowed(Role.VERIFIER, Action.OFFLINE_TEST, disposable_offline=True)
    assert not proposal_allowed(Role.VERIFIER, Action.OFFLINE_EDIT, disposable_offline=True)


@pytest.mark.parametrize('role', list(Role))
def test_explicit_instructions(role: Role) -> None:
    spec = contract(role)
    assert spec.role == role
    assert 'Never invent' in spec.instructions and 'sealed historical' in spec.instructions
    assert proposal_allowed(role, Action.PUBLIC_READ) is (not spec.runtime)


def test_independent_review_matches_bytes() -> None:
    assert review_is_independent('builder-1', 'reviewer-2', reviewed_sha256='a'*64, built_sha256='a'*64)
    assert not review_is_independent('same', 'same', reviewed_sha256='a'*64, built_sha256='a'*64)
    assert not review_is_independent('builder', 'reviewer', reviewed_sha256='b'*64, built_sha256='a'*64)
    assert not review_is_independent('builder', 'reviewer', reviewed_sha256='invalid', built_sha256='invalid')


def test_untyped_requests_fail_closed() -> None:
    assert not proposal_allowed('builder', 'report-findings')  # type: ignore[arg-type]
    with pytest.raises(ValueError, match='TEAM_ROLE_INVALID'):
        contract('builder')  # type: ignore[arg-type]


def test_toml_templates_do_not_override_permissions_or_activate() -> None:
    import tomllib
    templates = role_templates()
    assert len(templates) == 6
    for role in Role:
        parsed = tomllib.loads(templates[role.value + '.toml'])
        assert set(parsed) == {'name', 'description', 'developer_instructions'}
        assert parsed['name'] == role.value
        assert parsed['developer_instructions'] == contract(role).instructions
