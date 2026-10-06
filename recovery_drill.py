"""Guarded Supabase PITR planning and isolated-target verification.

This module never performs an in-place restore. Supabase's documented
Management API PITR endpoint restores the addressed project itself; it is not
an isolated-clone endpoint. Restore-to-new-project is therefore kept as an
explicit Dashboard operator action, followed by automated read-only checks.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from collections.abc import Callable
from contextlib import AbstractContextManager

from production_repository import ProductionRepository
from ledger_archive_repository import Connection, begin_read_snapshot
from ledger_runtime_reader import LedgerRuntimeReader
from ledger_recovery import RecoveryWitness, RecoveryCheckError, database_identity, verify_original_recovery


UTC = dt.timezone.utc


@dataclass(frozen=True)
class RecoveryPlan:
    source_project_ref: str
    dr_project_ref: str
    recovery_time_unix: int
    confirmation_token: str


def build_plan(*, source_project_ref: str, dr_project_ref: str,
               recovery_time: dt.datetime) -> RecoveryPlan:
    source, target = str(source_project_ref).strip(), str(dr_project_ref).strip()
    if not source or not target or source == target:
        raise ValueError("A distinct intended DR project identity is required")
    if recovery_time.tzinfo is None or recovery_time.utcoffset() is None:
        raise ValueError("Recovery time must be timezone-aware")
    epoch = int(recovery_time.astimezone(UTC).timestamp())
    if epoch >= int(dt.datetime.now(UTC).timestamp()):
        raise ValueError("Recovery time must be in the past")
    token = hashlib.sha256(f"{source}|{target}|{epoch}".encode()).hexdigest()[:16]
    return RecoveryPlan(source, target, epoch, token)


def request_restore(plan: RecoveryPlan, *, access_token: str, session,
                    confirmation_token: str, execute=False) -> dict:
    if not execute:
        return {"status": "PLAN_ONLY", "plan": asdict(plan), "network_write": False}
    if str(confirmation_token) != plan.confirmation_token:
        raise ValueError("Recovery confirmation token mismatch")
    # Do not call POST /v1/projects/{ref}/database/backups/restore-pitr here:
    # that is an in-place restore of {ref}, not a source-to-DR clone. Supabase
    # currently documents isolated restore-to-new-project as a Dashboard flow.
    return {
        "status": "OPERATOR_ACTION_REQUIRED",
        "plan": asdict(plan),
        "network_write": False,
        "action": (
            "In the source project's Backups page, choose Restore to a New Project, "
            "select the planned PITR timestamp, then configure DR_DATABASE_URL and run --verify"
        ),
    }


def verify_isolated_target(database_url: str, *, source_database_url: str | None = None,
                           expected: RecoveryWitness | None = None,
                           reader_factory: Callable[[Callable[[], AbstractContextManager[Connection]]],
                                                    LedgerRuntimeReader] | None = None) -> dict:
    """Verify original recovery on an explicit target, not empty-hot SQL continuity.

    The expected witness must come from a reviewed source audit. The factory must
    bind to this explicit target connection; no production reader may be reused.
    This scope is original ledger recovery, not whole-application disaster recovery.
    """
    if not str(database_url).strip():
        raise ValueError("Explicit DR database URL is required")
    failure = {'status': 'FAILED', 'ledger_chain_verified': False,
               'originals_verified': False, 'approval_authority': False,
               'application_recovery_verified': False}
    if expected is None:
        return {**failure, 'reason': 'RECOVERY_EXPECTATION_REQUIRED'}
    if not isinstance(expected, RecoveryWitness):
        return {**failure, 'reason': 'RECOVERY_EXPECTATION_INVALID'}
    if not source_database_url:
        return {**failure, 'reason': 'RECOVERY_SOURCE_IDENTITY_REQUIRED'}
    if reader_factory is None:
        return {**failure, 'reason': 'RECOVERY_READER_NOT_CONFIGURED'}
    try:
        if database_identity(database_url) == database_identity(source_database_url):
            raise RecoveryCheckError('RECOVERY_TARGET_IS_SOURCE')
        # No schema setup or privilege escalation. Read-only verification supports
        # a SELECT-only role; it does not require the app's INSERT privilege.
        repo = ProductionRepository(database_url, schema_mode="validate")
        with repo.connect() as conn:
            try:
                begin_read_snapshot(conn)
                role = conn.execute('''SELECT r.rolsuper,r.rolbypassrls,
                    EXISTS(SELECT 1 FROM pg_roles p WHERE (p.rolsuper OR p.rolbypassrls)
                      AND pg_has_role(current_user,p.oid,'MEMBER'))
                    FROM pg_roles r WHERE r.rolname=current_user''').fetchone()
                if role is None or len(role) != 3 or any(type(value) is not bool or value for value in role):
                    raise RecoveryCheckError('RECOVERY_TARGET_ROLE_UNSAFE')
            finally:
                conn.rollback()
        reader = reader_factory(repo.connect)
        if not isinstance(reader, LedgerRuntimeReader) or reader.connect != repo.connect:
            raise RecoveryCheckError('RECOVERY_READER_TARGET_MISMATCH')
        return {**verify_original_recovery(reader, expected), 'approval_authority': False,
                'application_recovery_verified': False}
    except RecoveryCheckError as exc:
        known = {'RECOVERY_TARGET_IS_SOURCE', 'RECOVERY_TARGET_ROLE_UNSAFE',
                 'RECOVERY_READER_TARGET_MISMATCH', 'RECOVERY_DATABASE_IDENTITY_INVALID',
                 'RECOVERY_EXPECTATION_INVALID', 'RECOVERY_SOURCE_EMPTY',
                 'RECOVERY_ORIGINALS_UNVERIFIED'}
        reason = str(exc)
        return {**failure, 'reason': reason if reason in known else 'RECOVERY_TARGET_UNVERIFIED'}
    except Exception:
        return {**failure, 'reason': 'RECOVERY_TARGET_UNVERIFIED'}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-project", default=os.environ.get("SUPABASE_SOURCE_PROJECT_REF"))
    parser.add_argument("--dr-project", default=os.environ.get("SUPABASE_DR_PROJECT_REF"))
    parser.add_argument("--recovery-time")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args(argv)
    if args.verify:
        result = verify_isolated_target(os.environ.get("DR_DATABASE_URL", ""))
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("status") == "PASS" else 1
    if not args.recovery_time:
        parser.error("--recovery-time is required for plan or execute")
    recovery_time = dt.datetime.fromisoformat(args.recovery_time.replace("Z", "+00:00"))
    plan = build_plan(
        source_project_ref=args.source_project, dr_project_ref=args.dr_project,
        recovery_time=recovery_time,
    )
    if not args.execute:
        print(json.dumps({"status": "PLAN_ONLY", "plan": asdict(plan)}, indent=2))
        return 0
    result = request_restore(
        plan, access_token=os.environ.get("SUPABASE_ACCESS_TOKEN", ""),
        session=None, confirmation_token=args.confirm, execute=True,
    )
    print(json.dumps(result, indent=2))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
