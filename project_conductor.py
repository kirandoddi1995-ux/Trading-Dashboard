"""Pure project front door: immutable memory, role delegation and evidence gates.

No I/O, LLM, API, scheduler, installed configuration or execution authority.
Receipts are supplied attestations, NOT authenticated or independently inspected
proofs. Prompts and this contract are not a sandbox. Missing proofs stay missing.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

from programme_agent_team import (
    Action, Contract, Role, contract, proposal_allowed, review_is_independent,
)


@dataclass(frozen=True)
class ProjectMemory:
    ambition: tuple[str, ...]
    rules: tuple[str, ...]
    agreement: str = 'PROJECT_WORKING_AGREEMENT.md'
    radar: str = 'TECHNOLOGY_RADAR_2026-10-15.md'


MEMORY = ProjectMemory(
    ambition=('trusted daily dataset and single go/no-go',
              'independent encrypted custody and demonstrated restore',
              'frozen prospective paper study', 'ML only after prior gates'),
    rules=('scout primary best practice before every milestone; adopt/adapt/defer/reject',
           'zero incremental monetary cost; no installs or accounts now',
           'source pins and fresh clock evidence; no catch-up or same-slot retry',
           'missing observations and proofs always remain missing',
           'runtime roles use only supplied redacted monitoring/reporting evidence',
           'no real capture, credential reads, trading or sealed 2025/2026 access',
           'no permissions changes or hosted writes without owner authorization',
           'owner authorization never expands these agent contracts',
           'frozen twenty-file continuity package is outside this sidecar',
           'no self-approval; exact-candidate Windows and Linux evidence required'),
)


class Stage(str, Enum):
    RADAR = 'technology-radar'
    BUILD = 'builder'
    REVIEW = 'independent-reviewer'
    WINDOWS = 'windows-verifier'
    LINUX = 'linux-verifier'
    OWNER = 'owner-commission'


ORDER = tuple(Stage)
DELEGATES = (None, Role.BUILDER, Role.REVIEWER, Role.VERIFIER, Role.VERIFIER, None)


@dataclass(frozen=True)
class Candidate:
    milestone: str
    sha256: str  # digest of the frozen candidate closure, not a mutable path
    source_pin: str  # exact public source revision
    owner: str


@dataclass(frozen=True)
class ScoutChoice:
    technology: str
    decision: str  # adopt, adapt, defer or reject
    primary_url: str
    rationale: str
    incremental_cost: int = 0  # integer monetary units; unknown cost is invalid


@dataclass(frozen=True)
class Verification:
    platform: str  # windows or linux
    runner: str  # hosted-windows or hosted-ubuntu; local passes stay local
    command: str
    environment: tuple[str, ...]  # Python/dependency versions, including none
    collection_sha256: str  # digest of canonical sorted collected test IDs
    collected: int
    passed: int
    failed: int
    skipped: int
    skip_reasons: tuple[str, ...] = ()  # one explicit reason per skipped test


@dataclass(frozen=True)
class Receipt:
    stage: Stage
    milestone: str
    candidate_sha256: str
    source_pin: str
    actor: str  # canonical principal ID, not a role/persona label
    evidence_sha256: str  # digest of supplied redacted evidence, never opened
    passed: bool
    verified: bool  # supplied evidence classification, never inferred from passed
    choices: tuple[ScoutChoice, ...] = ()
    verification: Verification | None = None


@dataclass(frozen=True)
class Route:
    status: str
    next_stage: Stage | None
    delegate: Role | None
    missing: tuple[Stage, ...]
    reason: str
    execution_authority: bool = False


def _text(value: object) -> bool:
    return type(value) is str and bool(value.strip()) and value == value.strip()


def _identity(value: object) -> bool:
    # Lower-case canonical IDs prevent whitespace/case aliases from self-approval.
    return type(value) is str and re.fullmatch(r'[a-z0-9][a-z0-9_.@-]{0,127}', value) is not None


def _sha(value: object) -> bool:
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def _pin(value: object) -> bool:
    return type(value) is str and re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', value) is not None


def _scouted(choices: object) -> bool:
    if type(choices) is not tuple or not choices:
        return False
    for choice in choices:
        if type(choice) is not ScoutChoice:
            return False
        if (not _text(choice.technology) or not _text(choice.rationale)
                or type(choice.decision) is not str
                or choice.decision not in {'adopt', 'adapt', 'defer', 'reject'}
                or type(choice.primary_url) is not str
                or re.fullmatch(r'https://[A-Za-z0-9.-]+/[^\s]*', choice.primary_url) is None
                or type(choice.incremental_cost) is not int or choice.incremental_cost != 0):
            return False
    # URL syntax cannot establish authorship: the independent reviewer must do so.
    return len({c.technology.casefold() for c in choices}) == len(choices)


def _verified_run(proof: object, stage: Stage) -> bool:
    if type(proof) is not Verification:
        return False
    platform, runner = ('windows', 'hosted-windows') if stage == Stage.WINDOWS else ('linux', 'hosted-ubuntu')
    if (type(proof.platform) is not str or proof.platform != platform
            or type(proof.runner) is not str or proof.runner != runner
            or not _text(proof.command) or not _sha(proof.collection_sha256)
            or type(proof.environment) is not tuple or not proof.environment
            or not all(_text(v) for v in proof.environment)
            or type(proof.skip_reasons) is not tuple
            or not all(_text(v) for v in proof.skip_reasons)):
        return False
    counts = (proof.collected, proof.passed, proof.failed, proof.skipped)
    return (all(type(v) is int and v >= 0 for v in counts)
            and proof.collected > 0 and proof.passed > 0 and proof.failed == 0
            and proof.passed + proof.skipped == proof.collected
            and len(proof.skip_reasons) == proof.skipped)


def plan_milestone(candidate: Candidate, receipts: tuple[Receipt, ...] = ()) -> Route:
    """Route the first unproved stage; reject unordered, stale or malformed input.

    All evidence must bind to this milestone, closure digest and source revision.
    A changed candidate starts again at radar. Completion describes supplied
    contracts only; it never enables capture, changes hosted state or approves a
    trade. Principal identity and proof authenticity require external enforcement.
    """
    def blocked(reason: str, count: int = 0) -> Route:
        return Route('BLOCKED', None, None, ORDER[count:], reason)

    if (type(candidate) is not Candidate or not _text(candidate.milestone)
            or not _sha(candidate.sha256) or not _pin(candidate.source_pin)
            or not _identity(candidate.owner)):
        return blocked('INVALID_CANDIDATE')
    if type(receipts) is not tuple or len(receipts) > len(ORDER):
        return blocked('INVALID_RECEIPTS')
    accepted: list[Receipt] = []
    for index, receipt in enumerate(receipts):
        if type(receipt) is not Receipt or type(receipt.stage) is not Stage:
            return blocked('INVALID_RECEIPT', index)
        if receipt.stage != ORDER[index]:
            return blocked('STAGE_ORDER', index)
        if (type(receipt.milestone) is not str or receipt.milestone != candidate.milestone
                or not _sha(receipt.candidate_sha256) or receipt.candidate_sha256 != candidate.sha256
                or not _pin(receipt.source_pin) or receipt.source_pin != candidate.source_pin):
            return blocked('SOURCE_OR_MILESTONE_MISMATCH', index)
        if not _identity(receipt.actor) or not _sha(receipt.evidence_sha256):
            return blocked('MISSING_PROOF_OR_IDENTITY', index)
        if receipt.passed is not True or receipt.verified is not True:
            return blocked('FAILED_OR_UNVERIFIED_PROOF', index)
        if type(receipt.choices) is not tuple:
            return blocked('INVALID_SCOUT_CHOICES', index)
        if receipt.stage != Stage.RADAR and receipt.choices:
            return blocked('UNEXPECTED_SCOUT_CHOICES', index)
        if receipt.stage not in {Stage.WINDOWS, Stage.LINUX} and receipt.verification is not None:
            return blocked('UNEXPECTED_PLATFORM_PROOF', index)
        if receipt.stage == Stage.RADAR and not _scouted(receipt.choices):
            return blocked('RADAR_REQUIRED_ZERO_COST_CHOICES', index)
        if receipt.stage != Stage.OWNER and receipt.actor == candidate.owner:
            return blocked('OWNER_CANNOT_APPROVE_OWN_WORK', index)
        if receipt.stage == Stage.REVIEW and not review_is_independent(
                accepted[1].actor, receipt.actor, reviewed_sha256=receipt.candidate_sha256,
                built_sha256=accepted[1].candidate_sha256):
            return blocked('SELF_REVIEW', index)
        if receipt.stage in {Stage.WINDOWS, Stage.LINUX}:
            if receipt.actor in {accepted[1].actor, accepted[2].actor}:
                return blocked('VERIFIER_NOT_INDEPENDENT', index)
            if not _verified_run(receipt.verification, receipt.stage):
                return blocked('PLATFORM_PROOF_REQUIRED', index)
            if receipt.stage == Stage.LINUX:
                windows = accepted[3].verification
                linux = receipt.verification
                assert windows is not None and linux is not None
                if (windows.collection_sha256 != linux.collection_sha256
                        or windows.collected != linux.collected):
                    return blocked('PLATFORM_COLLECTION_MISMATCH', index)
        if receipt.stage == Stage.OWNER:
            if receipt.actor != candidate.owner or receipt.actor in {r.actor for r in accepted}:
                return blocked('OWNER_COMMISSION_REQUIRED', index)
        accepted.append(receipt)
    if len(accepted) == len(ORDER):
        return Route('CONTRACT_COMPLETE', None, None, (), 'SUPPLIED_PROOFS_ONLY_NOT_LIVE_AUTHORITY')
    index = len(accepted)
    return Route('PENDING', ORDER[index], DELEGATES[index], ORDER[index:], 'MISSING_PROOFS_STAY_MISSING')


def delegate(role: Role) -> Contract:
    """Return the existing role specification, without installing or invoking it."""
    return contract(role)


def delegation_allowed(role: Role, action: Action, *, supplied_redacted: bool = False,
                       disposable_offline: bool = False) -> bool:
    """Planning predicate only; runtime reporting needs supplied redacted input."""
    if type(supplied_redacted) is not bool or type(disposable_offline) is not bool:
        return False
    if not proposal_allowed(role, action, disposable_offline=disposable_offline):
        return False
    if action == Action.REDACTED_READ or contract(role).runtime:
        return supplied_redacted
    return True
