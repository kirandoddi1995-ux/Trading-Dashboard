"""Deterministic six-week synthetic tier rehearsal; no installed capture/data.

Two in-memory domain labels test contracts only, not physical replica custody.
No CLI, automatic run, real writer factory, hosted transport or deletion path.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import catalog_receipts as receipts
import cold_catalog as catalog
import storage_capacity_watch as watch
import storage_transition as transition
import storage_write_guard as guard
from overnight_storage_contracts import (Candidate, CatalogCut, ContractError,
    ReviewGates, SourcePolicy, capacity_runway, dedup_shadow, digest, readback, retention_plan)
from overnight_storage_factory_adapter import FactoryCoverage, guarded_candidate
from overnight_storage_journal import Journal, metadata_bytes

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
SYNTHETIC_KEY = b'offline synthetic fixture only!!!' * 2


@dataclass
class SyntheticTier:
    domain: str
    objects: dict[str, bytes] = field(default_factory=dict)
    fault: str = ''

    def read(self, sha256: str, limit: int) -> bytes | None:
        raw = self.objects.get(sha256)
        if self.fault == 'unavailable':
            raise OSError('synthetic unavailable')
        if self.fault == 'missing':
            return None
        if raw is None:
            return None
        if self.fault == 'partial':
            return raw[:-1]
        if self.fault == 'corrupt':
            return bytes([raw[0] ^ 1]) + raw[1:]
        if self.fault == 'oversize':
            return raw + b'x'
        return raw[:limit]


def restore_synthetic(raw: bytes) -> str:
    """Decoder enforces synthetic schema before deriving canonical witness."""
    try:
        value = json.loads(raw)
        if (not isinstance(value, dict) or set(value) != {'source', 'rows'}
                or value['source'] != 'synthetic_universe'
                or not isinstance(value['rows'], list) or len(value['rows']) != 3
                or any(type(v) is not int for v in value['rows'])):
            raise ValueError
        canonical = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
        return digest(b'synthetic-restored-v1:' + canonical)
    except (ValueError, TypeError, UnicodeError):
        raise ContractError('SYNTHETIC_RESTORE_INVALID') from None


@dataclass
class SyntheticInfo:
    transaction_status: int = 0


class SyntheticConnection:
    """Serial guard simulation; native transactions/races must be tested later."""
    def __init__(self, now: datetime, *, fault: str = '') -> None:
        self.now = now
        self.fault = fault
        self.autocommit = False
        self.info = SyntheticInfo()
        self.size = 300_000_000
        self.txid = '1'
        self.locked = False
        self.result: object = None
        self.commits = 0
        self.rollbacks = 0

    @contextmanager
    def cursor(self) -> Iterator[SyntheticConnection]:
        yield self

    def execute(self, query: str) -> None:
        if query == 'BEGIN':
            self.info.transaction_status = 2
        elif query == guard.LOCK_SQL:
            self.locked = self.fault != 'busy'
            self.result = (self.locked,)
        elif query == guard.MEASURE_SQL:
            self.result = (self.now, self.size, False, False)
        elif query == guard.FENCE_SQL:
            self.result = (self.txid, self.locked)

    def fetchone(self) -> object:
        return self.result

    def append(self) -> int:
        if self.fault == 'full_disk':
            raise OSError('synthetic full disk')
        self.size += 500_000
        if self.fault == 'fencing':
            self.txid = '2'
        if self.fault == 'overrun':
            self.size += 4_000_000
        return 3

    def commit(self) -> None:
        self.commits += 1
        self.info.transaction_status = 0
        self.locked = False
        if self.fault == 'commit_reply_lost':
            raise OSError('synthetic lost reply')

    def rollback(self) -> None:
        self.rollbacks += 1
        self.info.transaction_status = 0
        self.locked = False


@dataclass(frozen=True)
class HarnessResult:
    days: int
    snapshots: int
    content_versions: int
    staged: int
    blocked_plans: int
    journal_reviewed: int
    adapter_commits: int
    deletion_authority: bool = False
    globally_wired: bool = False
    physical_custody_verified: bool = False


def run_synthetic(path: Path, *, days: int = 42, fault: str = '', fault_day: int = 14) -> HarnessResult:
    """Multi-week archive/dual-read/restore/retention/journal/guard cycle.

    Live factories unchanged: every staged retention plan is migration-blocked.
    This is intentionally a disconnected isolated integration candidate.
    """
    if type(days) is not int or not 21 <= days <= 84:
        raise ContractError('HARNESS_WEEK_BOUND')
    faults = {'', 'corrupt', 'partial', 'clock', 'revision', 'full_disk', 'fencing', 'commit_reply_lost'}
    if fault not in faults or type(fault_day) is not int or not 0 <= fault_day < days:
        raise ContractError('HARNESS_FAULT_INVALID')
    journal = Journal(path, initialize=True)
    fence = journal.claim(0)
    pages: dict[str, bytes] = {}
    tiers = (SyntheticTier('synthetic_online'), SyntheticTier('synthetic_detached'))
    anchor = receipts.genesis('overnight:synthetic')
    root = catalog.EMPTY_ROOT
    contents: set[str] = set()
    staged = blocked = reviewed = commits = 0
    for day in range(days):
        now = START + timedelta(days=day, seconds=1)
        raw = metadata_bytes({'source': 'synthetic_universe', 'rows': [day // 7, 2, 3]})
        candidate = Candidate('synthetic_universe', f'snapshot_{day}', 1,
            now - timedelta(days=1), now, digest(raw), len(raw), restore_synthetic(raw))
        patch = dedup_shadow(catalog.Catalog(root, pages.get), candidate, raw)
        pages.update(patch.pages)
        signed = receipts.sign(anchor, patch.root, candidate.sha256, now, 'synthetic', SYNTHETIC_KEY)
        cut = CatalogCut(anchor, signed.anchor, signed.data)
        request = journal.stage(f'day_{day}', metadata_bytes({'candidate': candidate.metadata(),
            'generation': cut.trusted.generation, 'root': cut.trusted.root}), fence=fence)
        for tier in tiers:
            tier.objects[candidate.sha256] = raw
        if day == fault_day and fault in {'corrupt', 'partial'}:
            tiers[1].fault = fault
        contents.add(candidate.sha256)
        proof = readback(candidate, cut, {'synthetic': SYNTHETIC_KEY}, pages.get, tiers,
                         restore=restore_synthetic)
        policy = SourcePolicy(candidate.source, now, digest(b'synthetic source policy'), 4, 4 * 65536)
        revision = 2 if day == fault_day and fault == 'revision' else 1
        observed = now + timedelta(seconds=1) if day == fault_day and fault == 'clock' else now
        gates = ReviewGates(revision, observed, 0, 0, ('synthetic_writer',), (),
                            None, None, digest(b'synthetic parity'), None)
        plan = retention_plan(policy, (candidate,), (proof,), gates, cut=cut, now=now)
        if 'SOURCE_REVISION_CHANGED' in plan.blockers:
            raise ContractError('HARNESS_SOURCE_REVISION_CHANGED')
        staged += len(plan.staged)
        blocked += bool(plan.blockers)
        runway = capacity_runway(watch.Observation(now, 300_000_000 + day * 500_000),
            watch.Observation(now - timedelta(days=1), 299_500_000 + day * 500_000), (),
            schedule_sha256=digest(b'synthetic calendar'),
            capacity=transition.Capacity(now, 300_000_000 + day * 500_000, 200_000_000, 0, 24_000_000),
            allocation=transition.Allocation('synthetic_archive', 1_000_000, 2_000_000),
            per_run_upper_bound=500_000, owner_delay_days=14, runs_per_day=1, now=now)
        if runway.bounded_runs_remaining is None:
            raise ContractError('HARNESS_RUNWAY_UNPROVEN')
        journal.advance(f'day_{day}', request, fence=fence, expected_revision=0, stage='VERIFIED')
        connection = SyntheticConnection(now, fault=fault if day == fault_day else '')
        _, receipt = guarded_candidate(connection, guard.AppendBound('synthetic_writer', 500_000),
            lambda supplied: connection.append() if supplied is connection else -1,
            clock=lambda: now, coverage=FactoryCoverage(('synthetic_writer',), ('synthetic_writer',),
                digest(b'synthetic inventory'), digest(b'synthetic migration')))
        if receipt.global_enforcement_commissioned:
            raise ContractError('HARNESS_FALSE_GLOBAL_CLAIM')
        commits += connection.commits
        journal.advance(f'day_{day}', request, fence=fence, expected_revision=1, stage='REVIEWED')
        reopened = Journal(path)
        if reopened.lookup(f'day_{day}') != (request, 'REVIEWED', 2):
            raise ContractError('HARNESS_DURABLE_REPLAY_FAILED')
        reviewed += 1
        anchor, root = signed.anchor, patch.root
    return HarnessResult(days, days, len(contents), staged, blocked, reviewed, commits)
