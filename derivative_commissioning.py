"""Conservative pilot admission, not a quota guarantee or trading approval."""
from __future__ import annotations

from typing import Literal
from datetime import date, datetime, timedelta, timezone

from nifty_session_calendar import cash_session

Mode = Literal["preview", "check", "pilot"]
QUOTA_BYTES = 500_000_000
RESERVE_BYTES = 20_000_000
PILOT_ALLOWANCE_BYTES = 4_000_000
DERIVATIVE_BUDGET_BYTES = 10_000_000
MAX_SOURCE_BYTES = 1_048_576
TABLES_SQL = """
WITH expected(schema_name,table_name) AS (VALUES
 ('derivatives_reference','contract_versions'), ('derivatives_reference','source_snapshots'),
 ('derivatives_reference','source_health'), ('derivatives_reference','exchange_rules'),
 ('derivatives_reference','decision_snapshots'), ('derivatives_monitor','records'),
 ('derivatives_monitor','state'), ('derivatives_monitor','positions'), ('derivatives_monitor','alerts'))
SELECT count(c.oid), COALESCE(bool_and(c.relrowsecurity),false)
FROM expected e LEFT JOIN pg_namespace n ON n.nspname=e.schema_name
LEFT JOIN pg_class c ON c.relnamespace=n.oid AND c.relname=e.table_name AND c.relkind='r'
"""

STORAGE_SQL = """
SELECT (SELECT sum(pg_database_size(datname))::bigint FROM pg_database),
       COALESCE(sum(pg_total_relation_size(c.oid)),0)::bigint
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname IN ('derivatives_reference','derivatives_monitor')
  AND c.relkind IN ('r','m')
"""


def authorised(mode: Mode, *, event: str, confirmation: str) -> bool:
    """Only an explicitly confirmed manual pilot may write; no truthy strings."""
    return mode == "pilot" and event == "workflow_dispatch" and confirmation == "true"


def assess(cluster_bytes: int, derivative_bytes: int) -> dict[str, object]:
    """Fail closed on unknown sizes; decimal bytes match the conservative policy."""
    if (type(cluster_bytes) is not int or type(derivative_bytes) is not int
            or cluster_bytes <= 0 or derivative_bytes < 0
            or derivative_bytes > cluster_bytes):
        raise ValueError("STORAGE_MEASUREMENT_INVALID")
    blockers = []
    if cluster_bytes + PILOT_ALLOWANCE_BYTES > QUOTA_BYTES - RESERVE_BYTES:
        blockers.append("CLUSTER_RESERVE_INSUFFICIENT")
    if derivative_bytes + PILOT_ALLOWANCE_BYTES > DERIVATIVE_BUDGET_BYTES:
        blockers.append("DERIVATIVE_PILOT_BUDGET_EXHAUSTED")
    return {"status": "PILOT_STORAGE_CHECK", "cluster_bytes": cluster_bytes,
            "derivative_bytes": derivative_bytes, "blockers": blockers,
            "pilot_storage_allowed": not blockers, "approval_authority": False,
            "recurring_ingestion_commissioned": False}


def validate_source(raw: bytes) -> None:
    """Bound retained pilot sources before insertion, without dropping records."""
    if not raw or len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("PILOT_SOURCE_SIZE_INVALID")


def validate_pilot_scope(trading_date: date | None, underlyings: list[str], now: datetime) -> None:
    """Require current IST date and regular reviewed session; never FO authority."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("PILOT_CLOCK_UNVERIFIED")
    today = now.astimezone(timezone(timedelta(hours=5, minutes=30))).date()
    if trading_date != today or underlyings != ["NSE_INDEX|Nifty 50"]:
        raise ValueError("PILOT_DATE_OR_SCOPE_INVALID")
    if cash_session(today)["kind"] != "REGULAR":
        raise ValueError("PILOT_SESSION_NOT_REGULAR")
