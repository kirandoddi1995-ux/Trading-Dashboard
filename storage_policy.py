"""Versioned steady-state allocation budgets and fail-closed storage admission.

Pure policy only. Writers must enforce this inside their transaction and reports
must retain signed historical measurements; importing this module changes no host.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

MB = 1_000_000
QUOTA_BYTES = 500 * MB
WARNING_BYTES = 350 * MB
PAUSE_BYTES = 400 * MB
CRITICAL_BYTES = 450 * MB
MEASUREMENT_MAX_AGE = timedelta(seconds=60)
CATALOG_ALLOWANCE_BYTES = 70 * MB


@dataclass(frozen=True)
class TableBudget:
    """Allocated heap/index/TOAST ceiling; retention is dependency-aware."""

    name: str
    allocated_bytes: int
    retention: str


def _tables(schema: str, entries: tuple[tuple[str, float, str], ...]) -> tuple[TableBudget, ...]:
    return tuple(TableBudget(f"{schema}.{name}", int(size * MB), policy)
                 for name, size, policy in entries)


BUDGETS = (
    _tables("quant_app", (
        ("archive_manifests", 2, "seal into cold catalog; bounded recent receipts"),
        ("collection_runs", 1, "completed runs 7 days; preserve active and failures"),
        ("collector_leases", .25, "current leases; bounded key cardinality"),
        ("corporate_actions", 3, "active/referenced records plus cold lookup"),
        ("data_quality_events", 1, "7 days plus referenced failures"),
        ("evidence_ledger_events", 20, "sealed prefixes; preserve hot and unresolved evidence"),
        ("execution_surveillance_events", 2, "unresolved plus 7 days"),
        ("feature_observations", 10, "active lookbacks plus cold PIT lookup"),
        ("instrument_enrichment_checks", 1, "current keys plus cold superseded records"),
        ("market_daily_volumes", 10, "required completed-session lookback plus cold PIT lookup"),
        ("market_quotes", 25, "3 days plus active references; cold exact reader"),
        ("mf_disclosures", 8, "latest per identity plus cold versions"),
        ("mf_nav", 5, "latest per scheme plus 1 day; verified cold history"),
        ("prediction_targets", 2, "active versions plus cold historical lookup"),
        ("recovery_drills", 1, "latest verified plus 7 days"),
        ("resilience_state_events", 2, "latest per control plus 7 days"),
        ("runtime_attestations", 2, "active releases plus 7 days"),
        ("scanner_observations", 25, "3 days plus unresolved references"),
        ("schema_migrations", .25, "never prune installed schema ledger"),
        ("universe_membership", 12, "current/latest complete plus hot referenced dates"),
        ("universe_membership_versions", 25, "current versions plus hot references; cold exact PIT lookup"),
        ("universe_snapshot_versions", .5, "hot headers; cold catalog retains history"),
        ("universe_snapshots", .5, "hot headers; cold catalog retains history"),
        ("validation_runs", 2, "active registry references plus cold historical lookup"),
    ))
    + _tables("equity_research", (
        ("observations", 5, "active cohort plus cold frozen reader"),
        ("outcomes", 40, "latest per active decision; superseded 7 days; completed cold reader"),
        ("source_decisions", 3, "active cohort plus cold frozen reader"),
    ))
    + _tables("equity_operations", (
        ("manual_quote_reviews", 2, "active intents plus 7 days"),
        ("order_intents", 2, "unresolved plus 7 days"),
        ("order_results", 2, "unresolved plus 7 days"),
        ("positions", 1, "all open positions; verified closed history"),
        ("scan_candidates", 8, "unacknowledged/recoverable plus 3 days"),
        ("scan_runs", 2, "active/recoverable plus 3 days"),
    ))
    + _tables("derivatives_reference", (
        ("contract_versions", 2, "active contracts and live decision dependencies"),
        ("source_snapshots", 3, "latest sources; verified referenced cold lineage"),
        ("source_health", .25, "current per source; bounded cardinality"),
        ("exchange_rules", .5, "active rules; cold historical versions"),
        ("decision_snapshots", 1.25, "unresolved plus 3 days; cold exact reader"),
    ))
    + _tables("derivatives_monitor", (
        ("records", 1, "active/retry; verified history"),
        ("state", .25, "current per monitored scope"),
        ("positions", .5, "all open; verified closed history"),
        ("alerts", 1.25, "unacknowledged/retry plus 7 days"),
    ))
    + _tables("quant_storage", (
        ("catalog_roots", .25, "two protected current roots; all old receipts in cold archive"),
        ("ledger_control", .25, "one owner-commissioned cold-reader control row; never prune"),
        ("ledger_hot_heads", 2, "protected terminal heads for hot aggregates; safely retired into cold catalog"),
    ))
)


@dataclass(frozen=True)
class Measurement:
    """Fresh complete allocation snapshot; missing/unknown tables are never hidden."""

    observed_at: datetime
    cluster_bytes: int
    relation_bytes: dict[str, int]


def assess(measurement: Measurement, now: datetime, *,
           requested_bytes: int = 0, previous: Measurement | None = None) -> dict[str, object]:
    """Classify quota, table-budget, freshness and projected-growth risk.

    Planned bytes are an admission allowance, not an allocator prediction.
    Growth is diagnostic; no negative extrapolation increases permission.
    """
    if (now.tzinfo is None or now.utcoffset() is None
            or measurement.observed_at.tzinfo is None
            or measurement.observed_at.utcoffset() is None):
        raise ValueError("STORAGE_CLOCK_UNVERIFIED")
    if (type(measurement.cluster_bytes) is not int or measurement.cluster_bytes <= 0
            or type(requested_bytes) is not int or requested_bytes < 0
            or any(type(value) is not int or value < 0 for value in measurement.relation_bytes.values())
            or sum(measurement.relation_bytes.values()) > measurement.cluster_bytes):
        raise ValueError("STORAGE_MEASUREMENT_INVALID")
    age = now - measurement.observed_at
    reasons: list[str] = []
    if age < timedelta(0) or age > MEASUREMENT_MAX_AGE:
        reasons.append("STORAGE_MEASUREMENT_STALE_OR_FUTURE")
    budgets = {item.name: item.allocated_bytes for item in BUDGETS}
    unknown = sorted(set(measurement.relation_bytes) - budgets.keys())
    missing = sorted(name for name in budgets if not name.startswith("derivatives_")
                     and name not in measurement.relation_bytes)
    derivative_names = {name for name in budgets if name.startswith("derivatives_")}
    installed_derivatives = derivative_names.intersection(measurement.relation_bytes)
    if installed_derivatives and installed_derivatives != derivative_names:
        missing.extend(sorted(derivative_names - installed_derivatives))
    exceeded = sorted(name for name, size in measurement.relation_bytes.items()
                      if name in budgets and size > budgets[name])
    if unknown:
        reasons.append("UNBUDGETED_RELATION")
    if missing:
        reasons.append("STORAGE_INVENTORY_INCOMPLETE")
    if exceeded:
        reasons.append("TABLE_BUDGET_EXCEEDED")
    other_bytes = measurement.cluster_bytes - sum(measurement.relation_bytes.values())
    if other_bytes > CATALOG_ALLOWANCE_BYTES:
        reasons.append("OTHER_CLUSTER_BUDGET_EXCEEDED")
    projected = measurement.cluster_bytes + requested_bytes
    if projected >= PAUSE_BYTES:
        reasons.append("NONESSENTIAL_WRITE_PAUSE")
    state = ("EMERGENCY" if projected >= CRITICAL_BYTES else
             "PAUSE" if projected >= PAUSE_BYTES else
             "WARNING" if projected >= WARNING_BYTES else "NORMAL")
    growth_per_day: float | None = None
    if previous is not None:
        if previous.observed_at.tzinfo is None or previous.observed_at.utcoffset() is None:
            raise ValueError("STORAGE_CLOCK_UNVERIFIED")
        seconds = (measurement.observed_at - previous.observed_at).total_seconds()
        if seconds <= 0 or type(previous.cluster_bytes) is not int or previous.cluster_bytes <= 0:
            raise ValueError("STORAGE_TREND_INVALID")
        growth_per_day = (measurement.cluster_bytes - previous.cluster_bytes) * 86400 / seconds
        if projected + max(0, growth_per_day) >= CRITICAL_BYTES:
            reasons.append("PROJECTED_RESERVE_EXHAUSTION")
    return {"state": state, "reasons": reasons, "unknown_tables": unknown, "missing_tables": missing,
            "over_budget_tables": exceeded, "cluster_bytes": measurement.cluster_bytes,
            "other_cluster_bytes": other_bytes,
            "nominal_headroom_bytes": QUOTA_BYTES - measurement.cluster_bytes,
            "growth_bytes_per_day": growth_per_day, "alert_required": bool(reasons) or state != "NORMAL",
            "nonessential_writes_allowed": not reasons,
            "critical_capacity_available": not any(
                reason == "STORAGE_MEASUREMENT_STALE_OR_FUTURE" for reason in reasons)
                and projected < QUOTA_BYTES,
            "approval_authority": False}

