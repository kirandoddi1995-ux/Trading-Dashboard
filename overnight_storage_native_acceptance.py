"""Explicit isolated native staged-method acceptance, offline preview by default.

Fixed sandbox connection from the existing verified connector. No Docker commands,
provisioning, production URLs, passfile, workflow changes or deletion. Requires
overnight_storage_native_fixture.sql provisioned separately by Main.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime, timezone
import json
from typing import Protocol, cast

import derivative_repository
import equity_scan_repository
import production_repository
import storage_native_conformance as native
import storage_write_guard as guard
from overnight_storage_contracts import ContractError, digest
from overnight_storage_factory_adapter import FactoryCoverage
from overnight_storage_staged_factories import (BorrowedConnection, LegacyCursor,
    LegacyDriver, STAGED_METHODS, invoke_staged)


class NativeRaw(guard.Connection, Protocol):
    def cursor(self) -> AbstractContextManager[LegacyCursor]: ...
    def close(self) -> None: ...


class DisposableDriver:
    """Validated local fixture; synthetic bounds remain uncommissioned."""
    synthetic_fixture = True

    def __init__(self, raw: NativeRaw, *, lose_commit_reply: bool = False) -> None:
        self.raw = raw
        self.lose_commit_reply = lose_commit_reply

    @property
    def autocommit(self) -> bool:
        return self.raw.autocommit

    @property
    def info(self) -> guard.ConnectionInfo:
        return self.raw.info

    def cursor(self) -> AbstractContextManager[LegacyCursor]:
        return self.raw.cursor()

    def commit(self) -> None:
        self.raw.commit()
        if self.lose_commit_reply:
            raise OSError('synthetic reply loss after accepted native commit')

    def rollback(self) -> None:
        self.raw.rollback()


class Scan(Protocol):
    def create_run(self, run: Mapping[str, object], items: Sequence[object]) -> object: ...


class Derivative(Protocol):
    def mark_pending(self, kind: str, trading_date: object, now: object) -> object: ...


class Production(Protocol):
    def start_run(self, mode: str) -> str: ...


def fixture_constructor(family: str, session: Callable[[], AbstractContextManager[BorrowedConnection]]) -> object:
    if family == 'equity_scan':
        return cast(Callable[[object], object], equity_scan_repository.EquityScanRepository)(session)
    if family == 'derivative':
        return cast(Callable[[object], object], derivative_repository.DerivativeRepository)(session)
    if family != 'production':
        raise ContractError('NATIVE_FACTORY_UNKNOWN')
    constructor = cast(Callable[..., object], production_repository.ProductionRepository)
    repo = constructor('postgresql://inactive.invalid/synthetic', evidence_signing_key=b'', schema_mode='validate')
    # This explicitly disposable fixture has only these method tables, NOT the
    # whole application schema. No schema discovery/migration is claimed.
    setattr(repo, '_schema_ready', True)
    setattr(repo, 'connect', session)
    return repo


def clock() -> datetime:
    return datetime.now(timezone.utc)


@contextmanager
def disposable(port: int) -> Iterator[NativeRaw]:
    if port != 55443:
        raise ContractError('NATIVE_EXACT_LOOPBACK_PORT_REQUIRED')
    raw = cast(NativeRaw, native.connect_fixture(port))
    try:
        with raw.cursor() as cursor:
            cursor.execute(native.PROFILE_SQL)
            native.validate_profile(cursor.fetchone())
            cursor.execute('SELECT marker FROM public.overnight_storage_fixture')
            if cursor.fetchone() != ('staged-three-methods-v1',):
                raise ContractError('NATIVE_STAGED_FIXTURE_MARKER_REQUIRED')
        raw.rollback()
        yield raw
    finally:
        raw.close()


def run_native(port: int) -> dict[str, object]:
    completed: list[str] = []
    with disposable(port) as raw:
        for method in STAGED_METHODS:
            family = method.factory
            driver: LegacyDriver = DisposableDriver(raw)
            def invoke(repo: object) -> object:
                if family == 'production':
                    return cast(Production, repo).start_run('overnight_storage_synthetic')
                if family == 'equity_scan':
                    return cast(Scan, repo).create_run({'id': 'overnight_storage_native', 'owner': 'synthetic',
                        'signature': 'synthetic', 'started_at': clock().timestamp()}, [])
                return cast(Derivative, repo).mark_pending('OVERNIGHT_STORAGE_NATIVE', clock().date(), clock())
            coverage = FactoryCoverage((family,), (family,), digest(b'disposable inventory'), digest(b'disposable migration'))
            _, receipt = invoke_staged(driver, method, lambda session: fixture_constructor(family, session),
                invoke, coverage=coverage, clock=clock)
            if receipt.status != 'COMMITTED' or receipt.global_enforcement_commissioned:
                raise ContractError('NATIVE_STAGED_RECEIPT_INVALID')
            completed.append(family + '_existing_method_committed')
        # Native accepted commit + missing client reply: no second automatic append.
        driver = DisposableDriver(raw, lose_commit_reply=True)
        method = STAGED_METHODS[0]
        coverage = FactoryCoverage(('production',), ('production',), digest(b'fixture'), digest(b'fixture migration'))
        try:
            invoke_staged(driver, method, lambda session: fixture_constructor('production', session),
                lambda repo: cast(Production, repo).start_run('overnight_storage_reply_loss'),
                coverage=coverage, clock=clock)
        except guard.GuardError as error:
            if str(error) != 'STORAGE_COMMIT_UNCONFIRMED_RECONCILE_DO_NOT_RETRY':
                raise
        else:
            raise ContractError('NATIVE_COMMIT_REPLY_LOSS_NOT_DETECTED')
        with raw.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM quant_app.collection_runs WHERE mode='overnight_storage_reply_loss'")
            if cursor.fetchone() != (1,):
                raise ContractError('NATIVE_COMMIT_RECONCILIATION_FAILED')
        raw.rollback()
        completed.append('accepted_native_commit_reply_loss_reconciled_without_retry')
    return {'status': 'NATIVE_STAGED_METHODS_PASSED', 'passed_cases': completed,
            'global_enforcement_commissioned': False, 'allocation_bounds_commissioned': False,
            'whole_schema_migration_verified': False, 'hosted_changes': 0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--confirm-disposable', action='store_true')
    parser.add_argument('--port', type=int, default=55443)
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({'status': 'PREVIEW', 'network_calls': 0, 'writes': 0}))
        return 0
    if not args.confirm_disposable or args.port != 55443:
        print(json.dumps({'status': 'BLOCKED', 'code': 'EXACT_DISPOSABLE_CONFIRMATION_REQUIRED'}))
        return 2
    try:
        result = run_native(args.port)
    except Exception:
        print(json.dumps({'status': 'BLOCKED', 'code': 'NATIVE_STAGED_ACCEPTANCE_FAILED', 'hosted_changes': 0}))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
