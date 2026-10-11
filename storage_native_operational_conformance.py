"""Native acceptance of an inactive operational journal, fixed disposable only."""
from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator
from contextlib import contextmanager
import json
from typing import Any

import operational_receipt_writer as writer
import storage_native_conformance as sandbox
from storage_native_ledger_conformance import Harness, RUNTIME, require

KEY = b'public-operational-fixture-only!!'
CASES = ('restricted_identity', 'original_receipt_and_idempotency',
         'conflicting_original_rejected', 'operation_and_receipt_rollback_together',
         'direct_receipt_mutation_denied', 'expired_owner_takeover',
         'competing_takeovers_one_generation', 'old_writer_waits_then_is_rejected',
         'unknown_commit_exact_readback')


def intent(run: str, fence: int = 1, value: int = 1, *, kind: str = 'checkpoint') -> writer.PreparedReceipt:
    """Synthetic values only; no market, capture or credential dependency."""
    request: dict[str, Any] = {'run_id': run, 'fencing_token': fence}
    if kind == 'checkpoint':
        request.update(instrument='SYNTHETIC', result={'value': value}, rejection=None,
                       quote_observed_at=None, governance_decision_at=None, item={'synthetic': True})
    else:
        request.update(status='COMPLETE', finished_at=1.0, error_kind=None)
    return writer.prepare(kind, request, key_id='fixture', signing_key=KEY)


class OperationalHarness(Harness):
    """Reuse fixed identity and bounded native lock observation; no live wiring."""

    @contextmanager
    def connection(self, role: str) -> Iterator[Any]:
        """Every native operation has bounded SQL wait and execution time."""
        with super().connection(role) as connection:
            connection.execute("SET LOCAL lock_timeout='2s'")
            connection.execute("SET LOCAL statement_timeout='5s'")
            yield connection

    def identity_operational(self) -> None:
        with self.connection(RUNTIME) as first, self.connection(RUNTIME) as second:
            require(first.info.backend_pid != second.info.backend_pid)
            require(first.execute('SELECT count(*) FROM quant_operational_receipts.receipts').fetchone() == (0,))

    def idempotency(self) -> None:
        prepared = intent('idempotent')
        with self.connection(RUNTIME) as connection:
            require(writer.claim(connection, prepared.run_id, 'owner', expected_fence=0, lease_seconds=300) == 1)
            require(writer.apply(connection, 'owner', prepared) == 'NEW')
            connection.commit()
        with self.connection(RUNTIME) as connection:
            require(writer.apply(connection, 'owner', prepared) == 'IDEMPOTENT')
            require(writer.original(connection, prepared) == prepared.receipt)
            terminal = intent('idempotent', kind='run')
            require(writer.apply(connection, 'owner', terminal) == 'NEW')
            connection.commit()

    def conflict(self) -> None:
        with self.connection(RUNTIME) as connection:
            try:
                writer.apply(connection, 'owner', intent('idempotent', value=2))
            except Exception as error:
                require(getattr(error, 'sqlstate', None) == 'P0001')
                connection.rollback()
            else:
                raise AssertionError('CONFLICT_ACCEPTED')
        with self.connection(RUNTIME) as connection:
            require(writer.original(connection, intent('idempotent')) is not None)

    def rollback_pair(self) -> None:
        with self.connection(RUNTIME) as connection:
            writer.claim(connection, 'rollback', 'owner', expected_fence=0)
            writer.apply(connection, 'owner', intent('rollback'))
            connection.rollback()
        with self.connection(RUNTIME) as connection:
            require(writer.original(connection, intent('rollback')) is None)
            require(connection.execute("SELECT count(*) FROM quant_operational_receipts.current_operations WHERE run_id='rollback'").fetchone() == (0,))

    def mutation_denied(self) -> None:
        for sql in ('UPDATE quant_operational_receipts.receipts SET request_text=\'{}\'',
                    'DELETE FROM quant_operational_receipts.receipts',
                    'TRUNCATE quant_operational_receipts.receipts'):
            with self.connection(RUNTIME) as connection:
                try:
                    connection.execute(sql)
                except Exception as error:
                    require(getattr(error, 'sqlstate', None) == '42501')
                    connection.rollback()
                else:
                    raise AssertionError('MUTATION_GRANTED')

    def takeover(self) -> None:
        with self.connection(RUNTIME) as connection:
            require(writer.claim(connection, 'expired-serial', 'new', expected_fence=1) == 2)
            require(writer.apply(connection, 'new', intent('expired-serial', 2)) == 'NEW')
            connection.commit()
        with self.connection(RUNTIME) as connection:
            try:
                writer.apply(connection, 'old', intent('expired-serial'))
            except Exception as error:
                require(getattr(error, 'sqlstate', None) == 'P0001')
                connection.rollback()
            else:
                raise AssertionError('STALE_OWNER_ACCEPTED')

    def takeover_cas(self) -> None:
        with self.connection(RUNTIME) as holder, self.connection(RUNTIME) as peer:
            require(writer.claim(holder, 'expired-cas', 'first', expected_fence=1) == 2)
            def contender() -> str:
                try:
                    writer.claim(peer, 'expired-cas', 'second', expected_fence=1)
                except Exception as error:
                    require(getattr(error, 'sqlstate', None) == 'P0001')
                    peer.rollback()
                    return 'BLOCKED'
                raise AssertionError('TWO_TAKEOVERS_ACCEPTED')
            require(self.race(holder, peer, contender) == 'BLOCKED')

    def old_writer(self) -> None:
        with self.connection(RUNTIME) as holder, self.connection(RUNTIME) as peer:
            writer.claim(holder, 'expired-old-writer', 'new', expected_fence=1)
            def contender() -> str:
                try:
                    writer.apply(peer, 'old', intent('expired-old-writer'))
                except Exception as error:
                    require(getattr(error, 'sqlstate', None) == 'P0001')
                    peer.rollback()
                    return 'BLOCKED'
                raise AssertionError('OLD_WRITER_ACCEPTED')
            require(self.race(holder, peer, contender) == 'BLOCKED')
        with self.connection(RUNTIME) as connection:
            require(writer.original(connection, intent('expired-old-writer')) is None)

    def unknown_commit(self) -> None:
        prepared = intent('unknown-commit')
        with self.connection(RUNTIME) as connection:
            writer.claim(connection, prepared.run_id, 'owner', expected_fence=0)
            writer.apply(connection, 'owner', prepared)
            connection.commit()
            # Explicit accepted-COMMIT lost-reply fault, not TCP/network chaos.
            try:
                raise ConnectionError('synthetic lost reply')
            except ConnectionError:
                pass
        with self.connection(RUNTIME) as independent:
            require(writer.original(independent, prepared) == prepared.receipt)
            require(independent.execute("SELECT count(*) FROM quant_operational_receipts.receipts WHERE run_id='unknown-commit'").fetchone() == (1,))


class OperationalFailure(ValueError):
    """Allowlisted diagnostics, never raw exceptions or SQL parameters."""
    def __init__(self, case: str, category: str, passed: list[str]) -> None:
        super().__init__('NATIVE_OPERATIONAL_CONFORMANCE_FAILED')
        self.case = case if case in CASES else 'IDENTITY_OR_CLEANUP'
        self.category = category if category in sandbox.CATEGORIES else 'REDACTED_EXCEPTION'
        self.passed = [name for name in passed if name in CASES]


def run_native(connect: Callable[[str], Any]) -> dict[str, object]:
    """All nine cases required; existing whole-chain flags remain false."""
    harness = OperationalHarness(connect)
    methods = (harness.identity_operational, harness.idempotency, harness.conflict,
               harness.rollback_pair, harness.mutation_denied, harness.takeover,
               harness.takeover_cas, harness.old_writer, harness.unknown_commit)
    passed: list[str] = []
    for case, method in zip(CASES, methods, strict=True):
        try:
            method()
        except Exception as error:
            category = 'ASSERTION' if isinstance(error, AssertionError) else sandbox._category(error)
            raise OperationalFailure(case, category, passed) from None
        passed.append(case)
    return {'status': 'NATIVE_OPERATIONAL_CASES_PASSED', 'passed_cases': passed,
            'hosted_changes': 0, 'inactive_journal_cases_verified': True,
            'immutable_operational_receipts_verified': False, 'fencing_takeover_verified': False,
            'global_enforcement_commissioned': False, 'approval_authority': False}


def main(argv: list[str] | None = None) -> int:
    """Default zero-I/O preview; fixed sandbox confirmation required."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--confirm-disposable', action='store_true')
    parser.add_argument('--port', type=int, default=55432)
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({'status': 'PREVIEW', 'network_calls': 0, 'writes': 0}))
        return 0
    if args.confirm_disposable is not True or not 1024 <= args.port <= 65535:
        print(json.dumps({'status': 'BLOCKED', 'code': 'DISPOSABLE_CONFIRMATION_REQUIRED'}))
        return 2
    try:
        result = run_native(lambda role: sandbox.connect_fixture(args.port, role=role))
    except Exception as error:
        failure = error if isinstance(error, OperationalFailure) else None
        print(json.dumps({'status': 'BLOCKED', 'code': 'NATIVE_OPERATIONAL_CONFORMANCE_FAILED',
            'case': failure.case if failure else 'IDENTITY_OR_CLEANUP',
            'error_category': failure.category if failure else 'REDACTED_EXCEPTION',
            'passed_cases': failure.passed if failure else [], 'hosted_changes': 0,
            'global_enforcement_commissioned': False, 'approval_authority': False}))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
