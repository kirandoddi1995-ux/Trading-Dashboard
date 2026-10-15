"""Inert role contracts for offline engineering and read-only runtime reporting.

This pure policy is NOT an OS sandbox, installed agent or automatic scheduler.
No API calls, credentials, file reads, model inference or trading decisions.
Actual tool permissions must enforce the same restriction outside this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    BUILDER = 'builder'
    REVIEWER = 'independent-reviewer'
    VERIFIER = 'windows-linux-ci-verifier'
    MORNING = 'morning-ops-guide'
    AUDITOR = 'evidence-auditor'
    POSTSESSION = 'post-session-health-reporter'


class Action(str, Enum):
    PUBLIC_READ = 'read-public-source'
    REDACTED_READ = 'read-supplied-redacted-report'
    OFFLINE_EDIT = 'edit-reviewed-offline-package'
    OFFLINE_TEST = 'test-disposable-offline-fixtures'
    REPORT = 'report-findings'
    HOSTED_WRITE = 'change-hosted-resource'
    TASK_ENABLE = 'enable-capture-task'
    SECRET_READ = 'read-credentials'
    CHANGE_GATE = 'loosen-evidence-gate'
    TRADE = 'place-order-or-approve-trade'
    DELETE = 'delete-evidence'
    TRAIN = 'train-real-model'


@dataclass(frozen=True)
class Contract:
    role: Role
    allowed: frozenset[Action]
    runtime: bool
    instructions: str


COMMON = (
    'Use only the explicitly supplied public revision or redacted evidence. '
    'Separate verified, owner-reported and unknown facts. Never invent values, '
    'fills, missing slots, model results, custody or delivery. Do not inspect '
    'credentials, private captures, installed tasks, sealed historical 2025/2026 '
    'or hosted resources. Never push, enable, delete, trade, loosen a gate, '
    'train real models or change release expectations. Report blockers with '
    'public categories, hashes and counts only. Host/private read permission '
    'must be separately supplied and enforced, never inferred from this prompt.'
)
REPORTING = frozenset({Action.PUBLIC_READ, Action.REDACTED_READ, Action.REPORT})


def contract(role: Role) -> Contract:
    """Fresh immutable role specification; no environment-dependent defaults."""
    if type(role) is not Role:
        raise ValueError('TEAM_ROLE_INVALID')
    prompts = {
        Role.BUILDER: 'Implement one bounded reviewed offline package and deterministic failure tests. '
            'Preserve user changes. Hand off exact paths, source pins and pending acceptance. '
            'Do not self-certify review or merge readiness.',
        Role.REVIEWER: 'Review independently from the builder. Try to falsify invariants and '
            'source-bound claims. Return severity, exact public path and reproducible counterexample. '
            'Do not edit the patch you are reviewing or certify actual private evidence.',
        Role.VERIFIER: 'Verify the exact frozen public candidate on Windows and Linux. '
            'Record Python/dependency/Node versions, commands, counts, skip reasons and source hashes. '
            'Compare test collection totals and enforce exact-head hosted CI as owner acceptance. '
            'A local Debian pass is not an Ubuntu hosted pass.',
        Role.MORNING: 'Summarize pre-open go/no-go from supplied dated reports. '
            'A stale/missing clock, recipe, task binding, notification acceptance or deadline '
            'means NO_GO, not a repair or late retry. Explain the next owner step in plain language.',
        Role.AUDITOR: 'Check supplied verified audit summaries for generation identity, '
            'gaps, forks and independent custody scope. Missing observations stay missing; '
            'index snapshots are not derivative fills. Do not assert licence from an acknowledgment.',
        Role.POSTSESSION: 'Report recorded, raw-only and missing slots separately; '
            'distinguish local integrity, remote readback, independent encrypted custody and '
            'restore. Highlight lost runs and unknown commits; never replay or repair evidence.',
    }
    runtime = role in {Role.MORNING, Role.AUDITOR, Role.POSTSESSION}
    allowed = frozenset({Action.REDACTED_READ, Action.REPORT}) if runtime else REPORTING
    if role == Role.BUILDER:
        allowed |= frozenset({Action.OFFLINE_EDIT, Action.OFFLINE_TEST})
    elif role == Role.VERIFIER:
        allowed |= frozenset({Action.OFFLINE_TEST})
    return Contract(role, allowed, runtime,
                    COMMON + ' ' + prompts[role])


def proposal_allowed(role: Role, action: Action, *, disposable_offline: bool = False) -> bool:
    """Deny untyped/unknown operations and live operations even for a builder.

    A True result is a planning check, not authority to execute tools. Supplied
    reports must already be redacted; this policy never opens their source paths.
    """
    if type(role) is not Role or type(action) is not Action or type(disposable_offline) is not bool:
        return False
    spec = contract(role)
    if action not in spec.allowed:
        return False
    if action in {Action.OFFLINE_EDIT, Action.OFFLINE_TEST}:
        return disposable_offline and not spec.runtime
    return True


def review_is_independent(builder_identity: str, reviewer_identity: str, *,
                          reviewed_sha256: str, built_sha256: str) -> bool:
    """Prevent self-review and review of different bytes from appearing accepted."""
    import re
    values = (builder_identity, reviewer_identity, reviewed_sha256, built_sha256)
    if any(type(value) is not str for value in values):
        return False
    if (not builder_identity or not reviewer_identity or len(builder_identity) > 128
            or len(reviewer_identity) > 128 or builder_identity == reviewer_identity):
        return False
    return (re.fullmatch('[0-9a-f]{64}', reviewed_sha256) is not None
            and reviewed_sha256 == built_sha256)


def role_templates() -> dict[str, str]:
    """Render owner-review TOML strings, never write/install custom agents.

    Current official custom agents inherit parent permissions. Do not encode a
    sandbox override and imply a read-only boundary that the parent lacks.
    Models/provider/keys/budgets are deliberately not chosen or activated here.
    """
    import json
    result: dict[str, str] = {}
    for role in Role:
        spec = contract(role)
        fields = {'name': role.value,
                  'description': 'Use for ' + role.value + ': offline engineering or supplied evidence reporting only.',
                  'developer_instructions': spec.instructions}
        result[role.value + '.toml'] = '\n'.join(
            key + ' = ' + json.dumps(value, ensure_ascii=True) for key, value in fields.items()) + '\n'
    return result
