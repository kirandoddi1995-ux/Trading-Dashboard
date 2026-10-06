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

from evidence_ledger import GENESIS_HASH
from production_repository import ProductionRepository


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


def verify_isolated_target(database_url: str) -> dict:
    """Read-only post-restore verification; never accepts the production URL implicitly."""
    if not str(database_url).strip():
        raise ValueError("Explicit DR database URL is required")
    repo = ProductionRepository(database_url, schema_mode="validate", enforce_restricted_role=True)
    health = repo.health()
    if not health.get("connected"):
        return {"status": "FAILED", "health": health, "ledger_chain_verified": False}
    with repo.connect() as conn:
        broken = conn.execute("""
            WITH ordered AS (
              SELECT aggregate_id,sequence_no,previous_hash,event_hash,
                     lag(event_hash) OVER (PARTITION BY aggregate_id ORDER BY sequence_no) AS prior_hash
              FROM quant_app.evidence_ledger_events
            )
            SELECT COUNT(*) FROM ordered
            WHERE (sequence_no=1 AND previous_hash<>%s)
               OR (sequence_no>1 AND previous_hash IS DISTINCT FROM prior_hash)
        """, (GENESIS_HASH,)).fetchone()[0]
        duplicates = conn.execute("""
            SELECT COUNT(*) FROM (
              SELECT aggregate_id,sequence_no FROM quant_app.evidence_ledger_events
              GROUP BY aggregate_id,sequence_no HAVING COUNT(*)>1
            ) AS duplicate_sequences
        """).fetchone()[0]
    valid = int(broken) == 0 and int(duplicates) == 0
    return {
        "status": "PASS" if valid else "FAILED", "health": health,
        "ledger_chain_verified": valid, "broken_links": int(broken),
        "duplicate_sequences": int(duplicates),
    }


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
